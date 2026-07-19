const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");
const yaml = require("js-yaml");
const {
  bundleSha256,
  desktopArchiveInputEntries,
  sidecarPayloadEntries,
} = require("./release-integrity.cjs");
const { validateWindowsIcon } = require("./windows-icon-verifier.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const readJson = (relative) => JSON.parse(fs.readFileSync(path.join(root, relative), "utf8"));
const rootPackage = readJson("package.json");
const rendererPackage = readJson("apps/desktop/renderer/package.json");
const lock = readJson("package-lock.json");
const pythonVersionSource = fs.readFileSync(path.join(root, "apps/runtime/version.py"), "utf8");
const pythonVersion = pythonVersionSource.match(/__version__\s*=\s*["']([^"']+)["']/)?.[1];
const pythonReleaseLockRelative = "packaging/python-windows-release-lock.txt";
const pythonReleaseLockPath = path.join(root, pythonReleaseLockRelative);
const windowsToolchainLockRelative = "packaging/windows-toolchain-lock.json";
const windowsToolchainLockPath = path.join(root, windowsToolchainLockRelative);
const nsisIncludeRelative = "packaging/installer.nsh";
const nsisIncludePath = path.join(root, nsisIncludeRelative);
const windowsToolchainLock = readJson(windowsToolchainLockRelative);
const expectedWindowsToolchainLock = {
  schema_version: 1,
  electron_builder_version: "26.15.3",
  nsis: {
    toolset: "0.0.0",
    release: "nsis-3.0.4.1",
    archive: "nsis-3.0.4.1.7z",
    sha256: "9877df902530f96357d13a7a31ae2b9df67f48b11ffc9a1700a7c961574ec5fa",
  },
  nsis_resources: {
    release: "nsis-resources-3.4.1",
    archive: "nsis-resources-3.4.1.7z",
    sha256: "593a9a92ef958321293ac6a2ee61e64bf1bd543142a5bd6b3d310709cc924103",
  },
  seven_zip: {
    release: "7zip@1.0.0",
    archive: "7zip-win-x64.tar.gz",
    sha256: "be071f15bd6da2f78fe81c6ddef2009b0c4d8a51f36b780cb806c7e6df95e1b3",
  },
};

if (!pythonVersion || rootPackage.version !== pythonVersion || rendererPackage.version !== pythonVersion) {
  throw new Error(`Release versions diverge: desktop=${rootPackage.version}, renderer=${rendererPackage.version}, python=${pythonVersion}`);
}
if (lock.version !== rootPackage.version || lock.packages?.[""]?.version !== rootPackage.version) {
  throw new Error("package-lock.json root version is stale");
}
if (lock.packages?.["apps/desktop/renderer"]?.version !== rendererPackage.version) {
  throw new Error("package-lock.json renderer version is stale");
}
const pinnedPostcss = rootPackage.overrides?.["next@16.2.9"]?.postcss;
if (
  !pinnedPostcss ||
  lock.packages?.["node_modules/postcss"]?.version !== pinnedPostcss ||
  lock.packages?.["node_modules/next/node_modules/postcss"]
) {
  throw new Error("package-lock.json does not enforce the audited Next.js PostCSS override");
}

function assertExactVersions(manifestName, section, entries) {
  for (const [name, value] of Object.entries(entries ?? {})) {
    if (value && typeof value === "object") {
      assertExactVersions(manifestName, `${section}.${name}`, value);
      continue;
    }
    if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(value)) {
      throw new Error(`${manifestName} ${section}.${name} is not an exact version: ${value}`);
    }
  }
}

for (const [manifestName, manifest] of [["desktop", rootPackage], ["renderer", rendererPackage]]) {
  for (const section of ["dependencies", "devDependencies", "overrides"]) {
    assertExactVersions(manifestName, section, manifest[section]);
  }
}

const pythonReleaseLockEntries = fs.readFileSync(pythonReleaseLockPath, "utf8")
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith("#"));
const lockedPythonNames = new Map();
for (const line of pythonReleaseLockEntries) {
  const match = line.match(
    /^([A-Za-z0-9][A-Za-z0-9._-]*)==([0-9][A-Za-z0-9.!+_-]*) --hash=sha256:([a-f0-9]{64})$/,
  );
  if (!match) throw new Error(`Python release lock entry is not exact and hash-pinned: ${line}`);
  const canonicalName = match[1].toLowerCase().replace(/[-_.]+/g, "-");
  if (canonicalName === "webfa-desktop-runtime") {
    throw new Error("The source-built WebFA wheel must not be fetched by the third-party release lock");
  }
  if (lockedPythonNames.has(canonicalName)) throw new Error(`Duplicate Python release lock entry: ${match[1]}`);
  lockedPythonNames.set(canonicalName, match[2]);
}
if (lockedPythonNames.size < 40) throw new Error("Python release lock is unexpectedly incomplete");
if (!isDeepStrictEqual(windowsToolchainLock, expectedWindowsToolchainLock)) {
  throw new Error("Windows release toolchain lock changed without an audited verifier update");
}
if (readJson("node_modules/electron-builder/package.json").version !== windowsToolchainLock.electron_builder_version) {
  throw new Error("Installed electron-builder differs from the Windows release toolchain lock");
}
const windowsToolsetSource = fs.readFileSync(
  path.join(root, "node_modules/app-builder-lib/out/toolsets/windows.js"),
  "utf8",
);
const sevenZipToolsetSource = fs.readFileSync(
  path.join(root, "node_modules/app-builder-lib/out/toolsets/7zip.js"),
  "utf8",
);
for (const expected of [
  windowsToolchainLock.nsis.release,
  windowsToolchainLock.nsis.archive,
  windowsToolchainLock.nsis.sha256,
  windowsToolchainLock.nsis_resources.release,
  windowsToolchainLock.nsis_resources.archive,
  windowsToolchainLock.nsis_resources.sha256,
]) {
  if (!windowsToolsetSource.includes(expected)) {
    throw new Error(`Installed NSIS toolset implementation differs from the lock: ${expected}`);
  }
}
for (const expected of [
  windowsToolchainLock.seven_zip.release,
  windowsToolchainLock.seven_zip.archive,
  windowsToolchainLock.seven_zip.sha256,
]) {
  if (!sevenZipToolsetSource.includes(expected)) {
    throw new Error(`Installed 7-Zip toolset implementation differs from the lock: ${expected}`);
  }
}
const sidecarBuildScript = fs.readFileSync(path.join(root, "scripts/build-sidecar.ps1"), "utf8");
for (const invariant of [
  "python-windows-release-lock.txt",
  "--require-hashes",
  "--only-binary=:all:",
  "--no-deps",
  "--isolated",
  "Remove-Item Env:PYTHONHOME",
  "Remove-Item Env:PYTHONPATH",
]) {
  if (!sidecarBuildScript.includes(invariant)) throw new Error(`Sidecar build does not enforce: ${invariant}`);
}
if (sidecarBuildScript.includes('"--constraint"')) {
  throw new Error("Sidecar build still permits unhashed constraint-only installation");
}

const npmInstallVerification = verifyNodeInstall(pinnedPostcss);

const requiredFiles = [
  "apps/desktop/electron/dist/main.js",
  "apps/desktop/electron/dist/preload.js",
  "apps/desktop/electron/dist/monitorPreload.js",
  "apps/desktop/electron/dist/runtimeProcess.js",
  "apps/desktop/electron/dist/processTermination.js",
  "apps/desktop/electron/dist/rendererServer.js",
  "apps/desktop/renderer/out/index.html",
  "apps/desktop/renderer/out/monitor/index.html",
  ".release/sidecar/webfa.exe",
  ".release/metadata/build-manifest.json",
  ".release/metadata/SBOM.spdx.json",
  ".release/metadata/THIRD_PARTY_NOTICES.md",
  ".release/metadata/windows-toolchain-lock.json",
  "packaging/webfa.ico",
  nsisIncludeRelative,
  windowsToolchainLockRelative,
  "LICENSE",
];
for (const relative of requiredFiles) {
  const target = path.join(root, relative);
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Invalid release input: ${relative}`);
}
const applicationIcon = validateWindowsIcon(path.join(root, "packaging/webfa.ico"));
const nsisInclude = fs.readFileSync(nsisIncludePath, "utf8");
for (const invariant of [
  "!define WEBFA_MIN_TEMP_FREE_MB 4096",
  "!macro customInit",
  "GetDiskFreeSpaceEx",
  "System::Int64Op",
  "SetErrorLevel 3",
  "!macro customUnInstall",
  "APP_INSTALLER_STORE_FILE",
  'Delete "$LOCALAPPDATA\\${APP_INSTALLER_STORE_FILE}"',
  '${GetParent} "$LOCALAPPDATA\\${APP_INSTALLER_STORE_FILE}"',
  'RMDir "$R0"',
]) {
  if (!nsisInclude.includes(invariant)) throw new Error(`NSIS uninstall cache cleanup does not enforce: ${invariant}`);
}
if (/RMDir\s+\/r|\$APPDATA|DELETE_APP_DATA_ON_UNINSTALL/.test(nsisInclude)) {
  throw new Error("NSIS uninstall cache cleanup may not recursively remove application or user data");
}

for (const directTool of ["@electron/asar", "@electron/get", "js-yaml", "resedit"]) {
  if (!rootPackage.devDependencies?.[directTool]) {
    throw new Error(`Release script dependency must be declared directly: ${directTool}`);
  }
}

const buildManifest = readJson(".release/metadata/build-manifest.json");
const expectedPythonBuildRuntime = `Python ${fs.readFileSync(path.join(root, ".python-version"), "utf8").trim()}`;
const currentGitCommit = execFileSync("git", ["rev-parse", "HEAD"], {
  cwd: root,
  encoding: "utf8",
  windowsHide: true,
}).trim();
if (
  buildManifest.schema_version !== 1 ||
  buildManifest.product !== "webfa" ||
  buildManifest.release_version !== rootPackage.version ||
  buildManifest.runtime_protocol_version !== 1 ||
  buildManifest.target !== "windows-x64" ||
  buildManifest.desktop_sidecar_layout !== "pyinstaller-onedir" ||
  buildManifest.electron_version !== rootPackage.devDependencies.electron ||
  buildManifest.electron_builder_version !== windowsToolchainLock.electron_builder_version ||
  buildManifest.node_version !== process.version ||
  buildManifest.python_build_runtime !== expectedPythonBuildRuntime ||
  buildManifest.git_commit !== currentGitCommit ||
  typeof buildManifest.source_tree_dirty !== "boolean" ||
  typeof buildManifest.generated_at !== "string" ||
  Number.isNaN(Date.parse(buildManifest.generated_at)) ||
  new Date(buildManifest.generated_at).toISOString() !== buildManifest.generated_at
) {
  throw new Error(`Invalid release build manifest: ${JSON.stringify(buildManifest)}`);
}
if (
  buildManifest.package_lock_sha256 !== hashFile(path.join(root, "package-lock.json")) ||
  buildManifest.python_release_lock_sha256 !== hashFile(pythonReleaseLockPath) ||
  buildManifest.windows_toolchain_lock_sha256 !== hashFile(windowsToolchainLockPath) ||
  buildManifest.application_icon_sha256 !== hashFile(path.join(root, "packaging/webfa.ico")) ||
  buildManifest.nsis_include_sha256 !== hashFile(nsisIncludePath)
) {
  throw new Error("Release build manifest dependency-lock hashes are stale");
}
const sbomPath = path.join(root, ".release/metadata/SBOM.spdx.json");
const noticesPath = path.join(root, ".release/metadata/THIRD_PARTY_NOTICES.md");
const packagedWindowsToolchainLockPath = path.join(root, ".release/metadata/windows-toolchain-lock.json");
if (
  buildManifest.sbom_sha256 !== hashFile(sbomPath) ||
  buildManifest.third_party_notices_sha256 !== hashFile(noticesPath) ||
  hashFile(packagedWindowsToolchainLockPath) !== hashFile(windowsToolchainLockPath)
) {
  throw new Error("Release build manifest legal metadata hashes are stale");
}
const sbom = JSON.parse(fs.readFileSync(sbomPath, "utf8"));
if (
  sbom.spdxVersion !== "SPDX-2.3" ||
  sbom.dataLicense !== "CC0-1.0" ||
  !new RegExp(`^https://spdx\\.org/spdxdocs/WebFA-${rootPackage.version.replaceAll(".", "\\.")}-[a-f0-9]{64}$`)
    .test(sbom.documentNamespace) ||
  sbom.creationInfo?.created !== buildManifest.generated_at ||
  !Array.isArray(sbom.packages) ||
  sbom.packages.length < 10
) {
  throw new Error("Release SBOM is absent or incomplete");
}
const pythonReleaseComponents = sbom.packages
  .filter((item) => String(item.comment).startsWith("Ecosystem: pypi;"))
  .map((item) => ({
    name: String(item.name).toLowerCase().replace(/[-_.]+/g, "-"),
    version: String(item.versionInfo),
  }))
  .sort((left, right) => `${left.name}@${left.version}`.localeCompare(`${right.name}@${right.version}`, "en"));
for (const [name, version] of lockedPythonNames) {
  if (!pythonReleaseComponents.some((item) => item.name === name && item.version === version)) {
    throw new Error(`Release SBOM is missing locked Python component ${name}==${version}`);
  }
}
if (!pythonReleaseComponents.some((item) => (
  item.name === "webfa-desktop-runtime" && item.version === rootPackage.version
))) {
  throw new Error("Release SBOM is missing the source-built WebFA wheel");
}
for (const [name, licenseDeclared] of [
  ["certifi", "MPL-2.0"],
  ["greenlet", "MIT AND PSF-2.0"],
  ["pywin32", "PSF-2.0"],
  ["typing-extensions", "PSF-2.0"],
]) {
  const component = sbom.packages.find((item) => (
    String(item.name).toLowerCase().replace(/[-_.]+/g, "-") === name &&
    String(item.comment).startsWith("Ecosystem: pypi;")
  ));
  if (component?.licenseDeclared !== licenseDeclared) {
    throw new Error(`Release SBOM license normalization is stale for ${name}`);
  }
}
const pythonReleaseComponentsSha256 = crypto
  .createHash("sha256")
  .update(JSON.stringify(pythonReleaseComponents))
  .digest("hex");
if (
  buildManifest.python_release_component_count !== pythonReleaseComponents.length ||
  buildManifest.python_release_components_sha256 !== pythonReleaseComponentsSha256
) {
  throw new Error("Release build manifest Python component inventory is stale");
}
const notices = fs.readFileSync(noticesPath, "utf8");
if (
  !notices.includes(`Generated for WebFA ${rootPackage.version}`) ||
  !notices.includes("| Ecosystem | Component |") ||
  !notices.includes("| pypi | fastapi |") ||
  !notices.includes("| pypi | SQLAlchemy |")
) {
  throw new Error("Third-party component notice is absent or stale");
}

const sidecarRoot = path.join(root, ".release/sidecar");
const sidecarFiles = [];
const sidecarPending = [sidecarRoot];
while (sidecarPending.length) {
  const current = sidecarPending.pop();
  for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
    const target = path.join(current, entry.name);
    const stat = fs.lstatSync(target);
    const relative = path.relative(sidecarRoot, target).replaceAll(path.sep, "/");
    if (stat.isSymbolicLink()) throw new Error(`Sidecar bundle contains a link: ${relative}`);
    if (entry.isDirectory()) {
      sidecarPending.push(target);
      continue;
    }
    if (!entry.isFile()) throw new Error(`Sidecar bundle contains a non-file entry: ${relative}`);
    if (/direct_url\.json$/i.test(relative)) {
      throw new Error(`Sidecar bundle leaks build-local metadata: ${relative}`);
    }
    if (/\.(?:py|pyc|pyo)$/i.test(relative)) {
      throw new Error(`Sidecar bundle contains Python source or bytecode: ${relative}`);
    }
    const bytes = fs.readFileSync(target);
    if (bytes.includes(Buffer.from("direct_url.json"))) {
      throw new Error(`Sidecar archive references build-local direct_url metadata: ${relative}`);
    }
    sidecarFiles.push({
      path: relative,
      bytes: stat.size,
      sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    });
  }
}
sidecarFiles.sort((left, right) => left.path.localeCompare(right.path, "en"));
if (sidecarFiles.length < 2 || !sidecarFiles.some((entry) => entry.path === "webfa.exe")) {
  throw new Error("Frozen sidecar must be a staged onedir bundle");
}
const sidecarBundleSha256 = crypto
  .createHash("sha256")
  .update(JSON.stringify(sidecarFiles))
  .digest("hex");
if (buildManifest.sidecar_bundle_sha256 !== sidecarBundleSha256) {
  throw new Error("Release build manifest sidecar bundle hash is stale");
}
const sidecarPayloadBundleSha256 = bundleSha256(sidecarPayloadEntries(sidecarRoot));
if (buildManifest.sidecar_payload_bundle_sha256 !== sidecarPayloadBundleSha256) {
  throw new Error("Release build manifest sidecar payload hash is stale");
}
const sidecarPePayloads = sidecarPayloadEntries(sidecarRoot)
  .filter((entry) => entry.path.toLowerCase().endsWith(".exe"));
if (!isDeepStrictEqual(buildManifest.sidecar_pe_payloads, sidecarPePayloads)) {
  throw new Error("Release build manifest sidecar PE payload identities are stale");
}
const desktopArchiveInputSha256 = bundleSha256(desktopArchiveInputEntries(root, rootPackage));
if (buildManifest.desktop_archive_input_sha256 !== desktopArchiveInputSha256) {
  throw new Error("Release build manifest Desktop archive input hash is stale");
}
if (fs.existsSync(path.join(root, "apps/desktop/electron/dist/mcpProcess.js"))) {
  throw new Error("Stale Electron-owned MCP process output is present");
}

for (const relativeRoot of ["apps/desktop/electron/dist", "apps/desktop/renderer/out"]) {
  const pending = [path.join(root, relativeRoot)];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      const stat = fs.lstatSync(target);
      if (stat.isSymbolicLink()) throw new Error(`Release input contains a link: ${path.relative(root, target)}`);
      if (entry.isDirectory()) pending.push(target);
      if (entry.isFile() && /\.(?:map|ts)$/.test(entry.name)) {
        throw new Error(`Release input contains source material: ${path.relative(root, target)}`);
      }
    }
  }
}

const builder = yaml.load(fs.readFileSync(path.join(root, "electron-builder.yml"), "utf8"), {
  filename: "electron-builder.yml",
  json: false,
});
const signedBuilder = yaml.load(fs.readFileSync(path.join(root, "electron-builder.signed.yml"), "utf8"), {
  filename: "electron-builder.signed.yml",
  json: false,
});
const electronVersion = rootPackage.devDependencies?.electron;
const electronArchive = `electron-v${electronVersion}-win32-x64.zip`;
const electronChecksums = readJson("node_modules/electron/checksums.json");
const electronChecksum = electronChecksums[electronArchive];
if (!electronChecksum) {
  throw new Error("electron-builder.yml does not pin the installed Electron Windows checksum");
}
const electronDist = path.join(root, ".release/electron-dist", electronArchive);
const electronDistStat = fs.lstatSync(electronDist);
if (!electronDistStat.isFile() || electronDistStat.isSymbolicLink()) {
  throw new Error("Prepared Electron runtime is not a regular file");
}
const electronDistHash = crypto.createHash("sha256").update(fs.readFileSync(electronDist)).digest("hex");
if (electronDistHash !== electronChecksum) {
  throw new Error(`Prepared Electron runtime checksum mismatch: ${electronDistHash}`);
}
if (buildManifest.electron_archive_sha256 !== electronDistHash) {
  throw new Error("Release build manifest Electron archive hash is stale");
}
const expectedBuilder = {
  appId: "com.webfa.desktop",
  productName: "WebFA",
  artifactName: "${productName}-Setup-${version}-${arch}.${ext}",
  asar: true,
  compression: "maximum",
  publish: null,
  toolsets: { nsis: "0.0.0" },
  electronDownload: { mirrorOptions: {}, checksums: { [electronArchive]: electronChecksum } },
  electronDist: ".release/electron-dist",
  directories: { output: ".release/electron", buildResources: "packaging" },
  files: [
    "package.json",
    "apps/desktop/electron/dist/**/*",
    "apps/desktop/renderer/out/**/*",
    "!**/*.map",
    "!**/*.ts",
  ],
  extraResources: [
    { from: ".release/sidecar", to: "sidecar" },
    { from: "packaging/webfa.ico", to: "assets/webfa.ico" },
    { from: "LICENSE", to: "legal/LICENSE.txt" },
    { from: ".release/metadata", to: "legal" },
  ],
  win: {
    executableName: "WebFA",
    icon: "webfa.ico",
    requestedExecutionLevel: "asInvoker",
    target: [{ target: "nsis", arch: ["x64"] }],
  },
  nsis: {
    oneClick: false,
    perMachine: false,
    allowElevation: false,
    packElevateHelper: false,
    differentialPackage: false,
    allowToChangeInstallationDirectory: true,
    createDesktopShortcut: true,
    createStartMenuShortcut: true,
    shortcutName: "WebFA",
    installerIcon: "webfa.ico",
    uninstallerIcon: "webfa.ico",
    include: "installer.nsh",
    deleteAppDataOnUninstall: false,
  },
  electronFuses: {
    runAsNode: false,
    enableCookieEncryption: true,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
    enableEmbeddedAsarIntegrityValidation: true,
    onlyLoadAppFromAsar: true,
    grantFileProtocolExtraPrivileges: false,
  },
};
if (!isDeepStrictEqual(builder, expectedBuilder)) {
  throw new Error(`electron-builder.yml effective configuration changed: ${JSON.stringify(builder)}`);
}
if (!isDeepStrictEqual(signedBuilder, { extends: "./electron-builder.yml", forceCodeSigning: true })) {
  throw new Error(`electron-builder.signed.yml effective configuration changed: ${JSON.stringify(signedBuilder)}`);
}

const sidecar = path.join(sidecarRoot, "webfa.exe");
const versionOutput = execFileSync(sidecar, ["--version"], { cwd: osTemp(), encoding: "utf8", windowsHide: true }).trim();
if (versionOutput !== `webfa ${rootPackage.version}`) {
  throw new Error(`Unexpected sidecar version output: ${versionOutput}`);
}
execFileSync(process.execPath, [path.join(root, "scripts/smoke-sidecar.cjs"), sidecar], {
  cwd: osTemp(),
  stdio: "inherit",
  windowsHide: true,
});
process.stdout.write(`${JSON.stringify({
  status: "pass",
  version: rootPackage.version,
  sidecarFiles: sidecarFiles.length,
  sidecarBytes: sidecarFiles.reduce((total, entry) => total + entry.bytes, 0),
  sidecarExecutableSha256: sidecarFiles.find((entry) => entry.path === "webfa.exe").sha256,
  sidecarBundleSha256,
  sidecarPayloadBundleSha256,
  desktopArchiveInputSha256,
  electronArchive,
  electronSha256: electronDistHash,
  windowsToolchain: windowsToolchainLock,
  npmInstallVerification,
  applicationIcon,
})}\n`);

function osTemp() {
  return process.env.TEMP || process.env.TMP || root;
}

function hashFile(target) {
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Invalid release hash input: ${target}`);
  return crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");
}

function verifyNodeInstall(expectedPostcss) {
  const npmCli = [
    process.env.npm_execpath,
    path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js"),
  ].filter(Boolean).find((candidate) => fs.existsSync(candidate));
  if (!npmCli) throw new Error("Could not locate npm-cli.js to verify the installed dependency tree");

  let stdout;
  try {
    stdout = execFileSync(process.execPath, [npmCli, "ls", "--all", "--json", "--loglevel=silent"], {
      cwd: root,
      encoding: "utf8",
      windowsHide: true,
      maxBuffer: 16 * 1024 * 1024,
    });
  } catch (error) {
    stdout = error.stdout;
    if (typeof stdout !== "string" || !stdout.trim()) throw error;
  }
  const tree = JSON.parse(stdout);
  const problems = tree.problems ?? [];
  // Next 16.2.x declares PostCSS 8.4.31 exactly. WebFA deliberately replaces
  // that build-only copy with the audited patched version. npm reports this
  // exact override as invalid even though the lock, installed bytes, audit,
  // and production static export all use the patched version. No other npm
  // tree problem is accepted. See vercel/next.js#93234.
  const expectedProblem = new RegExp(
    `^invalid: postcss@${expectedPostcss.replaceAll(".", "\\.")} .*[\\\\/]node_modules[\\\\/]postcss$`,
    "i",
  );
  if (problems.length > 1 || (problems.length === 1 && !expectedProblem.test(problems[0]))) {
    throw new Error(`Installed npm dependency tree is inconsistent: ${JSON.stringify(problems)}`);
  }
  const installedPostcss = readJson("node_modules/postcss/package.json").version;
  if (
    installedPostcss !== expectedPostcss ||
    fs.existsSync(path.join(root, "node_modules/next/node_modules/postcss"))
  ) {
    throw new Error("The patched PostCSS override is not the only installed Next.js copy");
  }
  return problems.length === 0 ? "clean" : "patched-next-postcss-known-exception";
}
