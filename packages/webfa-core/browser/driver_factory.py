from __future__ import annotations

from typing import Callable

from browser.driver import BrowserDriver
from browser.profile_storage import ProfileLaunchSpec


DriverFactory = Callable[[], BrowserDriver]


def create_default_driver_factory(
    driver_name: str,
    headless: bool,
    launch_spec: ProfileLaunchSpec | None = None,
) -> DriverFactory:
    if driver_name != "managed-chromium":
        raise ValueError("WEBFA_BROWSER_DRIVER must be 'managed-chromium'")

    from browser.host_driver import HostBrowserDriver
    from browser.managed_chromium_host import ManagedChromiumHost

    return lambda: HostBrowserDriver(
        ManagedChromiumHost(headless=headless, launch_spec=launch_spec)
    )
