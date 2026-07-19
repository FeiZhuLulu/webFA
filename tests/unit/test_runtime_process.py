from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from apps.runtime import cli, process


RUNTIME_URL = "http://127.0.0.1:8787"
INSTANCE_ID = "runtime_0123456789abcdef0123456789abcdef"


def _health(instance_id: str = INSTANCE_ID) -> dict[str, object]:
    return {
        "product": "webfa",
        "release_version": "0.2.0",
        "protocol_version": 1,
        "instance_id": instance_id,
        "status": "ok",
    }


@pytest.fixture(autouse=True)
def _isolated_webfa_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))


def test_parse_runtime_url_accepts_http_url():
    assert process.parse_runtime_url(RUNTIME_URL) == ("127.0.0.1", 8787)


def test_normalize_runtime_url_canonicalizes_case_ipv6_and_default_port():
    assert process.normalize_runtime_url("HTTP://LOCALHOST/") == "http://127.0.0.1:80"
    assert process.normalize_runtime_url("http://[0:0:0:0:0:0:0:1]:8787/") == "http://[::1]:8787"


def test_parse_runtime_url_rejects_non_origin_or_non_http_urls():
    for value in (
        "stdio://webfa",
        "http://user:pass@127.0.0.1:8787",
        "http://127.0.0.1:8787/api",
        "http://127.0.0.1:8787?x=1",
    ):
        with pytest.raises(ValueError, match="runtime URL"):
            process.parse_runtime_url(value)


def test_is_local_runtime_url_accepts_loopback_hosts():
    assert process.is_local_runtime_url(RUNTIME_URL) is True
    assert process.is_local_runtime_url("http://localhost:8787") is True
    assert process.is_local_runtime_url("http://[::1]:8787") is True


def test_is_local_runtime_url_rejects_non_loopback_hosts():
    assert process.is_local_runtime_url("http://10.0.0.5:8787") is False
    assert process.is_local_runtime_url("https://example.com") is False


def test_runtime_health_disables_env_proxy_and_validates_identity(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json() -> dict[str, object]:
            return _health()

    def fake_get(url: str, timeout: float, **kwargs):
        captured["url"] = url
        captured["timeout"] = timeout
        captured["trust_env"] = kwargs.get("trust_env")
        return FakeResponse()

    monkeypatch.setattr(process.httpx, "get", fake_get)

    health = process.runtime_health(RUNTIME_URL, expected_instance_id=INSTANCE_ID)

    assert health == _health()
    assert captured == {
        "url": f"{RUNTIME_URL}/health",
        "timeout": 2.0,
        "trust_env": False,
    }


@pytest.mark.parametrize(
    "body",
    [
        {"status": "ok"},
        {"product": "not-webfa", "release_version": "0.2.0", "protocol_version": 1, "instance_id": INSTANCE_ID},
        {"product": "webfa", "release_version": "9.9.9", "protocol_version": 1, "instance_id": INSTANCE_ID},
        {"product": "webfa", "release_version": "0.2.0", "protocol_version": 2, "instance_id": INSTANCE_ID},
        {"product": "webfa", "release_version": "0.2.0", "protocol_version": 1, "instance_id": "short"},
    ],
)
def test_runtime_health_rejects_foreign_or_invalid_occupants(monkeypatch, body):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return body

    monkeypatch.setattr(process.httpx, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(process.RuntimeIdentityError, match="handshake"):
        process.runtime_health(RUNTIME_URL)


def test_runtime_health_rejects_wrong_expected_instance(monkeypatch):
    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return _health()

    monkeypatch.setattr(process.httpx, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(process.RuntimeIdentityError, match="different WebFA Runtime"):
        process.runtime_health(
            RUNTIME_URL,
            expected_instance_id="runtime_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        )


def test_runtime_health_rejects_http_responder_without_webfa_health(monkeypatch):
    class FakeResponse:
        status_code = 404

    monkeypatch.setattr(process.httpx, "get", lambda *args, **kwargs: FakeResponse())

    with pytest.raises(process.RuntimeIdentityError, match="HTTP 404"):
        process.runtime_health(RUNTIME_URL)


def test_ensure_runtime_foreign_occupant_fails_before_spawn(monkeypatch):
    monkeypatch.setattr(
        process,
        "runtime_health",
        lambda runtime_url: (_ for _ in ()).throw(process.RuntimeIdentityError("foreign occupant")),
    )
    monkeypatch.setattr(
        process.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("foreign occupant must never spawn"),
    )

    with pytest.raises(process.RuntimeIdentityError, match="foreign occupant"):
        process.ensure_runtime(RUNTIME_URL)


def test_ensure_runtime_reuses_external_without_taking_ownership(monkeypatch):
    stopped: list[int] = []
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: _health())
    monkeypatch.setattr(
        process,
        "terminate_process_tree",
        lambda **kwargs: stopped.append(kwargs["pid"]),
    )

    result = process.ensure_runtime(RUNTIME_URL, auto_start=False)
    result.close()

    assert result.reused_existing is True
    assert result.process is None
    assert result.managed_auto_start is False
    assert stopped == []


def test_ensure_runtime_without_auto_start_fails_when_unreachable(monkeypatch):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: None)

    with pytest.raises(RuntimeError, match="Runtime unreachable"):
        process.ensure_runtime(RUNTIME_URL, auto_start=False)


@pytest.mark.parametrize(
    "runtime_url",
    ["http://10.0.0.5:8787", "https://127.0.0.1:8787"],
)
def test_auto_start_rejects_remote_or_non_http_loopback(monkeypatch, runtime_url):
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: None)
    monkeypatch.setattr(
        process.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("foreign/remote endpoint must never spawn"),
    )

    with pytest.raises(RuntimeError, match="restricted to loopback HTTP"):
        process.ensure_runtime(runtime_url, auto_start=True)


class _FakeProcess:
    def __init__(self, pid: int = 4321) -> None:
        self.pid = pid
        self.wait_calls: list[float] = []

    def wait(self, timeout: float) -> int:
        self.wait_calls.append(timeout)
        return 0


def _install_spawn_fakes(monkeypatch, captured: dict[str, object], *, frozen: bool = False) -> _FakeProcess:
    child = _FakeProcess()

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return child

    monkeypatch.setattr(process, "runtime_health", lambda runtime_url, **kwargs: None)

    def fake_wait(runtime_url, timeout_seconds=20.0, *, expected_instance_id=None):
        captured["waited_instance_id"] = expected_instance_id
        return _health(expected_instance_id)

    monkeypatch.setattr(process, "wait_for_runtime", fake_wait)
    monkeypatch.setattr(process.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process, "_process_identity", lambda pid: f"identity-{pid}")
    monkeypatch.setattr(process.sys, "frozen", frozen, raising=False)
    return child


def test_ensure_runtime_propagates_address_and_verified_instance_to_child(monkeypatch):
    captured: dict[str, object] = {}
    child = _install_spawn_fakes(monkeypatch, captured)

    result = process.ensure_runtime("http://127.0.0.2:9123")

    assert result.process is child
    assert result.managed_auto_start is True
    assert captured["env"]["WEBFA_API_HOST"] == "127.0.0.2"
    assert captured["env"]["WEBFA_API_PORT"] == "9123"
    assert captured["env"]["WEBFA_RUNTIME_INSTANCE_ID"] == result.instance_id
    assert captured["waited_instance_id"] == result.instance_id
    if os.name == "nt":
        assert "creationflags" in captured
    else:
        assert captured["start_new_session"] is True


def test_ensure_runtime_uses_multicall_sidecar_when_frozen(monkeypatch):
    captured: dict[str, object] = {}
    _install_spawn_fakes(monkeypatch, captured, frozen=True)
    monkeypatch.setattr(process.sys, "executable", "C:/WebFA/webfa.exe")

    process.ensure_runtime("http://127.0.0.2:9123")

    assert captured["command"] == [
        "C:/WebFA/webfa.exe",
        "runtime",
        "--host",
        "127.0.0.2",
        "--port",
        "9123",
    ]


def test_check_and_spawn_lock_allows_only_one_concurrent_spawn(monkeypatch):
    state: dict[str, object] = {
        "running": False,
        "instance_id": None,
        "runtime_alive": True,
        "spawn_count": 0,
    }
    state_lock = threading.Lock()
    start = threading.Barrier(2)
    stopped: list[int] = []

    def fake_health(runtime_url, timeout=2.0, *, expected_instance_id=None):
        with state_lock:
            if not state["running"]:
                return None
            instance_id = str(state["instance_id"])
        if expected_instance_id is not None and expected_instance_id != instance_id:
            raise process.RuntimeIdentityError("different instance")
        return _health(instance_id)

    def fake_popen(command, **kwargs):
        with state_lock:
            state["spawn_count"] = int(state["spawn_count"]) + 1
            state["instance_id"] = kwargs["env"]["WEBFA_RUNTIME_INSTANCE_ID"]
        time.sleep(0.05)
        return _FakeProcess()

    def fake_wait(runtime_url, timeout_seconds=20.0, *, expected_instance_id=None):
        with state_lock:
            state["running"] = True
        return _health(str(expected_instance_id))

    def fake_alive(pid: int) -> bool:
        return bool(state["runtime_alive"]) if pid == 4321 else pid == os.getpid()

    def fake_stop(**kwargs):
        stopped.append(kwargs["pid"])
        state["runtime_alive"] = False
        state["running"] = False

    monkeypatch.setattr(process, "runtime_health", fake_health)
    monkeypatch.setattr(process, "wait_for_runtime", fake_wait)
    monkeypatch.setattr(process.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(process, "_process_is_alive", fake_alive)
    monkeypatch.setattr(process, "_process_identity", lambda pid: f"identity-{pid}")
    monkeypatch.setattr(process, "terminate_process_tree", fake_stop)

    handles: list[process.RuntimeProcess] = []
    errors: list[BaseException] = []

    def connect() -> None:
        try:
            start.wait(timeout=2)
            handles.append(process.ensure_runtime(RUNTIME_URL))
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=connect), threading.Thread(target=connect)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert len(handles) == 2
    assert state["spawn_count"] == 1
    assert all(handle.managed_auto_start for handle in handles)
    handles[0].close()
    assert stopped == []
    handles[1].close()
    assert stopped == [4321]


def test_endpoint_lock_serializes_across_processes(tmp_path):
    lock_path = tmp_path / "cross-process.lock"
    code = (
        "import sys\n"
        "from pathlib import Path\n"
        "from apps.runtime.process import _endpoint_lock\n"
        "with _endpoint_lock(Path(sys.argv[1])):\n"
        "    print('LOCKED', flush=True)\n"
        "    sys.stdin.readline()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(lock_path)],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "LOCKED"
        with pytest.raises(RuntimeError, match="ownership lock"):
            with process._endpoint_lock(lock_path, timeout_seconds=0.15):
                pass
    finally:
        if child.stdin is not None:
            child.stdin.write("release\n")
            child.stdin.flush()
        child.wait(timeout=5)
    assert child.returncode == 0


def test_last_client_adopts_cleanup_after_original_owner_exited(monkeypatch):
    metadata_path, _lock_path = process._ownership_paths(RUNTIME_URL)
    stale_owner_pid = 1111
    runtime_pid = 4321
    metadata = {
        "schema_version": 1,
        "kind": "webfa-mcp-auto-start",
        "runtime_url": RUNTIME_URL,
        "instance_id": INSTANCE_ID,
        "pid": runtime_pid,
        "process_identity": f"identity-{runtime_pid}",
        "process_group_id": runtime_pid,
        "created_at": "2026-07-16T00:00:00+00:00",
        "leases": [
            {
                "lease_id": "dead-owner",
                "client_pid": stale_owner_pid,
                "client_process_identity": f"identity-{stale_owner_pid}",
                "created_at": "2026-07-16T00:00:00+00:00",
            }
        ],
    }
    process._write_metadata(metadata_path, metadata)
    stopped: list[int] = []
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url, **kwargs: _health())
    monkeypatch.setattr(
        process,
        "_process_is_alive",
        lambda pid: pid in {runtime_pid, os.getpid()},
    )
    monkeypatch.setattr(process, "_process_identity", lambda pid: f"identity-{pid}")
    monkeypatch.setattr(
        process,
        "terminate_process_tree",
        lambda **kwargs: stopped.append(kwargs["pid"]),
    )

    adopter = process.ensure_runtime(RUNTIME_URL)
    current = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert adopter.managed_auto_start is True
    assert len(current["leases"]) == 1
    assert current["leases"][0]["client_pid"] == os.getpid()
    adopter.close()
    assert stopped == [runtime_pid]
    assert not metadata_path.exists()


def test_mismatched_metadata_never_stops_external_runtime(monkeypatch):
    metadata_path, _lock_path = process._ownership_paths(RUNTIME_URL)
    process._write_metadata(
        metadata_path,
        {
            "schema_version": 1,
            "kind": "webfa-mcp-auto-start",
            "runtime_url": RUNTIME_URL,
            "instance_id": "runtime_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "pid": 4321,
            "process_identity": "identity-4321",
            "leases": [],
        },
    )
    stopped: list[int] = []
    monkeypatch.setattr(process, "runtime_health", lambda runtime_url: _health())
    monkeypatch.setattr(process, "_process_is_alive", lambda pid: True)
    monkeypatch.setattr(process, "_process_identity", lambda pid: f"identity-{pid}")
    monkeypatch.setattr(
        process,
        "terminate_process_tree",
        lambda **kwargs: stopped.append(kwargs["pid"]),
    )

    external = process.ensure_runtime(RUNTIME_URL)
    external.close()

    assert external.managed_auto_start is False
    assert stopped == []


def test_windows_tree_termination_uses_taskkill_tree_force(monkeypatch):
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(
        process.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)),
    )
    monkeypatch.setattr(process, "_wait_for_process_exit", lambda *args, **kwargs: True)

    process.terminate_process_tree(pid=4321, timeout_seconds=3)

    assert calls[0][0] == ["taskkill", "/PID", "4321", "/T", "/F"]
    assert calls[0][1]["timeout"] == 3


def test_tree_termination_fails_closed_when_process_survives(monkeypatch):
    monkeypatch.setattr(process.os, "name", "nt")
    monkeypatch.setattr(process.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(process, "_wait_for_process_exit", lambda *args, **kwargs: False)

    with pytest.raises(RuntimeError, match="did not terminate"):
        process.terminate_process_tree(pid=4321)


def test_posix_tree_termination_signals_process_group(monkeypatch):
    signals: list[tuple[int, int]] = []
    waits = iter([False, True])
    monkeypatch.setattr(process.os, "name", "posix")
    monkeypatch.setattr(
        process.os,
        "killpg",
        lambda group, sig: signals.append((group, sig)),
        raising=False,
    )
    monkeypatch.setattr(process.signal, "SIGKILL", 9, raising=False)
    monkeypatch.setattr(process, "_wait_for_process_exit", lambda *args, **kwargs: next(waits))

    process.terminate_process_tree(pid=4321, process_group_id=5000)

    assert signals == [(5000, process.signal.SIGTERM), (5000, 9)]


def test_mcp_cli_finally_releases_runtime_handle(monkeypatch):
    class Handle:
        closed = False

        def close(self):
            self.closed = True

    handle = Handle()
    monkeypatch.setattr(cli, "ensure_runtime", lambda *args, **kwargs: handle)
    def fail_server():
        raise RuntimeError("stdio closed")

    monkeypatch.setattr("apps.runtime.mcp.server.main", fail_server)

    with pytest.raises(RuntimeError, match="stdio closed"):
        cli._run_mcp(RUNTIME_URL, no_auto_start=False)
    assert handle.closed is True


def test_doctor_finally_releases_runtime_handle(monkeypatch, capsys):
    class Handle:
        runtime_url = RUNTIME_URL
        closed = False

        def close(self):
            self.closed = True

    handle = Handle()
    monkeypatch.setattr(cli, "ensure_runtime", lambda *args, **kwargs: handle)
    monkeypatch.setattr(
        cli,
        "wait_for_runtime",
        lambda runtime_url: {"browser": {"selected_driver": "managed-chromium", "executable_found": True}},
    )
    monkeypatch.setattr(cli, "_mcp_tools_are_default", lambda runtime_url: True)
    monkeypatch.setattr(cli, "_run_browser_loop", lambda runtime_url: True)

    assert cli._cmd_doctor(RUNTIME_URL, auto_start=True) == 0
    assert handle.closed is True
    assert json.loads(capsys.readouterr().out)["status"] == "pass"
