from __future__ import annotations


class BrowserHostClosedError(RuntimeError):
    """Raised when the browser host has exited and open_url is required to restart it."""

    def __init__(self, message: str = "Browser host has exited; use open_url to restart") -> None:
        super().__init__(message)
