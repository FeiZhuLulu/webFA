from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from browser.managed_chromium_host import ManagedChromiumHost, _find_chromium_executable
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
