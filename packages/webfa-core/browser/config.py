from __future__ import annotations

import os
from dataclasses import dataclass


DEFAULT_BROWSER_DRIVER = "managed-chromium"
SUPPORTED_BROWSER_DRIVERS = {"managed-chromium"}
DEFAULT_AUTH_SURFACE_MODE = "electron"
SUPPORTED_AUTH_SURFACE_MODES = {"electron", "legacy"}
DEFAULT_PRIVATE_URL_POLICY = "warn"
SUPPORTED_PRIVATE_URL_POLICIES = {"allow", "warn", "block"}


@dataclass(frozen=True)
class BrowserRuntimeConfig:
    driver_name: str
    headless: bool
    auth_takeover: str
    auth_surface_mode: str
    private_url_policy: str


def resolve_browser_runtime_config(headless: bool | None = None) -> BrowserRuntimeConfig:
    driver_name = os.getenv("WEBFA_BROWSER_DRIVER", DEFAULT_BROWSER_DRIVER)
    if driver_name not in SUPPORTED_BROWSER_DRIVERS:
        supported = "', '".join(sorted(SUPPORTED_BROWSER_DRIVERS))
        raise ValueError(f"WEBFA_BROWSER_DRIVER must be '{supported}'")

    if headless is None:
        headless = _default_headless(driver_name)
    auth_takeover = os.getenv("WEBFA_AUTH_TAKEOVER", "auto").lower()
    if auth_takeover not in {"auto", "off"}:
        raise ValueError("WEBFA_AUTH_TAKEOVER must be 'auto' or 'off'")
    auth_surface_mode = os.getenv("WEBFA_AUTH_SURFACE_MODE", DEFAULT_AUTH_SURFACE_MODE).lower()
    if auth_surface_mode not in SUPPORTED_AUTH_SURFACE_MODES:
        supported = "', '".join(sorted(SUPPORTED_AUTH_SURFACE_MODES))
        raise ValueError(f"WEBFA_AUTH_SURFACE_MODE must be '{supported}'")
    private_url_policy = os.getenv("WEBFA_PRIVATE_URL_POLICY", DEFAULT_PRIVATE_URL_POLICY).lower()
    if private_url_policy not in SUPPORTED_PRIVATE_URL_POLICIES:
        supported = "', '".join(sorted(SUPPORTED_PRIVATE_URL_POLICIES))
        raise ValueError(f"WEBFA_PRIVATE_URL_POLICY must be '{supported}'")
    return BrowserRuntimeConfig(
        driver_name=driver_name,
        headless=headless,
        auth_takeover=auth_takeover,
        auth_surface_mode=auth_surface_mode,
        private_url_policy=private_url_policy,
    )


def _default_headless(driver_name: str) -> bool:
    value = os.getenv("WEBFA_BROWSER_HEADLESS")
    if value is not None:
        return value == "1"
    # P9.1: agent host stays headless; human auth uses WebFA-owned Auth Surface.
    return True
