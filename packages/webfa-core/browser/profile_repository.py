from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from schemas.profile import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserSessionMetadata,
    SessionControlState,
    SessionHealth,
    SessionLifecycle,
)
from schemas.safety import ProfileOwnershipMetadata
from storage.db import session_scope
from storage.models import (
    BrowserProfileAgentBindingRecord,
    BrowserProfileRecord,
    BrowserProfileRuntimeEventRecord,
    BrowserSessionRecord,
)


class ProfileRepositoryError(RuntimeError):
    code = "profile_repository_error"


class ProfileNotFoundError(ProfileRepositoryError):
    code = "profile_not_found"


class ProfileConflictError(ProfileRepositoryError):
    code = "profile_conflict"


class ProfileVersionConflictError(ProfileRepositoryError):
    code = "profile_version_conflict"


class ProfileStateError(ProfileRepositoryError):
    code = "profile_state_invalid"


class SessionNotFoundError(ProfileRepositoryError):
    code = "session_not_found"


class ProfileRepository:
    def ensure_default_profile(self) -> BrowserProfile:
        try:
            return self.get_profile("default")
        except ProfileNotFoundError:
            try:
                return self.create_profile(
                    BrowserProfileCreate(
                        agent_alias="default",
                        display_name="WebFA Default Profile",
                        agent_description="Default WebFA internet identity",
                        persistence="persistent",
                        owner="shared",
                        trust_mode="trusted_agent",
                        bootstrap_source="blank",
                    ),
                    profile_id="default",
                )
            except ProfileConflictError:
                return self.get_profile("default")

    def create_profile(
        self,
        payload: BrowserProfileCreate,
        *,
        profile_id: str | None = None,
    ) -> BrowserProfile:
        normalized_id = profile_id or f"profile_{uuid4().hex}"
        storage_key = f"profiles/{normalized_id}"
        record = BrowserProfileRecord(
            id=normalized_id,
            agent_alias=payload.agent_alias,
            display_name=payload.display_name,
            agent_description=payload.agent_description,
            persistence=payload.persistence,
            owner=payload.owner,
            trust_mode=payload.trust_mode,
            allowed_origins_json=list(payload.allowed_origins),
            unknown_effect_policy=payload.unknown_external_effect_policy or "require_step_up",
            safety_policy_id=payload.safety_policy_id,
            financial_policy_id=payload.financial_policy_id,
            storage_key=storage_key,
            bootstrap_source=payload.bootstrap_source,
            catalog_state="ready",
            version=1,
        )
        record.agent_bindings = [
            BrowserProfileAgentBindingRecord(agent_id=agent_id, binding_mode="allowed")
            for agent_id in payload.bound_agent_ids
        ]
        try:
            with session_scope() as session:
                session.add(record)
                session.flush()
                session.refresh(record)
                return _profile_from_record(record)
        except IntegrityError as exc:
            raise ProfileConflictError("profile id, alias, or storage reference already exists") from exc

    def get_profile(self, profile_ref: str) -> BrowserProfile:
        with session_scope() as session:
            record = session.get(BrowserProfileRecord, profile_ref)
            if record is None:
                record = session.scalar(
                    select(BrowserProfileRecord).where(BrowserProfileRecord.agent_alias == profile_ref)
                )
            if record is None:
                raise ProfileNotFoundError(f"browser profile '{profile_ref}' was not found")
            _load_bindings(record)
            return _profile_from_record(record)

    def list_profiles(self, *, include_archived: bool = True) -> list[BrowserProfile]:
        with session_scope() as session:
            query = select(BrowserProfileRecord).order_by(BrowserProfileRecord.created_at, BrowserProfileRecord.id)
            if not include_archived:
                query = query.where(BrowserProfileRecord.catalog_state == "ready")
            records = list(session.scalars(query).all())
            for record in records:
                _load_bindings(record)
            return [_profile_from_record(record) for record in records]

    def update_profile(self, profile_ref: str, payload: BrowserProfileUpdate) -> BrowserProfile:
        try:
            with session_scope() as session:
                record = _require_profile_record(session, profile_ref)
                if record.version != payload.expected_version:
                    raise ProfileVersionConflictError(
                        f"profile version is {record.version}, expected {payload.expected_version}"
                    )
                if record.catalog_state in {"deleting", "error"}:
                    raise ProfileStateError(
                        f"profile in state '{record.catalog_state}' cannot be edited"
                    )
                changes = payload.model_dump(exclude_unset=True)
                changes.pop("expected_version", None)
                bound_agent_ids = changes.pop("bound_agent_ids", None)
                allowed_origins = changes.pop("allowed_origins", None)
                if "unknown_external_effect_policy" in changes:
                    unknown_policy = changes.pop("unknown_external_effect_policy")
                    if unknown_policy is not None:
                        record.unknown_effect_policy = unknown_policy
                for field, value in changes.items():
                    setattr(record, field, value)
                if allowed_origins is not None:
                    record.allowed_origins_json = list(allowed_origins)
                if bound_agent_ids is not None:
                    record.agent_bindings.clear()
                    record.agent_bindings.extend(
                        BrowserProfileAgentBindingRecord(agent_id=agent_id, binding_mode="allowed")
                        for agent_id in bound_agent_ids
                    )
                record.version += 1
                session.flush()
                session.refresh(record)
                _load_bindings(record)
                return _profile_from_record(record)
        except IntegrityError as exc:
            raise ProfileConflictError("profile alias already exists") from exc

    def archive_profile(self, profile_ref: str, *, expected_version: int) -> BrowserProfile:
        with session_scope() as session:
            record = _require_profile_record(session, profile_ref)
            if record.id == "default":
                raise ProfileStateError("the default profile cannot be archived")
            if record.version != expected_version:
                raise ProfileVersionConflictError(
                    f"profile version is {record.version}, expected {expected_version}"
                )
            if _has_active_session(session, record.id):
                raise ProfileStateError("profile with an active session cannot be archived")
            record.catalog_state = "archived"
            record.version += 1
            session.flush()
            session.refresh(record)
            _load_bindings(record)
            return _profile_from_record(record)

    def restore_profile(self, profile_ref: str, *, expected_version: int) -> BrowserProfile:
        with session_scope() as session:
            record = _require_profile_record(session, profile_ref)
            if record.version != expected_version:
                raise ProfileVersionConflictError(
                    f"profile version is {record.version}, expected {expected_version}"
                )
            if record.catalog_state != "archived":
                raise ProfileStateError("only archived profiles can be restored")
            record.catalog_state = "ready"
            record.version += 1
            session.flush()
            session.refresh(record)
            _load_bindings(record)
            return _profile_from_record(record)

    def get_policy(self, profile_ref: str) -> ProfileOwnershipMetadata:
        profile = self.get_profile(profile_ref)
        return ProfileOwnershipMetadata(
            profile_id=profile.profile_id,
            owner=profile.owner,
            bound_agent_ids=profile.bound_agent_ids,
            allowed_origins=profile.allowed_origins,
            safety_policy_id=profile.safety_policy_id,
            financial_policy_id=profile.financial_policy_id,
            trust_mode=profile.trust_mode,
            unknown_external_effect_policy=profile.unknown_external_effect_policy,
        )

    def upsert_policy(self, metadata: ProfileOwnershipMetadata) -> ProfileOwnershipMetadata:
        try:
            profile = self.get_profile(metadata.profile_id)
        except ProfileNotFoundError:
            created = self.create_profile(
                BrowserProfileCreate(
                    agent_alias=_safe_alias(metadata.profile_id),
                    display_name=f"WebFA Profile {metadata.profile_id}",
                    owner=metadata.owner,
                    trust_mode=metadata.trust_mode,
                    bound_agent_ids=metadata.bound_agent_ids,
                    allowed_origins=metadata.allowed_origins,
                    unknown_external_effect_policy=metadata.unknown_external_effect_policy,
                    safety_policy_id=metadata.safety_policy_id,
                    financial_policy_id=metadata.financial_policy_id,
                ),
                profile_id=metadata.profile_id,
            )
            profile = created
        updated = self.update_profile(
            profile.profile_id,
            BrowserProfileUpdate(
                expected_version=profile.version,
                owner=metadata.owner,
                trust_mode=metadata.trust_mode,
                bound_agent_ids=metadata.bound_agent_ids,
                allowed_origins=metadata.allowed_origins,
                unknown_external_effect_policy=metadata.unknown_external_effect_policy,
                safety_policy_id=metadata.safety_policy_id,
                financial_policy_id=metadata.financial_policy_id,
            ),
        )
        return self.get_policy(updated.profile_id)

    def mark_profile_used(self, profile_id: str) -> None:
        with session_scope() as session:
            record = session.get(BrowserProfileRecord, profile_id)
            if record is not None:
                record.last_used_at = _utc_now()

    def record_runtime_event(
        self,
        *,
        profile_id: str,
        event_type: str,
        session_id: str | None = None,
        safe_metadata: dict | None = None,
    ) -> None:
        with session_scope() as session:
            session.add(
                BrowserProfileRuntimeEventRecord(
                    profile_id=profile_id,
                    session_id=session_id,
                    event_type=event_type,
                    safe_metadata_json=safe_metadata or {},
                )
            )


class BrowserSessionRepository:
    def create_session(
        self,
        *,
        session_id: str,
        profile_id: str,
        runtime_generation: str,
        created_by_agent_id: str | None = None,
        created_by_connection_id: str | None = None,
    ) -> BrowserSessionMetadata:
        record = BrowserSessionRecord(
            id=session_id,
            profile_id=profile_id,
            runtime_generation=runtime_generation,
            lifecycle="created",
            control_state="idle",
            health="healthy",
            created_by_agent_id=created_by_agent_id,
            created_by_connection_id=created_by_connection_id,
        )
        try:
            with session_scope() as session:
                if session.get(BrowserProfileRecord, profile_id) is None:
                    raise ProfileConflictError(
                        f"browser profile '{profile_id}' was not found"
                    )
                session.add(record)
                session.flush()
                session.refresh(record)
                return _session_from_record(record)
        except IntegrityError as exc:
            raise ProfileConflictError("session id already exists") from exc

    def get_session(self, session_id: str) -> BrowserSessionMetadata:
        with session_scope() as session:
            record = session.get(BrowserSessionRecord, session_id)
            if record is None:
                raise SessionNotFoundError(f"browser session '{session_id}' was not found")
            return _session_from_record(record)

    def list_sessions(self, *, profile_id: str | None = None) -> list[BrowserSessionMetadata]:
        with session_scope() as session:
            query = select(BrowserSessionRecord).order_by(
                BrowserSessionRecord.created_at,
                BrowserSessionRecord.id,
            )
            if profile_id is not None:
                query = query.where(BrowserSessionRecord.profile_id == profile_id)
            return [_session_from_record(row) for row in session.scalars(query).all()]

    def transition(
        self,
        session_id: str,
        *,
        lifecycle: SessionLifecycle | None = None,
        control_state: SessionControlState | None = None,
        health: SessionHealth | None = None,
        active_tab_id: str | None = None,
        close_reason: str | None = None,
    ) -> BrowserSessionMetadata:
        now = _utc_now()
        with session_scope() as session:
            record = session.get(BrowserSessionRecord, session_id)
            if record is None:
                raise SessionNotFoundError(f"browser session '{session_id}' was not found")
            if lifecycle is not None:
                record.lifecycle = lifecycle
                if lifecycle == "running" and record.started_at is None:
                    record.started_at = now
                if lifecycle in {"closed", "crashed", "interrupted"}:
                    record.stopped_at = now
            if control_state is not None:
                record.control_state = control_state
            if health is not None:
                record.health = health
            if active_tab_id is not None:
                record.active_tab_id = active_tab_id
            if close_reason is not None:
                record.close_reason = close_reason[:500]
            record.last_activity_at = now
            session.flush()
            session.refresh(record)
            return _session_from_record(record)

    def touch(self, session_id: str, *, active_tab_id: str | None = None) -> None:
        with session_scope() as session:
            record = session.get(BrowserSessionRecord, session_id)
            if record is None:
                return
            record.last_activity_at = _utc_now()
            if active_tab_id is not None:
                record.active_tab_id = active_tab_id

    def interrupt_nonterminal_sessions(self, *, profile_id: str | None = None) -> int:
        terminal = {"closed", "crashed", "interrupted"}
        now = _utc_now()
        changed = 0
        with session_scope() as session:
            query = select(BrowserSessionRecord)
            if profile_id is not None:
                query = query.where(BrowserSessionRecord.profile_id == profile_id)
            records = list(session.scalars(query).all())
            for record in records:
                if record.lifecycle not in terminal:
                    record.lifecycle = "interrupted"
                    record.health = "failed"
                    record.stopped_at = now
                    record.last_activity_at = now
                    record.close_reason = "runtime restarted before durable session resume was available"
                    changed += 1
        return changed


def _require_profile_record(session, profile_ref: str) -> BrowserProfileRecord:
    record = session.get(BrowserProfileRecord, profile_ref)
    if record is None:
        record = session.scalar(
            select(BrowserProfileRecord).where(BrowserProfileRecord.agent_alias == profile_ref)
        )
    if record is None:
        raise ProfileNotFoundError(f"browser profile '{profile_ref}' was not found")
    _load_bindings(record)
    return record


def _has_active_session(session, profile_id: str) -> bool:
    active_lifecycles = {"created", "starting", "running", "stopping"}
    rows = session.scalars(
        select(BrowserSessionRecord.lifecycle).where(BrowserSessionRecord.profile_id == profile_id)
    ).all()
    return any(value in active_lifecycles for value in rows)


def _load_bindings(record: BrowserProfileRecord) -> None:
    _ = list(record.agent_bindings)


def _profile_from_record(record: BrowserProfileRecord) -> BrowserProfile:
    return BrowserProfile(
        profile_id=record.id,
        agent_alias=record.agent_alias,
        display_name=record.display_name,
        agent_description=record.agent_description or "",
        persistence=record.persistence,
        owner=record.owner,
        trust_mode=record.trust_mode,
        bound_agent_ids=sorted(binding.agent_id for binding in record.agent_bindings),
        allowed_origins=list(record.allowed_origins_json or []),
        unknown_external_effect_policy=record.unknown_effect_policy,
        safety_policy_id=record.safety_policy_id,
        financial_policy_id=record.financial_policy_id,
        storage_ref=record.storage_key,
        bootstrap_source=record.bootstrap_source,
        catalog_state=record.catalog_state,
        version=record.version,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_used_at=record.last_used_at,
    )


def _session_from_record(record: BrowserSessionRecord) -> BrowserSessionMetadata:
    return BrowserSessionMetadata(
        session_id=record.id,
        profile_id=record.profile_id,
        runtime_generation=record.runtime_generation,
        lifecycle=record.lifecycle,
        control_state=record.control_state,
        health=record.health,
        active_tab_id=record.active_tab_id,
        created_by_agent_id=record.created_by_agent_id,
        created_by_connection_id=record.created_by_connection_id,
        created_at=record.created_at,
        started_at=record.started_at,
        last_activity_at=record.last_activity_at,
        stopped_at=record.stopped_at,
        close_reason=record.close_reason,
    )


def _safe_alias(profile_id: str) -> str:
    raw = "".join(char.lower() if char.isalnum() else "-" for char in profile_id).strip("-")
    raw = raw[:64].strip("-") or f"profile-{uuid4().hex[:12]}"
    if len(raw) == 1:
        return raw
    return raw


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
