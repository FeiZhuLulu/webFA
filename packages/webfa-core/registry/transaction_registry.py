from __future__ import annotations

from pathlib import Path

import yaml

from schemas.transaction import TransactionDefinition


class TransactionRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, TransactionDefinition] = {}

    def load_dir(self, directory: Path) -> list[TransactionDefinition]:
        loaded: list[TransactionDefinition] = []
        for path in sorted(directory.glob("*.yaml")):
            loaded.append(self.load_file(path))
        return loaded

    def load_file(self, path: Path) -> TransactionDefinition:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        definition = TransactionDefinition.model_validate(data)
        self._definitions[definition.id] = definition
        return definition

    def list(self) -> list[TransactionDefinition]:
        return list(self._definitions.values())

    def get(self, transaction_id: str) -> TransactionDefinition | None:
        return self._definitions.get(transaction_id)

    def as_json(self) -> list[dict]:
        return [definition.model_dump(mode="json") for definition in self.list()]


def default_resources_root() -> Path:
    return Path(__file__).resolve().parents[3] / "resources"


def build_default_registry(resources_root: Path | None = None) -> TransactionRegistry:
    root = resources_root or default_resources_root()
    registry = TransactionRegistry()
    registry.load_dir(root / "transactions")
    return registry
