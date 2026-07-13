from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
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
