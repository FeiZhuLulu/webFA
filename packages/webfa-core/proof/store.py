"""Proof Service: generates, stores, and retrieves proofs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from planner.plan_hash import compute_proof_hash
from schemas.common import VerificationResult
from schemas.proof import ProofHashes, ProofRead, ProofResource
from storage.file_store import ensure_webfa_data_dir
from storage.models import AuditEvent, Proof, new_id


class ProofService:
    def create_proof(
        self,
        session: Session,
        execution_id: str,
        provider: str,
        transaction_id: str,
        plan_id: str,
        resource_type: str,
        resource_id: str,
        resource_url: str | None,
        plan_hash: str,
        diff_hash: str | None,
        verification: VerificationResult,
        workspace_id: str | None = None,
    ) -> ProofRead:
        """Generate proof, write to DB and file, return ProofRead."""

        # Build proof bundle
        verification_dict = verification.model_dump()
        proof_payload: dict[str, Any] = {
            "proof_version": "0.1",
            "provider": provider,
            "transaction_id": transaction_id,
            "plan_id": plan_id,
            "execution_id": execution_id,
            "resource": {
                "type": resource_type,
                "id": resource_id,
                "url": resource_url,
            },
            "hashes": {
                "plan_hash": plan_hash,
                "diff_hash": diff_hash,
            },
            "verification": verification_dict,
        }

        # Compute proof_hash
        proof_hash = compute_proof_hash(proof_payload)
        proof_payload["hashes"]["proof_hash"] = proof_hash

        # Write to DB
        proof = Proof(
            id=new_id("proof"),
            execution_id=execution_id,
            provider=provider,
            proof_type="state",
            resource_type=resource_type,
            resource_id=resource_id,
            url=resource_url,
            hash=proof_hash,
            proof_json=proof_payload,
        )
        session.add(proof)

        # Audit
        session.add(AuditEvent(
            id=new_id("audit"),
            workspace_id=workspace_id,
            plan_id=plan_id,
            execution_id=execution_id,
            event_type="proof.created",
            event_payload_json={"proof_id": proof.id, "proof_hash": proof_hash},
        ))

        session.flush()

        # Write to file
        self._write_proof_file(proof.id, proof_payload)

        return ProofRead(
            id=proof.id,
            execution_id=execution_id,
            provider=provider,
            proof_type="state",
            resource_type=resource_type,
            resource_id=resource_id,
            url=resource_url,
            hash=proof_hash,
            proof=proof_payload,
            created_at=proof.created_at.isoformat() if proof.created_at else None,
        )

    def get_proof(self, session: Session, proof_id: str) -> ProofRead | None:
        proof = session.get(Proof, proof_id)
        if proof is None:
            return None
        return ProofRead(
            id=proof.id,
            execution_id=proof.execution_id or "",
            provider=proof.provider,
            proof_type=proof.proof_type,
            resource_type=proof.resource_type,
            resource_id=proof.resource_id,
            url=proof.url,
            hash=proof.hash,
            proof=proof.proof_json,
            created_at=proof.created_at.isoformat() if proof.created_at else None,
        )

    def _write_proof_file(self, proof_id: str, payload: dict[str, Any]) -> None:
        """Write proof JSON to proofs/ directory."""
        paths = ensure_webfa_data_dir()
        proofs_dir = paths["proofs"]
        proof_file = proofs_dir / f"{proof_id}.json"
        proof_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
