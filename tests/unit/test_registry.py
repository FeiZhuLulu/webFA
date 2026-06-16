from pathlib import Path

from registry.transaction_registry import build_default_registry


def test_transactions_are_loaded_from_resources():
    resources_root = Path(__file__).resolve().parents[2] / "resources"
    registry = build_default_registry(resources_root)
    ids = {definition.id for definition in registry.list()}

    assert "github.patch_and_open_pr" in ids
    assert "hf.compare_and_publish" in ids
    assert registry.get("github.patch_and_open_pr").provider == "github"
