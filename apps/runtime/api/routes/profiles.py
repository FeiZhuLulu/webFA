from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.runtime.api.visualizer_control import (
    VISUALIZER_CONTROL_HEADER,
    require_visualizer_control,
)
from browser.profile_bootstrap import (
    MAX_COOKIE_IMPORT_BYTES,
    CookieImportApplyError,
    CookieImportBindingError,
    CookieImportBusyError,
    CookieImportLimitError,
    CookieImportParseError,
    CookieImportPreviewExpiredError,
    CookieImportPreviewNotFoundError,
    CookieImportVerificationError,
    ProfileBootstrapError,
    ProfileBootstrapService,
    ProfileCloneApplyError,
    ProfileCloneBindingError,
    ProfileCloneBusyError,
    ProfileClonePreviewExpiredError,
    ProfileClonePreviewNotFoundError,
    ProfileCloneSourceChangedError,
)
from browser.profile_repository import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileRepository,
    ProfileRepositoryError,
    ProfileStateError,
    ProfileVersionConflictError,
)
from browser.profile_storage import ProfileLockBusyError, ProfileStorageManager
from schemas.profile import BrowserProfileCreate, BrowserProfileUpdate
from schemas.profile_bootstrap import (
    CookieImportCancelRequest,
    CookieImportCommitRequest,
    CookieImportFormat,
    ProfileCloneCancelRequest,
    ProfileCloneCommitRequest,
)


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


def get_profile_storage_manager(request: Request) -> ProfileStorageManager:
    storage = getattr(request.app.state, "profile_storage_manager", None)
    if storage is None:
        storage = ProfileStorageManager()
        request.app.state.profile_storage_manager = storage
    return storage


def get_profile_bootstrap_service(request: Request) -> ProfileBootstrapService:
    service = getattr(request.app.state, "profile_bootstrap_service", None)
    if service is None:
        service = ProfileBootstrapService(
            repository=get_profile_repository(request),
            storage=get_profile_storage_manager(request),
        )
        request.app.state.profile_bootstrap_service = service
    return service


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
    repository = get_profile_repository(request)
    lease = None
    try:
        selected = repository.get_profile(profile_ref)
        lease = get_profile_storage_manager(request).acquire_mutation_lease(
            selected,
            mutation_id=f"profile_archive_{uuid4().hex}",
            operation="profile_archive",
        )
        profile = repository.archive_profile(
            profile_ref,
            expected_version=payload.expected_version,
        )
        return profile.model_dump(mode="json")
    except ProfileLockBusyError as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    finally:
        if lease is not None:
            lease.release()


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


@router.post("/profiles/{profile_ref}/session/close")
def close_profile_session(profile_ref: str, request: Request):
    try:
        profile = get_profile_repository(request).get_profile(profile_ref)
        runtime = getattr(request.app.state, "browser_runtime_supervisor", None)
        if runtime is None:
            runtime = getattr(request.app.state, "browser_runtime", None)
        close_for_profile = getattr(runtime, "close_profile_session", None) if runtime is not None else None
        if not callable(close_for_profile):
            return {
                "status": "already_inactive",
                "profile_id": profile.profile_id,
                "session_id": None,
            }
        session_id = close_for_profile(
            profile.profile_id,
            reason="profile_control_close",
        )
        return {
            "status": "session_closed" if session_id is not None else "already_inactive",
            "profile_id": profile.profile_id,
            "session_id": session_id,
        }
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/cookies/preview")
async def preview_cookie_import(
    profile_ref: str,
    request: Request,
    expected_version: int = Query(ge=1),
    input_format: CookieImportFormat = Query(default="auto", alias="format"),
):
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            declared_length = int(content_length)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail={"code": "content_length_invalid", "message": "invalid Content-Length header"},
            )
        if declared_length > MAX_COOKIE_IMPORT_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": CookieImportLimitError.code,
                    "message": "cookie input exceeds the 5 MiB limit",
                },
            )
    content = await request.body()
    try:
        preview = get_profile_bootstrap_service(request).preview_cookie_import(
            profile_ref,
            expected_version=expected_version,
            content=content,
            input_format=input_format,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return preview.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/cookies/cancel")
def cancel_cookie_import(
    profile_ref: str,
    payload: CookieImportCancelRequest,
    request: Request,
):
    try:
        result = get_profile_bootstrap_service(request).cancel_cookie_import(
            profile_ref,
            preview_token=payload.preview_token,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return result.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/cookies/import")
def commit_cookie_import(
    profile_ref: str,
    payload: CookieImportCommitRequest,
    request: Request,
):
    try:
        result = get_profile_bootstrap_service(request).commit_cookie_import(
            profile_ref,
            preview_token=payload.preview_token,
            expected_version=payload.expected_version,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return result.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/clone/preview")
def preview_profile_clone(
    profile_ref: str,
    request: Request,
    expected_version: int = Query(ge=1),
):
    try:
        preview = get_profile_bootstrap_service(request).preview_profile_clone(
            profile_ref,
            expected_source_version=expected_version,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return preview.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/clone/cancel")
def cancel_profile_clone(
    profile_ref: str,
    payload: ProfileCloneCancelRequest,
    request: Request,
):
    try:
        result = get_profile_bootstrap_service(request).cancel_profile_clone(
            profile_ref,
            preview_token=payload.preview_token,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return result.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


@router.post("/profiles/{profile_ref}/bootstrap/clone")
def commit_profile_clone(
    profile_ref: str,
    payload: ProfileCloneCommitRequest,
    request: Request,
):
    try:
        result = get_profile_bootstrap_service(request).commit_profile_clone(
            profile_ref,
            preview_token=payload.preview_token,
            expected_source_version=payload.expected_source_version,
            target_profile=payload.target_profile,
            control_token=request.headers.get(VISUALIZER_CONTROL_HEADER, ""),
        )
        return result.model_dump(mode="json")
    except ProfileRepositoryError as exc:
        raise _profile_http_error(exc) from exc
    except ProfileBootstrapError as exc:
        raise _bootstrap_http_error(exc) from exc


def _bootstrap_http_error(exc: ProfileBootstrapError) -> HTTPException:
    if isinstance(exc, CookieImportLimitError):
        status_code = 413
    elif isinstance(exc, CookieImportParseError):
        status_code = 400
    elif isinstance(exc, CookieImportPreviewNotFoundError):
        status_code = 404
    elif isinstance(exc, CookieImportPreviewExpiredError):
        status_code = 410
    elif isinstance(exc, (CookieImportBindingError, ProfileCloneBindingError)):
        status_code = 403
    elif isinstance(exc, (CookieImportBusyError, ProfileCloneBusyError, ProfileCloneSourceChangedError)):
        status_code = 409
    elif isinstance(exc, ProfileClonePreviewNotFoundError):
        status_code = 404
    elif isinstance(exc, ProfileClonePreviewExpiredError):
        status_code = 410
    elif isinstance(
        exc,
        (CookieImportApplyError, CookieImportVerificationError, ProfileCloneApplyError),
    ):
        status_code = 500
    else:
        status_code = 500
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": str(exc)},
    )


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
