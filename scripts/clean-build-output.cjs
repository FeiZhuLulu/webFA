const fs = require("node:fs");
const path = require("node:path");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const groups = {
  electron: ["apps/desktop/electron/dist"],
  renderer: ["apps/desktop/renderer/out", "apps/desktop/renderer/.next"],
  release: [
    ".release",
    "apps/desktop/electron/dist",
    "apps/desktop/renderer/out",
    "apps/desktop/renderer/.next",
  ],
};

const mode = process.argv[2];
if (!Object.hasOwn(groups, mode)) {
  throw new Error(`Usage: node scripts/clean-build-output.cjs ${Object.keys(groups).join("|")}`);
}

for (const relative of groups[mode]) {
  const target = path.resolve(root, relative);
  const relation = path.relative(root, target);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Refusing to clean path outside the workspace: ${target}`);
  }
  fs.rmSync(target, { recursive: true, force: true, maxRetries: 3, retryDelay: 100 });
}

process.stdout.write(`${JSON.stringify({ cleaned: groups[mode] })}\n`);
