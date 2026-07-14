from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from browser.managed_chromium_host import ManagedChromiumHost, _find_chromium_executable
from browser.profile_bundle import ProfileBundleService
from browser.profile_bootstrap import ProfileBootstrapService
from browser.profile_repository import ProfileRepository
from browser.profile_storage import ProfileStorageManager
from schemas.profile import BrowserProfileCreate
from storage.db import init_db, reset_engine_for_tests


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        body = b"<!doctype html><html><body>cookie import verification</body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
          document.cookie = 'clone_identity={identity}; path=/; Max-Age=3600; SameSite=Lax';
          localStorage.setItem('clone_identity', '{identity}');
          const db = await new Promise((resolve, reject) => {{
            const request = indexedDB.open('webfa-clone-test', 1);
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
          return true;
        }})()
        """
    )
    assert result is True


def _read_identity(host: ManagedChromiumHost) -> dict:
    result = host.evaluate(
        """
        (async () => {
          const db = await new Promise((resolve, reject) => {
            const request = indexedDB.open('webfa-clone-test', 1);
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
          return {
            cookie: document.cookie,
            local: localStorage.getItem('clone_identity'),
            indexed,
          };
        })()
        """
    )
    assert isinstance(result, dict)
    return result


def test_cookie_import_persists_through_real_maintenance_host(monkeypatch, tmp_path: Path) -> None:
    _require_managed_chromium()
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    profile = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="cookie-import",
            display_name="Cookie Import",
        )
    )
    storage = ProfileStorageManager(home)
    service = ProfileBootstrapService(repository=repository, storage=storage)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    secret = "real-maintenance-cookie-secret"
    content = json.dumps(
        [
            {
                "name": "webfa_imported_identity",
                "value": secret,
                "url": url,
                "path": "/",
                "secure": False,
                "httpOnly": False,
                "expirationDate": time.time() + 3600,
            }
        ]
    ).encode("utf-8")

    try:
        preview = service.preview_cookie_import(
            profile.profile_id,
            expected_version=profile.version,
            content=content,
            input_format="json",
            control_token="control-token",
        )
        assert preview.accepted_count == 1
        assert secret not in json.dumps(preview.model_dump(mode="json"))

        result = service.commit_cookie_import(
            profile.profile_id,
            preview_token=preview.preview_token,
            expected_version=profile.version,
            control_token="control-token",
        )
        assert result.status == "cookies_imported"
        assert result.imported_count == 1
        assert result.verified_count == 1
        assert secret not in json.dumps(result.model_dump(mode="json"))

        updated = repository.get_profile(profile.profile_id)
        lock = storage.acquire_process_lock(
            updated,
            runtime_instance_id="runtime-verification",
            runtime_generation="generation-verification",
            session_id="session-verification",
        )
        host = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                updated,
                headless=True,
                runtime_instance_id="runtime-verification",
                runtime_generation="generation-verification",
            )
        )
        try:
            host.navigate(url)
            cookie_text = host.evaluate("document.cookie")
            assert isinstance(cookie_text, str)
            assert f"webfa_imported_identity={secret}" in cookie_text
        finally:
            host.close()
            lock.release()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_profile_clone_copies_real_chromium_identity_and_then_isolates_mutations(monkeypatch, tmp_path: Path) -> None:
    _require_managed_chromium()
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    source = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="clone-source",
            display_name="Clone Source",
        )
    )
    storage = ProfileStorageManager(home)
    service = ProfileBootstrapService(repository=repository, storage=storage)

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"

    source_lock = storage.acquire_process_lock(
        source,
        runtime_instance_id="source-seed",
        runtime_generation="source-seed-generation",
        session_id="source-seed-session",
    )
    source_host = ManagedChromiumHost(
        launch_spec=storage.launch_spec(
            source,
            headless=True,
            runtime_instance_id="source-seed",
            runtime_generation="source-seed-generation",
        )
    )
    try:
        source_host.navigate(url)
        _write_identity(source_host, "SOURCE")
    finally:
        source_host.close()
        source_lock.release()

    try:
        preview = service.preview_profile_clone(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-token",
        )
        result = service.commit_profile_clone(
            source.profile_id,
            preview_token=preview.preview_token,
            expected_source_version=source.version,
            target_profile=BrowserProfileCreate(
                agent_alias="clone-target",
                display_name="Clone Target",
            ),
            control_token="control-token",
        )
        target = repository.get_profile(result.target_profile_id)
        assert target.bootstrap_source == "cloned"

        source_lock = storage.acquire_process_lock(
            source,
            runtime_instance_id="source-check",
            runtime_generation="source-check-generation",
            session_id="source-check-session",
        )
        target_lock = storage.acquire_process_lock(
            target,
            runtime_instance_id="target-check",
            runtime_generation="target-check-generation",
            session_id="target-check-session",
        )
        source_host = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                source,
                headless=True,
                runtime_instance_id="source-check",
                runtime_generation="source-check-generation",
            )
        )
        target_host = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                target,
                headless=True,
                runtime_instance_id="target-check",
                runtime_generation="target-check-generation",
            )
        )
        try:
            source_host.navigate(url)
            target_host.navigate(url)
            source_state = _read_identity(source_host)
            target_state = _read_identity(target_host)
            assert source_state["local"] == "SOURCE"
            assert source_state["indexed"] == "SOURCE"
            assert "clone_identity=SOURCE" in source_state["cookie"]
            assert target_state == source_state

            _write_identity(target_host, "TARGET")
            assert _read_identity(target_host)["local"] == "TARGET"
            assert _read_identity(source_host)["local"] == "SOURCE"
            assert "clone_identity=SOURCE" in _read_identity(source_host)["cookie"]
        finally:
            source_host.close()
            target_host.close()
            source_lock.release()
            target_lock.release()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_profile_bundle_roundtrip_restores_real_chromium_identity(monkeypatch, tmp_path: Path) -> None:
    _require_managed_chromium()
    home = tmp_path / "WebFA"
    monkeypatch.setenv("WEBFA_HOME", str(home))
    reset_engine_for_tests()
    init_db()
    repository = ProfileRepository()
    source = repository.create_profile(
        BrowserProfileCreate(
            agent_alias="bundle-source",
            display_name="Bundle Source",
        )
    )
    storage = ProfileStorageManager(home)
    bundle_service = ProfileBundleService(
        repository=repository,
        storage=storage,
        temp_root=tmp_path / "bundle-temp",
    )

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/"
    passphrase = "real chromium bundle passphrase"

    source_lock = storage.acquire_process_lock(
        source,
        runtime_instance_id="bundle-source-seed",
        runtime_generation="bundle-source-generation",
        session_id="bundle-source-session",
    )
    source_host = ManagedChromiumHost(
        launch_spec=storage.launch_spec(
            source,
            headless=True,
            runtime_instance_id="bundle-source-seed",
            runtime_generation="bundle-source-generation",
        )
    )
    try:
        source_host.navigate(url)
        _write_identity(source_host, "BUNDLE")
    finally:
        source_host.close()
        source_lock.release()

    try:
        export_preview = bundle_service.preview_export(
            source.profile_id,
            expected_source_version=source.version,
            control_token="control-token",
        )
        artifact = bundle_service.export_bundle(
            source.profile_id,
            preview_token=export_preview.preview_token,
            expected_source_version=source.version,
            passphrase=passphrase,
            control_token="control-token",
        )
        restore_preview = bundle_service.preview_restore(
            artifact.path,
            passphrase=passphrase,
            control_token="control-token",
        )
        restored_result = bundle_service.restore_bundle(
            preview_token=restore_preview.preview_token,
            passphrase=passphrase,
            target_profile=BrowserProfileCreate(
                agent_alias="bundle-restored",
                display_name="Bundle Restored",
            ),
            control_token="control-token",
        )
        restored = repository.get_profile(restored_result.target_profile_id)
        assert restored.bootstrap_source == "restored"

        source_lock = storage.acquire_process_lock(
            source,
            runtime_instance_id="bundle-source-check",
            runtime_generation="bundle-source-check-generation",
            session_id="bundle-source-check-session",
        )
        restored_lock = storage.acquire_process_lock(
            restored,
            runtime_instance_id="bundle-restored-check",
            runtime_generation="bundle-restored-check-generation",
            session_id="bundle-restored-check-session",
        )
        source_host = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                source,
                headless=True,
                runtime_instance_id="bundle-source-check",
                runtime_generation="bundle-source-check-generation",
            )
        )
        restored_host = ManagedChromiumHost(
            launch_spec=storage.launch_spec(
                restored,
                headless=True,
                runtime_instance_id="bundle-restored-check",
                runtime_generation="bundle-restored-check-generation",
            )
        )
        try:
            source_host.navigate(url)
            restored_host.navigate(url)
            source_state = _read_identity(source_host)
            restored_state = _read_identity(restored_host)
            assert restored_state == source_state
            assert source_state["local"] == "BUNDLE"
            assert source_state["indexed"] == "BUNDLE"
            assert "clone_identity=BUNDLE" in source_state["cookie"]

            _write_identity(restored_host, "RESTORED")
            assert _read_identity(restored_host)["local"] == "RESTORED"
            assert _read_identity(source_host)["local"] == "BUNDLE"
        finally:
            source_host.close()
            restored_host.close()
            source_lock.release()
            restored_lock.release()
    finally:
        bundle_service.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
