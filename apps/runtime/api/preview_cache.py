from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Request

PREVIEW_TTL_SECONDS = 4.0


@dataclass
class PreviewCacheEntry:
    data_url: str | None
    captured_at: str | None
    expires_at: float


def get_cached_preview(request: Request) -> PreviewCacheEntry | None:
    cache = getattr(request.app.state, "visualizer_preview_cache", None)
    if not isinstance(cache, PreviewCacheEntry):
        return None
    if cache.expires_at <= datetime.now(timezone.utc).timestamp():
        return None
    return cache


def store_preview_cache(request: Request, data_url: str | None, captured_at: str | None) -> PreviewCacheEntry:
    entry = PreviewCacheEntry(
        data_url=data_url,
        captured_at=captured_at,
        expires_at=datetime.now(timezone.utc).timestamp() + PREVIEW_TTL_SECONDS,
    )
    request.app.state.visualizer_preview_cache = entry
    return entry