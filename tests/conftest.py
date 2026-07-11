from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _enable_unsafe_legacy_browser_api_for_historical_regressions(monkeypatch):
    """Historical P4-P9 tests exercise the retired primitive BrowserAction surface.

    Production defaults keep it disabled. Individual security tests delete this
    variable before constructing the Runtime app to verify fail-closed behavior.
    """

    monkeypatch.setenv("WEBFA_ENABLE_UNSAFE_LEGACY_BROWSER_API", "1")
