const assert = require("node:assert/strict");
const asar = require("@electron/asar");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const verifier = path.resolve(__dirname, "../../scripts/verify-unpacked-release.cjs");

function verifyAsarEnvelope(archive) {
  return spawnSync(process.execPath, [verifier, "--verify-asar-envelope-only", archive], {
    encoding: "utf8",
    windowsHide: true,
  });
}

test("ASAR envelope rejects trailing and truncated physical payload bytes", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-asar-envelope-"));
  const source = path.join(root, "source");
  const archive = path.join(root, "app.asar");
  await fs.mkdir(path.join(source, "nested"), { recursive: true });
  await fs.writeFile(path.join(source, "entry.js"), "globalThis.webfa = true;\n");
  await fs.writeFile(path.join(source, "nested", "data.json"), '{"ready":true}\n');
  try {
    await asar.createPackage(source, archive);
    const original = await fs.readFile(archive);
    const verified = verifyAsarEnvelope(archive);
    assert.equal(verified.status, 0, verified.stderr);
    const evidence = JSON.parse(verified.stdout);
    assert.equal(evidence.physicalBytes, original.length);
    assert.equal(evidence.packedFiles, 2);

    await fs.writeFile(archive, Buffer.concat([original, Buffer.from([0xa5])]));
    const trailing = verifyAsarEnvelope(archive);
    assert.notEqual(trailing.status, 0);
    assert.match(trailing.stderr, /ASAR physical length does not exactly match packed payload/);

    await fs.writeFile(archive, original.subarray(0, original.length - 1));
    const truncated = verifyAsarEnvelope(archive);
    assert.notEqual(truncated.status, 0);
    assert.match(
      truncated.stderr,
      /ASAR physical length does not exactly match packed payload|ASAR packed payload integrity differs/,
    );
  } finally {
    await fs.rm(root, { recursive: true, force: true });
  }
});
