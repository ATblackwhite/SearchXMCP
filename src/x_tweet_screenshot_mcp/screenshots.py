from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .models import SearchRequest, TweetResult
from .parsing import ensure_child_path, normalize_tweet_url, screenshot_filename


BLOCKED_TEXT = (
    "captcha",
    "challenge",
    "verify",
    "robot",
    "unusual activity",
    "sign in",
    "log in",
    "login",
)


def prepare_output_dir(request: SearchRequest) -> Path:
    base = Path(request.output_dir).expanduser()
    if request.create_run_subdir:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ensure_child_path(base, run_name)
    else:
        output_dir = base.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def screenshot_tweet_url(url: str, output_path: Path, timeout_ms: int = 30_000) -> tuple[str, str | None]:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local environment
        return "failed", f"playwright is required. Install project dependencies first: {exc}"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=1)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except PlaywrightTimeoutError:
                pass

            body_text = ""
            try:
                body_text = (await page.locator("body").inner_text(timeout=5_000)).lower()
            except PlaywrightError:
                pass
            if any(marker in body_text for marker in BLOCKED_TEXT) and not await page.locator("article, [data-testid=tweet]").count():
                await page.screenshot(path=str(output_path), full_page=False)
                return "failed", "X page appears to be blocked by login, verification, or CAPTCHA."

            locator = page.locator("article, [data-testid=tweet], [data-testid=post]").first
            if await locator.count():
                try:
                    await locator.scroll_into_view_if_needed(timeout=5_000)
                    await locator.screenshot(path=str(output_path), timeout=15_000)
                    return "success", None
                except PlaywrightError as exc:
                    await page.screenshot(path=str(output_path), full_page=False)
                    return "success", f"Article screenshot failed; saved viewport instead: {exc}"

            await page.screenshot(path=str(output_path), full_page=False)
            return "failed", "Tweet article was not found; saved viewport screenshot instead."
        except PlaywrightError as exc:
            return "failed", str(exc)
        finally:
            await browser.close()


async def add_screenshots(request: SearchRequest, tweets: list[TweetResult]) -> tuple[Path, list[TweetResult]]:
    output_dir = prepare_output_dir(request)

    for index, tweet in enumerate(tweets, start=1):
        normalized = normalize_tweet_url(tweet.url)
        if not normalized:
            tweet.screenshot_status = "skipped"
            tweet.error = "Invalid tweet URL."
            continue

        tweet.url = normalized.url
        if not tweet.author_handle:
            tweet.author_handle = normalized.handle

        filename = screenshot_filename(request.query, index, normalized.status_id)
        output_path = ensure_child_path(output_dir, filename)
        status, error = await screenshot_tweet_url(normalized.url, output_path)
        tweet.screenshot_path = str(output_path)
        tweet.screenshot_status = status
        tweet.error = error

    return output_dir, tweets
