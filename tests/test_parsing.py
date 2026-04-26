from pathlib import Path

import pytest

from x_tweet_screenshot_mcp.parsing import (
    ensure_child_path,
    extract_tweet_urls,
    normalize_tweet_url,
    parse_tweets_from_content,
    screenshot_filename,
)


def test_normalize_tweet_url():
    normalized = normalize_tweet_url("https://twitter.com/OpenAI/status/12345?s=20")
    assert normalized is not None
    assert normalized.url == "https://x.com/OpenAI/status/12345"
    assert normalized.handle == "OpenAI"
    assert normalized.status_id == "12345"


def test_extract_tweet_urls_deduplicates():
    content = """
    https://x.com/OpenAI/status/1
    https://twitter.com/OpenAI/status/1?foo=bar
    https://x.com/xai/status/2.
    """
    assert [item.url for item in extract_tweet_urls(content)] == [
        "https://x.com/OpenAI/status/1",
        "https://x.com/xai/status/2",
    ]


def test_parse_json_tweets():
    content = """```json
    {"tweets":[{"text":"OpenAI发布重要更新","url":"https://x.com/OpenAI/status/42","author_handle":"OpenAI","posted_at":"2026-04-19","importance_reason":"这是官方发布"}]}
    ```"""
    tweets = parse_tweets_from_content(content, 5)
    assert len(tweets) == 1
    assert tweets[0].text == "OpenAI发布重要更新"
    assert tweets[0].url == "https://x.com/OpenAI/status/42"
    assert tweets[0].author_handle == "OpenAI"
    assert tweets[0].importance_reason == "这是官方发布"


def test_parse_markdown_tweets():
    content = """
    1. @OpenAI posted on 2026-04-19: hello world https://x.com/OpenAI/status/42
    2. @xai posted on 2026-04-18: grok news https://twitter.com/xai/status/43
    """
    tweets = parse_tweets_from_content(content, 2)
    assert [tweet.url for tweet in tweets] == [
        "https://x.com/OpenAI/status/42",
        "https://x.com/xai/status/43",
    ]
    assert tweets[0].posted_at == "2026-04-19"


def test_screenshot_filename_is_safe():
    assert screenshot_filename("AI / X 热门?", 1, "123") == "AI_X_01_123.png"


def test_ensure_child_path_rejects_escape(tmp_path: Path):
    with pytest.raises(ValueError):
        ensure_child_path(tmp_path, "../escape.png")
