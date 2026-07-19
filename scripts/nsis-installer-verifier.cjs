const { execFileSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { getPath7za } = require("app-builder-lib/out/toolsets/7zip.js");
const {
  bundleSha256,
  collectBundle,
  portableExecutablePayload,
} = require("./release-integrity.cjs");

const NSIS_SIGNATURE = Buffer.from([
  0xef, 0xbe, 0xad, 0xde,
  0x4e, 0x75, 0x6c, 0x6c, 0x73, 0x6f, 0x66, 0x74, 0x49, 0x6e, 0x73, 0x74,
]);

const parseNsisEnvelope = (installerPath) => {
  const bytes = fs.readFileSync(installerPath);
  if (bytes.length < 1024 * 1024 || bytes.readUInt16LE(0) !== 0x5a4d) {
    throw new Error("Windows installer is not a plausible PE executable");
  }
  const peOffset = bytes.readUInt32LE(0x3c);
  if (peOffset + 24 > bytes.length || bytes.readUInt32LE(peOffset) !== 0x00004550) {
    throw new Error("Windows installer has an invalid PE signature");
  }
  const sectionCount = bytes.readUInt16LE(peOffset + 6);
  const optionalHeaderSize = bytes.readUInt16LE(peOffset + 20);
  const optionalHeader = peOffset + 24;
  const optionalEnd = optionalHeader + optionalHeaderSize;
  const sectionTableEnd = optionalEnd + sectionCount * 40;
  if (sectionCount < 1 || sectionCount > 32 || sectionTableEnd > bytes.length) {
    throw new Error("Windows installer has an invalid PE section table");
  }
  const magic = bytes.readUInt16LE(optionalHeader);
  const dataDirectory = optionalHeader + (magic === 0x20b ? 112 : magic === 0x10b ? 96 : -1);
  if (dataDirectory < optionalHeader || dataDirectory + 40 > optionalEnd) {
    throw new Error("Windows installer has an unsupported PE optional header");
  }
  const securityDirectory = dataDirectory + 4 * 8;
  const certificateOffset = bytes.readUInt32LE(securityDirectory);
  const certificateBytes = bytes.readUInt32LE(securityDirectory + 4);
  if ((certificateOffset === 0) !== (certificateBytes === 0)) {
    throw new Error("Windows installer has an invalid PE certificate directory");
  }
  if (certificateOffset && certificateOffset + certificateBytes !== bytes.length) {
    throw new Error("Windows installer certificate table is not the final file payload");
  }
  const payloadLimit = certificateOffset || bytes.length;

  const rawRanges = [];
  let nsisOffset = 0;
  for (let index = 0; index < sectionCount; index += 1) {
    const sectionOffset = optionalEnd + index * 40;
    const name = bytes
      .subarray(sectionOffset, sectionOffset + 8)
      .toString("ascii")
      .replace(/\0.*$/, "");
    const rawSize = bytes.readUInt32LE(sectionOffset + 16);
    const rawPointer = bytes.readUInt32LE(sectionOffset + 20);
    if ((rawSize === 0) !== (rawPointer === 0)) {
      throw new Error(`Windows installer PE section has an incomplete raw range: ${name}`);
    }
    if (rawSize === 0) continue;
    const rawEnd = rawPointer + rawSize;
    if (!Number.isSafeInteger(rawEnd) || rawPointer < sectionTableEnd || rawEnd > payloadLimit) {
      throw new Error(`Windows installer PE section is outside the executable payload: ${name}`);
    }
    rawRanges.push({ name, start: rawPointer, end: rawEnd });
    nsisOffset = Math.max(nsisOffset, rawEnd);
  }
  rawRanges.sort((left, right) => left.start - right.start || left.end - right.end);
  for (let index = 1; index < rawRanges.length; index += 1) {
    if (rawRanges[index].start < rawRanges[index - 1].end) {
      throw new Error("Windows installer PE sections overlap on disk");
    }
  }
  if (nsisOffset + 28 > payloadLimit) {
    throw new Error("Windows installer is missing its NSIS data envelope");
  }
  if (!bytes.subarray(nsisOffset + 4, nsisOffset + 20).equals(NSIS_SIGNATURE)) {
    throw new Error("Windows installer has an invalid NSIS signature");
  }
  const nsisBytes = bytes.readUInt32LE(nsisOffset + 24);
  const unsignedPayloadBytes = nsisOffset + nsisBytes;
  if (
    nsisBytes < 1024 * 1024 ||
    unsignedPayloadBytes > payloadLimit ||
    payloadLimit - unsignedPayloadBytes > 7 ||
    bytes.subarray(unsignedPayloadBytes, payloadLimit).some((value) => value !== 0)
  ) {
    throw new Error("Windows installer NSIS physical size does not match its PE payload");
  }
  const canonicalPePayload = portableExecutablePayload(installerPath, unsignedPayloadBytes);
  return {
    canonicalPePayloadSha256: canonicalPePayload.sha256,
    nsisBytes,
    nsisOffset,
    peSections: rawRanges.map((entry) => entry.name),
    signedCertificateBytes: certificateBytes,
    unsignedPayloadBytes,
  };
};

const run7za = (sevenZip, args, cwd) => execFileSync(
  sevenZip,
  [...args, "-sccUTF-8"],
  {
    cwd,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  },
);

const verifyNsisInstallerPayload = async (installerPath, unpackedRoot) => {
  const envelope = parseNsisEnvelope(installerPath);
  const sevenZip = await getPath7za();
  const listing = run7za(sevenZip, ["l", "-slt", installerPath], path.dirname(installerPath));
  if (!/(?:^|\r?\n)Type = 7z(?:\r?\n|$)/.test(listing)) {
    throw new Error("Pinned 7-Zip did not locate the NSIS embedded 7z application archive");
  }
  const readArchiveInteger = (field) => {
    const matches = [...listing.matchAll(new RegExp(`^${field} = ([0-9]+)\\r?$`, "gm"))];
    if (matches.length !== 1) {
      throw new Error(`Pinned 7-Zip reported an ambiguous embedded archive ${field}`);
    }
    const value = Number(matches[0][1]);
    if (!Number.isSafeInteger(value) || value < 0) {
      throw new Error(`Pinned 7-Zip reported an invalid embedded archive ${field}`);
    }
    return value;
  };
  const archiveOffset = readArchiveInteger("Offset");
  const archiveBytes = readArchiveInteger("Physical Size");
  const archiveTailBytes = readArchiveInteger("Tail Size");
  const installerBytes = fs.readFileSync(installerPath);
  if (
    archiveOffset < envelope.nsisOffset ||
    archiveBytes < 1024 * 1024 ||
    archiveOffset + archiveBytes > envelope.unsignedPayloadBytes ||
    archiveOffset + archiveBytes + archiveTailBytes !== installerBytes.length
  ) {
    throw new Error("NSIS embedded 7z physical range is inconsistent with the verified installer envelope");
  }
  const appArchiveBytes = installerBytes.subarray(archiveOffset, archiveOffset + archiveBytes);
  if (!appArchiveBytes.subarray(0, 6).equals(Buffer.from([0x37, 0x7a, 0xbc, 0xaf, 0x27, 0x1c]))) {
    throw new Error("NSIS application payload is not a plausible 7z archive");
  }

  const tempBase = fs.realpathSync(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempBase, "webfa-nsis-verify-"));
  const resolvedTempRoot = fs.realpathSync(tempRoot);
  if (!resolvedTempRoot.startsWith(`${tempBase}${path.sep}`)) {
    throw new Error("NSIS verification temporary directory escaped the system temp root");
  }
  const payloadRoot = path.join(resolvedTempRoot, "payload");
  fs.mkdirSync(payloadRoot);
  try {
    let archiveTest;
    try {
      archiveTest = run7za(sevenZip, ["t", "-bd", "-bb0", installerPath], resolvedTempRoot);
    } catch {
      throw new Error("NSIS application archive failed the pinned 7-Zip integrity test");
    }
    if (!archiveTest.includes("Everything is Ok")) {
      throw new Error("NSIS application archive did not pass the pinned 7-Zip integrity test");
    }
    run7za(sevenZip, ["x", "-y", "-bd", "-bb0", `-o${payloadRoot}`, installerPath], resolvedTempRoot);

    const expectedPayload = collectBundle(unpackedRoot);
    const extractedPayload = collectBundle(payloadRoot);
    if (JSON.stringify(extractedPayload) !== JSON.stringify(expectedPayload)) {
      throw new Error("NSIS embedded application payload differs from win-unpacked");
    }
    return {
      ...envelope,
      appArchiveBytes: archiveBytes,
      appArchiveSha256: crypto.createHash("sha256").update(appArchiveBytes).digest("hex"),
      appArchiveSha512: crypto.createHash("sha512").update(appArchiveBytes).digest("hex"),
      archiveOffset,
      archiveTailBytes,
      embeddedPayloadBundleSha256: bundleSha256(extractedPayload),
      embeddedPayloadFiles: extractedPayload.length,
    };
  } finally {
    fs.rmSync(resolvedTempRoot, { force: true, maxRetries: 3, recursive: true });
  }
};

module.exports = { parseNsisEnvelope, verifyNsisInstallerPayload };
