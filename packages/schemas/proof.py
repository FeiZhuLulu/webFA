"""Proof schemas for request/response."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from schemas.common import VerificationResult


class ProofResource(BaseModel):
    type: str
    id: str
    url: str | None = None


class ProofHashes(BaseModel):
    plan_hash: str
    diff_hash: str | None = None
    proof_hash: str


class ProofBundle(BaseModel):
    proof_version: str = "0.1"
    provider: str
    transaction_id: str
    plan_id: str
    execution_id: str
    resource: ProofResource
    hashes: ProofHashes
    verification: VerificationResult
    created_at: str | None = None


class ProofRead(BaseModel):
    id: str
    execution_id: str
    provider: str
    proof_type: str
    resource_type: str | None = None
    resource_id: str | None = None
    url: str | None = None
    hash: str | None = None
    proof: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
