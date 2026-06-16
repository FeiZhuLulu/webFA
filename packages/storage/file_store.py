from __future__ import annotations

import json
import os
import platform
from pathlib import Path

WEBFA_DIR_NAME_WINDOWS_MAC = "WebFA"
WEBFA_DIR_NAME_LINUX = "webfa"
REQUIRED_SUBDIRS = ["credentials", "proofs", "audits", "artifacts", "logs", "tmp"]


def get_webfa_data_dir() -> Path:
    override = os.getenv("WEBFA_HOME")
    if override:
        return Path(override).expanduser().resolve()

    system = platform.system().lower()
    home = Path.home()

    if system == "windows":
        appdata = os.getenv("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / WEBFA_DIR_NAME_WINDOWS_MAC

    if system == "darwin":
        return home / "Library" / "Application Support" / WEBFA_DIR_NAME_WINDOWS_MAC

    xdg_config_home = os.getenv("XDG_CONFIG_HOME")
    base = Path(xdg_config_home) if xdg_config_home else home / ".config"
    return base / WEBFA_DIR_NAME_LINUX


def ensure_webfa_data_dir() -> dict[str, Path]:
    data_dir = get_webfa_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    config_path = data_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps({"version": 1}, indent=2), encoding="utf-8")

    paths: dict[str, Path] = {
        "data_dir": data_dir,
        "config": config_path,
        "db": data_dir / "webfa.db",
    }

    for dirname in REQUIRED_SUBDIRS:
        path = data_dir / dirname
        path.mkdir(parents=True, exist_ok=True)
        paths[dirname] = path

    return paths
