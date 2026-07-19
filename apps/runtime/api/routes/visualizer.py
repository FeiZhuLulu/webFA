from __future__ import annotations

from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.runtime.api.action_log import get_action_log
from apps.runtime.api.preview_cache import get_cached_preview, store_preview_cache
from apps.runtime.api.visualizer_control import require_visualizer_control
from apps.runtime.api.routes.browser import get_browser_runtime
from apps.runtime.api.routes.profiles import (
    get_profile_repository,
)
from browser.local_resource_broker import LocalResourceError
from browser.managed_chromium_host import chromium_executable_status
from browser.payment_broker import PaymentInstrumentError
from browser.profile_repository import ProfileNotFoundError, ProfileRepositoryError
from browser.profile_storage import ProfileLockBusyError
from browser.runtime_errors import BrowserRuntimeError
from browser.runtime_supervisor import BrowserRuntimeSupervisor
from browser.step_up import StepUpError
from browser.exceptions import BrowserHostClosedError
from schemas.safety import (
    FinancialPolicy,
    PaymentInstrumentRef,
    ProfileOwnershipMetadata,
    ResourceOwner,
    StepUpScopeScalar,
)
from schemas.visualizer import VisualizerState
from schemas.web import WebObserveRequest

_CONTROL_DEPENDENCIES = [Depends(require_visualizer_control)]
router = APIRouter(tags=["visualizer"], dependencies=_CONTROL_DEPENDENCIES)


def _require_legacy_auth_surface() -> None:
    raise HTTPException(
        status_code=410,
        detail={
            "code": "legacy_auth_surface_disabled",
            "message": (
                "The duplicate-page AuthSurface is retired. Use the Session Monitor "
                "HumanControlLease to control the existing BrowserHost page."
            ),
        },
    )


class StepUpDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decided_by: str = Field(default="local_user", min_length=1, max_length=200)
    decision_note: str = Field(default="", max_length=1000)
    approved_scope: dict[str, StepUpScopeScalar] | None = Field(default=None, max_length=50)


class LocalResourceGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=500)
    content_base64: str = Field(min_length=1)
    owner: ResourceOwner = "user"
    purpose: str = Field(min_length=1, max_length=500)
    allowed_origins: list[str] = Field(min_length=1, max_length=100)
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    bound_profile_ids: list[str] = Field(default_factory=list, max_length=100)
    expires_in_seconds: int | None = Field(default=3600, ge=1, le=86400)
    max_uses: int = Field(default=1, ge=1, le=10000)


def _record_action(
    request: Request,
    *,
    tool: str,
    status: str = "ok",
    code: str | None = None,
    message: str = "",
    agent_id: str | None = None,
) -> None:
    get_action_log(request).record(
        tool=tool,
        status=status,
        code=code,
        message=message,
        agent_id=agent_id,
    )


def _profile_policy_http_error(
    exc: ProfileRepositoryError,
) -> HTTPException:
    status_code = 404 if isinstance(exc, ProfileNotFoundError) else 409
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


def _find_control_session_runtime(
    request: Request,
    profile_ref: str | None = None,
):
    runtime = get_browser_runtime(request)
    if isinstance(runtime, BrowserRuntimeSupervisor):
        return runtime.find_control_session_runtime(profile_ref)
    return runtime


def _ensure_control_session_runtime(
    request: Request,
    profile_ref: str | None = None,
):
    runtime = get_browser_runtime(request)
    if isinstance(runtime, BrowserRuntimeSupervisor):
        try:
            return runtime.ensure_control_session_runtime(profile_ref)
        except ProfileLockBusyError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": exc.code, "message": str(exc)},
            ) from exc
        except ProfileRepositoryError as exc:
            raise _profile_policy_http_error(exc) from exc
    return runtime


def _auth_surface_payload(request: Request, browser_state_url: str | None = None) -> dict[str, object]:
    _ = request, browser_state_url
    return {
        "active": False,
        "url": None,
        "mode": "monitor",
    }


def _takeover_surface_payload(
    request: Request,
    *,
    web_state,
    browser_status: dict,
    browser_state_url: str | None = None,
) -> dict[str, object]:
    _ = request
    web_takeover = web_state.takeover if web_state is not None else None
    active = bool(
        (web_takeover is not None and web_takeover.required)
        or browser_status.get("takeover_active")
    )
    reason = web_takeover.reason if web_takeover is not None and web_takeover.required else browser_status.get("takeover_reason")
    return {
        "active": active,
        "url": browser_status.get("takeover_url") or browser_state_url,
        "mode": "monitor",
        "reason": reason,
        "target": (web_takeover.target if web_takeover is not None else None) or browser_status.get("takeover_target"),
        "origin": (web_takeover.origin if web_takeover is not None else "") or browser_status.get("takeover_origin", ""),
    }


def build_visualizer_state(request: Request) -> VisualizerState:
    runtime = get_browser_runtime(request)
    errors: list[dict[str, str]] = []
    browser_state = None
    web_state = None
    preview_data_url: str | None = None
    preview_captured_at: str | None = None

    browser_status = runtime.status()
    executable_found = browser_status.get("executable_found")
    executable_name = browser_status.get("executable_name")
    if (
        browser_status.get("selected_driver", "managed-chromium") == "managed-chromium"
        and not isinstance(executable_found, bool)
    ):
        executable_found, executable_name = chromium_executable_status()
    supervisor_inactive = (
        isinstance(runtime, BrowserRuntimeSupervisor)
        and browser_status.get("supervisor_lifecycle") == "inactive"
    )
    if not supervisor_inactive:
        try:
            browser_state = runtime.observe()
        except BrowserHostClosedError as exc:
            errors.append({"code": "browser_host_closed", "message": str(exc)})
        except Exception as exc:
            errors.append({"code": "observe_failed", "message": str(exc)})

    raw_profile_id = browser_status.get("profile_id")
    profile_id = raw_profile_id if isinstance(raw_profile_id, str) and raw_profile_id else "default"
    if isinstance(runtime, BrowserRuntimeSupervisor):
        profile_metadata = runtime.profile_repository.get_policy(profile_id)
    else:
        profile_metadata = runtime.get_profile_policy(profile_id)
    observe_web = None if supervisor_inactive else getattr(runtime, "observe_web", None)
    if callable(observe_web) and (
        browser_status.get("takeover_active")
        or (browser_state is not None and bool(browser_state.url))
    ):
        try:
            web_state = observe_web(WebObserveRequest(mode="page", detail="summary", limit=50)).state
        except Exception as exc:
            errors.append({"code": "web_observe_failed", "message": str(exc)})

    takeover_surface = _takeover_surface_payload(
        request,
        web_state=web_state,
        browser_status=browser_status,
        browser_state_url=browser_state.url if browser_state is not None else None,
    )

    cached_preview = get_cached_preview(request)
    if takeover_surface["active"]:
        preview_data_url = None
        preview_captured_at = None
    elif cached_preview is not None:
        preview_data_url = cached_preview.data_url
        preview_captured_at = cached_preview.captured_at
    elif browser_status.get("host_status") == "running":
        try:
            screenshot = runtime.capture_preview()
            if screenshot:
                preview_data_url = f"data:image/png;base64,{screenshot}"
                preview_captured_at = datetime.now(timezone.utc).isoformat()
            store_preview_cache(request, preview_data_url, preview_captured_at)
        except Exception:
            store_preview_cache(request, None, None)

    page = {
        "url": "",
        "title": "",
        "status": "idle",
        "auth": {},
    }
    if web_state is not None:
        page = {
            "url": web_state.url,
            "title": web_state.title,
            "status": web_state.status,
            "auth": web_state.auth.model_dump(),
        }
    elif browser_state is not None:
        page = {
            "url": browser_state.url,
            "title": browser_state.title,
            "status": browser_state.page_status,
            "auth": browser_state.auth.model_dump(),
        }

    local_resources = [] if supervisor_inactive else [
        item.model_dump()
        for item in runtime.list_local_resources()
    ]
    financial_policies = [] if supervisor_inactive else [
        item.model_dump()
        for item in runtime.list_financial_policies()
    ]
    payment_instruments = [] if supervisor_inactive else [
        item.model_dump()
        for item in runtime.list_payment_instruments()
    ]
    step_ups = [] if supervisor_inactive else [
        item.model_dump()
        for item in runtime.list_step_ups(include_terminal=True)
    ]
    safety_receipts = [] if supervisor_inactive else [
        item.model_dump()
        for item in runtime.list_safety_receipts(limit=100)
    ]

    return VisualizerState.model_validate(
        {
            "runtime": {
                "online": True,
                "driver": browser_status.get("selected_driver", "managed-chromium"),
                "headless": bool(browser_status.get("headless")),
                "host_status": browser_status.get("host_status", "not_started"),
                "visible_window": bool(browser_status.get("visible_window")),
                "executable_found": executable_found,
                "executable_name": executable_name,
                "last_error": browser_status.get("last_error"),
            },
            "agent": {
                "active_agent_id": browser_status.get("active_agent_id"),
                "lease_expires_at": browser_status.get("agent_lease_expires_at"),
            },
            "profile": {
                "profile_id": profile_metadata.profile_id,
                "shared": profile_metadata.owner == "shared",
                "owner": profile_metadata.owner,
                "trust_mode": profile_metadata.trust_mode,
                "unknown_external_effect_policy": profile_metadata.unknown_external_effect_policy,
                "bound_agent_ids": profile_metadata.bound_agent_ids,
                "allowed_origins": profile_metadata.allowed_origins,
                "safety_policy_id": profile_metadata.safety_policy_id,
                "financial_policy_id": profile_metadata.financial_policy_id,
            },
            "page": page,
            "browser_state": browser_state.model_dump() if browser_state is not None else None,
            "web_state": web_state.model_dump() if web_state is not None else None,
            "preview": {
                "format": "png",
                "data_url": preview_data_url,
                "captured_at": preview_captured_at,
            },
            "auth_surface": _auth_surface_payload(request, browser_state.url if browser_state else None),
            "takeover_surface": takeover_surface,
            "local_resources": local_resources,
            "financial_policies": financial_policies,
            "payment_instruments": payment_instruments,
            "step_ups": step_ups,
            "safety_receipts": safety_receipts,
            "recent_actions": get_action_log(request).recent(),
            "errors": errors,
        }
    )


def _payload_with_state(request: Request, state) -> dict:
    store_preview_cache(request, None, None)
    payload = build_visualizer_state(request).model_dump()
    payload["browser_state"] = state.model_dump()
    payload["auth_surface"] = _auth_surface_payload(request, state.url)
    return payload


@router.get("/visualizer/state")
def visualizer_state(request: Request) -> dict:
    return build_visualizer_state(request).model_dump()


@router.post(
    "/visualizer/open-auth-surface",
    dependencies=_CONTROL_DEPENDENCIES,
    deprecated=True,
)
def open_auth_surface(request: Request) -> dict:
    _ = request
    _require_legacy_auth_surface()


@router.post(
    "/visualizer/open-host",
    dependencies=_CONTROL_DEPENDENCIES,
    deprecated=True,
)
def open_host(request: Request) -> dict:
    _ = request
    _require_legacy_auth_surface()


@router.post(
    "/visualizer/close-auth-surface",
    dependencies=_CONTROL_DEPENDENCIES,
    deprecated=True,
)
def close_auth_surface(request: Request) -> dict:
    _ = request
    _require_legacy_auth_surface()


@router.get("/visualizer/profile-policy/{profile_id}")
def get_profile_policy(profile_id: str, request: Request) -> dict:
    try:
        metadata = get_profile_repository(request).get_policy(profile_id)
        return {"profile": metadata.model_dump()}
    except ProfileRepositoryError as exc:
        raise _profile_policy_http_error(exc) from exc


@router.put("/visualizer/profile-policy/{profile_id}", dependencies=_CONTROL_DEPENDENCIES)
def set_profile_policy(
    profile_id: str,
    payload: ProfileOwnershipMetadata,
    request: Request,
) -> dict:
    if payload.profile_id != profile_id:
        raise HTTPException(
            status_code=400,
            detail={"code": "profile_id_mismatch", "message": "profile_id in path and body must match"},
        )
    try:
        metadata = get_profile_repository(request).upsert_policy(payload)
        _record_action(
            request,
            tool="visualizer.set_profile_policy",
            message=f"profile policy updated: {profile_id}",
        )
        return {"profile": metadata.model_dump()}
    except ProfileRepositoryError as exc:
        raise _profile_policy_http_error(exc) from exc


@router.get("/visualizer/financial-policies")
def list_financial_policies(request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        return {"policies": []}
    return {"policies": [item.model_dump() for item in runtime.list_financial_policies()]}


@router.post("/visualizer/financial-policies", dependencies=_CONTROL_DEPENDENCIES)
def create_financial_policy(payload: FinancialPolicy, request: Request) -> dict:
    runtime = _ensure_control_session_runtime(request)
    policy = runtime.register_financial_policy(payload)
    _record_action(
        request,
        tool="visualizer.create_financial_policy",
        message=f"financial policy registered: {policy.policy_id}",
    )
    return {"policy": policy.model_dump()}


@router.get("/visualizer/financial-policies/{policy_id}/usage")
def get_financial_usage(policy_id: str, request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "financial_policy_missing", "message": "financial policy was not found"},
        )
    try:
        return {"usage": runtime.financial_usage(policy_id).model_dump()}
    except PaymentInstrumentError as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/visualizer/payment-instruments")
def list_payment_instruments(request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        return {"instruments": []}
    return {
        "instruments": [item.model_dump() for item in runtime.list_payment_instruments()]
    }


@router.post("/visualizer/payment-instruments", dependencies=_CONTROL_DEPENDENCIES)
def create_payment_instrument(payload: PaymentInstrumentRef, request: Request) -> dict:
    repository = get_profile_repository(request)
    try:
        profile = repository.get_policy(payload.profile_id)
        runtime = _ensure_control_session_runtime(request, payload.profile_id)
        if profile.financial_policy_id is not None and profile.financial_policy_id != payload.policy_id:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "profile_financial_policy_mismatch",
                    "message": "payment instrument policy must match the active Profile financial policy",
                },
            )
        # Validate the complete Session-scoped reference before changing
        # persistent Profile metadata. This means a catalog failure cannot leave
        # behind a usable in-memory payment reference with no matching policy.
        runtime.validate_payment_instrument(payload)
        if profile.financial_policy_id is None:
            repository.upsert_policy(
                profile.model_copy(update={"financial_policy_id": payload.policy_id}, deep=True)
            )
        state = runtime.register_payment_instrument(payload)
        _record_action(
            request,
            tool="visualizer.create_payment_instrument",
            message=f"payment instrument registered: {payload.instrument_id}",
        )
        return {"instrument": state.model_dump()}
    except PaymentInstrumentError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ProfileRepositoryError as exc:
        raise _profile_policy_http_error(exc) from exc


@router.delete("/visualizer/payment-instruments/{instrument_id}", dependencies=_CONTROL_DEPENDENCIES)
def revoke_payment_instrument(instrument_id: str, request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "payment_instrument_missing", "message": "payment instrument was not found"},
        )
    try:
        state = runtime.revoke_payment_instrument(instrument_id)
        _record_action(
            request,
            tool="visualizer.revoke_payment_instrument",
            message=f"payment instrument revoked: {instrument_id}",
        )
        return {"instrument": state.model_dump()}
    except PaymentInstrumentError as exc:
        raise HTTPException(
            status_code=404 if exc.code == "payment_instrument_missing" else 400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/visualizer/step-ups")
def list_step_ups(request: Request, include_terminal: bool = True) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        return {"step_ups": []}
    return {
        "step_ups": [
            item.model_dump()
            for item in runtime.list_step_ups(include_terminal=include_terminal)
        ]
    }


@router.post("/visualizer/step-ups/{step_up_id}/approve", dependencies=_CONTROL_DEPENDENCIES)
def approve_step_up(
    step_up_id: str,
    payload: StepUpDecisionRequest,
    request: Request,
) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "step_up_not_found", "message": "step-up request was not found"},
        )
    try:
        state = runtime.approve_step_up(
            step_up_id,
            decided_by=payload.decided_by,
            decision_note=payload.decision_note,
            approved_scope=payload.approved_scope,
        )
        _record_action(
            request,
            tool="visualizer.approve_step_up",
            message=f"step-up approved: {step_up_id}",
        )
        return {"step_up": state.model_dump()}
    except StepUpError as exc:
        raise HTTPException(
            status_code=404 if exc.code == "step_up_not_found" else 400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/visualizer/step-ups/{step_up_id}/reject", dependencies=_CONTROL_DEPENDENCIES)
def reject_step_up(
    step_up_id: str,
    payload: StepUpDecisionRequest,
    request: Request,
) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "step_up_not_found", "message": "step-up request was not found"},
        )
    try:
        state = runtime.reject_step_up(
            step_up_id,
            decided_by=payload.decided_by,
            decision_note=payload.decision_note,
        )
        _record_action(
            request,
            tool="visualizer.reject_step_up",
            message=f"step-up rejected: {step_up_id}",
        )
        return {"step_up": state.model_dump()}
    except StepUpError as exc:
        raise HTTPException(
            status_code=404 if exc.code == "step_up_not_found" else 400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.get("/visualizer/safety-receipts")
def list_safety_receipts(request: Request, limit: int = 100) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        return {"receipts": []}
    return {
        "receipts": [
            item.model_dump()
            for item in runtime.list_safety_receipts(limit=limit)
        ]
    }


@router.get("/visualizer/safety-receipts/{receipt_id}")
def get_safety_receipt(receipt_id: str, request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "safety_receipt_not_found", "message": "safety receipt was not found"},
        )
    receipt = runtime.get_safety_receipt(receipt_id)
    if receipt is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "safety_receipt_not_found", "message": "safety receipt was not found"},
        )
    return {"receipt": receipt.model_dump()}


@router.get("/visualizer/resources")
def list_local_resources(request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        return {"resources": []}
    return {
        "resources": [item.model_dump() for item in runtime.list_local_resources()]
    }


@router.post("/visualizer/resources", dependencies=_CONTROL_DEPENDENCIES)
def create_local_resource(payload: LocalResourceGrantRequest, request: Request) -> dict:
    if len(payload.bound_profile_ids) > 1:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "resource_profile_scope_ambiguous",
                "message": "a Session-scoped resource grant can target at most one Browser Profile",
            },
        )
    target_profile = (
        payload.bound_profile_ids[0]
        if len(payload.bound_profile_ids) == 1
        else None
    )
    try:
        runtime = _ensure_control_session_runtime(request, target_profile)
        state = runtime.register_local_resource(
            display_name=payload.display_name,
            content_base64=payload.content_base64,
            owner=payload.owner,
            purpose=payload.purpose,
            allowed_origins=payload.allowed_origins,
            bound_agent_ids=payload.bound_agent_ids,
            bound_profile_ids=payload.bound_profile_ids,
            expires_in_seconds=payload.expires_in_seconds,
            max_uses=payload.max_uses,
        )
        _record_action(
            request,
            tool="visualizer.create_resource_grant",
            message=f"resource grant created: {state.grant.resource_ref}",
        )
        return {"resource": state.model_dump()}
    except LocalResourceError as exc:
        _record_action(
            request,
            tool="visualizer.create_resource_grant",
            status="error",
            code=exc.code,
            message=str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ProfileRepositoryError as exc:
        raise _profile_policy_http_error(exc) from exc


@router.delete("/visualizer/resources/{resource_ref}", dependencies=_CONTROL_DEPENDENCIES)
def revoke_local_resource(resource_ref: str, request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "resource_not_found", "message": "resource grant was not found"},
        )
    try:
        state = runtime.revoke_local_resource(resource_ref)
        _record_action(
            request,
            tool="visualizer.revoke_resource_grant",
            message=f"resource grant revoked: {resource_ref}",
        )
        return {"resource": state.model_dump()}
    except LocalResourceError as exc:
        _record_action(
            request,
            tool="visualizer.revoke_resource_grant",
            status="error",
            code=exc.code,
            message=str(exc),
        )
        raise HTTPException(
            status_code=404 if exc.code == "resource_not_found" else 400,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


@router.post("/visualizer/restart-host", dependencies=_CONTROL_DEPENDENCIES)
def restart_host(request: Request) -> dict:
    runtime = _find_control_session_runtime(request)
    if runtime is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "session_context_required",
                "message": "no active Browser Session is available to restart",
            },
        )
    try:
        state = runtime.restart_host()
        store_preview_cache(request, None, None)
        _record_action(request, tool="visualizer.restart_host", message="host restarted with current url")
        return _payload_with_state(request, state)
    except BrowserRuntimeError as exc:
        _record_action(
            request,
            tool="visualizer.restart_host",
            status="error",
            code=exc.code,
            message=exc.message,
        )
        raise HTTPException(status_code=exc.http_status, detail=exc.to_detail()) from exc
    except BrowserHostClosedError as exc:
        _record_action(request, tool="visualizer.restart_host", status="error", code="browser_host_closed", message=str(exc))
        raise HTTPException(status_code=503, detail={"code": "browser_host_closed", "message": str(exc)}) from exc
    except Exception as exc:
        _record_action(request, tool="visualizer.restart_host", status="error", message=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
