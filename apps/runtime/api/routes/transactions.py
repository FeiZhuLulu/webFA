from __future__ import annotations

from fastapi import APIRouter, Request

from registry.transaction_registry import build_default_registry

router = APIRouter(tags=["transactions"])


@router.get("/transactions")
def list_transactions(request: Request) -> dict:
    registry = getattr(request.app.state, "transaction_registry", None) or build_default_registry()
    return {
        "transactions": [
            {
                "id": definition.id,
                "provider": definition.provider,
                "name": definition.name,
                "description": definition.description,
                "risk": definition.risk,
                "approval_level": definition.approval_level,
                "required_capabilities": definition.required_capabilities,
                "proof_types": definition.proof_types,
            }
            for definition in registry.list()
        ]
    }
