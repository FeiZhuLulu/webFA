import pytest

from browser.config import resolve_browser_runtime_config


def test_browser_runtime_config_defaults_to_managed_chromium(monkeypatch):
    monkeypatch.delenv("WEBFA_BROWSER_DRIVER", raising=False)
    monkeypatch.delenv("WEBFA_BROWSER_HEADLESS", raising=False)

    config = resolve_browser_runtime_config()

    assert config.driver_name == "managed-chromium"
    assert config.headless is True


def test_browser_runtime_config_allows_playwright_fallback(monkeypatch):
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "playwright")
    monkeypatch.delenv("WEBFA_BROWSER_HEADLESS", raising=False)

    config = resolve_browser_runtime_config()

    assert config.driver_name == "playwright"
    assert config.headless is False


def test_browser_runtime_config_rejects_unknown_driver(monkeypatch):
    monkeypatch.setenv("WEBFA_BROWSER_DRIVER", "raw-cdp")

    with pytest.raises(ValueError, match="WEBFA_BROWSER_DRIVER"):
        resolve_browser_runtime_config()

