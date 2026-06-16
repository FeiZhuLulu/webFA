from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

RiskLevel = Literal["low", "medium", "high", "critical"]


class TransactionDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    provider: str
    name: str
    description: str = ""
    risk: RiskLevel
    approval_level: str = "required"
    required_capabilities: list[str] = Field(default_factory=list)
    read_set: list[str] = Field(default_factory=list)
    write_set: list[str] = Field(default_factory=list)
    verification_strategy: list[str] = Field(default_factory=list)
    proof_types: list[str] = Field(default_factory=list)
    rollback_strategy: str = "manual"
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
