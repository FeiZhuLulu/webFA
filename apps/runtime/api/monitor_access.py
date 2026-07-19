from __future__ import annotations

import threading

from fastapi import FastAPI, Request, WebSocket

from browser.monitor_gateway import MonitorAccessManager

_MONITOR_ACCESS_INIT_FALLBACK_LOCK = threading.RLock()


def get_monitor_access_manager(source: Request | WebSocket | FastAPI) -> MonitorAccessManager:
    app = source if isinstance(source, FastAPI) else source.app
    manager = getattr(app.state, "monitor_access_manager", None)
    if manager is not None:
        return manager
    init_lock = getattr(
        app.state,
        "runtime_service_init_lock",
        _MONITOR_ACCESS_INIT_FALLBACK_LOCK,
    )
    with init_lock:
        manager = getattr(app.state, "monitor_access_manager", None)
        if manager is None:
            manager = MonitorAccessManager()
            app.state.monitor_access_manager = manager
        return manager
