from datetime import datetime, timezone

from apps.runtime.api.preview_cache import get_cached_preview, store_preview_cache


class _FakeState:
    def __init__(self) -> None:
        self.visualizer_preview_cache = None


class _FakeRequest:
    def __init__(self) -> None:
        self.app = type("App", (), {"state": _FakeState()})()


def test_preview_cache_returns_recent_capture():
    request = _FakeRequest()
    store_preview_cache(request, "data:image/png;base64,abc", "2026-07-03T00:00:00+00:00")

    cached = get_cached_preview(request)
    assert cached is not None
    assert cached.data_url == "data:image/png;base64,abc"
    assert cached.captured_at == "2026-07-03T00:00:00+00:00"


def test_preview_cache_expires():
    request = _FakeRequest()
    entry = store_preview_cache(request, "data:image/png;base64,abc", "2026-07-03T00:00:00+00:00")
    entry.expires_at = datetime.now(timezone.utc).timestamp() - 1

    assert get_cached_preview(request) is None