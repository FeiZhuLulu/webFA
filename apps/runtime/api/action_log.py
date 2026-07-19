from __future__ import annotations

import threading

from fastapi import Request

from browser.action_log import ActionLog

_ACTION_LOG_INIT_FALLBACK_LOCK = threading.RLock()


def get_action_log(request: Request) -> ActionLog:
    log = getattr(request.app.state, "visualizer_action_log", None)
    if log is not None:
        return log
    init_lock = getattr(
        request.app.state,
        "runtime_service_init_lock",
        _ACTION_LOG_INIT_FALLBACK_LOCK,
    )
    with init_lock:
        log = getattr(request.app.state, "visualizer_action_log", None)
        if log is None:
            log = ActionLog()
            request.app.state.visualizer_action_log = log
        return log
