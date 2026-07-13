from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import re
import secrets
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Callable
from urllib.parse import urlparse
from uuid import uuid4

from browser.managed_chromium_host import ManagedChromiumHost
from browser.profile_repository import (
    ProfileRepository,
    ProfileStateError,
    ProfileVersionConflictError,
)
from browser.profile_storage import (
    ProfileLockBusyError,
    ProfileMutationLease,
    ProfileStorageManager,
)
from schemas.profile import BrowserProfile
from schemas.profile_bootstrap import (
    CookieImportCancelResult,
    CookieImportFormat,
    CookieImportPreview,
    CookieImportResult,
    CookieImportSourceFormat,
    CookieImportWarning,
)


MAX_COOKIE_IMPORT_BYTES = 5 * 1024 * 1024
MAX_COOKIE_IMPORT_ENTRIES = 5000
DEFAULT_PREVIEW_TTL_SECONDS = 600
_COOKIE_NAME_RE = re.compile(r'^[^\x00-\x20\x7f()<>@,;:\\"/\[\]?={}]+$')


class ProfileBootstrapError(RuntimeError):
    code = "profile_bootstrap_error"


class CookieImportParseError(ProfileBootstrapError):
    code = "cookie_import_invalid"


class CookieImportLimitError(ProfileBootstrapError):
    code = "cookie_import_limit_exceeded"


class CookieImportPreviewNotFoundError(ProfileBootstrapError):
    code = "cookie_import_preview_not_found"


class CookieImportPreviewExpiredError(ProfileBootstrapError):
    code = "cookie_import_preview_expired"


class CookieImportBindingError(ProfileBootstrapError):
    code = "cookie_import_binding_mismatch"


class CookieImportBusyError(ProfileBootstrapError):
    code = "cookie_import_busy"


class CookieImportApplyError(ProfileBootstrapError):
    code = "cookie_import_failed"


class CookieImportVerificationError(ProfileBootstrapError):
    code = "cookie_import_verification_failed"


class _CookieEntryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class _NormalizedCookie:
    params: dict[str, Any] = field(repr=False)
    domain: str
    secure: bool
    http_only: bool
    session: bool
    partitioned: bool

    def key(self) -> tuple[object, ...]:
        partition = self.params.get("partitionKey")
        if isinstance(partition, dict):
            partition_site = partition.get("topLevelSite", "")
            cross_site = bool(partition.get("hasCrossSiteAncestor", False))
        else:
            partition_site = ""
            cross_site = False
        return (
            self.params["name"],
            self.domain,
            self.params.get("path", "/"),
            partition_site,
            cross_site,
        )


@dataclass(frozen=True)
class _ParsedCookieImport:
    source_format: CookieImportSourceFormat
    total_entries: int
    cookies: tuple[_NormalizedCookie, ...] = field(repr=False)
    rejected_count: int
    warnings: tuple[CookieImportWarning, ...]


@dataclass
class _PendingCookieImport:
    token: str
    control_digest: str
    profile_id: str
    profile_version: int
    source_format: CookieImportSourceFormat
    cookies: tuple[_NormalizedCookie, ...] = field(repr=False)
    summary: CookieImportPreview
    expires_at: datetime
    in_progress: bool = False


class ProfileMaintenanceHost:
    """Bounded browser host used only while a ProfileMutationLease is held."""

    def __init__(
        self,
        profile: BrowserProfile,
        storage: ProfileStorageManager,
        mutation_id: str,
    ) -> None:
        launch_spec = storage.launch_spec(
            profile,
            headless=True,
            runtime_instance_id=f"maintenance:{mutation_id}",
            runtime_generation=f"maintenance:{mutation_id}",
        )
        self._host = ManagedChromiumHost(launch_spec=launch_spec)

    def import_cookies(self, cookies: list[dict[str, Any]]) -> int:
        return self._host.import_cookies(cookies)

    def close(self) -> None:
        self._host.close()


MaintenanceHostFactory = Callable[
    [BrowserProfile, ProfileStorageManager, str],
    ProfileMaintenanceHost,
]
Clock = Callable[[], datetime]


class ProfileBootstrapService:
    def __init__(
        self,
        *,
        repository: ProfileRepository | None = None,
        storage: ProfileStorageManager | None = None,
        host_factory: MaintenanceHostFactory | None = None,
        clock: Clock | None = None,
        preview_ttl_seconds: int = DEFAULT_PREVIEW_TTL_SECONDS,
    ) -> None:
        self._repository = repository or ProfileRepository()
        self._storage = storage or ProfileStorageManager()
        self._host_factory = host_factory or ProfileMaintenanceHost
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._preview_ttl = max(60, min(preview_ttl_seconds, 3600))
        self._pending: dict[str, _PendingCookieImport] = {}
        self._lock = RLock()

    def close(self) -> None:
        with self._lock:
            self._pending.clear()

    def preview_cookie_import(
        self,
        profile_ref: str,
        *,
        expected_version: int,
        content: bytes,
        input_format: CookieImportFormat,
        control_token: str,
    ) -> CookieImportPreview:
        profile = self._repository.get_profile(profile_ref)
        self._require_bootstrap_profile(profile, expected_version=expected_version)
        parsed = parse_cookie_import(content, input_format=input_format)
        if not parsed.cookies:
            raise CookieImportParseError("cookie input contains no importable entries")

        now = self._clock()
        expires_at = now + timedelta(seconds=self._preview_ttl)
        preview_token = f"cookie_preview_{secrets.token_urlsafe(32)}"
        domains = sorted({cookie.domain for cookie in parsed.cookies})
        warnings = list(parsed.warnings)
        if len(domains) > 200:
            warnings.append(CookieImportWarning(code="domain_list_truncated", count=len(domains) - 200))
        summary = CookieImportPreview(
            preview_token=preview_token,
            profile_id=profile.profile_id,
            profile_version=profile.version,
            source_format=parsed.source_format,
            total_entries=parsed.total_entries,
            accepted_count=len(parsed.cookies),
            rejected_count=parsed.rejected_count,
            domain_count=len(domains),
            domains=domains[:200],
            secure_count=sum(cookie.secure for cookie in parsed.cookies),
            http_only_count=sum(cookie.http_only for cookie in parsed.cookies),
            session_count=sum(cookie.session for cookie in parsed.cookies),
            persistent_count=sum(not cookie.session for cookie in parsed.cookies),
            partitioned_count=sum(cookie.partitioned for cookie in parsed.cookies),
            warnings=warnings,
            expires_at=expires_at,
        )
        pending = _PendingCookieImport(
            token=preview_token,
            control_digest=_control_digest(control_token),
            profile_id=profile.profile_id,
            profile_version=profile.version,
            source_format=parsed.source_format,
            cookies=parsed.cookies,
            summary=summary,
            expires_at=expires_at,
        )
        with self._lock:
            self._purge_expired_locked(now)
            if len(self._pending) >= 20:
                oldest = min(self._pending.values(), key=lambda item: item.expires_at)
                self._pending.pop(oldest.token, None)
            self._pending[preview_token] = pending
        self._record_event(
            profile_id=profile.profile_id,
            event_type="cookie_import_previewed",
            safe_metadata={
                "source_format": parsed.source_format,
                "accepted_count": len(parsed.cookies),
                "rejected_count": parsed.rejected_count,
                "domain_count": len(domains),
            },
        )
        return summary.model_copy(deep=True)

    def cancel_cookie_import(
        self,
        profile_ref: str,
        *,
        preview_token: str,
        control_token: str,
    ) -> CookieImportCancelResult:
        now = self._clock()
        profile = self._repository.get_profile(profile_ref)
        with self._lock:
            self._purge_expired_locked(now)
            pending = self._pending.get(preview_token)
            if pending is None:
                raise CookieImportPreviewNotFoundError("cookie import preview was not found")
            if pending.in_progress:
                raise CookieImportBusyError("cookie import preview is already being committed")
            if (
                pending.profile_id != profile.profile_id
                or pending.control_digest != _control_digest(control_token)
            ):
                raise CookieImportBindingError(
                    "cookie import preview is bound to another Profile or control session"
                )
            self._pending.pop(preview_token, None)
        return CookieImportCancelResult(profile_id=profile.profile_id)

    def commit_cookie_import(
        self,
        profile_ref: str,
        *,
        preview_token: str,
        expected_version: int,
        control_token: str,
    ) -> CookieImportResult:
        now = self._clock()
        with self._lock:
            self._purge_expired_locked(now)
            pending = self._pending.get(preview_token)
            if pending is None:
                raise CookieImportPreviewNotFoundError("cookie import preview was not found")
            if pending.expires_at <= now:
                self._pending.pop(preview_token, None)
                raise CookieImportPreviewExpiredError("cookie import preview has expired")
            if pending.in_progress:
                raise CookieImportBusyError("cookie import preview is already being committed")
            if (
                pending.profile_id != self._repository.get_profile(profile_ref).profile_id
                or pending.profile_version != expected_version
                or pending.control_digest != _control_digest(control_token)
            ):
                raise CookieImportBindingError(
                    "cookie import preview is bound to another Profile, version, or control session"
                )
            pending.in_progress = True

        profile = self._repository.get_profile(profile_ref)
        try:
            self._require_bootstrap_profile(profile, expected_version=expected_version)
        except Exception:
            with self._lock:
                pending.in_progress = False
            raise

        mutation_id = f"cookie_import_{uuid4().hex}"
        lease: ProfileMutationLease | None = None
        try:
            lease = self._storage.acquire_mutation_lease(
                profile,
                mutation_id=mutation_id,
                operation="cookie_import",
            )
        except ProfileLockBusyError as exc:
            with self._lock:
                pending.in_progress = False
            raise CookieImportBusyError(
                "target Profile is active; close its Browser Session before importing cookies"
            ) from exc
        except Exception as exc:
            with self._lock:
                pending.in_progress = False
            raise CookieImportApplyError("unable to acquire the Profile maintenance lease") from exc

        with self._lock:
            self._pending.pop(preview_token, None)

        host: ProfileMaintenanceHost | None = None
        cookie_params = [dict(cookie.params) for cookie in pending.cookies]
        try:
            try:
                host = self._host_factory(profile, self._storage, mutation_id)
                verified_count = host.import_cookies(cookie_params)
            except Exception as exc:
                self._record_event(
                    profile_id=profile.profile_id,
                    event_type="cookie_import_failed",
                    safe_metadata={
                        "source_format": pending.source_format,
                        "cookie_count": len(cookie_params),
                        "failure_code": "maintenance_host_error",
                    },
                )
                raise CookieImportApplyError("cookie import failed in the maintenance host") from exc
            finally:
                if host is not None:
                    try:
                        host.close()
                    except Exception:
                        pass

            if verified_count != len(cookie_params):
                self._record_event(
                    profile_id=profile.profile_id,
                    event_type="cookie_import_failed",
                    safe_metadata={
                        "source_format": pending.source_format,
                        "cookie_count": len(cookie_params),
                        "verified_count": verified_count,
                        "failure_code": "verification_mismatch",
                    },
                )
                raise CookieImportVerificationError(
                    "maintenance host could not verify every imported cookie"
                )

            updated = self._repository.mark_bootstrap_source(
                profile.profile_id,
                bootstrap_source="imported",
            )
            occurred_at = self._clock()
            self._record_event(
                profile_id=profile.profile_id,
                event_type="cookies_imported",
                safe_metadata={
                    "source_format": pending.source_format,
                    "imported_count": len(cookie_params),
                    "verified_count": verified_count,
                    "domain_count": pending.summary.domain_count,
                },
            )
            return CookieImportResult(
                profile_id=profile.profile_id,
                profile_version=updated.version,
                source_format=pending.source_format,
                imported_count=len(cookie_params),
                verified_count=verified_count,
                domain_count=pending.summary.domain_count,
                occurred_at=occurred_at,
            )
        finally:
            lease.release()

    def _record_event(
        self,
        *,
        profile_id: str,
        event_type: str,
        safe_metadata: dict[str, Any],
    ) -> None:
        try:
            self._repository.record_runtime_event(
                profile_id=profile_id,
                event_type=event_type,
                safe_metadata=safe_metadata,
            )
        except Exception:
            # Audit failure must not turn a verified storage mutation into a
            # misleading Cookie-import failure response.
            pass

    @staticmethod
    def _require_bootstrap_profile(profile: BrowserProfile, *, expected_version: int) -> None:
        if profile.version != expected_version:
            raise ProfileVersionConflictError(
                f"profile version is {profile.version}, expected {expected_version}"
            )
        if profile.catalog_state != "ready":
            raise ProfileStateError(
                f"profile in state '{profile.catalog_state}' cannot be bootstrapped"
            )
        if profile.persistence != "persistent":
            raise ProfileStateError("cookie import requires a persistent Browser Profile")

    def _purge_expired_locked(self, now: datetime) -> None:
        expired = [
            token
            for token, pending in self._pending.items()
            if pending.expires_at <= now and not pending.in_progress
        ]
        for token in expired:
            self._pending.pop(token, None)


def parse_cookie_import(
    content: bytes,
    *,
    input_format: CookieImportFormat = "auto",
) -> _ParsedCookieImport:
    if not content:
        raise CookieImportParseError("cookie input is empty")
    if len(content) > MAX_COOKIE_IMPORT_BYTES:
        raise CookieImportLimitError("cookie input exceeds the 5 MiB limit")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CookieImportParseError("cookie input must be UTF-8 text") from exc
    selected = _detect_format(text) if input_format == "auto" else input_format
    if selected == "json":
        entries = _parse_json_entries(text)
        normalizer = _normalize_json_cookie
    elif selected == "netscape":
        entries = _parse_netscape_entries(text)
        normalizer = _normalize_netscape_cookie
    else:
        raise CookieImportParseError("unsupported cookie input format")
    if len(entries) > MAX_COOKIE_IMPORT_ENTRIES:
        raise CookieImportLimitError("cookie input exceeds the 5000-entry limit")

    warnings: Counter[str] = Counter()
    normalized: dict[tuple[object, ...], _NormalizedCookie] = {}
    rejected = 0
    for entry in entries:
        try:
            cookie, cookie_warnings = normalizer(entry)
        except _CookieEntryError as exc:
            warnings[exc.code] += 1
            rejected += 1
            continue
        for code in cookie_warnings:
            warnings[code] += 1
        key = cookie.key()
        if key in normalized:
            warnings["duplicate_cookie_replaced"] += 1
            rejected += 1
        normalized[key] = cookie
    return _ParsedCookieImport(
        source_format=selected,
        total_entries=len(entries),
        cookies=tuple(normalized.values()),
        rejected_count=rejected,
        warnings=tuple(
            CookieImportWarning(code=code, count=count)
            for code, count in sorted(warnings.items())
        ),
    )


def _detect_format(text: str) -> CookieImportSourceFormat:
    stripped = text.lstrip()
    if stripped.startswith("[") or stripped.startswith("{"):
        return "json"
    return "netscape"


def _parse_json_entries(text: str) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CookieImportParseError("cookie JSON is malformed") from exc
    if isinstance(payload, dict):
        payload = payload.get("cookies")
    if not isinstance(payload, list):
        raise CookieImportParseError("cookie JSON must be an array or an object with a cookies array")
    entries: list[dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict):
            entries.append(item)
        else:
            entries.append({"__invalid_entry__": True})
    return entries


def _parse_netscape_entries(text: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.strip("\r\n")
        if not line.strip():
            continue
        http_only = False
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :]
            http_only = True
        elif line.lstrip().startswith("#"):
            continue
        parts = line.split("\t", 6)
        if len(parts) != 7:
            entries.append({"__invalid_entry__": True})
            continue
        domain, include_subdomains, path, secure, expires, name, value = parts
        entries.append(
            {
                "domain": domain,
                "include_subdomains": include_subdomains,
                "path": path,
                "secure": secure,
                "expires": expires,
                "name": name,
                "value": value,
                "http_only": http_only,
            }
        )
    return entries


def _normalize_json_cookie(entry: dict[str, Any]) -> tuple[_NormalizedCookie, list[str]]:
    if entry.get("__invalid_entry__"):
        raise _CookieEntryError("entry_not_object")
    name = _cookie_name(entry.get("name"))
    value = _cookie_value(entry.get("value"))
    secure = _optional_bool(entry, "secure", default=False)
    http_only = _optional_bool_alias(entry, ("httpOnly", "http_only"), default=False)
    path = _cookie_path(entry.get("path", "/"))
    raw_url = entry.get("url")
    url = _cookie_url(raw_url) if raw_url is not None else None
    raw_domain = entry.get("domain")
    domain = _cookie_domain(raw_domain) if raw_domain is not None else ""
    if not domain and url is None:
        raise _CookieEntryError("domain_or_url_required")
    host_only = _optional_bool_alias(
        entry,
        ("hostOnly", "host_only"),
        default=bool(url is not None or (domain and not domain.startswith("."))),
    )
    if url is not None:
        summary_domain = urlparse(url).hostname or ""
    else:
        summary_domain = domain.lstrip(".")
        if host_only:
            scheme = "https" if secure else "http"
            url = f"{scheme}://{summary_domain}/"
    params: dict[str, Any] = {
        "name": name,
        "value": value,
        "path": path,
        "secure": secure,
        "httpOnly": http_only,
    }
    if host_only:
        params["url"] = url
    elif domain:
        params["domain"] = domain
    elif url is not None:
        params["url"] = url

    warnings: list[str] = []
    same_site = _same_site(entry.get("sameSite", entry.get("same_site")))
    if same_site is not None:
        if same_site == "None" and not secure:
            raise _CookieEntryError("same_site_none_requires_secure")
        params["sameSite"] = same_site
    session = _optional_bool(entry, "session", default=False)
    expires = _expires_value(
        entry.get("expirationDate", entry.get("expiration_date", entry.get("expires"))),
        session=session,
    )
    if expires is not None:
        params["expires"] = expires
    else:
        session = True
    priority = _priority(entry.get("priority"))
    if priority is not None:
        params["priority"] = priority
    source_scheme = _source_scheme(entry.get("sourceScheme", entry.get("source_scheme")))
    if source_scheme is not None:
        params["sourceScheme"] = source_scheme
    source_port = entry.get("sourcePort", entry.get("source_port"))
    if source_port is not None:
        params["sourcePort"] = _source_port(source_port)
    partition_key = _partition_key(entry.get("partitionKey", entry.get("partition_key")))
    if partition_key is not None:
        params["partitionKey"] = partition_key
    _validate_prefix_constraints(name, params, host_only=host_only)
    if raw_domain is not None and str(raw_domain).strip() != domain:
        warnings.append("domain_normalized")
    return (
        _NormalizedCookie(
            params=params,
            domain=summary_domain.lower(),
            secure=secure,
            http_only=http_only,
            session=session,
            partitioned=partition_key is not None,
        ),
        warnings,
    )


def _normalize_netscape_cookie(entry: dict[str, Any]) -> tuple[_NormalizedCookie, list[str]]:
    if entry.get("__invalid_entry__"):
        raise _CookieEntryError("netscape_line_invalid")
    include_subdomains = _parse_bool(entry.get("include_subdomains"), code="include_subdomains_invalid")
    domain = _cookie_domain(entry.get("domain"))
    summary_domain = domain.lstrip(".")
    secure = _parse_bool(entry.get("secure"), code="secure_flag_invalid")
    http_only = bool(entry.get("http_only", False))
    path = _cookie_path(entry.get("path", "/"))
    name = _cookie_name(entry.get("name"))
    value = _cookie_value(entry.get("value"))
    host_only = not include_subdomains
    params: dict[str, Any] = {
        "name": name,
        "value": value,
        "path": path,
        "secure": secure,
        "httpOnly": http_only,
    }
    if host_only:
        scheme = "https" if secure else "http"
        params["url"] = f"{scheme}://{summary_domain}/"
    else:
        params["domain"] = domain if domain.startswith(".") else f".{domain}"
    expires = _expires_value(entry.get("expires"), session=False)
    session = expires is None
    if expires is not None:
        params["expires"] = expires
    _validate_prefix_constraints(name, params, host_only=host_only)
    return (
        _NormalizedCookie(
            params=params,
            domain=summary_domain.lower(),
            secure=secure,
            http_only=http_only,
            session=session,
            partitioned=False,
        ),
        [],
    )


def _cookie_name(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise _CookieEntryError("cookie_name_invalid")
    if not _COOKIE_NAME_RE.fullmatch(value):
        raise _CookieEntryError("cookie_name_invalid")
    return value


def _cookie_value(value: object) -> str:
    if not isinstance(value, str):
        raise _CookieEntryError("cookie_value_invalid")
    if len(value) > 4096 or any(char in value for char in ("\0", "\r", "\n")):
        raise _CookieEntryError("cookie_value_invalid")
    return value


def _cookie_path(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 2048:
        raise _CookieEntryError("cookie_path_invalid")
    return value


def _cookie_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > 4096:
        raise _CookieEntryError("cookie_url_invalid")
    parsed = urlparse(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise _CookieEntryError("cookie_url_invalid")
    return value


def _cookie_domain(value: object) -> str:
    if not isinstance(value, str):
        raise _CookieEntryError("cookie_domain_invalid")
    raw = value.strip().lower()
    if not raw or len(raw) > 253 or any(char.isspace() for char in raw):
        raise _CookieEntryError("cookie_domain_invalid")
    leading_dot = raw.startswith(".")
    host = raw.lstrip(".")
    if not host or "/" in host or "://" in host or "\0" in host:
        raise _CookieEntryError("cookie_domain_invalid")
    try:
        ipaddress.ip_address(host)
        normalized = host
    except ValueError:
        try:
            normalized = host.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise _CookieEntryError("cookie_domain_invalid") from exc
        labels = normalized.split(".")
        if any(
            not label
            or len(label) > 63
            or label.startswith("-")
            or label.endswith("-")
            or not re.fullmatch(r"[a-z0-9-]+", label)
            for label in labels
        ):
            raise _CookieEntryError("cookie_domain_invalid")
    return f".{normalized}" if leading_dot else normalized


def _same_site(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _CookieEntryError("same_site_invalid")
    normalized = value.strip().lower().replace("-", "_")
    mapping = {
        "strict": "Strict",
        "lax": "Lax",
        "none": "None",
        "no_restriction": "None",
        "unspecified": None,
    }
    if normalized not in mapping:
        raise _CookieEntryError("same_site_invalid")
    return mapping[normalized]


def _priority(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _CookieEntryError("priority_invalid")
    mapping = {"low": "Low", "medium": "Medium", "high": "High"}
    result = mapping.get(value.strip().lower())
    if result is None:
        raise _CookieEntryError("priority_invalid")
    return result


def _source_scheme(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _CookieEntryError("source_scheme_invalid")
    mapping = {
        "unset": "Unset",
        "nonsecure": "NonSecure",
        "non_secure": "NonSecure",
        "secure": "Secure",
    }
    result = mapping.get(value.strip().lower())
    if result is None:
        raise _CookieEntryError("source_scheme_invalid")
    return result


def _source_port(value: object) -> int:
    if isinstance(value, bool):
        raise _CookieEntryError("source_port_invalid")
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise _CookieEntryError("source_port_invalid") from exc
    if port != -1 and not 1 <= port <= 65535:
        raise _CookieEntryError("source_port_invalid")
    return port


def _partition_key(value: object) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, str):
        top_level_site = value
        cross_site = False
    elif isinstance(value, dict):
        top_level_site = value.get("topLevelSite", value.get("top_level_site"))
        cross_site = _optional_bool_alias(
            value,
            ("hasCrossSiteAncestor", "has_cross_site_ancestor"),
            default=False,
        )
    else:
        raise _CookieEntryError("partition_key_invalid")
    if not isinstance(top_level_site, str):
        raise _CookieEntryError("partition_key_invalid")
    parsed = urlparse(top_level_site)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise _CookieEntryError("partition_key_invalid")
    return {
        "topLevelSite": f"{parsed.scheme}://{parsed.hostname}",
        "hasCrossSiteAncestor": cross_site,
    }


def _expires_value(value: object, *, session: bool) -> float | None:
    if session or value is None or value == "":
        return None
    if isinstance(value, bool):
        raise _CookieEntryError("cookie_expiry_invalid")
    try:
        expires = float(value)
    except (TypeError, ValueError) as exc:
        raise _CookieEntryError("cookie_expiry_invalid") from exc
    if not math.isfinite(expires):
        raise _CookieEntryError("cookie_expiry_invalid")
    if expires <= 0:
        return None
    if expires > 253_402_300_799:
        expires /= 1000
    if expires <= time.time():
        raise _CookieEntryError("cookie_expired")
    if expires > 253_402_300_799:
        raise _CookieEntryError("cookie_expiry_invalid")
    return expires


def _validate_prefix_constraints(
    name: str,
    params: dict[str, Any],
    *,
    host_only: bool,
) -> None:
    secure = bool(params.get("secure", False))
    if name.startswith("__Secure-") and not secure:
        raise _CookieEntryError("secure_prefix_requires_secure")
    if name.startswith("__Host-"):
        if not secure or params.get("path") != "/" or not host_only:
            raise _CookieEntryError("host_prefix_scope_invalid")


def _optional_bool(entry: dict[str, Any], key: str, *, default: bool) -> bool:
    if key not in entry or entry[key] is None:
        return default
    return _parse_bool(entry[key], code=f"{key}_invalid")


def _optional_bool_alias(
    entry: dict[str, Any],
    keys: tuple[str, ...],
    *,
    default: bool,
) -> bool:
    for key in keys:
        if key in entry and entry[key] is not None:
            return _parse_bool(entry[key], code=f"{key}_invalid")
    return default


def _parse_bool(value: object, *, code: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    raise _CookieEntryError(code)


def _control_digest(control_token: str) -> str:
    if not control_token:
        raise CookieImportBindingError("visualizer control token is required")
    return hashlib.sha256(control_token.encode("utf-8")).hexdigest()
