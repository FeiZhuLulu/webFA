from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from uuid import uuid4

from schemas.safety import StepUpReason, StepUpRequest, StepUpRequestState, StepUpScopeScalar


class StepUpError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class StepUpManager:
    """Session-local, exact-scope escalation grants for the Visualizer.

    A step-up is not a general approval token. It is bound to one Agent,
    Profile, Origin, WebObject target, semantic operation, and optional
    SafetyContext. Approved requests are single-use by default.
    """

    def __init__(self) -> None:
        self._states: dict[str, StepUpRequestState] = {}
        self._fingerprints: dict[tuple[object, ...], str] = {}
        self._lock = RLock()

    def request(
        self,
        *,
        reason: StepUpReason,
        context_id: str | None,
        agent_id: str,
        profile_id: str,
        origin: str,
        target_object_id: str,
        operation: str,
        message: str,
        current_scope: dict[str, StepUpScopeScalar] | None = None,
        requested_scope: dict[str, StepUpScopeScalar] | None = None,
        expires_in_seconds: int = 900,
    ) -> StepUpRequestState:
        current = current_scope or {}
        requested = requested_scope or {}
        fingerprint = self._fingerprint(
            reason=reason,
            context_id=context_id,
            agent_id=agent_id,
            profile_id=profile_id,
            origin=origin,
            target_object_id=target_object_id,
            operation=operation,
            requested_scope=requested,
        )
        with self._lock:
            existing_id = self._fingerprints.get(fingerprint)
            if existing_id is not None:
                existing = self._states.get(existing_id)
                if existing is not None:
                    self._refresh(existing)
                    if existing.status in {"pending", "approved"}:
                        return existing.model_copy(deep=True)

            now = datetime.now(timezone.utc)
            request = StepUpRequest(
                step_up_id=f"stepup_{uuid4().hex}",
                reason=reason,
                context_id=context_id,
                agent_id=agent_id,
                profile_id=profile_id,
                origin=origin,
                target_object_id=target_object_id,
                operation=operation,
                message=message,
                current_scope=current,
                requested_scope=requested,
                created_at=now,
                expires_at=now + timedelta(seconds=max(60, expires_in_seconds)),
            )
            state = StepUpRequestState(request=request)
            self._states[request.step_up_id] = state
            self._fingerprints[fingerprint] = request.step_up_id
            return state.model_copy(deep=True)

    def list(self, *, include_terminal: bool = True) -> list[StepUpRequestState]:
        with self._lock:
            states: list[StepUpRequestState] = []
            for state in self._states.values():
                self._refresh(state)
                if include_terminal or state.status in {"pending", "approved"}:
                    states.append(state.model_copy(deep=True))
            return sorted(states, key=lambda item: item.request.created_at, reverse=True)

    def get(self, step_up_id: str) -> StepUpRequestState:
        with self._lock:
            state = self._require(step_up_id)
            self._refresh(state)
            return state.model_copy(deep=True)

    def approve(
        self,
        step_up_id: str,
        *,
        decided_by: str = "local_user",
        decision_note: str = "",
        approved_scope: dict[str, StepUpScopeScalar] | None = None,
    ) -> StepUpRequestState:
        with self._lock:
            state = self._require(step_up_id)
            self._refresh(state)
            if state.status != "pending":
                raise StepUpError("step_up_not_pending", "step-up request is not pending")
            scope = approved_scope or state.request.requested_scope
            if not _scope_matches(state.request.requested_scope, scope):
                raise StepUpError(
                    "step_up_scope_mismatch",
                    "step-up approval must exactly match the originally requested scope",
                )
            approved = state.model_copy(
                update={
                    "status": "approved",
                    "approved_scope": dict(scope),
                    "decided_by": decided_by,
                    "decision_note": decision_note,
                    "decided_at": datetime.now(timezone.utc),
                    "remaining_uses": 1,
                },
                deep=True,
            )
            self._states[step_up_id] = approved
            return approved.model_copy(deep=True)

    def reject(
        self,
        step_up_id: str,
        *,
        decided_by: str = "local_user",
        decision_note: str = "",
    ) -> StepUpRequestState:
        with self._lock:
            state = self._require(step_up_id)
            self._refresh(state)
            if state.status != "pending":
                raise StepUpError("step_up_not_pending", "step-up request is not pending")
            rejected = state.model_copy(
                update={
                    "status": "rejected",
                    "decided_by": decided_by,
                    "decision_note": decision_note,
                    "decided_at": datetime.now(timezone.utc),
                    "remaining_uses": 0,
                },
                deep=True,
            )
            self._states[step_up_id] = rejected
            return rejected.model_copy(deep=True)

    def authorize(
        self,
        step_up_id: str,
        *,
        context_id: str | None,
        agent_id: str,
        profile_id: str,
        origin: str,
        target_object_id: str,
        operation: str,
        requested_scope: dict[str, StepUpScopeScalar] | None = None,
    ) -> StepUpRequestState:
        with self._lock:
            state = self._require(step_up_id)
            self._refresh(state)
            if state.status != "approved":
                raise StepUpError("step_up_not_approved", "step-up request has not been approved")
            request = state.request
            actual_binding = (
                context_id,
                agent_id,
                profile_id,
                origin,
                target_object_id,
                operation,
            )
            expected_binding = (
                request.context_id,
                request.agent_id,
                request.profile_id,
                request.origin,
                request.target_object_id,
                request.operation,
            )
            if actual_binding != expected_binding:
                raise StepUpError(
                    "step_up_binding_mismatch",
                    "step-up approval is bound to a different task operation",
                )
            if not _scope_matches(state.request.requested_scope, requested_scope or {}):
                raise StepUpError(
                    "step_up_scope_mismatch",
                    "current operation does not exactly match the approved step-up scope",
                )
            return state.model_copy(deep=True)

    def consume(self, step_up_id: str) -> StepUpRequestState:
        with self._lock:
            state = self._require(step_up_id)
            self._refresh(state)
            if state.status != "approved" or state.remaining_uses <= 0:
                raise StepUpError("step_up_not_approved", "step-up approval is not available")
            consumed = state.model_copy(
                update={"status": "consumed", "remaining_uses": 0},
                deep=True,
            )
            self._states[step_up_id] = consumed
            return consumed.model_copy(deep=True)

    def _require(self, step_up_id: str) -> StepUpRequestState:
        state = self._states.get(step_up_id)
        if state is None:
            raise StepUpError("step_up_not_found", "step-up request was not found")
        return state

    @staticmethod
    def _refresh(state: StepUpRequestState) -> None:
        if state.status in {"pending", "approved"} and state.request.expires_at <= datetime.now(timezone.utc):
            state.status = "expired"
            state.remaining_uses = 0

    @staticmethod
    def _fingerprint(
        *,
        reason: StepUpReason,
        context_id: str | None,
        agent_id: str,
        profile_id: str,
        origin: str,
        target_object_id: str,
        operation: str,
        requested_scope: dict[str, StepUpScopeScalar],
    ) -> tuple[object, ...]:
        return (
            reason,
            context_id,
            agent_id,
            profile_id,
            origin,
            target_object_id,
            operation,
            tuple(sorted(requested_scope.items())),
        )


def _scope_matches(
    expected: dict[str, StepUpScopeScalar],
    actual: dict[str, StepUpScopeScalar],
) -> bool:
    if set(expected) != set(actual):
        return False
    for key, value in expected.items():
        actual_value = actual.get(key)
        if key in {"amount", "maximum_amount", "autonomy_limit"}:
            try:
                if Decimal(str(actual_value)) != Decimal(str(value)):
                    return False
            except (InvalidOperation, TypeError, ValueError):
                return False
        elif actual_value != value:
            return False
    return True
