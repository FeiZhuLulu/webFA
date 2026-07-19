const { spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const yaml = require("js-yaml");
const {
  bundleSha256,
  collectBundle,
  hashFile,
} = require("./release-integrity.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const mode = process.argv[2];
const cleanupOnly = process.argv.includes("--cleanup-only");
if (process.platform !== "win32" || !new Set(["signed", "unsigned"]).has(mode)) {
  throw new Error(
    "Usage (Windows only): node scripts/smoke-installed-desktop.cjs signed|unsigned [--cleanup-only]",
  );
}

const sourceManifest = require(path.join(root, "package.json"));
const builderConfig = yaml.load(fs.readFileSync(path.join(root, "electron-builder.yml"), "utf8"));
const appId = builderConfig?.appId;
if (typeof appId !== "string" || !appId) throw new Error("electron-builder.yml must define appId");

const installerGuid = uuidV5(appId, "50e065bc-3134-11e6-9bab-38c9862bdaf3");
const releaseRoot = path.join(root, ".release");
const electronReleaseRoot = path.join(releaseRoot, "electron");
const installer = path.join(
  electronReleaseRoot,
  `WebFA-Setup-${sourceManifest.version}-x64.exe`,
);
const unpackedRoot = path.join(electronReleaseRoot, "win-unpacked");
const ownedRoot = path.join(releaseRoot, "installed-smoke");
const installRoot = path.join(ownedRoot, "WebFA");
const ownershipMarker = path.join(ownedRoot, ".webfa-installed-smoke-owned.json");
const installedExecutable = path.join(installRoot, "WebFA.exe");
const uninstaller = path.join(installRoot, "Uninstall WebFA.exe");
const uninstallerIcon = path.join(installRoot, "uninstallerIcon.ico");
const sourceIcon = path.join(root, "packaging", "webfa.ico");
const updaterCacheRoot = path.join(
  process.env.LOCALAPPDATA ?? (() => { throw new Error("LOCALAPPDATA is unavailable"); })(),
  `${sourceManifest.name}-updater`,
);
const updaterCachedInstaller = path.join(updaterCacheRoot, "installer.exe");
const minimumTempFreeBytes = 4 * 1024 * 1024 * 1024;
const userDesktopShortcut = path.join(folderPath("Desktop"), "WebFA.lnk");
const userStartMenuShortcut = path.join(folderPath("Programs"), "WebFA.lnk");

for (const candidate of [installer, unpackedRoot, sourceIcon]) requireRegularPath(candidate);
assertOwnedDirectory(ownedRoot, releaseRoot);
assertOwnedDirectory(installRoot, ownedRoot);

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
  $_.Name -ieq "WebFA.exe" -or
  ($_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath) -eq (Join-Path $installRoot "WebFA.exe"))
} | ForEach-Object {
  [pscustomobject]@{
    processId = [int]$_.ProcessId
    name = [string]$_.Name
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
    signerSubject = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
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

function uuidV5(value, namespace) {
  const namespaceBytes = Buffer.from(namespace.replaceAll("-", ""), "hex");
  if (namespaceBytes.length !== 16) throw new Error(`Invalid UUID namespace: ${namespace}`);
  const bytes = crypto.createHash("sha1")
    .update(namespaceBytes)
    .update(value, "utf8")
    .digest()
    .subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function folderPath(name) {
  const script = `[Console]::Out.Write([Environment]::GetFolderPath("${name}"))`;
  const value = runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
  }).stdout.trim();
  if (!value) throw new Error(`Windows known folder is unavailable: ${name}`);
  return value;
}

function requireRegularPath(target) {
  const stat = fs.lstatSync(target);
  if (stat.isSymbolicLink() || (!stat.isFile() && !stat.isDirectory())) {
    throw new Error(`Invalid installed-smoke input: ${target}`);
  }
}

function assertOwnedDirectory(target, parent) {
  const resolvedTarget = path.resolve(target);
  const resolvedParent = path.resolve(parent);
  const relation = path.relative(resolvedParent, resolvedTarget);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Installed-smoke path is outside its owned parent: ${resolvedTarget}`);
  }
  if (fs.existsSync(resolvedTarget) && fs.lstatSync(resolvedTarget).isSymbolicLink()) {
    throw new Error(`Installed-smoke path must not be a link: ${resolvedTarget}`);
  }
}

function sameWindowsPath(left, right) {
  return path.win32.normalize(left).toLowerCase() === path.win32.normalize(right).toLowerCase();
}

function runFile(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    timeout: options.timeoutMs ?? 120_000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(
      `${path.basename(command)} exited with status ${result.status}: ${(result.stderr ?? result.stdout ?? "").trim()}`,
    );
  }
  return result;
}

function inspectState() {
  const result = runFile(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", stateScript],
    {
      capture: true,
      env: {
        ...process.env,
        WEBFA_INSTALL_GUID: installerGuid,
        WEBFA_INSTALL_ROOT: installRoot,
      },
    },
  );
  return {
    ...JSON.parse(result.stdout),
    updaterCache: inspectUpdaterCache(),
  };
}

function inspectUpdaterCache() {
  if (!fs.existsSync(updaterCacheRoot)) return { exists: false, files: [] };
  const stat = fs.lstatSync(updaterCacheRoot);
  if (!stat.isDirectory() || stat.isSymbolicLink()) {
    throw new Error(`WebFA updater cache is not a regular directory: ${updaterCacheRoot}`);
  }
  return { exists: true, files: collectBundle(updaterCacheRoot) };
}

function assertCleanState(state, phase) {
  const dirty =
    state.installDirectoryExists ||
    state.uninstallEntries.length ||
    state.installKeys.length ||
    state.shortcuts.length ||
    state.processes.length ||
    state.updaterCache.exists;
  if (dirty) throw new Error(`${phase} left installed WebFA state: ${JSON.stringify(state)}`);
}

function assertOwnedRootEmpty() {
  if (!fs.existsSync(ownedRoot)) return;
  const entries = fs.readdirSync(ownedRoot).filter((entry) => entry !== path.basename(ownershipMarker));
  if (entries.length) {
    throw new Error(`Owned installed-smoke root is not empty: ${JSON.stringify(entries)}`);
  }
}

function invokeInstaller() {
  runWindowsProcessTree(installer, `/S /D=${installRoot}`);
}

function runWindowsProcessTree(target, argumentLine) {
  const script = String.raw`
$ErrorActionPreference = "Stop"
$process = Start-Process -FilePath $env:WEBFA_PROCESS_TARGET -ArgumentList $env:WEBFA_PROCESS_ARGUMENT_LINE -WindowStyle Hidden -Wait -PassThru
[Console]::Out.Write($process.ExitCode)
`;
  let result;
  try {
    result = runFile(
      "pwsh.exe",
      ["-NoProfile", "-NonInteractive", "-Command", script],
      {
        capture: true,
        timeoutMs: 180_000,
        env: {
          ...process.env,
          WEBFA_PROCESS_TARGET: target,
          WEBFA_PROCESS_ARGUMENT_LINE: argumentLine,
        },
      },
    );
  } catch (error) {
    if (error?.code === "ENOENT") {
      throw new Error("Installed Desktop lifecycle smoke requires PowerShell 7 (pwsh.exe)");
    }
    throw error;
  }
  const exitCode = Number(result.stdout.trim());
  if (!Number.isInteger(exitCode) || exitCode !== 0) {
    throw new Error(`${path.basename(target)} process tree exited with status ${result.stdout.trim()}`);
  }
}

function writeOwnershipMarker() {
  fs.writeFileSync(
    ownershipMarker,
    `${JSON.stringify({ schema: 1, appId, installerGuid, installRoot })}\n`,
    { encoding: "utf8", mode: 0o600, flag: "wx" },
  );
}

function hasValidOwnershipMarker() {
  if (!fs.existsSync(ownershipMarker)) return false;
  const marker = JSON.parse(fs.readFileSync(ownershipMarker, "utf8"));
  return (
    marker.schema === 1 &&
    marker.appId === appId &&
    marker.installerGuid === installerGuid &&
    sameWindowsPath(marker.installRoot, installRoot)
  );
}

function removeOwnedInstallTree() {
  if (!fs.existsSync(installRoot)) return;
  if (!hasValidOwnershipMarker()) {
    throw new Error(`Refusing to remove an unmarked installed-smoke tree: ${installRoot}`);
  }
  assertOwnedDirectory(installRoot, ownedRoot);
  collectBundle(installRoot);
  fs.rmSync(installRoot, { recursive: true, force: true });
}

function recoverKnownPartialInstall(state) {
  if (
    !state.installDirectoryExists ||
    state.uninstallEntries.length ||
    state.installKeys.length ||
    state.shortcuts.length ||
    state.processes.length ||
    !fs.existsSync(installRoot)
  ) return;
  const entries = collectBundle(installRoot);
  if (
    entries.length === 1 &&
    entries[0].path === "uninstallerIcon.ico" &&
    entries[0].bytes === fs.statSync(sourceIcon).size &&
    entries[0].sha256 === hashFile(sourceIcon)
  ) {
    fs.mkdirSync(ownedRoot, { recursive: true });
    if (!fs.existsSync(ownershipMarker)) writeOwnershipMarker();
    removeOwnedInstallTree();
  }
}

function removeCandidateUpdaterCache() {
  const cache = inspectUpdaterCache();
  if (!cache.exists) return;
  if (
    cache.files.length !== 1 ||
    cache.files[0].path !== "installer.exe" ||
    cache.files[0].bytes !== fs.statSync(installer).size ||
    cache.files[0].sha256 !== hashFile(installer)
  ) {
    throw new Error(`Refusing to remove an updater cache not owned by this candidate: ${updaterCacheRoot}`);
  }
  fs.unlinkSync(updaterCachedInstaller);
  fs.rmdirSync(updaterCacheRoot);
}

function recoverCandidateUpdaterCache(state) {
  if (
    !state.updaterCache.exists ||
    state.installDirectoryExists ||
    state.uninstallEntries.length ||
    state.installKeys.length ||
    state.shortcuts.length ||
    state.processes.length
  ) return;
  removeCandidateUpdaterCache();
}

function removeOwnershipMarkerAndRoot() {
  if (fs.existsSync(ownershipMarker)) fs.unlinkSync(ownershipMarker);
  if (fs.existsSync(ownedRoot)) {
    assertOwnedRootEmpty();
    fs.rmdirSync(ownedRoot);
  }
}

function assertPeExecutable(target) {
  const bytes = fs.readFileSync(target);
  if (bytes.length < 128 * 1024 || bytes.readUInt16LE(0) !== 0x5a4d) {
    throw new Error(`Installed uninstaller is not a substantial PE executable: ${target}`);
  }
  const peOffset = bytes.readUInt32LE(0x3c);
  if (peOffset + 4 > bytes.length || bytes.readUInt32LE(peOffset) !== 0x00004550) {
    throw new Error(`Installed uninstaller has an invalid PE signature: ${target}`);
  }
}

function assertInstalledPayload() {
  const expected = collectBundle(unpackedRoot);
  const installed = collectBundle(installRoot);
  const expectedMap = new Map(expected.map((entry) => [entry.path, entry]));
  const installedMap = new Map(installed.map((entry) => [entry.path, entry]));
  for (const entry of expected) {
    const actual = installedMap.get(entry.path);
    if (!actual || actual.bytes !== entry.bytes || actual.sha256 !== entry.sha256) {
      throw new Error(`Installed payload differs from win-unpacked: ${entry.path}`);
    }
  }
  const extras = installed.filter((entry) => !expectedMap.has(entry.path));
  const extraNames = extras.map((entry) => entry.path);
  if (JSON.stringify(extraNames) !== JSON.stringify(["Uninstall WebFA.exe", "uninstallerIcon.ico"])) {
    throw new Error(`Installed payload has unexpected install-time files: ${JSON.stringify(extraNames)}`);
  }
  const iconEntry = installedMap.get("uninstallerIcon.ico");
  if (iconEntry.sha256 !== hashFile(sourceIcon) || iconEntry.bytes !== fs.statSync(sourceIcon).size) {
    throw new Error("Installed uninstaller icon differs from the release icon");
  }
  assertPeExecutable(uninstaller);
  return {
    sourceFiles: expected.length,
    installedFiles: installed.length,
    sourceBundleSha256: bundleSha256(expected),
    installedBundleSha256: bundleSha256(installed),
    uninstallerBytes: fs.statSync(uninstaller).size,
    uninstallerSha256: hashFile(uninstaller),
  };
}

function assertInstalledState(state) {
  if (!state.installDirectoryExists) throw new Error("Installer did not create the requested directory");
  if (state.processes.length) throw new Error(`Installer left WebFA running: ${JSON.stringify(state.processes)}`);
  if (
    state.installKeys.length !== 1 ||
    state.installKeys[0].hive !== "HKCU" ||
    !sameWindowsPath(state.installKeys[0].installLocation, installRoot)
  ) {
    throw new Error(`Current-user install identity is invalid: ${JSON.stringify(state.installKeys)}`);
  }
  if (state.uninstallEntries.length !== 1) {
    throw new Error(`Expected one current-user uninstall entry: ${JSON.stringify(state.uninstallEntries)}`);
  }
  const entry = state.uninstallEntries[0];
  const expectedUninstall = `"${uninstaller}" /currentuser`;
  if (
    entry.hive !== "HKCU" ||
    entry.key !== installerGuid ||
    entry.displayName !== `WebFA ${sourceManifest.version}` ||
    entry.displayVersion !== sourceManifest.version ||
    entry.publisher !== sourceManifest.author ||
    !sameWindowsPath(entry.displayIcon.split(",")[0], uninstallerIcon) ||
    entry.uninstallString !== expectedUninstall ||
    entry.quietUninstallString !== `${expectedUninstall} /S` ||
    entry.estimatedSize <= 0 ||
    entry.noModify !== 1 ||
    entry.noRepair !== 1
  ) {
    throw new Error(`Uninstall registry identity is invalid: ${JSON.stringify(entry)}`);
  }

  const expectedShortcuts = new Map([
    ["user-desktop", userDesktopShortcut],
    ["user-start-menu", userStartMenuShortcut],
  ]);
  if (state.shortcuts.length !== expectedShortcuts.size) {
    throw new Error(`Expected exactly two current-user shortcuts: ${JSON.stringify(state.shortcuts)}`);
  }
  for (const shortcut of state.shortcuts) {
    if (
      !expectedShortcuts.has(shortcut.scope) ||
      !sameWindowsPath(shortcut.path, expectedShortcuts.get(shortcut.scope)) ||
      !sameWindowsPath(shortcut.targetPath, installedExecutable) ||
      shortcut.arguments !== "" ||
      !sameWindowsPath(shortcut.workingDirectory, installRoot) ||
      !sameWindowsPath(shortcut.iconLocation.split(",")[0], installedExecutable)
    ) {
      throw new Error(`Installed shortcut identity is invalid: ${JSON.stringify(shortcut)}`);
    }
  }

  const signature = state.uninstaller;
  if (!signature) throw new Error("Installed uninstaller signature evidence is missing");
  if (
    signature.productName !== "WebFA" ||
    signature.productVersion !== sourceManifest.version ||
    signature.fileVersion !== sourceManifest.version ||
    signature.fileDescription !== sourceManifest.description ||
    signature.companyName !== sourceManifest.author
  ) {
    throw new Error(`Installed uninstaller version identity is invalid: ${JSON.stringify(signature)}`);
  }
  if (mode === "unsigned") {
    if (signature.signatureStatus !== "NotSigned") {
      throw new Error(`Unsigned install produced a signed or invalid uninstaller: ${JSON.stringify(signature)}`);
    }
  } else {
    const approved = process.env.WEBFA_SIGNING_CERT_SHA1?.replaceAll(" ", "").toUpperCase();
    if (
      !approved ||
      !/^[A-F0-9]{40}$/.test(approved) ||
      signature.signatureStatus !== "Valid" ||
      signature.signerThumbprint?.toUpperCase() !== approved ||
      !signature.timestampThumbprint
    ) {
      throw new Error(`Signed installed uninstaller failed identity verification: ${JSON.stringify(signature)}`);
    }
  }
  if (
    !state.updaterCache.exists ||
    state.updaterCache.files.length !== 1 ||
    state.updaterCache.files[0].path !== "installer.exe" ||
    state.updaterCache.files[0].bytes !== fs.statSync(installer).size ||
    state.updaterCache.files[0].sha256 !== hashFile(installer)
  ) {
    throw new Error(`Installed updater cache differs from the candidate installer: ${JSON.stringify(state.updaterCache)}`);
  }
}

function runInstalledSmoke() {
  const result = runFile(
    process.execPath,
    [path.join(root, "scripts", "smoke-unpacked-desktop.cjs"), installRoot],
    { capture: true },
  );
  const lines = result.stdout.trim().split(/\r?\n/);
  const evidence = JSON.parse(lines.at(-1));
  if (evidence.status !== "pass" || !sameWindowsPath(evidence.executable, installedExecutable)) {
    throw new Error(`Installed Desktop lifecycle smoke failed: ${result.stdout}`);
  }
  return evidence;
}

function invokeUninstaller() {
  runWindowsProcessTree(uninstaller, "/currentuser /S");
}

async function waitForInstalledReady(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  do {
    try {
      const firstPayload = assertInstalledPayload();
      const firstState = inspectState();
      assertInstalledState(firstState);
      await new Promise((resolve) => setTimeout(resolve, 500));
      const stablePayload = assertInstalledPayload();
      const stableState = inspectState();
      assertInstalledState(stableState);
      if (
        stablePayload.installedBundleSha256 === firstPayload.installedBundleSha256 &&
        stablePayload.uninstallerSha256 === firstPayload.uninstallerSha256
      ) {
        return { payload: stablePayload, state: stableState };
      }
      lastError = new Error("Installed payload changed during the stability window");
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  throw new Error(`Installed state did not become stable: ${lastError?.message ?? lastError}`);
}

async function waitForCleanState(timeoutMs = 60_000) {
  const deadline = Date.now() + timeoutMs;
  let state;
  do {
    state = inspectState();
    if (
      !state.installDirectoryExists &&
      !state.uninstallEntries.length &&
      !state.installKeys.length &&
      !state.shortcuts.length &&
      !state.processes.length &&
      !state.updaterCache.exists
    ) return state;
    await new Promise((resolve) => setTimeout(resolve, 250));
  } while (Date.now() < deadline);
  return state;
}

async function main() {
  let initialState = inspectState();
  recoverKnownPartialInstall(initialState);
  initialState = inspectState();
  recoverCandidateUpdaterCache(initialState);
  initialState = inspectState();
  assertCleanState(initialState, "Preflight");
  if (cleanupOnly) {
    removeOwnershipMarkerAndRoot();
    process.stdout.write(`${JSON.stringify({
      status: "pass",
      mode,
      cleanupOnly: true,
      candidateUpdaterCacheRemoved: true,
      installedStateClean: true,
    })}\n`);
    return;
  }
  const tempStats = fs.statfsSync(os.tmpdir(), { bigint: true });
  const tempFreeBytes = tempStats.bavail * tempStats.bsize;
  if (tempFreeBytes < BigInt(minimumTempFreeBytes)) {
    throw new Error(
      `Installed Desktop lifecycle smoke requires at least 4 GiB free on the temporary volume: ${os.tmpdir()}`,
    );
  }
  assertOwnedRootEmpty();
  fs.mkdirSync(ownedRoot, { recursive: true });
  if (fs.existsSync(ownershipMarker)) {
    if (!hasValidOwnershipMarker()) throw new Error(`Invalid installed-smoke ownership marker: ${ownershipMarker}`);
  } else {
    writeOwnershipMarker();
  }

  let installationStarted = false;
  let caughtError;
  try {
    installationStarted = true;
    invokeInstaller();
    const firstInstall = await waitForInstalledReady();
    const firstPayload = firstInstall.payload;
    const firstState = firstInstall.state;
    const firstSmoke = runInstalledSmoke();

    invokeInstaller();
    const reinstall = await waitForInstalledReady();
    const reinstallPayload = reinstall.payload;
    const reinstallState = reinstall.state;
    if (
      reinstallPayload.sourceBundleSha256 !== firstPayload.sourceBundleSha256 ||
      reinstallPayload.uninstallerSha256 !== firstPayload.uninstallerSha256 ||
      reinstallState.uninstallEntries[0].key !== firstState.uninstallEntries[0].key
    ) {
      throw new Error("Same-version reinstall changed its stable payload or installer identity");
    }
    const reinstallSmoke = runInstalledSmoke();

    invokeUninstaller();
    const finalState = await waitForCleanState();
    assertCleanState(finalState, "Uninstall");
    installationStarted = false;
    removeOwnershipMarkerAndRoot();
    process.stdout.write(`${JSON.stringify({
      status: "pass",
      mode,
      appId,
      installerGuid,
      installer,
      installRoot,
      payload: firstPayload,
      registryHive: firstState.uninstallEntries[0].hive,
      shortcutScopes: firstState.shortcuts.map((shortcut) => shortcut.scope).sort(),
      firstSmoke: {
        version: firstSmoke.version,
        runtimeOwnership: firstSmoke.runtimeOwnership,
        rendererTitle: firstSmoke.renderer.title,
        cleanup: firstSmoke.cleanup,
      },
      reinstall: {
        payloadStable: true,
        installerIdentityStable: true,
        runtimeOwnership: reinstallSmoke.runtimeOwnership,
        cleanup: reinstallSmoke.cleanup,
      },
      uninstall: {
        installDirectoryRemoved: true,
        registryRemoved: true,
        shortcutsRemoved: true,
        processesRemoved: true,
        updaterCacheRemoved: true,
      },
      temporaryVolume: {
        path: os.tmpdir(),
        freeBytesBeforeInstall: Number(tempFreeBytes),
        minimumRequiredBytes: minimumTempFreeBytes,
      },
    })}\n`);
  } catch (error) {
    caughtError = error;
    throw error;
  } finally {
    if (installationStarted) {
      let cleanupError;
      try {
        if (fs.existsSync(uninstaller)) {
          invokeUninstaller();
          const state = await waitForCleanState();
          assertCleanState(state, "Failure cleanup");
        }
        const state = inspectState();
        if (
          !state.uninstallEntries.length &&
          !state.installKeys.length &&
          !state.shortcuts.length &&
          !state.processes.length
        ) {
          removeOwnedInstallTree();
          removeCandidateUpdaterCache();
          removeOwnershipMarkerAndRoot();
        }
      } catch (error) {
        cleanupError = error;
      }
      if (cleanupError) {
        const diagnostic = `Installed-smoke cleanup also failed: ${cleanupError.stack ?? cleanupError}`;
        if (caughtError) process.stderr.write(`${diagnostic}\n`);
        else throw cleanupError;
      }
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
