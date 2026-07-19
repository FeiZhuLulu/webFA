"""PyInstaller entry point for the WebFA multicall Runtime sidecar."""

from apps.runtime.cli import main_webfa


if __name__ == "__main__":
    raise SystemExit(main_webfa())
