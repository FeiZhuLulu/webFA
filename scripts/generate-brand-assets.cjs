"use strict";

// 从 packaging/webfa-mark.svg 的几何重新生成品牌资产：
//   - packaging/webfa.ico（9 帧：16-128 为 maskless 32bpp DIB，256 为 PNG，满足 windows-icon-verifier）
//   - apps/desktop/renderer/src/app/icon.png（512x512 favicon）
// 栅格化复用本机 Chrome + CDP canvas，无第三方依赖。

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");

if (typeof WebSocket !== "function") throw new Error("Node.js WebSocket support is required");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const markSvgPath = path.join(root, "packaging", "webfa-mark.svg");
const icoPath = path.join(root, "packaging", "webfa.ico");
const appIconPath = path.join(root, "apps", "desktop", "renderer", "src", "app", "icon.png");
const chromeExecutable = process.env.WEBFA_AUDIT_CHROME || [
  path.join(process.env.ProgramFiles || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env["ProgramFiles(x86)"] || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env.ProgramFiles || "", "Microsoft", "Edge", "Application", "msedge.exe"),
].find((candidate) => candidate && fs.existsSync(candidate));

const ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256];

if (!fs.existsSync(markSvgPath)) throw new Error(`Master mark is missing: ${markSvgPath}`);
if (!chromeExecutable || !fs.existsSync(chromeExecutable)) {
  throw new Error("Chrome/Edge is unavailable; set WEBFA_AUDIT_CHROME");
}

const masterSvg = fs.readFileSync(markSvgPath, "utf8");
const requiredGeometry = [
  'd="M 19.05 9.43 A 7.5 7.5 0 1 1 15.17 5.20"',
  'cx="19.34" cy="5.25" r="2.6"',
];
if (!requiredGeometry.every((fragment) => masterSvg.includes(fragment))) {
  throw new Error("Master mark geometry changed; update the rasterizer contract before generating assets");
}

class CdpClient {
  constructor(url) {
    this.url = url;
    this.socket = undefined;
    this.id = 0;
    this.pending = new Map();
  }

  async connect() {
    this.socket = new WebSocket(this.url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("CDP connection timed out")), 10_000);
      this.socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      this.socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error("CDP connection failed")); }, { once: true });
    });
    this.socket.addEventListener("message", (event) => this.onMessage(event.data));
    this.socket.addEventListener("close", () => this.rejectAll(new Error("CDP connection closed")));
    await this.send("Page.enable");
    await this.send("Runtime.enable");
  }

  onMessage(raw) {
    const message = JSON.parse(typeof raw === "string" ? Buffer.from(raw).toString("utf8") : raw);
    if (!message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
    else pending.resolve(message.result || {});
  }

  rejectAll(error) {
    for (const pending of this.pending.values()) {
      clearTimeout(pending.timer);
      pending.reject(error);
    }
    this.pending.clear();
  }

  send(method, params = {}, timeoutMs = 15_000) {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error(`CDP is unavailable for ${method}`));
    }
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { method, resolve, reject, timer });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.send("Runtime.evaluate", { expression, returnByValue: true });
    if (result.exceptionDetails) throw new Error(`Evaluation failed: ${result.exceptionDetails.text}`);
    return result.result?.value;
  }

  close() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) this.socket.close();
  }
}

async function waitForFile(target, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (fs.existsSync(target) && fs.statSync(target).size > 0) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for ${target}`);
}

async function waitForPageTarget(port, timeoutMs = 15_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/json/list`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page.webSocketDebuggerUrl;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("Timed out waiting for a Chrome page target");
}

// 徽标（teal 渐变 squircle + 白色品牌标）在 canvas 上按 size 栅格化，
// 返回非预乘 RGBA（base64）与 PNG data URL。品牌标几何与 packaging/webfa-mark.svg 一致：
// 开放环圆心 (12,12) r=7.5 缺口朝向右上，节点 (19.34,5.25) r=2.6，stroke 2.4 round cap。
function renderExpression(size) {
  return `(() => {
    const size = ${size};
    const canvas = document.createElement("canvas");
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    const gradient = ctx.createLinearGradient(size * 0.1, 0, size * 0.9, size);
    gradient.addColorStop(0, "#1a7f76");
    gradient.addColorStop(1, "#0e5f58");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.roundRect(0, 0, size, size, size * 0.225);
    ctx.fill();
    const markSize = Math.round(size * 0.67);
    const offset = (size - markSize) / 2;
    ctx.save();
    ctx.translate(offset, offset);
    ctx.scale(markSize / 24, markSize / 24);
    ctx.strokeStyle = "#ffffff";
    ctx.fillStyle = "#ffffff";
    ctx.lineWidth = 2.4;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.arc(12, 12, 7.5, Math.atan2(9.43 - 12, 19.05 - 12), Math.atan2(5.20 - 12, 15.17 - 12), false);
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(19.34, 5.25, 2.6, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();
    const rgba = ctx.getImageData(0, 0, size, size).data;
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < rgba.length; i += chunk) {
      binary += String.fromCharCode(...rgba.subarray(i, i + chunk));
    }
    return { rgba: btoa(binary), png: canvas.toDataURL("image/png") };
  })()`;
}

function dibFrame(size, rgba) {
  const header = Buffer.alloc(40);
  header.writeUInt32LE(40, 0);
  header.writeInt32LE(size, 4);
  header.writeInt32LE(size * 2, 8);
  header.writeUInt16LE(1, 12);
  header.writeUInt16LE(32, 14);
  header.writeUInt32LE(0, 16);
  header.writeUInt32LE(size * size * 4, 20);
  const pixels = Buffer.alloc(size * size * 4);
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const src = (y * size + x) * 4;
      const dst = ((size - 1 - y) * size + x) * 4;
      pixels[dst] = rgba[src + 2];
      pixels[dst + 1] = rgba[src + 1];
      pixels[dst + 2] = rgba[src];
      pixels[dst + 3] = rgba[src + 3];
    }
  }
  return Buffer.concat([header, pixels]);
}

function buildIco(frames) {
  const count = frames.length;
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0);
  header.writeUInt16LE(1, 2);
  header.writeUInt16LE(count, 4);
  let offset = 6 + count * 16;
  const entries = [];
  for (const { size, data } of frames) {
    const entry = Buffer.alloc(16);
    entry[0] = size === 256 ? 0 : size;
    entry[1] = size === 256 ? 0 : size;
    entry[2] = 0;
    entry[3] = 0;
    entry.writeUInt16LE(1, 4);
    entry.writeUInt16LE(32, 6);
    entry.writeUInt32LE(data.length, 8);
    entry.writeUInt32LE(offset, 12);
    entries.push(entry);
    offset += data.length;
  }
  return Buffer.concat([header, ...entries, ...frames.map((frame) => frame.data)]);
}

async function run() {
  const profileRoot = path.join(root, ".tmp", "brand-assets-chrome-profile");
  fs.rmSync(profileRoot, { recursive: true, force: true });
  fs.mkdirSync(profileRoot, { recursive: true });
  const chrome = spawn(chromeExecutable, [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-debugging-port=0",
    `--user-data-dir=${profileRoot}`,
    "about:blank",
  ], { stdio: "ignore", windowsHide: true });
  let client;
  try {
    const activePortFile = path.join(profileRoot, "DevToolsActivePort");
    await waitForFile(activePortFile);
    const [portText] = fs.readFileSync(activePortFile, "utf8").trim().split(/\r?\n/);
    client = new CdpClient(await waitForPageTarget(Number(portText)));
    await client.connect();

    const frames = [];
    for (const size of ICO_SIZES) {
      const rendered = await client.evaluate(renderExpression(size));
      const rgba = Buffer.from(rendered.rgba, "base64");
      const data = size === 256
        ? Buffer.from(rendered.png.split(",")[1], "base64")
        : dibFrame(size, rgba);
      frames.push({ size, data });
    }
    fs.writeFileSync(icoPath, buildIco(frames));

    const appIcon = await client.evaluate(renderExpression(512));
    fs.writeFileSync(appIconPath, Buffer.from(appIcon.png.split(",")[1], "base64"));
  } finally {
    client?.close();
    chrome.kill();
    await new Promise((resolve) => setTimeout(resolve, 250));
    fs.rmSync(profileRoot, { recursive: true, force: true });
  }

  const { validateWindowsIcon } = require("./windows-icon-verifier.cjs");
  const validation = validateWindowsIcon(icoPath);
  process.stdout.write(`${JSON.stringify({
    status: "pass",
    ico: path.relative(root, icoPath),
    frames: validation.sizes,
    sha256: validation.sha256,
    appIcon: path.relative(root, appIconPath),
  })}\n`);
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
