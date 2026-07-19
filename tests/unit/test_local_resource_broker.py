from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest

from browser.local_resource_broker import LocalResourceBroker, LocalResourceError, _process_is_alive


def test_resource_grant_is_opaque_and_scoped(tmp_path) -> None:
    broker = LocalResourceBroker(resource_dir=tmp_path / "resources")
    state = broker.register_bytes(
        display_name="resume.pdf",
        content=b"test-pdf",
        owner="user",
        purpose="job_application",
        allowed_origins=["https://jobs.example/apply"],
        bound_agent_ids=["agent-a"],
        bound_profile_ids=["profile-a"],
        max_uses=2,
    )

    assert state.status == "active"
    assert state.grant.resource_ref.startswith("resource_")
    assert state.grant.allowed_origins == ["https://jobs.example"]
    assert "path" not in state.model_dump()
    assert "path" not in state.grant.model_dump()

    authorization = broker.authorize(
        state.grant.resource_ref,
        agent_id="agent-a",
        profile_id="profile-a",
        origin="https://jobs.example/submit",
        purpose="job_application",
    )
    assert authorization.path.is_file()
    assert authorization.path.read_bytes() == b"test-pdf"


def test_resource_scope_rejects_agent_profile_origin_and_purpose_mismatch(tmp_path) -> None:
    broker = LocalResourceBroker(resource_dir=tmp_path / "resources")
    state = broker.register_bytes(
        display_name="notes.txt",
        content=b"notes",
        owner="user",
        purpose="support_ticket",
        allowed_origins=["https://support.example"],
        bound_agent_ids=["agent-a"],
        bound_profile_ids=["default"],
    )

    cases = [
        ({"agent_id": "agent-b", "profile_id": "default", "origin": "https://support.example", "purpose": "support_ticket"}, "resource_agent_mismatch"),
        ({"agent_id": "agent-a", "profile_id": "other", "origin": "https://support.example", "purpose": "support_ticket"}, "resource_profile_mismatch"),
        ({"agent_id": "agent-a", "profile_id": "default", "origin": "https://evil.example", "purpose": "support_ticket"}, "resource_origin_mismatch"),
        ({"agent_id": "agent-a", "profile_id": "default", "origin": "https://support.example", "purpose": "other"}, "resource_purpose_mismatch"),
    ]
    for kwargs, code in cases:
        with pytest.raises(LocalResourceError) as raised:
            broker.authorize(state.grant.resource_ref, **kwargs)
        assert raised.value.code == code


def test_resource_use_count_expiry_and_revoke(tmp_path) -> None:
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)
    clock_value = [now]
    broker = LocalResourceBroker(
        resource_dir=tmp_path / "resources",
        clock=lambda: clock_value[0],
    )
    state = broker.register_bytes(
        display_name="data.csv",
        content=b"a,b\n1,2\n",
        owner="agent",
        purpose="upload",
        allowed_origins=["file://"],
        expires_in_seconds=60,
        max_uses=1,
    )

    authorization = broker.authorize(
        state.grant.resource_ref,
        agent_id="agent-a",
        profile_id="default",
        origin="file://",
    )
    backing_path = authorization.path
    assert backing_path.is_file()

    consumed = broker.consume(state.grant.resource_ref)
    assert consumed.status == "consumed"
    assert backing_path.exists()
    with pytest.raises(LocalResourceError) as raised:
        broker.authorize(
            state.grant.resource_ref,
            agent_id="agent-a",
            profile_id="default",
            origin="file://",
        )
    assert raised.value.code == "resource_consumed"

    second = broker.register_bytes(
        display_name="other.txt",
        content=b"other",
        owner="user",
        purpose="upload",
        allowed_origins=["file://"],
        expires_in_seconds=60,
    )
    second_authorization = broker.authorize(
        second.grant.resource_ref,
        agent_id="agent-a",
        profile_id="default",
        origin="file://",
    )
    clock_value[0] = now + timedelta(seconds=61)
    assert broker.list()[0].status == "expired"
    assert not second_authorization.path.exists()

    third = broker.register_bytes(
        display_name="revoke.txt",
        content=b"revoke",
        owner="user",
        purpose="upload",
        allowed_origins=["file://"],
    )
    third_authorization = broker.authorize(
        third.grant.resource_ref,
        agent_id="agent-a",
        profile_id="default",
        origin="file://",
    )
    revoked = broker.revoke(third.grant.resource_ref)
    assert revoked.status == "revoked"
    assert not third_authorization.path.exists()

    broker.close()
    assert not backing_path.exists()


def test_resource_broker_purges_only_stale_orphaned_session_files_on_start(tmp_path) -> None:
    import os
    import time

    resource_dir = tmp_path / "resources"
    orphan_dir = resource_dir / "session_orphan"
    orphan_dir.mkdir(parents=True)
    orphan_file = orphan_dir / "secret.txt"
    orphan_file.write_text("orphaned", encoding="utf-8")
    stale_time = time.time() - (2 * 24 * 60 * 60)
    os.utime(orphan_file, (stale_time, stale_time))
    os.utime(orphan_dir, (stale_time, stale_time))

    broker = LocalResourceBroker(resource_dir=resource_dir)

    assert not orphan_dir.exists()
    assert not orphan_file.exists()
    broker.close()


def test_resource_broker_purges_recent_session_when_owner_process_is_dead(tmp_path) -> None:
    resource_dir = tmp_path / "resources"
    orphan_dir = resource_dir / "session_99999999_dead"
    orphan_dir.mkdir(parents=True)
    orphan_file = orphan_dir / "secret.txt"
    orphan_file.write_text("orphaned", encoding="utf-8")

    broker = LocalResourceBroker(resource_dir=resource_dir)

    assert not orphan_dir.exists()
    assert not orphan_file.exists()
    broker.close()


def test_second_resource_broker_does_not_delete_active_first_session(tmp_path) -> None:
    resource_dir = tmp_path / "resources"
    first = LocalResourceBroker(resource_dir=resource_dir)
    state = first.register_bytes(
        display_name="active.txt",
        content=b"active",
        owner="user",
        purpose="upload",
        allowed_origins=["https://example.com"],
    )
    authorization = first.authorize(
        state.grant.resource_ref,
        agent_id="agent-a",
        profile_id="default",
        origin="https://example.com",
    )

    second = LocalResourceBroker(resource_dir=resource_dir)

    assert authorization.path.is_file()
    assert authorization.path.read_bytes() == b"active"
    second.close()
    assert authorization.path.is_file()
    first.close()
    assert not authorization.path.exists()


def test_process_liveness_probe_distinguishes_live_and_exited_processes() -> None:
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        assert _process_is_alive(process.pid)
    finally:
        process.terminate()
        process.wait(timeout=10)

    assert not _process_is_alive(process.pid)


def test_resource_broker_rejects_invalid_base64_and_empty_content(tmp_path) -> None:
    broker = LocalResourceBroker(resource_dir=tmp_path / "resources")
    with pytest.raises(LocalResourceError) as invalid:
        broker.register_base64(
            display_name="bad.txt",
            content_base64="not base64!",
            owner="user",
            purpose="upload",
            allowed_origins=["https://example.com"],
        )
    assert invalid.value.code == "invalid_resource_content"

    with pytest.raises(LocalResourceError) as empty:
        broker.register_bytes(
            display_name="empty.txt",
            content=b"",
            owner="user",
            purpose="upload",
            allowed_origins=["https://example.com"],
        )
    assert empty.value.code == "empty_resource"
