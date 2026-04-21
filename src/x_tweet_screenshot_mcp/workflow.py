from __future__ import annotations

from .models import DEFAULT_MODEL, SearchRequest, SearchResponse
from .openrouter import extract_message_content, extract_usage, extract_web_search_metadata, search_with_openrouter
from .parsing import parse_tweets_from_content
from .screenshots import add_screenshots, prepare_output_dir


async def search_x_tweets_with_screenshots_impl(request: SearchRequest) -> SearchResponse:
    response = await search_with_openrouter(request)
    content = extract_message_content(response)
    tweets = parse_tweets_from_content(content, request.max_results)

    if tweets:
        output_dir, tweets = await add_screenshots(request, tweets)
    else:
        output_dir = prepare_output_dir(request)

    return SearchResponse(
        query=request.query,
        model=DEFAULT_MODEL,
        output_dir=str(output_dir),
        raw_grok_content=content,
        tweets=tweets,
        usage=extract_usage(response),
        web_search=extract_web_search_metadata(response),
    )
