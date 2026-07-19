import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _json(relative_path: str) -> dict:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def test_release_versions_are_synchronized_across_distribution_inputs():
    desktop = _json("package.json")
    renderer = _json("apps/desktop/renderer/package.json")
    lock = _json("package-lock.json")
    runtime_version = (ROOT / "apps/runtime/version.py").read_text(encoding="utf-8")
    version_info = (ROOT / "packaging/webfa-version-info.txt").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts/build-sidecar.ps1").read_text(encoding="utf-8")

    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', runtime_version)
    assert match is not None
    version = match.group(1)
    version_tuple = tuple(int(part) for part in version.split(".")) + (0,)

    assert desktop["version"] == renderer["version"] == version
    assert lock["version"] == version
    assert lock["packages"][""]["version"] == version
    assert lock["packages"]["apps/desktop/renderer"]["version"] == version
    assert f"FileVersion', u'{version}'" in version_info
    assert f"ProductVersion', u'{version}'" in version_info
    assert f"filevers={version_tuple}" in version_info
    assert f"prodvers={version_tuple}" in version_info
    assert 'webfa_desktop_runtime-${ReleaseVersion}-*.whl' in build_script
    assert "Sidecar releases require Windows x64 CPython 3.12" in build_script
    assert "Build-local direct_url.json metadata must not enter" in build_script


def test_release_toolchains_and_signed_provenance_are_pinned():
    desktop = _json("package.json")
    windows_toolchain = _json("packaging/windows-toolchain-lock.json")
    wrapper = (ROOT / "scripts/build-windows-package.cjs").read_text(encoding="utf-8")
    provenance = (ROOT / "scripts/verify-release-provenance.cjs").read_text(
        encoding="utf-8"
    )

    assert (ROOT / ".nvmrc").read_text(encoding="utf-8").strip() == desktop["engines"][
        "node"
    ]
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12.10"
    assert windows_toolchain["schema_version"] == 1
    assert windows_toolchain["electron_builder_version"] == desktop["devDependencies"][
        "electron-builder"
    ]
    assert windows_toolchain["nsis"]["toolset"] == "0.0.0"
    for tool in ("nsis", "nsis_resources", "seven_zip"):
        assert re.fullmatch(r"[a-f0-9]{64}", windows_toolchain[tool]["sha256"])
    assert "verify-release-provenance.cjs" in wrapper
    assert "Formal signed release requires a clean source tree" in provenance
    assert 'describe", "--tags", "--exact-match"' in provenance


def test_python_release_wheels_are_exact_and_hash_locked():
    release_lock = ROOT / "packaging/python-windows-release-lock.txt"
    build_script = (ROOT / "scripts/build-sidecar.ps1").read_text(encoding="utf-8")
    entries = [
        line.strip()
        for line in release_lock.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]

    assert len(entries) >= 40
    assert len(entries) == len(set(entries))
    assert all(
        re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*==[0-9][A-Za-z0-9.!+_-]* "
            r"--hash=sha256:[a-f0-9]{64}",
            entry,
        )
        for entry in entries
    )
    assert not any(entry.lower().startswith("webfa-desktop-runtime==") for entry in entries)
    assert "python-windows-release-lock.txt" in build_script
    assert '"--require-hashes"' in build_script
    assert '"--only-binary=:all:"' in build_script
    assert '"--no-deps"' in build_script
    assert '"--isolated"' in build_script
    assert "Remove-Item Env:PYTHONHOME" in build_script
    assert "Remove-Item Env:PYTHONPATH" in build_script
    assert "& $PythonExecutable -I -c" in build_script
    assert 'Invoke-Checked $PythonExecutable @("-I", "-m", "venv", $VenvRoot)' in build_script
    assert "& $VenvPython -I -c" in build_script
    assert 'from importlib.metadata import version' in build_script
    assert '$ExpectedSeededPipVersion = "25.0.1"' in build_script
    assert "CPython 3.12.10 must seed pip $ExpectedSeededPipVersion" in build_script
    venv_invocations = re.findall(
        r"Invoke-Checked \$VenvPython @\((.*?)\)", build_script, re.DOTALL
    )
    assert len(venv_invocations) == 5
    assert all(re.match(r'\s*"-I",\s*"-m"', invocation) for invocation in venv_invocations)
    assert '"--constraint"' not in build_script
    sidecar_spec = (ROOT / "packaging/webfa-sidecar.spec").read_text(encoding="utf-8")
    assert sidecar_spec.count('icon=str(spec_root / "webfa.ico")') == 2


def test_node_release_manifests_use_only_exact_dependency_versions():
    exact_version = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")

    def assert_exact_specs(relative_path: str, section: str, values: dict) -> None:
        for name, value in values.items():
            if isinstance(value, dict):
                assert_exact_specs(relative_path, f"{section}.{name}", value)
                continue
            assert exact_version.fullmatch(value), (
                f"{relative_path} {section}.{name} must be exact, got {value}"
            )

    for relative_path in ("package.json", "apps/desktop/renderer/package.json"):
        manifest = _json(relative_path)
        for section in ("dependencies", "devDependencies", "overrides"):
            assert_exact_specs(relative_path, section, manifest.get(section, {}))


def test_next_postcss_security_override_is_resolved_in_the_lockfile():
    desktop = _json("package.json")
    lock = _json("package-lock.json")
    pinned = desktop["overrides"]["next@16.2.9"]["postcss"]

    assert lock["packages"]["node_modules/postcss"]["version"] == pinned
    assert "node_modules/next/node_modules/postcss" not in lock["packages"]


def test_electron_builder_contract_is_source_free_and_hardened():
    builder = (ROOT / "electron-builder.yml").read_text(encoding="utf-8")
    desktop = _json("package.json")

    assert desktop["productName"] == "WebFA"

    for required in (
        "appId: com.webfa.desktop",
        "asar: true",
        "compression: maximum",
        "publish: null",
        "toolsets:",
        'nsis: "0.0.0"',
        "electronDist: .release/electron-dist",
        "- package.json",
        "- apps/desktop/electron/dist/**/*",
        "- apps/desktop/renderer/out/**/*",
        "from: .release/sidecar",
        "from: packaging/webfa.ico",
        "icon: webfa.ico",
        "installerIcon: webfa.ico",
        "uninstallerIcon: webfa.ico",
        "include: installer.nsh",
        "requestedExecutionLevel: asInvoker",
        "perMachine: false",
        "allowElevation: false",
        "packElevateHelper: false",
        "differentialPackage: false",
        "runAsNode: false",
        "enableCookieEncryption: true",
        "enableNodeOptionsEnvironmentVariable: false",
        "enableNodeCliInspectArguments: false",
        "enableEmbeddedAsarIntegrityValidation: true",
        "onlyLoadAppFromAsar: true",
        "grantFileProtocolExtraPrivileges: false",
    ):
        assert required in builder

    assert "node_modules" not in builder
    files_block = builder.split("files:", 1)[1].split("extraResources:", 1)[0]
    positive_inputs = {
        line.strip()[2:]
        for line in files_block.splitlines()
        if line.strip().startswith("- ") and not line.strip().startswith('- "!')
    }
    assert positive_inputs == {
        "package.json",
        "apps/desktop/electron/dist/**/*",
        "apps/desktop/renderer/out/**/*",
    }


def test_release_scripts_gate_inputs_unpacking_and_signing():
    scripts = _json("package.json")["scripts"]
    input_pipeline = scripts["build:release-inputs"]
    wrapper = (ROOT / "scripts/build-windows-package.cjs").read_text(encoding="utf-8")
    signed_builder = (ROOT / "electron-builder.signed.yml").read_text(encoding="utf-8")

    for step in (
        "clean:release",
        "build:renderer",
        "build:electron",
        "build:sidecar:onedir",
        "prepare:electron-runtime",
        "generate:release-metadata",
        "verify:release-inputs",
    ):
        assert step in input_pipeline
    assert scripts["package:unpacked"].endswith("build-windows-package.cjs unpacked")
    assert scripts["package:windows:unsigned"].endswith(
        "build-windows-package.cjs unsigned"
    )
    assert scripts["package:windows:signed"].endswith("build-windows-package.cjs signed")
    assert 'delete cleanEnvironment[name]' in wrapper
    assert 'CSC_IDENTITY_AUTO_DISCOVERY: "false"' in wrapper
    assert '...signingEnvironment, CSC_IDENTITY_AUTO_DISCOVERY: "true"' in wrapper
    assert "WEBFA_SIGNING_CERT_SHA1" in wrapper
    assert "resolveNpmCli()" in wrapper
    assert 'require.resolve("electron-builder/package.json")' in wrapper
    assert 'run(process.execPath, [builder, ...builderArguments]' in wrapper
    assert '"ci", "--ignore-scripts"' in wrapper
    assert "npm.cmd" not in wrapper
    assert "electron-builder.cmd" not in wrapper
    assert "verify-unpacked-release.cjs" in wrapper
    assert "smoke-unpacked-desktop.cjs" in wrapper
    assert "verify-windows-package.cjs" in wrapper
    assert "forceCodeSigning: true" in signed_builder


def test_unpacked_desktop_smoke_proves_runtime_renderer_and_cleanup_lifecycle():
    scripts = _json("package.json")["scripts"]
    smoke = (ROOT / "scripts/smoke-unpacked-desktop.cjs").read_text(encoding="utf-8")

    assert scripts["smoke:unpacked"].endswith("smoke-unpacked-desktop.cjs")
    for required in (
        "--webfa-release-smoke",
        "--user-data-dir=",
        "release-smoke-result.json",
        'result.runtimeOwnership !== "desktop"',
        'result.applicationIconLoaded !== true',
        'result.apiUrl !== `http://127.0.0.1:${port}`',
        "environment.WEBFA_HOME = hostileInheritedHome",
        "--reuse-upgrade-user-data",
        "result.userDataPath",
        "reusedUpgradeUserData",
        'result.cleanup?.runtimeState !== "stopped"',
        "await canConnect(port)",
        "countProcessesByExecutable(sidecarExecutable)",
    ):
        assert required in smoke


def test_installed_desktop_smoke_proves_install_reinstall_and_uninstall_lifecycle():
    scripts = _json("package.json")["scripts"]
    smoke = (ROOT / "scripts/smoke-installed-desktop.cjs").read_text(
        encoding="utf-8"
    )

    assert scripts["smoke:installed:unsigned"].endswith(
        "smoke-installed-desktop.cjs unsigned"
    )
    assert scripts["smoke:installed:signed"].endswith(
        "smoke-installed-desktop.cjs signed"
    )
    for required in (
        'const minimumTempFreeBytes = 4 * 1024 * 1024 * 1024',
        '"pwsh.exe"',
        "waitForInstalledReady",
        "Installed payload differs from win-unpacked",
        'extraNames) !== JSON.stringify(["Uninstall WebFA.exe", "uninstallerIcon.ico"])',
        "Installed updater cache differs from the candidate installer",
        "Same-version reinstall changed its stable payload or installer identity",
        "invokeUninstaller()",
        "updaterCacheRemoved: true",
        'process.argv.includes("--cleanup-only")',
    ):
        assert required in smoke


def test_installed_ui_audit_proves_real_mcp_projection_and_accessibility_evidence():
    scripts = _json("package.json")["scripts"]
    audit = (ROOT / "scripts/audit-installed-ui.cjs").read_text(encoding="utf-8")

    assert scripts["audit:installed:ui"].endswith("audit-installed-ui.cjs")
    for required in (
        "installed Electron renderer via loopback-only CDP",
        "Accessibility.getFullAXTree",
        "unlabeledButtons",
        "unlabeledFields",
        "errorToasts",
        "raw fetch failure text is visible",
        "failed deterministic UI diagnostics",
        "accessibility tree is empty",
        "smoke-frozen-mcp.py",
        "/v1/mcp/config",
        'JSON.stringify(entry.args) !== \'["mcp"]\'',
        "desktopRuntimeOwnershipPreserved: true",
        "liveSessionHeldForProjection: true",
        "liveSessionReleasedCleanly",
        "installed MCP live-session checkpoint",
        "releaseInstalledMcpFlow()",
        "Control Center projection of the external MCP Agent session",
        "Monitor live projection of the external MCP Agent session",
        "HumanControlLease acquisition",
        "Agent control restoration",
        "pressTab(client",
        "tabToFocus(client",
        "Control Center skip link is not the first visible keyboard stop",
        "Monitor skip link is not the first visible keyboard stop",
        "Escape did not return HumanControl keyboard focus to Monitor controls",
        "HumanControl release became unavailable while its lease was active",
        "releaseAvailableWithoutFrameDependency",
        "keyboard.humanControl",
        "focusRecoveryAction",
        "controlCenterDrawerFocusRestored",
        "monitorDrawerFocusRestored",
        "monitor-runtime-disconnected",
        "endpoint-collision-mobile",
        "browser-missing-mobile",
        "control-center-sidecar-missing",
        "control-center-sidecar-corrupt-mobile",
        "control-center-runtime-startup-timeout",
        "control-center-sidecar-repaired",
        "desktop Monitor sidebar restoration after compact layout",
        "desktopMonitorSidebarStateRestored",
        "applicationLogValidation",
        "expectedSpawnDiagnostics",
        "buildSleeperExecutable()",
        "isolateInstalledSidecar()",
        "restoreInstalledSidecar()",
        "removeFailureHarness()",
        "installedSidecarRestored",
        "sidecarRepairRecoveryCaptured",
        "fs.constants.COPYFILE_EXCL",
        "DeprecationWarning",
        "HTTP error response",
        "Chromium error level",
        'await mainClient.send("Browser.close"',
        'await monitorClient.send("Page.close"',
        "lifecyclePreflight()",
    ):
        assert required in audit


def test_cross_version_upgrade_smoke_requires_real_older_identity_and_exact_cleanup():
    scripts = _json("package.json")["scripts"]
    smoke = (ROOT / "scripts/smoke-upgrade-desktop.cjs").read_text(encoding="utf-8")

    assert scripts["smoke:upgrade:windows"].endswith("smoke-upgrade-desktop.cjs")
    for required in (
        "Previous installer must be older",
        "same stable appId",
        "Signed previous installers require --previous-signer-sha1",
        "verify-windows-package.cjs",
        "Previous and current installers must be different artifacts",
        "Previous ${request.previousVersion} install",
        "Upgrade to ${currentVersion}",
        "Upgraded payload differs from current win-unpacked",
        "Upgrade left stale or unexpected application files",
        "smoke-unpacked-desktop.cjs",
        "runtimeOwnership !== \"desktop\"",
        "rendererServerStopped",
        "inspectInstalledArchiveIdentity",
        "Previous packaged app name changed the default user-data root",
        "seedProfileSentinel",
        "Current uninstaller changed preserved WebFA user data",
        "profileDataPreserved: true",
        "Upgrade uninstall cleanup",
        "Refusing to terminate processes without a valid upgrade-smoke marker",
        "Refusing to remove an unowned updater cache",
        "releaseQualified: request.previousMode === \"signed\" && request.currentMode === \"signed\"",
    ):
        assert required in smoke


def test_release_metadata_is_generated_and_packaged_as_legal_material():
    generator = (ROOT / "scripts/generate-release-metadata.cjs").read_text(encoding="utf-8")
    builder = (ROOT / "electron-builder.yml").read_text(encoding="utf-8")

    assert "SBOM.spdx.json" in generator
    assert "THIRD_PARTY_NOTICES.md" in generator
    assert "build-manifest.json" in generator
    assert 'desktop_sidecar_layout: "pyinstaller-onedir"' in generator
    assert "package_lock_sha256" in generator
    assert "python_release_lock_sha256" in generator
    assert "electron_archive_sha256" in generator
    assert "sidecar_bundle_sha256" in generator
    assert "sidecar_payload_bundle_sha256" in generator
    assert "desktop_archive_input_sha256" in generator
    assert "sidecar_pe_payloads" in generator
    assert "python_release_component_count" in generator
    assert "python_release_components_sha256" in generator
    assert "sbom_sha256" in generator
    assert "third_party_notices_sha256" in generator
    assert "windows_toolchain_lock_sha256" in generator
    assert "windows-toolchain-lock.json" in generator
    assert "application_icon_sha256" in generator
    assert "nsis_include_sha256" in generator
    assert "normalizeSpdxLicense" in generator
    assert '"MPL-2.0"' in generator
    assert '"PSF-2.0"' in generator
    assert "from: LICENSE" in builder
    assert "from: .release/metadata" in builder


def test_nsis_uninstall_hook_removes_only_release_installer_cache():
    hook = (ROOT / "packaging/installer.nsh").read_text(encoding="utf-8")
    verifier = (ROOT / "scripts/verify-release-inputs.cjs").read_text(encoding="utf-8")

    for required in (
        "!macro customUnInstall",
        "APP_INSTALLER_STORE_FILE",
        'Delete "$LOCALAPPDATA\\${APP_INSTALLER_STORE_FILE}"',
        '${GetParent} "$LOCALAPPDATA\\${APP_INSTALLER_STORE_FILE}"',
        'RMDir "$R0"',
    ):
        assert required in hook
    assert "RMDir /r" not in hook
    assert "$APPDATA" not in hook
    assert "DELETE_APP_DATA_ON_UNINSTALL" not in hook
    assert "NSIS uninstall cache cleanup does not enforce" in verifier
    assert "NSIS uninstall cache cleanup may not recursively remove" in verifier


def test_nsis_installer_fails_before_extraction_when_temp_drive_is_too_full():
    hook = (ROOT / "packaging/installer.nsh").read_text(encoding="utf-8")

    for required in (
        "!define WEBFA_MIN_TEMP_FREE_MB 4096",
        "!macro customInit",
        "GetDiskFreeSpaceEx",
        "System::Int64Op $0 / 1048576",
        "${If} $0 < ${WEBFA_MIN_TEMP_FREE_MB}",
        "SetErrorLevel 3",
        "Quit",
    ):
        assert required in hook


def test_release_verifiers_cover_hashes_fuses_and_archive_allowlist():
    inputs = (ROOT / "scripts/verify-release-inputs.cjs").read_text(encoding="utf-8")
    unpacked = (ROOT / "scripts/verify-unpacked-release.cjs").read_text(encoding="utf-8")
    icon_verifier = (ROOT / "scripts/windows-icon-verifier.cjs").read_text(encoding="utf-8")
    sidecar_smoke = (ROOT / "scripts/smoke-sidecar.cjs").read_text(encoding="utf-8")
    electron_runtime = (ROOT / "scripts/electron-runtime-verifier.cjs").read_text(
        encoding="utf-8"
    )

    for required in (
        "Release versions diverge",
        "package-lock.json root version is stale",
        "is not an exact version",
        "electronDistHash !== electronChecksum",
        "smoke-sidecar.cjs",
        "electron-builder.yml effective configuration changed",
        "publish: null",
        "Release build manifest Desktop archive input hash is stale",
        "Release build manifest legal metadata hashes are stale",
        "Release SBOM license normalization is stale",
        "Windows release toolchain lock changed without an audited verifier update",
        "Installed NSIS toolset implementation differs from the lock",
        "Installed 7-Zip toolset implementation differs from the lock",
    ):
        assert required in inputs
    for required in (
        "Packaged sidecar bundle differs from the verified release input",
        "app.asar contains an unexpected path",
        "app.asar contains forbidden material",
        "Packaged app manifest exposes build-only field",
        "app.asar file set differs from the verified release inputs",
        "app.asar content differs from the verified release input",
        "RunAsNode is Disabled",
        "EnableEmbeddedAsarIntegrityValidation is Enabled",
        "OnlyLoadAppFromAsar is Enabled",
        "GrantFileProtocolExtraPrivileges is Disabled",
        "verifyEmbeddedWindowsIcons",
        "Packaged sidecar PE payload is not bound to the build manifest",
        "Packaged Desktop archive is not bound to the build manifest",
        "ASAR physical length does not exactly match packed payload",
        "ASAR packed payload ranges are not contiguous",
        "ASAR physical envelope contains a symbolic link",
        "--verify-asar-envelope-only",
        "verifyElectronRuntimeFromArchive",
        "Unpacked release file set differs from the pinned runtime and verified inputs",
        "windows-toolchain-lock.json",
    ):
        assert required in unpacked
    for required in (
        "Pinned Electron archive contains an unsafe path",
        "Pinned Electron archive contains a case-insensitive duplicate",
        "Packaged Electron runtime differs from the pinned archive",
        "LICENSE.electron.txt",
        "LICENSES.chromium.html",
        "resources/default_app.asar",
        "runtimeInventorySha256",
    ):
        assert required in electron_runtime
    for required in (
        "planes !== 1",
        "bitsPerPixel !== 32",
        "ICO PNG frame has an unexpected format",
        "ICO PNG chunk CRC is invalid",
        "ICO PNG frame is missing IEND",
        "ICO DIB frame has an unexpected format",
        "ExtractAssociatedIcon",
        "IconGroupEntry.fromEntries",
        "matchingGroups",
        "ignoreCert: true",
        "Embedded application icon differs from the verified source",
    ):
        assert required in icon_verifier
    for required in (
        "advertised-mcp-config.json",
        'JSON.stringify(entry.args) !== \'["mcp"]\'',
        "smoke-frozen-mcp.py",
    ):
        assert required in sidecar_smoke


def test_windows_installer_verification_binds_identity_structure_and_payload():
    installer = (ROOT / "scripts/nsis-installer-verifier.cjs").read_text(
        encoding="utf-8"
    )
    windows = (ROOT / "scripts/verify-windows-package.cjs").read_text(
        encoding="utf-8"
    )
    integrity = (ROOT / "scripts/release-integrity.cjs").read_text(encoding="utf-8")
    scripts = _json("package.json")["scripts"]

    for required in (
        "Windows installer has an invalid NSIS signature",
        "Windows installer NSIS physical size does not match its PE payload",
        "portableExecutablePayload(installerPath, unsignedPayloadBytes)",
        'Type = 7z',
        "NSIS embedded 7z physical range is inconsistent",
        "NSIS application archive did not pass the pinned 7-Zip integrity test",
        "NSIS embedded application payload differs from win-unpacked",
        "embeddedPayloadBundleSha256",
    ):
        assert required in installer
    for required in (
        "verifyNsisInstallerPayload",
        "Windows release version identity changed",
        "releaseQualified",
        "development-only-unsigned-artifact",
        "not qualified for publication",
    ):
        assert required in windows
    for required in (
        "Invalid PE WIN_CERTIFICATE table alignment",
        "Invalid PE WIN_CERTIFICATE entry",
        "Invalid PE WIN_CERTIFICATE padding",
        "PE must contain exactly one WIN_CERTIFICATE entry",
    ):
        assert required in integrity
    assert "tests/electron/release_integrity.test.cjs" in scripts["test:electron-process"]
