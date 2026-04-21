from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .models import TweetResult


TWEET_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,15})/status(?:es)?/(\d+)(?:[/?#][^\s\])}>\"']*)?",
    re.IGNORECASE,
)
HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{1,15})")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?)\b")


@dataclass(frozen=True)
class NormalizedTweetUrl:
    url: str
    handle: str
    status_id: str


def normalize_tweet_url(url: str) -> NormalizedTweetUrl | None:
    match = TWEET_URL_RE.search(url)
    if not match:
        return None
    handle, status_id = match.group(1), match.group(2)
    return NormalizedTweetUrl(url=f"https://x.com/{handle}/status/{status_id}", handle=handle, status_id=status_id)


def extract_tweet_urls(text: str, limit: int | None = None) -> list[NormalizedTweetUrl]:
    urls: list[NormalizedTweetUrl] = []
    seen: set[str] = set()
    for match in TWEET_URL_RE.finditer(text):
        normalized = normalize_tweet_url(match.group(0))
        if not normalized or normalized.url in seen:
            continue
        urls.append(normalized)
        seen.add(normalized.url)
        if limit is not None and len(urls) >= limit:
            break
    return urls


def _load_json_object(content: str) -> dict | None:
    stripped = content.strip()
    candidates = [stripped]

    fenced = re.findall(r"```(?:json)?\s*(.*?)```", stripped, flags=re.IGNORECASE | re.DOTALL)
    candidates.extend(fenced)

    first_object = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if first_object:
        candidates.append(first_object.group(0))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _clean_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value.strip(" -*\t\r\n")


def _text_near_url(content: str, url: NormalizedTweetUrl) -> str:
    match = re.search(re.escape(url.url), content)
    if not match:
        twitter_variant = url.url.replace("https://x.com/", "https://twitter.com/")
        match = re.search(re.escape(twitter_variant), content)
    if not match:
        return ""

    line_start = content.rfind("\n", 0, match.start())
    prev_line_start = content.rfind("\n", 0, max(line_start, 0))
    start = prev_line_start + 1 if prev_line_start >= 0 else 0
    line_end = content.find("\n", match.end())
    next_line_end = content.find("\n", line_end + 1) if line_end >= 0 else -1
    end = next_line_end if next_line_end >= 0 else len(content)
    snippet = content[start:end]
    snippet = TWEET_URL_RE.sub("", snippet)
    return _clean_text(snippet)


def parse_tweets_from_content(content: str, max_results: int) -> list[TweetResult]:
    tweets: list[TweetResult] = []
    seen: set[str] = set()

    parsed = _load_json_object(content)
    raw_tweets = parsed.get("tweets") if parsed else None
    if isinstance(raw_tweets, list):
        for item in raw_tweets:
            if not isinstance(item, dict):
                continue
            url_value = str(item.get("url") or item.get("link") or "")
            normalized = normalize_tweet_url(url_value)
            if not normalized or normalized.url in seen:
                continue
            tweets.append(
                TweetResult(
                    text=_clean_text(str(item.get("text") or item.get("content") or "")),
                    url=normalized.url,
                    author_handle=(str(item.get("author_handle") or item.get("handle") or normalized.handle).lstrip("@") or None),
                    posted_at=str(item.get("posted_at") or item.get("date") or "") or None,
                )
            )
            seen.add(normalized.url)
            if len(tweets) >= max_results:
                return tweets

    for normalized in extract_tweet_urls(content, limit=max_results):
        if normalized.url in seen:
            continue
        snippet = _text_near_url(content, normalized)
        handle_match = HANDLE_RE.search(snippet)
        date_match = DATE_RE.search(snippet)
        tweets.append(
            TweetResult(
                text=snippet or normalized.url,
                url=normalized.url,
                author_handle=(handle_match.group(1) if handle_match else normalized.handle),
                posted_at=(date_match.group(1) if date_match else None),
            )
        )
        seen.add(normalized.url)
        if len(tweets) >= max_results:
            break

    return tweets


def safe_filename_part(value: str, max_length: int = 60) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = "x_search"
    return cleaned[:max_length]


def screenshot_filename(query: str, index: int, status_id: str) -> str:
    return f"{safe_filename_part(query)}_{index:02d}_{status_id}.png"


def ensure_child_path(parent: Path, child_name: str) -> Path:
    candidate = parent / child_name
    resolved_parent = parent.resolve()
    resolved_candidate = candidate.resolve()
    if resolved_parent != resolved_candidate and resolved_parent not in resolved_candidate.parents:
        raise ValueError("Resolved screenshot path escaped output directory.")
    return resolved_candidate
