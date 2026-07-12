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
from browser.human_control import HumanControlError, parse_human_input_event
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
        after_sequence = auth.get("after_sequence", 0)
        if not isinstance(after_sequence, int) or isinstance(after_sequence, bool) or after_sequence < 0:
            await websocket.close(code=4400, reason="after_sequence must be a non-negative integer")
            return
        try:
            stream_config = parse_stream_config(auth.get("stream"))
        except ValueError as exc:
            await websocket.close(code=4400, reason=str(exc))
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
        receiver = asyncio.create_task(
            _receiver_loop(
                websocket,
                runtime,
                connection,
                grant,
                human_control_available=stream_id is not None,
            )
        )
        human_sync = asyncio.create_task(
            _human_sync_loop(runtime, connection, grant)
        )
        grant_watch = asyncio.create_task(
            _grant_watch_loop(websocket, access_manager, grant.grant_id, grant.expires_at)
        )
        done, pending = await asyncio.wait(
            {writer, receiver, human_sync, grant_watch},
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
        if connection_grant is not None:
            with contextlib.suppress(Exception):
                runtime.release_human_control_connection(connection_grant.connection_id)
            access_manager.release(connection_grant.connection_id)
        if stream_id is not None:
            with contextlib.suppress(Exception):
                runtime.stop_visual_stream(stream_id)
        if subscription_id is not None:
            with contextlib.suppress(Exception):
                runtime.unsubscribe_session_events(subscription_id)
        with contextlib.suppress(Exception):
            await websocket.close()


class _ConnectionBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, snapshot_provider) -> None:
        self._loop = loop
        self._snapshot_provider = snapshot_provider
        self._controls: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=32)
        self._events: asyncio.Queue[dict[str, object]] = asyncio.Queue(maxsize=256)
        self._frames: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        self._deferred: list[dict[str, object] | bytes] = []
        self._human_control_lease_id: str | None = None
        self._closed = False

    async def next_message(self) -> dict[str, object] | bytes:
        if self._deferred:
            return self._deferred.pop(0)
        control_task = asyncio.create_task(self._controls.get())
        event_task = asyncio.create_task(self._events.get())
        frame_task = asyncio.create_task(self._frames.get())
        ordered_tasks = (control_task, event_task, frame_task)
        tasks = set(ordered_tasks)
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
            results = [task.result() for task in ordered_tasks if task in done]
            if len(results) > 1:
                self._deferred.extend(results[1:])
            return results[0]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            for task in tasks:
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

    def send_control(self, payload: dict[str, object]) -> None:
        if self._closed:
            return
        self._put_control(payload)

    def set_human_control_lease(self, lease_id: str | None) -> None:
        self._human_control_lease_id = lease_id

    def human_control_lease_id(self) -> str | None:
        return self._human_control_lease_id

    def close(self) -> None:
        self._closed = True

    def _put_control(self, payload: dict[str, object]) -> None:
        if self._closed:
            return
        if self._controls.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._controls.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self._controls.put_nowait(payload)

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


async def _receiver_loop(
    websocket: WebSocket,
    runtime: BrowserRuntime,
    connection: _ConnectionBridge,
    grant: MonitorConnectionGrant,
    *,
    human_control_available: bool,
) -> None:
    while True:
        message = await websocket.receive()
        if message.get("type") == "websocket.disconnect":
            raise WebSocketDisconnect(message.get("code", 1000))
        text = message.get("text")
        if not isinstance(text, str):
            await websocket.close(code=4400, reason="Monitor control messages must be JSON text")
            return
        try:
            import json

            payload = json.loads(text)
        except Exception:
            await websocket.close(code=4400, reason="Monitor control message is invalid JSON")
            return
        if not isinstance(payload, dict):
            await websocket.close(code=4400, reason="Monitor control message must be an object")
            return
        message_type = payload.get("type")
        if message_type == "ping":
            connection.send_control({"type": "pong"})
            continue
        if message_type not in {
            "human_control_acquire",
            "human_input",
            "human_control_release",
        }:
            await websocket.close(code=4400, reason="Unsupported Monitor control message")
            return
        if "takeover" not in grant.permissions:
            await websocket.close(code=4403, reason="Monitor grant does not allow HumanControlLease")
            return
        if message_type in {"human_control_acquire", "human_input"} and not human_control_available:
            connection.send_control(
                {
                    "type": "human_control_error",
                    "code": "human_control_visual_unavailable",
                    "message": "Human control requires an active BrowserHost visual stream",
                }
            )
            continue
        try:
            if message_type == "human_control_acquire":
                reason = payload.get("reason")
                if reason is not None and not isinstance(reason, str):
                    raise ValueError("reason must be a string")
                ttl = payload.get("ttl_seconds", 300)
                if not isinstance(ttl, int) or isinstance(ttl, bool):
                    raise ValueError("ttl_seconds must be an integer")
                remaining = max(
                    30,
                    int((grant.expires_at - datetime.now(timezone.utc)).total_seconds()),
                )
                lease = await asyncio.to_thread(
                    runtime.acquire_human_control,
                    connection_id=grant.connection_id,
                    reason=reason,
                    ttl_seconds=min(ttl, remaining, 1800),
                )
                connection.set_human_control_lease(lease.lease_id)
                connection.send_control(
                    {
                        "type": "human_control_state",
                        "active": True,
                        "lease_id": lease.lease_id,
                        "reason": lease.reason,
                        "expires_at": lease.expires_at.isoformat(),
                    }
                )
                connection.send_control(
                    {
                        "type": "state_snapshot",
                        "cause": "human_control_acquired",
                        "snapshot": await asyncio.to_thread(runtime.monitor_snapshot),
                    }
                )
                continue
            lease_id = payload.get("lease_id")
            if not isinstance(lease_id, str) or not lease_id:
                raise ValueError("lease_id is required")
            if message_type == "human_input":
                event = parse_human_input_event(payload.get("event"))
                await asyncio.to_thread(
                    runtime.send_human_input,
                    connection_id=grant.connection_id,
                    lease_id=lease_id,
                    event=event,
                )
                continue
            lease = await asyncio.to_thread(
                runtime.release_human_control,
                connection_id=grant.connection_id,
                lease_id=lease_id,
            )
            connection.set_human_control_lease(None)
            connection.send_control(
                {
                    "type": "human_control_state",
                    "active": False,
                    "lease_id": lease.lease_id,
                    "status": lease.status,
                }
            )
            connection.send_control(
                {
                    "type": "state_snapshot",
                    "cause": "human_control_released",
                    "snapshot": await asyncio.to_thread(runtime.monitor_snapshot),
                }
            )
        except (HumanControlError, ValueError) as exc:
            connection.send_control(
                {
                    "type": "human_control_error",
                    "code": getattr(exc, "code", "invalid_human_control_request"),
                    "message": str(exc),
                }
            )
        except Exception:
            connection.send_control(
                {
                    "type": "human_control_error",
                    "code": "human_control_failed",
                    "message": "Human control operation failed",
                }
            )


async def _human_sync_loop(
    runtime: BrowserRuntime,
    connection: _ConnectionBridge,
    grant: MonitorConnectionGrant,
) -> None:
    if "takeover" not in grant.permissions:
        await asyncio.Future()
        return
    previous: tuple[object, ...] | None = None
    while True:
        await asyncio.sleep(0.4)
        known_lease_id = connection.human_control_lease_id()
        lease = await asyncio.to_thread(runtime.human_control_status)
        if lease is None or lease.connection_id != grant.connection_id:
            if known_lease_id is not None:
                connection.set_human_control_lease(None)
                connection.send_control(
                    {
                        "type": "human_control_state",
                        "active": False,
                        "lease_id": known_lease_id,
                        "status": "inactive",
                    }
                )
                try:
                    snapshot = await asyncio.to_thread(runtime.monitor_snapshot)
                except Exception:
                    snapshot = None
                if snapshot is not None:
                    connection.send_control(
                        {
                            "type": "state_snapshot",
                            "cause": "human_control_inactive",
                            "snapshot": snapshot,
                        }
                    )
            previous = None
            continue
        connection.set_human_control_lease(lease.lease_id)
        try:
            snapshot = await asyncio.to_thread(
                runtime.sync_human_control_state,
                connection_id=grant.connection_id,
                lease_id=lease.lease_id,
            )
        except (HumanControlError, RuntimeError):
            continue
        fingerprint = (
            snapshot.get("tab_id"),
            snapshot.get("document_id"),
            snapshot.get("document_revision"),
            snapshot.get("url"),
            snapshot.get("takeover_required"),
        )
        if fingerprint == previous:
            continue
        previous = fingerprint
        connection.send_control(
            {
                "type": "state_snapshot",
                "cause": "human_control_sync",
                "snapshot": snapshot,
            }
        )


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
