from __future__ import annotations

from browser.driver import VISIBLE_TEXT_MAX_CHARS, RawPageSnapshot
from browser.url_policy import evaluate_url_security
from schemas.browser import (
    BrowserAuthState,
    BrowserContentBlock,
    BrowserDialog,
    BrowserElement,
    BrowserForm,
    BrowserFrame,
    BrowserState,
    BrowserUrlSecurity,
    parse_browser_url_parts,
)


class AgentViewBuilder:
    def build(self, raw: RawPageSnapshot, session_id: str = "default") -> BrowserState:
        interactive_elements = [_sanitize_element(item) for item in raw.interactive_elements]
        forms = [_sanitize_form(item) for item in raw.forms]
        url_parts = parse_browser_url_parts(raw.url)
        return BrowserState(
            session_id=session_id,
            url=raw.url,
            url_parts=url_parts,
            title=raw.title,
            page_status="loading" if raw.loading else "idle",
            focused_element_id=raw.focused_element_id,
            viewport=raw.viewport,
            tabs=raw.tabs,
            visible_text=(raw.visible_text or "")[:VISIBLE_TEXT_MAX_CHARS],
            content_blocks=[BrowserContentBlock(**item) for item in raw.content_blocks],
            forms=[BrowserForm(**item) for item in forms],
            interactive_elements=[BrowserElement(**item) for item in interactive_elements],
            auth=_detect_auth_surface(raw, interactive_elements, forms),
            security=evaluate_url_security(raw.url),
            dialogs=[BrowserDialog(**item) for item in raw.dialogs],
            frames=[_build_frame(item) for item in raw.frames],
            error=None,
        )


def _build_frame(item: dict) -> BrowserFrame:
    url = str(item.get("url", ""))
    return BrowserFrame(
        id=str(item.get("id", "frame_1")),
        parent_id=item.get("parent_id"),
        url=url,
        title=str(item.get("title", "")),
        same_origin=bool(item.get("same_origin", True)),
        visible=bool(item.get("visible", True)),
        security=evaluate_url_security(url) if url else BrowserUrlSecurity(),
    )


def _sanitize_element(item: dict) -> dict:
    sanitized = dict(item)
    if _is_protected_field(sanitized, type_key="input_type"):
        sanitized["value"] = ""
    return sanitized


def _sanitize_form(item: dict) -> dict:
    sanitized = dict(item)
    field_details = []
    for field in sanitized.get("field_details", []):
        clean = dict(field)
        if _is_protected_field(clean, type_key="type"):
            clean["value"] = ""
        field_details.append(clean)
    sanitized["field_details"] = field_details
    return sanitized


def _is_protected_field(value: dict, *, type_key: str) -> bool:
    input_type = str(value.get(type_key) or "").lower()
    autocomplete = str(value.get("autocomplete") or "").lower()
    combined = " ".join(
        str(value.get(key) or "").lower()
        for key in ("name", "field_name", "placeholder", "key", "label")
    )
    if input_type in {"password", "file"}:
        return True
    if autocomplete in {"one-time-code", "cc-number", "cc-csc", "cc-exp", "cc-exp-month", "cc-exp-year"}:
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


def _detect_auth_surface(raw: RawPageSnapshot, elements: list[dict], forms: list[dict]) -> BrowserAuthState:
    reasons: list[str] = []
    visible_text = (raw.visible_text or "").lower()
    url = (raw.url or "").lower()
    title = (raw.title or "").lower()
    frame_text = " ".join(str(frame.get("title") or "").lower() for frame in raw.frames)
    combined_text = " ".join(
        [
            visible_text,
            title,
            frame_text,
            " ".join(str(element.get("name") or "").lower() for element in elements),
            " ".join(str(element.get("placeholder") or "").lower() for element in elements),
        ]
    )
    login_like_url = any(marker in url for marker in ("/login", "/signin", "auth", "passport", "cancel_login"))
    has_login_text = any(
        marker in combined_text
        for marker in (
            "login",
            "log in",
            "sign in",
            "登录",
            "登陆",
            "邮箱登录",
            "手机号登录",
            "密码登录",
            "账号登录",
            "qq登录",
            "微信登录",
        )
    )
    has_password_input = False
    has_login_input = False
    if login_like_url and has_login_text:
        reasons.append("login_url")
    has_human_auth_text = any(
        marker in combined_text
        for marker in (
            "扫码",
            "二维码",
            "qr code",
            "verification code",
            "验证码",
            "2fa",
            "two-factor",
            "授权",
            "authorize",
        )
    )
    for element in elements:
        input_type = str(element.get("input_type") or "").lower()
        name = str(element.get("name") or "").lower()
        placeholder = str(element.get("placeholder") or "").lower()
        if input_type == "password":
            has_password_input = True
        if input_type in {"email", "tel"} and (login_like_url or has_login_text):
            has_login_input = True
            reasons.append(f"{input_type}_login_input")
        if any(marker in f"{name} {placeholder}" for marker in ("password", "密码")):
            has_password_input = True
    for form in forms:
        text = str(form.get("text") or "").lower()
        if any(marker in text for marker in ("password", "密码")):
            has_password_input = True
        if any(marker in text for marker in ("验证码", "扫码")) and (login_like_url or has_login_text):
            reasons.append("auth_form")
    if has_password_input:
        reasons.append("password_input")
    if has_human_auth_text and (login_like_url or has_login_text or has_password_input or has_login_input):
        reasons.append("human_auth_text")

    deduped = list(dict.fromkeys(reasons))
    detected = bool(deduped)
    return BrowserAuthState(
        surface_detected=detected,
        takeover="none",
        reason=deduped,
        user_action_required=detected,
    )
