"""Unit tests for CapabilityRegistry and mock transaction loading."""

from pathlib import Path

from registry.capability_registry import CapabilityRegistry
from registry.transaction_registry import TransactionRegistry


def test_capability_registry_has_mock_capabilities():
    reg = CapabilityRegistry()
    caps = reg.list()
    assert len(caps) == 6
    ids = {c.id for c in caps}
    assert "mock.issue.read" in ids
    assert "mock.branch.create" in ids
    assert "mock.pr.create" in ids


def test_capability_registry_get():
    reg = CapabilityRegistry()
    cap = reg.get("mock.issue.read")
    assert cap is not None
    assert cap.provider == "mock"


def test_capability_registry_exists():
    reg = CapabilityRegistry()
    assert reg.exists("mock.issue.read") is True
    assert reg.exists("nonexistent.capability") is False


def test_capability_registry_validate_required():
    reg = CapabilityRegistry()
    missing = reg.validate_required(["mock.issue.read", "mock.branch.create"])
    assert missing == []

    missing = reg.validate_required(["mock.issue.read", "nonexistent.capability"])
    assert missing == ["nonexistent.capability"]


def test_mock_transaction_loaded():
    resources_root = Path(__file__).resolve().parents[2] / "resources"
    registry = TransactionRegistry()
    registry.load_dir(resources_root / "transactions")

    mock_txn = registry.get("mock.patch_and_open_pr")
    assert mock_txn is not None
    assert mock_txn.provider == "mock"
    assert mock_txn.risk == "high"
    assert mock_txn.approval_level == "user"
    assert len(mock_txn.required_capabilities) == 6


def test_mock_transaction_capabilities_valid():
    resources_root = Path(__file__).resolve().parents[2] / "resources"
    registry = TransactionRegistry()
    registry.load_dir(resources_root / "transactions")

    missing = registry.validate_capabilities("mock.patch_and_open_pr")
    assert missing == []


def test_all_transactions_loaded():
    resources_root = Path(__file__).resolve().parents[2] / "resources"
    registry = TransactionRegistry()
    registry.load_dir(resources_root / "transactions")

    txns = registry.list()
    ids = {t.id for t in txns}
    assert "mock.patch_and_open_pr" in ids
    assert "github.patch_and_open_pr" in ids
    assert "hf.compare_and_publish" in ids
