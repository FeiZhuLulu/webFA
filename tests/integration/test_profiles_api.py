from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from browser.profile_bundle import BUNDLE_CONTENT_TYPE, ProfileBundleService
from browser.profile_bootstrap import ProfileBootstrapService
from browser.profile_storage import ProfileStorageManager
from storage.db import reset_engine_for_tests


TOKEN = "p12-profile-control-token"
HEADERS = {"X-WebFA-Visualizer-Token": TOKEN}


def test_profile_catalog_control_api_is_protected_and_versioned(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        denied = client.get("/v1/profiles")
        assert denied.status_code == 403

        listed = client.get("/v1/profiles", headers=HEADERS)
        assert listed.status_code == 200
        assert [item["profile_id"] for item in listed.json()["profiles"]] == ["default"]

        created = client.post(
            "/v1/profiles",
            headers=HEADERS,
            json={
                "agent_alias": "work",
                "display_name": "Work Account",
                "agent_description": "Agent-visible work identity",
                "owner": "user_owned",
                "trust_mode": "guarded",
                "bound_agent_ids": ["agent-a"],
            },
        )
        assert created.status_code == 201, created.text
        profile = created.json()
        assert profile["agent_alias"] == "work"
        assert profile["storage_ref"].startswith("profiles/")

        updated = client.patch(
            f"/v1/profiles/{profile['profile_id']}",
            headers=HEADERS,
            json={
                "expected_version": profile["version"],
                "display_name": "Work Account Updated",
            },
        )
        assert updated.status_code == 200, updated.text
        updated_profile = updated.json()
        assert updated_profile["version"] == profile["version"] + 1

        stale = client.patch(
            f"/v1/profiles/{profile['profile_id']}",
            headers=HEADERS,
            json={
                "expected_version": profile["version"],
                "display_name": "Stale Update",
            },
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "profile_version_conflict"

        archived = client.request(
            "DELETE",
            f"/v1/profiles/{profile['profile_id']}",
            headers=HEADERS,
            json={"expected_version": updated_profile["version"]},
        )
        assert archived.status_code == 200, archived.text
        assert archived.json()["catalog_state"] == "archived"


def test_cookie_import_control_api_is_two_phase_and_secret_free(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()

    class FakeMaintenanceHost:
        def __init__(self, profile, storage, mutation_id):
            _ = profile, storage, mutation_id

        def import_cookies(self, cookies):
            return len(cookies)

        def close(self):
            return None

    secret = "api-cookie-secret-never-returned"
    content = json.dumps(
        [
            {
                "name": "sid",
                "value": secret,
                "url": "https://example.com/",
                "path": "/",
                "secure": True,
                "httpOnly": True,
                "expirationDate": time.time() + 3600,
            }
        ]
    ).encode("utf-8")

    with TestClient(app) as client:
        repository = app.state.profile_repository
        profile = repository.get_profile("default")
        app.state.profile_bootstrap_service = ProfileBootstrapService(
            repository=repository,
            storage=ProfileStorageManager(tmp_path / "WebFA"),
            host_factory=FakeMaintenanceHost,
        )

        denied = client.post(
            f"/v1/profiles/default/bootstrap/cookies/preview?expected_version={profile.version}",
            content=content,
            headers={"Content-Type": "application/octet-stream"},
        )
        assert denied.status_code == 403

        previewed = client.post(
            f"/v1/profiles/default/bootstrap/cookies/preview?expected_version={profile.version}",
            content=content,
            headers={**HEADERS, "Content-Type": "application/octet-stream"},
        )
        assert previewed.status_code == 200, previewed.text
        preview = previewed.json()
        assert preview["accepted_count"] == 1
        assert preview["domains"] == ["example.com"]
        assert secret not in previewed.text
        assert "sid" not in previewed.text

        wrong_control = client.post(
            "/v1/profiles/default/bootstrap/cookies/import",
            headers={"X-WebFA-Visualizer-Token": "wrong-token"},
            json={
                "preview_token": preview["preview_token"],
                "expected_version": profile.version,
            },
        )
        assert wrong_control.status_code == 403

        imported = client.post(
            "/v1/profiles/default/bootstrap/cookies/import",
            headers=HEADERS,
            json={
                "preview_token": preview["preview_token"],
                "expected_version": profile.version,
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["status"] == "cookies_imported"
        assert imported.json()["imported_count"] == 1
        assert secret not in imported.text
        assert "sid" not in imported.text


def test_profile_clone_control_api_creates_new_isolated_catalog_entry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()

    with TestClient(app) as client:
        repository = app.state.profile_repository
        source = repository.get_profile("default")
        storage = ProfileStorageManager(tmp_path / "WebFA")
        source_paths = storage.paths_for(source)
        (source_paths.user_data_dir / "Default" / "Local Storage").mkdir(parents=True)
        (source_paths.user_data_dir / "Default" / "Local Storage" / "state.log").write_bytes(
            b"clone-api-state"
        )
        app.state.profile_storage_manager = storage
        app.state.profile_bootstrap_service = ProfileBootstrapService(
            repository=repository,
            storage=storage,
        )

        denied = client.post(
            f"/v1/profiles/default/bootstrap/clone/preview?expected_version={source.version}"
        )
        assert denied.status_code == 403

        previewed = client.post(
            f"/v1/profiles/default/bootstrap/clone/preview?expected_version={source.version}",
            headers=HEADERS,
        )
        assert previewed.status_code == 200, previewed.text
        preview = previewed.json()
        assert preview["file_count"] == 1
        assert "state.log" not in previewed.text
        assert "clone-api-state" not in previewed.text

        cloned = client.post(
            "/v1/profiles/default/bootstrap/clone",
            headers=HEADERS,
            json={
                "preview_token": preview["preview_token"],
                "expected_source_version": source.version,
                "target_profile": {
                    "agent_alias": "api-clone",
                    "display_name": "API Clone",
                    "owner": "user_owned",
                    "trust_mode": "guarded",
                },
            },
        )
        assert cloned.status_code == 200, cloned.text
        result = cloned.json()
        assert result["status"] == "profile_cloned"
        assert result["target_agent_alias"] == "api-clone"
        assert "clone-api-state" not in cloned.text

        target = repository.get_profile(result["target_profile_id"])
        assert target.bootstrap_source == "cloned"
        assert target.bound_agent_ids == []
        assert (
            storage.paths_for(target).user_data_dir
            / "Default"
            / "Local Storage"
            / "state.log"
        ).read_bytes() == b"clone-api-state"


def test_validation_errors_do_not_echo_sensitive_inputs(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    secret = "sensitive bundle passphrase 123"

    with TestClient(create_app()) as client:
        response = client.post(
            "/v1/profiles/default/bootstrap/bundle/export",
            headers=HEADERS,
            json={
                "preview_token": "preview-token",
                "expected_source_version": 1,
                "passphrase": secret,
            },
        )

    assert response.status_code == 422
    assert secret not in response.text
    assert '"input"' not in response.text


def test_profile_bundle_api_streams_encrypted_export_and_restores_new_profile(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()
    app = create_app()
    passphrase = "bundle api passphrase 123"

    with TestClient(app) as client:
        repository = app.state.profile_repository
        source = repository.get_profile("default")
        storage = ProfileStorageManager(tmp_path / "WebFA")
        source_paths = storage.paths_for(source)
        (source_paths.user_data_dir / "Default" / "Local Storage").mkdir(parents=True)
        (source_paths.user_data_dir / "Default" / "Local Storage" / "bundle.log").write_bytes(
            b"bundle-api-state"
        )
        app.state.profile_storage_manager = storage
        app.state.profile_bundle_service = ProfileBundleService(
            repository=repository,
            storage=storage,
            temp_root=tmp_path / "bundle-temp",
        )

        previewed = client.post(
            f"/v1/profiles/default/bootstrap/bundle/export/preview?expected_version={source.version}",
            headers=HEADERS,
        )
        assert previewed.status_code == 200, previewed.text
        export_preview = previewed.json()
        assert export_preview["file_count"] == 1
        assert "bundle.log" not in previewed.text
        assert "bundle-api-state" not in previewed.text

        exported = client.post(
            "/v1/profiles/default/bootstrap/bundle/export",
            headers={**HEADERS, "X-WebFA-Bundle-Passphrase": passphrase},
            json={
                "preview_token": export_preview["preview_token"],
                "expected_source_version": source.version,
            },
        )
        assert exported.status_code == 200, exported.text
        assert exported.headers["content-type"].startswith(BUNDLE_CONTENT_TYPE)
        assert exported.content.startswith(b"WEBFAPB1")
        assert b"bundle-api-state" not in exported.content
        assert exported.headers["x-webfa-bundle-sha256"]

        restore_previewed = client.post(
            "/v1/profile-bundles/restore/preview",
            headers={
                **HEADERS,
                "Content-Type": "application/octet-stream",
                "X-WebFA-Bundle-Passphrase": passphrase,
            },
            content=exported.content,
        )
        assert restore_previewed.status_code == 200, restore_previewed.text
        restore_preview = restore_previewed.json()
        assert restore_preview["source_agent_alias"] == source.agent_alias
        assert restore_preview["file_count"] == 1
        assert "bundle.log" not in restore_previewed.text
        assert "bundle-api-state" not in restore_previewed.text
        assert passphrase not in restore_previewed.text

        restored = client.post(
            "/v1/profile-bundles/restore",
            headers={**HEADERS, "X-WebFA-Bundle-Passphrase": passphrase},
            json={
                "preview_token": restore_preview["preview_token"],
                "target_profile": {
                    "agent_alias": "bundle-api-restored",
                    "display_name": "Bundle API Restored",
                },
            },
        )
        assert restored.status_code == 200, restored.text
        result = restored.json()
        assert result["status"] == "profile_restored"
        target = repository.get_profile(result["target_profile_id"])
        assert target.bootstrap_source == "restored"
        assert (
            storage.paths_for(target).user_data_dir
            / "Default"
            / "Local Storage"
            / "bundle.log"
        ).read_bytes() == b"bundle-api-state"
        assert list((tmp_path / "bundle-temp").glob("*.webfa-profile")) == []
        assert list((tmp_path / "bundle-temp").glob("upload-*.bundle")) == []
