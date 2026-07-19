from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from apps.runtime.identity import (
    PRODUCT_ID,
    RELEASE_VERSION,
    RUNTIME_INSTANCE_ID,
    RUNTIME_INSTANCE_ID_ENV,
    RUNTIME_PROTOCOL_VERSION,
    _resolve_runtime_instance_id,
    runtime_identity,
)
from apps.runtime.version import __version__


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_identity_uses_the_canonical_release_version() -> None:
    identity = runtime_identity()

    assert identity == {
        "product": PRODUCT_ID,
        "release_version": __version__,
        "protocol_version": RUNTIME_PROTOCOL_VERSION,
        "instance_id": RUNTIME_INSTANCE_ID,
    }
    assert RELEASE_VERSION == __version__
    assert PRODUCT_ID == "webfa"
    assert RUNTIME_PROTOCOL_VERSION == 1


def test_runtime_instance_id_accepts_a_configured_ownership_nonce() -> None:
    configured = "desktop_0123456789abcdef"

    assert _resolve_runtime_instance_id(configured) == configured


@pytest.mark.parametrize(
    "configured",
    [
        "",
        "short",
        "_starts_with_punctuation",
        "contains a space 1234",
        "contains/slash/1234",
        "非ascii-runtime-instance-id",
        "a" * 129,
    ],
)
def test_runtime_instance_id_rejects_ambiguous_or_unbounded_values(configured: str) -> None:
    with pytest.raises(ValueError, match="16-128 characters"):
        _resolve_runtime_instance_id(configured)


def test_default_runtime_instance_id_is_process_stable_and_non_secret() -> None:
    first = runtime_identity()
    second = runtime_identity()

    assert first["instance_id"] == second["instance_id"] == RUNTIME_INSTANCE_ID
    assert re.fullmatch(r"runtime_[0-9a-f]{32}", RUNTIME_INSTANCE_ID)
    assert set(first) == {"product", "release_version", "protocol_version", "instance_id"}


def test_unconfigured_runtime_processes_receive_distinct_instance_ids() -> None:
    env = os.environ.copy()
    env.pop(RUNTIME_INSTANCE_ID_ENV, None)
    command = [
        sys.executable,
        "-c",
        "from apps.runtime.identity import RUNTIME_INSTANCE_ID; print(RUNTIME_INSTANCE_ID)",
    ]

    first = subprocess.check_output(command, cwd=ROOT, env=env, text=True).strip()
    second = subprocess.check_output(command, cwd=ROOT, env=env, text=True).strip()

    assert re.fullmatch(r"runtime_[0-9a-f]{32}", first)
    assert re.fullmatch(r"runtime_[0-9a-f]{32}", second)
    assert first != second


def test_runtime_process_prefers_valid_configured_instance_id() -> None:
    configured = "desktop_0123456789abcdef"
    env = os.environ.copy()
    env[RUNTIME_INSTANCE_ID_ENV] = configured
    command = [
        sys.executable,
        "-c",
        "from apps.runtime.identity import RUNTIME_INSTANCE_ID; print(RUNTIME_INSTANCE_ID)",
    ]

    observed = subprocess.check_output(command, cwd=ROOT, env=env, text=True).strip()

    assert observed == configured
