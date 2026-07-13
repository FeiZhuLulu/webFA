from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class BrowserProfileRecord(Base, TimestampMixin):
    __tablename__ = "browser_profiles"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    agent_alias: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    persistence: Mapped[str] = mapped_column(String(32), nullable=False, default="persistent")
    owner: Mapped[str] = mapped_column(String(32), nullable=False, default="shared")
    trust_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="trusted_agent")
    allowed_origins_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    unknown_effect_policy: Mapped[str] = mapped_column(String(32), nullable=False, default="require_step_up")
    safety_policy_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    financial_policy_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    storage_key: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    bootstrap_source: Mapped[str] = mapped_column(String(32), nullable=False, default="blank")
    catalog_state: Mapped[str] = mapped_column(String(32), nullable=False, default="ready")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    agent_bindings: Mapped[list["BrowserProfileAgentBindingRecord"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["BrowserSessionRecord"]] = relationship(back_populates="profile")


class BrowserProfileAgentBindingRecord(Base):
    __tablename__ = "browser_profile_agent_bindings"
    __table_args__ = (UniqueConstraint("profile_id", "agent_id", name="uq_profile_agent_binding"),)

    profile_id: Mapped[str] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    binding_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="allowed")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    profile: Mapped[BrowserProfileRecord] = relationship(back_populates="agent_bindings")


class BrowserSessionRecord(Base, TimestampMixin):
    __tablename__ = "browser_sessions"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    runtime_generation: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    lifecycle: Mapped[str] = mapped_column(String(32), nullable=False, default="created")
    control_state: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    health: Mapped[str] = mapped_column(String(32), nullable=False, default="healthy")
    active_tab_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_agent_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by_connection_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    profile: Mapped[BrowserProfileRecord] = relationship(back_populates="sessions")


class BrowserProfileRuntimeEventRecord(Base):
    __tablename__ = "browser_profile_runtime_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("profile_event"))
    profile_id: Mapped[str] = mapped_column(
        ForeignKey("browser_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("browser_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    safe_metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StorageMigrationRecord(Base):
    __tablename__ = "storage_migrations"

    migration_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProviderConnection(Base, TimestampMixin):
    __tablename__ = "provider_connections"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("provider"))
    provider: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    auth_mode: Mapped[str | None] = mapped_column(String(64), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(256), nullable=True)
    scopes_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    resource_scope_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="disconnected", nullable=False)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Transaction(Base, TimestampMixin):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("workspace"))
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    user_goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="created", nullable=False)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    plans: Mapped[list["Plan"]] = relationship(back_populates="workspace")


class Plan(Base, TimestampMixin):
    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("plan"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    transaction_id: Mapped[str] = mapped_column(String(128), nullable=False)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    steps_json: Mapped[list | None] = mapped_column(JSON, nullable=True)
    risk: Mapped[str] = mapped_column(String(32), nullable=False)
    plan_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)

    workspace: Mapped[Workspace | None] = relationship(back_populates="plans")
    approvals: Mapped[list["Approval"]] = relationship(back_populates="plan")
    executions: Mapped[list["Execution"]] = relationship(back_populates="plan")


class Approval(Base, TimestampMixin):
    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("approval"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False)
    approval_level: Mapped[str] = mapped_column(String(32), nullable=False)
    approval_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    approval_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="approvals")


class Execution(Base, TimestampMixin):
    __tablename__ = "executions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("exec"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(ForeignKey("approvals.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="executions")
    steps: Mapped[list["ExecutionStep"]] = relationship(back_populates="execution")
    proofs: Mapped[list["Proof"]] = relationship(back_populates="execution")


class ExecutionStep(Base):
    __tablename__ = "execution_steps"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("step"))
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id"), nullable=False)
    step_name: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    input_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    execution: Mapped[Execution] = relationship(back_populates="steps")


class Proof(Base):
    __tablename__ = "proofs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("proof"))
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    proof_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    proof_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    execution: Mapped[Execution | None] = relationship(back_populates="proofs")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("audit"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    plan_id: Mapped[str | None] = mapped_column(ForeignKey("plans.id"), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("executions.id"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    event_payload_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ResourceSnapshot(Base):
    __tablename__ = "resource_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("snap"))
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    taint_level: Mapped[str] = mapped_column(String(64), nullable=False, default="external")
    etag: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(128), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
