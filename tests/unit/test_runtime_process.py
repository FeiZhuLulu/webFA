from __future__ import annotations

import pytest

from apps.runtime import process


def test_parse_runtime_url_accepts_http_url():
    assert process.parse_runtime_url("http://127.0.0.1:8787") == ("127.0.0.1", 8787)


def test_parse_runtime_url_rejects_non_http_url():
    with pytest.raises(ValueError, match="runtime URL"):
        process.parse_runtime_url("stdio://webfa")


def test_ensure_runtime_reuses_existing(monkeypatch):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: {"status": "ok"})

    result = process.ensure_runtime("http://127.0.0.1:8787", auto_start=False)

    assert result.reused_existing is True
    assert result.process is None


def test_ensure_runtime_without_auto_start_fails_when_unreachable(monkeypatch):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: None)

    with pytest.raises(RuntimeError, match="Runtime unreachable"):
        process.ensure_runtime("http://127.0.0.1:8787", auto_start=False)

