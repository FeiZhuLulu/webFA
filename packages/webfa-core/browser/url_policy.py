"""Lightweight URL policy for developer-preview hardening.

This is not production-grade SSRF or internal-network isolation: classification
uses the hostname string only (no DNS resolution) and standard IP parsing only.
Known gaps (DNS aliases to loopback, non-dotted IP literals) are tracked for a
later hardening phase.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit

from browser.action_log import SENSITIVE_MESSAGE_KEYS
from browser.runtime_errors import BrowserRuntimeError, navigation_blocked, private_url_blocked, sensitive_url_blocked
from schemas.browser import BrowserUrlSecurity, UrlClass, UrlPolicy


DEFAULT_PRIVATE_URL_POLICY = "warn"
SUPPORTED_PRIVATE_URL_POLICIES = {"allow", "warn", "block"}
METADATA_HOST = "169.254.169.254"
PRIVATE_SUFFIXES = (".local", ".lan", ".internal")


@dataclass(frozen=True)
class UrlClassification:
    url_class: UrlClass
    risk_flags: tuple[str, ...] = ()
    hard_block: bool = False


def resolve_private_url_policy() -> UrlPolicy:
    value = os.getenv("WEBFA_PRIVATE_URL_POLICY", DEFAULT_PRIVATE_URL_POLICY).lower()
    if value not in SUPPORTED_PRIVATE_URL_POLICIES:
        supported = "', '".join(sorted(SUPPORTED_PRIVATE_URL_POLICIES))
        raise ValueError(f"WEBFA_PRIVATE_URL_POLICY must be '{supported}'")
    return value  # type: ignore[return-value]


def classify_url(url: str) -> UrlClassification:
    normalized = (url or "").strip()
    if normalized in {"about:blank", "about:srcdoc"} or normalized.startswith("about:blank#"):
        return UrlClassification(url_class="public", risk_flags=())

    try:
        parts = urlsplit(url)
    except ValueError:
        return UrlClassification(url_class="blocked", risk_flags=("invalid_url",), hard_block=True)

    scheme = (parts.scheme or "").lower()
    if scheme == "about":
        return UrlClassification(url_class="public", risk_flags=())
    if scheme not in {"http", "https", "file"}:
        return UrlClassification(url_class="blocked", risk_flags=("unsupported_scheme",), hard_block=True)

    if scheme == "file":
        risk_flags = _sensitive_query_flags(parts.query)
        return UrlClassification(url_class="file", risk_flags=risk_flags)

    host = (parts.hostname or "").lower().strip(".")
    if not host:
        return UrlClassification(url_class="blocked", risk_flags=("missing_host",), hard_block=True)

    if host == METADATA_HOST:
        return UrlClassification(url_class="blocked", risk_flags=("metadata_endpoint",), hard_block=True)

    risk_flags = list(_sensitive_query_flags(parts.query))
    if host in {"localhost", "::1"}:
        return UrlClassification(url_class="local", risk_flags=tuple(risk_flags))
    if _is_private_suffix(host):
        risk_flags.append("private_suffix")
        return UrlClassification(url_class="private", risk_flags=tuple(risk_flags))

    ip_class = _classify_host_ip(host)
    if ip_class == "metadata":
        return UrlClassification(url_class="blocked", risk_flags=("metadata_endpoint",), hard_block=True)
    if ip_class == "local":
        return UrlClassification(url_class="local", risk_flags=tuple(risk_flags))
    if ip_class == "private":
        return UrlClassification(url_class="private", risk_flags=tuple(risk_flags))

    return UrlClassification(url_class="public", risk_flags=tuple(risk_flags))


def evaluate_url_security(url: str, *, policy: UrlPolicy | None = None) -> BrowserUrlSecurity:
    resolved_policy = policy or resolve_private_url_policy()
    classification = classify_url(url)

    if classification.hard_block:
        return BrowserUrlSecurity(
            url_class=classification.url_class,
            risk_flags=list(classification.risk_flags),
            policy="block",
            message="This URL is blocked by WebFA runtime policy",
        )

    if classification.risk_flags and any(flag.startswith("sensitive_query:") for flag in classification.risk_flags):
        if resolved_policy == "block":
            return BrowserUrlSecurity(
                url_class=classification.url_class,
                risk_flags=list(classification.risk_flags),
                policy="block",
                message="URL contains sensitive query parameters",
            )
        return BrowserUrlSecurity(
            url_class=classification.url_class,
            risk_flags=list(classification.risk_flags),
            policy="warn",
            message="URL contains sensitive query parameters",
        )

    if classification.url_class in {"local", "private", "file"}:
        if resolved_policy == "block":
            return BrowserUrlSecurity(
                url_class=classification.url_class,
                risk_flags=list(classification.risk_flags),
                policy="block",
                message=f"{classification.url_class} URLs are blocked by WEBFA_PRIVATE_URL_POLICY=block",
            )
        if resolved_policy == "warn":
            return BrowserUrlSecurity(
                url_class=classification.url_class,
                risk_flags=list(classification.risk_flags),
                policy="warn",
                message=f"{classification.url_class} URL; proceed only for trusted local testing",
            )
        return BrowserUrlSecurity(
            url_class=classification.url_class,
            risk_flags=list(classification.risk_flags),
            policy="allow",
            message=None,
        )

    return BrowserUrlSecurity(
        url_class=classification.url_class,
        risk_flags=list(classification.risk_flags),
        policy="allow",
        message=None,
    )


def should_block_navigation(url: str, *, policy: UrlPolicy | None = None) -> BrowserUrlSecurity | None:
    security = evaluate_url_security(url, policy=policy)
    if security.policy == "block":
        return security
    return None


def enforce_navigation_allowed(url: str, *, policy: UrlPolicy | None = None) -> BrowserUrlSecurity:
    resolved_policy = policy or resolve_private_url_policy()
    security = evaluate_url_security(url, policy=resolved_policy)
    if security.policy != "block":
        return security
    classification = classify_url(url)
    if classification.hard_block:
        raise navigation_blocked(url)
    if any(flag.startswith("sensitive_query:") for flag in security.risk_flags):
        raise sensitive_url_blocked(url)
    raise private_url_blocked(url, policy=resolved_policy)


def _sensitive_query_flags(query: str) -> list[str]:
    flags: list[str] = []
    for key, _value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if any(marker in lowered for marker in SENSITIVE_MESSAGE_KEYS):
            flags.append(f"sensitive_query:{key}")
    return flags


def _is_private_suffix(host: str) -> bool:
    return any(host == suffix[1:] or host.endswith(suffix) for suffix in PRIVATE_SUFFIXES)


def _classify_host_ip(host: str) -> str | None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if str(ip) == METADATA_HOST:
        return "metadata"
    if ip.is_loopback:
        return "local"
    if ip.is_private or ip.is_link_local:
        return "private"
    return "public"