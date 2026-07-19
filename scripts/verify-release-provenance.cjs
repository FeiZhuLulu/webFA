const { execFileSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const manifest = require(path.join(root, "package.json"));
const buildManifest = require(path.join(root, ".release/metadata/build-manifest.json"));
const expectedNode = fs.readFileSync(path.join(root, ".nvmrc"), "utf8").trim();
const expectedPython = fs.readFileSync(path.join(root, ".python-version"), "utf8").trim();
const head = git(["rev-parse", "HEAD"]);
const tag = git(["describe", "--tags", "--exact-match", "HEAD"]);
const status = git(["status", "--porcelain"]);
const pythonVersion = execFileSync("python", ["--version"], {
  cwd: root,
  encoding: "utf8",
  windowsHide: true,
}).trim().replace(/^Python\s+/, "");

if (status) throw new Error("Formal signed release requires a clean source tree");
if (tag !== `v${manifest.version}`) {
  throw new Error(`Formal signed release requires exact tag v${manifest.version}; got ${tag || "none"}`);
}
if (process.version !== `v${expectedNode}` || pythonVersion !== expectedPython) {
  throw new Error(
    `Release toolchain mismatch: node=${process.version}, python=${pythonVersion}, expected=v${expectedNode}/${expectedPython}`,
  );
}
if (buildManifest.source_tree_dirty || buildManifest.git_commit !== head) {
  throw new Error("Generated build manifest does not prove the clean tagged source revision");
}
process.stdout.write(`${JSON.stringify({ status: "pass", version: manifest.version, head, tag })}\n`);

function git(args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8", windowsHide: true }).trim();
}
