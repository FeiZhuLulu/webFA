from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx


DEFAULT_RUNTIME_URL = "http://127.0.0.1:8787"


@dataclass
class RuntimeProcess:
    runtime_url: str
    process: subprocess.Popen | None
    reused_existing: bool


def get_runtime_url(runtime_url: str | None = None) -> str:
    return runtime_url or os.getenv("WEBFA_RUNTIME_URL", DEFAULT_RUNTIME_URL)


def parse_runtime_url(runtime_url: str) -> tuple[str, int]:
    parsed = urlparse(runtime_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("runtime URL must be an http(s) URL with a host")
    return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def is_local_runtime_url(runtime_url: str) -> bool:
    host, _port = parse_runtime_url(runtime_url)
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def runtime_http_options(runtime_url: str) -> dict[str, object]:
    if is_local_runtime_url(runtime_url):
        return {"trust_env": False}
    return {}


def runtime_health(runtime_url: str | None = None, timeout: float = 2.0) -> dict | None:
    url = get_runtime_url(runtime_url)
    try:
        response = httpx.get(f"{url}/health", timeout=timeout, **runtime_http_options(url))
        if response.status_code == 200:
            return response.json()
    except httpx.HTTPError:
        return None
    return None


def wait_for_runtime(runtime_url: str, timeout_seconds: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        health = runtime_health(runtime_url, timeout=1.0)
        if health is not None:
            return health
        time.sleep(0.1)
    raise RuntimeError(f"Runtime did not become healthy at {runtime_url}")


def ensure_runtime(runtime_url: str | None = None, auto_start: bool = True) -> RuntimeProcess:
    url = get_runtime_url(runtime_url)
    if runtime_health(url) is not None:
        return RuntimeProcess(runtime_url=url, process=None, reused_existing=True)
    if not auto_start:
        raise RuntimeError(f"Runtime unreachable at {url}")

    host, port = parse_runtime_url(url)
    env = os.environ.copy()
    env.setdefault("WEBFA_BROWSER_DRIVER", "managed-chromium")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.runtime.main:app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_for_runtime(url)
    except Exception:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        raise
    return RuntimeProcess(runtime_url=url, process=process, reused_existing=False)
