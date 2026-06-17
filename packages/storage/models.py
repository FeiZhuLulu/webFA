from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, Text
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
