import asyncio
from pathlib import Path

from x_tweet_screenshot_mcp.models import SearchRequest, TweetResult
from x_tweet_screenshot_mcp.screenshots import add_screenshots


def test_add_screenshots_uses_best_effort(monkeypatch, tmp_path: Path):
    async def fake_screenshot(url, output_path):
        output_path.write_bytes(b"fake png")
        return "success", None

    monkeypatch.setattr("x_tweet_screenshot_mcp.screenshots.screenshot_tweet_url", fake_screenshot)
    request = SearchRequest(query="ai", output_dir=str(tmp_path), create_run_subdir=False)
    tweets = [TweetResult(text="hello", url="https://twitter.com/OpenAI/status/123")]

    output_dir, result = asyncio.run(add_screenshots(request, tweets))

    assert output_dir == tmp_path.resolve()
    assert result[0].url == "https://x.com/OpenAI/status/123"
    assert result[0].screenshot_status == "success"
    assert result[0].screenshot_path is not None
    assert Path(result[0].screenshot_path).exists()
