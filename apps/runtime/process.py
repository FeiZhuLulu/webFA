from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from ipaddress import ip_address
from pathlib import Path
from typing import IO, Iterator
from urllib.parse import urlparse
from uuid import uuid4

import httpx

from apps.runtime.identity import PRODUCT_ID, RELEASE_VERSION, RUNTIME_PROTOCOL_VERSION
from storage.file_store import get_webfa_data_dir


DEFAULT_RUNTIME_URL = "http://127.0.0.1:8787"
_OWNERSHIP_SCHEMA_VERSION = 1
_OWNERSHIP_KIND = "webfa-mcp-auto-start"
_INSTANCE_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{15,127}")


class RuntimeIdentityError(RuntimeError):
    """The configured endpoint responded, but it is not the expected Runtime."""


@dataclass
class RuntimeProcess:
    runtime_url: str
    process: subprocess.Popen | None
    reused_existing: bool
    instance_id: str
    _lease_id: str | None = field(default=None, repr=False)
    _metadata_path: Path | None = field(default=None, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)

    @property
    def managed_auto_start(self) -> bool:
        return self._lease_id is not None

    def close(self) -> None:
        """Release this client and stop only the last MCP-owned auto-start Runtime."""

        if self._closed:
            return
        if self._lease_id is None or self._metadata_path is None:
            self._closed = True
            return
        _release_runtime_lease(self)
        self._closed = True


def get_runtime_url(runtime_url: str | None = None) -> str:
    return runtime_url or os.getenv("WEBFA_RUNTIME_URL", DEFAULT_RUNTIME_URL)


def normalize_runtime_url(runtime_url: str) -> str:
    parsed = urlparse(runtime_url)
    host, port = parse_runtime_url(runtime_url)
    if host.lower() == "localhost":
        # Collapse the common hostname alias into the IPv4 loopback ownership
        # domain so two MCP clients cannot race separate locks for one port.
        normalized_host = "127.0.0.1"
    else:
        try:
            normalized_host = ip_address(host).compressed
        except ValueError:
            normalized_host = host.lower()
    if ":" in normalized_host:
        normalized_host = f"[{normalized_host}]"
    return f"{parsed.scheme.lower()}://{normalized_host}:{port}"


def parse_runtime_url(runtime_url: str) -> tuple[str, int]:
    parsed = urlparse(runtime_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("runtime URL must be an http(s) URL with a host")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("runtime URL must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise ValueError("runtime URL must identify an origin without a path, query, or fragment")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("runtime URL contains an invalid port") from exc
    return parsed.hostname, port


def is_local_runtime_url(runtime_url: str) -> bool:
    host, _port = parse_runtime_url(runtime_url)
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def runtime_http_options(runtime_url: str) -> dict[str, object]:
    if is_local_runtime_url(runtime_url):
        return {"trust_env": False}
    return {}


def runtime_health(
    runtime_url: str | None = None,
    timeout: float = 2.0,
    *,
    expected_instance_id: str | None = None,
) -> dict | None:
    """Return a verified WebFA health document, or ``None`` if unreachable.

    Any HTTP responder at the configured origin is an occupied endpoint.  A
    non-WebFA response therefore fails closed instead of being mistaken for a
    free port that auto-start may bind.
    """

    url = normalize_runtime_url(get_runtime_url(runtime_url))
    try:
        response = httpx.get(f"{url}/health", timeout=timeout, **runtime_http_options(url))
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        raise RuntimeIdentityError(
            f"Endpoint {url} responded to /health with HTTP {response.status_code}; refusing to treat it as WebFA"
        )
    try:
        health = response.json()
    except (TypeError, ValueError) as exc:
        raise RuntimeIdentityError(f"Endpoint {url} returned a non-JSON /health response") from exc
    _validate_runtime_identity(health, url, expected_instance_id=expected_instance_id)
    return health


def wait_for_runtime(
    runtime_url: str,
    timeout_seconds: float = 20.0,
    *,
    expected_instance_id: str | None = None,
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        health = runtime_health(
            runtime_url,
            timeout=1.0,
            expected_instance_id=expected_instance_id,
        )
        if health is not None:
            return health
        time.sleep(0.1)
    raise RuntimeError(f"Runtime did not become healthy at {runtime_url}")


def ensure_runtime(runtime_url: str | None = None, auto_start: bool = True) -> RuntimeProcess:
    """Connect to a Runtime and acquire ownership only for MCP auto-starts.

    Check-and-spawn and lease mutations are serialized by an OS file lock.  A
    valid existing Desktop/external Runtime is reused without ownership, while
    an existing Runtime carrying matching MCP auto-start metadata gets a lease
    so it cannot be stopped until the last MCP client closes.
    """

    url = normalize_runtime_url(get_runtime_url(runtime_url))
    metadata_path, lock_path = _ownership_paths(url)
    with _endpoint_lock(lock_path):
        health = runtime_health(url)
        if health is not None:
            managed = _matching_managed_metadata(metadata_path, url, health)
            if managed is not None:
                lease_id = _add_runtime_lease(managed)
                _write_metadata(metadata_path, managed)
                return RuntimeProcess(
                    runtime_url=url,
                    process=None,
                    reused_existing=True,
                    instance_id=str(health["instance_id"]),
                    _lease_id=lease_id,
                    _metadata_path=metadata_path,
                )
            return RuntimeProcess(
                runtime_url=url,
                process=None,
                reused_existing=True,
                instance_id=str(health["instance_id"]),
            )

        if not auto_start:
            raise RuntimeError(f"Runtime unreachable at {url}")
        parsed = urlparse(url)
        if parsed.scheme != "http" or not is_local_runtime_url(url):
            raise RuntimeError(
                f"Runtime auto-start is restricted to loopback HTTP origins; configured endpoint is {url}"
            )

        # An unreachable stale record must not confer ownership on a new PID.
        with suppress(FileNotFoundError):
            metadata_path.unlink()

        host, port = parse_runtime_url(url)
        instance_id = f"runtime_{uuid4().hex}"
        env = os.environ.copy()
        env.setdefault("WEBFA_BROWSER_DRIVER", "managed-chromium")
        env["WEBFA_API_HOST"] = host
        env["WEBFA_API_PORT"] = str(port)
        env["WEBFA_RUNTIME_INSTANCE_ID"] = instance_id
        if getattr(sys, "frozen", False):
            command = [
                sys.executable,
                "runtime",
                "--host",
                host,
                "--port",
                str(port),
            ]
        else:
            command = [
                sys.executable,
                "-m",
                "uvicorn",
                "apps.runtime.main:app",
                "--host",
                host,
                "--port",
                str(port),
            ]
        popen_options: dict[str, object] = {
            "env": env,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
        }
        if os.name == "nt":
            popen_options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_options["start_new_session"] = True
        child = subprocess.Popen(command, **popen_options)
        pid = getattr(child, "pid", None)
        if not isinstance(pid, int) or pid <= 0:
            terminate_process_tree(pid=0, process=child)
            raise RuntimeError("Runtime child did not expose a valid process id")
        process_identity = _process_identity(pid)
        if process_identity is None:
            terminate_process_tree(
                pid=pid,
                process=child,
                process_group_id=pid if os.name != "nt" else None,
            )
            raise RuntimeError("Unable to establish a stable Runtime child process identity")
        try:
            verified_health = wait_for_runtime(url, expected_instance_id=instance_id)
        except Exception:
            terminate_process_tree(
                pid=pid,
                process=child,
                process_group_id=pid if os.name != "nt" else None,
            )
            raise
        _validate_runtime_identity(verified_health, url, expected_instance_id=instance_id)

        lease_id = uuid4().hex
        try:
            metadata = {
                "schema_version": _OWNERSHIP_SCHEMA_VERSION,
                "kind": _OWNERSHIP_KIND,
                "runtime_url": url,
                "instance_id": instance_id,
                "pid": pid,
                "process_identity": process_identity,
                "process_group_id": pid if os.name != "nt" else None,
                "created_at": _utc_now(),
                "leases": [_new_lease(lease_id)],
            }
            _write_metadata(metadata_path, metadata)
        except Exception:
            terminate_process_tree(
                pid=pid,
                process=child,
                process_group_id=pid if os.name != "nt" else None,
            )
            raise
        return RuntimeProcess(
            runtime_url=url,
            process=child,
            reused_existing=False,
            instance_id=instance_id,
            _lease_id=lease_id,
            _metadata_path=metadata_path,
        )


def terminate_process_tree(
    *,
    pid: int,
    process: subprocess.Popen | None = None,
    process_group_id: int | None = None,
    timeout_seconds: float = 5.0,
) -> None:
    """Terminate an owned Runtime's complete process tree."""

    if pid <= 0:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
        )
        if not _wait_for_process_exit(pid, process, timeout_seconds):
            raise RuntimeError(f"Owned Runtime process tree {pid} did not terminate")
        return

    group_id = process_group_id if isinstance(process_group_id, int) and process_group_id > 0 else pid
    try:
        os.killpg(group_id, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError as exc:
        raise RuntimeError(f"Unable to terminate owned Runtime process group {group_id}") from exc
    if _wait_for_process_exit(pid, process, timeout_seconds):
        return
    with suppress(ProcessLookupError):
        os.killpg(group_id, signal.SIGKILL)
    if not _wait_for_process_exit(pid, process, timeout_seconds):
        raise RuntimeError(f"Owned Runtime process group {group_id} did not terminate")


def _validate_runtime_identity(
    health: object,
    runtime_url: str,
    *,
    expected_instance_id: str | None,
) -> None:
    if not isinstance(health, dict):
        raise RuntimeIdentityError(f"Endpoint {runtime_url} returned an invalid WebFA /health document")
    instance_id = health.get("instance_id")
    valid_instance = isinstance(instance_id, str) and _INSTANCE_ID_PATTERN.fullmatch(instance_id) is not None
    if (
        health.get("product") != PRODUCT_ID
        or health.get("release_version") != RELEASE_VERSION
        or health.get("protocol_version") != RUNTIME_PROTOCOL_VERSION
        or not valid_instance
    ):
        raise RuntimeIdentityError(
            f"Endpoint {runtime_url} failed the WebFA product/protocol/instance ownership handshake"
        )
    if expected_instance_id is not None and instance_id != expected_instance_id:
        raise RuntimeIdentityError(
            f"Endpoint {runtime_url} is a different WebFA Runtime instance; refusing ownership"
        )


def _ownership_paths(runtime_url: str) -> tuple[Path, Path]:
    root = get_webfa_data_dir() / "tmp" / "runtime-processes"
    root.mkdir(parents=True, exist_ok=True)
    endpoint_id = hashlib.sha256(runtime_url.encode("utf-8")).hexdigest()[:32]
    return root / f"{endpoint_id}.json", root / f"{endpoint_id}.lock"


@contextmanager
def _endpoint_lock(lock_path: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                _try_lock_file(handle)
                break
            except (BlockingIOError, OSError) as exc:
                if not _lock_is_busy(exc) or time.monotonic() >= deadline:
                    raise RuntimeError(f"Timed out acquiring Runtime ownership lock {lock_path}") from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock_file(handle)
    finally:
        handle.close()


def _try_lock_file(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: IO[bytes]) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _lock_is_busy(exc: OSError) -> bool:
    return isinstance(exc, BlockingIOError) or exc.errno in {
        errno.EACCES,
        errno.EAGAIN,
        getattr(errno, "EDEADLK", -1),
    }


def _matching_managed_metadata(metadata_path: Path, runtime_url: str, health: dict) -> dict | None:
    metadata = _read_metadata(metadata_path)
    if metadata is None:
        return None
    pid = metadata.get("pid")
    if (
        metadata.get("schema_version") != _OWNERSHIP_SCHEMA_VERSION
        or metadata.get("kind") != _OWNERSHIP_KIND
        or metadata.get("runtime_url") != runtime_url
        or metadata.get("instance_id") != health.get("instance_id")
        or not isinstance(pid, int)
        or pid <= 0
        or not _same_process(pid, metadata.get("process_identity"))
        or not isinstance(metadata.get("leases"), list)
    ):
        return None
    metadata["leases"] = [lease for lease in metadata["leases"] if _lease_is_live(lease)]
    return metadata


def _read_metadata(metadata_path: Path) -> dict | None:
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_metadata(metadata_path: Path, metadata: dict) -> None:
    temporary = metadata_path.with_name(f".{metadata_path.name}.{uuid4().hex}.tmp")
    encoded = json.dumps(metadata, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            descriptor = -1
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, metadata_path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(FileNotFoundError):
            temporary.unlink()


def _new_lease(lease_id: str) -> dict[str, object]:
    pid = os.getpid()
    process_identity = _process_identity(pid)
    if process_identity is None:
        raise RuntimeError("Unable to establish a stable MCP client process identity")
    return {
        "lease_id": lease_id,
        "client_pid": pid,
        "client_process_identity": process_identity,
        "created_at": _utc_now(),
    }


def _add_runtime_lease(metadata: dict) -> str:
    lease_id = uuid4().hex
    metadata["leases"].append(_new_lease(lease_id))
    return lease_id


def _lease_is_live(lease: object) -> bool:
    if not isinstance(lease, dict):
        return False
    lease_id = lease.get("lease_id")
    pid = lease.get("client_pid")
    if not isinstance(lease_id, str) or not lease_id or not isinstance(pid, int) or pid <= 0:
        return False
    return _same_process(pid, lease.get("client_process_identity"))


def _release_runtime_lease(runtime: RuntimeProcess) -> None:
    assert runtime._metadata_path is not None
    assert runtime._lease_id is not None
    metadata_path = runtime._metadata_path
    lock_path = metadata_path.with_suffix(".lock")
    with _endpoint_lock(lock_path):
        metadata = _read_metadata(metadata_path)
        if metadata is None:
            return
        if (
            metadata.get("schema_version") != _OWNERSHIP_SCHEMA_VERSION
            or metadata.get("kind") != _OWNERSHIP_KIND
            or metadata.get("runtime_url") != runtime.runtime_url
            or metadata.get("instance_id") != runtime.instance_id
        ):
            return
        leases = metadata.get("leases")
        if not isinstance(leases, list):
            return
        metadata["leases"] = [
            lease
            for lease in leases
            if isinstance(lease, dict)
            and lease.get("lease_id") != runtime._lease_id
            and _lease_is_live(lease)
        ]
        if metadata["leases"]:
            _write_metadata(metadata_path, metadata)
            return

        pid = metadata.get("pid")
        process_identity = metadata.get("process_identity")
        if not isinstance(pid, int) or pid <= 0 or not _same_process(pid, process_identity):
            with suppress(FileNotFoundError):
                metadata_path.unlink()
            return

        try:
            health = runtime_health(
                runtime.runtime_url,
                expected_instance_id=runtime.instance_id,
            )
        except RuntimeIdentityError:
            # The origin now belongs to someone else.  Drop stale metadata but
            # never signal the recorded PID.
            with suppress(FileNotFoundError):
                metadata_path.unlink()
            return
        if health is None and process_identity is None:
            # Without either a live handshake or a process-creation identity,
            # PID reuse cannot be excluded.
            return
        terminate_process_tree(
            pid=pid,
            process=runtime.process if runtime.process is not None and runtime.process.pid == pid else None,
            process_group_id=metadata.get("process_group_id"),
        )
        with suppress(FileNotFoundError):
            metadata_path.unlink()


def _same_process(pid: int, recorded_identity: object) -> bool:
    if not _process_is_alive(pid):
        return False
    if recorded_identity is None:
        return False
    if not isinstance(recorded_identity, str) or not recorded_identity:
        return False
    return _process_identity(pid) == recorded_identity


def _process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        return _windows_process_is_alive(pid)
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno in {errno.EPERM, errno.EACCES}:
            return True
        return False
    return True


def _windows_process_is_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_access_denied = 5
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() == error_access_denied
    try:
        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)


def _process_identity(pid: int) -> str | None:
    if pid <= 0:
        return None
    if os.name == "nt":
        return _windows_process_identity(pid)
    stat_path = Path(f"/proc/{pid}/stat")
    try:
        stat = stat_path.read_text(encoding="ascii")
        fields = stat[stat.rfind(")") + 2 :].split()
        start_ticks = fields[19]
        boot_id_path = Path("/proc/sys/kernel/random/boot_id")
        boot_id = boot_id_path.read_text(encoding="ascii").strip() if boot_id_path.exists() else "unknown"
        return f"proc:{boot_id}:{start_ticks}"
    except (OSError, IndexError, UnicodeError):
        pass
    try:
        result = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    started = result.stdout.strip()
    return f"ps:{started}" if result.returncode == 0 and started else None


def _windows_process_identity(pid: int) -> str | None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
        return f"win:{created.dwHighDateTime:08x}{created.dwLowDateTime:08x}"
    finally:
        kernel32.CloseHandle(handle)


def _wait_for_process_exit(
    pid: int,
    process: subprocess.Popen | None,
    timeout_seconds: float,
) -> bool:
    if process is not None:
        try:
            process.wait(timeout=timeout_seconds)
            return True
        except subprocess.TimeoutExpired:
            return False
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if not _process_is_alive(pid):
            return True
        time.sleep(0.05)
    return not _process_is_alive(pid)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
