"use strict";

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

if (typeof WebSocket !== "function") throw new Error("Node.js WebSocket support is required");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const rendererRoot = path.join(root, "apps", "desktop", "renderer", "out");
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const outputRoot = path.resolve(
  process.env.WEBFA_SOURCE_UI_AUDIT_OUTPUT
    || path.join(root, ".release", "ui-audit", `source-${stamp}`),
);
const chromeExecutable = process.env.WEBFA_AUDIT_CHROME || [
  path.join(process.env.ProgramFiles || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env["ProgramFiles(x86)"] || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env.LOCALAPPDATA || "", "Google", "Chrome", "Application", "chrome.exe"),
  path.join(process.env.ProgramFiles || "", "Microsoft", "Edge", "Application", "msedge.exe"),
].find((candidate) => candidate && fs.existsSync(candidate));

if (!fs.existsSync(path.join(rendererRoot, "index.html"))) {
  throw new Error("Renderer export is missing; run npm run build:renderer first");
}
if (!chromeExecutable || !fs.existsSync(chromeExecutable)) {
  throw new Error("Chrome/Edge is unavailable; set WEBFA_AUDIT_CHROME");
}
assertInside(outputRoot, path.join(root, ".release", "ui-audit"));
fs.mkdirSync(outputRoot, { recursive: true });

// 视觉回归 baseline：tests/ui-baseline/ 内的 PNG 与 capture 一一对应。
// WEBFA_UI_AUDIT_UPDATE_BASELINE=1 时刷新 baseline 并跳过 diff 判定；
// diffRatio 阈值可用 WEBFA_UI_AUDIT_DIFF_TOLERANCE 调整（默认 0.2%）。
const baselineRoot = path.join(root, "tests", "ui-baseline");
assertInside(baselineRoot, path.join(root, "tests"));
const updateBaseline = process.env.WEBFA_UI_AUDIT_UPDATE_BASELINE === "1";
const diffTolerance = Number(process.env.WEBFA_UI_AUDIT_DIFF_TOLERANCE || "0.002");
const PIXEL_CHANNEL_TOLERANCE = 16;

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".woff2": "font/woff2",
};

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
    await this.send("Accessibility.enable");
  }

  onMessage(raw) {
    const message = JSON.parse(typeof raw === "string" ? raw : Buffer.from(raw).toString("utf8"));
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

  async evaluate(expression, awaitPromise = false) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) throw new Error(`Renderer evaluation failed: ${result.exceptionDetails.text}`);
    return result.result?.value;
  }

  close() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) this.socket.close();
  }
}

function assertInside(target, parent) {
  const relation = path.relative(path.resolve(parent), path.resolve(target));
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`Audit path is outside its owned root: ${target}`);
  }
}

function serveRenderer() {
  const server = http.createServer((request, response) => {
    try {
      const url = new URL(request.url || "/", "http://127.0.0.1");
      const decoded = decodeURIComponent(url.pathname);
      // /__baseline__/ 与 /__current__/ 仅供视觉 diff 页面读取 PNG，其余路径仍只服务 Renderer 导出。
      let parentRoot = rendererRoot;
      let target;
      if (decoded.startsWith("/__baseline__/")) {
        parentRoot = baselineRoot;
        target = path.resolve(baselineRoot, `.${decoded.slice(13)}`);
      } else if (decoded.startsWith("/__current__/")) {
        parentRoot = outputRoot;
        target = path.resolve(outputRoot, `.${decoded.slice(12)}`);
      } else {
        const relative = decoded.endsWith("/") ? `${decoded}index.html` : decoded;
        target = path.resolve(rendererRoot, `.${relative}`);
      }
      const relation = path.relative(parentRoot, target);
      if (relation.startsWith("..") || path.isAbsolute(relation) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
        response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
        response.end("Not found");
        return;
      }
      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Type": mimeTypes[path.extname(target).toLowerCase()] || "application/octet-stream",
        "X-Content-Type-Options": "nosniff",
      });
      fs.createReadStream(target).pipe(response);
    } catch (error) {
      response.writeHead(400, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Bad request");
    }
  });
  return new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      resolve({ server, origin: `http://127.0.0.1:${address.port}` });
    });
  });
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

async function settle(client, origin, route, width, height) {
  await client.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await client.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-reduced-motion", value: "reduce" }],
  });
  await client.send("Page.navigate", { url: `${origin}${route}` });
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (await client.evaluate("document.readyState === 'complete'")) break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  await client.evaluate("new Promise((resolve) => setTimeout(resolve, 3200))", true);
  if (route === "/") {
    const runtimeDeadline = Date.now() + 10_000;
    let runtimeState = null;
    while (Date.now() < runtimeDeadline) {
      runtimeState = await client.evaluate(`(() => {
        const pill = document.querySelector(".viz-header-pill");
        return pill instanceof HTMLElement ? pill.textContent?.trim().toLowerCase() || null : null;
      })()`);
      if (runtimeState && runtimeState !== "starting") {
        await client.evaluate("new Promise((resolve) => setTimeout(resolve, 120))", true);
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    throw new Error(`Runtime state did not settle before source UI capture: ${runtimeState || "missing"}`);
  }
}

async function capture(client, name) {
  const metrics = await client.evaluate(`(() => {
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };
    const controls = [...document.querySelectorAll("button, a[href], input, select, textarea")].filter(visible);
    const controlEscapes = controls.map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        tag: element.tagName.toLowerCase(),
        name: element.getAttribute("aria-label") || element.textContent?.trim() || element.getAttribute("name") || "",
        left: Math.round(rect.left), right: Math.round(rect.right), top: Math.round(rect.top), bottom: Math.round(rect.bottom),
      };
    }).filter((item) => item.left < -1 || item.right > innerWidth + 1);
    const liveRegions = [...document.querySelectorAll('[role="alert"], [role="status"], [aria-live]')].filter(visible).map((element) => {
      const rect = element.getBoundingClientRect();
      return {
        role: element.getAttribute("role"),
        text: element.textContent?.trim().replace(/\s+/g, " ").slice(0, 180),
        left: Math.round(rect.left), right: Math.round(rect.right), top: Math.round(rect.top), bottom: Math.round(rect.bottom),
      };
    });
    const dialogs = [...document.querySelectorAll('[role="dialog"]')].filter(visible).map((element) => {
      const backgroundColor = getComputedStyle(element).backgroundColor;
      const alpha = backgroundColor.match(/^rgba\\([^,]+,[^,]+,[^,]+,\\s*([0-9.]+)\\)$/)?.[1];
      return {
        label: element.getAttribute("aria-label") || element.getAttribute("aria-labelledby") || "",
        ariaModal: element.getAttribute("aria-modal"),
        backgroundColor,
        opaque: alpha === undefined || Number(alpha) >= 1,
      };
    });
    const centeredState = (subjectSelector, containerSelector) => {
      const subject = document.querySelector(subjectSelector);
      const container = document.querySelector(containerSelector);
      if (!(subject instanceof HTMLElement) || !(container instanceof HTMLElement) || !visible(subject) || !visible(container)) return null;
      const subjectRect = subject.getBoundingClientRect();
      const containerRect = container.getBoundingClientRect();
      return {
        x: Math.round((subjectRect.left + subjectRect.width / 2) - (containerRect.left + containerRect.width / 2)),
        y: Math.round((subjectRect.top + subjectRect.height / 2) - (containerRect.top + containerRect.height / 2)),
      };
    };
    const active = document.activeElement;
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentOverflow: document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight,
      horizontalOverflow: document.documentElement.scrollWidth > innerWidth || document.body.scrollWidth > innerWidth,
      controlEscapes,
      visibleUnnamedButtons: controls.filter((element) => element.tagName === "BUTTON" && !(element.getAttribute("aria-label") || element.textContent?.trim())).length,
      visibleUnlabeledFields: controls.filter((element) => /^(INPUT|SELECT|TEXTAREA)$/.test(element.tagName) && !(element.getAttribute("aria-label") || element.getAttribute("aria-labelledby") || element.labels?.length)).length,
      liveRegions,
      dialogs,
      monitorEmptyCenterOffset: centeredState('[data-ui="monitor-empty-surface"]', '[data-ui="monitor-surface"]'),
      actionLogEmptyCenterOffset: centeredState('[data-ui="action-log-empty"]', '[data-ui="action-log"]'),
      inertRegions: document.querySelectorAll("[inert]").length,
      activeElement: active === document.body ? "BODY" : active?.getAttribute("aria-label") || active?.textContent?.trim() || active?.tagName,
    };
  })()`);
  const ax = await client.send("Accessibility.getFullAXTree");
  const screenshot = await client.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  });
  fs.writeFileSync(path.join(outputRoot, name), Buffer.from(screenshot.data, "base64"));
  return { ...metrics, accessibilityNodes: ax.nodes?.length || 0 };
}

async function click(client, selector) {
  const clicked = await client.evaluate(`(() => {
    const element = document.querySelector(${JSON.stringify(selector)});
    if (!(element instanceof HTMLElement)) return false;
    element.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`Visible audit control is missing: ${selector}`);
  await client.evaluate("new Promise((resolve) => setTimeout(resolve, 120))", true);
}

async function diffVisualBaseline(client, origin, names) {
  const results = {};
  if (updateBaseline) {
    fs.mkdirSync(baselineRoot, { recursive: true });
    for (const name of names) {
      fs.copyFileSync(path.join(outputRoot, name), path.join(baselineRoot, name));
      results[name] = { baseline: "updated" };
    }
    return results;
  }
  const missing = names.filter((name) => !fs.existsSync(path.join(baselineRoot, name)));
  if (missing.length) {
    for (const name of missing) results[name] = { error: "baseline missing; run npm run audit:source:ui:update" };
    return results;
  }
  // 不跳转 about:blank（opaque origin 会拦截回环图片请求），直接在当前同源页面上下文里比较。
  for (const name of names) {
    const result = await client.evaluate(`(async () => {
      const load = (url) => new Promise((resolve, reject) => {
        const image = new Image();
        image.onload = () => resolve(image);
        image.onerror = () => reject(new Error("image load failed: " + url));
        image.src = url;
      });
      const [base, current] = await Promise.all([
        load(${JSON.stringify(`${origin}/__baseline__/`)} + ${JSON.stringify(name)}),
        load(${JSON.stringify(`${origin}/__current__/`)} + ${JSON.stringify(name)}),
      ]);
      if (base.width !== current.width || base.height !== current.height) {
        return { sizeMismatch: { baseline: [base.width, base.height], current: [current.width, current.height] }, diffRatio: 1 };
      }
      const canvas = document.createElement("canvas");
      canvas.width = base.width;
      canvas.height = base.height;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(base, 0, 0);
      const baseData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(current, 0, 0);
      const currentData = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      const heat = ctx.createImageData(canvas.width, canvas.height);
      let diff = 0;
      for (let i = 0; i < currentData.length; i += 4) {
        const delta = Math.max(
          Math.abs(currentData[i] - baseData[i]),
          Math.abs(currentData[i + 1] - baseData[i + 1]),
          Math.abs(currentData[i + 2] - baseData[i + 2]),
        );
        if (delta > ${PIXEL_CHANNEL_TOLERANCE}) {
          diff += 1;
          heat.data[i] = 255; heat.data[i + 1] = 0; heat.data[i + 2] = 0; heat.data[i + 3] = 255;
        } else {
          heat.data[i] = currentData[i]; heat.data[i + 1] = currentData[i + 1]; heat.data[i + 2] = currentData[i + 2]; heat.data[i + 3] = 90;
        }
      }
      ctx.putImageData(heat, 0, 0);
      return { diffRatio: diff / (canvas.width * canvas.height), diffPixels: diff, heatmap: canvas.toDataURL("image/png") };
    })()`, true);
    if (result.heatmap) {
      fs.writeFileSync(path.join(outputRoot, `diff-${name}`), Buffer.from(result.heatmap.split(",")[1], "base64"));
      delete result.heatmap;
    }
    results[name] = result;
  }
  return results;
}

async function run() {
  const { server, origin } = await serveRenderer();
  const profileRoot = path.join(outputRoot, ".chrome-profile");
  assertInside(profileRoot, outputRoot);
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
    const clientUrl = await waitForPageTarget(Number(portText));
    client = new CdpClient(clientUrl);
    await client.connect();

    const evidence = { source: "production static Renderer via Chrome CDP device metrics", captures: {} };
    await settle(client, origin, "/", 1440, 960);
    evidence.captures.controlDesktop = await capture(client, "control-desktop.png");
    await click(client, '.viz-sidebar-nav button:nth-child(2)');
    evidence.captures.controlIdentityDesktop = await capture(client, "control-identity-desktop.png");
    await click(client, '.viz-sidebar-nav button:nth-child(3)');
    evidence.captures.controlSafetyDesktop = await capture(client, "control-safety-desktop.png");
    await settle(client, origin, "/", 390, 844);
    evidence.captures.controlMobile = await capture(client, "control-mobile.png");
    await click(client, 'button[aria-label="展开控制面板"]');
    evidence.captures.controlMobileLeft = await capture(client, "control-mobile-left.png");
    await click(client, '.viz-sidebar-nav button:nth-child(2)');
    evidence.captures.controlIdentityMobile = await capture(client, "control-identity-mobile.png");
    await click(client, '.viz-sidebar-nav button:nth-child(3)');
    evidence.captures.controlSafetyMobile = await capture(client, "control-safety-mobile.png");
    await click(client, 'button[aria-label="收起控制面板"]');
    await click(client, 'button[aria-label="展开 Runtime 投影"]');
    evidence.captures.controlMobileRight = await capture(client, "control-mobile-right.png");

    await settle(client, origin, "/monitor/", 1440, 960);
    evidence.captures.monitorDesktop = await capture(client, "monitor-desktop.png");
    await settle(client, origin, "/monitor/", 390, 844);
    evidence.captures.monitorMobile = await capture(client, "monitor-mobile.png");
    await click(client, 'button[aria-label="展开左栏"]');
    evidence.captures.monitorMobileLeft = await capture(client, "monitor-mobile-left.png");
    await click(client, 'button[aria-label="收起左栏"]');
    await click(client, 'button[aria-label="展开右栏"]');
    evidence.captures.monitorMobileRight = await capture(client, "monitor-mobile-right.png");

    const captureNames = fs.readdirSync(outputRoot).filter((file) => file.endsWith(".png") && !file.startsWith("diff-"));
    const visualDiff = await diffVisualBaseline(client, origin, captureNames);
    evidence.visualDiff = {
      baseline: path.relative(root, baselineRoot),
      tolerance: diffTolerance,
      updateBaseline,
      captures: visualDiff,
    };

    fs.writeFileSync(path.join(outputRoot, "evidence.json"), `${JSON.stringify(evidence, null, 2)}\n`);
    const failures = Object.entries(evidence.captures).filter(([, item]) => (
      item.horizontalOverflow
      || item.controlEscapes.length
      || item.visibleUnnamedButtons
      || item.visibleUnlabeledFields
      || item.dialogs.some((dialog) => dialog.ariaModal !== "true" || !dialog.opaque)
      || (item.monitorEmptyCenterOffset && (Math.abs(item.monitorEmptyCenterOffset.x) > 2 || Math.abs(item.monitorEmptyCenterOffset.y) > 2))
      || (item.actionLogEmptyCenterOffset && (Math.abs(item.actionLogEmptyCenterOffset.x) > 2 || Math.abs(item.actionLogEmptyCenterOffset.y) > 2))
    ));
    const diffFailures = Object.entries(visualDiff).filter(([, item]) => (
      item.error || item.sizeMismatch || (typeof item.diffRatio === "number" && item.diffRatio > diffTolerance)
    ));
    if (failures.length || diffFailures.length) {
      const parts = [];
      if (failures.length) parts.push(`layout: ${failures.map(([name]) => name).join(", ")}`);
      if (diffFailures.length) {
        parts.push(`visual diff: ${diffFailures.map(([name, item]) => `${name}(${item.error || (item.sizeMismatch ? "size mismatch" : `${(item.diffRatio * 100).toFixed(2)}%`)})`).join(", ")}`);
      }
      throw new Error(`Source UI audit failed: ${parts.join("; ")}`);
    }
    process.stdout.write(`${JSON.stringify({ status: "pass", outputRoot, captures: Object.keys(evidence.captures).length, baselineUpdated: updateBaseline })}\n`);
  } finally {
    client?.close();
    chrome.kill();
    await new Promise((resolve) => server.close(resolve));
    await new Promise((resolve) => setTimeout(resolve, 250));
    fs.rmSync(profileRoot, { recursive: true, force: true });
  }
}

run().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
