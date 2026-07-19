from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata


spec_root = Path(SPECPATH).resolve()
entry_point = spec_root / "webfa_sidecar_entry.py"
mode = os.environ.get("WEBFA_PYINSTALLER_MODE", "onefile").strip().lower()
if mode not in {"onedir", "onefile"}:
    raise ValueError("WEBFA_PYINSTALLER_MODE must be onedir or onefile")

datas = collect_data_files("webfa_resources")
for distribution in ("webfa-desktop-runtime", "mcp"):
    datas += copy_metadata(distribution)

analysis = Analysis(
    [str(entry_point)],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "apps.runtime.main",
        "apps.runtime.mcp.server",
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(analysis.pure)

if mode == "onedir":
    executable = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="webfa",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(spec_root / "webfa.ico"),
        version=str(spec_root / "webfa-version-info.txt"),
    )
    bundle = COLLECT(
        executable,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="webfa",
    )
else:
    executable = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="webfa",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=True,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(spec_root / "webfa.ico"),
        version=str(spec_root / "webfa-version-info.txt"),
    )
