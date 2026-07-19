from pathlib import Path

import pytest

from registry.transaction_registry import build_default_registry, default_resources_root


def test_default_resources_root_uses_pyinstaller_extraction_root(monkeypatch, tmp_path: Path):
    packaged_root = tmp_path / "webfa_resources"
    packaged_root.mkdir()
    monkeypatch.setattr("registry.transaction_registry.sys._MEIPASS", str(tmp_path), raising=False)

    assert default_resources_root() == packaged_root


def test_build_default_registry_rejects_missing_packaged_resources(tmp_path: Path):
    with pytest.raises(RuntimeError, match="transaction resources are unavailable"):
        build_default_registry(tmp_path / "missing-resources")


def test_build_default_registry_rejects_empty_packaged_resources(tmp_path: Path):
    (tmp_path / "transactions").mkdir()

    with pytest.raises(RuntimeError, match="transaction resources are empty"):
        build_default_registry(tmp_path)
