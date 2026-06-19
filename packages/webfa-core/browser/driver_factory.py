from __future__ import annotations

from typing import Callable

from browser.driver import BrowserDriver


DriverFactory = Callable[[], BrowserDriver]


def create_default_driver_factory(driver_name: str, headless: bool) -> DriverFactory:
    if driver_name == "managed-chromium":
        from browser.host_driver import HostBrowserDriver
        from browser.managed_chromium_host import ManagedChromiumHost

        return lambda: HostBrowserDriver(ManagedChromiumHost(headless=headless))
    if driver_name == "playwright":
        from browser.playwright_driver import PlaywrightBrowserDriver

        return lambda: PlaywrightBrowserDriver(headless=headless)
    raise ValueError("WEBFA_BROWSER_DRIVER must be 'playwright' or 'managed-chromium'")

