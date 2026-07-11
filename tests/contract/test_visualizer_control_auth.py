from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


TOKEN = "visualizer-control-contract-token"
PROFILE_PAYLOAD = {
    "profile_id": "default",
    "owner": "agent_owned",
    "bound_agent_ids": ["agent-a"],
    "allowed_origins": [],
    "trust_mode": "trusted_agent",
    "unknown_external_effect_policy": "allow_with_audit",
}


def test_visualizer_control_plane_requires_separate_token_for_reads_and_mutations(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.setenv("WEBFA_VISUALIZER_CONTROL_TOKEN", TOKEN)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        missing_state = client.get("/v1/visualizer/state")
        allowed_state = client.get(
            "/v1/visualizer/state",
            headers={"X-WebFA-Visualizer-Token": TOKEN},
        )
        missing = client.put(
            "/v1/visualizer/profile-policy/default",
            json=PROFILE_PAYLOAD,
        )
        wrong = client.put(
            "/v1/visualizer/profile-policy/default",
            headers={"X-WebFA-Visualizer-Token": "wrong-token"},
            json=PROFILE_PAYLOAD,
        )
        allowed = client.put(
            "/v1/visualizer/profile-policy/default",
            headers={"X-WebFA-Visualizer-Token": TOKEN},
            json=PROFILE_PAYLOAD,
        )

    assert missing_state.status_code == 403
    assert allowed_state.status_code == 200
    assert missing.status_code == 403
    assert missing.json()["detail"]["code"] == "visualizer_control_forbidden"
    assert wrong.status_code == 403
    assert allowed.status_code == 200
    serialized = f"{missing_state.text} {allowed_state.text} {missing.text} {wrong.text} {allowed.text}"
    assert TOKEN not in serialized


def test_visualizer_control_plane_fails_closed_when_token_is_unconfigured(monkeypatch, tmp_path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    monkeypatch.delenv("WEBFA_VISUALIZER_CONTROL_TOKEN", raising=False)
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.put(
            "/v1/visualizer/profile-policy/default",
            headers={"X-WebFA-Visualizer-Token": TOKEN},
            json=PROFILE_PAYLOAD,
        )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "visualizer_control_unavailable"
