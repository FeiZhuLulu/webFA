const assert = require("node:assert/strict");
const { promises: fs } = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { RendererAssetServer } = require("../../apps/desktop/electron/dist/rendererServer.js");

async function createDirectoryLink(target, link) {
  try {
    await fs.symlink(target, link, process.platform === "win32" ? "junction" : "dir");
    return true;
  } catch (error) {
    if (["EACCES", "EPERM", "ENOSYS", "UNKNOWN"].includes(error.code)) return false;
    throw error;
  }
}

test("renderer asset server exposes only the exported loopback surface", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-"));
  await fs.mkdir(path.join(root, "monitor"), { recursive: true });
  await fs.mkdir(path.join(root, "_next", "static"), { recursive: true });
  await fs.writeFile(path.join(root, "index.html"), "<main>control center</main>");
  await fs.writeFile(path.join(root, "monitor", "index.html"), "<main>monitor</main>");
  await fs.writeFile(path.join(root, "_next", "static", "app.js"), "globalThis.webfa = true;");

  const server = new RendererAssetServer(root);
  try {
    const origin = await server.start();
    assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/);

    const rootResponse = await fetch(`${origin}/`);
    assert.equal(rootResponse.status, 200);
    assert.equal(await rootResponse.text(), "<main>control center</main>");
    assert.equal(rootResponse.headers.get("x-content-type-options"), "nosniff");
    assert.match(rootResponse.headers.get("content-security-policy"), /frame-ancestors 'none'/);

    const redirect = await fetch(`${origin}/monitor`, { redirect: "manual" });
    assert.equal(redirect.status, 308);
    assert.equal(redirect.headers.get("location"), "/monitor/");

    const monitorResponse = await fetch(`${origin}/monitor/`);
    assert.equal(monitorResponse.status, 200);
    assert.equal(await monitorResponse.text(), "<main>monitor</main>");

    const assetResponse = await fetch(`${origin}/_next/static/app.js`);
    assert.equal(assetResponse.status, 200);
    assert.equal(assetResponse.headers.get("cache-control"), "public, max-age=31536000, immutable");

    const traversalResponse = await fetch(`${origin}/%2e%2e%2fsecret.txt`);
    assert.notEqual(traversalResponse.status, 200);

    const postResponse = await fetch(`${origin}/`, { method: "POST" });
    assert.equal(postResponse.status, 405);
  } finally {
    await server.stop();
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("renderer asset server refuses an incomplete export", async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-incomplete-"));
  const server = new RendererAssetServer(root);
  try {
    await assert.rejects(() => server.start(), /ENOENT/);
    assert.equal(server.origin, null);
  } finally {
    await server.stop();
    await fs.rm(root, { recursive: true, force: true });
  }
});

test("renderer asset server reads a prevalidated integrity-protected ASAR root without metadata traversal", async () => {
  const parent = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-asar-"));
  const archive = path.join(parent, "app.asar");
  const root = path.join(archive, "apps", "desktop", "renderer", "out");
  await fs.mkdir(path.join(root, "monitor"), { recursive: true });
  await fs.writeFile(path.join(root, "index.html"), "<main>archive control center</main>");
  await fs.writeFile(path.join(root, "monitor", "index.html"), "<main>archive monitor</main>");

  const server = new RendererAssetServer(root, { integrityProtectedArchive: archive });
  try {
    const origin = await server.start();
    const response = await fetch(`${origin}/`);
    assert.equal(response.status, 200);
    assert.equal(await response.text(), "<main>archive control center</main>");
  } finally {
    await server.stop();
    await fs.rm(parent, { recursive: true, force: true });
  }
});

test("renderer asset server accepts archive trust only for a containing ASAR path", async () => {
  const parent = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-asar-boundary-"));
  const root = path.join(parent, "renderer");
  await fs.mkdir(root, { recursive: true });
  try {
    assert.throws(
      () => new RendererAssetServer(root, { integrityProtectedArchive: parent }),
      /must be an ASAR file/,
    );
    assert.throws(
      () => new RendererAssetServer(root, { integrityProtectedArchive: path.join(parent, "app.asar") }),
      /outside the integrity-protected archive/,
    );
  } finally {
    await fs.rm(parent, { recursive: true, force: true });
  }
});

test("renderer asset server rejects a symlink or junction escape", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-link-root-"));
  const outside = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-link-outside-"));
  await fs.mkdir(path.join(root, "monitor"), { recursive: true });
  await fs.writeFile(path.join(root, "index.html"), "<main>control center</main>");
  await fs.writeFile(path.join(root, "monitor", "index.html"), "<main>monitor</main>");
  await fs.writeFile(path.join(outside, "secret.txt"), "outside renderer root");

  const linked = await createDirectoryLink(outside, path.join(root, "escaped"));
  if (!linked) {
    t.skip("this platform does not permit creating a test symlink or junction");
    await fs.rm(root, { recursive: true, force: true });
    await fs.rm(outside, { recursive: true, force: true });
    return;
  }

  const server = new RendererAssetServer(root);
  try {
    const origin = await server.start();
    const response = await fetch(`${origin}/escaped/secret.txt`);
    assert.equal(response.status, 403);
    assert.notEqual(await response.text(), "outside renderer root");
  } finally {
    await server.stop();
    await fs.rm(root, { recursive: true, force: true });
    await fs.rm(outside, { recursive: true, force: true });
  }
});

test("renderer asset server refuses a required asset through an escaping link", async (t) => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-required-root-"));
  const outside = await fs.mkdtemp(path.join(os.tmpdir(), "webfa-renderer-required-outside-"));
  await fs.writeFile(path.join(root, "index.html"), "<main>control center</main>");
  await fs.writeFile(path.join(outside, "index.html"), "<main>outside monitor</main>");

  const linked = await createDirectoryLink(outside, path.join(root, "monitor"));
  if (!linked) {
    t.skip("this platform does not permit creating a test symlink or junction");
    await fs.rm(root, { recursive: true, force: true });
    await fs.rm(outside, { recursive: true, force: true });
    return;
  }

  const server = new RendererAssetServer(root);
  try {
    await assert.rejects(() => server.start(), /outside the renderer root/);
    assert.equal(server.origin, null);
  } finally {
    await server.stop();
    await fs.rm(root, { recursive: true, force: true });
    await fs.rm(outside, { recursive: true, force: true });
  }
});
