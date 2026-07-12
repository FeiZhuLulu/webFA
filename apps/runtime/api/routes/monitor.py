from __future__ import annotations

import asyncio
import contextlib
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field

from apps.runtime.api.monitor_access import get_monitor_access_manager
from apps.runtime.api.routes.browser import get_browser_runtime
from apps.runtime.api.visualizer_control import require_visualizer_control
from browser.monitor_gateway import (
    MonitorAccessError,
    MonitorConnectionGrant,
    MonitorPermission,
    encode_visual_frame_packet,
    parse_stream_config,
    serialize_session_event,
)
from browser.runtime import BrowserRuntime
from browser.session_events import SessionEvent
from browser.visual_surface import VisualFrame

control_router = APIRouter(
    tags=["monitor-control"],
    dependencies=[Depends(require_visualizer_control)],
)
monitor_router = APIRouter(tags=["monitor"])


class MonitorGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(default="default", min_length=1, max_length=200)
    permissions: tuple[MonitorPermission, ...] = ("events", "frames")
    ttl_seconds: int = Field(default=300, ge=30, le=3600)


@control_router.post("/visualizer/monitor-grants")
def issue_monitor_grant(payload: MonitorGrantRequest, request: Request) -> dict[str, Any]:
    runtime = get_browser_runtime(request)
    snapshot = runtime.monitor_snapshot()
    if payload.session_id != snapshot["session_id"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "monitor_session_mismatch",
                "message": "requested Monitor session is not the active Runtime session",
            },
        )
    try:
        grant = get_monitor_access_manager(request).issue(
            session_id=payload.session_id,
            permissions=payload.permissions,
            ttl_seconds=payload.ttl_seconds,
        )
    except (ValueError, MonitorAccessError) as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": getattr(exc, "code", "invalid_monitor_grant"),
                "message": str(exc),
            },
        ) from exc
    return {
        "grant": {
            "grant_id": grant.grant_id,
            "token": grant.token,
            "session_id": grant.session_id,
            "permissions": list(grant.permissions),
            "issued_at": grant.issued_at.isoformat(),
            "expires_at": grant.expires_at.isoformat(),
        }
    }


@control_router.get("/visualizer/monitor-grants")
def list_monitor_grants(request: Request) -> dict[str, Any]:
    return {
        "grants": [
            {
                "grant_id": state.grant_id,
                "session_id": state.session_id,
                "permissions": list(state.permissions),
                "issued_at": state.issued_at.isoformat(),
                "expires_at": state.expires_at.isoformat(),
                "status": state.status,
                "connection_id": state.connection_id,
            }
            for state in get_monitor_access_manager(request).list()
        ]
    }


@control_router.delete("/visualizer/monitor-grants/{grant_id}")
def revoke_monitor_grant(grant_id: str, request: Request) -> dict[str, Any]:
    try:
        state = get_monitor_access_manager(request).revoke(grant_id)
    except MonitorAccessError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    return {
        "grant": {
            "grant_id": state.grant_id,
            "session_id": state.session_id,
            "permissions": list(state.permissions),
            "issued_at": state.issued_at.isoformat(),
            "expires_at": state.expires_at.isoformat(),
            "status": state.status,
            "connection_id": state.connection_id,
        }
    }


@monitor_router.websocket("/monitor/ws")
async def monitor_websocket(websocket: WebSocket) -> None:
    if not _monitor_origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=4403, reason="Monitor origin is not allowed")
        return

    await websocket.accept()
    runtime = _get_runtime(websocket)
    access_manager = get_monitor_access_manager(websocket)
    connection: _ConnectionBridge | None = None
    connection_grant: MonitorConnectionGrant | None = None
    subscription_id: str | None = None
    stream_id: str | None = None

    try:
        try:
            auth = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        except TimeoutError:
            await websocket.close(code=4408, reason="Monitor authentication timed out")
            return
        if not isinstance(auth, dict) or auth.get("type") != "authenticate":
            await websocket.close(code=4401, reason="Monitor authentication is required")
            return
        token = auth.get("token")
        if not isinstance(token, str):
            await websocket.close(code=4401, reason="Monitor token is required")
            return
        try:
            grant = access_manager.consume(token)
            connection_grant = grant
        except MonitorAccessError:
            await websocket.close(code=4401, reason="Monitor token is invalid or already consumed")
            return

        snapshot = await asyncio.to_thread(runtime.monitor_snapshot)
        if snapshot.get("session_id") != grant.session_id:
            await websocket.close(code=4409, reason="Monitor grant is bound to another session")
            return

        after_sequence = auth.get("after_sequence", 0)
        if not isinstance(after_sequence, int) or after_sequence < 0:
            await websocket.close(code=4400, reason="after_sequence must be a non-negative integer")
            return
        try:
            stream_config = parse_stream_config(auth.get("stream"))
        except ValueError as exc:
            await websocket.close(code=4400, reason=str(exc))
            return

        loop = asyncio.get_running_loop()
        connection = _ConnectionBridge(loop, runtime.monitor_snapshot)
        if "events" in grant.permissions:
            subscription_id = runtime.subscribe_session_events(
                connection.on_event,
                replay_after_sequence=after_sequence,
                session_id=grant.session_id,
            )

        visual_error: str | None = None
        if "frames" in grant.permissions:
            try:
                stream_id = await asyncio.to_thread(
                    runtime.start_visual_stream,
                    connection.on_frame,
                    stream_config,
                )
            except Exception:
                visual_error = "BrowserHost visual stream is unavailable"

        await websocket.send_json(
            {
                "type": "monitor_ready",
                "protocol_version": 1,
                "grant_id": grant.grant_id,
                "connection_id": grant.connection_id,
                "session_id": grant.session_id,
                "permissions": list(grant.permissions),
                "expires_at": grant.expires_at.isoformat(),
                "snapshot": snapshot,
                "visual_stream_id": stream_id,
                "visual_error": visual_error,
            }
        )

        writer = asyncio.create_task(_writer_loop(websocket, connection))
        receiver = asyncio.create_task(_receiver_loop(websocket))
        grant_watch = asyncio.create_task(
            _grant_watch_loop(websocket, access_manager, grant.grant_id, grant.expires_at)
        )
        done, pending = await asyncio.wait(
            {writer, receiver, grant_watch},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        for task in pending:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            with contextlib.suppress(WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
                await task
    except WebSocketDisconnect:
        pass
    finally:
        if connection is not None:
            connection.close()
        if subscription_id is not None:
            runtime.unsubscribe_session_events(subscription_id)
        if stream_id is not None:
            with contextlib.suppress(Exception):
                runtime.stop_visual_stream(stream_id)
        if connection_grant is not None:
            access_manager.release(connection_grant.connection_id)
        with contextlib.suppress(Exception):
            await websocket.close()


class _ConnectionBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, snapshot_provider) -> None:
        self._loop = loop
        self._snapshot_provider = snapshot_provider
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        self._frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        self._deferred: list[dict[str, object] | bytes] = []
        self._closed = False

    async def next_message(self) -> dict[str, object] | bytes:
        if self._deferred:
            return self._deferred.pop(0)
        event_task = asyncio.create_task(self._events.get())
        frame_task = asyncio.create_task(self._frames.get())
        tasks = {event_task, frame_task}
        try:
            done, pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            results = [task.result() for task in done]
            if len(results) > 1:
                self._deferred.extend(results[1:])
            return results[0]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
                if task.cancelled() or task.done():
                    continue
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def on_event(self, event: SessionEvent) -> None:
        if self._closed:
            return
        payload = serialize_session_event(event)
        self._loop.call_soon_threadsafe(self._put_event, payload)
        if event.type in {
            "navigation_committed",
            "document_changed",
            "tab_switched",
            "operation_completed",
            "operation_failed",
            "safety_decision_changed",
            "takeover_required",
            "takeover_started",
            "takeover_finished",
        }:
            try:
                snapshot = self._snapshot_provider()
            except Exception:
                return
            self._loop.call_soon_threadsafe(
                self._put_event,
                {
                    "type": "state_snapshot",
                    "cause_sequence": event.sequence,
                    "snapshot": snapshot,
                },
            )

    def on_frame(self, frame: VisualFrame) -> None:
        if self._closed:
            return
        packet = encode_visual_frame_packet(frame)
        self._loop.call_soon_threadsafe(self._put_frame, packet)

    def close(self) -> None:
        self._closed = True

    def _put_event(self, payload: dict[str, object]) -> None:
        if self._closed:
            return
        if self._events.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._events.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._events.put_nowait(payload)

    def _put_frame(self, packet: bytes) -> None:
        if self._closed:
            return
        if self._frames.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._frames.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._frames.put_nowait(packet)


async def _writer_loop(websocket: WebSocket, connection: _ConnectionBridge) -> None:
    while True:
        message = await connection.next_message()
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_json(message)


async def _receiver_loop(websocket: WebSocket) -> None:
    message = await websocket.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(message.get("code", 1000))
    # The Monitor data plane is read-only in this phase. Any application-level
    # client message after authentication ends the connection. WebSocket
    # protocol ping/pong remains handled by the transport implementation.
    await websocket.close(code=4400, reason="Monitor connection is read-only")


async def _grant_watch_loop(
    websocket: WebSocket,
    access_manager,
    grant_id: str,
    expires_at: datetime,
) -> None:
    while True:
        delay = max(0.0, (expires_at - datetime.now(timezone.utc)).total_seconds())
        if delay <= 0:
            await websocket.close(code=4408, reason="Monitor grant expired")
            return
        try:
            state = access_manager.get(grant_id)
        except MonitorAccessError:
            await websocket.close(code=4401, reason="Monitor grant is unavailable")
            return
        if state.status == "revoked":
            await websocket.close(code=4403, reason="Monitor grant was revoked")
            return
        if state.status in {"expired", "closed"}:
            await websocket.close(code=4408, reason="Monitor grant is no longer active")
            return
        await asyncio.sleep(min(0.5, delay))


def _get_runtime(websocket: WebSocket) -> BrowserRuntime:
    runtime = getattr(websocket.app.state, "browser_runtime", None)
    if runtime is None:
        runtime = BrowserRuntime()
        websocket.app.state.browser_runtime = runtime
    return runtime


def _monitor_origin_allowed(origin: str | None) -> bool:
    configured = {
        item.strip()
        for item in os.getenv("WEBFA_MONITOR_ALLOWED_ORIGINS", "").split(",")
        if item.strip()
    }
    allowed = configured or {
        "http://127.0.0.1:8788",
        "http://localhost:8788",
        "http://[::1]:8788",
        "null",
        "file://",
    }
    if origin is None:
        return "null" in allowed
    return origin in allowed
