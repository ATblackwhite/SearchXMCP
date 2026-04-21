from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from .models import SearchRequest
from .workflow import search_x_tweets_with_screenshots_impl


mcp = FastMCP("x-tweet-screenshot")


@mcp.tool()
async def search_x_tweets_with_screenshots(
    query: str,
    output_dir: str,
    max_results: int = 5,
    days: int = 1,
    allowed_x_handles: list[str] | None = None,
    excluded_x_handles: list[str] | None = None,
    include_images: bool = False,
    include_videos: bool = False,
    create_run_subdir: bool = True,
) -> dict[str, Any]:
    """Search X/Twitter via OpenRouter Grok, screenshot tweet pages, and return text plus screenshot paths."""
    request = SearchRequest(
        query=query,
        output_dir=output_dir,
        max_results=max_results,
        days=days,
        allowed_x_handles=allowed_x_handles,
        excluded_x_handles=excluded_x_handles,
        include_images=include_images,
        include_videos=include_videos,
        create_run_subdir=create_run_subdir,
    )
    result = await search_x_tweets_with_screenshots_impl(request)
    if hasattr(result, "model_dump"):
        return result.model_dump()
    return result.dict()


def main() -> None:
    mcp.run()
