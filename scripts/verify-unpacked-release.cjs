const { execFileSync } = require("node:child_process");
const asar = require("@electron/asar");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { isDeepStrictEqual } = require("node:util");
const {
  bundleSha256,
  canonicalJsonBytes,
  hashBytes,
  releaseDesktopManifest,
  sidecarPayloadEntries,
} = require("./release-integrity.cjs");
const { verifyElectronRuntimeFromArchive } = require("./electron-runtime-verifier.cjs");
const { validateWindowsIcon, verifyEmbeddedWindowsIcons } = require("./windows-icon-verifier.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const sourceManifest = require(path.join(root, "package.json"));
const electronArchive = path.join(
  root,
  ".release/electron-dist",
  `electron-v${sourceManifest.devDependencies.electron}-win32-x64.zip`,
);
const expectedPythonBuildRuntime = `Python ${fs.readFileSync(path.join(root, ".python-version"), "utf8").trim()}`;
const currentGitCommit = execFileSync("git", ["rev-parse", "HEAD"], {
  cwd: root,
  encoding: "utf8",
  windowsHide: true,
}).trim();
const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const alignToFourBytes = (value) => Math.ceil(value / 4) * 4;

const verifyAsarPhysicalEnvelope = (archivePath) => {
  const archiveStat = fs.lstatSync(archivePath);
  if (!archiveStat.isFile() || archiveStat.isSymbolicLink()) {
    throw new Error(`ASAR physical envelope target is not a regular file: ${archivePath}`);
  }

  const archiveBytes = fs.readFileSync(archivePath);
  const rawHeader = asar.getRawHeader(archivePath);
  if (
    !isRecord(rawHeader) ||
    !isRecord(rawHeader.header) ||
    typeof rawHeader.headerString !== "string" ||
    !Number.isSafeInteger(rawHeader.headerSize) ||
    rawHeader.headerSize < 8
  ) {
    throw new Error("ASAR physical header returned by @electron/asar getRawHeader is invalid");
  }

  const headerStringBytes = Buffer.from(rawHeader.headerString, "utf8");
  const expectedHeaderSize = 8 + alignToFourBytes(headerStringBytes.length);
  const dataOffset = 8 + rawHeader.headerSize;
  if (
    rawHeader.headerSize !== expectedHeaderSize ||
    !Number.isSafeInteger(dataOffset) ||
    archiveBytes.length < dataOffset ||
    archiveBytes.readUInt32LE(0) !== 4 ||
    archiveBytes.readUInt32LE(4) !== rawHeader.headerSize ||
    archiveBytes.readUInt32LE(8) !== rawHeader.headerSize - 4 ||
    archiveBytes.readUInt32LE(12) !== headerStringBytes.length ||
    !archiveBytes.subarray(16, 16 + headerStringBytes.length).equals(headerStringBytes) ||
    archiveBytes.subarray(16 + headerStringBytes.length, dataOffset).some((byte) => byte !== 0)
  ) {
    throw new Error("ASAR physical header does not match @electron/asar getRawHeader");
  }

  const packedFiles = [];
  const visitNode = (node, archivePathParts) => {
    const displayPath = archivePathParts.length ? archivePathParts.join("/") : "/";
    if (!isRecord(node)) {
      throw new Error(`ASAR physical envelope contains an unknown unsafe node: ${displayPath}`);
    }
    if (Object.hasOwn(node, "unpacked")) {
      throw new Error(`ASAR physical envelope contains an unpacked entry: ${displayPath}`);
    }
    if (Object.hasOwn(node, "link")) {
      throw new Error(`ASAR physical envelope contains a symbolic link: ${displayPath}`);
    }
    if (Object.hasOwn(node, "files")) {
      if (Object.keys(node).length !== 1 || !isRecord(node.files)) {
        throw new Error(`ASAR physical envelope contains an unknown unsafe directory node: ${displayPath}`);
      }
      for (const [name, child] of Object.entries(node.files)) {
        if (
          name.length === 0 ||
          name === "." ||
          name === ".." ||
          name === "__proto__" ||
          /[\\/\0]/.test(name)
        ) {
          throw new Error(`ASAR physical envelope contains an unsafe path segment: ${JSON.stringify(name)}`);
        }
        visitNode(child, [...archivePathParts, name]);
      }
      return;
    }

    const allowedFileFields = new Set(["executable", "integrity", "offset", "size"]);
    if (
      Object.keys(node).some((field) => !allowedFileFields.has(field)) ||
      !Object.hasOwn(node, "offset") ||
      !Object.hasOwn(node, "size") ||
      !Object.hasOwn(node, "integrity") ||
      (Object.hasOwn(node, "executable") && typeof node.executable !== "boolean")
    ) {
      throw new Error(`ASAR physical envelope contains an unknown unsafe file node: ${displayPath}`);
    }
    if (
      typeof node.offset !== "string" ||
      !/^(?:0|[1-9][0-9]*)$/.test(node.offset) ||
      !Number.isSafeInteger(node.size) ||
      node.size < 0
    ) {
      throw new Error(`ASAR payload offset/size is not a non-negative safe integer: ${displayPath}`);
    }
    const offset = Number(node.offset);
    if (!Number.isSafeInteger(offset) || !Number.isSafeInteger(offset + node.size)) {
      throw new Error(`ASAR payload offset/size is not a non-negative safe integer: ${displayPath}`);
    }

    const integrity = node.integrity;
    if (
      !isRecord(integrity) ||
      JSON.stringify(Object.keys(integrity).sort()) !==
        JSON.stringify(["algorithm", "blockSize", "blocks", "hash"]) ||
      integrity.algorithm !== "SHA256" ||
      !/^[a-f0-9]{64}$/.test(integrity.hash) ||
      !Number.isSafeInteger(integrity.blockSize) ||
      integrity.blockSize <= 0 ||
      !Array.isArray(integrity.blocks) ||
      !integrity.blocks.every((blockHash) => /^[a-f0-9]{64}$/.test(blockHash))
    ) {
      throw new Error(`ASAR packed file integrity metadata is invalid: ${displayPath}`);
    }
    packedFiles.push({
      archivePath: displayPath,
      offset,
      size: node.size,
      integrity,
    });
  };
  visitNode(rawHeader.header, []);
  if (packedFiles.length === 0) {
    throw new Error("ASAR physical envelope contains no packed files");
  }

  packedFiles.sort((left, right) =>
    left.offset - right.offset ||
    Number(left.size !== 0) - Number(right.size !== 0) ||
    left.archivePath.localeCompare(right.archivePath, "en"),
  );
  let payloadBytes = 0;
  for (const file of packedFiles) {
    if (file.offset !== payloadBytes) {
      throw new Error(
        `ASAR packed payload ranges are not contiguous at ${file.archivePath}: expected ${payloadBytes}, got ${file.offset}`,
      );
    }
    payloadBytes += file.size;
    if (!Number.isSafeInteger(dataOffset + payloadBytes)) {
      throw new Error(`ASAR packed payload range exceeds the safe integer limit: ${file.archivePath}`);
    }
  }
  if (dataOffset + payloadBytes !== archiveBytes.length) {
    throw new Error(
      `ASAR physical length does not exactly match packed payload: expected ${dataOffset + payloadBytes}, got ${archiveBytes.length}`,
    );
  }

  for (const file of packedFiles) {
    const fileBytes = archiveBytes.subarray(
      dataOffset + file.offset,
      dataOffset + file.offset + file.size,
    );
    if (hashBytes(fileBytes) !== file.integrity.hash) {
      throw new Error(`ASAR packed payload integrity differs from its header: ${file.archivePath}`);
    }
    const expectedBlockCount = Math.max(1, Math.ceil(file.size / file.integrity.blockSize));
    if (file.integrity.blocks.length !== expectedBlockCount) {
      throw new Error(`ASAR packed payload block integrity metadata is stale: ${file.archivePath}`);
    }
    for (let blockIndex = 0; blockIndex < expectedBlockCount; blockIndex += 1) {
      const blockBytes = fileBytes.subarray(
        blockIndex * file.integrity.blockSize,
        Math.min((blockIndex + 1) * file.integrity.blockSize, fileBytes.length),
      );
      if (hashBytes(blockBytes) !== file.integrity.blocks[blockIndex]) {
        throw new Error(`ASAR packed payload block integrity differs from its header: ${file.archivePath}`);
      }
    }
  }

  return {
    dataOffset,
    headerSize: rawHeader.headerSize,
    packedFiles: packedFiles.length,
    payloadBytes,
    physicalBytes: archiveBytes.length,
  };
};

const envelopeOnlyIndex = process.argv.indexOf("--verify-asar-envelope-only");
if (envelopeOnlyIndex !== -1) {
  const envelopeTarget = process.argv[envelopeOnlyIndex + 1];
  if (!envelopeTarget || envelopeTarget.startsWith("--")) {
    throw new Error("--verify-asar-envelope-only requires an ASAR file path");
  }
  process.stdout.write(`${JSON.stringify(verifyAsarPhysicalEnvelope(path.resolve(envelopeTarget)))}\n`);
  process.exit(0);
}

const signed = process.argv.includes("--signed");
const unpackedArgument = process.argv.slice(2).find((value) => !value.startsWith("--"));
const unpacked = path.resolve(root, unpackedArgument ?? ".release/electron/win-unpacked");
const appExecutable = path.join(unpacked, "WebFA.exe");
const appAsar = path.join(unpacked, "resources/app.asar");
const packagedSidecarRoot = path.join(unpacked, "resources/sidecar");
const inputSidecarRoot = path.join(root, ".release/sidecar");
const packagedSidecar = path.join(packagedSidecarRoot, "webfa.exe");
const inputSidecar = path.join(inputSidecarRoot, "webfa.exe");
const legalFiles = [
  [path.join(root, "LICENSE"), path.join(unpacked, "resources/legal/LICENSE.txt")],
  [path.join(root, ".release/metadata/build-manifest.json"), path.join(unpacked, "resources/legal/build-manifest.json")],
  [path.join(root, ".release/metadata/SBOM.spdx.json"), path.join(unpacked, "resources/legal/SBOM.spdx.json")],
  [path.join(root, ".release/metadata/THIRD_PARTY_NOTICES.md"), path.join(unpacked, "resources/legal/THIRD_PARTY_NOTICES.md")],
  [path.join(root, "packaging/windows-toolchain-lock.json"), path.join(unpacked, "resources/legal/windows-toolchain-lock.json")],
];
const assetFiles = [
  [path.join(root, "packaging/webfa.ico"), path.join(unpacked, "resources/assets/webfa.ico")],
];

for (const target of [
  appExecutable,
  appAsar,
  electronArchive,
  packagedSidecar,
  inputSidecar,
  ...legalFiles.flat(),
  ...assetFiles.flat(),
]) {
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Invalid unpacked release file: ${target}`);
}

const hashFile = (target) => crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");
for (const [source, packaged] of legalFiles) {
  if (hashFile(source) !== hashFile(packaged)) {
    throw new Error(`Packaged legal/release metadata differs from its verified input: ${path.basename(source)}`);
  }
}
for (const [source, packaged] of assetFiles) {
  if (hashFile(source) !== hashFile(packaged)) {
    throw new Error(`Packaged application asset differs from its verified input: ${path.basename(source)}`);
  }
}
const asarEnvelope = verifyAsarPhysicalEnvelope(appAsar);
const electronRuntime = verifyElectronRuntimeFromArchive(electronArchive, unpacked);
const applicationIcon = validateWindowsIcon(assetFiles[0][0]);
const embeddedIcons = verifyEmbeddedWindowsIcons(assetFiles[0][0], [appExecutable, packagedSidecar]);
const packagedBuildManifest = JSON.parse(fs.readFileSync(legalFiles[1][1], "utf8"));
if (
  packagedBuildManifest.schema_version !== 1 ||
  packagedBuildManifest.product !== "webfa" ||
  packagedBuildManifest.release_version !== sourceManifest.version ||
  packagedBuildManifest.runtime_protocol_version !== 1 ||
  packagedBuildManifest.target !== "windows-x64" ||
  packagedBuildManifest.desktop_sidecar_layout !== "pyinstaller-onedir" ||
  packagedBuildManifest.electron_version !== sourceManifest.devDependencies.electron ||
  packagedBuildManifest.electron_builder_version !== sourceManifest.devDependencies["electron-builder"] ||
  packagedBuildManifest.node_version !== process.version ||
  packagedBuildManifest.python_build_runtime !== expectedPythonBuildRuntime ||
  packagedBuildManifest.git_commit !== currentGitCommit ||
  typeof packagedBuildManifest.source_tree_dirty !== "boolean" ||
  typeof packagedBuildManifest.generated_at !== "string" ||
  Number.isNaN(Date.parse(packagedBuildManifest.generated_at)) ||
  new Date(packagedBuildManifest.generated_at).toISOString() !== packagedBuildManifest.generated_at
) {
  throw new Error("Packaged build manifest identity changed");
}
if (
  packagedBuildManifest.package_lock_sha256 !== hashFile(path.join(root, "package-lock.json")) ||
  packagedBuildManifest.python_release_lock_sha256 !==
    hashFile(path.join(root, "packaging/python-windows-release-lock.txt")) ||
  packagedBuildManifest.windows_toolchain_lock_sha256 !== hashFile(legalFiles[4][1]) ||
  packagedBuildManifest.electron_archive_sha256 !== hashFile(electronArchive) ||
  packagedBuildManifest.application_icon_sha256 !== hashFile(assetFiles[0][1]) ||
  packagedBuildManifest.nsis_include_sha256 !== hashFile(path.join(root, "packaging/installer.nsh")) ||
  packagedBuildManifest.sbom_sha256 !== hashFile(legalFiles[2][1]) ||
  packagedBuildManifest.third_party_notices_sha256 !== hashFile(legalFiles[3][1])
) {
  throw new Error("Packaged build manifest input or legal metadata binding changed");
}

const collectBundle = (bundleRoot) => {
  const files = [];
  const pending = [bundleRoot];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      const stat = fs.lstatSync(target);
      const relative = path.relative(bundleRoot, target).replaceAll(path.sep, "/");
      if (stat.isSymbolicLink()) throw new Error(`Sidecar bundle contains a link: ${relative}`);
      if (entry.isDirectory()) {
        pending.push(target);
        continue;
      }
      if (!entry.isFile()) throw new Error(`Sidecar bundle contains a non-file entry: ${relative}`);
      files.push({
        path: relative,
        bytes: stat.size,
        sha256: crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex"),
      });
    }
  }
  return files.sort((left, right) => left.path.localeCompare(right.path, "en"));
};
const collectRegularFilePaths = (bundleRoot) => {
  const files = [];
  const pending = [bundleRoot];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      const stat = fs.lstatSync(target);
      const relative = path.relative(bundleRoot, target).replaceAll(path.sep, "/");
      if (stat.isSymbolicLink()) throw new Error(`Unpacked release contains a link: ${relative}`);
      if (entry.isDirectory()) {
        pending.push(target);
        continue;
      }
      if (!entry.isFile()) throw new Error(`Unpacked release contains a non-file entry: ${relative}`);
      files.push(relative);
    }
  }
  return files.sort((left, right) => left.localeCompare(right, "en"));
};
const inputSidecarFiles = collectBundle(inputSidecarRoot);
const packagedSidecarFiles = collectBundle(packagedSidecarRoot);
const comparableSidecarFiles = (entries) => signed
  ? entries.filter((entry) => !entry.path.toLowerCase().endsWith(".exe"))
  : entries;
if (
  JSON.stringify(packagedSidecarFiles.map((entry) => entry.path)) !==
    JSON.stringify(inputSidecarFiles.map((entry) => entry.path)) ||
  JSON.stringify(comparableSidecarFiles(packagedSidecarFiles)) !==
    JSON.stringify(comparableSidecarFiles(inputSidecarFiles))
) {
  throw new Error("Packaged sidecar bundle differs from the verified release input");
}
const packagedSidecarBundleSha256 = crypto
  .createHash("sha256")
  .update(JSON.stringify(packagedSidecarFiles))
  .digest("hex");
if (!signed && packagedBuildManifest.sidecar_bundle_sha256 !== packagedSidecarBundleSha256) {
  throw new Error("Unsigned packaged sidecar bundle is not bound to the build manifest");
}
const packagedSidecarPayloadBundleSha256 = bundleSha256(
  sidecarPayloadEntries(packagedSidecarRoot, packagedBuildManifest.sidecar_pe_payloads),
);
if (packagedBuildManifest.sidecar_payload_bundle_sha256 !== packagedSidecarPayloadBundleSha256) {
  throw new Error("Packaged sidecar PE payload is not bound to the build manifest");
}

const expectedUnpackedPaths = [
  ...electronRuntime.packagedPaths,
  "WebFA.exe",
  "resources/app.asar",
  "resources/assets/webfa.ico",
  "resources/legal/LICENSE.txt",
  "resources/legal/SBOM.spdx.json",
  "resources/legal/THIRD_PARTY_NOTICES.md",
  "resources/legal/build-manifest.json",
  "resources/legal/windows-toolchain-lock.json",
  ...packagedSidecarFiles.map((entry) => `resources/sidecar/${entry.path}`),
].sort((left, right) => left.localeCompare(right, "en"));
const actualUnpackedPaths = collectRegularFilePaths(unpacked);
if (JSON.stringify(actualUnpackedPaths) !== JSON.stringify(expectedUnpackedPaths)) {
  const expected = new Set(expectedUnpackedPaths);
  const actual = new Set(actualUnpackedPaths);
  const missing = expectedUnpackedPaths.filter((entry) => !actual.has(entry));
  const unexpected = actualUnpackedPaths.filter((entry) => !expected.has(entry));
  throw new Error(
    `Unpacked release file set differs from the pinned runtime and verified inputs: ${JSON.stringify({ missing, unexpected })}`,
  );
}

const asarBin = path.join(root, "node_modules/@electron/asar/bin/asar.js");
const asarEntries = execFileSync(process.execPath, [asarBin, "list", appAsar], {
  encoding: "utf8",
  windowsHide: true,
}).trim().split(/\r?\n/);
const allowedArchiveParents = new Set([
  "\\apps",
  "\\apps\\desktop",
  "\\apps\\desktop\\electron",
  "\\apps\\desktop\\electron\\dist",
  "\\apps\\desktop\\renderer",
  "\\apps\\desktop\\renderer\\out",
  "\\package.json",
]);
for (const entry of asarEntries) {
  if (
    allowedArchiveParents.has(entry) ||
    entry.startsWith("\\apps\\desktop\\electron\\dist\\") ||
    entry.startsWith("\\apps\\desktop\\renderer\\out\\")
  ) {
    continue;
  }
  throw new Error(`app.asar contains an unexpected path: ${entry}`);
}
for (const required of [
  "\\package.json",
  "\\apps\\desktop\\electron\\dist\\main.js",
  "\\apps\\desktop\\electron\\dist\\rendererServer.js",
  "\\apps\\desktop\\renderer\\out\\index.html",
  "\\apps\\desktop\\renderer\\out\\monitor\\index.html",
]) {
  if (!asarEntries.includes(required)) throw new Error(`app.asar is missing ${required}`);
}
for (const forbidden of ["authSurface.js", "mcpProcess.js", "node_modules", ".map", ".ts"]) {
  if (asarEntries.some((entry) => entry.includes(forbidden))) {
    throw new Error(`app.asar contains forbidden material: ${forbidden}`);
  }
}

const sourceArchiveFiles = new Map();
for (const [relativeRoot, archiveRoot] of [
  ["apps/desktop/electron/dist", "apps\\desktop\\electron\\dist"],
  ["apps/desktop/renderer/out", "apps\\desktop\\renderer\\out"],
]) {
  const sourceRoot = path.join(root, relativeRoot);
  const pending = [sourceRoot];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      const stat = fs.lstatSync(target);
      if (stat.isSymbolicLink()) throw new Error(`Release input contains a link: ${target}`);
      if (entry.isDirectory()) {
        pending.push(target);
        continue;
      }
      if (!entry.isFile()) throw new Error(`Release input contains a non-file entry: ${target}`);
      const relative = path.relative(sourceRoot, target).split(path.sep).join("\\");
      sourceArchiveFiles.set(`${archiveRoot}\\${relative}`, target);
    }
  }
}
const actualArchiveFiles = new Set();
for (const entry of asarEntries) {
  const archivePath = entry.replace(/^\\/, "");
  const stat = asar.statFile(appAsar, archivePath);
  if (!("files" in stat)) actualArchiveFiles.add(archivePath);
}
const expectedArchiveFiles = new Set(["package.json", ...sourceArchiveFiles.keys()]);
if (
  JSON.stringify([...actualArchiveFiles].sort()) !==
  JSON.stringify([...expectedArchiveFiles].sort())
) {
  throw new Error("app.asar file set differs from the verified release inputs");
}
for (const [archivePath, sourcePath] of sourceArchiveFiles) {
  const packagedBytes = asar.extractFile(appAsar, archivePath);
  const sourceBytes = fs.readFileSync(sourcePath);
  if (!packagedBytes.equals(sourceBytes)) {
    throw new Error(`app.asar content differs from the verified release input: ${archivePath}`);
  }
}

const packagedManifest = JSON.parse(asar.extractFile(appAsar, "package.json").toString("utf8"));
const expectedPackagedManifest = releaseDesktopManifest(sourceManifest);
if (!isDeepStrictEqual(packagedManifest, expectedPackagedManifest)) {
  throw new Error(`Packaged app manifest identity changed: ${JSON.stringify(packagedManifest)}`);
}
for (const forbiddenKey of ["scripts", "dependencies", "devDependencies"]) {
  if (forbiddenKey in packagedManifest) {
    throw new Error(`Packaged app manifest exposes build-only field: ${forbiddenKey}`);
  }
}
const packagedArchiveInputEntries = [...actualArchiveFiles].map((archivePath) => {
  const archiveBytes = archivePath === "package.json"
    ? canonicalJsonBytes(packagedManifest)
    : asar.extractFile(appAsar, archivePath);
  return {
    path: archivePath.replaceAll("\\", "/"),
    bytes: archiveBytes.length,
    sha256: hashBytes(archiveBytes),
  };
}).sort((left, right) => left.path.localeCompare(right.path, "en"));
const packagedDesktopArchiveInputSha256 = bundleSha256(packagedArchiveInputEntries);
if (packagedBuildManifest.desktop_archive_input_sha256 !== packagedDesktopArchiveInputSha256) {
  throw new Error("Packaged Desktop archive is not bound to the build manifest");
}

const fusesBin = path.join(root, "node_modules/@electron/fuses/dist/bin.js");
const fuses = execFileSync(process.execPath, [fusesBin, "read", "--app", appExecutable], {
  encoding: "utf8",
  windowsHide: true,
});
for (const invariant of [
  "RunAsNode is Disabled",
  "EnableCookieEncryption is Enabled",
  "EnableNodeOptionsEnvironmentVariable is Disabled",
  "EnableNodeCliInspectArguments is Disabled",
  "EnableEmbeddedAsarIntegrityValidation is Enabled",
  "OnlyLoadAppFromAsar is Enabled",
  "GrantFileProtocolExtraPrivileges is Disabled",
]) {
  if (!fuses.includes(invariant)) throw new Error(`Electron fuse invariant failed: ${invariant}`);
}

const packageVersion = sourceManifest.version;
const sidecarVersion = execFileSync(packagedSidecar, ["--version"], {
  cwd: process.env.TEMP || root,
  encoding: "utf8",
  windowsHide: true,
}).trim();
if (sidecarVersion !== `webfa ${packageVersion}`) {
  throw new Error(`Packaged sidecar version mismatch: ${sidecarVersion}`);
}

process.stdout.write(`${JSON.stringify({
  status: "pass",
  mode: signed ? "signed" : "unsigned",
  version: packageVersion,
  asarEntries: asarEntries.length,
  asarEnvelope,
  asarHeaderBytes: asarEnvelope.headerSize,
  asarPackedFiles: asarEnvelope.packedFiles,
  asarPayloadBytes: asarEnvelope.payloadBytes,
  electronRuntime: {
    archiveEntries: electronRuntime.archiveEntries,
    electronExecutableBytes: electronRuntime.electronExecutableBytes,
    verifiedFiles: electronRuntime.verifiedFiles,
    verifiedBytes: electronRuntime.verifiedBytes,
    runtimeInventorySha256: electronRuntime.runtimeInventorySha256,
  },
  packagedSidecarFiles: packagedSidecarFiles.length,
  packagedSidecarBundleSha256,
  packagedSidecarPayloadBundleSha256,
  packagedDesktopArchiveInputSha256,
  fuses: "hardened",
  applicationIcon,
  embeddedIconPixelSha256: embeddedIcons.source.pixelSha256,
})}\n`);
