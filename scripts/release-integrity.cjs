const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

function hashBytes(bytes) {
  return crypto.createHash("sha256").update(bytes).digest("hex");
}

function hashFile(target) {
  const stat = fs.lstatSync(target);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error(`Invalid release hash input: ${target}`);
  return hashBytes(fs.readFileSync(target));
}

function collectBundle(bundleRoot, prefix = "") {
  const files = [];
  const pending = [bundleRoot];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const target = path.join(current, entry.name);
      const stat = fs.lstatSync(target);
      const relative = path.relative(bundleRoot, target).replaceAll(path.sep, "/");
      const releasePath = prefix ? `${prefix.replace(/\/$/, "")}/${relative}` : relative;
      if (stat.isSymbolicLink()) throw new Error(`Release bundle contains a link: ${releasePath}`);
      if (entry.isDirectory()) {
        pending.push(target);
        continue;
      }
      if (!entry.isFile()) throw new Error(`Release bundle contains a non-file entry: ${releasePath}`);
      files.push({ path: releasePath, bytes: stat.size, sha256: hashFile(target) });
    }
  }
  return files.sort((left, right) => left.path.localeCompare(right.path, "en"));
}

function bundleSha256(entries) {
  return hashBytes(Buffer.from(JSON.stringify(entries)));
}

function canonicalJsonBytes(value) {
  const canonicalize = (item) => {
    if (Array.isArray(item)) return item.map(canonicalize);
    if (!item || typeof item !== "object") return item;
    return Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonicalize(item[key])]));
  };
  return Buffer.from(JSON.stringify(canonicalize(value)));
}

function releaseDesktopManifest(sourceManifest) {
  const manifest = structuredClone(sourceManifest);
  for (const removedKey of ["scripts", "dependencies", "devDependencies"]) delete manifest[removedKey];
  return manifest;
}

function desktopArchiveInputEntries(root, sourceManifest) {
  const manifest = releaseDesktopManifest(sourceManifest);
  const manifestBytes = canonicalJsonBytes(manifest);
  return [
    ...collectBundle(
      path.join(root, "apps/desktop/electron/dist"),
      "apps/desktop/electron/dist",
    ),
    ...collectBundle(
      path.join(root, "apps/desktop/renderer/out"),
      "apps/desktop/renderer/out",
    ),
    { path: "package.json", bytes: manifestBytes.length, sha256: hashBytes(manifestBytes) },
  ].sort((left, right) => left.path.localeCompare(right.path, "en"));
}

function portableExecutablePayload(target, expectedPayloadBytes) {
  const bytes = fs.readFileSync(target);
  if (bytes.length < 256 || bytes.readUInt16LE(0) !== 0x5a4d) {
    throw new Error(`Invalid PE executable: ${target}`);
  }
  const peOffset = bytes.readUInt32LE(0x3c);
  if (peOffset + 24 > bytes.length || bytes.readUInt32LE(peOffset) !== 0x00004550) {
    throw new Error(`Invalid PE signature: ${target}`);
  }
  const optionalHeaderSize = bytes.readUInt16LE(peOffset + 20);
  const optionalHeader = peOffset + 24;
  const optionalEnd = optionalHeader + optionalHeaderSize;
  if (optionalEnd > bytes.length) throw new Error(`Truncated PE optional header: ${target}`);
  const magic = bytes.readUInt16LE(optionalHeader);
  const dataDirectory = optionalHeader + (magic === 0x20b ? 112 : magic === 0x10b ? 96 : -1);
  if (dataDirectory < optionalHeader || dataDirectory + 40 > optionalEnd) {
    throw new Error(`Unsupported PE optional header: ${target}`);
  }
  const checksumOffset = optionalHeader + 64;
  const securityDirectory = dataDirectory + 4 * 8;
  const certificateOffset = bytes.readUInt32LE(securityDirectory);
  const certificateBytes = bytes.readUInt32LE(securityDirectory + 4);
  if ((certificateOffset === 0) !== (certificateBytes === 0)) {
    throw new Error(`Invalid PE certificate directory: ${target}`);
  }
  if (certificateOffset && certificateOffset + certificateBytes !== bytes.length) {
    throw new Error(`PE certificate table is not the final file payload: ${target}`);
  }
  if (certificateOffset) validateCertificateTable(bytes, certificateOffset, certificateBytes, target);

  let payloadEnd = certificateOffset || bytes.length;
  if (certificateOffset) {
    if (!Number.isInteger(expectedPayloadBytes) || expectedPayloadBytes <= optionalEnd) {
      throw new Error(`Signed PE requires its manifest-bound unsigned payload length: ${target}`);
    }
    const alignedPayloadBytes = Math.ceil(expectedPayloadBytes / 8) * 8;
    if (
      certificateOffset !== alignedPayloadBytes ||
      bytes.subarray(expectedPayloadBytes, certificateOffset).some((value) => value !== 0)
    ) {
      throw new Error(`Signed PE padding differs from its manifest-bound unsigned payload: ${target}`);
    }
    payloadEnd = expectedPayloadBytes;
  } else if (expectedPayloadBytes !== undefined && bytes.length !== expectedPayloadBytes) {
    throw new Error(`Unsigned PE length differs from its build manifest: ${target}`);
  }
  const payload = Buffer.from(bytes.subarray(0, payloadEnd));
  payload.fill(0, checksumOffset, checksumOffset + 4);
  payload.fill(0, securityDirectory, securityDirectory + 8);
  return { bytes: payload.length, sha256: hashBytes(payload) };
}

function validateCertificateTable(bytes, certificateOffset, certificateBytes, target) {
  if (certificateOffset % 8 !== 0 || certificateBytes < 8) {
    throw new Error(`Invalid PE WIN_CERTIFICATE table alignment: ${target}`);
  }
  const certificateEnd = certificateOffset + certificateBytes;
  let cursor = certificateOffset;
  let entries = 0;
  while (cursor < certificateEnd) {
    if (certificateEnd - cursor < 8) {
      throw new Error(`Truncated PE WIN_CERTIFICATE entry: ${target}`);
    }
    const entryBytes = bytes.readUInt32LE(cursor);
    const revision = bytes.readUInt16LE(cursor + 4);
    const certificateType = bytes.readUInt16LE(cursor + 6);
    if (
      entryBytes <= 8 ||
      revision !== 0x0200 ||
      certificateType !== 0x0002 ||
      cursor + entryBytes > certificateEnd
    ) {
      throw new Error(`Invalid PE WIN_CERTIFICATE entry: ${target}`);
    }
    const alignedEntryEnd = cursor + Math.ceil(entryBytes / 8) * 8;
    if (
      alignedEntryEnd > certificateEnd ||
      bytes.subarray(cursor + entryBytes, alignedEntryEnd).some((value) => value !== 0)
    ) {
      throw new Error(`Invalid PE WIN_CERTIFICATE padding: ${target}`);
    }
    cursor = alignedEntryEnd;
    entries += 1;
  }
  if (cursor !== certificateEnd || entries !== 1) {
    throw new Error(`PE must contain exactly one WIN_CERTIFICATE entry: ${target}`);
  }
}

function sidecarPayloadEntries(bundleRoot, expectedPePayloads) {
  const expected = expectedPePayloads
    ? new Map(expectedPePayloads.map((entry) => [entry.path, entry]))
    : null;
  return collectBundle(bundleRoot).map((entry) => {
    if (!entry.path.toLowerCase().endsWith(".exe")) return entry;
    const expectedEntry = expected?.get(entry.path);
    if (expected && !expectedEntry) {
      throw new Error(`Packaged sidecar has an unmanifested executable: ${entry.path}`);
    }
    const payload = portableExecutablePayload(path.join(bundleRoot, entry.path), expectedEntry?.bytes);
    if (expectedEntry && payload.sha256 !== expectedEntry.sha256) {
      throw new Error(`Packaged sidecar executable payload changed: ${entry.path}`);
    }
    return { path: entry.path, ...payload };
  });
}

module.exports = {
  bundleSha256,
  canonicalJsonBytes,
  collectBundle,
  desktopArchiveInputEntries,
  hashBytes,
  hashFile,
  portableExecutablePayload,
  releaseDesktopManifest,
  sidecarPayloadEntries,
};
