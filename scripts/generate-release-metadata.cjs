const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const {
  bundleSha256,
  collectBundle,
  desktopArchiveInputEntries,
  hashFile,
  sidecarPayloadEntries,
} = require("./release-integrity.cjs");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const outputRoot = path.join(root, ".release/metadata");
const relation = path.relative(root, outputRoot);
if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
  throw new Error(`Refusing to write release metadata outside the workspace: ${outputRoot}`);
}
fs.rmSync(outputRoot, { recursive: true, force: true });
fs.mkdirSync(outputRoot, { recursive: true });

const desktop = readJson("package.json");
const lock = readJson("package-lock.json");
const pythonReleaseLockPath = path.join(root, "packaging/python-windows-release-lock.txt");
const windowsToolchainLockPath = path.join(root, "packaging/windows-toolchain-lock.json");
const nsisIncludePath = path.join(root, "packaging/installer.nsh");
const windowsToolchainLock = readJson("packaging/windows-toolchain-lock.json");
fs.copyFileSync(
  windowsToolchainLockPath,
  path.join(outputRoot, "windows-toolchain-lock.json"),
);
const electronArchivePath = path.join(
  root,
  ".release/electron-dist",
  `electron-v${desktop.devDependencies.electron}-win32-x64.zip`,
);
const sidecarBundle = collectBundle(path.join(root, ".release/sidecar"));
const sidecarPayloadBundle = sidecarPayloadEntries(path.join(root, ".release/sidecar"));
const desktopArchiveInputs = desktopArchiveInputEntries(root, desktop);
const nodePackages = collectNodePackages(lock);
const pythonPackages = collectPythonPackages(path.join(root, ".release/sidecar-venv/Lib/site-packages"));
const lockedPythonRequirements = fs.readFileSync(pythonReleaseLockPath, "utf8")
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line && !line.startsWith("#"))
  .map((line) => {
    const match = line.match(/^([A-Za-z0-9][A-Za-z0-9._-]*)==([^ ]+) --hash=sha256:[a-f0-9]{64}$/);
    if (!match) throw new Error(`Invalid Python release lock entry while generating metadata: ${line}`);
    return { name: canonicalPythonName(match[1]), version: match[2] };
  });
const pythonPackageIdentities = pythonPackages.map((item) => ({
  name: canonicalPythonName(item.name),
  version: item.version,
})).sort((left, right) => `${left.name}@${left.version}`.localeCompare(`${right.name}@${right.version}`, "en"));
for (const requirement of lockedPythonRequirements) {
  if (!pythonPackageIdentities.some((item) => item.name === requirement.name && item.version === requirement.version)) {
    throw new Error(`Release venv metadata is missing locked Python component ${requirement.name}==${requirement.version}`);
  }
}
if (!pythonPackageIdentities.some((item) => (
  item.name === "webfa-desktop-runtime" && item.version === desktop.version
))) {
  throw new Error("Release venv metadata is missing the source-built WebFA wheel");
}
const components = [
  ...nodePackages.map((item) => ({ ...item, ecosystem: "npm" })),
  ...pythonPackages.map((item) => ({ ...item, ecosystem: "pypi" })),
  {
    name: "Electron",
    version: desktop.devDependencies.electron,
    license: "MIT",
    homepage: "https://www.electronjs.org/",
    ecosystem: "platform",
  },
  {
    name: "Chromium",
    version: "embedded by Electron",
    license: "NOASSERTION; see LICENSES.chromium.html",
    homepage: "https://www.chromium.org/",
    ecosystem: "platform",
  },
  {
    name: "CPython",
    version: "3.12",
    license: "Python-2.0",
    homepage: "https://www.python.org/",
    ecosystem: "platform",
  },
  {
    name: "PyInstaller bootloader",
    version: "6.21.0",
    license: "GPL-2.0-or-later WITH Bootloader-exception",
    homepage: "https://pyinstaller.org/",
    ecosystem: "platform",
  },
].sort((left, right) => `${left.ecosystem}:${left.name}@${left.version}`.localeCompare(
  `${right.ecosystem}:${right.name}@${right.version}`,
  "en",
));

const gitCommit = runText("git", ["rev-parse", "HEAD"], "unknown");
const gitDirty = runText("git", ["status", "--porcelain"], "unknown") !== "";
const created = process.env.SOURCE_DATE_EPOCH
  ? new Date(Number(process.env.SOURCE_DATE_EPOCH) * 1000).toISOString()
  : new Date().toISOString();
const buildManifest = {
  schema_version: 1,
  product: "webfa",
  release_version: desktop.version,
  runtime_protocol_version: 1,
  target: "windows-x64",
  desktop_sidecar_layout: "pyinstaller-onedir",
  electron_version: desktop.devDependencies.electron,
  electron_builder_version: windowsToolchainLock.electron_builder_version,
  node_version: process.version,
  python_build_runtime: runText("python", ["--version"], "unknown"),
  git_commit: gitCommit,
  source_tree_dirty: gitDirty,
  package_lock_sha256: hashFile(path.join(root, "package-lock.json")),
  python_release_lock_sha256: hashFile(pythonReleaseLockPath),
  windows_toolchain_lock_sha256: hashFile(windowsToolchainLockPath),
  electron_archive_sha256: hashFile(electronArchivePath),
  sidecar_bundle_sha256: bundleSha256(sidecarBundle),
  sidecar_payload_bundle_sha256: bundleSha256(sidecarPayloadBundle),
  sidecar_pe_payloads: sidecarPayloadBundle.filter((entry) => entry.path.toLowerCase().endsWith(".exe")),
  desktop_archive_input_sha256: bundleSha256(desktopArchiveInputs),
  python_release_component_count: pythonPackageIdentities.length,
  python_release_components_sha256: crypto
    .createHash("sha256")
    .update(JSON.stringify(pythonPackageIdentities))
    .digest("hex"),
  application_icon_sha256: hashFile(path.join(root, "packaging/webfa.ico")),
  nsis_include_sha256: hashFile(nsisIncludePath),
  generated_at: created,
};

const componentDigest = crypto.createHash("sha256").update(JSON.stringify(components)).digest("hex");
const documentDigest = crypto.createHash("sha256").update(JSON.stringify({
  components,
  gitCommit,
  created,
})).digest("hex");
const sbom = {
  spdxVersion: "SPDX-2.3",
  dataLicense: "CC0-1.0",
  SPDXID: "SPDXRef-DOCUMENT",
  name: `WebFA-${desktop.version}-windows-x64`,
  documentNamespace: `https://spdx.org/spdxdocs/WebFA-${desktop.version}-${documentDigest}`,
  creationInfo: {
    created,
    creators: ["Tool: WebFA generate-release-metadata.cjs"],
  },
  packages: components.map((item, index) => ({
    name: item.name,
    SPDXID: `SPDXRef-Package-${index + 1}`,
    versionInfo: item.version,
    downloadLocation: "NOASSERTION",
    filesAnalyzed: false,
    licenseConcluded: "NOASSERTION",
    licenseDeclared: normalizeSpdxLicense(item.license),
    copyrightText: "NOASSERTION",
    homepage: item.homepage || undefined,
    comment: `Ecosystem: ${item.ecosystem}; declared metadata: ${item.license}`,
  })),
  relationships: components.map((_, index) => ({
    spdxElementId: "SPDXRef-DOCUMENT",
    relationshipType: "DESCRIBES",
    relatedSpdxElement: `SPDXRef-Package-${index + 1}`,
  })),
};

const noticeLines = [
  "# WebFA Third-Party Component Notice",
  "",
  `Generated for WebFA ${desktop.version} (${created}).`,
  "",
  `This inventory combines the locked Node build/runtime dependency graph with the fresh Python release build/runtime environment: the ${lockedPythonRequirements.length} hash-locked requirements, interpreter-seeded pip, and the source-built WebFA wheel. Not every listed build tool is shipped in the runtime. It does not replace upstream license texts. Electron also ships \`LICENSE.electron.txt\` and \`LICENSES.chromium.html\` beside the application executable.`,
  "",
  "| Ecosystem | Component | Version | Declared license |",
  "| --- | --- | --- | --- |",
  ...components.map((item) => `| ${escapeTable(item.ecosystem)} | ${escapeTable(item.name)} | ${escapeTable(item.version)} | ${escapeTable(item.license)} |`),
  "",
];

const sbomText = `${JSON.stringify(sbom, null, 2)}\n`;
const noticeText = `${noticeLines.join("\n")}\n`;
buildManifest.sbom_sha256 = sha256Text(sbomText);
buildManifest.third_party_notices_sha256 = sha256Text(noticeText);
writeJson("build-manifest.json", buildManifest);
fs.writeFileSync(path.join(outputRoot, "SBOM.spdx.json"), sbomText, "utf8");
fs.writeFileSync(path.join(outputRoot, "THIRD_PARTY_NOTICES.md"), noticeText, "utf8");
process.stdout.write(`${JSON.stringify({
  status: "pass",
  outputRoot,
  components: components.length,
  componentDigest,
  gitCommit,
  sourceTreeDirty: gitDirty,
})}\n`);

function collectNodePackages(lockfile) {
  const unique = new Map();
  for (const [entryPath, entry] of Object.entries(lockfile.packages ?? {})) {
    if (!entryPath.includes("node_modules/") || !entry.version) continue;
    const name = entry.name || entryPath.split("node_modules/").at(-1);
    const installedManifest = path.join(root, entryPath, "package.json");
    let manifest = {};
    if (fs.existsSync(installedManifest)) {
      try { manifest = JSON.parse(fs.readFileSync(installedManifest, "utf8")); } catch { /* ignore */ }
    }
    const key = `${name}@${entry.version}`;
    if (!unique.has(key)) {
      unique.set(key, {
        name,
        version: entry.version,
        license: stringifyLicense(entry.license || manifest.license),
        homepage: stringifyHomepage(manifest.homepage),
      });
    }
  }
  return [...unique.values()];
}

function collectPythonPackages(sitePackagesRoot) {
  if (!fs.statSync(sitePackagesRoot).isDirectory()) {
    throw new Error(`Missing fresh release-venv package metadata: ${sitePackagesRoot}`);
  }
  const packages = [];
  for (const entry of fs.readdirSync(sitePackagesRoot, { withFileTypes: true })) {
    if (!entry.isDirectory() || !entry.name.endsWith(".dist-info")) continue;
    const metadataPath = path.join(sitePackagesRoot, entry.name, "METADATA");
    if (!fs.existsSync(metadataPath)) continue;
    const metadata = parseMetadata(fs.readFileSync(metadataPath, "utf8"));
    packages.push({
      name: metadata.Name || entry.name.replace(/\.dist-info$/, ""),
      version: metadata.Version || "unknown",
      license: stringifyLicense(metadata["License-Expression"] || metadata.License),
      homepage: metadata["Home-page"] || firstProjectUrl(metadata["Project-URL"]),
    });
  }
  return packages;
}

function canonicalPythonName(value) {
  return String(value).toLowerCase().replace(/[-_.]+/g, "-");
}

function parseMetadata(text) {
  const values = {};
  let key;
  for (const line of text.split(/\r?\n/)) {
    if (!line) break;
    if (/^[ \t]/.test(line) && key) {
      values[key] = `${values[key]} ${line.trim()}`;
      continue;
    }
    const separator = line.indexOf(":");
    if (separator < 1) continue;
    key = line.slice(0, separator);
    if (!(key in values)) values[key] = line.slice(separator + 1).trim();
  }
  return values;
}

function firstProjectUrl(value) {
  if (!value) return undefined;
  const separator = value.indexOf(",");
  return separator >= 0 ? value.slice(separator + 1).trim() : value;
}

function stringifyLicense(value) {
  if (Array.isArray(value)) return value.join(" OR ");
  if (value && typeof value === "object") return JSON.stringify(value);
  return typeof value === "string" && value.trim() ? value.trim() : "NOASSERTION";
}

function stringifyHomepage(value) {
  if (typeof value === "string") return value;
  return value?.url;
}

function normalizeSpdxLicense(value) {
  if (!value || value === "NOASSERTION") return "NOASSERTION";
  const normalizedValue = String(value).trim() === "PSF" ? "PSF-2.0" : String(value).trim();
  const licenseIds = new Set([
    "0BSD",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "BlueOak-1.0.0",
    "CC-BY-4.0",
    "CC0-1.0",
    "GPL-2.0-or-later",
    "ISC",
    "LGPL-3.0-or-later",
    "MIT",
    "MPL-2.0",
    "PSF-2.0",
    "Python-2.0",
    "WTFPL",
  ]);
  const exceptionIds = new Set(["Bootloader-exception"]);
  const tokens = normalizedValue.match(/\(|\)|[^\s()]+/g) ?? [];
  let index = 0;

  const parsePrimary = () => {
    if (tokens[index] === "(") {
      index += 1;
      if (!parseOr() || tokens[index] !== ")") return false;
      index += 1;
      return true;
    }
    if (!licenseIds.has(tokens[index])) return false;
    index += 1;
    if (tokens[index] === "WITH") {
      index += 1;
      if (!exceptionIds.has(tokens[index])) return false;
      index += 1;
    }
    return true;
  };
  const parseAnd = () => {
    if (!parsePrimary()) return false;
    while (tokens[index] === "AND") {
      index += 1;
      if (!parsePrimary()) return false;
    }
    return true;
  };
  const parseOr = () => {
    if (!parseAnd()) return false;
    while (tokens[index] === "OR") {
      index += 1;
      if (!parseAnd()) return false;
    }
    return true;
  };

  return tokens.length > 0 && parseOr() && index === tokens.length ? normalizedValue : "NOASSERTION";
}

function sha256Text(value) {
  return crypto.createHash("sha256").update(Buffer.from(value, "utf8")).digest("hex");
}

function escapeTable(value) {
  return String(value ?? "NOASSERTION").replaceAll("|", "\\|").replaceAll("\n", " ");
}

function runText(command, args, fallback) {
  try {
    return execFileSync(command, args, { cwd: root, encoding: "utf8", windowsHide: true }).trim();
  } catch {
    return fallback;
  }
}

function readJson(relativePath) {
  return JSON.parse(fs.readFileSync(path.join(root, relativePath), "utf8"));
}

function writeJson(name, value) {
  fs.writeFileSync(path.join(outputRoot, name), `${JSON.stringify(value, null, 2)}\n`, "utf8");
}
