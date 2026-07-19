import pytest

from apps.runtime.main import _console_allowed_origins


def test_console_origins_include_packaged_loopback_origin(monkeypatch):
    monkeypatch.delenv("WEBFA_STRICT_CONSOLE_ORIGINS", raising=False)
    monkeypatch.setenv(
        "WEBFA_CONSOLE_ALLOWED_ORIGINS",
        "http://127.0.0.1:49152,http://localhost:49153,http://[::1]:49154",
    )

    origins = _console_allowed_origins()

    assert "http://127.0.0.1:49152" in origins
    assert "http://localhost:49153" in origins
    assert "http://[::1]:49154" in origins


@pytest.mark.parametrize(
    "origin",
    [
        "https://127.0.0.1:49152",
        "http://192.0.2.10:49152",
        "http://example.com:49152",
        "http://127.0.0.1:49152/not-an-origin",
        "http://user@127.0.0.1:49152",
    ],
)
def test_console_origins_reject_non_loopback_or_non_origin_values(monkeypatch, origin):
    monkeypatch.delenv("WEBFA_STRICT_CONSOLE_ORIGINS", raising=False)
    monkeypatch.setenv("WEBFA_CONSOLE_ALLOWED_ORIGINS", origin)

    with pytest.raises(ValueError, match="origins"):
        _console_allowed_origins()


def test_strict_console_origins_use_only_explicit_packaged_origin(monkeypatch):
    monkeypatch.setenv("WEBFA_STRICT_CONSOLE_ORIGINS", "1")
    monkeypatch.setenv("WEBFA_CONSOLE_ALLOWED_ORIGINS", "http://127.0.0.1:49152/")

    origins = _console_allowed_origins()

    assert origins == ["http://127.0.0.1:49152"]
    assert "http://127.0.0.1:8788" not in origins
    assert "http://localhost:8788" not in origins


def test_strict_console_origins_require_an_explicit_origin(monkeypatch):
    monkeypatch.setenv("WEBFA_STRICT_CONSOLE_ORIGINS", "1")
    monkeypatch.delenv("WEBFA_CONSOLE_ALLOWED_ORIGINS", raising=False)

    with pytest.raises(ValueError, match="requires at least one explicit loopback origin"):
        _console_allowed_origins()
