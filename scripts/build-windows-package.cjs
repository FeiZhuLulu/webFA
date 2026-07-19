const { spawnSync } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const manifest = require(path.join(root, "package.json"));
const mode = process.argv[2];
if (!new Set(["unpacked", "unsigned", "signed"]).has(mode)) {
  throw new Error("Usage: node scripts/build-windows-package.cjs unpacked|unsigned|signed");
}
if (mode === "unsigned") {
  process.stderr.write(
    "WebFA unsigned mode produces a development-only installer candidate; " +
    "it does not run clean-tag provenance and must not be published.\n",
  );
}

const signingVariables = [
  "CSC_LINK",
  "CSC_KEY_PASSWORD",
  "CSC_NAME",
  "WIN_CSC_LINK",
  "WIN_CSC_KEY_PASSWORD",
];
const cleanEnvironment = { ...process.env, CSC_IDENTITY_AUTO_DISCOVERY: "false" };
for (const name of Object.keys(cleanEnvironment)) {
  if (/^(?:WEBFA_|NEXT_PUBLIC_|ELECTRON_|PYINSTALLER_|PYTHONHOME$|PYTHONPATH$|NODE_OPTIONS$|NODE_PATH$|npm_config_|NPM_CONFIG_)/i.test(name)) {
    delete cleanEnvironment[name];
  }
}
for (const name of signingVariables) delete cleanEnvironment[name];

const signingEnvironment = {};
if (mode === "signed") {
  for (const name of ["CSC_LINK", "CSC_KEY_PASSWORD", "WEBFA_SIGNING_CERT_SHA1"]) {
    if (!process.env[name]) throw new Error(`Signed Windows release requires ${name}`);
    signingEnvironment[name] = process.env[name];
  }
}

if (process.version !== `v${manifest.engines.node}`) {
  throw new Error(`Windows release requires Node ${manifest.engines.node}; got ${process.version}`);
}
const npmCli = resolveNpmCli();
const npmVersion = runText(process.execPath, [npmCli, "--version"], cleanEnvironment);
if (npmVersion !== manifest.engines.npm) {
  throw new Error(`Windows release requires npm ${manifest.engines.npm}; got ${npmVersion}`);
}
run(process.execPath, [npmCli, "ci", "--ignore-scripts", "--no-audit", "--no-fund"], cleanEnvironment);
run(process.execPath, [npmCli, "audit", "--audit-level=high"], cleanEnvironment);
run(process.execPath, [npmCli, "run", "build:release-inputs"], cleanEnvironment);
if (mode === "signed") {
  run(process.execPath, [path.join(root, "scripts/verify-release-provenance.cjs")], cleanEnvironment);
}

const builderPackagePath = require.resolve("electron-builder/package.json");
const builderPackage = require(builderPackagePath);
const builder = path.resolve(path.dirname(builderPackagePath), builderPackage.bin["electron-builder"]);
const builderArguments = ["--config", mode === "signed" ? "electron-builder.signed.yml" : "electron-builder.yml", "--win", "--x64"];
if (mode === "unpacked") builderArguments.push("--dir");
run(process.execPath, [builder, ...builderArguments], mode === "signed"
  ? { ...cleanEnvironment, ...signingEnvironment, CSC_IDENTITY_AUTO_DISCOVERY: "true" }
  : cleanEnvironment);

run(process.execPath, [
  path.join(root, "scripts/verify-unpacked-release.cjs"),
  ...(mode === "signed" ? ["--signed"] : []),
], cleanEnvironment);
run(process.execPath, [path.join(root, "scripts/smoke-unpacked-desktop.cjs")], cleanEnvironment);
if (mode !== "unpacked") {
  const verificationEnvironment = mode === "signed"
    ? { ...cleanEnvironment, WEBFA_SIGNING_CERT_SHA1: signingEnvironment.WEBFA_SIGNING_CERT_SHA1 }
    : cleanEnvironment;
  run(process.execPath, [path.join(root, "scripts/verify-windows-package.cjs"), mode], verificationEnvironment);
}

function resolveNpmCli() {
  const candidates = [path.join(path.dirname(process.execPath), "node_modules", "npm", "bin", "npm-cli.js")];
  const npmCli = candidates.find((candidate) => {
    try {
      return fs.statSync(candidate).isFile();
    } catch {
      return false;
    }
  });
  if (!npmCli) throw new Error("Could not locate npm-cli.js for the pinned Node toolchain");
  return npmCli;
}

function runText(command, args, env) {
  const result = spawnSync(command, args, {
    cwd: root,
    env,
    encoding: "utf8",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with status ${result.status}: ${result.stderr}`);
  }
  return result.stdout.trim();
}

function run(command, args, env) {
  const result = spawnSync(command, args, {
    cwd: root,
    env,
    stdio: "inherit",
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with status ${result.status}`);
  }
}
