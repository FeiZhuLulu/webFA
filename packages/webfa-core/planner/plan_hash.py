"""Canonical JSON hashing for plan integrity."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(payload: dict[str, Any]) -> str:
    """Produce deterministic JSON string: sorted keys, no whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_plan_hash(
    transaction_id: str,
    input_json: dict[str, Any],
    target_json: dict[str, Any],
    steps_json: list[dict[str, Any]],
    risk: str,
) -> str:
    """Compute sha256 hash of canonical plan payload."""
    payload = {
        "transaction_id": transaction_id,
        "input_json": input_json,
        "target_json": target_json,
        "steps_json": steps_json,
        "risk": risk,
    }
    return "sha256:" + hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def compute_diff_hash(diff_text: str) -> str:
    """Compute sha256 hash of diff text."""
    return "sha256:" + hashlib.sha256(diff_text.encode("utf-8")).hexdigest()


def compute_proof_hash(proof_payload: dict[str, Any]) -> str:
    """Compute sha256 hash of canonical proof payload."""
    return "sha256:" + hashlib.sha256(canonical_json(proof_payload).encode("utf-8")).hexdigest()
