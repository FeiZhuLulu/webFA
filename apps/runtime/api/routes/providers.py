from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from storage.db import session_scope
from storage.models import ProviderConnection

router = APIRouter(tags=["providers"])

PROVIDER_NAMES = {
    "github": "GitHub",
    "huggingface": "Hugging Face",
}


@router.get("/providers")
def list_providers() -> dict:
    with session_scope() as session:
        rows = session.scalars(select(ProviderConnection).order_by(ProviderConnection.provider)).all()
        providers = [
            {
                "id": row.provider,
                "name": PROVIDER_NAMES.get(row.provider, row.provider),
                "status": row.status,
                "auth_mode": row.auth_mode,
                "last_verified_at": row.last_verified_at.isoformat() if row.last_verified_at else None,
            }
            for row in rows
        ]
    return {"providers": providers}
