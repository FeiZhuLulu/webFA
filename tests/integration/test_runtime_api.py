from pathlib import Path

from fastapi.testclient import TestClient

from apps.runtime.main import create_app
from storage.db import reset_engine_for_tests


def test_health_returns_ok(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["runtime"] == "running"
    assert body["storage"]["db_path"].endswith("webfa.db")


def test_transactions_endpoint_returns_registry(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/transactions")

    assert response.status_code == 200
    ids = {item["id"] for item in response.json()["transactions"]}
    assert ids == {"github.patch_and_open_pr", "hf.compare_and_publish", "mock.patch_and_open_pr"}


def test_providers_endpoint_returns_disconnected(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("WEBFA_HOME", str(tmp_path / "WebFA"))
    reset_engine_for_tests()

    with TestClient(create_app()) as client:
        response = client.get("/v1/providers")

    assert response.status_code == 200
    providers = {item["id"]: item["status"] for item in response.json()["providers"]}
    assert providers["github"] == "disconnected"
    assert providers["huggingface"] == "disconnected"
