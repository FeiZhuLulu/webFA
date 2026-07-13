from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas.safety import AccountOwner, TrustMode, UnknownEffectPolicy


ProfilePersistence = Literal["persistent", "ephemeral"]
ProfileBootstrapSource = Literal["blank", "human_login", "imported", "cloned", "restored"]
ProfileCatalogState = Literal["ready", "archived", "deleting", "error"]
ProfileAvailability = Literal["available", "busy", "authorization_required", "unavailable"]
SessionLifecycle = Literal[
    "created",
    "starting",
    "running",
    "stopping",
    "closed",
    "crashed",
    "interrupted",
]
SessionControlState = Literal["idle", "agent_controlled", "human_controlled"]
SessionHealth = Literal["healthy", "degraded", "failed"]

_ALIAS_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$")


class StrictProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrowserProfileCreate(StrictProfileModel):
    agent_alias: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    agent_description: str = Field(default="", max_length=500)
    persistence: ProfilePersistence = "persistent"
    owner: AccountOwner = "shared"
    trust_mode: TrustMode = "trusted_agent"
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_origins: list[str] = Field(default_factory=list, max_length=100)
    unknown_external_effect_policy: UnknownEffectPolicy | None = None
    safety_policy_id: str | None = Field(default=None, max_length=200)
    financial_policy_id: str | None = Field(default=None, max_length=200)
    bootstrap_source: ProfileBootstrapSource = "blank"

    @field_validator("agent_alias")
    @classmethod
    def normalize_alias(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not _ALIAS_RE.fullmatch(normalized):
            raise ValueError(
                "agent_alias must use 1-64 lowercase letters, digits, hyphens, or underscores"
            )
        return normalized

    @field_validator("bound_agent_ids", "allowed_origins")
    @classmethod
    def normalize_unique_values(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result

    @model_validator(mode="after")
    def apply_unknown_effect_default(self) -> "BrowserProfileCreate":
        if self.unknown_external_effect_policy is None:
            self.unknown_external_effect_policy = (
                "allow_with_audit" if self.owner == "agent_owned" else "require_step_up"
            )
        return self


class BrowserProfileUpdate(StrictProfileModel):
    expected_version: int = Field(ge=1)
    agent_alias: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    agent_description: str | None = Field(default=None, max_length=500)
    owner: AccountOwner | None = None
    trust_mode: TrustMode | None = None
    bound_agent_ids: list[str] | None = Field(default=None, max_length=100)
    allowed_origins: list[str] | None = Field(default=None, max_length=100)
    unknown_external_effect_policy: UnknownEffectPolicy | None = None
    safety_policy_id: str | None = Field(default=None, max_length=200)
    financial_policy_id: str | None = Field(default=None, max_length=200)

    @field_validator("agent_alias")
    @classmethod
    def normalize_alias(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not _ALIAS_RE.fullmatch(normalized):
            raise ValueError(
                "agent_alias must use 1-64 lowercase letters, digits, hyphens, or underscores"
            )
        return normalized

    @field_validator("bound_agent_ids", "allowed_origins")
    @classmethod
    def normalize_unique_values(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            if value and value not in seen:
                seen.add(value)
                result.append(value)
        return result


class BrowserProfile(StrictProfileModel):
    profile_id: str = Field(min_length=1, max_length=200)
    agent_alias: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    agent_description: str = Field(default="", max_length=500)
    persistence: ProfilePersistence
    owner: AccountOwner
    trust_mode: TrustMode
    bound_agent_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_origins: list[str] = Field(default_factory=list, max_length=100)
    unknown_external_effect_policy: UnknownEffectPolicy
    safety_policy_id: str | None = Field(default=None, max_length=200)
    financial_policy_id: str | None = Field(default=None, max_length=200)
    storage_ref: str = Field(min_length=1, max_length=300)
    bootstrap_source: ProfileBootstrapSource
    catalog_state: ProfileCatalogState
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None

    def agent_view(self, *, availability: ProfileAvailability = "available") -> "BrowserProfileAgentView":
        return BrowserProfileAgentView(
            profile_id=self.profile_id,
            agent_alias=self.agent_alias,
            agent_description=self.agent_description,
            owner=self.owner,
            trust_mode=self.trust_mode,
            unknown_external_effect_policy=self.unknown_external_effect_policy,
            availability=availability,
            catalog_state=self.catalog_state,
            version=self.version,
        )


class BrowserProfileAgentView(StrictProfileModel):
    profile_id: str = Field(min_length=1, max_length=200)
    agent_alias: str = Field(min_length=1, max_length=64)
    agent_description: str = Field(default="", max_length=500)
    owner: AccountOwner
    trust_mode: TrustMode
    unknown_external_effect_policy: UnknownEffectPolicy
    availability: ProfileAvailability
    catalog_state: ProfileCatalogState
    version: int = Field(ge=1)


class BrowserSessionMetadata(StrictProfileModel):
    session_id: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    runtime_generation: str = Field(min_length=1, max_length=200)
    lifecycle: SessionLifecycle
    control_state: SessionControlState = "idle"
    health: SessionHealth = "healthy"
    active_tab_id: str | None = Field(default=None, max_length=200)
    created_by_agent_id: str | None = Field(default=None, max_length=200)
    created_by_connection_id: str | None = Field(default=None, max_length=200)
    created_at: datetime
    started_at: datetime | None = None
    last_activity_at: datetime | None = None
    stopped_at: datetime | None = None
    close_reason: str | None = Field(default=None, max_length=500)
