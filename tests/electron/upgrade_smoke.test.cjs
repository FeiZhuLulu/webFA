"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  compareSemver,
  parseArguments,
  parseSemver,
  validateUpgradeIdentity,
} = require("../../scripts/smoke-upgrade-desktop.cjs");

test("upgrade smoke accepts exact ordered release versions", () => {
  assert.deepEqual(parseSemver("0.12.34"), [0, 12, 34]);
  assert.equal(compareSemver("0.1.9", "0.2.0"), -1);
  assert.equal(compareSemver("1.0.0", "1.0.0"), 0);
  assert.equal(compareSemver("2.0.0", "1.9.9"), 1);
  assert.throws(() => parseSemver("v0.2.0"), /exact major\.minor\.patch/);
  assert.throws(() => parseSemver("0.2"), /exact major\.minor\.patch/);
});

test("upgrade smoke refuses same-version, downgrade, and appId migration claims", () => {
  const base = {
    nextVersion: "0.2.0",
    previousAppId: "com.webfa.desktop",
    nextAppId: "com.webfa.desktop",
  };
  assert.deepEqual(
    validateUpgradeIdentity({ ...base, previousVersion: "0.1.9" }),
    { previousVersion: "0.1.9", nextVersion: "0.2.0", appId: "com.webfa.desktop" },
  );
  assert.throws(() => validateUpgradeIdentity({ ...base, previousVersion: "0.2.0" }), /must be older/);
  assert.throws(() => validateUpgradeIdentity({ ...base, previousVersion: "0.3.0" }), /must be older/);
  assert.throws(
    () => validateUpgradeIdentity({ ...base, previousVersion: "0.1.9", previousAppId: "io.example.webfa" }),
    /same stable appId/,
  );
});

test("upgrade smoke requires signed historical identity unless unsigned is explicit", () => {
  assert.throws(
    () => parseArguments(["--previous", "old.exe", "--previous-version", "0.1.0"]),
    /require --previous-signer-sha1/,
  );
  const unsigned = parseArguments([
    "--previous", "old.exe",
    "--previous-version", "0.1.0",
    "--previous-mode", "unsigned",
    "--current-mode", "unsigned",
  ]);
  assert.equal(unsigned.previousInstaller, "old.exe");
  assert.equal(unsigned.previousVersion, "0.1.0");
  assert.equal(unsigned.previousMode, "unsigned");
  assert.equal(unsigned.currentMode, "unsigned");
  assert.throws(
    () => parseArguments([
      "--previous", "old.exe",
      "--previous-version", "0.1.0",
      "--previous-mode", "unsigned",
      "--previous-signer-sha1", "A".repeat(40),
    ]),
    /incompatible/,
  );
});
