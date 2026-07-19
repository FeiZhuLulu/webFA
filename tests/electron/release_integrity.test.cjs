const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { portableExecutablePayload } = require("../../scripts/release-integrity.cjs");
const { parseNsisEnvelope } = require("../../scripts/nsis-installer-verifier.cjs");

const PE_OFFSET = 0x80;
const OPTIONAL_HEADER = PE_OFFSET + 24;
const OPTIONAL_HEADER_BYTES = 240;
const SECURITY_DIRECTORY = OPTIONAL_HEADER + 112 + 4 * 8;

const initializePeHeaders = (bytes, sectionCount = 0) => {
  bytes.writeUInt16LE(0x5a4d, 0);
  bytes.writeUInt32LE(PE_OFFSET, 0x3c);
  bytes.writeUInt32LE(0x00004550, PE_OFFSET);
  bytes.writeUInt16LE(sectionCount, PE_OFFSET + 6);
  bytes.writeUInt16LE(OPTIONAL_HEADER_BYTES, PE_OFFSET + 20);
  bytes.writeUInt16LE(0x20b, OPTIONAL_HEADER);
};

const writeCertificateDirectory = (bytes, offset, size) => {
  bytes.writeUInt32LE(offset, SECURITY_DIRECTORY);
  bytes.writeUInt32LE(size, SECURITY_DIRECTORY + 4);
};

const writeCertificateEntry = (bytes, offset, entryBytes = 11) => {
  bytes.writeUInt32LE(entryBytes, offset);
  bytes.writeUInt16LE(0x0200, offset + 4);
  bytes.writeUInt16LE(0x0002, offset + 6);
  bytes.fill(0xa5, offset + 8, offset + entryBytes);
};

test("PE canonical payload is invariant only across a structurally valid Authenticode table", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "webfa-pe-integrity-"));
  try {
    const unsignedPath = path.join(tempRoot, "unsigned.exe");
    const signedPath = path.join(tempRoot, "signed.exe");
    const unsignedBytes = Buffer.alloc(509);
    initializePeHeaders(unsignedBytes);
    for (let index = OPTIONAL_HEADER + OPTIONAL_HEADER_BYTES; index < unsignedBytes.length; index += 1) {
      unsignedBytes[index] = index % 251;
    }
    fs.writeFileSync(unsignedPath, unsignedBytes);
    const unsignedIdentity = portableExecutablePayload(unsignedPath);

    const signedBytes = Buffer.alloc(528);
    unsignedBytes.copy(signedBytes);
    writeCertificateDirectory(signedBytes, 512, 16);
    writeCertificateEntry(signedBytes, 512);
    fs.writeFileSync(signedPath, signedBytes);
    const signedIdentity = portableExecutablePayload(signedPath, unsignedBytes.length);
    assert.deepEqual(signedIdentity, unsignedIdentity);

    const badPreCertificatePadding = Buffer.from(signedBytes);
    badPreCertificatePadding[510] = 1;
    fs.writeFileSync(signedPath, badPreCertificatePadding);
    assert.throws(
      () => portableExecutablePayload(signedPath, unsignedBytes.length),
      /Signed PE padding differs from its manifest-bound unsigned payload/,
    );

    const badCertificatePadding = Buffer.from(signedBytes);
    badCertificatePadding[527] = 1;
    fs.writeFileSync(signedPath, badCertificatePadding);
    assert.throws(
      () => portableExecutablePayload(signedPath, unsignedBytes.length),
      /Invalid PE WIN_CERTIFICATE padding/,
    );

    const multipleEntries = Buffer.alloc(544);
    unsignedBytes.copy(multipleEntries);
    writeCertificateDirectory(multipleEntries, 512, 32);
    writeCertificateEntry(multipleEntries, 512, 9);
    writeCertificateEntry(multipleEntries, 528, 9);
    fs.writeFileSync(signedPath, multipleEntries);
    assert.throws(
      () => portableExecutablePayload(signedPath, unsignedBytes.length),
      /PE must contain exactly one WIN_CERTIFICATE entry/,
    );
  } finally {
    fs.rmSync(tempRoot, { force: true, recursive: true });
  }
});

test("NSIS physical envelope rejects trailing, truncated, and signature-corrupted payloads", () => {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), "webfa-nsis-envelope-"));
  try {
    const installerPath = path.join(tempRoot, "setup.exe");
    const sectionRawPointer = 512;
    const sectionRawBytes = 512;
    const nsisOffset = sectionRawPointer + sectionRawBytes;
    const nsisBytes = 1024 * 1024 + 32;
    const installerBytes = Buffer.alloc(nsisOffset + nsisBytes);
    initializePeHeaders(installerBytes, 1);
    const sectionHeader = OPTIONAL_HEADER + OPTIONAL_HEADER_BYTES;
    installerBytes.write(".text", sectionHeader, "ascii");
    installerBytes.writeUInt32LE(sectionRawBytes, sectionHeader + 16);
    installerBytes.writeUInt32LE(sectionRawPointer, sectionHeader + 20);
    installerBytes.writeUInt32LE(0, nsisOffset);
    Buffer.from([
      0xef, 0xbe, 0xad, 0xde,
      0x4e, 0x75, 0x6c, 0x6c, 0x73, 0x6f, 0x66, 0x74, 0x49, 0x6e, 0x73, 0x74,
    ]).copy(installerBytes, nsisOffset + 4);
    installerBytes.writeUInt32LE(0, nsisOffset + 20);
    installerBytes.writeUInt32LE(nsisBytes, nsisOffset + 24);
    fs.writeFileSync(installerPath, installerBytes);

    const envelope = parseNsisEnvelope(installerPath);
    assert.equal(envelope.nsisOffset, nsisOffset);
    assert.equal(envelope.nsisBytes, nsisBytes);
    assert.equal(envelope.unsignedPayloadBytes, installerBytes.length);

    fs.writeFileSync(installerPath, Buffer.concat([installerBytes, Buffer.from([0])]));
    assert.throws(
      () => parseNsisEnvelope(installerPath),
      /Unsigned PE length differs from its build manifest/,
    );

    fs.writeFileSync(installerPath, installerBytes.subarray(0, installerBytes.length - 1));
    assert.throws(
      () => parseNsisEnvelope(installerPath),
      /NSIS physical size does not match its PE payload/,
    );

    const badSignature = Buffer.from(installerBytes);
    badSignature[nsisOffset + 4] ^= 0xff;
    fs.writeFileSync(installerPath, badSignature);
    assert.throws(() => parseNsisEnvelope(installerPath), /invalid NSIS signature/);
  } finally {
    fs.rmSync(tempRoot, { force: true, recursive: true });
  }
});
