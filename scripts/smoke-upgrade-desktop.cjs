"use strict";

const { spawnSync } = require("node:child_process");
const asar = require("@electron/asar");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const yaml = require("js-yaml");
const { bundleSha256, collectBundle, hashFile, portableExecutablePayload } = require("./release-integrity.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const releaseRoot = path.join(root, ".release");
const manifest = require(path.join(root, "package.json"));
const builder = yaml.load(fs.readFileSync(path.join(root, "electron-builder.yml"), "utf8"));
const currentAppId = builder?.appId;
const currentVersion = manifest.version;
const currentUserDataName = manifest.productName ?? manifest.name;
const currentInstaller = path.join(releaseRoot, "electron", `WebFA-Setup-${currentVersion}-x64.exe`);
const currentUnpackedRoot = path.join(releaseRoot, "electron", "win-unpacked");
const currentVerifier = path.join(root, "scripts", "verify-windows-package.cjs");
const runtimeSmoke = path.join(root, "scripts", "smoke-unpacked-desktop.cjs");
const ownedRoot = path.join(releaseRoot, "upgrade-smoke");
const installRoot = path.join(ownedRoot, "WebFA");
const markerPath = path.join(ownedRoot, ".webfa-upgrade-smoke-owned.json");
const upgradeUserDataRoot = path.join(ownedRoot, "user-data");
const profileSentinelPath = path.join(
  upgradeUserDataRoot,
  "profiles",
  "default",
  "maintenance",
  "upgrade-smoke-sentinel.json",
);
const installedExecutable = path.join(installRoot, "WebFA.exe");
const uninstaller = path.join(installRoot, "Uninstall WebFA.exe");
const uninstallerIcon = path.join(installRoot, "uninstallerIcon.ico");
const sourceIcon = path.join(root, "packaging", "webfa.ico");
const updaterCacheRoot = path.join(
  process.env.LOCALAPPDATA ?? (() => { throw new Error("LOCALAPPDATA is unavailable"); })(),
  `${manifest.name}-updater`,
);
const installerGuid = typeof currentAppId === "string"
  ? uuidV5(currentAppId, "50e065bc-3134-11e6-9bab-38c9862bdaf3")
  : "";

const stateScript = String.raw`
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$guid = $env:WEBFA_INSTALL_GUID
$installRoot = [IO.Path]::GetFullPath($env:WEBFA_INSTALL_ROOT)
$uninstallRoots = @(
  @{ hive = "HKCU"; path = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" },
  @{ hive = "HKLM"; path = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall" },
  @{ hive = "HKLM32"; path = "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall" }
)
[array]$uninstallEntries = foreach ($root in $uninstallRoots) {
  if (-not (Test-Path -LiteralPath $root.path)) { continue }
  Get-ChildItem -LiteralPath $root.path -ErrorAction Stop | ForEach-Object {
    $value = Get-ItemProperty -LiteralPath $_.PSPath -ErrorAction Stop
    if ($_.PSChildName -eq $guid -or $value.DisplayName -like "WebFA*") {
      [pscustomobject]@{
        hive = $root.hive
        key = $_.PSChildName
        displayName = [string]$value.DisplayName
        displayVersion = [string]$value.DisplayVersion
        publisher = [string]$value.Publisher
        displayIcon = [string]$value.DisplayIcon
        uninstallString = [string]$value.UninstallString
        quietUninstallString = [string]$value.QuietUninstallString
        estimatedSize = [long]$value.EstimatedSize
        noModify = [int]$value.NoModify
        noRepair = [int]$value.NoRepair
      }
    }
  }
}

$installKeySpecs = @(
  @{ hive = "HKCU"; path = "HKCU:\Software\$guid" },
  @{ hive = "HKLM"; path = "HKLM:\Software\$guid" }
)
[array]$installKeys = foreach ($spec in $installKeySpecs) {
  if (Test-Path -LiteralPath $spec.path) {
    $value = Get-ItemProperty -LiteralPath $spec.path -ErrorAction Stop
    [pscustomobject]@{
      hive = $spec.hive
      path = $spec.path
      installLocation = [string]$value.InstallLocation
    }
  }
}

$shortcutSpecs = @(
  @{ scope = "user-desktop"; path = Join-Path ([Environment]::GetFolderPath("Desktop")) "WebFA.lnk" },
  @{ scope = "common-desktop"; path = Join-Path ([Environment]::GetFolderPath("CommonDesktopDirectory")) "WebFA.lnk" },
  @{ scope = "user-start-menu"; path = Join-Path ([Environment]::GetFolderPath("Programs")) "WebFA.lnk" },
  @{ scope = "common-start-menu"; path = Join-Path ([Environment]::GetFolderPath("CommonPrograms")) "WebFA.lnk" }
)
$shell = New-Object -ComObject WScript.Shell
[array]$shortcuts = foreach ($spec in $shortcutSpecs) {
  if ($spec.path -and (Test-Path -LiteralPath $spec.path)) {
    $shortcut = $shell.CreateShortcut($spec.path)
    [pscustomobject]@{
      scope = $spec.scope
      path = $spec.path
      targetPath = [string]$shortcut.TargetPath
      arguments = [string]$shortcut.Arguments
      workingDirectory = [string]$shortcut.WorkingDirectory
      iconLocation = [string]$shortcut.IconLocation
    }
  }
}

[array]$processes = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
  $_.Name -ieq "WebFA.exe"
} | ForEach-Object {
  [pscustomobject]@{
    processId = [int]$_.ProcessId
    executablePath = [string]$_.ExecutablePath
    commandLine = [string]$_.CommandLine
  }
}

$uninstallerInfo = $null
$uninstallerPath = Join-Path $installRoot "Uninstall WebFA.exe"
if (Test-Path -LiteralPath $uninstallerPath -PathType Leaf) {
  $securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
  Import-Module -Name $securityModule -Force -ErrorAction Stop
  $signature = Get-AuthenticodeSignature -LiteralPath $uninstallerPath
  $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($uninstallerPath)
  $uninstallerInfo = [pscustomobject]@{
    signatureStatus = $signature.Status.ToString()
    signerThumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
    timestampThumbprint = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Thumbprint } else { $null }
    productName = [string]$version.ProductName
    productVersion = [string]$version.ProductVersion
    fileVersion = [string]$version.FileVersion
    fileDescription = [string]$version.FileDescription
    companyName = [string]$version.CompanyName
  }
}

[pscustomobject]@{
  installDirectoryExists = Test-Path -LiteralPath $installRoot -PathType Container
  uninstallEntries = @($uninstallEntries)
  installKeys = @($installKeys)
  shortcuts = @($shortcuts)
  processes = @($processes)
  uninstaller = $uninstallerInfo
} | ConvertTo-Json -Depth 8 -Compress
`;

const installerMetadataScript = String.raw`
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$securityModule = Join-Path $PSHOME "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
Import-Module -Name $securityModule -Force -ErrorAction Stop
$target = $env:WEBFA_INSTALLER_TARGET
$signature = Get-AuthenticodeSignature -LiteralPath $target
$version = [Diagnostics.FileVersionInfo]::GetVersionInfo($target)
[pscustomobject]@{
  signatureStatus = $signature.Status.ToString()
  signerSubject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
  signerThumbprint = if ($signature.SignerCertificate) { $signature.SignerCertificate.Thumbprint } else { $null }
  timestampThumbprint = if ($signature.TimeStamperCertificate) { $signature.TimeStamperCertificate.Thumbprint } else { $null }
  productName = [string]$version.ProductName
  productVersion = [string]$version.ProductVersion
  fileVersion = [string]$version.FileVersion
  fileDescription = [string]$version.FileDescription
  companyName = [string]$version.CompanyName
} | ConvertTo-Json -Compress
`;

function parseSemver(value) {
  if (typeof value !== "string") throw new Error("Release version must be a string");
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.exec(value);
  if (!match) throw new Error(`Release version must be exact major.minor.patch: ${value}`);
  return match.slice(1).map(Number);
}

function compareSemver(left, right) {
  const a = parseSemver(left);
  const b = parseSemver(right);
  for (let index = 0; index < 3; index += 1) {
    if (a[index] !== b[index]) return a[index] < b[index] ? -1 : 1;
  }
  return 0;
}

function validateUpgradeIdentity({ previousVersion, nextVersion, previousAppId, nextAppId }) {
  if (compareSemver(previousVersion, nextVersion) >= 0) {
    throw new Error(`Previous installer must be older than ${nextVersion}; got ${previousVersion}`);
  }
  if (
    typeof previousAppId !== "string" ||
    typeof nextAppId !== "string" ||
    !previousAppId ||
    previousAppId !== nextAppId
  ) {
    throw new Error(
      `Cross-version in-place upgrade requires the same stable appId; previous=${previousAppId}, current=${nextAppId}`,
    );
  }
  return { previousVersion, nextVersion, appId: nextAppId };
}

function parseArguments(argv) {
  const result = {
    currentMode: "unsigned",
    previousMode: "signed",
    previousAppId: currentAppId,
  };
  for (let index = 0; index < argv.length; index += 1) {
    const name = argv[index];
    if (name === "--help") return { help: true };
    if (!new Set([
      "--previous",
      "--previous-version",
      "--previous-app-id",
      "--previous-mode",
      "--previous-signer-sha1",
      "--current-mode",
    ]).has(name)) {
      throw new Error(`Unknown upgrade-smoke option: ${name}`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${name} requires a value`);
    index += 1;
    const key = {
      "--previous": "previousInstaller",
      "--previous-version": "previousVersion",
      "--previous-app-id": "previousAppId",
      "--previous-mode": "previousMode",
      "--previous-signer-sha1": "previousSignerSha1",
      "--current-mode": "currentMode",
    }[name];
    result[key] = value;
  }
  if (!result.previousInstaller || !result.previousVersion) {
    throw new Error("--previous and --previous-version are required");
  }
  for (const [name, value] of [["--previous-mode", result.previousMode], ["--current-mode", result.currentMode]]) {
    if (!new Set(["signed", "unsigned"]).has(value)) throw new Error(`${name} must be signed or unsigned`);
  }
  if (result.previousMode === "signed") {
    const thumbprint = normalizeThumbprint(result.previousSignerSha1);
    if (!thumbprint) throw new Error("Signed previous installers require --previous-signer-sha1");
    result.previousSignerSha1 = thumbprint;
  } else if (result.previousSignerSha1) {
    throw new Error("--previous-signer-sha1 is incompatible with --previous-mode unsigned");
  }
  return result;
}

function usage() {
  return [
    "Usage (Windows only):",
    "  node scripts/smoke-upgrade-desktop.cjs --previous <installer.exe> --previous-version <x.y.z>",
    "    [--previous-app-id <id>] [--previous-mode signed|unsigned]",
    "    [--previous-signer-sha1 <40-hex>] [--current-mode signed|unsigned]",
  ].join("\n");
}

function normalizeThumbprint(value) {
  if (typeof value !== "string") return undefined;
  const normalized = value.replaceAll(" ", "").toUpperCase();
  return /^[A-F0-9]{40}$/.test(normalized) ? normalized : undefined;
}

function uuidV5(value, namespace) {
  const namespaceBytes = Buffer.from(namespace.replaceAll("-", ""), "hex");
  if (namespaceBytes.length !== 16) throw new Error(`Invalid UUID namespace: ${namespace}`);
  const bytes = crypto.createHash("sha1").update(namespaceBytes).update(value, "utf8").digest().subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function sameWindowsPath(left, right) {
  return typeof left === "string" && typeof right === "string" &&
    path.win32.normalize(left).toLowerCase() === path.win32.normalize(right).toLowerCase();
}

function assertOwnedPath(target, parent) {
  const resolvedTarget = path.resolve(target);
  const resolvedParent = path.resolve(parent);
  const relation = path.relative(resolvedParent, resolvedTarget);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Upgrade-smoke path is outside its owned parent: ${resolvedTarget}`);
  }
  if (fs.existsSync(resolvedTarget) && fs.lstatSync(resolvedTarget).isSymbolicLink()) {
    throw new Error(`Upgrade-smoke path must not be a link: ${resolvedTarget}`);
  }
}

function requireRegularFile(target, label) {
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 1024 * 1024) {
    throw new Error(`${label} is not a substantial regular file: ${target}`);
  }
  portableExecutablePayload(target);
}

function runFile(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? root,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    timeout: options.timeoutMs ?? 180_000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with ${result.status}: ${(result.stderr || result.stdout || "").trim()}`);
  }
  return result;
}

function runWindowsProcessTree(target, argumentLine) {
  const script = String.raw`
$ErrorActionPreference = "Stop"
$process = Start-Process -FilePath $env:WEBFA_PROCESS_TARGET -ArgumentList $env:WEBFA_PROCESS_ARGUMENT_LINE -WindowStyle Hidden -Wait -PassThru
[Console]::Out.Write($process.ExitCode)
`;
  const result = runFile("pwsh.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
    timeoutMs: 240_000,
    env: {
      ...process.env,
      WEBFA_PROCESS_TARGET: target,
      WEBFA_PROCESS_ARGUMENT_LINE: argumentLine,
    },
  });
  if (Number(result.stdout.trim()) !== 0) {
    throw new Error(`${path.basename(target)} process tree exited with ${result.stdout.trim()}`);
  }
}

function inspectInstallerMetadata(target) {
  const result = runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", installerMetadataScript], {
    capture: true,
    env: { ...process.env, WEBFA_INSTALLER_TARGET: target },
  });
  return JSON.parse(result.stdout);
}

function inspectUpdaterCache() {
  if (!fs.existsSync(updaterCacheRoot)) return { exists: false, files: [] };
  const stat = fs.lstatSync(updaterCacheRoot);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`WebFA updater cache is not a regular directory: ${updaterCacheRoot}`);
  }
  return { exists: true, files: collectBundle(updaterCacheRoot) };
}

function inspectState() {
  const result = runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", stateScript], {
    capture: true,
    env: {
      ...process.env,
      WEBFA_INSTALL_GUID: installerGuid,
      WEBFA_INSTALL_ROOT: installRoot,
    },
  });
  return { ...JSON.parse(result.stdout), updaterCache: inspectUpdaterCache() };
}

function isCleanState(state) {
  return !state.installDirectoryExists && !state.uninstallEntries.length && !state.installKeys.length &&
    !state.shortcuts.length && !state.processes.length && !state.updaterCache.exists;
}

function assertCleanState(state, phase) {
  if (!isCleanState(state)) throw new Error(`${phase} found WebFA state: ${JSON.stringify(state)}`);
}

function expectedShortcutScopes() {
  return new Set(["user-desktop", "user-start-menu"]);
}

function assertVersionState(state, version, expectedInstaller, phase, signatureExpectation) {
  if (!state.installDirectoryExists) throw new Error(`${phase} did not create the install directory`);
  if (state.processes.length) throw new Error(`${phase} left WebFA running: ${JSON.stringify(state.processes)}`);
  if (
    state.installKeys.length !== 1 ||
    state.installKeys[0].hive !== "HKCU" ||
    !sameWindowsPath(state.installKeys[0].installLocation, installRoot)
  ) {
    throw new Error(`${phase} install-key identity is invalid: ${JSON.stringify(state.installKeys)}`);
  }
  if (state.uninstallEntries.length !== 1) {
    throw new Error(`${phase} expected one uninstall entry: ${JSON.stringify(state.uninstallEntries)}`);
  }
  const entry = state.uninstallEntries[0];
  const expectedUninstall = `"${uninstaller}" /currentuser`;
  if (
    entry.hive !== "HKCU" ||
    entry.key !== installerGuid ||
    entry.displayName !== `WebFA ${version}` ||
    entry.displayVersion !== version ||
    entry.publisher !== manifest.author ||
    !sameWindowsPath(entry.displayIcon.split(",")[0], uninstallerIcon) ||
    entry.uninstallString !== expectedUninstall ||
    entry.quietUninstallString !== `${expectedUninstall} /S` ||
    entry.estimatedSize <= 0 ||
    entry.noModify !== 1 ||
    entry.noRepair !== 1
  ) {
    throw new Error(`${phase} uninstall identity is invalid: ${JSON.stringify(entry)}`);
  }
  const scopes = expectedShortcutScopes();
  if (state.shortcuts.length !== scopes.size) {
    throw new Error(`${phase} expected two current-user shortcuts: ${JSON.stringify(state.shortcuts)}`);
  }
  for (const shortcut of state.shortcuts) {
    if (
      !scopes.has(shortcut.scope) ||
      !sameWindowsPath(shortcut.targetPath, installedExecutable) ||
      shortcut.arguments !== "" ||
      !sameWindowsPath(shortcut.workingDirectory, installRoot) ||
      !sameWindowsPath(shortcut.iconLocation.split(",")[0], installedExecutable)
    ) {
      throw new Error(`${phase} shortcut identity is invalid: ${JSON.stringify(shortcut)}`);
    }
  }
  if (
    !state.uninstaller ||
    state.uninstaller.productName !== "WebFA" ||
    state.uninstaller.productVersion !== version ||
    state.uninstaller.fileVersion !== version ||
    state.uninstaller.companyName !== manifest.author
  ) {
    throw new Error(`${phase} uninstaller version is invalid: ${JSON.stringify(state.uninstaller)}`);
  }
  if (signatureExpectation.mode === "unsigned") {
    if (state.uninstaller.signatureStatus !== "NotSigned") {
      throw new Error(`${phase} expected an unsigned uninstaller: ${JSON.stringify(state.uninstaller)}`);
    }
  } else if (
    state.uninstaller.signatureStatus !== "Valid" ||
    state.uninstaller.signerThumbprint?.toUpperCase() !== signatureExpectation.thumbprint ||
    !state.uninstaller.timestampThumbprint
  ) {
    throw new Error(`${phase} signed uninstaller identity is invalid: ${JSON.stringify(state.uninstaller)}`);
  }
  if (
    !state.updaterCache.exists ||
    state.updaterCache.files.length !== 1 ||
    state.updaterCache.files[0].path !== "installer.exe" ||
    state.updaterCache.files[0].bytes !== fs.statSync(expectedInstaller).size ||
    state.updaterCache.files[0].sha256 !== hashFile(expectedInstaller)
  ) {
    throw new Error(`${phase} updater cache does not match its installer: ${JSON.stringify(state.updaterCache)}`);
  }
  return state;
}

async function waitFor(predicate, label, timeoutMs = 60_000, intervalMs = 250) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const value = predicate();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error(`${label} timed out${lastError ? `: ${lastError.message ?? lastError}` : ""}`);
}

async function waitForVersion(version, expectedInstaller, phase, signatureExpectation) {
  return waitFor(
    () => assertVersionState(inspectState(), version, expectedInstaller, phase, signatureExpectation),
    phase,
  );
}

async function waitForClean(phase) {
  return waitFor(() => {
    const state = inspectState();
    return isCleanState(state) ? state : false;
  }, phase);
}

function assertCurrentPayload() {
  const expected = collectBundle(currentUnpackedRoot);
  const installed = collectBundle(installRoot);
  const expectedMap = new Map(expected.map((entry) => [entry.path, entry]));
  const installedMap = new Map(installed.map((entry) => [entry.path, entry]));
  for (const entry of expected) {
    const actual = installedMap.get(entry.path);
    if (!actual || actual.bytes !== entry.bytes || actual.sha256 !== entry.sha256) {
      throw new Error(`Upgraded payload differs from current win-unpacked: ${entry.path}`);
    }
  }
  const extras = installed.filter((entry) => !expectedMap.has(entry.path)).map((entry) => entry.path);
  if (JSON.stringify(extras) !== JSON.stringify(["Uninstall WebFA.exe", "uninstallerIcon.ico"])) {
    throw new Error(`Upgrade left stale or unexpected application files: ${JSON.stringify(extras)}`);
  }
  const icon = installedMap.get("uninstallerIcon.ico");
  if (!icon || icon.bytes !== fs.statSync(sourceIcon).size || icon.sha256 !== hashFile(sourceIcon)) {
    throw new Error("Upgraded uninstaller icon differs from the verified release icon");
  }
  return {
    sourceFiles: expected.length,
    installedFiles: installed.length,
    sourceBundleSha256: bundleSha256(expected),
    installedBundleSha256: bundleSha256(installed),
    uninstallerSha256: hashFile(uninstaller),
  };
}

function inspectInstalledArchiveIdentity(expectedVersion) {
  const archive = path.join(installRoot, "resources", "app.asar");
  const stat = fs.lstatSync(archive);
  if (!stat.isFile() || stat.isSymbolicLink()) {
    throw new Error(`Installed app.asar identity is invalid: ${archive}`);
  }
  const packagedManifest = JSON.parse(asar.extractFile(archive, "package.json").toString("utf8"));
  if (packagedManifest.version !== expectedVersion) {
    throw new Error(`Installed app.asar version differs from ${expectedVersion}: ${packagedManifest.version}`);
  }
  const packagedUserDataName = packagedManifest.productName ?? packagedManifest.name;
  if (packagedUserDataName !== currentUserDataName) {
    throw new Error(
      `Previous packaged app name changed the default user-data root; previous=${packagedUserDataName}, current=${currentUserDataName}`,
    );
  }
  return {
    name: packagedManifest.name,
    productName: packagedManifest.productName ?? null,
    userDataName: packagedUserDataName,
    version: packagedManifest.version,
    archiveBytes: stat.size,
    archiveSha256: hashFile(archive),
  };
}

function runInstalledRuntimeSmoke(expectedVersion) {
  const result = runFile(process.execPath, [
    runtimeSmoke,
    installRoot,
    "--expected-version",
    expectedVersion,
    "--reuse-upgrade-user-data",
    upgradeUserDataRoot,
  ], { capture: true, timeoutMs: 180_000 });
  const evidence = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  if (
    evidence.status !== "pass" ||
    evidence.version !== expectedVersion ||
    evidence.runtimeOwnership !== "desktop" ||
    evidence.reusedUpgradeUserData !== true ||
    !sameWindowsPath(evidence.userDataPath, upgradeUserDataRoot) ||
    evidence.cleanup?.runtimeState !== "stopped" ||
    evidence.cleanup?.rendererServerStopped !== true
  ) {
    throw new Error(`Installed ${expectedVersion} Desktop runtime smoke failed: ${JSON.stringify(evidence)}`);
  }
  return evidence;
}

function seedProfileSentinel(request) {
  if (fs.existsSync(profileSentinelPath)) {
    throw new Error(`Upgrade profile sentinel already exists: ${profileSentinelPath}`);
  }
  const payload = Buffer.from(`${JSON.stringify({
    schema: 1,
    profileId: "default",
    previousVersion: request.previousVersion,
    nextVersion: currentVersion,
    nonce: crypto.randomBytes(32).toString("hex"),
  })}\n`, "utf8");
  fs.mkdirSync(path.dirname(profileSentinelPath), { recursive: true });
  fs.writeFileSync(profileSentinelPath, payload, { flag: "wx", mode: 0o600 });
  return {
    path: path.relative(upgradeUserDataRoot, profileSentinelPath).replaceAll(path.sep, "/"),
    bytes: payload.length,
    sha256: hashFile(profileSentinelPath),
  };
}

function assertProfileSentinel(expected, phase) {
  if (!fs.existsSync(profileSentinelPath)) throw new Error(`${phase} removed Profile data`);
  const stat = fs.lstatSync(profileSentinelPath);
  if (
    !stat.isFile() ||
    stat.isSymbolicLink() ||
    stat.size !== expected.bytes ||
    hashFile(profileSentinelPath) !== expected.sha256
  ) {
    throw new Error(`${phase} changed the Profile preservation sentinel`);
  }
}

function removeUpgradeUserData() {
  if (!fs.existsSync(upgradeUserDataRoot)) return;
  assertOwnedPath(upgradeUserDataRoot, ownedRoot);
  fs.rmSync(upgradeUserDataRoot, { recursive: true, force: true });
}

function writeMarker(request) {
  fs.mkdirSync(ownedRoot, { recursive: true });
  fs.writeFileSync(markerPath, `${JSON.stringify({
    schema: 1,
    appId: currentAppId,
    installerGuid,
    installRoot,
    previousInstaller: request.previousInstaller,
    previousInstallerSha256: hashFile(request.previousInstaller),
    currentInstaller,
    currentInstallerSha256: hashFile(currentInstaller),
    upgradeUserDataRoot,
  })}\n`, { encoding: "utf8", mode: 0o600, flag: "wx" });
}

function hasValidMarker() {
  if (!fs.existsSync(markerPath)) return false;
  const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
  return marker.schema === 1 && marker.appId === currentAppId && marker.installerGuid === installerGuid &&
    sameWindowsPath(marker.installRoot, installRoot) && sameWindowsPath(marker.currentInstaller, currentInstaller) &&
    sameWindowsPath(marker.upgradeUserDataRoot, upgradeUserDataRoot);
}

function removeExactUpdaterCache(allowedInstallers) {
  const cache = inspectUpdaterCache();
  if (!cache.exists) return;
  if (cache.files.length !== 1 || cache.files[0].path !== "installer.exe") {
    throw new Error(`Refusing to remove an unexpected updater cache: ${JSON.stringify(cache)}`);
  }
  const allowedHashes = new Set(allowedInstallers.map(hashFile));
  if (!allowedHashes.has(cache.files[0].sha256)) {
    throw new Error(`Refusing to remove an unowned updater cache: ${JSON.stringify(cache)}`);
  }
  fs.rmSync(updaterCacheRoot, { recursive: true, force: true });
}

function terminateOwnedProcesses() {
  if (!hasValidMarker()) throw new Error("Refusing to terminate processes without a valid upgrade-smoke marker");
  const script = String.raw`
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($env:WEBFA_OWNED_INSTALL_ROOT).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)
} | Sort-Object ProcessId -Descending | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }
`;
  runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
    env: { ...process.env, WEBFA_OWNED_INSTALL_ROOT: installRoot },
  });
}

async function cleanupOwned(request) {
  if (!fs.existsSync(markerPath)) return;
  if (!hasValidMarker()) throw new Error(`Invalid upgrade-smoke ownership marker: ${markerPath}`);
  const state = inspectState();
  const ownedProcesses = state.processes.filter((item) => {
    if (!item.executablePath) return false;
    const relation = path.relative(installRoot, item.executablePath);
    return Boolean(relation) && !relation.startsWith("..") && !path.isAbsolute(relation);
  });
  if (ownedProcesses.length) terminateOwnedProcesses();
  if (fs.existsSync(uninstaller)) runWindowsProcessTree(uninstaller, "/currentuser /S");
  const remaining = inspectState();
  if (remaining.uninstallEntries.length || remaining.installKeys.length || remaining.shortcuts.length || remaining.processes.length) {
    throw new Error(`Upgrade-smoke cleanup left global WebFA state: ${JSON.stringify(remaining)}`);
  }
  removeExactUpdaterCache([request.previousInstaller, currentInstaller]);
  if (fs.existsSync(installRoot)) {
    assertOwnedPath(installRoot, ownedRoot);
    fs.rmSync(installRoot, { recursive: true, force: true });
  }
  removeUpgradeUserData();
  fs.rmSync(markerPath, { force: true });
  if (fs.existsSync(ownedRoot) && fs.readdirSync(ownedRoot).length === 0) fs.rmdirSync(ownedRoot);
}

async function main(argv = process.argv.slice(2)) {
  const request = parseArguments(argv);
  if (request.help) {
    process.stdout.write(`${usage()}\n`);
    return;
  }
  if (process.platform !== "win32") throw new Error(`Upgrade smoke is Windows-only\n${usage()}`);
  if (typeof currentAppId !== "string" || !currentAppId) throw new Error("electron-builder.yml must define appId");
  validateUpgradeIdentity({
    previousVersion: request.previousVersion,
    nextVersion: currentVersion,
    previousAppId: request.previousAppId,
    nextAppId: currentAppId,
  });
  request.previousInstaller = fs.realpathSync(path.resolve(root, request.previousInstaller));
  requireRegularFile(request.previousInstaller, "Previous installer");
  requireRegularFile(currentInstaller, "Current installer");
  if (sameWindowsPath(request.previousInstaller, currentInstaller) || hashFile(request.previousInstaller) === hashFile(currentInstaller)) {
    throw new Error("Previous and current installers must be different artifacts");
  }
  requireRegularFile(path.join(currentUnpackedRoot, "WebFA.exe"), "Current unpacked Desktop");
  assertOwnedPath(ownedRoot, releaseRoot);
  assertOwnedPath(installRoot, ownedRoot);

  const previousMetadata = inspectInstallerMetadata(request.previousInstaller);
  if (
    previousMetadata.productName !== "WebFA" ||
    previousMetadata.productVersion !== request.previousVersion ||
    previousMetadata.fileVersion !== request.previousVersion
  ) {
    throw new Error(`Previous installer version identity is invalid: ${JSON.stringify(previousMetadata)}`);
  }
  if (request.previousMode === "unsigned" && previousMetadata.signatureStatus !== "NotSigned") {
    throw new Error(`Expected an unsigned previous installer: ${JSON.stringify(previousMetadata)}`);
  }
  if (
    request.previousMode === "signed" &&
    (
      previousMetadata.signatureStatus !== "Valid" ||
      previousMetadata.signerThumbprint?.toUpperCase() !== request.previousSignerSha1 ||
      !previousMetadata.timestampThumbprint
    )
  ) {
    throw new Error(`Previous installer signature identity is invalid: ${JSON.stringify(previousMetadata)}`);
  }

  runFile(process.execPath, [currentVerifier, request.currentMode], { capture: true, timeoutMs: 180_000 });
  const currentSignatureExpectation = request.currentMode === "signed"
    ? { mode: "signed", thumbprint: normalizeThumbprint(process.env.WEBFA_SIGNING_CERT_SHA1) }
    : { mode: "unsigned" };
  if (request.currentMode === "signed" && !currentSignatureExpectation.thumbprint) {
    throw new Error("Signed current installers require WEBFA_SIGNING_CERT_SHA1");
  }
  const previousSignatureExpectation = request.previousMode === "signed"
    ? { mode: "signed", thumbprint: request.previousSignerSha1 }
    : { mode: "unsigned" };
  assertCleanState(inspectState(), "Upgrade preflight");
  if (fs.existsSync(ownedRoot)) {
    throw new Error(`Upgrade-smoke owned root already exists without installed state: ${ownedRoot}`);
  }

  let started = false;
  let primaryError;
  try {
    writeMarker(request);
    started = true;
    runWindowsProcessTree(request.previousInstaller, `/S /D=${installRoot}`);
    const previousState = await waitForVersion(
      request.previousVersion,
      request.previousInstaller,
      `Previous ${request.previousVersion} install`,
      previousSignatureExpectation,
    );
    const previousPayload = collectBundle(installRoot);
    const previousArchive = inspectInstalledArchiveIdentity(request.previousVersion);
    const previousRuntime = runInstalledRuntimeSmoke(request.previousVersion);
    const profileSentinel = seedProfileSentinel(request);
    const previousUserData = collectBundle(upgradeUserDataRoot);

    runWindowsProcessTree(currentInstaller, `/S /D=${installRoot}`);
    const currentState = await waitForVersion(
      currentVersion,
      currentInstaller,
      `Upgrade to ${currentVersion}`,
      currentSignatureExpectation,
    );
    const currentPayload = assertCurrentPayload();
    assertProfileSentinel(profileSentinel, "Current installer upgrade");
    const runtime = runInstalledRuntimeSmoke(currentVersion);
    assertProfileSentinel(profileSentinel, "Current Runtime startup");
    const userDataBeforeUninstall = collectBundle(upgradeUserDataRoot);

    runWindowsProcessTree(uninstaller, "/currentuser /S");
    await waitForClean("Upgrade uninstall cleanup");
    assertProfileSentinel(profileSentinel, "Current uninstaller");
    const userDataAfterUninstall = collectBundle(upgradeUserDataRoot);
    if (bundleSha256(userDataAfterUninstall) !== bundleSha256(userDataBeforeUninstall)) {
      throw new Error("Current uninstaller changed preserved WebFA user data");
    }
    removeUpgradeUserData();
    started = false;
    fs.rmSync(markerPath, { force: true });
    if (fs.existsSync(ownedRoot) && fs.readdirSync(ownedRoot).length === 0) fs.rmdirSync(ownedRoot);

    process.stdout.write(`${JSON.stringify({
      status: "pass",
      releaseQualified: request.previousMode === "signed" && request.currentMode === "signed",
      appId: currentAppId,
      installerGuid,
      previous: {
        version: request.previousVersion,
        installer: request.previousInstaller,
        bytes: fs.statSync(request.previousInstaller).size,
        sha256: hashFile(request.previousInstaller),
        signature: previousMetadata,
        packagedIdentity: previousArchive,
        installedFiles: previousPayload.length,
        installedBundleSha256: bundleSha256(previousPayload),
        registryHive: previousState.uninstallEntries[0].hive,
        runtimeOwnership: previousRuntime.runtimeOwnership,
      },
      current: {
        version: currentVersion,
        installer: currentInstaller,
        bytes: fs.statSync(currentInstaller).size,
        sha256: hashFile(currentInstaller),
        payload: currentPayload,
        registryHive: currentState.uninstallEntries[0].hive,
        runtimeOwnership: runtime.runtimeOwnership,
        runtimeCleanup: runtime.cleanup,
      },
      upgrade: {
        inPlace: true,
        staleApplicationFiles: 0,
        registryIdentityStable: true,
        shortcutIdentityStable: true,
        defaultUserDataNameStable: true,
        profileDataPreserved: true,
        profileSentinel,
        previousUserDataFiles: previousUserData.length,
        currentUserDataFiles: userDataBeforeUninstall.length,
      },
      uninstall: {
        installDirectoryRemoved: true,
        registryRemoved: true,
        shortcutsRemoved: true,
        updaterCacheRemoved: true,
        profileDataPreserved: true,
      },
    })}\n`);
  } catch (error) {
    primaryError = error;
    throw error;
  } finally {
    if (started) {
      try {
        await cleanupOwned(request);
      } catch (cleanupError) {
        if (primaryError) {
          process.stderr.write(`Upgrade-smoke cleanup also failed: ${cleanupError.stack ?? cleanupError}\n`);
        } else {
          throw cleanupError;
        }
      }
    }
  }
}

module.exports = {
  compareSemver,
  parseArguments,
  parseSemver,
  validateUpgradeIdentity,
};

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack ?? error}\n${usage()}\n`);
    process.exitCode = 1;
  });
}
