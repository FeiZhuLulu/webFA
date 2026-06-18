from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from browser.driver import BrowserDriver
from browser.element_registry import ElementRegistry


DriverFactory = Callable[[], BrowserDriver]


@dataclass
class BrowserSession:
    driver_factory: DriverFactory
    session_id: str = "default"
    profile_id: str = "default"
    registry: ElementRegistry = field(default_factory=ElementRegistry)
    driver: BrowserDriver | None = None

    def ensure_driver(self) -> BrowserDriver:
        if self.driver is None:
            self.driver = self.driver_factory()
        return self.driver

    def close(self) -> None:
        if self.driver is not None:
            self.driver.close()
        self.driver = None
        self.registry.clear()
