from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from browser.driver import BrowserDriver
from browser.object_registry import ObjectRegistry, WebObjectNotFoundError
from schemas.browser import BrowserActionRequest
from schemas.web import (
    SemanticOperationName,
    TakeoverReason,
    WebObject,
    WebOperationRequest,
)


class WebOperationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        target: str,
        operation: str,
        recover_hint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.target = target
        self.operation = operation
        self.recover_hint = recover_hint


class WebOperationTargetError(WebOperationError):
    pass


class WebObjectVersionConflictError(WebOperationError):
    pass


class WebOperationNotSupportedError(WebOperationError):
    pass


class WebOperationArgumentError(WebOperationError):
    pass


class WebOperationUnavailableError(WebOperationError):
    pass


@dataclass(frozen=True)
class WebOperationPlan:
    request: WebOperationRequest
    target: WebObject
    actions: tuple[BrowserActionRequest, ...] = ()
    takeover_reason: TakeoverReason | None = None
    no_op: bool = False


class SemanticOperationExecutor:
    """Validate WebObject capabilities and translate semantics into internal driver actions."""

    def __init__(self, registry: ObjectRegistry) -> None:
        self._registry = registry

    def plan(self, request: WebOperationRequest) -> WebOperationPlan:
        target = self._require_target(request)
        self._validate_version(request, target)
        self._validate_capability(request, target)
        self._validate_target_state(request, target)

        operation = request.operation
        if operation == "set_value":
            value = self._required_string_argument(request, "value")
            legacy_target = self._require_legacy_target(request, target)
            return WebOperationPlan(
                request=request,
                target=target,
                actions=(
                    BrowserActionRequest(action="clear", target=legacy_target),
                    BrowserActionRequest(action="type", target=legacy_target, text=value),
                ),
            )
        if operation == "clear_value":
            self._require_no_arguments(request)
            return self._single_legacy_action(request, target, "clear")
        if operation == "choose":
            value = self._required_string_argument(request, "value")
            legacy_target = self._require_legacy_target(request, target)
            return WebOperationPlan(
                request=request,
                target=target,
                actions=(BrowserActionRequest(action="select", target=legacy_target, value=value),),
            )
        if operation == "toggle":
            self._require_only_arguments(request, {"checked"})
            desired = request.arguments.get("checked")
            if desired is not None and not isinstance(desired, bool):
                raise self._argument_error(request, "checked must be a boolean")
            if target.role == "radio" and desired is False:
                raise self._argument_error(request, "radio objects cannot be toggled to false directly")
            if desired is not None and target.state.checked is desired:
                return WebOperationPlan(request=request, target=target, no_op=True)
            return self._single_legacy_action(request, target, "click")
        if operation in {"open", "activate"}:
            self._require_no_arguments(request)
            return self._single_legacy_action(request, target, "click")
        if operation == "submit":
            self._require_no_arguments(request)
            return self._submit_plan(request, target)
        if operation == "expand":
            self._require_no_arguments(request)
            if target.state.expanded is True:
                return WebOperationPlan(request=request, target=target, no_op=True)
            return self._single_legacy_action(request, target, "click")
        if operation == "collapse":
            self._require_no_arguments(request)
            if target.state.expanded is False:
                return WebOperationPlan(request=request, target=target, no_op=True)
            return self._single_legacy_action(request, target, "click")
        if operation == "dismiss":
            self._require_no_arguments(request)
            legacy_target = self._require_legacy_target(request, target)
            action = "dismiss_dialog" if target.category == "dialog" else "click"
            return WebOperationPlan(
                request=request,
                target=target,
                actions=(BrowserActionRequest(action=action, target=legacy_target),),
            )
        if operation == "request_human_takeover":
            self._require_no_arguments(request)
            return WebOperationPlan(
                request=request,
                target=target,
                takeover_reason=_takeover_reason(target),
            )
        if operation in {"open_in_new_context", "download", "upload"}:
            raise WebOperationUnavailableError(
                "operation_temporarily_unavailable",
                f"{operation} is defined by the WebFA Object Model but is not implemented by the current resource/host bridge",
                target=request.target,
                operation=operation,
                recover_hint="Use the current-context capability when available or request human takeover.",
            )
        raise WebOperationNotSupportedError(
            "operation_not_supported",
            f"unsupported semantic operation: {operation}",
            target=request.target,
            operation=operation,
            recover_hint="Observe the object again and use one of its declared capabilities.",
        )

    def execute(self, driver: BrowserDriver, plan: WebOperationPlan) -> None:
        for action in plan.actions:
            driver.act(action)

    def _require_target(self, request: WebOperationRequest) -> WebObject:
        try:
            return self._registry.require(request.target)
        except WebObjectNotFoundError as exc:
            raise WebOperationTargetError(
                "object_not_found",
                f"WebObject does not exist in the current document: {request.target}",
                target=request.target,
                operation=request.operation,
                recover_hint="Call observe in changes or query mode and choose a current object id.",
            ) from exc

    def _validate_version(self, request: WebOperationRequest, target: WebObject) -> None:
        expected = request.expected_object_version
        if expected is None or expected == target.version:
            return
        raise WebObjectVersionConflictError(
            "object_version_conflict",
            f"expected object version {expected}, current version is {target.version}",
            target=request.target,
            operation=request.operation,
            recover_hint="Observe the object or changes and retry using the current object version.",
        )

    def _validate_capability(self, request: WebOperationRequest, target: WebObject) -> None:
        if request.operation in target.capabilities:
            return
        raise WebOperationNotSupportedError(
            "operation_not_supported",
            f"object {target.id} does not declare capability {request.operation}",
            target=request.target,
            operation=request.operation,
            recover_hint="Use only capabilities declared by the current WebObject.",
        )

    def _validate_target_state(self, request: WebOperationRequest, target: WebObject) -> None:
        if request.operation == "request_human_takeover":
            return
        if not target.state.visible:
            raise WebOperationUnavailableError(
                "operation_temporarily_unavailable",
                "target object is not visible",
                target=request.target,
                operation=request.operation,
                recover_hint="Observe changes and retry when the object becomes visible.",
            )
        if not target.state.enabled:
            raise WebOperationUnavailableError(
                "operation_temporarily_unavailable",
                "target object is disabled",
                target=request.target,
                operation=request.operation,
                recover_hint="Observe the form or controlling object to determine why the target is disabled.",
            )

    def _single_legacy_action(
        self,
        request: WebOperationRequest,
        target: WebObject,
        action: str,
    ) -> WebOperationPlan:
        legacy_target = self._require_legacy_target(request, target)
        return WebOperationPlan(
            request=request,
            target=target,
            actions=(BrowserActionRequest(action=action, target=legacy_target),),
        )

    def _submit_plan(self, request: WebOperationRequest, target: WebObject) -> WebOperationPlan:
        submit_id = target.relations.submit_control
        if submit_id:
            submit = self._registry.require(submit_id)
            legacy_target = self._require_legacy_target(request, submit)
            return WebOperationPlan(
                request=request,
                target=target,
                actions=(BrowserActionRequest(action="click", target=legacy_target),),
            )
        for child_id in target.relations.children:
            child = self._registry.require(child_id)
            if child.role not in {"field", "searchbox", "textbox", "textarea", "combobox"}:
                continue
            legacy_target = self._require_legacy_target(request, child)
            return WebOperationPlan(
                request=request,
                target=target,
                actions=(BrowserActionRequest(action="press", target=legacy_target, key="Enter"),),
            )
        raise WebOperationUnavailableError(
            "operation_temporarily_unavailable",
            "form has no executable submit control or field",
            target=request.target,
            operation=request.operation,
            recover_hint="Observe the form again or activate its submit control directly.",
        )

    def _require_legacy_target(self, request: WebOperationRequest, target: WebObject) -> str:
        try:
            legacy_target = self._registry.legacy_target_for(target.id)
        except WebObjectNotFoundError as exc:
            legacy_target = None
            cause: Exception | None = exc
        else:
            cause = None
        if legacy_target:
            return legacy_target
        error = WebOperationUnavailableError(
            "operation_temporarily_unavailable",
            "the current compiler evidence does not provide an executable browser target",
            target=request.target,
            operation=request.operation,
            recover_hint="Observe changes and retry. If the object remains non-executable, request human takeover.",
        )
        if cause is not None:
            raise error from cause
        raise error

    def _required_string_argument(self, request: WebOperationRequest, name: str) -> str:
        self._require_only_arguments(request, {name})
        value = request.arguments.get(name)
        if not isinstance(value, str):
            raise self._argument_error(request, f"{name} must be a string")
        return value

    def _require_no_arguments(self, request: WebOperationRequest) -> None:
        self._require_only_arguments(request, set())

    def _require_only_arguments(self, request: WebOperationRequest, allowed: set[str]) -> None:
        unexpected = sorted(set(request.arguments) - allowed)
        if unexpected:
            raise self._argument_error(request, f"unexpected arguments: {', '.join(unexpected)}")

    def _argument_error(self, request: WebOperationRequest, message: str) -> WebOperationArgumentError:
        return WebOperationArgumentError(
            "invalid_operation_arguments",
            message,
            target=request.target,
            operation=request.operation,
            recover_hint="Inspect the capability descriptor and provide only the declared arguments.",
        )


def _takeover_reason(target: WebObject) -> TakeoverReason:
    if target.category == "opaque_surface" or target.role == "opaque_surface":
        return "opaque_surface"
    if target.role == "upload_target":
        return "file_selection"
    if target.role in {"field", "textbox", "searchbox"}:
        return "authentication"
    return "ambiguous_state"
