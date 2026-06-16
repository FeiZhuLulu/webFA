"""REST API: Proof endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from proof.store import ProofService
from storage.db import session_scope

router = APIRouter()
_service = ProofService()


@router.get("/proofs/{proof_id}")
def get_proof(proof_id: str):
    with session_scope() as session:
        proof = _service.get_proof(session, proof_id)
        if proof is None:
            raise HTTPException(status_code=404, detail="Proof not found")
        return proof.model_dump(mode="json")
