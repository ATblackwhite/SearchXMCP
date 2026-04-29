from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

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

SCREENSHOT_TIMEOUT_MS = 15_000
NETWORK_IDLE_TIMEOUT_MS = 3_000
BODY_TEXT_TIMEOUT_MS = 2_000
SCROLL_TIMEOUT_MS = 3_000
ARTICLE_READY_TIMEOUT_MS = 8_000
RENDER_SETTLE_TIMEOUT_MS = 1_200
ARTICLE_SCREENSHOT_TIMEOUT_MS = 8_000
SCREENSHOT_CONCURRENCY = 2


def prepare_output_dir(request: SearchRequest) -> Path:
    base = Path(request.output_dir).expanduser()
    if request.create_run_subdir:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ensure_child_path(base, run_name)
    else:
        output_dir = base.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


async def screenshot_tweet_page(page: Any, url: str, output_path: Path, timeout_ms: int = SCREENSHOT_TIMEOUT_MS) -> tuple[str, str | None]:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except ImportError as exc:  # pragma: no cover - depends on local environment
        return "failed", f"playwright is required. Install project dependencies first: {exc}"

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        try:
            await page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            pass

        body_text = ""
        try:
            body_text = (await page.locator("body").inner_text(timeout=BODY_TEXT_TIMEOUT_MS)).lower()
        except PlaywrightError:
            pass
        if any(marker in body_text for marker in BLOCKED_TEXT) and not await page.locator("article, [data-testid=tweet]").count():
            await page.screenshot(path=str(output_path), full_page=False)
            return "failed", "X page appears to be blocked by login, verification, or CAPTCHA."

        locator = page.locator("article, [data-testid=tweet], [data-testid=post]").first
        if await locator.count():
            try:
                await locator.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
                await locator.scroll_into_view_if_needed(timeout=SCROLL_TIMEOUT_MS)
                # X often inserts the tweet shell before the text/media finish rendering.
                await page.wait_for_timeout(RENDER_SETTLE_TIMEOUT_MS)
                await locator.screenshot(path=str(output_path), timeout=ARTICLE_SCREENSHOT_TIMEOUT_MS)
                return "success", None
            except PlaywrightError as exc:
                await page.screenshot(path=str(output_path), full_page=False)
                return "success", f"Article screenshot failed; saved viewport instead: {exc}"

        await page.screenshot(path=str(output_path), full_page=False)
        return "failed", "Tweet article was not found; saved viewport screenshot instead."
    except PlaywrightError as exc:
        return "failed", str(exc)


async def screenshot_tweet_url(url: str, output_path: Path, timeout_ms: int = SCREENSHOT_TIMEOUT_MS) -> tuple[str, str | None]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local environment
        return "failed", f"playwright is required. Install project dependencies first: {exc}"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=1)
        try:
            return await screenshot_tweet_page(page, url, output_path, timeout_ms=timeout_ms)
        finally:
            await browser.close()


async def capture_prepared_screenshots(prepared: list[tuple[TweetResult, str, Path]]) -> None:
    if not prepared:
        return

    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local environment
        for tweet, _, output_path in prepared:
            tweet.screenshot_path = str(output_path)
            tweet.screenshot_status = "failed"
            tweet.error = f"playwright is required. Install project dependencies first: {exc}"
        return

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        semaphore = asyncio.Semaphore(SCREENSHOT_CONCURRENCY)

        async def capture(tweet: TweetResult, url: str, output_path: Path) -> None:
            async with semaphore:
                page = None
                try:
                    page = await browser.new_page(viewport={"width": 900, "height": 900}, device_scale_factor=1)
                    status, error = await screenshot_tweet_page(page, url, output_path)
                except Exception as exc:  # pragma: no cover - defensive best-effort boundary
                    status, error = "failed", str(exc)
                finally:
                    if page is not None:
                        await page.close()
                tweet.screenshot_path = str(output_path)
                tweet.screenshot_status = status
                tweet.error = error

        try:
            await asyncio.gather(*(capture(tweet, url, output_path) for tweet, url, output_path in prepared))
        finally:
            await browser.close()


async def add_screenshots(request: SearchRequest, tweets: list[TweetResult]) -> tuple[Path, list[TweetResult]]:
    output_dir = prepare_output_dir(request)

    prepared: list[tuple[TweetResult, str, Path]] = []
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
        prepared.append((tweet, normalized.url, output_path))

    await capture_prepared_screenshots(prepared)

    return output_dir, tweets
