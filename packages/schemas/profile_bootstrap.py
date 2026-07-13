from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.profile import BrowserProfileCreate


CookieImportFormat = Literal["auto", "json", "netscape"]
CookieImportSourceFormat = Literal["json", "netscape"]


class StrictProfileBootstrapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CookieImportWarning(StrictProfileBootstrapModel):
    code: str = Field(min_length=1, max_length=100)
    count: int = Field(ge=1)


class CookieImportPreview(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    profile_id: str = Field(min_length=1, max_length=200)
    profile_version: int = Field(ge=1)
    source_format: CookieImportSourceFormat
    total_entries: int = Field(ge=0)
    accepted_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    domains: list[str] = Field(default_factory=list, max_length=200)
    secure_count: int = Field(ge=0)
    http_only_count: int = Field(ge=0)
    session_count: int = Field(ge=0)
    persistent_count: int = Field(ge=0)
    partitioned_count: int = Field(ge=0)
    warnings: list[CookieImportWarning] = Field(default_factory=list, max_length=100)
    expires_at: datetime


class CookieImportCommitRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=1)


class CookieImportCancelRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)


class CookieImportCancelResult(StrictProfileBootstrapModel):
    status: Literal["preview_cancelled"] = "preview_cancelled"
    profile_id: str = Field(min_length=1, max_length=200)


class CookieImportResult(StrictProfileBootstrapModel):
    status: Literal["cookies_imported"] = "cookies_imported"
    profile_id: str = Field(min_length=1, max_length=200)
    profile_version: int = Field(ge=1)
    source_format: CookieImportSourceFormat
    imported_count: int = Field(ge=0)
    verified_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    occurred_at: datetime


class ProfileClonePreview(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    source_profile_id: str = Field(min_length=1, max_length=200)
    source_profile_version: int = Field(ge=1)
    source_agent_alias: str = Field(min_length=1, max_length=64)
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    expires_at: datetime


class ProfileCloneCommitRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    expected_source_version: int = Field(ge=1)
    target_profile: BrowserProfileCreate

    @field_validator("target_profile")
    @classmethod
    def require_persistent_target(cls, value: BrowserProfileCreate) -> BrowserProfileCreate:
        if value.persistence != "persistent":
            raise ValueError("Profile clone target must be persistent")
        return value.model_copy(update={"bootstrap_source": "cloned"}, deep=True)


class ProfileCloneCancelRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)


class ProfileCloneCancelResult(StrictProfileBootstrapModel):
    status: Literal["clone_preview_cancelled"] = "clone_preview_cancelled"
    source_profile_id: str = Field(min_length=1, max_length=200)


class ProfileCloneResult(StrictProfileBootstrapModel):
    status: Literal["profile_cloned"] = "profile_cloned"
    source_profile_id: str = Field(min_length=1, max_length=200)
    target_profile_id: str = Field(min_length=1, max_length=200)
    target_agent_alias: str = Field(min_length=1, max_length=64)
    target_profile_version: int = Field(ge=1)
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    occurred_at: datetime
