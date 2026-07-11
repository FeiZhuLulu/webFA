from __future__ import annotations

from typing import Callable

from browser.driver import BrowserDriver


DriverFactory = Callable[[], BrowserDriver]


def create_default_driver_factory(driver_name: str, headless: bool) -> DriverFactory:
    if driver_name != "managed-chromium":
        raise ValueError("WEBFA_BROWSER_DRIVER must be 'managed-chromium'")

    from browser.host_driver import HostBrowserDriver
    from browser.managed_chromium_host import ManagedChromiumHost

    return lambda: HostBrowserDriver(ManagedChromiumHost(headless=headless))
