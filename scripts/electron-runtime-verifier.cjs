const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const zipInventoryScript = String.raw`
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::OpenRead($env:WEBFA_ELECTRON_ARCHIVE)
try {
  [array]$entries = foreach ($entry in $archive.Entries) {
    if ($entry.FullName.EndsWith("/", [StringComparison]::Ordinal)) { continue }
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
      $stream = $entry.Open()
      try {
        $hash = ([BitConverter]::ToString($sha.ComputeHash($stream))).Replace("-", "").ToLowerInvariant()
      } finally {
        $stream.Dispose()
      }
    } finally {
      $sha.Dispose()
    }
    [pscustomobject]@{
      path = $entry.FullName
      bytes = $entry.Length
      sha256 = $hash
      externalAttributes = $entry.ExternalAttributes
    }
  }
  ConvertTo-Json -InputObject $entries -Depth 3 -Compress
} finally {
  $archive.Dispose()
}
`;

const sha256File = (target) =>
  crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");

const verifySafeArchivePath = (archivePath) => {
  const parts = archivePath.split("/");
  if (
    archivePath.length === 0 ||
    archivePath.startsWith("/") ||
    archivePath.endsWith("/") ||
    archivePath.includes("\\") ||
    archivePath.includes("\0") ||
    archivePath.includes(":") ||
    parts.some((part) => part.length === 0 || part === "." || part === "..")
  ) {
    throw new Error(`Pinned Electron archive contains an unsafe path: ${JSON.stringify(archivePath)}`);
  }
};

const verifyElectronRuntimeFromArchive = (archivePath, unpackedRoot) => {
  for (const [label, target] of [["archive", archivePath], ["unpacked root", unpackedRoot]]) {
    const stat = fs.lstatSync(target);
    if (label === "archive" ? !stat.isFile() : !stat.isDirectory()) {
      throw new Error(`Electron ${label} has an unexpected filesystem type: ${target}`);
    }
    if (stat.isSymbolicLink()) {
      throw new Error(`Electron ${label} must not be a symbolic link: ${target}`);
    }
  }

  const inventory = JSON.parse(execFileSync(
    "powershell.exe",
    ["-NoProfile", "-NonInteractive", "-Command", zipInventoryScript],
    {
      cwd: unpackedRoot,
      encoding: "utf8",
      maxBuffer: 4 * 1024 * 1024,
      windowsHide: true,
      env: { ...process.env, WEBFA_ELECTRON_ARCHIVE: archivePath },
    },
  ));
  if (!Array.isArray(inventory) || inventory.length < 50) {
    throw new Error("Pinned Electron archive has an implausible runtime inventory");
  }

  const sourcePaths = new Set();
  const packagedPaths = new Set();
  const verifiedInventory = [];
  let executableEntry;
  let verifiedBytes = 0;
  for (const entry of inventory) {
    if (
      entry === null ||
      typeof entry !== "object" ||
      typeof entry.path !== "string" ||
      !Number.isSafeInteger(entry.bytes) ||
      entry.bytes < 0 ||
      !/^[a-f0-9]{64}$/.test(entry.sha256) ||
      !Number.isInteger(entry.externalAttributes)
    ) {
      throw new Error("Pinned Electron archive inventory contains malformed metadata");
    }
    verifySafeArchivePath(entry.path);
    const sourceKey = entry.path.toLowerCase();
    if (sourcePaths.has(sourceKey)) {
      throw new Error(`Pinned Electron archive contains a case-insensitive duplicate: ${entry.path}`);
    }
    sourcePaths.add(sourceKey);

    const posixMode = (entry.externalAttributes >>> 16) & 0xf000;
    if (posixMode === 0xa000) {
      throw new Error(`Pinned Electron archive contains a symbolic link: ${entry.path}`);
    }
    if (entry.path === "electron.exe") {
      executableEntry = entry;
      continue;
    }

    const packagedPath = entry.path === "LICENSE" ? "LICENSE.electron.txt" : entry.path;
    const packagedKey = packagedPath.toLowerCase();
    if (packagedPaths.has(packagedKey)) {
      throw new Error(`Electron archive entries map to one packaged path: ${packagedPath}`);
    }
    packagedPaths.add(packagedKey);
    const packagedTarget = path.join(unpackedRoot, ...packagedPath.split("/"));
    const packagedStat = fs.lstatSync(packagedTarget);
    if (!packagedStat.isFile() || packagedStat.isSymbolicLink()) {
      throw new Error(`Packaged Electron runtime entry is not a regular file: ${packagedPath}`);
    }
    if (packagedStat.size !== entry.bytes || sha256File(packagedTarget) !== entry.sha256) {
      throw new Error(`Packaged Electron runtime differs from the pinned archive: ${packagedPath}`);
    }
    verifiedBytes += entry.bytes;
    verifiedInventory.push({
      sourcePath: entry.path,
      packagedPath,
      bytes: entry.bytes,
      sha256: entry.sha256,
    });
  }

  if (!executableEntry || executableEntry.bytes < 100 * 1024 * 1024) {
    throw new Error("Pinned Electron archive is missing its expected executable payload");
  }
  for (const requiredPath of ["LICENSE", "LICENSES.chromium.html", "resources/default_app.asar"]) {
    if (!sourcePaths.has(requiredPath.toLowerCase())) {
      throw new Error(`Pinned Electron archive is missing required runtime material: ${requiredPath}`);
    }
  }

  verifiedInventory.sort((left, right) => left.packagedPath.localeCompare(right.packagedPath, "en"));
  return {
    archiveEntries: inventory.length,
    electronExecutableBytes: executableEntry.bytes,
    packagedPaths: verifiedInventory.map((entry) => entry.packagedPath),
    verifiedFiles: verifiedInventory.length,
    verifiedBytes,
    runtimeInventorySha256: crypto
      .createHash("sha256")
      .update(JSON.stringify(verifiedInventory))
      .digest("hex"),
  };
};

module.exports = { verifyElectronRuntimeFromArchive };
