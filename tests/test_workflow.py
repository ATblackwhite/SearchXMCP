import asyncio
from pathlib import Path
from types import SimpleNamespace

from x_tweet_screenshot_mcp.models import SearchRequest, TweetResult
from x_tweet_screenshot_mcp.screenshots import add_screenshots, get_screenshot_proxy, screenshot_tweet_page


def test_add_screenshots_uses_best_effort(monkeypatch, tmp_path: Path):
    async def fake_capture(prepared):
        for tweet, _, output_path in prepared:
            output_path.write_bytes(b"fake png")
            tweet.screenshot_path = str(output_path)
            tweet.screenshot_status = "success"
            tweet.error = None

    monkeypatch.setattr("x_tweet_screenshot_mcp.screenshots.capture_prepared_screenshots", fake_capture)
    request = SearchRequest(query="ai", output_dir=str(tmp_path), create_run_subdir=False)
    tweets = [TweetResult(text="hello", url="https://twitter.com/OpenAI/status/123")]

    output_dir, result = asyncio.run(add_screenshots(request, tweets))

    assert output_dir == tmp_path.resolve()
    assert result[0].url == "https://x.com/OpenAI/status/123"
    assert result[0].screenshot_status == "success"
    assert result[0].screenshot_path is not None
    assert Path(result[0].screenshot_path).exists()


def test_get_screenshot_proxy_normalizes_env_value(monkeypatch):
    for key in ("X_SCREENSHOT_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("X_SCREENSHOT_PROXY", "127.0.0.1:7890")

    assert get_screenshot_proxy() == "http://127.0.0.1:7890"


def test_screenshot_tweet_page_waits_for_visible_article_and_settles(tmp_path: Path):
    class FakeLocator:
        def __init__(self):
            self.waited_for = None
            self.scrolled = False
            self.screenshot_taken = False
            self.content_waited_for = None

        async def count(self):
            return 1

        async def wait_for(self, state, timeout):
            self.waited_for = (state, timeout)

        def locator(self, query):
            return SimpleNamespace(first=FakeContentLocator(self))

        async def scroll_into_view_if_needed(self, timeout):
            self.scrolled = True

        async def screenshot(self, path, timeout):
            self.screenshot_taken = True
            Path(path).write_bytes(b"fake png")

    class FakeContentLocator:
        def __init__(self, parent):
            self.parent = parent

        async def wait_for(self, state, timeout):
            self.parent.content_waited_for = (state, timeout)

    class FakeBodyLocator:
        async def inner_text(self, timeout):
            return "tweet content"

    class FakePage:
        def __init__(self, article_locator):
            self.article_locator = article_locator
            self.waited_for_timeout_ms = None

        async def goto(self, url, wait_until, timeout):
            return None

        async def wait_for_load_state(self, state, timeout):
            return None

        def locator(self, query):
            if query == "body":
                return FakeBodyLocator()
            return SimpleNamespace(first=self.article_locator, count=self.article_locator.count)

        async def wait_for_timeout(self, timeout):
            self.waited_for_timeout_ms = timeout

        async def screenshot(self, path, full_page):
            Path(path).write_bytes(b"viewport png")

    article_locator = FakeLocator()
    page = FakePage(article_locator)
    output_path = tmp_path / "tweet.png"

    status, error = asyncio.run(
        screenshot_tweet_page(page, "https://x.com/OpenAI/status/123", output_path)
    )

    assert status == "success"
    assert error is None
    assert article_locator.waited_for is not None
    assert article_locator.waited_for[0] == "visible"
    assert article_locator.content_waited_for is not None
    assert article_locator.content_waited_for[0] == "visible"
    assert article_locator.scrolled is True
    assert page.waited_for_timeout_ms is not None
    assert article_locator.screenshot_taken is True
    assert output_path.exists()
