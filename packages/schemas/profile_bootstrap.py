from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schemas.profile import BrowserProfileCreate, ProfileBootstrapSource
from schemas.safety import AccountOwner, TrustMode


CookieImportFormat = Literal["auto", "json", "netscape"]
CookieImportSourceFormat = Literal["json", "netscape"]


class StrictProfileBootstrapModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProfileBootstrapTarget(StrictProfileBootstrapModel):
    agent_alias: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    agent_description: str = Field(default="", max_length=500)
    owner: AccountOwner = "user_owned"
    trust_mode: TrustMode = "guarded"

    @field_validator("agent_alias")
    @classmethod
    def normalize_alias(cls, value: str) -> str:
        return BrowserProfileCreate(
            agent_alias=value,
            display_name="Bootstrap target",
        ).agent_alias

    def to_profile_create(
        self,
        *,
        bootstrap_source: ProfileBootstrapSource,
    ) -> BrowserProfileCreate:
        return BrowserProfileCreate(
            agent_alias=self.agent_alias,
            display_name=self.display_name,
            agent_description=self.agent_description,
            persistence="persistent",
            owner=self.owner,
            trust_mode=self.trust_mode,
            bound_agent_ids=[],
            allowed_origins=[],
            safety_policy_id=None,
            financial_policy_id=None,
            bootstrap_source=bootstrap_source,
        )


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
    target_profile: ProfileBootstrapTarget


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


class ProfileBundleExportPreview(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    source_profile_id: str = Field(min_length=1, max_length=200)
    source_profile_version: int = Field(ge=1)
    source_agent_alias: str = Field(min_length=1, max_length=64)
    source_display_name: str = Field(min_length=1, max_length=200)
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    excluded_count: int = Field(ge=0)
    suggested_filename: str = Field(min_length=1, max_length=240)
    expires_at: datetime


class ProfileBundleExportRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    expected_source_version: int = Field(ge=1)


class ProfileBundleExportCancelRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)


class ProfileBundleRestorePreview(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    bundle_format_version: int = Field(ge=1)
    source_agent_alias: str = Field(min_length=1, max_length=64)
    source_display_name: str = Field(min_length=1, max_length=200)
    source_bootstrap_source: str = Field(min_length=1, max_length=50)
    source_platform: str = Field(min_length=1, max_length=100)
    current_platform: str = Field(min_length=1, max_length=100)
    restoration_scope: Literal["browser_storage_only"] = "browser_storage_only"
    compatibility_warning: str = Field(min_length=1, max_length=1000)
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    created_at: datetime
    expires_at: datetime


class ProfileBundleRestoreCommitRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)
    target_profile: ProfileBootstrapTarget


class ProfileBundleRestoreCancelRequest(StrictProfileBootstrapModel):
    preview_token: str = Field(min_length=1, max_length=200)


class ProfileBundleRestoreResult(StrictProfileBootstrapModel):
    status: Literal["profile_restored"] = "profile_restored"
    target_profile_id: str = Field(min_length=1, max_length=200)
    target_agent_alias: str = Field(min_length=1, max_length=64)
    target_profile_version: int = Field(ge=1)
    file_count: int = Field(ge=0)
    total_bytes: int = Field(ge=0)
    occurred_at: datetime
