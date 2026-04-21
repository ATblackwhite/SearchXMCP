from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

try:
    from pydantic import field_validator, model_validator

    PYDANTIC_V2 = True
except ImportError:  # pragma: no cover - exercised in pydantic v1 environments
    from pydantic import root_validator, validator

    PYDANTIC_V2 = False


DEFAULT_MODEL = "x-ai/grok-4.1-fast"


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="X/Twitter search query.")
    output_dir: str = Field(..., min_length=1, description="Directory where screenshots are saved.")
    max_results: int = Field(5, ge=1, le=25)
    days: int = Field(1, ge=1, le=365)
    allowed_x_handles: list[str] | None = Field(default=None)
    excluded_x_handles: list[str] | None = Field(default=None)
    include_images: bool = False
    include_videos: bool = False
    create_run_subdir: bool = True

    if PYDANTIC_V2:
        @field_validator("allowed_x_handles", "excluded_x_handles")
        @classmethod
        def normalize_handles(cls, handles: list[str] | None) -> list[str] | None:
            if handles is None:
                return None
            normalized: list[str] = []
            for handle in handles:
                value = handle.strip().lstrip("@")
                if not value:
                    continue
                normalized.append(value)
            if len(normalized) > 10:
                raise ValueError("No more than 10 X handles are allowed.")
            return normalized or None

        @model_validator(mode="after")
        def validate_handle_filters(self) -> "SearchRequest":
            if self.allowed_x_handles and self.excluded_x_handles:
                raise ValueError("allowed_x_handles and excluded_x_handles cannot be used together.")
            return self
    else:
        @validator("allowed_x_handles", "excluded_x_handles", pre=True, always=True)
        def normalize_handles(cls, handles: list[str] | None) -> list[str] | None:
            if handles is None:
                return None
            normalized: list[str] = []
            for handle in handles:
                value = str(handle).strip().lstrip("@")
                if not value:
                    continue
                normalized.append(value)
            if len(normalized) > 10:
                raise ValueError("No more than 10 X handles are allowed.")
            return normalized or None

        @root_validator
        def validate_handle_filters(cls, values: dict[str, Any]) -> dict[str, Any]:
            if values.get("allowed_x_handles") and values.get("excluded_x_handles"):
                raise ValueError("allowed_x_handles and excluded_x_handles cannot be used together.")
            return values


class TweetResult(BaseModel):
    text: str
    url: str
    author_handle: str | None = None
    posted_at: str | None = None
    screenshot_path: str | None = None
    screenshot_status: Literal["pending", "success", "failed", "skipped"] = "pending"
    error: str | None = None


class SearchResponse(BaseModel):
    query: str
    model: str = DEFAULT_MODEL
    output_dir: str
    raw_grok_content: str
    tweets: list[TweetResult]
    usage: dict[str, Any] | None = None
    web_search: dict[str, Any] | None = None
