from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from browser.managed_chromium_host import ManagedChromiumHost, _find_chromium_executable
from browser.profile_repository import ProfileRepository
from browser.profile_storage import ProfileStorageManager
from schemas.profile import BrowserProfileCreate
from storage.db import init_db, reset_engine_for_tests


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/sw.js":
            body = (
                b"self.addEventListener('install', event => self.skipWaiting());"
                b"self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));"
            )
            content_type = "application/javascript; charset=utf-8"
        else:
            body = b"<!doctype html><html><body>profile isolation</body></html>"
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if self.path == "/sw.js":
            self.send_header("Service-Worker-Allowed", "/")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        _ = format, args


def _require_managed_chromium() -> None:
    pytest.importorskip("websockets.sync.client")
    try:
        _find_chromium_executable()
    except RuntimeError as exc:
        pytest.skip(str(exc))


def _write_identity(host: ManagedChromiumHost, identity: str) -> None:
    result = host.evaluate(
        f"""
        (async () => {{
          document.cookie = 'webfa_identity={identity}; path=/; Max-Age=3600; SameSite=Lax';
          localStorage.setItem('webfa_identity', '{identity}');
          const db = await new Promise((resolve, reject) => {{
            const request = indexedDB.open('webfa-profile-test', 1);
            request.onupgradeneeded = () => request.result.createObjectStore('state');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          }});
          await new Promise((resolve, reject) => {{
            const tx = db.transaction('state', 'readwrite');
            tx.objectStore('state').put('{identity}', 'identity');
            tx.oncomplete = () => resolve(true);
            tx.onerror = () => reject(tx.error);
          }});
          db.close();
          await navigator.serviceWorker.register('/sw.js', {{ scope: '/' }});
          await navigator.serviceWorker.ready;
          return true;
        }})()
        """
    )
    assert result is True


def _read_identity(host: ManagedChromiumHost) -> dict:
    value = host.evaluate(
        """
        (async () => {
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open('webfa-profile-test', 1);
            request.onupgradeneeded = () => request.result.createObjectStore('state');
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          const indexed = await new Promise((resolve, reject) => {
            const request = db.transaction('state', 'readonly').objectStore('state').get('identity');
            request.onsuccess = () => resolve(request.result || null);
            request.onerror = () => reject(request.error);
          });
          db.close();
          const registrations = await navigator.serviceWorker.getRegistrations();
          return {
            cookie: document.cookie,
            local: localStorage.getItem('webfa_identity'),
            indexed,
            serviceWorkerCount: registrations.length,
          };
        })()
        """
    )
    assert isinstance(value, dict)
    return value


def test_two_persistent_profiles_isolate_and_retain_web_storage(monkeypatch, tmp_path: Path):
    _require_managed_chromium()
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    profile_a = repository.create_profile(
        BrowserProfileCreate(agent_alias="account-a", display_name="Account A")
    )
    profile_b = repository.create_profile(
        BrowserProfileCreate(agent_alias="account-b", display_name="Account B")
    )
    storage = ProfileStorageManager(home)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"

    def open_hosts(generation: str):
        lock_a = storage.acquire_process_lock(
            profile_a,
            runtime_instance_id=f"runtime-a-{generation}",
            runtime_generation=f"generation-a-{generation}",
            session_id=f"session-a-{generation}",
        )
        lock_b = storage.acquire_process_lock(
            profile_b,
            runtime_instance_id=f"runtime-b-{generation}",
            runtime_generation=f"generation-b-{generation}",
            session_id=f"session-b-{generation}",
        )
        host_a = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                profile_a,
                headless=True,
                runtime_instance_id=f"runtime-a-{generation}",
                runtime_generation=f"generation-a-{generation}",
            )
        )
        host_b = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                profile_b,
                headless=True,
                runtime_instance_id=f"runtime-b-{generation}",
                runtime_generation=f"generation-b-{generation}",
            )
        )
        return lock_a, lock_b, host_a, host_b

    try:
        lock_a, lock_b, host_a, host_b = open_hosts("first")
        try:
            host_a.navigate(url)
            host_b.navigate(url)
            _write_identity(host_a, "A")
            _write_identity(host_b, "B")
            assert _read_identity(host_a)["local"] == "A"
            assert _read_identity(host_b)["local"] == "B"
        finally:
            host_a.close()
            host_b.close()
            lock_a.release()
            lock_b.release()

        lock_a, lock_b, host_a, host_b = open_hosts("second")
        try:
            host_a.navigate(url)
            host_b.navigate(url)
            state_a = _read_identity(host_a)
            state_b = _read_identity(host_b)
            assert state_a["local"] == "A"
            assert state_a["indexed"] == "A"
            assert state_a["serviceWorkerCount"] == 1
            assert "webfa_identity=A" in state_a["cookie"]
            assert state_b["local"] == "B"
            assert state_b["indexed"] == "B"
            assert state_b["serviceWorkerCount"] == 1
            assert "webfa_identity=B" in state_b["cookie"]
        finally:
            host_a.close()
            host_b.close()
            lock_a.release()
            lock_b.release()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
