from __future__ import annotations

import asyncio
import os
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

SCREENSHOT_TIMEOUT_MS = 25_000
PAGE_COMMIT_TIMEOUT_MS = 12_000
NETWORK_IDLE_TIMEOUT_MS = 5_000
BODY_TEXT_TIMEOUT_MS = 3_000
SCROLL_TIMEOUT_MS = 3_000
ARTICLE_READY_TIMEOUT_MS = 12_000
RENDER_SETTLE_TIMEOUT_MS = 2_500
ARTICLE_SCREENSHOT_TIMEOUT_MS = 10_000
SCREENSHOT_CONCURRENCY = 2
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
TWEET_ARTICLE_SELECTOR = "article, [data-testid=tweet], [data-testid=post]"
TWEET_CONTENT_SELECTOR = '[data-testid="tweetText"], time, div[lang], img[src*="twimg.com/media"]'
EMBED_TWEET_SELECTOR = "article, .twitter-tweet, body"
PROXY_ENV_KEYS = ("X_SCREENSHOT_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


def prepare_output_dir(request: SearchRequest) -> Path:
    base = Path(request.output_dir).expanduser()
    if request.create_run_subdir:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = ensure_child_path(base, run_name)
    else:
        output_dir = base.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def read_dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    prefix = f"{key}="
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix) :].strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return None


def get_screenshot_proxy() -> str | None:
    for key in PROXY_ENV_KEYS:
        value = os.getenv(key) or read_dotenv_value(Path.cwd() / ".env", key)
        if value:
            proxy = value.strip()
            if "://" not in proxy:
                proxy = f"http://{proxy}"
            return proxy
    return None


async def new_browser_context(browser: Any) -> Any:
    proxy = get_screenshot_proxy()
    context_options: dict[str, Any] = {
        "viewport": {"width": 900, "height": 900},
        "device_scale_factor": 1,
        "user_agent": DESKTOP_USER_AGENT,
        "locale": "en-US",
        "timezone_id": "America/Los_Angeles",
    }
    if proxy:
        context_options["proxy"] = {"server": proxy}
    context = await browser.new_context(**context_options)
    await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return context


def tweet_status_id(url: str) -> str | None:
    normalized = normalize_tweet_url(url)
    return normalized.status_id if normalized else None


def official_embed_url(url: str) -> str | None:
    status_id = tweet_status_id(url)
    if not status_id:
        return None
    return f"https://platform.twitter.com/embed/Tweet.html?id={status_id}&theme=light&dnt=true"


async def goto_tweet_page(page: Any, url: str, timeout_ms: int, fallback_error: type[Exception]) -> str | None:
    try:
        await page.goto(url, wait_until="commit", timeout=min(timeout_ms, PAGE_COMMIT_TIMEOUT_MS))
        return None
    except fallback_error as exc:
        embed_url = official_embed_url(url)
        if not embed_url:
            raise
        await page.goto(embed_url, wait_until="commit", timeout=min(timeout_ms, PAGE_COMMIT_TIMEOUT_MS))
        return f"Captured official Twitter embed fallback because x.com did not load: {exc}"


async def wait_for_loaded_tweet_locator(page: Any, url: str, use_embed_fallback: bool = False) -> Any | None:
    if use_embed_fallback:
        try:
            await page.locator(TWEET_CONTENT_SELECTOR).first.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
        except Exception:
            pass
        fallback = page.locator(EMBED_TWEET_SELECTOR).first
        try:
            await fallback.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
            return fallback
        except Exception:
            return None

    status_id = tweet_status_id(url)

    if status_id:
        target_selector = (
            f'article:has(a[href*="/status/{status_id}"]), '
            f'[data-testid=tweet]:has(a[href*="/status/{status_id}"]), '
            f'[data-testid=post]:has(a[href*="/status/{status_id}"])'
        )
        target = page.locator(target_selector).first
        try:
            await target.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
            await target.locator(TWEET_CONTENT_SELECTOR).first.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
            return target
        except Exception:
            pass

    fallback = page.locator(TWEET_ARTICLE_SELECTOR).first
    try:
        await fallback.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
        await fallback.locator(TWEET_CONTENT_SELECTOR).first.wait_for(state="visible", timeout=ARTICLE_READY_TIMEOUT_MS)
        return fallback
    except Exception:
        return None


async def screenshot_tweet_page(page: Any, url: str, output_path: Path, timeout_ms: int = SCREENSHOT_TIMEOUT_MS) -> tuple[str, str | None]:
    try:
        from playwright.async_api import Error as PlaywrightError
        from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    except ImportError as exc:  # pragma: no cover - depends on local environment
        return "failed", f"playwright is required. Install project dependencies first: {exc}"

    try:
        fallback_warning = await goto_tweet_page(page, url, timeout_ms, PlaywrightError)
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

        locator = await wait_for_loaded_tweet_locator(page, url, use_embed_fallback=fallback_warning is not None)
        if locator is not None and await locator.count():
            try:
                await locator.scroll_into_view_if_needed(timeout=SCROLL_TIMEOUT_MS)
                # X often inserts the tweet shell before the text/media finish rendering.
                await page.wait_for_timeout(RENDER_SETTLE_TIMEOUT_MS)
                await locator.screenshot(path=str(output_path), timeout=ARTICLE_SCREENSHOT_TIMEOUT_MS)
                return "success", fallback_warning
            except PlaywrightError as exc:
                await page.screenshot(path=str(output_path), full_page=False)
                return "success", f"Article screenshot failed; saved viewport instead: {exc}"

        await page.screenshot(path=str(output_path), full_page=False)
        return "failed", "Tweet article was not found; saved viewport screenshot instead."
    except PlaywrightError as exc:
        hint = "Configure X_SCREENSHOT_PROXY if x.com is not reachable directly."
        return "failed", f"{exc}\n{hint}"


async def screenshot_tweet_url(url: str, output_path: Path, timeout_ms: int = SCREENSHOT_TIMEOUT_MS) -> tuple[str, str | None]:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on local environment
        return "failed", f"playwright is required. Install project dependencies first: {exc}"

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await new_browser_context(browser)
        page = await context.new_page()
        try:
            return await screenshot_tweet_page(page, url, output_path, timeout_ms=timeout_ms)
        finally:
            await context.close()
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
        browser = await playwright.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = await new_browser_context(browser)
        semaphore = asyncio.Semaphore(SCREENSHOT_CONCURRENCY)

        async def capture(tweet: TweetResult, url: str, output_path: Path) -> None:
            async with semaphore:
                page = None
                try:
                    page = await context.new_page()
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
            await context.close()
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
