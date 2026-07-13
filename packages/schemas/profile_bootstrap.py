from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
