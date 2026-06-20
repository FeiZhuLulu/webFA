from pathlib import Path

from registry.transaction_registry import build_default_registry


def test_build_default_registry_allows_missing_resources_for_packaged_runtime(tmp_path: Path):
    registry = build_default_registry(tmp_path / "missing-resources")

    assert registry.as_json() == []

