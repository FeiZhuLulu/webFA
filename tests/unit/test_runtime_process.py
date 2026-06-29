from __future__ import annotations

import pytest

from apps.runtime import process


def test_parse_runtime_url_accepts_http_url():
    assert process.parse_runtime_url("http://127.0.0.1:8787") == ("127.0.0.1", 8787)


def test_is_local_runtime_url_accepts_loopback_hosts():
    assert process.is_local_runtime_url("http://127.0.0.1:8787") is True
    assert process.is_local_runtime_url("http://localhost:8787") is True
    assert process.is_local_runtime_url("http://[::1]:8787") is True


def test_is_local_runtime_url_rejects_non_loopback_hosts():
    assert process.is_local_runtime_url("http://10.0.0.5:8787") is False
    assert process.is_local_runtime_url("https://example.com") is False


def test_parse_runtime_url_rejects_non_http_url():
    with pytest.raises(ValueError, match="runtime URL"):
        process.parse_runtime_url("stdio://webfa")


def test_runtime_health_disables_env_proxy_for_loopback(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, str]:
            return {"status": "ok"}

    def fake_get(url: str, timeout: float, **kwargs):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["trust_env"] = kwargs.get("trust_env")
        return FakeResponse()

    monkeypatch.setattr(process.httpx, "get", fake_get)

    health = process.runtime_health("http://127.0.0.1:8787")

    assert health == {"status": "ok"}
    assert captured["trust_env"] is False


def test_ensure_runtime_reuses_existing(monkeypatch):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: {"status": "ok"})

    result = process.ensure_runtime("http://127.0.0.1:8787", auto_start=False)

    assert result.reused_existing is True
    assert result.process is None


def test_ensure_runtime_without_auto_start_fails_when_unreachable(monkeypatch):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: None)

    with pytest.raises(RuntimeError, match="Runtime unreachable"):
        process.ensure_runtime("http://127.0.0.1:8787", auto_start=False)
