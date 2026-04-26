from datetime import date

import pytest

from x_tweet_screenshot_mcp.models import SearchRequest
from x_tweet_screenshot_mcp.openrouter import build_date_range, build_payload, should_fallback


def test_build_date_range_single_day():
    assert build_date_range(1, today=date(2026, 4, 19)) == ("2026-04-19", "2026-04-19")


def test_build_date_range_multiple_days():
    assert build_date_range(7, today=date(2026, 4, 19)) == ("2026-04-13", "2026-04-19")


def test_build_server_tool_payload_includes_x_search_filter():
    request = SearchRequest(
        query="openai",
        output_dir="screens",
        max_results=3,
        days=2,
        allowed_x_handles=["@OpenAI"],
        include_images=True,
    )

    payload = build_payload(request, today=date(2026, 4, 19))

    tool = payload["tools"][0]
    search_filter = tool["parameters"]["x_search_filter"]
    assert payload["model"] == "x-ai/grok-4.1-fast"
    assert tool["type"] == "openrouter:web_search"
    assert tool["parameters"]["max_total_results"] == 3
    assert search_filter["from_date"] == "2026-04-18"
    assert search_filter["to_date"] == "2026-04-19"
    assert search_filter["allowed_x_handles"] == ["OpenAI"]
    assert search_filter["enable_image_understanding"] is True
    prompt = payload["messages"][1]["content"]
    assert "Simplified Chinese" in prompt
    assert "materially important within the target domain" in prompt
    assert "importance_reason" in prompt


def test_build_plugin_payload():
    request = SearchRequest(query="ai", output_dir="screens")
    payload = build_payload(request, mode="plugin", today=date(2026, 4, 19))
    assert "tools" not in payload
    assert payload["plugins"][0]["id"] == "web"
    assert payload["plugins"][0]["x_search_filter"]["from_date"] == "2026-04-19"


def test_system_message_requires_chinese_high_signal_results():
    request = SearchRequest(query="robotics", output_dir="screens")
    payload = build_payload(request, today=date(2026, 4, 19))
    system_message = payload["messages"][0]["content"]
    assert "high-importance updates" in system_message
    assert "Simplified Chinese" in system_message


def test_handle_filters_are_mutually_exclusive():
    with pytest.raises(ValueError):
        SearchRequest(
            query="ai",
            output_dir="screens",
            allowed_x_handles=["OpenAI"],
            excluded_x_handles=["xai"],
        )


def test_should_fallback_for_search_tool_errors():
    assert should_fallback(400, "unknown openrouter:web_search tool")
    assert should_fallback(422, "x_search_filter invalid")
    assert not should_fallback(401, "bad key")
