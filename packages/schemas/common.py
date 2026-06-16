"""Shared types for WebFA schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RiskLevel = Literal["low", "medium", "high", "critical"]


class ChangedFile(BaseModel):
    path: str
    additions: int = 0
    deletions: int = 0


class RiskFlag(BaseModel):
    code: str
    message: str


class PolicyViolation(BaseModel):
    code: str
    message: str
    path: str | None = None


class PolicyResult(BaseModel):
    allowed: bool
    approval_required: bool
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    blocked: list[PolicyViolation] = Field(default_factory=list)


class VerificationCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class VerificationResult(BaseModel):
    passed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)
