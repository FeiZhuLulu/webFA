from __future__ import annotations

import re
from urllib.parse import urlparse

from browser.web_capabilities import capability_descriptor
from schemas.safety import (
    SafetyAssuranceLevel,
    SafetyDimensionType,
    SafetyEvidenceItem,
    SafetyEvidenceReport,
)
from schemas.web import SemanticOperationName, WebObject, WebState


_ASSURANCE_ORDER: dict[SafetyAssuranceLevel, int] = {
    "agent_asserted": 0,
    "runtime_observed": 1,
    "provider_verified": 2,
    "user_confirmed": 3,
}

_PAYMENT_MARKERS = (
    "payment",
    "pay now",
    "checkout",
    "place order",
    "order total",
    "card number",
    "credit card",
    "debit card",
    "支付",
    "付款",
    "结算",
    "提交订单",
    "银行卡",
)
_FINANCIAL_COMMIT_MARKERS = (
    "pay now",
    "pay with",
    "place order",
    "buy now",
    "confirm purchase",
    "complete purchase",
    "submit payment",
    "confirm and pay",
    "提交订单",
    "立即购买",
    "立即支付",
    "确认支付",
    "确认购买",
)
_RECURRING_MARKERS = (
    "subscription",
    "subscribe",
    "auto-renew",
    "automatic renewal",
    "recurring",
    "per month",
    "per year",
    "monthly",
    "yearly",
    "订阅",
    "自动续费",
    "连续包月",
    "连续包年",
    "每月",
    "每年",
)
_BIOMETRIC_MARKERS = (
    "fingerprint",
    "face id",
    "touch id",
    "biometric",
    "指纹",
    "面容",
    "生物识别",
)
_PAYMENT_CHALLENGE_MARKERS = (
    "3d secure",
    "3-d secure",
    "bank verification",
    "payment verification",
    "verify payment",
    "支付验证",
    "银行验证",
    "支付密码",
)


class RuntimeEvidenceResolver:
    """Derive minimum safety evidence from P10 semantics and current WebState.

    This resolver deliberately uses only deterministic protocol metadata and
    conservative string markers. It never interprets user conversation text and
    never lowers an Agent-declared risk dimension.
    """

    def resolve(
        self,
        *,
        target: WebObject,
        operation: SemanticOperationName,
        state: WebState,
    ) -> SafetyEvidenceReport:
        descriptor = capability_descriptor(operation)
        items: list[SafetyEvidenceItem] = [
            SafetyEvidenceItem(
                code=f"p10_effect:{descriptor.effect}",
                kind="p10_effect",
                source="p10_capability",
                assurance="runtime_observed",
                summary=f"P10 capability {operation} declares effect {descriptor.effect}",
                object_id=target.id,
                origin=target.origin,
                details={"operation": operation, "effect": descriptor.effect},
            )
        ]
        observed: list[SafetyDimensionType] = []
        assurance: SafetyAssuranceLevel = "runtime_observed"
        external_origin = _is_external_origin(target.origin or state.url)
        combined = _related_text(target, state)
        target_text = " ".join(
            value.lower()
            for value in (target.name, target.description, target.text)
            if value
        )

        def add_dimension(
            dimension: SafetyDimensionType,
            *,
            code: str,
            kind: str,
            summary: str,
            source: str = "web_object",
            details: dict[str, str | int | float | bool] | None = None,
            item_assurance: SafetyAssuranceLevel = "runtime_observed",
        ) -> None:
            nonlocal assurance
            if dimension not in observed:
                observed.append(dimension)
            if _ASSURANCE_ORDER[item_assurance] > _ASSURANCE_ORDER[assurance]:
                assurance = item_assurance
            items.append(
                SafetyEvidenceItem(
                    code=code,
                    kind=kind,  # type: ignore[arg-type]
                    source=source,  # type: ignore[arg-type]
                    assurance=item_assurance,
                    dimension=dimension,
                    summary=summary,
                    object_id=target.id,
                    origin=target.origin or _origin(state.url),
                    details=details or {},
                )
            )

        if operation == "provide_payment_instrument":
            add_dimension(
                "financial_commitment",
                code="runtime:payment_instrument_operation",
                kind="payment_instrument",
                summary="The operation requests a protected payment instrument for the current transaction",
                details={"role": target.role},
            )
        if descriptor.effect == "upload" or operation == "upload" or target.role == "upload_target":
            add_dimension(
                "local_data_egress",
                code="runtime:upload_target",
                kind="upload_target",
                summary="The operation uploads a locally granted resource to the current origin",
                details={"role": target.role},
            )
        elif descriptor.effect == "external_send" and external_origin:
            add_dimension(
                "external_representation",
                code="runtime:external_send",
                kind="external_mutation",
                summary="The operation sends or publishes information to an external origin",
            )
        elif descriptor.effect == "destructive" and external_origin:
            add_dimension(
                "destructive_change",
                code="runtime:destructive_effect",
                kind="external_mutation",
                summary="The operation declares a destructive P10 effect",
            )
        elif descriptor.effect == "permission_change" and external_origin:
            add_dimension(
                "authority_change",
                code="runtime:permission_change",
                kind="external_mutation",
                summary="The operation changes authority or permissions",
            )
        elif descriptor.effect == "external_write" and external_origin:
            add_dimension(
                "unknown_external_effect",
                code="runtime:external_write",
                kind="external_mutation",
                summary="The operation changes external state but Runtime cannot fully classify the business effect",
            )
        elif operation == "activate" and external_origin and _is_form_submit_control(target, state):
            add_dimension(
                "unknown_external_effect",
                code="runtime:form_submit_activation",
                kind="external_mutation",
                summary="The activated control is the submit control of an external form",
            )

        protected_kind = target.security.protected_kind
        if protected_kind is not None:
            if protected_kind in {"password", "one_time_code"}:
                add_dimension(
                    "identity_context",
                    code=f"runtime:protected:{protected_kind}",
                    kind="protected_credential",
                    summary="The target is a protected authentication input",
                    details={"protected_kind": protected_kind},
                )
            elif protected_kind == "captcha":
                add_dimension(
                    "identity_context",
                    code="runtime:captcha",
                    kind="captcha_surface",
                    summary="The target is a CAPTCHA or human verification surface",
                    details={"protected_kind": protected_kind},
                )
            elif protected_kind in {"payment_card", "payment_verification"}:
                add_dimension(
                    "financial_commitment",
                    code=f"runtime:protected:{protected_kind}",
                    kind="payment_challenge" if protected_kind == "payment_verification" else "payment_surface",
                    summary="The target is a protected payment input or verification surface",
                    details={"protected_kind": protected_kind},
                )
            elif protected_kind == "biometric_verification":
                add_dimension(
                    "identity_context",
                    code="runtime:biometric_verification",
                    kind="authentication_surface",
                    summary="The target requests biometric user verification",
                    details={"protected_kind": protected_kind},
                )

        if external_origin and _contains_any(combined, _PAYMENT_MARKERS):
            add_dimension(
                "financial_commitment",
                code="runtime:payment_surface_markers",
                kind="payment_surface",
                summary="Visible target or related form text contains deterministic payment-surface markers",
            )
        if (
            external_origin
            and (
                operation in {"activate", "submit"}
                or (operation == "provide_payment_instrument" and target.role == "button")
            )
            and _contains_any(target_text, _FINANCIAL_COMMIT_MARKERS)
        ):
            add_dimension(
                "financial_commitment",
                code="runtime:financial_commit_control",
                kind="financial_policy",
                summary="The target is a deterministic final payment or order-commit control",
            )
        observed_total = _extract_order_total(state)
        if external_origin and observed_total is not None:
            amount, currency = observed_total
            add_dimension(
                "financial_commitment",
                code="runtime:observed_order_total",
                kind="financial_amount",
                summary="Runtime observed a structured order-total marker near a monetary amount",
                source="runtime_page",
                details={"amount": amount, "currency": currency},
            )
        if external_origin and _contains_any(combined, _RECURRING_MARKERS):
            add_dimension(
                "recurring_commitment",
                code="runtime:recurring_markers",
                kind="recurring_commitment",
                summary="Visible target or related form text contains deterministic recurring-commitment markers",
            )
        if _contains_any(combined, _PAYMENT_CHALLENGE_MARKERS):
            add_dimension(
                "financial_commitment",
                code="runtime:payment_challenge_markers",
                kind="payment_challenge",
                summary="The current surface contains deterministic payment verification markers",
            )
        if _contains_any(combined, _BIOMETRIC_MARKERS):
            add_dimension(
                "identity_context",
                code="runtime:biometric_markers",
                kind="authentication_surface",
                summary="The current surface contains deterministic biometric verification markers",
            )

        if state.auth.surface_detected and operation == "request_human_takeover":
            add_dimension(
                "identity_context",
                code="runtime:auth_surface",
                kind="authentication_surface",
                summary="Browser Runtime detected an authentication surface requiring user action",
                source="runtime_page",
                details={"user_action_required": state.auth.user_action_required},
            )

        return SafetyEvidenceReport(
            p10_effect=descriptor.effect,
            observed_dimensions=observed,
            minimum_assurance=assurance,
            items=_dedupe_items(items),
            mismatches=[],
        )


def _is_form_submit_control(target: WebObject, state: WebState) -> bool:
    form_id = target.relations.form
    if not form_id:
        return False
    for item in state.objects:
        if isinstance(item, WebObject) and item.id == form_id:
            return item.relations.submit_control == target.id
    return False


def _related_text(target: WebObject, state: WebState) -> str:
    parts = [target.name, target.description, target.text]
    related_ids = {
        value
        for value in (
            target.relations.form,
            target.relations.parent,
            target.relations.belongs_to,
        )
        if value
    }
    for item in state.objects:
        if not isinstance(item, WebObject):
            continue
        if item.id in related_ids:
            parts.extend((item.name, item.description, item.text))
    return " ".join(part.strip().lower() for part in parts if part and part.strip())


def _extract_order_total(state: WebState) -> tuple[str, str] | None:
    parts: list[str] = []
    for item in state.objects:
        if not isinstance(item, WebObject):
            continue
        parts.extend((item.name, item.description, item.text))
    text = " ".join(part.strip() for part in parts if part and part.strip())
    pattern = re.compile(
        r"(?:order\s+total|grand\s+total|amount\s+due|total\s+due|合计|总计|订单总额|应付|实付)"
        r"\s*[:：]?\s*(?:(CNY|RMB|USD|EUR|GBP|JPY)\s*)?"
        r"(?:[¥￥$€£]\s*)?([0-9][0-9,]*(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        return None
    currency = (match.group(1) or "").upper()
    if currency == "RMB":
        currency = "CNY"
    amount = match.group(2).replace(",", "")
    return amount, currency


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    return any(marker in value for marker in markers)


def _is_external_origin(value: str) -> bool:
    return urlparse(value).scheme.lower() in {"http", "https"}


def _origin(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


def _dedupe_items(items: list[SafetyEvidenceItem]) -> list[SafetyEvidenceItem]:
    by_code: dict[str, SafetyEvidenceItem] = {}
    for item in items:
        by_code.setdefault(item.code, item)
    return list(by_code.values())
