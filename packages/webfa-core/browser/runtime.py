from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, replace
from hashlib import sha256
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from uuid import uuid4

from browser.agent_lease import AgentLease, AgentLeaseSnapshot
from browser.agent_view import AgentViewBuilder
from browser.action_log import redact_action_message
from browser.config import resolve_browser_runtime_config
from browser.driver import BrowserDriver, RawPageSnapshot
from browser.driver_factory import create_default_driver_factory
from browser.exceptions import BrowserHostClosedError
from browser.human_control import (
    HumanControlError,
    HumanControlLeaseManager,
    HumanControlLeaseState,
    HumanInputEvent,
)
from browser.local_resource_broker import (
    LocalResourceBroker,
    LocalResourceError,
)
from browser.object_registry import ObjectRegistry
from browser.payment_broker import (
    FinancialAuthorization,
    PaymentAuthorization,
    PaymentInstrumentBroker,
    PaymentInstrumentError,
    parse_amount,
)
from browser.profile_policy import ProfilePolicyEvaluation, ProfilePolicyStore
from browser.semantic_operations import SemanticOperationExecutor, WebOperationPlan
from browser.session_events import SessionEvent, SessionEventBus
from browser.safety_audit import SafetyReceiptStore
from browser.safety_context import SafetyContextManager
from browser.safety_evidence import RuntimeEvidenceResolver
from browser.step_up import StepUpError, StepUpManager
from browser.runtime_errors import BrowserRuntimeError
from browser.runtime_errors import auth_surface_active as auth_surface_active_error
from browser.runtime_errors import auth_surface_retired as auth_surface_retired_error
from browser.runtime_errors import human_control_active as human_control_active_error
from browser.runtime_errors import dialog_not_found
from browser.runtime_errors import dialog_required as dialog_required_error
from browser.runtime_errors import stale_element as stale_element_error
from browser.web_object_compiler import WebObjectCompiler
from browser.web_observe import (
    WebObserveDebugForbiddenError,
    WebObserveResult,
    WebObserveService,
    WebObserveUnavailableError,
)
from browser.url_policy import enforce_navigation_allowed
from browser.session import BrowserSession
from browser.visual_surface import (
    BoundVisualSurfaceProvider,
    VisualFrameSink,
    VisualStreamConfig,
    VisualStreamState,
    VisualSurfaceBinding,
)
from schemas.browser import (
    BrowserActionRequest,
    BrowserActionResult,
    BrowserAgentState,
    BrowserAuthState,
    BrowserElement,
    BrowserForm,
    BrowserState,
    BrowserTab,
)
from schemas.safety import (
    FinancialPolicy,
    FinancialUsageState,
    LocalResourceGrant,
    LocalResourceGrantState,
    PaymentInstrumentRef,
    PaymentInstrumentState,
    ProfileOwnershipMetadata,
    ResourceOwner,
    SafetyAssuranceLevel,
    SafetyDecision,
    SafetyEvidenceItem,
    SafetyEvidenceReport,
    SafetyMismatch,
    SafetyReceipt,
    StepUpReason,
    StepUpRequestState,
    StepUpScopeScalar,
)
from schemas.web import (
    HumanTakeoverState,
    TakeoverReason,
    WebObject,
    WebObserveRequest,
    WebOpenRequest,
    WebOpenResult,
    WebOperationRequest,
    WebOperationResult,
    WebState,
)


DriverFactory = Callable[[], BrowserDriver]


@dataclass(frozen=True)
class _SelectedPaymentInstrument:
    agent_id: str
    profile_id: str
    document_id: str
    origin: str
    target_object_id: str
    instrument_id: str
    amount: Decimal
    currency: str
    transaction_kind: str
    recurring: bool
    assurance: SafetyAssuranceLevel


class BrowserRuntime:
    """Single-session agent browser runtime backed by one driver thread."""

    def __init__(self, headless: bool | None = None, driver_factory: DriverFactory | None = None) -> None:
        config = resolve_browser_runtime_config(headless=headless)
        self._driver_name = config.driver_name
        self._headless = config.headless
        self._auth_takeover = config.auth_takeover
        self._auth_surface_mode = config.auth_surface_mode
        self._private_url_policy = config.private_url_policy
        self._driver_factory = driver_factory or create_default_driver_factory(self._driver_name, self._headless)
        self._jobs: queue.Queue[tuple[str, tuple, queue.Queue] | None] = queue.Queue()
        self._web_operation_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._closed = False
        self._agent_lease = AgentLease()
        self._safety_contexts = SafetyContextManager()
        self._local_resources = LocalResourceBroker()
        self._profile_policies = ProfilePolicyStore()
        self._payments = PaymentInstrumentBroker()
        self._selected_payment: _SelectedPaymentInstrument | None = None
        self._step_ups = StepUpManager()
        self._safety_receipts = SafetyReceiptStore()
        self._session_events = SessionEventBus()
        self._human_control = HumanControlLeaseManager()
        self._human_pointer_down: HumanInputEvent | None = None
        self._human_pressed_keys: dict[tuple[str, str], HumanInputEvent] = {}

    def replay_session_events(
        self,
        *,
        after_sequence: int = 0,
        session_id: str | None = None,
        limit: int = 200,
    ) -> list[SessionEvent]:
        return self._session_events.replay(
            after_sequence=after_sequence,
            session_id=session_id,
            limit=limit,
        )

    def subscribe_session_events(
        self,
        callback: Callable[[SessionEvent], None],
        *,
        replay_after_sequence: int | None = None,
        session_id: str | None = None,
    ) -> str:
        return self._session_events.subscribe(
            callback,
            replay_after_sequence=replay_after_sequence,
            session_id=session_id,
        )

    def unsubscribe_session_events(self, subscription_id: str) -> bool:
        return self._session_events.unsubscribe(subscription_id)

    def start_visual_stream(
        self,
        frame_sink: VisualFrameSink,
        config: VisualStreamConfig | None = None,
    ) -> str:
        with self._web_operation_lock:
            return self._call("start_visual_stream", config or VisualStreamConfig(), frame_sink)

    def stop_visual_stream(self, stream_id: str) -> VisualStreamState:
        with self._web_operation_lock:
            return self._call("stop_visual_stream", stream_id)

    def visual_stream_status(self, stream_id: str | None = None) -> VisualStreamState | None:
        return self._call("visual_stream_status", stream_id)

    def monitor_snapshot(self) -> dict[str, Any]:
        self._reconcile_human_control_expiry()
        snapshot = self._agent_lease.snapshot()
        worker = self._call("monitor_snapshot") if self._thread is not None else {}
        human = self._human_control.active()
        return {
            "session_id": worker.get("session_id", "default"),
            "profile_id": snapshot.profile_id,
            "active_agent_id": snapshot.active_agent_id,
            "agent_lease_expires_at": snapshot.expires_at.isoformat() if snapshot.expires_at else None,
            "human_control_active": human is not None,
            "human_control_reason": human.reason if human is not None else None,
            "human_control_expires_at": human.expires_at.isoformat() if human is not None else None,
            **worker,
        }

    def acquire_human_control(
        self,
        *,
        connection_id: str,
        reason: str | None = None,
        ttl_seconds: int = 300,
    ) -> HumanControlLeaseState:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            existing = self._human_control.active()
            snapshot = self._agent_lease.snapshot()
            worker = self._call("monitor_snapshot")
            session_id = str(worker.get("session_id") or "default")
            tab_id = str(worker.get("tab_id") or "tab_1")
            effective_reason = _normalize_takeover_reason(
                (reason or "").strip()
                or str(worker.get("takeover_reason") or "manual_identity_confirmation")
            )
            lease = self._human_control.acquire(
                connection_id=connection_id,
                session_id=session_id,
                profile_id=snapshot.profile_id,
                tab_id=tab_id,
                reason=effective_reason,
                active_agent_id=snapshot.active_agent_id,
                ttl_seconds=ttl_seconds,
            )
            if existing is not None and existing.lease_id == lease.lease_id:
                return lease
            try:
                self._call("begin_human_control", effective_reason)
            except Exception:
                self._human_control.release(
                    lease_id=lease.lease_id,
                    connection_id=connection_id,
                    status="aborted",
                )
                raise
            return lease

    def send_human_input(
        self,
        *,
        connection_id: str,
        lease_id: str,
        event: HumanInputEvent,
    ) -> None:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            worker = self._call("monitor_snapshot")
            lease = self._human_control.require_active(
                lease_id=lease_id,
                connection_id=connection_id,
                session_id=str(worker.get("session_id") or "default"),
            )
            current_tab_id = str(worker.get("tab_id") or "tab_1")
            if lease.tab_id != current_tab_id:
                raise HumanControlError(
                    "human_control_tab_mismatch",
                    "HumanControlLease is bound to another tab",
                )
            self._call("dispatch_human_input", event)
            self._record_human_input_state(event)

    def sync_human_control_state(
        self,
        *,
        connection_id: str,
        lease_id: str,
    ) -> dict[str, Any]:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            worker = self._call("monitor_snapshot")
            lease = self._human_control.require_active(
                lease_id=lease_id,
                connection_id=connection_id,
                session_id=str(worker.get("session_id") or "default"),
            )
            current_tab_id = str(worker.get("tab_id") or "tab_1")
            if lease.tab_id != current_tab_id:
                raise HumanControlError(
                    "human_control_tab_mismatch",
                    "HumanControlLease is bound to another tab",
                )
            self._call("sync_human_control_state")
            return self.monitor_snapshot()

    def release_human_control(
        self,
        *,
        connection_id: str,
        lease_id: str,
        aborted: bool = False,
    ) -> HumanControlLeaseState:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            lease = self._human_control.release(
                lease_id=lease_id,
                connection_id=connection_id,
                status="aborted" if aborted else "released",
            )
            try:
                self._release_stuck_human_inputs()
                self._call("end_human_control", aborted)
            finally:
                if lease.active_agent_id is not None:
                    self._agent_lease.acquire(lease.active_agent_id)
            return lease

    def release_human_control_connection(self, connection_id: str) -> HumanControlLeaseState | None:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            lease = self._human_control.release_connection(connection_id)
            if lease is None:
                return None
            try:
                self._release_stuck_human_inputs()
                self._call("end_human_control", True)
            finally:
                if lease.active_agent_id is not None:
                    self._agent_lease.acquire(lease.active_agent_id)
            return lease

    def human_control_status(self) -> HumanControlLeaseState | None:
        with self._web_operation_lock:
            self._reconcile_human_control_expiry()
            return self._human_control.active()

    def open(self, url: str, agent_id: str | None = None) -> BrowserActionResult:
        with self._web_operation_lock:
            self._require_agent_control_available()
            self._agent_lease.acquire(agent_id)
            return self._with_agent_result(self._call("open", url))

    def observe(self) -> BrowserState:
        return self._with_agent_state(self._call("observe"))

    def open_web(self, request: WebOpenRequest, agent_id: str | None = None) -> WebOpenResult:
        with self._web_operation_lock:
            result = self._open_web_inner(request, agent_id=agent_id)
            if result.safety_decision is None:
                return result
            receipt = self._generic_open_receipt(request, result)
            result.safety_receipt = self._safety_receipts.append(receipt)
            self._publish_safety_event(
                result.safety_decision,
                result.state,
                operation="open_url",
            )
            return result

    def _open_web_inner(self, request: WebOpenRequest, agent_id: str | None = None) -> WebOpenResult:
        self._require_agent_control_available()
        snapshot = self._agent_lease.acquire(agent_id)
        active_agent_id = snapshot.active_agent_id or "anonymous-mcp"
        requested_origin = _origin_from_url(request.url)
        declaration = request.safety.declaration if request.safety is not None else None
        supplied_step_up_id = request.safety.step_up_id if request.safety is not None else None
        authorized_step_up_id: str | None = None
        profile_evaluation = self._profile_policies.evaluate(
            agent_id=active_agent_id,
            profile_id=snapshot.profile_id,
            current_origin=requested_origin,
            declaration=declaration,
            evidence_report=None,
        )
        if profile_evaluation.decision not in {"allow", "allow_with_audit"}:
            state = WebState(
                url=request.url,
                agent=self._agent_state(snapshot),
            )
            if profile_evaluation.decision == "require_step_up":
                reason, current_scope, requested_scope = _profile_step_up_scope(
                    profile_evaluation,
                    self._profile_policies.get(snapshot.profile_id),
                    declaration,
                )
                profile_declared_origins = _declaration_origins(declaration)
                if profile_declared_origins and requested_origin not in profile_declared_origins:
                    current_scope["origin_scope"] = "|".join(profile_declared_origins)
                    requested_scope["origin"] = requested_origin
                requested_scope = _bind_navigation_scope(requested_scope, request.url)
                if supplied_step_up_id is not None:
                    try:
                        self._step_ups.authorize(
                            supplied_step_up_id,
                            context_id=request.safety.context_id if request.safety is not None else None,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                            origin=requested_origin,
                            target_object_id="navigation",
                            operation="open_url",
                            requested_scope=requested_scope,
                        )
                        authorized_step_up_id = supplied_step_up_id
                        profile_evaluation = ProfilePolicyEvaluation(
                            decision="allow_with_audit",
                            status="ready",
                            message="Approved step-up grant covers the navigation Profile escalation",
                            evidence=profile_evaluation.evidence,
                        )
                    except StepUpError as exc:
                        decision = _decision_from_profile(profile_evaluation).model_copy(
                            update={"message": str(exc), "step_up": _safe_step_up_get(self._step_ups, supplied_step_up_id)}
                        )
                        return WebOpenResult(
                            ok=False,
                            url=request.url,
                            state=state,
                            safety_decision=decision,
                        )
                else:
                    step_up = self._step_ups.request(
                        reason=reason,
                        context_id=request.safety.context_id if request.safety is not None else None,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        origin=requested_origin,
                        target_object_id="navigation",
                        operation="open_url",
                        message=profile_evaluation.message,
                        current_scope=current_scope,
                        requested_scope=requested_scope,
                    )
                    decision = _decision_from_profile(profile_evaluation).model_copy(update={"step_up": step_up})
                    return WebOpenResult(
                        ok=False,
                        url=request.url,
                        state=state,
                        safety_decision=decision,
                    )
            else:
                decision = _decision_from_profile(profile_evaluation)
                return WebOpenResult(
                    ok=False,
                    url=request.url,
                    state=state,
                    safety_decision=decision,
                )

        effective_safety = request.safety
        if request.safety is not None:
            context_id = request.safety.context_id
            scoped_declaration = declaration
            if scoped_declaration is None and context_id is not None:
                scoped_declaration = self._safety_contexts.declaration_for(context_id)
            declared_origins = _declaration_origins(scoped_declaration)
            if declared_origins and requested_origin not in declared_origins:
                current_scope: dict[str, StepUpScopeScalar] = {
                    "origin_scope": "|".join(declared_origins),
                }
                requested_scope = _bind_navigation_scope(
                    {"origin": requested_origin},
                    request.url,
                )
                if supplied_step_up_id is not None and authorized_step_up_id is None:
                    try:
                        self._step_ups.authorize(
                            supplied_step_up_id,
                            context_id=context_id,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                            origin=requested_origin,
                            target_object_id="navigation",
                            operation="open_url",
                            requested_scope=requested_scope,
                        )
                        authorized_step_up_id = supplied_step_up_id
                    except StepUpError as exc:
                        state = WebState(url=request.url, agent=self._agent_state(snapshot))
                        return WebOpenResult(
                            ok=False,
                            url=request.url,
                            state=state,
                            safety_decision=SafetyDecision(
                                decision="require_step_up",
                                status="step_up_required",
                                context_id=context_id,
                                message=str(exc),
                                step_up=_safe_step_up_get(self._step_ups, supplied_step_up_id),
                            ),
                        )
                if authorized_step_up_id is not None:
                    if context_id is not None:
                        scope_decision = self._safety_contexts.extend_origin_scope(
                            context_id,
                            requested_origin,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                        )
                        if scope_decision.decision not in {"allow", "allow_with_audit"}:
                            state = WebState(url=request.url, agent=self._agent_state(snapshot))
                            return WebOpenResult(
                                ok=False,
                                url=request.url,
                                state=state,
                                safety_decision=scope_decision.model_copy(
                                    update={
                                        "step_up": _safe_step_up_get(
                                            self._step_ups,
                                            authorized_step_up_id,
                                        )
                                    }
                                ),
                            )
                    elif declaration is not None:
                        expanded_declaration = declaration.model_copy(
                            update={
                                "origin_scope": [*declared_origins, requested_origin],
                            },
                            deep=True,
                        )
                        effective_safety = request.safety.model_copy(
                            update={"declaration": expanded_declaration},
                            deep=True,
                        )
                else:
                    step_up = self._step_ups.request(
                        reason="profile_scope",
                        context_id=context_id,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        origin=requested_origin,
                        target_object_id="navigation",
                        operation="open_url",
                        message="Requested navigation origin is outside the SafetyContext scope",
                        current_scope=current_scope,
                        requested_scope=requested_scope,
                    )
                    state = WebState(url=request.url, agent=self._agent_state(snapshot))
                    return WebOpenResult(
                        ok=False,
                        url=request.url,
                        state=state,
                        safety_decision=SafetyDecision(
                            decision="require_step_up",
                            status="step_up_required",
                            context_id=context_id,
                            message="Requested navigation origin is outside the SafetyContext scope",
                            step_up=step_up,
                        ),
                    )

        self._selected_payment = None
        self._call("open", request.url)
        result = self._call("observe_web", WebObserveRequest(), False)
        state = result.state
        state.agent = self._agent_state(snapshot)
        decision = None
        if effective_safety is not None:
            decision = self._safety_contexts.evaluate(
                effective_safety,
                agent_id=active_agent_id,
                profile_id=snapshot.profile_id,
                current_origin=_origin_from_url(state.url),
            )
            decision = _merge_profile_evaluation(decision, profile_evaluation)
            state.safety = decision.state
        else:
            state.safety = self._current_safety_state(snapshot, state)
        if authorized_step_up_id is not None:
            self._step_ups.consume(authorized_step_up_id)
        return WebOpenResult(ok=True, url=request.url, state=state, safety_decision=decision)

    def observe_web(
        self,
        request: WebObserveRequest | None = None,
        *,
        allow_debug: bool = False,
    ) -> WebObserveResult:
        result = self._call("observe_web", request or WebObserveRequest(), allow_debug)
        snapshot = self._agent_lease.snapshot()
        result.state.agent = self._agent_state(snapshot)
        result.state.safety = self._current_safety_state(snapshot, result.state)
        return result

    def register_local_resource(
        self,
        *,
        display_name: str,
        content_base64: str,
        owner: ResourceOwner,
        purpose: str,
        allowed_origins: list[str],
        bound_agent_ids: list[str] | None = None,
        bound_profile_ids: list[str] | None = None,
        expires_in_seconds: int | None = 3600,
        max_uses: int = 1,
    ) -> LocalResourceGrantState:
        return self._local_resources.register_base64(
            display_name=display_name,
            content_base64=content_base64,
            owner=owner,
            purpose=purpose,
            allowed_origins=allowed_origins,
            bound_agent_ids=bound_agent_ids,
            bound_profile_ids=bound_profile_ids,
            expires_in_seconds=expires_in_seconds,
            max_uses=max_uses,
        )

    def list_local_resources(self) -> list[LocalResourceGrantState]:
        return self._local_resources.list()

    def revoke_local_resource(self, resource_ref: str) -> LocalResourceGrantState:
        return self._local_resources.revoke(resource_ref)

    def get_profile_policy(self, profile_id: str = "default") -> ProfileOwnershipMetadata:
        return self._profile_policies.get(profile_id)

    def set_profile_policy(self, metadata: ProfileOwnershipMetadata) -> ProfileOwnershipMetadata:
        return self._profile_policies.upsert(metadata)

    def list_profile_policies(self) -> list[ProfileOwnershipMetadata]:
        return self._profile_policies.list()

    def register_financial_policy(self, policy: FinancialPolicy) -> FinancialPolicy:
        return self._payments.register_policy(policy)

    def list_financial_policies(self) -> list[FinancialPolicy]:
        return self._payments.list_policies()

    def register_payment_instrument(self, instrument: PaymentInstrumentRef) -> PaymentInstrumentState:
        return self._payments.register_instrument(instrument)

    def list_payment_instruments(self) -> list[PaymentInstrumentState]:
        return self._payments.list_instruments()

    def revoke_payment_instrument(self, instrument_id: str) -> PaymentInstrumentState:
        return self._payments.revoke_instrument(instrument_id)

    def financial_usage(self, policy_id: str) -> FinancialUsageState:
        return self._payments.usage(policy_id)

    def list_step_ups(self, *, include_terminal: bool = True) -> list[StepUpRequestState]:
        return self._step_ups.list(include_terminal=include_terminal)

    def approve_step_up(
        self,
        step_up_id: str,
        *,
        decided_by: str = "local_user",
        decision_note: str = "",
        approved_scope: dict[str, StepUpScopeScalar] | None = None,
    ) -> StepUpRequestState:
        return self._step_ups.approve(
            step_up_id,
            decided_by=decided_by,
            decision_note=decision_note,
            approved_scope=approved_scope,
        )

    def reject_step_up(
        self,
        step_up_id: str,
        *,
        decided_by: str = "local_user",
        decision_note: str = "",
    ) -> StepUpRequestState:
        return self._step_ups.reject(
            step_up_id,
            decided_by=decided_by,
            decision_note=decision_note,
        )

    def list_safety_receipts(self, *, limit: int = 100) -> list[SafetyReceipt]:
        return self._safety_receipts.list(limit=limit)

    def get_safety_receipt(self, receipt_id: str) -> SafetyReceipt | None:
        return self._safety_receipts.get(receipt_id)

    def act(self, request: BrowserActionRequest, agent_id: str | None = None) -> BrowserActionResult:
        with self._web_operation_lock:
            self._require_agent_control_available()
            self._agent_lease.acquire(agent_id)
            return self._with_agent_result(self._call("act", request))

    def act_web(self, request: WebOperationRequest, agent_id: str | None = None) -> WebOperationResult:
        with self._web_operation_lock:
            result = self._act_web_inner(request, agent_id=agent_id)
            if result.safety_decision is None:
                return result
            receipt = result.safety_receipt or self._generic_safety_receipt(request, result)
            result.safety_receipt = self._safety_receipts.append(receipt)
            self._publish_safety_event(
                result.safety_decision,
                result.state,
                operation=request.operation,
            )
            return result

    def _act_web_inner(self, request: WebOperationRequest, agent_id: str | None = None) -> WebOperationResult:
        self._require_agent_control_available()
        snapshot = self._agent_lease.acquire(agent_id)
        active_agent_id = snapshot.active_agent_id or "anonymous-mcp"
        current = self._call("observe_web", WebObserveRequest(), False).state
        current.agent = self._agent_state(snapshot)
        evidence: SafetyEvidenceReport = self._call("operation_evidence", request)
        decision: SafetyDecision | None = None
        authorized_step_up_id: str | None = None
        supplied_step_up_id = request.safety.step_up_id if request.safety is not None else None
        declaration = None
        if request.safety is not None:
            declaration = request.safety.declaration
            if declaration is None and request.safety.context_id is not None:
                declaration = self._safety_contexts.declaration_for(request.safety.context_id)
        profile_evaluation = self._profile_policies.evaluate(
            agent_id=active_agent_id,
            profile_id=snapshot.profile_id,
            current_origin=_origin_from_url(current.url),
            declaration=declaration,
            evidence_report=evidence,
        )
        evidence = _with_profile_policy_evidence(evidence, profile_evaluation)
        if profile_evaluation.decision not in {"allow", "allow_with_audit"}:
            if profile_evaluation.decision == "require_step_up":
                reason, current_scope, requested_scope = _profile_step_up_scope(
                    profile_evaluation,
                    self._profile_policies.get(snapshot.profile_id),
                    declaration,
                )
                current_origin = _origin_from_url(current.url)
                profile_declared_origins = _declaration_origins(declaration)
                if profile_declared_origins and current_origin not in profile_declared_origins:
                    current_scope["origin_scope"] = "|".join(profile_declared_origins)
                    requested_scope["origin"] = current_origin
                requested_scope = _bind_web_operation_scope(
                    requested_scope,
                    current,
                    request.target,
                )
                if supplied_step_up_id is not None:
                    try:
                        self._step_ups.authorize(
                            supplied_step_up_id,
                            context_id=request.safety.context_id if request.safety is not None else None,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                            origin=_origin_from_url(current.url),
                            target_object_id=request.target,
                            operation=request.operation,
                            requested_scope=requested_scope,
                        )
                        authorized_step_up_id = supplied_step_up_id
                        profile_evaluation = ProfilePolicyEvaluation(
                            decision="allow_with_audit",
                            status="ready",
                            message="Approved step-up grant covers the Profile policy escalation",
                            evidence=profile_evaluation.evidence,
                        )
                    except StepUpError as exc:
                        denied = _decision_from_profile(profile_evaluation, evidence_report=evidence).model_copy(
                            update={"message": str(exc), "step_up": _safe_step_up_get(self._step_ups, supplied_step_up_id)}
                        )
                        current.safety = denied.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=denied,
                            data={"executed": False},
                        )
                else:
                    step_up = self._step_ups.request(
                        reason=reason,
                        context_id=request.safety.context_id if request.safety is not None else None,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        origin=_origin_from_url(current.url),
                        target_object_id=request.target,
                        operation=request.operation,
                        message=profile_evaluation.message,
                        current_scope=current_scope,
                        requested_scope=requested_scope,
                    )
                    denied = _decision_from_profile(profile_evaluation, evidence_report=evidence).model_copy(
                        update={"step_up": step_up}
                    )
                    current.safety = denied.state
                    return WebOperationResult(
                        ok=False,
                        target=request.target,
                        operation=request.operation,
                        document_revision=current.document_revision,
                        state=current,
                        safety_decision=denied,
                        data={"executed": False, "step_up_id": step_up.request.step_up_id},
                    )
            else:
                denied = _decision_from_profile(profile_evaluation, evidence_report=evidence)
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )

        if request.safety is not None:
            current_origin = _origin_from_url(current.url)
            decision = self._safety_contexts.evaluate(
                request.safety,
                agent_id=active_agent_id,
                profile_id=snapshot.profile_id,
                current_origin=current_origin,
            )
            declared_origins = _declaration_origins(declaration)
            origin_scope_mismatch = bool(
                decision.context_id is not None
                and decision.decision == "require_step_up"
                and declared_origins
                and current_origin not in declared_origins
            )
            if origin_scope_mismatch:
                requested_scope = _bind_web_operation_scope(
                    {"origin": current_origin},
                    current,
                    request.target,
                )
                if supplied_step_up_id is not None and authorized_step_up_id is None:
                    try:
                        self._step_ups.authorize(
                            supplied_step_up_id,
                            context_id=decision.context_id,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                            origin=current_origin,
                            target_object_id=request.target,
                            operation=request.operation,
                            requested_scope=requested_scope,
                        )
                        authorized_step_up_id = supplied_step_up_id
                    except StepUpError as exc:
                        decision = decision.model_copy(
                            update={
                                "message": str(exc),
                                "step_up": _safe_step_up_get(
                                    self._step_ups,
                                    supplied_step_up_id,
                                ),
                            }
                        )
                        current.safety = decision.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=decision,
                            data={"executed": False},
                        )
                if authorized_step_up_id is not None:
                    decision = self._safety_contexts.extend_origin_scope(
                        decision.context_id,
                        current_origin,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                    )
                else:
                    step_up = self._step_ups.request(
                        reason="profile_scope",
                        context_id=decision.context_id,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        origin=current_origin,
                        target_object_id=request.target,
                        operation=request.operation,
                        message="Current origin is outside the SafetyContext scope",
                        current_scope={"origin_scope": "|".join(declared_origins)},
                        requested_scope=requested_scope,
                    )
                    decision = decision.model_copy(update={"step_up": step_up})
                    current.safety = decision.state
                    return WebOperationResult(
                        ok=False,
                        target=request.target,
                        operation=request.operation,
                        document_revision=current.document_revision,
                        state=current,
                        safety_decision=decision,
                        data={"executed": False, "step_up_id": step_up.request.step_up_id},
                    )
            if decision.context_id is not None and decision.decision in {"allow", "allow_with_audit", "require_assertion"}:
                decision = self._safety_contexts.apply_evidence(
                    decision.context_id,
                    evidence,
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    current_origin=_origin_from_url(current.url),
                )
            else:
                decision = decision.model_copy(update={"evidence_report": evidence})
            decision = _merge_profile_evaluation(decision, profile_evaluation, evidence_report=evidence)
        elif request.operation != "request_human_takeover" and evidence.observed_dimensions:
            decision = SafetyDecision(
                decision="require_assertion",
                status="undeclared",
                message=(
                    "Runtime observed a protected or externally mutating operation. "
                    "Submit a task-scoped safety declaration and assertions before retrying."
                ),
                evidence_report=evidence,
            )

        takeover_reason = _hard_takeover_reason(evidence)
        if takeover_reason is not None and request.operation != "request_human_takeover":
            takeover_state = self._call("request_safety_takeover", request.target, takeover_reason)
            takeover_state.agent = self._agent_state(snapshot)
            if decision is None:
                decision = SafetyDecision(
                    decision="require_takeover",
                    status="takeover_required",
                    message="A protected credential or verification surface requires human takeover",
                    evidence_report=evidence,
                )
            else:
                decision = decision.model_copy(
                    update={
                        "decision": "require_takeover",
                        "status": "takeover_required",
                        "message": "A protected credential or verification surface requires human takeover",
                        "evidence_report": evidence,
                    }
                )
            takeover_state.safety = decision.state
            return WebOperationResult(
                ok=False,
                target=request.target,
                operation=request.operation,
                document_revision=takeover_state.document_revision,
                state=takeover_state,
                safety_decision=decision,
                data={"executed": False, "takeover_requested": True},
            )

        if decision is not None and decision.decision not in {"allow", "allow_with_audit"}:
            current.safety = decision.state
            return WebOperationResult(
                ok=False,
                target=request.target,
                operation=request.operation,
                document_revision=current.document_revision,
                state=current,
                safety_decision=decision,
                data={"executed": False},
            )

        payment_authorization: PaymentAuthorization | None = None
        payment_operation_commits = False
        if request.operation == "provide_payment_instrument":
            payment_operation_commits = _payment_operation_is_final_commit(evidence)
            payment_scope_error = self._validate_payment_declaration_scope(
                decision.context_id if decision is not None else None,
                request=request,
                evidence=evidence,
            )
            if payment_scope_error is not None:
                denied = _payment_denied_decision(
                    payment_scope_error,
                    decision=decision,
                    evidence=_with_payment_mismatch(evidence, payment_scope_error),
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )
            try:
                expected_amount = parse_amount(request.arguments.get("amount"))
                requested_currency = str(request.arguments.get("currency") or "").upper()
                transaction_kind = str(request.arguments.get("transaction_kind") or "")
                recurring = bool(request.arguments.get("recurring", False))
                observed = _observed_payment_total(evidence)
                actual_amount = expected_amount
                actual_currency = requested_currency
                payment_assurance: SafetyAssuranceLevel = "agent_asserted"
                if observed is not None:
                    observed_amount, observed_currency = observed
                    if observed_amount != expected_amount:
                        message = "Runtime-observed order total does not match the Agent-declared payment amount"
                        denied = _payment_denied_decision(
                            message,
                            decision=decision,
                            evidence=_with_payment_mismatch(
                                evidence,
                                message,
                                code="financial_amount_mismatch",
                            ),
                        )
                        current.safety = denied.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=denied,
                            data={"executed": False},
                        )
                    if observed_currency and observed_currency != requested_currency:
                        message = "Runtime-observed order currency does not match the Agent-declared payment currency"
                        denied = _payment_denied_decision(
                            message,
                            decision=decision,
                            evidence=_with_payment_mismatch(
                                evidence,
                                message,
                                code="financial_currency_mismatch",
                            ),
                        )
                        current.safety = denied.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=denied,
                            data={"executed": False},
                        )
                    actual_amount = observed_amount
                    actual_currency = observed_currency or requested_currency
                    payment_assurance = "runtime_observed"

                target = _require_web_object(current, request.target)
                payment_authorization = self._payments.authorize(
                    instrument_id=str(request.arguments.get("instrument_id") or ""),
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    origin=_origin_from_url(current.url),
                    target_label=" ".join(
                        part for part in (target.name, target.description, target.text) if part
                    ),
                    amount=actual_amount,
                    currency=actual_currency,
                    transaction_kind=transaction_kind,
                    recurring=recurring,
                    assurance=payment_assurance,
                    enforce_financial_limits=payment_operation_commits,
                )
            except PaymentInstrumentError as exc:
                denied = _payment_denied_decision(
                    str(exc),
                    decision=decision,
                    evidence=_with_payment_mismatch(evidence, str(exc), code=exc.code),
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )

            evidence = _with_payment_authorization(evidence, payment_authorization)
            if payment_authorization.decision not in {"allow", "allow_with_audit"}:
                if payment_authorization.decision == "require_step_up":
                    reason, current_scope, requested_scope = _payment_step_up_scope(payment_authorization)
                    requested_scope = _bind_web_operation_scope(
                        requested_scope,
                        current,
                        request.target,
                    )
                    if supplied_step_up_id is not None and authorized_step_up_id is None:
                        try:
                            self._step_ups.authorize(
                                supplied_step_up_id,
                                context_id=decision.context_id if decision is not None else None,
                                agent_id=active_agent_id,
                                profile_id=snapshot.profile_id,
                                origin=_origin_from_url(current.url),
                                target_object_id=request.target,
                                operation=request.operation,
                                requested_scope=requested_scope,
                            )
                            authorized_step_up_id = supplied_step_up_id
                            payment_authorization = replace(
                                payment_authorization,
                                decision="allow_with_audit",
                                status="ready",
                                message="Approved step-up grant covers the payment scope escalation",
                                mismatches=(),
                            )
                        except StepUpError as exc:
                            blocked = SafetyDecision(
                                decision="require_step_up",
                                status="step_up_required",
                                context_id=decision.context_id if decision is not None else None,
                                message=str(exc),
                                contract=decision.contract if decision is not None else None,
                                state=decision.state if decision is not None else None,
                                evidence_report=evidence,
                                step_up=_safe_step_up_get(self._step_ups, supplied_step_up_id),
                            )
                            current.safety = blocked.state
                            return WebOperationResult(
                                ok=False,
                                target=request.target,
                                operation=request.operation,
                                document_revision=current.document_revision,
                                state=current,
                                safety_decision=blocked,
                                data={"executed": False},
                            )
                    else:
                        step_up = self._step_ups.request(
                            reason=reason,
                            context_id=decision.context_id if decision is not None else None,
                            agent_id=active_agent_id,
                            profile_id=snapshot.profile_id,
                            origin=_origin_from_url(current.url),
                            target_object_id=request.target,
                            operation=request.operation,
                            message=payment_authorization.message,
                            current_scope=current_scope,
                            requested_scope=requested_scope,
                        )
                        blocked = SafetyDecision(
                            decision="require_step_up",
                            status="step_up_required",
                            context_id=decision.context_id if decision is not None else None,
                            message=payment_authorization.message,
                            contract=decision.contract if decision is not None else None,
                            state=decision.state if decision is not None else None,
                            evidence_report=evidence,
                            step_up=step_up,
                        )
                        current.safety = blocked.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=blocked,
                            data={"executed": False, "step_up_id": step_up.request.step_up_id},
                        )
                else:
                    blocked = SafetyDecision(
                        decision=payment_authorization.decision,
                        status=payment_authorization.status,  # type: ignore[arg-type]
                        context_id=decision.context_id if decision is not None else None,
                        message=payment_authorization.message,
                        contract=decision.contract if decision is not None else None,
                        state=decision.state if decision is not None else None,
                        evidence_report=evidence,
                    )
                    current.safety = blocked.state
                    return WebOperationResult(
                        ok=False,
                        target=request.target,
                        operation=request.operation,
                        document_revision=current.document_revision,
                        state=current,
                        safety_decision=blocked,
                        data={"executed": False},
                    )
            if decision is not None and decision.context_id is not None:
                decision = self._safety_contexts.apply_evidence(
                    decision.context_id,
                    evidence,
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    current_origin=_origin_from_url(current.url),
                )
                if decision.decision not in {"allow", "allow_with_audit"}:
                    current.safety = decision.state
                    return WebOperationResult(
                        ok=False,
                        target=request.target,
                        operation=request.operation,
                        document_revision=current.document_revision,
                        state=current,
                        safety_decision=decision,
                        data={"executed": False},
                    )

        financial_commit_authorization: FinancialAuthorization | PaymentAuthorization | None = None
        if request.operation != "provide_payment_instrument" and _is_final_financial_commit(request, evidence):
            financial_scope, financial_scope_error = self._resolve_financial_commit_scope(
                decision.context_id if decision is not None else None,
                evidence=evidence,
            )
            if financial_scope_error is not None or financial_scope is None:
                message = financial_scope_error or "financial commitment scope is unavailable"
                denied = _payment_denied_decision(
                    message,
                    decision=decision,
                    evidence=_with_payment_mismatch(evidence, message),
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )

            try:
                metadata = self._profile_policies.get(snapshot.profile_id)
                policy_id = metadata.financial_policy_id
                instrument_id = financial_scope["instrument_id"]
                if instrument_id:
                    selection_error = self._selected_payment_error(
                        instrument_id=instrument_id,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        state=current,
                        amount=financial_scope["amount"],
                        currency=financial_scope["currency"],
                        transaction_kind=financial_scope["transaction_kind"],
                        recurring=financial_scope["recurring"],
                    )
                    if selection_error is not None:
                        raise PaymentInstrumentError(
                            "payment_instrument_scope_mismatch",
                            selection_error,
                        )
                    instrument_state = self._payments.get_instrument(instrument_id)
                    instrument_policy_id = instrument_state.instrument.policy_id
                    if policy_id is not None and policy_id != instrument_policy_id:
                        raise PaymentInstrumentError(
                            "payment_instrument_scope_mismatch",
                            "declared payment instrument does not use the active Profile financial policy",
                        )
                    policy_id = instrument_policy_id
                    financial_commit_authorization = self._payments.authorize(
                        instrument_id=instrument_id,
                        agent_id=active_agent_id,
                        profile_id=snapshot.profile_id,
                        origin=_origin_from_url(current.url),
                        target_label=None,
                        amount=financial_scope["amount"],
                        currency=financial_scope["currency"],
                        transaction_kind=financial_scope["transaction_kind"],
                        recurring=financial_scope["recurring"],
                        assurance=financial_scope["assurance"],
                        enforce_financial_limits=True,
                    )
                elif policy_id is not None:
                    financial_commit_authorization = self._payments.authorize_policy(
                        policy_id=policy_id,
                        amount=financial_scope["amount"],
                        currency=financial_scope["currency"],
                        transaction_kind=financial_scope["transaction_kind"],
                        recurring=financial_scope["recurring"],
                        assurance=financial_scope["assurance"],
                        origin=_origin_from_url(current.url),
                    )
            except PaymentInstrumentError as exc:
                denied = _payment_denied_decision(
                    str(exc),
                    decision=decision,
                    evidence=_with_payment_mismatch(evidence, str(exc), code=exc.code),
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )

            if financial_commit_authorization is not None:
                evidence = _with_payment_authorization(evidence, financial_commit_authorization)
                if financial_commit_authorization.decision not in {"allow", "allow_with_audit"}:
                    if financial_commit_authorization.decision == "require_step_up":
                        if isinstance(financial_commit_authorization, PaymentAuthorization):
                            reason, current_scope, requested_scope = _payment_step_up_scope(
                                financial_commit_authorization
                            )
                        else:
                            reason, current_scope, requested_scope = _financial_step_up_scope(
                                financial_commit_authorization
                            )
                        requested_scope = _bind_web_operation_scope(
                            requested_scope,
                            current,
                            request.target,
                        )
                        if supplied_step_up_id is not None and authorized_step_up_id is None:
                            try:
                                self._step_ups.authorize(
                                    supplied_step_up_id,
                                    context_id=decision.context_id if decision is not None else None,
                                    agent_id=active_agent_id,
                                    profile_id=snapshot.profile_id,
                                    origin=_origin_from_url(current.url),
                                    target_object_id=request.target,
                                    operation=request.operation,
                                    requested_scope=requested_scope,
                                )
                                authorized_step_up_id = supplied_step_up_id
                                financial_commit_authorization = replace(
                                    financial_commit_authorization,
                                    decision="allow_with_audit",
                                    status="ready",
                                    message="Approved step-up grant covers the final financial commit",
                                    mismatches=(),
                                )
                            except StepUpError as exc:
                                blocked = SafetyDecision(
                                    decision="require_step_up",
                                    status="step_up_required",
                                    context_id=decision.context_id if decision is not None else None,
                                    message=str(exc),
                                    contract=decision.contract if decision is not None else None,
                                    state=decision.state if decision is not None else None,
                                    evidence_report=evidence,
                                    step_up=_safe_step_up_get(self._step_ups, supplied_step_up_id),
                                )
                                current.safety = blocked.state
                                return WebOperationResult(
                                    ok=False,
                                    target=request.target,
                                    operation=request.operation,
                                    document_revision=current.document_revision,
                                    state=current,
                                    safety_decision=blocked,
                                    data={"executed": False},
                                )
                        else:
                            step_up = self._step_ups.request(
                                reason=reason,
                                context_id=decision.context_id if decision is not None else None,
                                agent_id=active_agent_id,
                                profile_id=snapshot.profile_id,
                                origin=_origin_from_url(current.url),
                                target_object_id=request.target,
                                operation=request.operation,
                                message=financial_commit_authorization.message,
                                current_scope=current_scope,
                                requested_scope=requested_scope,
                            )
                            blocked = SafetyDecision(
                                decision="require_step_up",
                                status="step_up_required",
                                context_id=decision.context_id if decision is not None else None,
                                message=financial_commit_authorization.message,
                                contract=decision.contract if decision is not None else None,
                                state=decision.state if decision is not None else None,
                                evidence_report=evidence,
                                step_up=step_up,
                            )
                            current.safety = blocked.state
                            return WebOperationResult(
                                ok=False,
                                target=request.target,
                                operation=request.operation,
                                document_revision=current.document_revision,
                                state=current,
                                safety_decision=blocked,
                                data={"executed": False, "step_up_id": step_up.request.step_up_id},
                            )
                    else:
                        blocked = SafetyDecision(
                            decision=financial_commit_authorization.decision,
                            status=financial_commit_authorization.status,  # type: ignore[arg-type]
                            context_id=decision.context_id if decision is not None else None,
                            message=financial_commit_authorization.message,
                            contract=decision.contract if decision is not None else None,
                            state=decision.state if decision is not None else None,
                            evidence_report=evidence,
                        )
                        current.safety = blocked.state
                        return WebOperationResult(
                            ok=False,
                            target=request.target,
                            operation=request.operation,
                            document_revision=current.document_revision,
                            state=current,
                            safety_decision=blocked,
                            data={"executed": False},
                        )

        upload_path: str | None = None
        upload_resource_ref: str | None = None
        if request.operation == "upload":
            upload_resource_ref = str(request.arguments.get("resource_ref") or "")
            purpose = request.arguments.get("purpose")
            scope_error = self._validate_upload_declaration_scope(
                decision.context_id if decision is not None else None,
                resource_ref=upload_resource_ref,
                origin=_origin_from_url(current.url),
                purpose=purpose if isinstance(purpose, str) else None,
            )
            if scope_error is not None:
                evidence = _with_resource_mismatch(evidence, scope_error)
                denied = SafetyDecision(
                    decision="deny",
                    status="blocked",
                    context_id=decision.context_id if decision is not None else None,
                    message=scope_error,
                    contract=decision.contract if decision is not None else None,
                    state=decision.state if decision is not None else None,
                    evidence_report=evidence,
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )
            try:
                authorization = self._local_resources.authorize(
                    upload_resource_ref,
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    origin=_origin_from_url(current.url),
                    purpose=purpose if isinstance(purpose, str) else None,
                )
            except LocalResourceError as exc:
                evidence = _with_resource_mismatch(evidence, str(exc), code=exc.code)
                denied = SafetyDecision(
                    decision="deny",
                    status="blocked",
                    context_id=decision.context_id if decision is not None else None,
                    message=str(exc),
                    contract=decision.contract if decision is not None else None,
                    state=decision.state if decision is not None else None,
                    evidence_report=evidence,
                )
                current.safety = denied.state
                return WebOperationResult(
                    ok=False,
                    target=request.target,
                    operation=request.operation,
                    document_revision=current.document_revision,
                    state=current,
                    safety_decision=denied,
                    data={"executed": False},
                )
            upload_path = str(authorization.path)
            evidence = _with_resource_authorization(evidence, authorization.grant)
            if decision is not None and decision.context_id is not None:
                decision = self._safety_contexts.apply_evidence(
                    decision.context_id,
                    evidence,
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    current_origin=_origin_from_url(current.url),
                )

        result = self._call("act_web", request, upload_path)
        result.state.agent = self._agent_state(snapshot)
        operation_executed = not (
            result.data
            and (
                result.data.get("takeover_requested") is True
                or result.data.get("no_op") is True
            )
        )
        if upload_resource_ref is not None and operation_executed:
            self._local_resources.consume(upload_resource_ref)
        if authorized_step_up_id is not None and operation_executed:
            self._step_ups.consume(authorized_step_up_id)
        if payment_authorization is not None and operation_executed:
            result.data = {
                **(result.data or {}),
                "payment_instrument": {
                    "type": payment_authorization.instrument.type,
                    "brand": payment_authorization.instrument.brand,
                    "last4": payment_authorization.instrument.last4,
                },
            }
            if payment_operation_commits:
                usage = self._payments.record_use(payment_authorization)
                self._selected_payment = None
                result.data["financial_commitment"] = {
                    "amount": str(payment_authorization.amount),
                    "currency": payment_authorization.currency,
                    "transaction_kind": payment_authorization.transaction_kind,
                    "assurance": payment_authorization.assurance,
                    "committed": True,
                }
                result.data["financial_usage"] = usage.model_dump(mode="json")
            else:
                self._selected_payment = _SelectedPaymentInstrument(
                    agent_id=active_agent_id,
                    profile_id=snapshot.profile_id,
                    document_id=current.document_id,
                    origin=_origin_from_url(current.url),
                    target_object_id=request.target,
                    instrument_id=payment_authorization.instrument.instrument_id,
                    amount=payment_authorization.amount,
                    currency=payment_authorization.currency,
                    transaction_kind=payment_authorization.transaction_kind,
                    recurring=bool(request.arguments.get("recurring", False)),
                    assurance=payment_authorization.assurance,
                )
                result.data["payment_selection"] = {
                    "amount": str(payment_authorization.amount),
                    "currency": payment_authorization.currency,
                    "transaction_kind": payment_authorization.transaction_kind,
                    "assurance": payment_authorization.assurance,
                    "committed": False,
                }
        if financial_commit_authorization is not None and operation_executed:
            usage = self._payments.record_use(financial_commit_authorization)
            self._selected_payment = None
            result.data = {
                **(result.data or {}),
                "financial_commitment": {
                    "amount": str(financial_commit_authorization.amount),
                    "currency": financial_commit_authorization.currency,
                    "transaction_kind": financial_commit_authorization.transaction_kind,
                    "assurance": financial_commit_authorization.assurance,
                    "committed": True,
                },
                "financial_usage": usage.model_dump(mode="json"),
            }
            if isinstance(financial_commit_authorization, PaymentAuthorization):
                result.data["payment_instrument"] = {
                    "type": financial_commit_authorization.instrument.type,
                    "brand": financial_commit_authorization.instrument.brand,
                    "last4": financial_commit_authorization.instrument.last4,
                }
        if decision is not None and decision.context_id is not None and operation_executed:
            consumed = self._safety_contexts.consume(
                decision.context_id,
                agent_id=active_agent_id,
                profile_id=snapshot.profile_id,
                current_origin=_origin_from_url(result.state.url),
            )
            result.state.safety = consumed
            result.safety_decision = decision.model_copy(update={"state": consumed})
        elif decision is not None:
            result.state.safety = decision.state
            result.safety_decision = decision
        else:
            result.state.safety = self._current_safety_state(snapshot, result.state)
        return result

    def _selected_payment_error(
        self,
        *,
        instrument_id: str,
        agent_id: str,
        profile_id: str,
        state: WebState,
        amount: Decimal,
        currency: str,
        transaction_kind: str,
        recurring: bool,
    ) -> str | None:
        selected = self._selected_payment
        if selected is None:
            return "declared payment instrument was not selected on the current document"
        expected = (
            agent_id,
            profile_id,
            state.document_id,
            _origin_from_url(state.url),
            instrument_id,
            amount,
            currency.upper(),
            transaction_kind,
            recurring,
        )
        actual = (
            selected.agent_id,
            selected.profile_id,
            selected.document_id,
            selected.origin,
            selected.instrument_id,
            selected.amount,
            selected.currency,
            selected.transaction_kind,
            selected.recurring,
        )
        if actual != expected:
            return "selected payment instrument or transaction scope no longer matches the final commit"
        selected_object = next(
            (
                item
                for item in state.objects
                if isinstance(item, WebObject) and item.id == selected.target_object_id
            ),
            None,
        )
        if selected_object is None:
            return "selected payment instrument control is no longer present on the current document"
        if (
            selected_object.role in {"radio", "checkbox", "option"}
            and selected_object.state.checked is not True
            and selected_object.state.selected is not True
        ):
            return "selected payment instrument control is no longer active on the current document"
        return None

    def _validate_payment_declaration_scope(
        self,
        context_id: str | None,
        *,
        request: WebOperationRequest,
        evidence: SafetyEvidenceReport,
    ) -> str | None:
        if context_id is None:
            return "payment instrument use requires a task-scoped safety context"
        declaration = self._safety_contexts.declaration_for(context_id)
        if declaration is None:
            return "payment safety context was not found"
        financial_dimensions = [
            dimension
            for dimension in declaration.dimensions
            if dimension.type == "financial_commitment"
        ]
        if not financial_dimensions:
            return "payment safety declaration must include financial_commitment"
        dimension = financial_dimensions[0]
        instrument_id = str(request.arguments.get("instrument_id") or "")
        transaction_kind = str(request.arguments.get("transaction_kind") or "")
        currency = str(request.arguments.get("currency") or "").upper()
        try:
            amount = parse_amount(request.arguments.get("amount"))
        except PaymentInstrumentError as exc:
            return str(exc)
        if dimension.payment_instrument_ref and dimension.payment_instrument_ref != instrument_id:
            return "payment instrument is outside the declared financial commitment scope"
        if dimension.kind != transaction_kind:
            return "payment transaction kind does not match the declared financial commitment"
        if dimension.currency != currency:
            return "payment currency does not match the declared financial commitment"
        if dimension.maximum_amount is not None and amount > dimension.maximum_amount:
            return "payment amount exceeds the declared financial commitment maximum"
        recurring = bool(request.arguments.get("recurring", False))
        declared_recurring = any(
            item.type == "recurring_commitment"
            for item in declaration.dimensions
        )
        if recurring and not declared_recurring:
            return "recurring payment requires a separate recurring_commitment declaration"
        if "recurring_commitment" in evidence.observed_dimensions and not declared_recurring:
            return "Runtime observed a recurring commitment outside the declared safety scope"
        return None

    def _resolve_financial_commit_scope(
        self,
        context_id: str | None,
        *,
        evidence: SafetyEvidenceReport,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if context_id is None:
            return None, "final financial commit requires a task-scoped safety context"
        declaration = self._safety_contexts.declaration_for(context_id)
        if declaration is None:
            return None, "financial safety context was not found"
        dimensions = [
            dimension
            for dimension in declaration.dimensions
            if dimension.type == "financial_commitment"
        ]
        if not dimensions:
            return None, "final financial commit requires financial_commitment in the safety declaration"
        dimension = dimensions[0]
        observed = _observed_payment_total(evidence)
        assurance: SafetyAssuranceLevel = "agent_asserted"
        if observed is not None:
            amount, observed_currency = observed
            currency = observed_currency or dimension.currency
            assurance = "runtime_observed"
            if observed_currency and observed_currency != dimension.currency:
                return None, "Runtime-observed order currency does not match the declared financial commitment"
        else:
            declared_amount = dimension.estimated_amount or dimension.maximum_amount
            if declared_amount is None:
                return None, "financial policy requires an observed or declared transaction amount"
            amount = parse_amount(declared_amount)
            currency = dimension.currency
        if dimension.maximum_amount is not None and amount > dimension.maximum_amount:
            return None, "Runtime-observed order total exceeds the declared financial commitment maximum"
        declared_recurring = any(
            item.type == "recurring_commitment"
            for item in declaration.dimensions
        )
        observed_recurring = "recurring_commitment" in evidence.observed_dimensions
        if observed_recurring and not declared_recurring:
            return None, "Runtime observed a recurring commitment outside the declared safety scope"
        return {
            "amount": amount,
            "currency": currency,
            "transaction_kind": dimension.kind,
            "recurring": declared_recurring or observed_recurring,
            "assurance": assurance,
            "instrument_id": dimension.payment_instrument_ref or "",
        }, None

    def _payment_receipt(
        self,
        *,
        decision: SafetyDecision,
        request: WebOperationRequest,
        profile_id: str,
        agent_id: str,
        origin: str,
        before_revision: int,
        after_revision: int,
    ) -> SafetyReceipt:
        contract = decision.contract
        return SafetyReceipt(
            receipt_id=f"receipt_{uuid4().hex}",
            context_id=decision.context_id or "",
            agent_id=agent_id,
            profile_id=profile_id,
            origin=origin,
            target_object_id=request.target,
            operation=request.operation,
            p10_effect="external_write",
            safety_dimensions=(contract.active_dimensions if contract is not None else []),
            assertion_refs=(contract.required_assertions if contract is not None else []),
            hard_boundary_decision=decision.decision,
            final_decision="allow_with_audit",
            before_revision=before_revision,
            after_revision=after_revision,
            result="executed",
            message=decision.message,
            authority_source=_authority_source(self._safety_contexts, decision.context_id),
            step_up_id=request.safety.step_up_id if request.safety is not None else None,
            timestamp=datetime.now(timezone.utc),
        )

    def _generic_open_receipt(
        self,
        request: WebOpenRequest,
        result: WebOpenResult,
    ) -> SafetyReceipt:
        decision = result.safety_decision
        assert decision is not None
        step_up = decision.step_up
        metadata: dict[str, StepUpScopeScalar] = {}
        if step_up is not None:
            metadata["step_up_status"] = step_up.status
            metadata["step_up_reason"] = step_up.request.reason
        authority_source = None
        if decision.context_id is not None:
            authority_source = _authority_source(self._safety_contexts, decision.context_id)
        elif request.safety is not None and request.safety.declaration is not None:
            authority_source = _authority_source_fingerprint(
                request.safety.declaration.authorization_claim.source_ref
            )
        return SafetyReceipt(
            receipt_id=f"receipt_{uuid4().hex}",
            context_id=decision.context_id or "unscoped",
            agent_id=result.state.agent.active_agent_id or "anonymous-mcp",
            profile_id=result.state.agent.profile_id or "default",
            origin=_origin_from_url(result.url),
            target_object_id="navigation",
            operation="open_url",
            p10_effect="navigation",
            safety_dimensions=(decision.contract.active_dimensions if decision.contract is not None else []),
            assertion_refs=(decision.contract.required_assertions if decision.contract is not None else []),
            hard_boundary_decision=decision.decision,
            final_decision=decision.decision,
            before_revision=0,
            after_revision=result.state.document_revision,
            result="executed" if result.ok else ("denied" if decision.decision == "deny" else "not_executed"),
            message=decision.message,
            authority_source=authority_source,
            step_up_id=(
                step_up.request.step_up_id
                if step_up is not None
                else (request.safety.step_up_id if request.safety is not None else None)
            ),
            metadata=metadata,
            timestamp=datetime.now(timezone.utc),
        )

    def _generic_safety_receipt(
        self,
        request: WebOperationRequest,
        result: WebOperationResult,
    ) -> SafetyReceipt:
        decision = result.safety_decision
        assert decision is not None
        takeover = bool(result.data and result.data.get("takeover_requested"))
        no_op = bool(result.data and result.data.get("no_op"))
        if takeover:
            outcome = "takeover"
        elif result.ok and not no_op:
            outcome = "executed"
        elif decision.decision == "deny":
            outcome = "denied"
        else:
            outcome = "not_executed"
        contract = decision.contract
        evidence = decision.evidence_report
        step_up = decision.step_up
        metadata: dict[str, StepUpScopeScalar] = {}
        if step_up is not None:
            metadata["step_up_status"] = step_up.status
            metadata["step_up_reason"] = step_up.request.reason
        return SafetyReceipt(
            receipt_id=f"receipt_{uuid4().hex}",
            context_id=decision.context_id or "unscoped",
            agent_id=result.state.agent.active_agent_id or "anonymous-mcp",
            profile_id=result.state.agent.profile_id or "default",
            origin=_origin_from_url(result.state.url),
            target_object_id=request.target,
            operation=request.operation,
            p10_effect=evidence.p10_effect if evidence is not None else "unknown",
            safety_dimensions=(contract.active_dimensions if contract is not None else (evidence.observed_dimensions if evidence is not None else [])),
            assertion_refs=(contract.required_assertions if contract is not None else []),
            hard_boundary_decision=decision.decision,
            final_decision=decision.decision,
            before_revision=request.expected_document_revision or result.document_revision,
            after_revision=result.document_revision,
            result=outcome,  # type: ignore[arg-type]
            message=decision.message,
            authority_source=_authority_source(self._safety_contexts, decision.context_id),
            step_up_id=(
                step_up.request.step_up_id
                if step_up is not None
                else (request.safety.step_up_id if request.safety is not None else None)
            ),
            metadata=metadata,
            timestamp=datetime.now(timezone.utc),
        )

    def _validate_upload_declaration_scope(
        self,
        context_id: str | None,
        *,
        resource_ref: str,
        origin: str,
        purpose: str | None,
    ) -> str | None:
        if context_id is None:
            return "upload requires a task-scoped safety context"
        declaration = self._safety_contexts.declaration_for(context_id)
        if declaration is None:
            return "upload safety context was not found"
        dimensions = [
            dimension
            for dimension in declaration.dimensions
            if dimension.type == "local_data_egress"
        ]
        if not dimensions:
            return "upload safety declaration must include local_data_egress"
        dimension = dimensions[0]
        if resource_ref not in dimension.resource_refs:
            return "resource_ref is outside the declared local_data_egress scope"
        declared_origin = _normalize_origin_scope(dimension.destination_origin)
        if declared_origin != origin:
            return "current origin does not match the declared local_data_egress destination"
        if purpose is not None and purpose.strip() != dimension.purpose:
            return "upload purpose does not match the declared local_data_egress purpose"
        return None

    def tabs(self) -> list[BrowserTab]:
        return self._call("tabs")

    def switch_tab(self, tab_id: str, agent_id: str | None = None) -> BrowserState:
        with self._web_operation_lock:
            self._require_agent_control_available()
            self._agent_lease.acquire(agent_id)
            self._selected_payment = None
            return self._with_agent_state(self._call("switch_tab", tab_id))

    def capture_preview(self) -> str | None:
        if self._closed:
            return None
        if self._thread is None:
            return None
        try:
            return self._call("capture_preview")
        except Exception:
            return None

    def restart_host(self) -> BrowserState:
        with self._web_operation_lock:
            self._require_agent_control_available()
            self._selected_payment = None
            return self._with_agent_state(self._call("restart_host"))

    def relaunch_visible_host(self) -> BrowserState:
        raise auth_surface_retired_error()

    def open_auth_surface(self, url: str | None = None) -> BrowserState:
        _ = url
        raise auth_surface_retired_error()

    def close_auth_surface(self, url: str | None = None) -> BrowserState:
        _ = url
        raise auth_surface_retired_error()

    def _record_human_input_state(self, event: HumanInputEvent) -> None:
        if event.type == "mouse_down":
            self._human_pointer_down = event
            return
        if event.type == "mouse_move" and self._human_pointer_down is not None:
            self._human_pointer_down = replace(
                self._human_pointer_down,
                x=event.x,
                y=event.y,
                buttons=event.buttons,
            )
            return
        if event.type == "mouse_up":
            self._human_pointer_down = None
            return
        if event.type == "key_down":
            key = (event.key or "", event.code or "")
            self._human_pressed_keys[key] = HumanInputEvent(
                type="key_down",
                key=event.key,
                code=event.code,
                modifiers=event.modifiers,
                auto_repeat=False,
            )
            return
        if event.type == "key_up":
            self._human_pressed_keys.pop((event.key or "", event.code or ""), None)

    def _release_stuck_human_inputs(self) -> None:
        pointer = self._human_pointer_down
        pressed_keys = tuple(self._human_pressed_keys.values())
        self._human_pointer_down = None
        self._human_pressed_keys.clear()
        if self._thread is None or self._closed:
            return
        if pointer is not None and pointer.x is not None and pointer.y is not None:
            try:
                self._call(
                    "dispatch_human_input",
                    HumanInputEvent(
                        type="mouse_up",
                        x=pointer.x,
                        y=pointer.y,
                        button=pointer.button,
                        buttons=0,
                        click_count=1,
                        modifiers=pointer.modifiers,
                    ),
                )
            except Exception:
                pass
        for key_event in pressed_keys:
            try:
                self._call(
                    "dispatch_human_input",
                    HumanInputEvent(
                        type="key_up",
                        key=key_event.key,
                        code=key_event.code,
                        modifiers=key_event.modifiers,
                    ),
                )
            except Exception:
                continue

    def _reconcile_human_control_expiry(self) -> None:
        with self._web_operation_lock:
            expired = self._human_control.pop_expired_cleanup()
            if expired is None:
                return
            if self._thread is not None and not self._closed:
                try:
                    self._release_stuck_human_inputs()
                    self._call("end_human_control", True)
                except Exception:
                    pass
            if expired.active_agent_id is not None:
                self._agent_lease.acquire(expired.active_agent_id)

    def _require_agent_control_available(self) -> None:
        self._reconcile_human_control_expiry()
        if self._human_control.active() is not None:
            raise human_control_active_error()

    def status(self) -> dict[str, Any]:
        self._reconcile_human_control_expiry()
        snapshot = self._agent_lease.snapshot()
        lease = snapshot.as_dict()
        metadata = self._profile_policies.get(snapshot.profile_id)
        base = {
            "selected_driver": self._driver_name,
            "headless": self._headless,
            "auth_takeover": self._auth_takeover,
            "auth_surface_mode": self._auth_surface_mode,
            "visible_window": False,
            "session_id": "default",
            "profile_id": snapshot.profile_id,
            "profile_shared": metadata.owner == "shared",
            "profile_owner": metadata.owner,
            "profile_trust_mode": metadata.trust_mode,
            "unknown_external_effect_policy": metadata.unknown_external_effect_policy,
            **lease,
            "host_status": "not_started",
            "last_error": None,
        }
        if self._closed:
            return {**base, "host_status": "closed"}
        if self._thread is None:
            return base
        try:
            worker_status = self._call("status")
            return {**base, **worker_status}
        except Exception as exc:
            return {**base, "host_status": "error", "last_error": str(exc)}

    def _publish_safety_event(
        self,
        decision: SafetyDecision,
        state: WebState,
        *,
        operation: str,
    ) -> None:
        step_up_id = (
            decision.step_up.request.step_up_id
            if decision.step_up is not None
            else None
        )
        data: dict[str, Any] = {
            "operation": operation,
            "decision": decision.decision,
            "status": decision.status,
            "requires_user_attention": decision.decision in {
                "require_step_up",
                "require_takeover",
                "deny",
            },
        }
        if decision.context_id is not None:
            data["context_id"] = decision.context_id
        if step_up_id is not None:
            data["step_up_id"] = step_up_id
        self._session_events.publish(
            "safety_decision_changed",
            session_id=state.session_id or "default",
            document_id=state.document_id or None,
            data=data,
        )

    def close(self) -> None:
        with self._web_operation_lock:
            if self._closed:
                return
            try:
                self._reconcile_human_control_expiry()
                active_human = self._human_control.active()
                if active_human is not None:
                    try:
                        if self._thread is not None:
                            self._release_stuck_human_inputs()
                            self._call("end_human_control", True)
                    except Exception:
                        pass
                    finally:
                        try:
                            self._human_control.release(
                                lease_id=active_human.lease_id,
                                connection_id=active_human.connection_id,
                                status="aborted",
                            )
                        except HumanControlError:
                            pass
                if self._thread is None:
                    return
                result: queue.Queue = queue.Queue(maxsize=1)
                self._jobs.put(("close", (), result))
                ok, value = result.get(timeout=30)
                self._thread.join(timeout=30)
                if not ok:
                    raise value
            finally:
                self._closed = True
                self._local_resources.close()
                self._session_events.close()

    def _call(self, name: str, *args: Any) -> Any:
        if self._closed:
            raise RuntimeError("browser runtime is closed")
        self._ensure_thread()
        result: queue.Queue = queue.Queue(maxsize=1)
        self._jobs.put((name, args, result))
        ok, value = result.get(timeout=60)
        if ok:
            return value
        raise value

    def _ensure_thread(self) -> None:
        if self._thread is not None:
            return
        worker = _BrowserWorker(
            self._driver_factory,
            headless=self._headless,
            auth_takeover=self._auth_takeover,
            auth_surface_mode=self._auth_surface_mode,
            private_url_policy=self._private_url_policy,
            event_bus=self._session_events,
        )
        self._thread = threading.Thread(target=worker.run, args=(self._jobs,), name="webfa-browser", daemon=True)
        self._thread.start()

    def _current_safety_state(self, snapshot: AgentLeaseSnapshot, state: WebState):
        if snapshot.active_agent_id is None:
            return None
        return self._safety_contexts.current_state(
            agent_id=snapshot.active_agent_id,
            profile_id=snapshot.profile_id,
            current_origin=_origin_from_url(state.url),
        )

    def _with_agent_result(self, result: BrowserActionResult) -> BrowserActionResult:
        result.state = self._with_agent_state(result.state)
        return result

    def _with_agent_state(self, state: BrowserState) -> BrowserState:
        state.agent = self._agent_state(self._agent_lease.snapshot())
        return state

    def _agent_state(self, snapshot: AgentLeaseSnapshot) -> BrowserAgentState:
        metadata = self._profile_policies.get(snapshot.profile_id)
        return _agent_state_from_snapshot(snapshot, metadata)


def _agent_state_from_snapshot(
    snapshot: AgentLeaseSnapshot,
    metadata: ProfileOwnershipMetadata,
) -> BrowserAgentState:
    return BrowserAgentState(
        active_agent_id=snapshot.active_agent_id,
        agent_lease_expires_at=snapshot.expires_at.isoformat() if snapshot.expires_at else None,
        profile_shared=metadata.owner == "shared",
        profile_id=snapshot.profile_id,
        profile_owner=metadata.owner,
        trust_mode=metadata.trust_mode,
        unknown_external_effect_policy=metadata.unknown_external_effect_policy or "require_step_up",
    )


class _BrowserWorker:
    def __init__(
        self,
        driver_factory: DriverFactory,
        headless: bool,
        auth_takeover: str,
        auth_surface_mode: str,
        private_url_policy: str,
        event_bus: SessionEventBus,
    ) -> None:
        self._session = BrowserSession(driver_factory=driver_factory)
        self._view_builder = AgentViewBuilder()
        self._web_compiler = WebObjectCompiler()
        self._object_registry = ObjectRegistry()
        self._web_observe = WebObserveService(self._object_registry)
        self._semantic_operations = SemanticOperationExecutor(self._object_registry)
        self._safety_evidence = RuntimeEvidenceResolver()
        self._headless = headless
        self._auth_takeover = auth_takeover
        self._auth_surface_mode = auth_surface_mode
        self._private_url_policy = private_url_policy
        self._event_bus = event_bus
        self._visual_provider: BoundVisualSurfaceProvider | None = None
        self._visual_binding_lock = threading.RLock()
        self._visual_binding = VisualSurfaceBinding(
            session_id=self._session.session_id,
            tab_id="tab_1",
            document_id="",
        )
        self._auth_surface_active = False
        self._auth_surface_url: str | None = None
        self._takeover_reason: TakeoverReason | None = None
        self._takeover_target: str | None = None
        self._takeover_origin: str = ""

    def run(self, jobs: queue.Queue) -> None:
        handlers: dict[str, Callable[..., Any]] = {
            "open": self.open,
            "observe": self.observe,
            "observe_web": self.observe_web,
            "act": self.act,
            "act_web": self.act_web,
            "operation_evidence": self.operation_evidence,
            "request_safety_takeover": self.request_safety_takeover,
            "tabs": self.tabs,
            "switch_tab": self.switch_tab,
            "close": self.close,
            "status": self.status,
            "capture_preview": self.capture_preview,
            "start_visual_stream": self.start_visual_stream,
            "stop_visual_stream": self.stop_visual_stream,
            "visual_stream_status": self.visual_stream_status,
            "monitor_snapshot": self.monitor_snapshot,
            "begin_human_control": self.begin_human_control,
            "dispatch_human_input": self.dispatch_human_input,
            "sync_human_control_state": self.sync_human_control_state,
            "end_human_control": self.end_human_control,
            "restart_host": self.restart_host,
            "relaunch_visible_host": self.relaunch_visible_host,
            "open_auth_surface": self.open_auth_surface,
            "close_auth_surface": self.close_auth_surface,
        }
        self._event_bus.publish("session_started", session_id=self._session.session_id)
        while True:
            job = jobs.get()
            if job is None:
                return
            name, args, result = job
            try:
                value = handlers[name](*args)
                result.put((True, value))
                if name == "close":
                    return
            except Exception as exc:
                self._publish_job_failure(name, args, exc)
                result.put((False, exc))

    def open(self, url: str) -> BrowserActionResult:
        operation_id = f"nav_{uuid4().hex}"
        self._event_bus.publish(
            "navigation_started",
            session_id=self._session.session_id,
            operation_id=operation_id,
            data={"origin": _origin_from_url(url)},
        )
        self._clear_takeover()
        enforce_navigation_allowed(url, policy=self._private_url_policy)  # type: ignore[arg-type]
        if self._host_is_exited():
            self._session.reset()
        driver = self._ensure_driver()
        self._invalidate_visual_document()
        driver.open(url)
        state = self._state_after_navigation(driver)
        try:
            self._refresh_web_state(driver)
        except WebObserveUnavailableError:
            pass
        binding = self._current_visual_binding()
        self._event_bus.publish(
            "navigation_committed",
            session_id=self._session.session_id,
            tab_id=binding.tab_id,
            document_id=binding.document_id or None,
            operation_id=operation_id,
            data={"origin": _origin_from_url(state.url)},
        )
        return BrowserActionResult(ok=True, action="open_url", state=state)

    def observe(self) -> BrowserState:
        if self._auth_surface_active:
            return self._auth_surface_state()
        if self._session.driver is None:
            return BrowserState()
        self._raise_if_host_exited()
        return self._state_from_raw(self._session.driver.observe_raw())

    def observe_web(self, request: WebObserveRequest, allow_debug: bool = False) -> WebObserveResult:
        if request.detail == "debug" and not allow_debug:
            raise WebObserveDebugForbiddenError("debug observe is local-only")
        if self._auth_surface_active:
            if request.mode == "changes":
                raise WebObserveUnavailableError("changes are unavailable while human takeover is active")
            legacy = self._auth_surface_state()
            reason = self._takeover_reason or "authentication"
            return WebObserveResult(
                state=WebState(
                    session_id=legacy.session_id,
                    document_id="human_takeover",
                    document_revision=self._object_registry.current_revision,
                    url=legacy.url,
                    title=legacy.title,
                    auth=legacy.auth,
                    takeover=HumanTakeoverState(
                        required=True,
                        reason=reason,
                        target=self._takeover_target,
                        origin=self._takeover_origin,
                    ),
                )
            )
        if self._session.driver is None:
            raise WebObserveUnavailableError("browser host has not started")
        self._raise_if_host_exited()
        driver = self._session.driver
        self._refresh_web_state(driver)
        return self._web_observe.observe(request, allow_debug=allow_debug)

    def operation_evidence(self, request: WebOperationRequest) -> SafetyEvidenceReport:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        self._refresh_web_state(driver)
        plan = self._semantic_operations.plan(request)
        state = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
        return self._safety_evidence.resolve(
            target=plan.target,
            operation=request.operation,
            state=state,
        )

    def request_safety_takeover(self, target_id: str, reason: TakeoverReason) -> WebState:
        current = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
        target = self._object_registry.require(target_id)
        target_url = current.url or "about:blank"
        self._set_takeover(
            reason=reason,
            url=target_url,
            target=target.id,
            origin=target.origin,
        )
        state = current.model_copy(deep=True)
        state.document_id = "human_takeover"
        state.title = "WebFA Human Takeover"
        state.objects = []
        state.object_count = 0
        state.changes = None
        state.takeover = HumanTakeoverState(
            required=True,
            reason=reason,
            target=target.id,
            origin=target.origin,
        )
        if reason in {"authentication", "captcha", "biometric_verification"}:
            state.auth = BrowserAuthState(
                surface_detected=True,
                takeover="auth_surface",
                reason=[f"safety_takeover:{reason}"],
                user_action_required=True,
            )
        self._event_bus.publish(
            "takeover_required",
            session_id=self._session.session_id,
            tab_id=self._current_visual_binding().tab_id,
            document_id=current.document_id or None,
            data={"reason": reason, "target": target.id, "origin": target.origin},
        )
        return state

    def act_web(self, request: WebOperationRequest, upload_path: str | None = None) -> WebOperationResult:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        if self._driver_has_pending_dialog(driver) and request.operation != "dismiss":
            raise dialog_required_error()

        operation_id = f"op_{uuid4().hex}"
        current = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
        self._event_bus.publish(
            "operation_started",
            session_id=self._session.session_id,
            tab_id=self._current_visual_binding().tab_id,
            document_id=current.document_id or None,
            operation_id=operation_id,
            data={"operation": request.operation, "target": request.target},
        )

        plan = self._semantic_operations.plan(request)
        previous_version = plan.target.version
        if plan.takeover_reason is not None:
            result = self._request_web_takeover(plan)
            self._event_bus.publish(
                "takeover_required",
                session_id=self._session.session_id,
                tab_id=self._current_visual_binding().tab_id,
                document_id=current.document_id or None,
                operation_id=operation_id,
                data={
                    "reason": plan.takeover_reason,
                    "target": plan.target.id,
                    "origin": plan.target.origin,
                },
            )
            self._publish_operation_completed(operation_id, result)
            return result
        if plan.no_op:
            state = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
            result = WebOperationResult(
                ok=True,
                target=request.target,
                operation=request.operation,
                previous_object_version=previous_version,
                current_object_version=previous_version,
                document_revision=state.document_revision,
                state=state,
                data={"no_op": True},
            )
            self._publish_operation_completed(operation_id, result)
            return result

        if plan.upload_resource_ref is not None:
            if not upload_path or not plan.upload_legacy_target:
                raise ValueError("authorized upload resource is unavailable")
            uploader = getattr(driver, "upload_file", None)
            if not callable(uploader):
                raise ValueError("selected BrowserHost does not support protected file upload")
            uploader(plan.upload_legacy_target, upload_path)
        else:
            self._semantic_operations.execute(driver, plan)
        registered = self._refresh_web_state(driver)
        current_version: int | None = None
        try:
            current_version = self._object_registry.require(request.target).version
        except Exception:
            current_version = None
        result = WebOperationResult(
            ok=True,
            target=request.target,
            operation=request.operation,
            previous_object_version=previous_version,
            current_object_version=current_version,
            document_revision=registered.state.document_revision,
            state=registered.state,
        )
        self._publish_operation_completed(operation_id, result)
        return result

    def act(self, request: BrowserActionRequest) -> BrowserActionResult:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        if request.action in {"accept_dialog", "dismiss_dialog"}:
            return self._dialog_action(driver, request)
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        if request.action in {"fill_form", "submit_form", "follow_link", "activate_control", "choose_option", "read_list", "inspect_block"}:
            return self._object_action(driver, request)
        if request.target:
            if request.action == "type":
                state = self._state_from_raw(driver.observe_raw())
                element = _find_element(state, request.target)
                if _legacy_element_is_protected(element):
                    raise auth_surface_active_error()
            self._session.registry.require(request.target)
        driver.act(request)
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))

    def tabs(self) -> list[BrowserTab]:
        if self._auth_surface_active:
            return []
        if self._session.driver is None:
            return []
        self._raise_if_host_exited()
        return self._session.driver.tabs()

    def switch_tab(self, tab_id: str) -> BrowserState:
        if self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._ensure_driver()
        driver.switch_tab(tab_id)
        state = self._state_from_raw(driver.observe_raw())
        self._event_bus.publish(
            "tab_switched",
            session_id=self._session.session_id,
            tab_id=tab_id,
            data={"tab_id": tab_id},
        )
        return state

    def close(self) -> None:
        if self._visual_provider is not None:
            self._visual_provider.close()
            self._visual_provider = None
        self._session.close()
        self._event_bus.publish("session_closed", session_id=self._session.session_id)

    def status(self) -> dict[str, Any]:
        takeover = {
            "takeover_active": self._auth_surface_active,
            "takeover_reason": self._takeover_reason,
            "takeover_target": self._takeover_target,
            "takeover_origin": self._takeover_origin,
            "takeover_url": self._auth_surface_url,
        }
        if self._session.driver is None:
            return {"host_status": "not_started", **takeover}
        driver = self._session.driver
        if hasattr(driver, "status"):
            status = driver.status()
            if isinstance(status, dict):
                return {**status, **takeover}
        return {"host_status": "running", **takeover}

    def capture_preview(self) -> str | None:
        if self._session.driver is None:
            return None
        self._raise_if_host_exited()
        capture = getattr(self._session.driver, "capture_screenshot", None)
        if not callable(capture):
            return None
        return capture()

    def start_visual_stream(
        self,
        config: VisualStreamConfig,
        frame_sink: VisualFrameSink,
    ) -> str:
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        self._refresh_web_state(driver)
        backend_getter = getattr(driver, "visual_surface_backend", None)
        backend = backend_getter() if callable(backend_getter) else None
        if backend is None:
            raise RuntimeError("selected BrowserHost does not provide a visual surface backend")
        if self._visual_provider is None:
            self._visual_provider = BoundVisualSurfaceProvider(
                backend,
                event_bus=self._event_bus,
            )
        return self._visual_provider.start_stream(
            self._current_visual_binding,
            config,
            frame_sink,
        )

    def stop_visual_stream(self, stream_id: str) -> VisualStreamState:
        if self._visual_provider is None:
            raise KeyError(f"visual stream not found: {stream_id}")
        return self._visual_provider.stop_stream(stream_id)

    def visual_stream_status(self, stream_id: str | None = None) -> VisualStreamState | None:
        if self._visual_provider is None:
            return None
        return self._visual_provider.status(stream_id)

    def begin_human_control(self, reason: str) -> dict[str, Any]:
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        registered = self._refresh_web_state(driver)
        effective_reason = _normalize_takeover_reason(reason)
        if not self._auth_surface_active:
            self._set_takeover(
                reason=effective_reason,
                url=registered.state.url or "about:blank",
                target=None,
                origin=_origin_from_url(registered.state.url),
            )
        self._event_bus.publish(
            "takeover_started",
            session_id=self._session.session_id,
            tab_id=self._current_visual_binding().tab_id,
            document_id=registered.state.document_id or None,
            data={
                "reason": self._takeover_reason or effective_reason,
                "origin": self._takeover_origin or _origin_from_url(registered.state.url),
            },
        )
        return self.monitor_snapshot()

    def dispatch_human_input(self, event: HumanInputEvent) -> None:
        if not self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        dispatcher = getattr(driver, "dispatch_human_input", None)
        if not callable(dispatcher):
            raise RuntimeError("selected BrowserHost does not support human input")
        dispatcher(event)

    def sync_human_control_state(self) -> dict[str, Any]:
        if not self._auth_surface_active:
            raise auth_surface_active_error()
        self._raise_if_host_exited()
        driver = self._session.ensure_driver()
        self._refresh_web_state(driver)
        return self.monitor_snapshot()

    def end_human_control(self, aborted: bool = False) -> WebState:
        reason = self._takeover_reason or "manual_identity_confirmation"
        state = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
        if self._session.driver is not None and not self._host_is_exited():
            try:
                state = self._refresh_web_state(self._session.driver).state
            except Exception:
                state = self._object_registry.current_state() or state
        self._clear_takeover()
        state = state.model_copy(deep=True)
        state.takeover = HumanTakeoverState(required=False)
        try:
            self._event_bus.publish(
                "takeover_finished",
                session_id=self._session.session_id,
                tab_id=self._current_visual_binding().tab_id,
                document_id=state.document_id or None,
                data={"reason": reason, "aborted": aborted},
            )
        except RuntimeError:
            # Runtime shutdown may close the journal before final lease cleanup.
            pass
        return state

    def monitor_snapshot(self) -> dict[str, Any]:
        binding = self._current_visual_binding()
        state = self._object_registry.current_state()
        return {
            "session_id": self._session.session_id,
            "tab_id": binding.tab_id,
            "document_id": binding.document_id,
            "document_revision": state.document_revision if state is not None else 0,
            "url": _monitor_safe_url(state.url) if state is not None else "about:blank",
            "title": state.title if state is not None else "",
            "object_count": state.object_count if state is not None else 0,
            "takeover_required": self._auth_surface_active
            or (bool(state.takeover.required) if state is not None else False),
            "takeover_reason": self._takeover_reason
            or (
                state.takeover.reason
                if state is not None and state.takeover.required
                else None
            ),
        }

    def restart_host(self) -> BrowserState:
        self._clear_takeover()
        url = self._current_url_or_blank()
        self._session.reset()
        driver = self._ensure_driver()
        driver.open(url)
        return self._state_after_navigation(driver)

    def relaunch_visible_host(self) -> BrowserState:
        raise auth_surface_retired_error()

    def open_auth_surface(self, url: str | None = None) -> BrowserState:
        _ = url
        raise auth_surface_retired_error()

    def close_auth_surface(self, url: str | None = None) -> BrowserState:
        _ = url
        raise auth_surface_retired_error()

    def _auth_surface_state(self, url: str | None = None) -> BrowserState:
        reason = self._takeover_reason or "authentication"
        is_auth = reason == "authentication"
        return BrowserState(
            session_id=self._session.session_id,
            url=url or self._auth_surface_url or "about:blank",
            title="WebFA Human Takeover",
            auth=BrowserAuthState(
                surface_detected=is_auth,
                takeover="auth_surface" if is_auth else "none",
                reason=["human_control_active"],
                user_action_required=True,
            ),
        )

    def _set_takeover(
        self,
        *,
        reason: TakeoverReason,
        url: str,
        target: str | None,
        origin: str,
    ) -> None:
        self._auth_surface_active = True
        self._auth_surface_url = url
        self._takeover_reason = reason
        self._takeover_target = target
        self._takeover_origin = origin

    def _clear_takeover(self) -> None:
        self._auth_surface_active = False
        self._auth_surface_url = None
        self._takeover_reason = None
        self._takeover_target = None
        self._takeover_origin = ""

    def _current_url_or_blank(self) -> str:
        if self._session.driver is None:
            return "about:blank"
        if self._host_is_exited():
            return "about:blank"
        try:
            raw = self._session.driver.observe_raw()
            return raw.url or "about:blank"
        except Exception:
            return "about:blank"

    def _publish_operation_completed(
        self,
        operation_id: str,
        result: WebOperationResult,
    ) -> None:
        self._event_bus.publish(
            "operation_completed",
            session_id=self._session.session_id,
            tab_id=self._current_visual_binding().tab_id,
            document_id=result.state.document_id or None,
            operation_id=operation_id,
            data={
                "operation": result.operation,
                "target": result.target,
                "ok": result.ok,
                "document_revision": result.document_revision,
                "takeover_requested": bool(
                    result.data and result.data.get("takeover_requested")
                ),
            },
        )

    def _publish_job_failure(self, name: str, args: tuple, exc: Exception) -> None:
        if isinstance(exc, BrowserHostClosedError):
            try:
                self._event_bus.publish(
                    "browser_crashed",
                    session_id=self._session.session_id,
                    data={"error_type": type(exc).__name__},
                )
            except Exception:
                pass
            return
        try:
            if name == "open" and args:
                self._event_bus.publish(
                    "navigation_failed",
                    session_id=self._session.session_id,
                    data={
                        "origin": _origin_from_url(str(args[0])),
                        "error_type": type(exc).__name__,
                    },
                )
            elif name == "act_web" and args and isinstance(args[0], WebOperationRequest):
                request = args[0]
                self._event_bus.publish(
                    "operation_failed",
                    session_id=self._session.session_id,
                    tab_id=self._current_visual_binding().tab_id,
                    document_id=self._current_visual_binding().document_id or None,
                    data={
                        "operation": request.operation,
                        "target": request.target,
                        "error_type": type(exc).__name__,
                    },
                )
        except Exception:
            pass

    def _invalidate_visual_document(self) -> None:
        with self._visual_binding_lock:
            self._visual_binding = VisualSurfaceBinding(
                session_id=self._visual_binding.session_id,
                tab_id=self._visual_binding.tab_id,
                document_id="",
            )

    def _update_visual_binding(self, state: WebState, driver: BrowserDriver) -> None:
        tab_id = "tab_1"
        try:
            tabs = driver.tabs()
            active = next((tab for tab in tabs if tab.active), None)
            if active is not None:
                tab_id = active.id
            elif tabs:
                tab_id = tabs[0].id
        except Exception:
            pass
        with self._visual_binding_lock:
            self._visual_binding = VisualSurfaceBinding(
                session_id=state.session_id or self._session.session_id,
                tab_id=tab_id,
                document_id=state.document_id,
            )

    def _current_visual_binding(self) -> VisualSurfaceBinding:
        with self._visual_binding_lock:
            return self._visual_binding

    def _ensure_driver(self) -> BrowserDriver:
        return self._session.ensure_driver()

    def _host_is_exited(self) -> bool:
        driver = self._session.driver
        if driver is None or not hasattr(driver, "status"):
            return False
        status = driver.status()
        return isinstance(status, dict) and status.get("host_status") == "exited"

    def _raise_if_host_exited(self) -> None:
        if self._host_is_exited():
            raise BrowserHostClosedError()

    def _refresh_web_state(self, driver: BrowserDriver):
        observe_web_raw = getattr(driver, "observe_web_raw", None)
        if not callable(observe_web_raw):
            raise WebObserveUnavailableError("selected browser driver does not provide RawWebSnapshot")
        previous = self._object_registry.current_state()
        snapshot = observe_web_raw()
        try:
            enforce_navigation_allowed(snapshot.url, policy=self._private_url_policy)  # type: ignore[arg-type]
        except BrowserRuntimeError:
            self._session.reset()
            self._object_registry.clear()
            raise
        compilation = self._web_compiler.compile(
            snapshot,
            session_id=self._session.session_id,
        )
        registered = self._object_registry.update(compilation)
        self._update_visual_binding(registered.state, driver)
        if (
            previous is None
            or previous.document_id != registered.state.document_id
            or previous.document_revision != registered.state.document_revision
        ):
            changed_fields = (
                list(registered.changes.document_changed_fields)
                if registered.changes is not None
                else []
            )
            self._event_bus.publish(
                "document_changed",
                session_id=self._session.session_id,
                tab_id=self._current_visual_binding().tab_id,
                document_id=registered.state.document_id,
                data={
                    "document_revision": registered.state.document_revision,
                    "changed_fields": changed_fields,
                    "object_count": registered.state.object_count,
                },
            )
        return registered

    def _request_web_takeover(self, plan: WebOperationPlan) -> WebOperationResult:
        current = self._object_registry.current_state() or WebState(session_id=self._session.session_id)
        target_url = current.url or "about:blank"
        self._set_takeover(
            reason=plan.takeover_reason,
            url=target_url,
            target=plan.target.id,
            origin=plan.target.origin,
        )
        state = current.model_copy(deep=True)
        state.document_id = "human_takeover"
        state.title = "WebFA Human Takeover"
        state.objects = []
        state.object_count = 0
        state.changes = None
        state.takeover = HumanTakeoverState(
            required=True,
            reason=plan.takeover_reason,
            target=plan.target.id,
            origin=plan.target.origin,
        )
        if plan.takeover_reason == "authentication":
            state.auth = BrowserAuthState(
                surface_detected=True,
                takeover="auth_surface",
                reason=["semantic_takeover_requested"],
                user_action_required=True,
            )
        return WebOperationResult(
            ok=True,
            target=plan.request.target,
            operation=plan.request.operation,
            previous_object_version=plan.target.version,
            current_object_version=plan.target.version,
            document_revision=state.document_revision,
            state=state,
            data={"takeover_requested": True},
        )

    def _state_from_raw(self, raw: RawPageSnapshot) -> BrowserState:
        self._session.registry.update(raw)
        return self._view_builder.build(raw, session_id=self._session.session_id)

    def _state_after_navigation(self, driver: BrowserDriver) -> BrowserState:
        raw = driver.observe_raw()
        try:
            enforce_navigation_allowed(raw.url, policy=self._private_url_policy)  # type: ignore[arg-type]
        except BrowserRuntimeError:
            self._session.reset()
            raise
        state = self._state_from_raw(raw)
        if self._auth_surface_mode == "electron":
            return state
        if not self._should_takeover_auth(driver, state):
            return state
        relaunch = getattr(driver, "relaunch_visible", None)
        if not callable(relaunch):
            return state
        relaunch(state.url)
        self._session.registry.clear()
        visible_state = self._state_from_raw(driver.observe_raw())
        visible_state.auth.surface_detected = True
        visible_state.auth.takeover = "visible_window"
        visible_state.auth.user_action_required = True
        if not visible_state.auth.reason:
            visible_state.auth.reason = state.auth.reason
        return visible_state

    def _should_takeover_auth(self, driver: BrowserDriver, state: BrowserState) -> bool:
        if self._auth_surface_mode == "electron":
            return False
        if self._auth_takeover != "auto":
            return False
        if not self._headless:
            return False
        if not state.auth.surface_detected:
            return False
        if not state.url.startswith(("http://", "https://")):
            return False
        status = driver.status() if hasattr(driver, "status") else {}
        if isinstance(status, dict) and status.get("visible_window"):
            return False
        return True

    def _driver_has_pending_dialog(self, driver: BrowserDriver) -> bool:
        has_pending = getattr(driver, "has_pending_dialog", None)
        if callable(has_pending):
            return bool(has_pending())
        return False

    def _dialog_action(self, driver: BrowserDriver, request: BrowserActionRequest) -> BrowserActionResult:
        if not request.target:
            raise dialog_not_found(None)
        driver.act(request)
        return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))

    def _object_action(self, driver: BrowserDriver, request: BrowserActionRequest) -> BrowserActionResult:
        if self._driver_has_pending_dialog(driver):
            raise dialog_required_error()
        state = self._state_from_raw(driver.observe_raw())
        if request.action == "fill_form":
            form = _find_form(state, request.target)
            for key, value in (request.fields or {}).items():
                field = _find_field(form, key)
                if _legacy_form_field_is_protected(field):
                    raise auth_surface_active_error()
                self._session.registry.require(field.id)
                driver.act(BrowserActionRequest(action="clear", target=field.id))
                driver.act(BrowserActionRequest(action="type", target=field.id, text=value))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "submit_form":
            form = _find_form(state, request.target)
            if form.submit:
                self._session.registry.require(form.submit)
                driver.act(BrowserActionRequest(action="click", target=form.submit))
            elif form.fields:
                self._session.registry.require(form.fields[0])
                driver.act(BrowserActionRequest(action="press", target=form.fields[0], key="Enter"))
            else:
                raise ValueError("form has no submit control or fields")
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action in {"follow_link", "activate_control"}:
            element = _find_element(state, request.target)
            expected = "link" if request.action == "follow_link" else None
            if expected and element.role != expected:
                raise ValueError("follow_link requires a link element")
            self._session.registry.require(element.id)
            driver.act(BrowserActionRequest(action="click", target=element.id))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "choose_option":
            element = _find_element(state, request.target)
            self._session.registry.require(element.id)
            driver.act(BrowserActionRequest(action="select", target=element.id, value=request.value, text=request.text))
            return BrowserActionResult(ok=True, action=request.action, state=self._state_after_navigation(driver))
        if request.action == "inspect_block":
            data = _inspect_block(state, request.target)
            return BrowserActionResult(ok=True, action=request.action, state=state, data=data)
        if request.action == "read_list":
            data = _read_list(state, request.target)
            return BrowserActionResult(ok=True, action=request.action, state=state, data=data)
        raise ValueError(f"unsupported object action: {request.action}")


def _legacy_element_is_protected(element: BrowserElement) -> bool:
    input_type = (element.input_type or "").lower()
    combined = " ".join(
        value.lower()
        for value in (element.name, element.placeholder, element.text)
        if value
    )
    if input_type in {"password", "file"}:
        return True
    return any(
        marker in combined
        for marker in (
            "one-time code",
            "verification code",
            "otp",
            "2fa",
            "captcha",
            "cvv",
            "cvc",
            "card number",
            "验证码",
            "支付密码",
            "银行卡号",
        )
    )


def _legacy_form_field_is_protected(field) -> bool:
    field_type = (field.type or "").lower()
    combined = " ".join(
        value.lower()
        for value in (field.key, field.name, field.label, field.placeholder)
        if value
    )
    if field_type in {"password", "file"}:
        return True
    return any(
        marker in combined
        for marker in (
            "one-time code",
            "verification code",
            "otp",
            "2fa",
            "captcha",
            "cvv",
            "cvc",
            "card number",
            "验证码",
            "支付密码",
            "银行卡号",
        )
    )


def _find_form(state: BrowserState, form_id: str | None) -> BrowserForm:
    for form in state.forms:
        if form.id == form_id:
            return form
    raise stale_element_error()


def _find_field(form: BrowserForm, key: str):
    normalized = _norm(key)
    for field in form.field_details:
        candidates = {field.key, field.name, field.label, field.placeholder, field.id}
        if normalized in {_norm(candidate) for candidate in candidates if candidate}:
            return field
    raise ValueError(f"form field not found: {key}")


def _find_element(state: BrowserState, element_id: str | None) -> BrowserElement:
    for element in state.interactive_elements:
        if element.id == element_id:
            return element
    raise stale_element_error()


def _inspect_block(state: BrowserState, block_id: str | None) -> dict:
    for block in state.content_blocks:
        if block.id == block_id:
            elements = [element.model_dump() for element in state.interactive_elements if element.id in set(block.element_ids)]
            return {
                "id": block.id,
                "type": block.type,
                "text": block.text,
                "element_ids": block.element_ids,
                "elements": elements,
            }
    raise stale_element_error()


def _read_list(state: BrowserState, block_id: str | None) -> dict:
    inspected = _inspect_block(state, block_id)
    text = inspected["text"]
    lines = [part.strip() for part in text.replace(" • ", "\n").splitlines() if part.strip()]
    if len(lines) <= 1:
        lines = [part.strip() for part in text.split("  ") if part.strip()]
    return {
        **inspected,
        "items": [{"text": line} for line in lines] or [{"text": text}],
    }


def _require_web_object(state: WebState, object_id: str) -> WebObject:
    for item in state.objects:
        if isinstance(item, WebObject) and item.id == object_id:
            return item
    raise stale_element_error()


def _decision_from_profile(
    evaluation: ProfilePolicyEvaluation,
    *,
    evidence_report: SafetyEvidenceReport | None = None,
) -> SafetyDecision:
    return SafetyDecision(
        decision=evaluation.decision,
        status=evaluation.status,  # type: ignore[arg-type]
        message=evaluation.message,
        evidence_report=evidence_report,
    )


def _merge_profile_evaluation(
    decision: SafetyDecision,
    evaluation: ProfilePolicyEvaluation,
    *,
    evidence_report: SafetyEvidenceReport | None = None,
) -> SafetyDecision:
    if evaluation.decision not in {"allow", "allow_with_audit"}:
        return SafetyDecision(
            decision=evaluation.decision,
            status=evaluation.status,  # type: ignore[arg-type]
            context_id=decision.context_id,
            message=evaluation.message,
            contract=decision.contract,
            state=decision.state,
            evidence_report=evidence_report or decision.evidence_report,
        )
    return decision.model_copy(
        update={"evidence_report": evidence_report or decision.evidence_report}
    )


def _with_profile_policy_evidence(
    report: SafetyEvidenceReport,
    evaluation: ProfilePolicyEvaluation,
) -> SafetyEvidenceReport:
    items = [*report.items]
    existing_codes = {item.code for item in items}
    for item in evaluation.evidence:
        if item.code not in existing_codes:
            items.append(item)
            existing_codes.add(item.code)
    mismatches = [*report.mismatches]
    existing_mismatches = {(item.code, item.message) for item in mismatches}
    for mismatch in evaluation.mismatches:
        key = (mismatch.code, mismatch.message)
        if key not in existing_mismatches:
            mismatches.append(mismatch)
            existing_mismatches.add(key)
    assurance = report.minimum_assurance
    if evaluation.evidence:
        assurance = _max_assurance(assurance, "provider_verified")
    return report.model_copy(
        update={
            "minimum_assurance": assurance,
            "items": items,
            "mismatches": mismatches,
        }
    )


def _observed_payment_total(
    report: SafetyEvidenceReport,
) -> tuple[Decimal, str] | None:
    for item in report.items:
        if item.kind != "financial_amount":
            continue
        amount = item.details.get("amount")
        currency = str(item.details.get("currency") or "").upper()
        try:
            return parse_amount(amount), currency
        except PaymentInstrumentError:
            continue
    return None


def _with_payment_authorization(
    report: SafetyEvidenceReport,
    authorization: PaymentAuthorization | FinancialAuthorization,
) -> SafetyEvidenceReport:
    items = [*report.items]
    existing_codes = {item.code for item in items}
    for item in authorization.evidence:
        if item.code not in existing_codes:
            items.append(item)
            existing_codes.add(item.code)
    mismatches = [*report.mismatches]
    existing_mismatches = {(item.code, item.message) for item in mismatches}
    for mismatch in authorization.mismatches:
        key = (mismatch.code, mismatch.message)
        if key not in existing_mismatches:
            mismatches.append(mismatch)
            existing_mismatches.add(key)
    return report.model_copy(
        update={
            "minimum_assurance": _max_assurance(
                report.minimum_assurance,
                authorization.assurance,
            ),
            "items": items,
            "mismatches": mismatches,
        }
    )


def _with_payment_mismatch(
    report: SafetyEvidenceReport,
    message: str,
    *,
    code: str = "payment_instrument_scope_mismatch",
) -> SafetyEvidenceReport:
    allowed_codes = {
        "payment_instrument_missing",
        "payment_instrument_scope_mismatch",
        "financial_amount_mismatch",
        "financial_limit_exceeded",
        "financial_currency_mismatch",
        "transaction_type_not_allowed",
        "recurring_commitment_not_allowed",
        "assurance_below_policy",
    }
    mismatch_code = code if code in allowed_codes else "payment_instrument_scope_mismatch"
    mismatch = SafetyMismatch(
        code=mismatch_code,  # type: ignore[arg-type]
        severity="deny",
        message=message,
        observed_dimension="financial_commitment",
        evidence_codes=[
            item.code
            for item in report.items
            if item.dimension in {"financial_commitment", "recurring_commitment"}
        ],
    )
    mismatches = [*report.mismatches]
    if all(
        not (existing.code == mismatch.code and existing.message == mismatch.message)
        for existing in mismatches
    ):
        mismatches.append(mismatch)
    return report.model_copy(update={"mismatches": mismatches})


def _payment_denied_decision(
    message: str,
    *,
    decision: SafetyDecision | None,
    evidence: SafetyEvidenceReport,
) -> SafetyDecision:
    return SafetyDecision(
        decision="deny",
        status="blocked",
        context_id=decision.context_id if decision is not None else None,
        message=message,
        contract=decision.contract if decision is not None else None,
        state=decision.state if decision is not None else None,
        evidence_report=evidence,
    )


def _max_assurance(
    left: SafetyAssuranceLevel,
    right: SafetyAssuranceLevel,
) -> SafetyAssuranceLevel:
    order = {
        "agent_asserted": 0,
        "runtime_observed": 1,
        "provider_verified": 2,
        "user_confirmed": 3,
    }
    return left if order[left] >= order[right] else right


def _hard_takeover_reason(report: SafetyEvidenceReport) -> TakeoverReason | None:
    for item in report.items:
        if item.code == "runtime:captcha":
            return "captcha"
        if item.code == "runtime:biometric_verification" or item.code == "runtime:biometric_markers":
            return "biometric_verification"
        if item.code in {
            "runtime:protected:payment_card",
            "runtime:protected:payment_verification",
            "runtime:payment_challenge_markers",
        }:
            return "payment_verification"
        if item.code in {
            "runtime:protected:password",
            "runtime:protected:one_time_code",
        }:
            return "authentication"
    return None


def _with_resource_authorization(
    report: SafetyEvidenceReport,
    grant: LocalResourceGrant,
) -> SafetyEvidenceReport:
    item = SafetyEvidenceItem(
        code=f"resource_grant:{grant.resource_ref}",
        kind="resource_grant",
        source="resource_broker",
        assurance="provider_verified",
        dimension="local_data_egress",
        summary="LocalResourceBroker verified the scoped resource reference",
        origin=grant.allowed_origins[0] if grant.allowed_origins else "",
        details={
            "resource_ref": grant.resource_ref,
            "purpose": grant.purpose,
            "max_uses": grant.max_uses,
        },
    )
    items = [*report.items]
    if all(existing.code != item.code for existing in items):
        items.append(item)
    return report.model_copy(
        update={
            "minimum_assurance": "provider_verified",
            "items": items,
        }
    )


def _with_resource_mismatch(
    report: SafetyEvidenceReport,
    message: str,
    *,
    code: str = "resource_grant_scope_mismatch",
) -> SafetyEvidenceReport:
    mismatch_code = (
        "resource_grant_missing"
        if code in {"resource_not_found", "resource_missing"}
        else "resource_grant_scope_mismatch"
    )
    mismatch = SafetyMismatch(
        code=mismatch_code,
        severity="deny",
        message=message,
        observed_dimension="local_data_egress",
        evidence_codes=[item.code for item in report.items if item.dimension == "local_data_egress"],
    )
    mismatches = [*report.mismatches]
    if all(
        not (existing.code == mismatch.code and existing.message == mismatch.message)
        for existing in mismatches
    ):
        mismatches.append(mismatch)
    return report.model_copy(update={"mismatches": mismatches})


def _safe_step_up_get(manager: StepUpManager, step_up_id: str) -> StepUpRequestState | None:
    try:
        state = manager.get(step_up_id)
    except StepUpError:
        return None
    return state.model_copy(
        update={"decided_by": None, "decision_note": ""},
        deep=True,
    )


def _bind_web_operation_scope(
    scope: dict[str, StepUpScopeScalar],
    state: WebState,
    target_object_id: str,
) -> dict[str, StepUpScopeScalar]:
    bound = dict(scope)
    bound["document_id"] = state.document_id
    for item in state.objects:
        if isinstance(item, WebObject) and item.id == target_object_id:
            bound["object_version"] = item.version
            break
    return bound


def _profile_step_up_scope(
    evaluation: ProfilePolicyEvaluation,
    metadata: ProfileOwnershipMetadata,
    declaration,
) -> tuple[StepUpReason, dict[str, StepUpScopeScalar], dict[str, StepUpScopeScalar]]:
    mismatch_codes = {mismatch.code for mismatch in evaluation.mismatches}
    if "identity_switch_requires_step_up" in mismatch_codes:
        action = "identity_change"
        if declaration is not None:
            for dimension in declaration.dimensions:
                if dimension.type == "identity_context":
                    action = dimension.action
                    break
        return (
            "identity_switch",
            {"profile_owner": metadata.owner, "trust_mode": metadata.trust_mode},
            {"profile_owner": metadata.owner, "action": action},
        )
    if "unknown_effect_policy_violation" in mismatch_codes:
        return (
            "unknown_external_effect",
            {"policy": metadata.unknown_external_effect_policy or "require_step_up"},
            {"effect": "unknown_external_effect", "origin_policy": "single_operation"},
        )
    return (
        "profile_scope",
        {"profile_owner": metadata.owner, "trust_mode": metadata.trust_mode},
        {"profile_id": metadata.profile_id, "origin_policy": "single_operation"},
    )


def _payment_operation_is_final_commit(evidence: SafetyEvidenceReport) -> bool:
    return any(item.code == "runtime:financial_commit_control" for item in evidence.items)


def _is_final_financial_commit(
    request: WebOperationRequest,
    evidence: SafetyEvidenceReport,
) -> bool:
    if "financial_commitment" not in evidence.observed_dimensions:
        return False
    evidence_codes = {item.code for item in evidence.items}
    if "runtime:financial_commit_control" in evidence_codes:
        return True
    if request.operation not in {"activate", "submit"}:
        return False
    return bool(
        "runtime:form_submit_activation" in evidence_codes
        and "runtime:payment_surface_markers" in evidence_codes
    )


def _payment_step_up_scope(
    authorization: PaymentAuthorization,
) -> tuple[StepUpReason, dict[str, StepUpScopeScalar], dict[str, StepUpScopeScalar]]:
    mismatch_codes = {mismatch.code for mismatch in authorization.mismatches}
    reason: StepUpReason = (
        "financial_assurance"
        if "assurance_below_policy" in mismatch_codes
        else "financial_limit"
    )
    return (
        reason,
        {
            "autonomy_limit": str(authorization.policy.autonomy_limit),
            "step_up_limit": str(authorization.policy.step_up_limit),
            "absolute_limit": str(authorization.policy.absolute_limit),
            "minimum_assurance": authorization.policy.minimum_assurance,
        },
        {
            "amount": str(authorization.amount),
            "currency": authorization.currency,
            "transaction_kind": authorization.transaction_kind,
            "instrument_id": authorization.instrument.instrument_id,
            "assurance": authorization.assurance,
        },
    )


def _financial_step_up_scope(
    authorization: FinancialAuthorization,
) -> tuple[StepUpReason, dict[str, StepUpScopeScalar], dict[str, StepUpScopeScalar]]:
    mismatch_codes = {mismatch.code for mismatch in authorization.mismatches}
    reason: StepUpReason = (
        "financial_assurance"
        if "assurance_below_policy" in mismatch_codes
        else "financial_limit"
    )
    return (
        reason,
        {
            "autonomy_limit": str(authorization.policy.autonomy_limit),
            "step_up_limit": str(authorization.policy.step_up_limit),
            "absolute_limit": str(authorization.policy.absolute_limit),
            "minimum_assurance": authorization.policy.minimum_assurance,
        },
        {
            "amount": str(authorization.amount),
            "currency": authorization.currency,
            "transaction_kind": authorization.transaction_kind,
            "assurance": authorization.assurance,
        },
    )


def _authority_source(manager: SafetyContextManager, context_id: str | None) -> str | None:
    if context_id is None:
        return None
    declaration = manager.declaration_for(context_id)
    if declaration is None:
        return None
    return _authority_source_fingerprint(declaration.authorization_claim.source_ref)


def _authority_source_fingerprint(value: str | None) -> str | None:
    if not value:
        return None
    digest = sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"sha256:{digest}"


def _bind_navigation_scope(
    scope: dict[str, StepUpScopeScalar],
    url: str,
) -> dict[str, StepUpScopeScalar]:
    bound = dict(scope)
    bound["url"] = redact_action_message(url)
    bound["url_fingerprint"] = f"sha256:{sha256(url.encode('utf-8')).hexdigest()[:24]}"
    return bound


def _declaration_origins(declaration: Any | None) -> list[str]:
    if declaration is None:
        return []
    normalized = [
        _normalize_origin_scope(value)
        for value in declaration.origin_scope
    ]
    return list(dict.fromkeys(value for value in normalized if value))


def _normalize_origin_scope(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    if parsed.scheme == "file":
        return "file://"
    return ""


def _normalize_takeover_reason(value: str) -> TakeoverReason:
    supported = {
        "authentication",
        "captcha",
        "payment_verification",
        "biometric_verification",
        "opaque_surface",
        "high_risk_confirmation",
        "permission_request",
        "file_selection",
        "ambiguous_state",
        "manual_identity_confirmation",
    }
    normalized = value.strip().lower()
    return normalized if normalized in supported else "manual_identity_confirmation"  # type: ignore[return-value]


def _monitor_safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        name = parsed.path.replace("\\", "/").rstrip("/").split("/")[-1] or "local"
        return f"file:///{_monitor_safe_path_segment(name)}"
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return (
            f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
            f"{_monitor_safe_path(parsed.path or '/')}"
        )
    return redact_action_message(url.split("?", 1)[0].split("#", 1)[0])


def _monitor_safe_path(path: str) -> str:
    sensitive_markers = {
        "auth",
        "callback",
        "code",
        "invite",
        "magic",
        "reset",
        "secret",
        "session",
        "token",
        "verify",
        "verification",
    }
    segments = path.split("/")
    result: list[str] = []
    redact_next = False
    for segment in segments:
        if not segment:
            result.append(segment)
            continue
        decoded = unquote(segment)
        lowered = decoded.lower()
        marker_tokens = {
            token
            for token in lowered.replace("-", " ").replace("_", " ").replace(".", " ").replace("~", " ").split()
            if token
        }
        if redact_next:
            result.append("[REDACTED]")
            redact_next = False
            continue
        result.append(_monitor_safe_path_segment(segment))
        if lowered in sensitive_markers or marker_tokens.intersection(sensitive_markers):
            redact_next = True
    return "/".join(result) or "/"


def _monitor_safe_path_segment(segment: str) -> str:
    decoded = unquote(segment)
    if "@" in decoded:
        return "[REDACTED]"
    compact = decoded.replace("-", "").replace("_", "").replace(".", "").replace("~", "")
    if len(segment) >= 24 and compact.isalnum():
        return "[REDACTED]"
    return segment


def _origin_from_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme == "file":
        return "file://"
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())
