const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const root = fs.realpathSync(path.resolve(__dirname, ".."));

async function main() {
  const manifest = require(path.join(root, "package.json"));
  const version = manifest.devDependencies?.electron;
  if (!/^\d+\.\d+\.\d+$/.test(version ?? "")) {
    throw new Error(`Desktop Electron version is not exact: ${version}`);
  }
  const filename = `electron-v${version}-win32-x64.zip`;
  const checksums = require(path.join(root, "node_modules/electron/checksums.json"));
  const expectedHash = checksums[filename];
  if (!/^[a-f0-9]{64}$/.test(expectedHash ?? "")) {
    throw new Error(`Electron package does not provide a checksum for ${filename}`);
  }

  const electronGet = await import("@electron/get");
  if (process.env.HTTPS_PROXY || process.env.HTTP_PROXY || process.env.https_proxy || process.env.http_proxy) {
    electronGet.initializeProxy();
  }
  const source = await electronGet.downloadArtifact({
    version,
    artifactName: "electron",
    platform: "win32",
    arch: "x64",
    checksums: { [filename]: expectedHash },
  });
  const sourceHash = hashFile(source);
  if (sourceHash !== expectedHash) {
    throw new Error(`Electron cache checksum mismatch: ${sourceHash}`);
  }

  const destinationRoot = path.join(root, ".release/electron-dist");
  const destination = path.join(destinationRoot, filename);
  const relative = path.relative(root, destination);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) {
    throw new Error(`Refusing to write outside the workspace: ${destination}`);
  }
  fs.mkdirSync(destinationRoot, { recursive: true });
  const temporary = `${destination}.${process.pid}.tmp`;
  fs.copyFileSync(source, temporary);
  if (hashFile(temporary) !== expectedHash) {
    fs.rmSync(temporary, { force: true });
    throw new Error("Copied Electron release input failed checksum verification");
  }
  fs.renameSync(temporary, destination);
  process.stdout.write(`${JSON.stringify({ status: "pass", filename, sha256: expectedHash, bytes: fs.statSync(destination).size })}\n`);
}

function hashFile(target) {
  return crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
