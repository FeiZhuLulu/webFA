from __future__ import annotations

from fastapi import Request

from browser.action_log import ActionLog


def get_action_log(request: Request) -> ActionLog:
    log = getattr(request.app.state, "visualizer_action_log", None)
    if log is None:
        log = ActionLog()
        request.app.state.visualizer_action_log = log
    return log