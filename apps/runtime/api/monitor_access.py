from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket

from browser.monitor_gateway import MonitorAccessManager


def get_monitor_access_manager(source: Request | WebSocket | FastAPI) -> MonitorAccessManager:
    app = source if isinstance(source, FastAPI) else source.app
    manager = getattr(app.state, "monitor_access_manager", None)
    if manager is None:
        manager = MonitorAccessManager()
        app.state.monitor_access_manager = manager
    return manager
