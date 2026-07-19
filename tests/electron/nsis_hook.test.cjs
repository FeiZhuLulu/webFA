const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { getMakeNsisPath } = require("app-builder-lib/out/toolsets/windows.js");

const root = fs.realpathSync(path.resolve(__dirname, "../.."));

function nsisPath(target) {
  return target.replaceAll("/", "\\").replaceAll("$", "$$").replaceAll('"', '$\\"');
}

test("the pinned NSIS compiler accepts the audited install and uninstall hooks", {
  skip: process.platform !== "win32",
}, async () => {
  const tool = await getMakeNsisPath("0.0.0");
  const tempBase = fs.realpathSync(os.tmpdir());
  const tempRoot = fs.mkdtempSync(path.join(tempBase, "webfa-nsis-hook-test-"));
  const resolvedTempRoot = fs.realpathSync(tempRoot);
  assert.ok(resolvedTempRoot.startsWith(`${tempBase}${path.sep}`));
  const output = path.join(resolvedTempRoot, "hook-contract.exe");
  const hook = path.join(root, "packaging", "installer.nsh");
  const script = [
    "Unicode true",
    "RequestExecutionLevel user",
    '!include "LogicLib.nsh"',
    '!include "FileFunc.nsh"',
    '!define APP_INSTALLER_STORE_FILE "webfa-desktop-updater\\installer.exe"',
    "Var installMode",
    `!include "${nsisPath(hook)}"`,
    'Name "WebFA NSIS Hook Contract"',
    `OutFile "${nsisPath(output)}"`,
    "Section",
    "  StrCpy $installMode CurrentUser",
    "  !insertmacro customInit",
    "  !insertmacro customUnInstall",
    "SectionEnd",
    "",
  ].join("\n");
  try {
    const result = spawnSync(tool.path, ["-WX", "-INPUTCHARSET", "UTF8", "-"], {
      cwd: root,
      env: { ...process.env, ...(tool.env ?? {}) },
      input: script,
      encoding: "utf8",
      windowsHide: true,
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, `${result.stdout}\n${result.stderr}`);
    const compiled = fs.readFileSync(output);
    assert.ok(compiled.length > 10 * 1024);
    assert.equal(compiled.readUInt16LE(0), 0x5a4d);
  } finally {
    fs.rmSync(resolvedTempRoot, { recursive: true, force: true });
  }
});
