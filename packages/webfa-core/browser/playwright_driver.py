"""Compatibility tombstone for the removed Playwright driver.

WebFA no longer ships or supports a Playwright BrowserDriver. Managed Chromium
is the only BrowserHost implementation. This module remains temporarily so an
old direct import fails with a clear migration error instead of importing a
third-party automation runtime.
"""

from __future__ import annotations


class PlaywrightBrowserDriver:
    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError(
            "PlaywrightBrowserDriver was removed in P10; use the WebFA managed-chromium BrowserHost"
        )
