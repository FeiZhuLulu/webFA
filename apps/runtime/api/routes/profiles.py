from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.runtime.api.visualizer_control import require_visualizer_control
from browser.profile_repository import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileRepository,
    ProfileRepositoryError,
    ProfileStateError,
    ProfileVersionConflictError,
)
from schemas.profile import BrowserProfileCreate, BrowserProfileUpdate


router = APIRouter(
    tags=["profiles"],
    dependencies=[Depends(require_visualizer_control)],
)


class ProfileVersionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)


def get_profile_repository(request: Request) -> ProfileRepository:
    repository = getattr(request.app.state, "profile_repository", None)
    if repository is None:
        repository = ProfileRepository()
        repository.ensure_default_profile()
        request.app.state.profile_repository = repository
    return repository


@router.get("/profiles")
def list_profiles(request: Request, include_archived: bool = True):
    repository = get_profile_repository(request)
    return {
        "profiles": [
            profile.model_dump(mode="json")
            for profile in repository.list_profiles(include_archived=include_archived)
        ]
    }


@router.post("/profiles", status_code=201)
def create_profile(payload: BrowserProfileCreate, request: Request):
    try:
        profile = get_profile_repository(request).create_profile(payload)
        return profile.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


@router.get("/profiles/{profile_ref}")
def get_profile(profile_ref: str, request: Request):
    try:
        profile = get_profile_repository(request).get_profile(profile_ref)
        return profile.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


@router.patch("/profiles/{profile_ref}")
def update_profile(profile_ref: str, payload: BrowserProfileUpdate, request: Request):
    try:
        profile = get_profile_repository(request).update_profile(profile_ref, payload)
        return profile.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


@router.delete("/profiles/{profile_ref}")
def archive_profile(profile_ref: str, payload: ProfileVersionRequest, request: Request):
    try:
        profile = get_profile_repository(request).archive_profile(
            profile_ref,
            expected_version=payload.expected_version,
        )
        return profile.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/restore")
def restore_profile(profile_ref: str, payload: ProfileVersionRequest, request: Request):
    try:
        profile = get_profile_repository(request).restore_profile(
            profile_ref,
            expected_version=payload.expected_version,
        )
        return profile.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


def _profile_http_error(exc: ProfileRepositoryError) -> HTTPException:
    if isinstance(exc, ProfileNotFoundError):
        status_code = 404
    elif isinstance(
        exc,
        (ProfileConflictError, ProfileVersionConflictError, ProfileStateError),
    ):
        status_code = 409
    else:
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )
