from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .models import DEFAULT_MODEL, SearchRequest

if TYPE_CHECKING:
    import httpx


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
SEARCH_ERROR_HINTS = (
    "x_search_filter",
    "openrouter:web_search",
    "plugin",
    "plugins",
    "tool",
    "tools",
    "web_search",
)


class OpenRouterError(RuntimeError):
    pass


def read_dotenv_value(path: Path, key: str) -> str | None:
    if not path.exists() or not path.is_file():
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.+?)\s*$")
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = pattern.match(line)
        if not match:
            continue
        value = match.group(1).strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        return value
    return None


def get_openrouter_api_key() -> str:
    env_key = os.getenv("OPENROUTER_API_KEY")
    if env_key:
        return env_key.strip()

    candidates = [
        Path.cwd() / ".env",
        Path.home() / ".openclaw" / "workspace" / ".env",
    ]
    for candidate in candidates:
        value = read_dotenv_value(candidate, "OPENROUTER_API_KEY")
        if value:
            return value.strip()

    raise OpenRouterError("OPENROUTER_API_KEY is not set and was not found in .env.")


def build_date_range(days: int, today: date | None = None) -> tuple[str, str]:
    end = today or date.today()
    start = end - timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def build_prompt(request: SearchRequest, from_date: str, to_date: str) -> str:
    handle_instruction = ""
    if request.allowed_x_handles:
        handle_instruction = f"Only include posts from these X handles: {', '.join(request.allowed_x_handles)}."
    elif request.excluded_x_handles:
        handle_instruction = f"Exclude posts from these X handles: {', '.join(request.excluded_x_handles)}."

    media_instruction = []
    if request.include_images:
        media_instruction.append("Use image understanding when useful.")
    if request.include_videos:
        media_instruction.append("Use video understanding when useful.")

    return "\n".join(
        line
        for line in [
            "You are an X/Twitter search assistant.",
            "Use web search to find real, current X/Twitter posts.",
            f"Search query: {request.query}",
            f"Date range: {from_date} to {to_date}.",
            f"Return up to {request.max_results} real posts.",
            handle_instruction,
            "Every result must include the exact tweet/post URL from x.com or twitter.com.",
            "Do not invent links, authors, dates, or tweet text.",
            "Prefer direct /status/ URLs. Exclude profile pages, search pages, news articles, and non-X pages.",
            "Return concise JSON if possible with this shape: {\"tweets\":[{\"text\":\"...\",\"url\":\"https://x.com/user/status/id\",\"author_handle\":\"user\",\"posted_at\":\"...\"}]}",
            "If JSON is not possible, return one numbered item per tweet with text, author, date, and direct URL.",
            " ".join(media_instruction),
        ]
        if line
    )


def build_payload(
    request: SearchRequest,
    mode: Literal["server_tool", "plugin", "prompt_only"] = "server_tool",
    model: str = DEFAULT_MODEL,
    today: date | None = None,
) -> dict[str, Any]:
    from_date, to_date = build_date_range(request.days, today)
    prompt = build_prompt(request, from_date, to_date)

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You have access to web search. Use it to find current X/Twitter posts."},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 4000,
    }

    x_search_filter: dict[str, Any] = {
        "from_date": from_date,
        "to_date": to_date,
        "enable_image_understanding": request.include_images,
        "enable_video_understanding": request.include_videos,
    }
    if request.allowed_x_handles:
        x_search_filter["allowed_x_handles"] = request.allowed_x_handles
    if request.excluded_x_handles:
        x_search_filter["excluded_x_handles"] = request.excluded_x_handles

    if mode == "server_tool":
        payload["tools"] = [
            {
                "type": "openrouter:web_search",
                "parameters": {
                    "engine": "native",
                    "max_total_results": request.max_results,
                    "x_search_filter": x_search_filter,
                },
            }
        ]
    elif mode == "plugin":
        payload["plugins"] = [
            {
                "id": "web",
                "engine": "native",
                "max_results": request.max_results,
                "x_search_filter": x_search_filter,
            }
        ]

    return payload


def should_fallback(status_code: int, body: str) -> bool:
    if status_code < 400:
        return False
    body_lower = body.lower()
    return status_code in {400, 404, 422} or any(hint.lower() in body_lower for hint in SEARCH_ERROR_HINTS)


async def post_chat_completion(
    client: Any,
    api_key: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    response = await client.post(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://openclaw.ai",
            "X-Title": "X Tweet Screenshot MCP",
        },
        json=payload,
    )
    if response.status_code >= 400:
        raise OpenRouterError(f"OpenRouter API error {response.status_code}: {response.text[:1000]}")
    return response.json()


async def search_with_openrouter(
    request: SearchRequest,
    api_key: str | None = None,
    client: Any | None = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - depends on local environment
        raise OpenRouterError("httpx is required. Install project dependencies first.") from exc

    key = api_key or get_openrouter_api_key()
    close_client = client is None
    http_client = client or httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=20.0))

    try:
        last_error: OpenRouterError | None = None
        for mode in ("server_tool", "plugin", "prompt_only"):
            payload = build_payload(request, mode=mode, model=model)
            try:
                return await post_chat_completion(http_client, key, payload)
            except OpenRouterError as exc:
                last_error = exc
                message = str(exc)
                status_match = re.search(r"OpenRouter API error (\d+):", message)
                status = int(status_match.group(1)) if status_match else 500
                if not should_fallback(status, message):
                    raise
        assert last_error is not None
        raise last_error
    finally:
        if close_client:
            await http_client.aclose()


def extract_message_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts)
    return ""


def extract_usage(response: dict[str, Any]) -> dict[str, Any] | None:
    usage = response.get("usage")
    return usage if isinstance(usage, dict) else None


def extract_web_search_metadata(response: dict[str, Any]) -> dict[str, Any] | None:
    metadata: dict[str, Any] = {}
    for key in ("web_search", "web_search_results", "annotations"):
        value = response.get(key)
        if value is not None:
            metadata[key] = value

    choices = response.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        for key in ("annotations", "web_search", "web_search_results"):
            value = message.get(key)
            if value is not None:
                metadata[f"message_{key}"] = value

    return metadata or None
