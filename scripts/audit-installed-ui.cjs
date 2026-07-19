"use strict";

const { spawn, spawnSync } = require("node:child_process");
const crypto = require("node:crypto");
const fs = require("node:fs");
const http = require("node:http");
const net = require("node:net");
const path = require("node:path");
const yaml = require("js-yaml");

if (process.platform !== "win32") throw new Error("Installed UI audit is Windows-only");
if (typeof WebSocket !== "function") throw new Error("Node.js WebSocket support is required");

const root = fs.realpathSync(path.resolve(__dirname, ".."));
const releaseRoot = path.join(root, ".release");
const manifest = require(path.join(root, "package.json"));
const builder = yaml.load(fs.readFileSync(path.join(root, "electron-builder.yml"), "utf8"));
const installer = path.join(releaseRoot, "electron", `WebFA-Setup-${manifest.version}-x64.exe`);
const ownedRoot = path.join(releaseRoot, "installed-smoke");
const installRoot = path.join(ownedRoot, "WebFA");
const executable = path.join(installRoot, "WebFA.exe");
const uninstaller = path.join(installRoot, "Uninstall WebFA.exe");
const marker = path.join(ownedRoot, ".webfa-installed-smoke-owned.json");
const lifecycleSmoke = path.join(root, "scripts", "smoke-installed-desktop.cjs");
const mcpProbe = path.join(root, "scripts", "smoke-frozen-mcp.py");
const releasePython = path.join(releaseRoot, "sidecar-venv", "Scripts", "python.exe");
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
const outputRoot = path.join(releaseRoot, "ui-audit", `installed-${manifest.version}-${stamp}`);
const runtimeData = path.join(outputRoot, ".runtime-data");
const browserIsolationRoot = path.join(outputRoot, ".browser-isolation");
const failureHarnessRoot = path.join(outputRoot, ".failure-harness");
const mcpWorkingRoot = path.join(outputRoot, "mcp-flow");
const mcpReadyFile = path.join(mcpWorkingRoot, "session-ready.json");
const mcpReleaseFile = path.join(mcpWorkingRoot, "release-session");
const installedSidecar = path.join(installRoot, "resources", "sidecar", "webfa.exe");
const sidecarBackup = path.join(failureHarnessRoot, "webfa.exe.original");
const sleeperExecutable = path.join(failureHarnessRoot, "webfa-sleeper.exe");
const reportPath = path.join(outputRoot, "audit-evidence.json");
const appId = builder?.appId;
const traceDeprecation = process.env.WEBFA_AUDIT_TRACE_DEPRECATION === "1";

if (typeof appId !== "string" || !appId) throw new Error("electron-builder.yml must define appId");
if (!fs.existsSync(installer)) throw new Error(`Installer is missing: ${installer}`);
for (const [target, parent] of [
  [ownedRoot, releaseRoot],
  [installRoot, ownedRoot],
  [outputRoot, path.join(releaseRoot, "ui-audit")],
  [runtimeData, outputRoot],
  [browserIsolationRoot, outputRoot],
  [failureHarnessRoot, outputRoot],
  [mcpWorkingRoot, outputRoot],
  [mcpReadyFile, mcpWorkingRoot],
  [mcpReleaseFile, mcpWorkingRoot],
  [installedSidecar, installRoot],
  [sidecarBackup, failureHarnessRoot],
  [sleeperExecutable, failureHarnessRoot],
]) assertOwnedPath(target, parent);

const report = {
  schema: 1,
  createdAt: new Date().toISOString(),
  candidate: {
    version: manifest.version,
    appId,
    installer,
    bytes: fs.statSync(installer).size,
    sha256: hashFile(installer),
  },
  capture: {
    source: "installed Electron renderer via loopback-only CDP",
    outputRoot,
    traceDeprecation,
    steps: [],
  },
  mcp: {},
  lifecycle: {},
};

let appProcess;
let mainClient;
let monitorClient;
let debugPort;
let apiPort;
let lifecycleStarted = false;
let capturedError;
let captureSequence = 0;
const appLog = [];
const applicationLogs = new Map();
let sidecarIsolated = false;
let mcpProbeProcess;
let mcpProbeStdout = "";
let mcpProbeStderr = "";
let mcpProbeSpawnError;

class CdpClient {
  constructor(url) {
    this.url = url;
    this.socket = undefined;
    this.id = 0;
    this.pending = new Map();
  }

  async connect() {
    const socket = new WebSocket(this.url);
    this.socket = socket;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`CDP connection timed out: ${this.url}`)), 10_000);
      socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener("error", () => { clearTimeout(timer); reject(new Error(`CDP connection failed: ${this.url}`)); }, { once: true });
    });
    socket.addEventListener("message", (event) => this.onMessage(event.data));
    socket.addEventListener("close", () => this.rejectAll(new Error("CDP connection closed")));
    await this.send("Page.enable");
    await this.send("Runtime.enable");
    await this.send("Accessibility.enable");
    await this.send("Emulation.setEmulatedMedia", {
      features: [{ name: "prefers-reduced-motion", value: "reduce" }],
    });
    return this;
  }

  onMessage(data) {
    const message = JSON.parse(typeof data === "string" ? data : Buffer.from(data).toString("utf8"));
    if (!message.id) return;
    const pending = this.pending.get(message.id);
    if (!pending) return;
    this.pending.delete(message.id);
    clearTimeout(pending.timer);
    if (message.error) pending.reject(new Error(`${pending.method}: ${message.error.message}`));
    else pending.resolve(message.result ?? {});
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
      return Promise.reject(new Error(`CDP is not open for ${method}`));
    }
    const id = ++this.id;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`CDP command timed out: ${method}`));
      }, timeoutMs);
      this.pending.set(id, { resolve, reject, timer, method });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression, awaitPromise = false) {
    const response = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise,
      returnByValue: true,
      userGesture: true,
    });
    if (response.exceptionDetails) {
      throw new Error(`Renderer evaluation failed: ${response.exceptionDetails.text ?? "unknown error"}`);
    }
    return response.result?.value;
  }

  close() {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) this.socket.close();
  }
}

function assertOwnedPath(target, parent) {
  const resolvedTarget = path.resolve(target);
  const resolvedParent = path.resolve(parent);
  const relation = path.relative(resolvedParent, resolvedTarget);
  if (!relation || relation.startsWith("..") || path.isAbsolute(relation)) {
    throw new Error(`UI audit path is outside its owned parent: ${resolvedTarget}`);
  }
  if (fs.existsSync(resolvedTarget) && fs.lstatSync(resolvedTarget).isSymbolicLink()) {
    throw new Error(`UI audit path must not be a link: ${resolvedTarget}`);
  }
}

function hashFile(target) {
  return crypto.createHash("sha256").update(fs.readFileSync(target)).digest("hex");
}

function uuidV5(value, namespace) {
  const bytes = crypto.createHash("sha1")
    .update(Buffer.from(namespace.replaceAll("-", ""), "hex"))
    .update(value, "utf8")
    .digest()
    .subarray(0, 16);
  bytes[6] = (bytes[6] & 0x0f) | 0x50;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function runFile(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: root,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    timeout: options.timeoutMs ?? 180_000,
    windowsHide: true,
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${path.basename(command)} exited with ${result.status}: ${(result.stderr || result.stdout || "").trim()}`);
  }
  return result;
}

function runWindowsProcessTree(target, argumentLine) {
  const script = String.raw`
$ErrorActionPreference = "Stop"
$process = Start-Process -FilePath $env:WEBFA_PROCESS_TARGET -ArgumentList $env:WEBFA_PROCESS_ARGUMENT_LINE -WindowStyle Hidden -Wait -PassThru
[Console]::Out.Write($process.ExitCode)
`;
  const result = runFile("pwsh.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
    env: { ...process.env, WEBFA_PROCESS_TARGET: target, WEBFA_PROCESS_ARGUMENT_LINE: argumentLine },
  });
  if (Number(result.stdout.trim()) !== 0) {
    throw new Error(`${path.basename(target)} process tree exited with ${result.stdout.trim()}`);
  }
}

function lifecyclePreflight() {
  const result = runFile(process.execPath, [lifecycleSmoke, "unsigned", "--cleanup-only"], { capture: true });
  const payload = JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1));
  if (payload.status !== "pass" || payload.installedStateClean !== true) {
    throw new Error(`Installed lifecycle preflight failed: ${result.stdout}`);
  }
  return payload;
}

function writeMarker() {
  fs.mkdirSync(ownedRoot, { recursive: true });
  fs.writeFileSync(marker, `${JSON.stringify({
    schema: 1,
    appId,
    installerGuid: uuidV5(appId, "50e065bc-3134-11e6-9bab-38c9862bdaf3"),
    installRoot,
  })}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
}

async function reservePorts(count) {
  const servers = [];
  const ports = [];
  try {
    for (let index = 0; index < count; index += 1) {
      const server = net.createServer();
      servers.push(server);
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(0, "127.0.0.1", resolve);
      });
      ports.push(server.address().port);
    }
    return ports;
  } finally {
    await Promise.all(servers.map((server) => new Promise((resolve) => server.close(resolve))));
  }
}

async function waitFor(predicate, label, timeoutMs = 45_000, intervalMs = 150) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  do {
    try {
      const value = await predicate();
      if (value) return value;
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  } while (Date.now() < deadline);
  throw new Error(`${label} timed out${lastError ? `: ${lastError.message ?? lastError}` : ""}`);
}

async function getJson(url, timeoutMs = 5_000) {
  const response = await fetch(url, {
    cache: "no-store",
    headers: { Connection: "close" },
    signal: AbortSignal.timeout(timeoutMs),
  });
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return response.json();
}

async function runInstalledMcpFlow() {
  const config = await getJson(`http://127.0.0.1:${apiPort}/v1/mcp/config`);
  const entry = config?.mcpServers?.webfa;
  if (
    !entry ||
    typeof entry.command !== "string" ||
    !Array.isArray(entry.args) ||
    !entry.env ||
    typeof entry.env !== "object"
  ) {
    throw new Error(`Installed Runtime advertised an invalid MCP entry: ${JSON.stringify(config)}`);
  }

  const expectedSidecar = fs.realpathSync(path.join(installRoot, "resources", "sidecar", "webfa.exe"));
  const advertisedCommand = fs.realpathSync(entry.command);
  if (advertisedCommand.toLowerCase() !== expectedSidecar.toLowerCase()) {
    throw new Error(`Installed MCP command does not target the installed sidecar: ${advertisedCommand}`);
  }
  if (JSON.stringify(entry.args) !== '["mcp"]') {
    throw new Error(`Installed MCP arguments changed: ${JSON.stringify(entry.args)}`);
  }
  if (entry.env.WEBFA_RUNTIME_URL !== `http://127.0.0.1:${apiPort}`) {
    throw new Error(`Installed MCP Runtime binding changed: ${JSON.stringify(entry.env)}`);
  }
  if (entry.env.WEBFA_AGENT_ID !== "external-agent") {
    throw new Error(`Installed MCP Agent identity changed: ${JSON.stringify(entry.env)}`);
  }

  const pythonStat = fs.lstatSync(releasePython);
  if (!pythonStat.isFile() || pythonStat.isSymbolicLink()) {
    throw new Error(`Fresh release-venv Python is required for the installed MCP probe: ${releasePython}`);
  }
  fs.mkdirSync(mcpWorkingRoot, { recursive: true });
  const configPath = path.join(mcpWorkingRoot, "advertised-mcp-config.json");
  fs.writeFileSync(configPath, `${JSON.stringify(entry)}\n`, { encoding: "utf8", flag: "wx" });

  mcpProbeStdout = "";
  mcpProbeStderr = "";
  mcpProbeSpawnError = undefined;
  mcpProbeProcess = spawn(
    releasePython,
    [
      "-I",
      mcpProbe,
      configPath,
      mcpWorkingRoot,
      "--ready-file",
      mcpReadyFile,
      "--release-file",
      mcpReleaseFile,
    ],
    {
      cwd: root,
      env: { ...process.env, WEBFA_RUNTIME_URL: `http://127.0.0.1:${apiPort}` },
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    },
  );
  mcpProbeProcess.stdout.on("data", (chunk) => { mcpProbeStdout += chunk.toString(); });
  mcpProbeProcess.stderr.on("data", (chunk) => { mcpProbeStderr += chunk.toString(); });
  mcpProbeProcess.on("error", (error) => { mcpProbeSpawnError = error; });
  await waitFor(() => {
    if (mcpProbeSpawnError) throw mcpProbeSpawnError;
    if (mcpProbeProcess?.exitCode !== null) {
      throw new Error(`Installed MCP probe exited before its live-session checkpoint (${mcpProbeProcess?.exitCode}): ${mcpProbeStderr}`);
    }
    return fs.existsSync(mcpReadyFile);
  }, "installed MCP live-session checkpoint", 120_000, 100);
  let flow;
  try {
    flow = JSON.parse(fs.readFileSync(mcpReadyFile, "utf8"));
  } catch (error) {
    throw new Error(`Installed MCP probe did not emit valid live-session evidence: ${mcpProbeStdout}`, { cause: error });
  }
  if (
    flow.status !== "pass" ||
    JSON.stringify(flow.flow) !==
      JSON.stringify(["initialize", "tools/list", "open", "observe", "act", "observe"])
  ) {
    throw new Error(`Installed MCP flow evidence changed: ${JSON.stringify(flow)}`);
  }

  const health = await getJson(`http://127.0.0.1:${apiPort}/health`);
  if (
    health.product !== "webfa" ||
    health.release_version !== manifest.version ||
    health.instance_id !== report.capture.runtimeReadyObservation?.instanceId
  ) {
    throw new Error(`External MCP flow changed Desktop Runtime ownership: ${JSON.stringify(health)}`);
  }
  report.mcp = {
    status: "pass",
    advertisedCommand,
    commandSha256: hashFile(advertisedCommand),
    args: entry.args,
    runtimeUrl: entry.env.WEBFA_RUNTIME_URL,
    agentId: entry.env.WEBFA_AGENT_ID,
    tools: flow.tools,
    flow: flow.flow,
    documentId: flow.document_id,
    runtimeInstanceId: health.instance_id,
    desktopRuntimeOwnershipPreserved: true,
    liveSessionHeldForProjection: true,
  };
}

function waitForChildExit(child, timeoutMs) {
  if (!child || child.exitCode !== null) return Promise.resolve(true);
  return new Promise((resolve) => {
    const onExit = () => { clearTimeout(timer); resolve(true); };
    const timer = setTimeout(() => { child.removeListener("exit", onExit); resolve(false); }, timeoutMs);
    child.once("exit", onExit);
  });
}

async function releaseInstalledMcpFlow() {
  const child = mcpProbeProcess;
  if (!child) return;
  if (child.exitCode === null && !fs.existsSync(mcpReleaseFile)) {
    fs.writeFileSync(mcpReleaseFile, "release\n", { encoding: "utf8", flag: "wx" });
  }
  if (!(await waitForChildExit(child, 15_000))) {
    child.kill();
    await waitForChildExit(child, 5_000);
    throw new Error(`Installed MCP probe did not release cleanly: ${mcpProbeStderr}`);
  }
  if (child.exitCode !== 0) {
    throw new Error(`Installed MCP probe failed while releasing its live session (${child.exitCode}): ${mcpProbeStderr}`);
  }
  let finalFlow;
  try {
    finalFlow = JSON.parse(mcpProbeStdout.trim().split(/\r?\n/).at(-1));
  } catch (error) {
    throw new Error(`Installed MCP probe did not emit final evidence: ${mcpProbeStdout}`, { cause: error });
  }
  if (Array.isArray(report.mcp.flow) && JSON.stringify(finalFlow.flow) !== JSON.stringify(report.mcp.flow)) {
    throw new Error(`Installed MCP live-session evidence changed during release: ${JSON.stringify(finalFlow)}`);
  }
  report.mcp.liveSessionReleasedCleanly = true;
  mcpProbeProcess = undefined;
}

async function listTargets() {
  const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`, {
    cache: "no-store",
    signal: AbortSignal.timeout(1_500),
  });
  if (!response.ok) throw new Error(`CDP target list returned HTTP ${response.status}`);
  return response.json();
}

async function waitForTarget(predicate, label) {
  return waitFor(async () => {
    const targets = await listTargets();
    return targets.find((target) => target.type === "page" && predicate(target));
  }, label);
}

function launchApp(environmentOverrides = {}, logScenario = "baseline") {
  const scenarioLog = applicationLogs.get(logScenario) ?? [];
  applicationLogs.set(logScenario, scenarioLog);
  const recordLog = (value) => {
    const text = String(value);
    appLog.push(text);
    scenarioLog.push(text);
    while (appLog.join("").length > 100_000) appLog.shift();
    while (scenarioLog.join("").length > 50_000) scenarioLog.shift();
  };
  appProcess = spawn(executable, [
    ...(traceDeprecation ? ["--trace-deprecation"] : []),
    `--remote-debugging-port=${debugPort}`,
    "--remote-debugging-address=127.0.0.1",
    `--user-data-dir=${runtimeData}`,
  ], {
    cwd: installRoot,
    env: {
      ...process.env,
      ...environmentOverrides,
      WEBFA_API_HOST: "127.0.0.1",
      WEBFA_API_PORT: String(apiPort),
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: false,
  });
  for (const stream of [appProcess.stdout, appProcess.stderr]) {
    stream?.on("data", recordLog);
  }
  appProcess.once("error", (error) => recordLog(`launch error: ${error.stack ?? error}`));
}

const diagnosticsScript = String.raw`(() => {
  const visible = (element) => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";
  const nameOf = (element) => (element.getAttribute("aria-label") || element.textContent || element.getAttribute("title") || "").trim().replace(/\s+/g, " ");
  const root = document.documentElement;
  const visibleElements = Array.from(document.body.querySelectorAll("*")).filter(visible);
  const overflow = visibleElements.filter((element) => {
    const rect = element.getBoundingClientRect();
    return rect.left < -1 || rect.right > innerWidth + 1;
  }).slice(0, 30).map((element) => ({ tag: element.tagName.toLowerCase(), className: String(element.className).slice(0, 180), name: nameOf(element).slice(0, 120), rect: element.getBoundingClientRect().toJSON() }));
  const buttons = Array.from(document.querySelectorAll("button")).filter(visible).map((button) => ({ name: nameOf(button), disabled: button.disabled, expanded: button.getAttribute("aria-expanded"), pressed: button.getAttribute("aria-pressed") }));
  const unlabeledFields = Array.from(document.querySelectorAll("input, select, textarea")).filter(visible).filter((field) => {
    const id = field.getAttribute("id");
    return !field.getAttribute("aria-label") && !field.getAttribute("aria-labelledby") && !field.closest("label") && !(id && document.querySelector('label[for="' + CSS.escape(id) + '"]'));
  }).map((field) => ({ tag: field.tagName.toLowerCase(), type: field.getAttribute("type"), placeholder: field.getAttribute("placeholder") }));
  const active = document.activeElement;
  return {
    title: document.title,
    url: location.href,
    readyState: document.readyState,
    viewport: { width: innerWidth, height: innerHeight, dpr: devicePixelRatio },
    documentSize: { width: root.scrollWidth, height: root.scrollHeight },
    horizontalOverflow: root.scrollWidth > root.clientWidth + 1,
    verticalOverflow: root.scrollHeight > root.clientHeight + 1,
    overflow,
    buttons,
    unlabeledButtons: buttons.filter((button) => !button.name),
    unlabeledFields,
    landmarks: Array.from(document.querySelectorAll("main, nav, header, aside, [role]")).filter(visible).map((element) => ({ tag: element.tagName.toLowerCase(), role: element.getAttribute("role"), name: nameOf(element).slice(0, 120) })).slice(0, 60),
    activeElement: active ? { tag: active.tagName.toLowerCase(), name: nameOf(active), outline: getComputedStyle(active).outline } : null,
    errorToasts: Array.from(document.querySelectorAll(".viz-toast.error")).filter(visible).map((element) => nameOf(element)),
    bodyText: document.body.innerText.slice(0, 5000),
  };
})()`;

function pngDimensions(buffer) {
  if (buffer.length < 24 || buffer.toString("hex", 0, 8) !== "89504e470d0a1a0a") {
    throw new Error("Captured file is not a PNG");
  }
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

async function captureStep(client, number, slug, description, settleMs = 350) {
  if (settleMs > 0) await new Promise((resolve) => setTimeout(resolve, settleMs));
  const diagnostics = await client.evaluate(diagnosticsScript);
  const accessibility = await client.send("Accessibility.getFullAXTree", { depth: 12 });
  const capture = await client.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: false,
  }, 30_000);
  const bytes = Buffer.from(capture.data, "base64");
  if (bytes.length < 10_000) throw new Error(`Screenshot is unexpectedly small: ${bytes.length} bytes`);
  const accessibilityNodeCount = accessibility.nodes?.length ?? 0;
  const violations = [];
  if (diagnostics.readyState !== "complete") violations.push(`document readyState is ${diagnostics.readyState}`);
  if (diagnostics.horizontalOverflow) violations.push(`document width ${diagnostics.documentSize.width}px exceeds viewport ${diagnostics.viewport.width}px`);
  if (diagnostics.overflow?.length) violations.push(`${diagnostics.overflow.length} visible elements cross the horizontal viewport boundary`);
  if (diagnostics.unlabeledButtons?.length) violations.push(`${diagnostics.unlabeledButtons.length} visible buttons have no accessible name`);
  if (diagnostics.unlabeledFields?.length) violations.push(`${diagnostics.unlabeledFields.length} visible fields have no accessible label`);
  if (diagnostics.errorToasts?.length) violations.push(`${diagnostics.errorToasts.length} visible error toasts remain on the surface`);
  if (/failed to fetch|fetch failed/i.test(diagnostics.bodyText)) violations.push("raw fetch failure text is visible");
  if (accessibilityNodeCount === 0) violations.push("accessibility tree is empty");
  if (violations.length > 0) {
    throw new Error(`${slug} failed deterministic UI diagnostics: ${violations.join("; ")}`);
  }
  const stem = `${String(number).padStart(2, "0")}-${slug}`;
  const imagePath = path.join(outputRoot, `${stem}.png`);
  const evidencePath = path.join(outputRoot, `${stem}.json`);
  fs.writeFileSync(imagePath, bytes, { flag: "wx" });
  fs.writeFileSync(evidencePath, `${JSON.stringify({ diagnostics, accessibilityTree: accessibility.nodes }, null, 2)}\n`, { flag: "wx" });
  report.capture.steps.push({
    number,
    description,
    status: "captured",
    image: imagePath,
    evidence: evidencePath,
    bytes: bytes.length,
    sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
    dimensions: pngDimensions(bytes),
    diagnostics,
    accessibilityNodeCount,
  });
}

async function captureNext(client, slug, description, settleMs = 350) {
  captureSequence += 1;
  await captureStep(client, captureSequence, slug, description, settleMs);
}

async function startForeignEndpoint(port) {
  const server = http.createServer((_request, response) => {
    response.statusCode = 200;
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify({ product: "not-webfa", status: "occupied" }));
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  return server;
}

async function closeServer(server) {
  if (!server?.listening) return;
  await new Promise((resolve, reject) => {
    server.close((error) => error ? reject(error) : resolve());
  });
}

async function clickButton(client, predicate, label) {
  const actions = await client.evaluate(String.raw`(() => Array.from(document.querySelectorAll("button")).filter((button) => button.getClientRects().length > 0).map((button) => ({ text: button.textContent.trim().replace(/\s+/g, " "), ariaLabel: button.getAttribute("aria-label"), disabled: button.disabled })))()`);
  report.capture.steps.at(-1).availableActionsBeforeNextStep = actions;
  const clicked = await client.evaluate(`(() => { const button = Array.from(document.querySelectorAll("button")).find((candidate) => ${predicate}); if (!button || button.disabled) return false; button.click(); return true; })()`);
  if (!clicked) throw new Error(`Could not activate ${label}`);
}

async function setViewport(client, width, height) {
  let observed;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await client.send("Page.bringToFront");
    if (attempt > 1) await client.send("Emulation.clearDeviceMetricsOverride");
    await client.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false, screenWidth: width, screenHeight: height });
    await client.evaluate(`window.dispatchEvent(new Event("resize"))`);
    await new Promise((resolve) => setTimeout(resolve, 500));
    observed = await client.evaluate(`({ width: innerWidth, height: innerHeight, compact920: matchMedia("(max-width: 920px)").matches, compact820: matchMedia("(max-width: 820px)").matches })`);
    if (observed?.width === width && observed?.height === height) return;
  }
  throw new Error(`Viewport override did not converge to ${width}x${height}: ${JSON.stringify(observed)}`);
}

async function clearViewport(client) {
  await client.send("Emulation.clearDeviceMetricsOverride");
  await new Promise((resolve) => setTimeout(resolve, 500));
}

async function pressKey(client, key, code, windowsVirtualKeyCode, modifiers = 0) {
  const text = modifiers === 0 && key === "Enter" ? "\r" : undefined;
  const params = {
    key,
    code,
    windowsVirtualKeyCode,
    nativeVirtualKeyCode: windowsVirtualKeyCode,
    modifiers,
    ...(text ? { text, unmodifiedText: text } : {}),
  };
  await client.send("Input.dispatchKeyEvent", { type: "keyDown", ...params });
  await client.send("Input.dispatchKeyEvent", { type: "keyUp", ...params });
  await new Promise((resolve) => setTimeout(resolve, 250));
}

async function pressEscape(client) {
  await pressKey(client, "Escape", "Escape", 27);
}

async function pressEnter(client) {
  await pressKey(client, "Enter", "Enter", 13);
}

async function pressTab(client, shift = false) {
  await pressKey(client, "Tab", "Tab", 9, shift ? 8 : 0);
}

async function activeFocus(client) {
  return client.evaluate(String.raw`(() => {
    const element = document.activeElement;
    if (!(element instanceof HTMLElement)) return null;
    const rect = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return {
      tag: element.tagName.toLowerCase(),
      id: element.id,
      ariaLabel: element.getAttribute("aria-label"),
      text: (element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 160),
      className: String(element.className).slice(0, 180),
      visible: rect.width > 0 && rect.height > 0 && style.visibility !== "hidden",
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
      withinControlPanel: Boolean(element.closest("#webfa-control-panel")),
      withinAgentView: Boolean(element.closest("#webfa-agent-view")),
      withinMonitorLeft: element.closest('aside[aria-label="会话上下文"]') !== null,
      withinMonitorRight: element.closest('aside[aria-label="活动与安全"]') !== null,
    };
  })()`);
}

async function tabToFocus(client, matcher, label, { shift = false, maximum = 24 } = {}) {
  let observation;
  for (let index = 0; index < maximum; index += 1) {
    await pressTab(client, shift);
    observation = await activeFocus(client);
    if (matcher(observation)) return observation;
  }
  throw new Error(`${label} was not keyboard reachable: ${JSON.stringify(observation)}`);
}

async function focusRecoveryAction(client, expectedText, label) {
  await client.evaluate(`document.querySelector("#webfa-main-content")?.focus()`);
  const observation = await tabToFocus(
    client,
    (focus) => focus?.tag === "button" && focus.text.includes(expectedText),
    label,
  );
  if (!observation.visible || observation.outlineStyle === "none" || observation.outlineWidth === "0px") {
    throw new Error(`${label} does not expose a visible keyboard focus indicator: ${JSON.stringify(observation)}`);
  }
  return observation;
}

async function waitForProcessExit(timeoutMs) {
  if (!appProcess || appProcess.exitCode !== null) return true;
  return new Promise((resolve) => {
    const onExit = () => { clearTimeout(timer); resolve(true); };
    const timer = setTimeout(() => { appProcess?.removeListener("exit", onExit); resolve(false); }, timeoutMs);
    appProcess.once("exit", onExit);
  });
}

function terminateOwnedProcesses() {
  const script = String.raw`
$ErrorActionPreference = "Stop"
$root = [IO.Path]::GetFullPath($env:WEBFA_OWNED_INSTALL_ROOT).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
Get-CimInstance Win32_Process | Where-Object {
  $_.ExecutablePath -and [IO.Path]::GetFullPath($_.ExecutablePath).StartsWith($root, [StringComparison]::OrdinalIgnoreCase)
} | Sort-Object ProcessId -Descending | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop }
`;
  runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
    env: { ...process.env, WEBFA_OWNED_INSTALL_ROOT: installRoot },
  });
}

async function closeApplication() {
  if (mainClient) {
    try { await mainClient.send("Browser.close", {}, 5_000); } catch { /* transport closes first */ }
  }
  if (await waitForProcessExit(30_000)) {
    report.lifecycle.gracefulBrowserClose = true;
    return;
  }
  terminateOwnedProcesses();
  if (!(await waitForProcessExit(10_000))) throw new Error("Installed Electron process tree did not exit");
  report.lifecycle.forcedOwnedProcessCleanup = true;
}

async function closeMonitorWindow() {
  if (!monitorClient) return;
  try { await monitorClient.send("Page.close", {}, 5_000); } catch { /* page transport may close first */ }
  monitorClient.close();
  monitorClient = undefined;
  await new Promise((resolve) => setTimeout(resolve, 500));
}

function rejectedLogDiagnostics(log, patterns) {
  return patterns.flatMap(([name, pattern]) => {
    const match = pattern.exec(log);
    if (!match) return [];
    const start = Math.max(0, match.index - 120);
    return [{ name, excerpt: log.slice(start, match.index + match[0].length + 240) }];
  });
}

function validateApplicationLogs() {
  const allLog = appLog.join("");
  const cleanScenarios = ["baseline", "missing-browser", "startup-timeout", "sidecar-recovery"];
  const cleanLog = cleanScenarios.map((name) => (applicationLogs.get(name) ?? []).join("")).join("");
  const cleanRejectedPatterns = [
    ["Node or Electron warning", /\b(?:DeprecationWarning|ExperimentalWarning|Warning):/],
    ["Python traceback", /Traceback \(most recent call last\):/],
    ["unhandled JavaScript failure", /\b(?:UnhandledPromiseRejection|uncaught exception)\b/i],
    ["runtime error level", /^\s*(?:\[[^\]]+\]\s*)?(?:ERROR|FATAL|CRITICAL)\b/im],
    ["Chromium error level", /^\s*\[[^\r\n]+\]:(?:ERROR|FATAL):/im],
    ["Runtime manager error diagnostic", /\[webfa-runtime\][^\r\n]*(?:error|failed)/i],
    ["Electron IPC handler error", /Error occurred in handler/i],
    ["HTTP error response", /HTTP\/1\.1"\s+[45]\d{2}\b/],
    ["application launch error", /launch error:/i],
  ];
  const rejected = rejectedLogDiagnostics(cleanLog, cleanRejectedPatterns);
  const faultRejectedPatterns = [
    ["Node or Electron warning", /\b(?:DeprecationWarning|ExperimentalWarning|Warning):/],
    ["Python traceback", /Traceback \(most recent call last\):/],
    ["unhandled JavaScript failure", /\b(?:UnhandledPromiseRejection|uncaught exception)\b/i],
    ["Chromium error level", /^\s*\[[^\r\n]+\]:(?:ERROR|FATAL):/im],
    ["Electron IPC handler error", /Error occurred in handler/i],
    ["HTTP error response", /HTTP\/1\.1"\s+[45]\d{2}\b/],
    ["application launch error", /launch error:/i],
    ["Desktop initialization failure", /WebFA Desktop failed to initialize/i],
    ["unexpected Runtime startup wrapper", /\[webfa-runtime\] Runtime startup failed/i],
    ["failed-start cleanup error", /\[webfa-runtime\] Failed-start cleanup did not complete/i],
    ["process-tree cleanup error", /\[webfa-runtime\] Runtime process-tree cleanup failed/i],
  ];
  const expectedFaults = ["missing-sidecar", "corrupt-sidecar"].map((scenario) => {
    const log = (applicationLogs.get(scenario) ?? []).join("");
    const diagnostics = log.match(/\[webfa-runtime\] Runtime process (?:could not be spawned|emitted an error)/gi) ?? [];
    const unexpected = rejectedLogDiagnostics(log, faultRejectedPatterns);
    if (diagnostics.length !== 1) {
      unexpected.push({
        name: "expected spawn diagnostic count",
        excerpt: `Expected exactly one local spawn diagnostic, observed ${diagnostics.length}: ${log.slice(0, 400)}`,
      });
    }
    return {
      scenario,
      status: unexpected.length === 0 ? "pass" : "fail",
      checkedBytes: Buffer.byteLength(log, "utf8"),
      expectedSpawnDiagnostics: diagnostics.length,
      unexpected,
    };
  });
  for (const fault of expectedFaults) {
    rejected.push(...fault.unexpected.map((item) => ({ ...item, scenario: fault.scenario })));
  }
  report.capture.applicationLogValidation = {
    status: rejected.length === 0 ? "pass" : "fail",
    checkedBytes: Buffer.byteLength(allLog, "utf8"),
    cleanScenarios,
    expectedFaults,
    rejected,
  };
  if (rejected.length > 0) {
    throw new Error(`Installed application log contains rejected diagnostics: ${rejected.map((item) => item.name).join(", ")}`);
  }
}

function buildSleeperExecutable() {
  fs.mkdirSync(failureHarnessRoot, { recursive: true });
  const script = String.raw`
$ErrorActionPreference = "Stop"
$source = 'using System.Threading; public static class Program { public static void Main(string[] args) { Thread.Sleep(60000); } }'
Add-Type -TypeDefinition $source -Language CSharp -OutputAssembly $env:WEBFA_SLEEPER_TARGET -OutputType ConsoleApplication
`;
  runFile("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
    capture: true,
    timeoutMs: 60_000,
    env: { ...process.env, WEBFA_SLEEPER_TARGET: sleeperExecutable },
  });
  const stat = fs.lstatSync(sleeperExecutable);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size < 1_024) {
    throw new Error("Failure harness did not produce a regular sleeper executable");
  }
}

function isolateInstalledSidecar() {
  if (sidecarIsolated || fs.existsSync(sidecarBackup)) throw new Error("Installed sidecar isolation is already active");
  const stat = fs.lstatSync(installedSidecar);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("Installed sidecar must be a regular file before fault injection");
  fs.mkdirSync(failureHarnessRoot, { recursive: true });
  fs.renameSync(installedSidecar, sidecarBackup);
  sidecarIsolated = true;
  const expectedHash = report.mcp.commandSha256;
  if (typeof expectedHash !== "string" || hashFile(sidecarBackup) !== expectedHash) {
    throw new Error("Isolated sidecar does not match the installed MCP executable identity");
  }
}

function clearInjectedSidecar() {
  if (!fs.existsSync(installedSidecar)) return;
  const stat = fs.lstatSync(installedSidecar);
  if (!stat.isFile() || stat.isSymbolicLink()) throw new Error("Injected sidecar path is not a regular file");
  fs.rmSync(installedSidecar, { force: true });
}

function restoreInstalledSidecar() {
  if (!sidecarIsolated && !fs.existsSync(sidecarBackup)) return;
  clearInjectedSidecar();
  if (!fs.existsSync(sidecarBackup)) throw new Error("Original installed sidecar backup is missing");
  fs.renameSync(sidecarBackup, installedSidecar);
  sidecarIsolated = false;
  if (hashFile(installedSidecar) !== report.mcp.commandSha256) {
    throw new Error("Restored installed sidecar identity changed");
  }
  report.lifecycle.installedSidecarRestored = true;
}

function removeFailureHarness() {
  if (sidecarIsolated || fs.existsSync(sidecarBackup)) {
    throw new Error("Failure harness cannot be removed before the original sidecar is restored");
  }
  if (!fs.existsSync(failureHarnessRoot)) return;
  assertOwnedPath(failureHarnessRoot, outputRoot);
  fs.rmSync(failureHarnessRoot, { recursive: true, force: true });
  report.lifecycle.failureHarnessRemoved = true;
}

async function connectMainTarget(label) {
  const target = await waitForTarget((candidate) => !candidate.url.includes("/monitor/"), `${label} Control Center target`);
  const client = await new CdpClient(target.webSocketDebuggerUrl).connect();
  await waitFor(
    () => client.evaluate(`document.readyState === "complete" && document.title === "WebFA Control Center"`),
    `${label} Control Center ready state`,
    45_000,
    150,
  );
  return { client, target };
}

async function waitForBoundedRuntimeFault(code, heading, label) {
  let observation;
  await waitFor(async () => {
    observation = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
    return observation?.state === "error"
      && observation?.ownership === "none"
      && observation?.issue?.code === code
      && !observation?.pid;
  }, `${label} Runtime status`, 45_000, 150);
  const presentation = await waitFor(async () => {
    const value = await mainClient.evaluate(`({ text: document.body.innerText, html: document.body.innerHTML })`);
    return value.text.includes(heading) ? value : undefined;
  }, `${label} bounded presentation`, 15_000, 100);
  const exposed = [installRoot, installedSidecar, "ENOENT", "spawn UNKNOWN", "spawn "]
    .filter((value) => presentation.text.toLowerCase().includes(value.toLowerCase()));
  if (exposed.length > 0) {
    throw new Error(`${label} presentation exposed private diagnostics: ${exposed.join(", ")}`);
  }
  return observation;
}

async function closeScenarioApplication() {
  await closeApplication();
  mainClient?.close();
  mainClient = undefined;
}

async function uninstallAndClean() {
  if (fs.existsSync(uninstaller)) runWindowsProcessTree(uninstaller, "/currentuser /S");
  await waitFor(() => !fs.existsSync(installRoot), "installed directory removal", 60_000, 250);
  const clean = lifecyclePreflight();
  report.lifecycle.uninstalled = true;
  report.lifecycle.cleanState = clean.installedStateClean;
}

async function runAudit() {
  fs.mkdirSync(outputRoot, { recursive: true });
  report.lifecycle.preflight = lifecyclePreflight();
  writeMarker();
  lifecycleStarted = true;
  runWindowsProcessTree(installer, `/S /D=${installRoot}`);
  await waitFor(() => fs.existsSync(executable), "installed executable", 30_000, 200);
  report.lifecycle.installed = true;

  [apiPort, debugPort] = await reservePorts(2);
  report.capture.apiPort = apiPort;
  report.capture.debugPort = debugPort;
  fs.mkdirSync(runtimeData, { recursive: true });
  launchApp({}, "baseline");

  const mainTarget = await waitForTarget((target) => !target.url.includes("/monitor/"), "Control Center target");
  report.capture.mainTarget = { id: mainTarget.id, title: mainTarget.title, url: mainTarget.url };
  mainClient = await new CdpClient(mainTarget.webSocketDebuggerUrl).connect();
  await waitFor(async () => {
    const state = await mainClient.evaluate(`({ ready: document.readyState, title: document.title, text: document.body?.innerText || "" })`);
    report.capture.mainReadyObservation = { ...state, text: state.text.slice(0, 1000) };
    return state.ready === "complete" && state.title === "WebFA Control Center" && state.text.includes("WebFA");
  }, "Control Center ready state", 60_000, 250);
  await waitFor(
    () => mainClient.evaluate(`document.body.innerText.includes("正在启动 WebFA Runtime") || document.body.innerText.includes("正在连接 Runtime")`),
    "Control Center startup boundary",
    15_000,
    50,
  );
  await captureNext(mainClient, "control-center-startup", "Installed Control Center while Runtime identity and protected state are still being verified", 0);
  await waitFor(async () => {
    const status = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
    report.capture.runtimeReadyObservation = status;
    return status?.state === "running" && status?.ownership === "desktop";
  }, "verified Desktop Runtime ownership", 60_000, 250);
  await waitFor(() => mainClient.evaluate(`document.querySelector('[aria-label="Runtime 状态：running"]') !== null`), "reconciled Runtime status", 10_000, 250);

  await mainClient.evaluate(`document.activeElement instanceof HTMLElement && document.activeElement.blur()`);
  await pressTab(mainClient);
  const controlCenterSkipFocus = await activeFocus(mainClient);
  if (!controlCenterSkipFocus?.className.includes("viz-skip-link") || !controlCenterSkipFocus.visible) {
    throw new Error(`Control Center skip link is not the first visible keyboard stop: ${JSON.stringify(controlCenterSkipFocus)}`);
  }
  await pressEnter(mainClient);
  await waitFor(() => mainClient.evaluate(`document.activeElement?.id === "webfa-main-content"`), "Control Center skip-link target focus", 5_000, 50);
  report.capture.keyboard = {
    controlCenterSkipLink: { status: "pass", focus: controlCenterSkipFocus, target: "webfa-main-content" },
  };
  await mainClient.evaluate(`document.activeElement instanceof HTMLElement && document.activeElement.blur()`);

  await captureNext(mainClient, "control-center-overview", "Control Center overview at the installed desktop viewport");
  await clickButton(mainClient, `candidate.textContent.trim() === "身份"`, "Identity section");
  await waitFor(() => mainClient.evaluate(`document.body.innerText.includes("Profile bootstrap")`), "Identity section");
  await captureNext(mainClient, "control-center-identity", "Profile identity and bootstrap management surface");
  await clickButton(mainClient, `candidate.textContent.trim() === "安全"`, "Safety section");
  await waitFor(() => mainClient.evaluate(`document.body.innerText.includes("Safety center")`), "Safety section");
  await captureNext(mainClient, "control-center-safety", "Resource grants and safety-management surface");

  await clickButton(mainClient, `candidate.textContent.trim() === "概览"`, "Overview section");
  await setViewport(mainClient, 390, 844);
  await waitFor(() => mainClient.evaluate(`matchMedia("(max-width: 920px)").matches && document.querySelector("#webfa-control-panel")?.hidden === true`), "compact Control Center layout");
  await captureNext(mainClient, "control-center-mobile", "Compact Control Center with both drawers closed");
  await mainClient.evaluate(`document.querySelector("#webfa-main-content")?.focus()`);
  const controlCenterDrawerTrigger = await tabToFocus(
    mainClient,
    (focus) => focus?.ariaLabel === "展开控制面板",
    "Control Center drawer trigger",
  );
  await pressEnter(mainClient);
  await waitFor(() => mainClient.evaluate(`document.querySelector("#webfa-control-panel")?.hidden === false && document.querySelector("#webfa-main-content")?.hasAttribute("inert")`), "Control Center drawer open");
  await waitFor(() => mainClient.evaluate(`document.activeElement?.closest("#webfa-control-panel") !== null`), "Control Center drawer initial focus", 5_000, 50);
  await captureNext(mainClient, "control-center-mobile-drawer", "Compact Control Center drawer, inert background, and focus treatment");
  const controlCenterDrawerFirst = await activeFocus(mainClient);
  await pressTab(mainClient, true);
  const controlCenterDrawerLast = await activeFocus(mainClient);
  if (!controlCenterDrawerLast?.withinControlPanel || controlCenterDrawerLast.text === controlCenterDrawerFirst?.text) {
    throw new Error(`Control Center drawer did not wrap Shift+Tab within the modal: ${JSON.stringify({ first: controlCenterDrawerFirst, last: controlCenterDrawerLast })}`);
  }
  await pressTab(mainClient);
  const controlCenterDrawerWrapped = await activeFocus(mainClient);
  if (!controlCenterDrawerWrapped?.withinControlPanel || controlCenterDrawerWrapped.text !== controlCenterDrawerFirst?.text) {
    throw new Error(`Control Center drawer did not wrap Tab to its first control: ${JSON.stringify(controlCenterDrawerWrapped)}`);
  }
  await pressEscape(mainClient);
  const restoredFocus = await mainClient.evaluate(`document.activeElement?.getAttribute("aria-label")`);
  if (restoredFocus !== "展开控制面板") throw new Error(`Control Center focus was not restored: ${restoredFocus}`);
  report.capture.controlCenterDrawerFocusRestored = true;
  report.capture.keyboard.controlCenterDrawer = {
    status: "pass",
    trigger: controlCenterDrawerTrigger,
    first: controlCenterDrawerFirst,
    wrappedFromLast: controlCenterDrawerLast,
    restoredTo: restoredFocus,
  };
  await mainClient.evaluate(`(() => {
    const panel = document.querySelector("#webfa-control-panel");
    if (panel instanceof HTMLElement) {
      panel.scrollTop = 0;
      panel.querySelectorAll("*").forEach((element) => {
        if (element instanceof HTMLElement) element.scrollTop = 0;
      });
    }
    if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
  })()`);
  await clearViewport(mainClient);

  const monitorOpened = await mainClient.evaluate(`window.webfaDesktop.openMonitor()`, true);
  if (monitorOpened?.opened !== true) throw new Error("Control Center did not open Monitor");
  const monitorTarget = await waitForTarget((target) => target.url.includes("/monitor/"), "Monitor target");
  monitorClient = await new CdpClient(monitorTarget.webSocketDebuggerUrl).connect();
  await waitFor(async () => {
    const state = await monitorClient.evaluate(`({ ready: document.readyState, title: document.title, text: document.body?.innerText || "" })`);
    report.capture.monitorReadyObservation = { ...state, text: state.text.slice(0, 1000) };
    return state.ready === "complete" && state.title === "WebFA 会话监控" && (state.text.includes("实时连接") || state.text.includes("等待会话") || state.text.includes("连接错误"));
  }, "Monitor stable state", 45_000, 250);
  await captureNext(monitorClient, "monitor-overview", "Installed Session Monitor at its desktop viewport");
  await monitorClient.evaluate(`document.activeElement instanceof HTMLElement && document.activeElement.blur()`);
  await pressTab(monitorClient);
  const monitorSkipFocus = await activeFocus(monitorClient);
  if (!monitorSkipFocus?.className.includes("skipLink") || !monitorSkipFocus.visible) {
    throw new Error(`Monitor skip link is not the first visible keyboard stop: ${JSON.stringify(monitorSkipFocus)}`);
  }
  await pressEnter(monitorClient);
  await waitFor(() => monitorClient.evaluate(`document.activeElement?.id === "webfa-monitor-surface"`), "Monitor skip-link target focus", 5_000, 50);
  report.capture.keyboard.monitorSkipLink = { status: "pass", focus: monitorSkipFocus, target: "webfa-monitor-surface" };
  await monitorClient.evaluate(`document.activeElement instanceof HTMLElement && document.activeElement.blur()`);

  await runInstalledMcpFlow();
  await waitFor(
    () => mainClient.evaluate(`document.body.innerText.includes("WebFA Frozen MCP Smoke") && document.body.innerText.includes("external-agent")`),
    "Control Center projection of the external MCP Agent session",
    30_000,
    250,
  );
  await mainClient.evaluate(`(() => {
    const panel = document.querySelector("#webfa-control-panel");
    if (panel instanceof HTMLElement) {
      panel.scrollTop = 0;
      panel.querySelectorAll("*").forEach((element) => {
        if (element instanceof HTMLElement) element.scrollTop = 0;
      });
    }
  })()`);
  await captureNext(mainClient, "control-center-agent-session", "Control Center projecting the real external MCP Agent session");
  await waitFor(
    () => monitorClient.evaluate(`(() => { const takeover = Array.from(document.querySelectorAll("button")).find((button) => button.textContent.includes("临时接管")); const body = document.body.innerText; return body.includes("实时连接") && body.includes("WebFA Frozen MCP Smoke") && body.includes("JPEG") && !body.includes("暂无视觉帧") && takeover && !takeover.disabled; })()`),
    "Monitor live projection of the external MCP Agent session",
    30_000,
    250,
  );
  await captureNext(monitorClient, "monitor-live-agent-session", "Installed Session Monitor projecting the real MCP-controlled BrowserHost");

  const keyboardTakeoverTrigger = await tabToFocus(
    monitorClient,
    (focus) => focus?.tag === "button" && focus.text.includes("临时接管"),
    "HumanControl takeover button",
    { shift: true },
  );
  await pressEnter(monitorClient);
  await waitFor(
    () => monitorClient.evaluate(`Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("完成并归还 Agent")) && document.body.innerText.includes("HumanControlLease")`),
    "HumanControlLease acquisition",
    15_000,
    200,
  );
  await waitFor(
    () => monitorClient.evaluate(`document.activeElement?.getAttribute("aria-label") === "人工接管键盘输入捕获"`),
    "HumanControl keyboard capture focus",
    5_000,
    50,
  );
  await pressEscape(monitorClient);
  const keyboardCaptureExit = await activeFocus(monitorClient);
  if (keyboardCaptureExit?.ariaLabel !== "继续页面键盘控制" || !keyboardCaptureExit.visible) {
    throw new Error(`Escape did not return HumanControl keyboard focus to Monitor controls: ${JSON.stringify(keyboardCaptureExit)}`);
  }
  const humanControlReleaseAvailable = await monitorClient.evaluate(`Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("完成并归还 Agent") && !button.disabled)`);
  if (!humanControlReleaseAvailable) {
    throw new Error("HumanControl release became unavailable while its lease was active");
  }
  await captureNext(monitorClient, "monitor-human-control", "Installed Session Monitor with HumanControl active and keyboard focus safely returned from the page capture");
  await pressEnter(monitorClient);
  await waitFor(() => monitorClient.evaluate(`document.activeElement?.getAttribute("aria-label") === "人工接管键盘输入捕获"`), "HumanControl keyboard re-entry", 5_000, 50);
  await pressEscape(monitorClient);
  await pressTab(monitorClient);
  const keyboardReleaseTrigger = await activeFocus(monitorClient);
  if (keyboardReleaseTrigger?.tag !== "button" || !keyboardReleaseTrigger.text.includes("完成并归还 Agent")) {
    throw new Error(`HumanControl release is not the next keyboard action after capture exit: ${JSON.stringify(keyboardReleaseTrigger)}`);
  }
  await pressEnter(monitorClient);
  await waitFor(
    () => monitorClient.evaluate(`Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("临时接管")) && document.body.innerText.includes("外部 Agent 控制")`),
    "Agent control restoration",
    15_000,
    200,
  );
  report.capture.keyboard.humanControl = {
    status: "pass",
    acquiredFrom: keyboardTakeoverTrigger,
    captureExit: keyboardCaptureExit,
    releaseAvailableWithoutFrameDependency: humanControlReleaseAvailable,
    reenteredCapture: true,
    releasedFrom: keyboardReleaseTrigger,
  };
  await captureNext(monitorClient, "monitor-agent-control-restored", "Installed Session Monitor after returning the same page to Agent control");

  await setViewport(monitorClient, 390, 844);
  await waitFor(() => monitorClient.evaluate(`matchMedia("(max-width: 820px)").matches && Array.from(document.querySelectorAll("aside")).every((panel) => panel.hidden)`), "compact Monitor layout");
  await captureNext(monitorClient, "monitor-mobile", "Compact live Session Monitor with sidebars closed");
  await monitorClient.evaluate(`document.querySelector("#webfa-monitor-surface")?.focus()`);
  const monitorDrawerTrigger = await tabToFocus(
    monitorClient,
    (focus) => focus?.ariaLabel === "展开左栏",
    "Monitor context drawer trigger",
  );
  await pressEnter(monitorClient);
  await waitFor(() => monitorClient.evaluate(`Array.from(document.querySelectorAll("aside")).some((panel) => !panel.hidden && panel.getAttribute("aria-label") === "会话上下文")`), "Monitor context drawer open");
  await waitFor(() => monitorClient.evaluate(`document.activeElement?.closest('aside[aria-label="会话上下文"]') !== null`), "Monitor drawer initial focus", 5_000, 50);
  await captureNext(monitorClient, "monitor-mobile-context-drawer", "Compact live Monitor context drawer and inert surface");
  const monitorDrawerFirst = await activeFocus(monitorClient);
  await pressTab(monitorClient, true);
  const monitorDrawerLast = await activeFocus(monitorClient);
  if (!monitorDrawerLast?.withinMonitorLeft) {
    throw new Error(`Monitor drawer did not wrap Shift+Tab within the modal: ${JSON.stringify({ first: monitorDrawerFirst, last: monitorDrawerLast })}`);
  }
  await pressTab(monitorClient);
  await pressEscape(monitorClient);
  const monitorFocus = await monitorClient.evaluate(`document.activeElement?.getAttribute("aria-label")`);
  if (monitorFocus !== "展开左栏") throw new Error(`Monitor focus was not restored: ${monitorFocus}`);
  report.capture.monitorDrawerFocusRestored = true;
  report.capture.keyboard.monitorDrawer = {
    status: "pass",
    trigger: monitorDrawerTrigger,
    first: monitorDrawerFirst,
    wrappedFromLast: monitorDrawerLast,
    restoredTo: monitorFocus,
  };

  await monitorClient.evaluate(`document.activeElement instanceof HTMLElement && document.activeElement.blur()`);
  const compactKeyboardTakeoverTrigger = await tabToFocus(
    monitorClient,
    (focus) => focus?.tag === "button" && focus.text.includes("临时接管"),
    "compact HumanControl takeover button",
  );
  await pressEnter(monitorClient);
  await waitFor(
    () => monitorClient.evaluate(`document.body.innerText.includes("HumanControl") && document.body.innerText.includes("完成并归还 Agent")`),
    "compact HumanControl lease",
    15_000,
    200,
  );
  await waitFor(
    () => monitorClient.evaluate(`document.activeElement?.getAttribute("aria-label") === "人工接管键盘输入捕获"`),
    "compact HumanControl keyboard capture focus",
    5_000,
    50,
  );
  await pressEscape(monitorClient);
  const compactKeyboardCaptureExit = await activeFocus(monitorClient);
  if (compactKeyboardCaptureExit?.ariaLabel !== "继续页面键盘控制" || !compactKeyboardCaptureExit.visible) {
    throw new Error(`Escape did not return compact HumanControl focus to Monitor controls: ${JSON.stringify(compactKeyboardCaptureExit)}`);
  }
  await captureNext(monitorClient, "monitor-human-control-mobile", "Compact live Session Monitor with HumanControl active and a local keyboard escape path");
  await pressTab(monitorClient);
  const compactKeyboardReleaseTrigger = await activeFocus(monitorClient);
  if (compactKeyboardReleaseTrigger?.tag !== "button" || !compactKeyboardReleaseTrigger.text.includes("完成并归还 Agent")) {
    throw new Error(`Compact HumanControl release is not the next keyboard action after capture exit: ${JSON.stringify(compactKeyboardReleaseTrigger)}`);
  }
  await pressEnter(monitorClient);
  await waitFor(
    () => monitorClient.evaluate(`Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("临时接管")) && !Array.from(document.querySelectorAll("button")).some((button) => button.textContent.includes("完成并归还 Agent"))`),
    "compact Agent control restoration",
    15_000,
    200,
  );
  report.capture.keyboard.humanControlCompact = {
    status: "pass",
    acquiredFrom: compactKeyboardTakeoverTrigger,
    captureExit: compactKeyboardCaptureExit,
    releasedFrom: compactKeyboardReleaseTrigger,
  };
  await releaseInstalledMcpFlow();

  await clearViewport(monitorClient);
  await waitFor(
    () => monitorClient.evaluate(`!matchMedia("(max-width: 820px)").matches && Array.from(document.querySelectorAll("aside")).length === 2 && Array.from(document.querySelectorAll("aside")).every((panel) => !panel.hidden)`),
    "desktop Monitor sidebar restoration after compact layout",
    5_000,
    50,
  );
  report.capture.desktopMonitorSidebarStateRestored = true;
  const stopped = await mainClient.evaluate(`window.webfaDesktop.stopRuntime()`, true);
  if (stopped?.state !== "stopped" || stopped?.ownership !== "none") {
    throw new Error(`Runtime did not stop at the installed UI boundary: ${JSON.stringify(stopped)}`);
  }
  await waitFor(
    () => mainClient.evaluate(`document.body.innerText.includes("Runtime 已停止") && document.querySelector('[aria-label="Runtime 状态：stopped"]') !== null`),
    "stopped Runtime presentation",
    15_000,
    100,
  );
  await captureNext(mainClient, "control-center-runtime-stopped", "Installed Control Center after a graceful Desktop-owned Runtime stop");
  await waitFor(
    () => monitorClient.evaluate(`(() => { const body = document.body.innerText; return (body.includes("连接错误") || body.includes("连接已断开")) && (body.includes("Monitor 连接失败") || body.includes("Monitor 已断开")) && body.includes("暂无视觉帧") && body.includes("无实时页面") && !body.includes("实时投影"); })()`),
    "disconnected Monitor presentation without stale visual projection",
    15_000,
    100,
  );
  await captureNext(monitorClient, "monitor-runtime-disconnected", "Installed Session Monitor after Runtime shutdown, with stale page state cleared");

  const foreignEndpoint = await startForeignEndpoint(apiPort);
  try {
    await clickButton(mainClient, `candidate.textContent.trim() === "启动 Runtime"`, "Runtime start against occupied endpoint");
    await waitFor(async () => {
      const status = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
      return status?.state === "error" && status?.ownership === "collision" && status?.issue?.code === "endpoint_collision";
    }, "bounded endpoint collision", 15_000, 100);
    await waitFor(
      () => mainClient.evaluate(`document.body.innerText.includes("Runtime 端口被其他服务占用")`),
      "endpoint collision presentation",
      10_000,
      100,
    );
    report.capture.keyboard.endpointCollisionAction = await focusRecoveryAction(mainClient, "重新检测并启动", "endpoint-collision recovery action");
    await captureNext(mainClient, "control-center-endpoint-collision", "Installed Control Center refusing an incompatible local endpoint without attaching");
    await setViewport(mainClient, 390, 844);
    await waitFor(
      () => mainClient.evaluate(`matchMedia("(max-width: 920px)").matches && document.body.innerText.includes("Runtime 端口被其他服务占用")`),
      "compact endpoint collision presentation",
      10_000,
      100,
    );
    await captureNext(mainClient, "control-center-endpoint-collision-mobile", "Compact Control Center endpoint-collision state with drawers closed");
    await clearViewport(mainClient);
  } finally {
    await closeServer(foreignEndpoint);
  }

  await clickButton(mainClient, `candidate.textContent.trim() === "重新检测并启动"`, "Runtime recovery after endpoint release");
  await waitFor(async () => {
    const status = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
    return status?.state === "running" && status?.ownership === "desktop";
  }, "Runtime recovery after endpoint release", 60_000, 150);
  await waitFor(
    () => mainClient.evaluate(`document.querySelector('[aria-label="Runtime 状态：running"]') !== null && document.body.innerText.includes("等待 Agent 打开网页")`),
    "recovered Control Center projection",
    15_000,
    100,
  );
  await captureNext(mainClient, "control-center-runtime-recovered", "Installed Control Center after recovering from an endpoint collision");
  report.capture.failureStates = {
    startupBoundaryCaptured: true,
    gracefulStopCaptured: true,
    monitorDisconnectCaptured: true,
    endpointCollisionCaptured: true,
    endpointCollisionCompactCaptured: true,
    recoveryCaptured: true,
  };

  await closeMonitorWindow();
  await closeApplication();
  mainClient?.close();
  mainClient = undefined;

  const isolatedPath = path.join(browserIsolationRoot, "path");
  const isolatedPrograms = path.join(browserIsolationRoot, "program-files");
  const isolatedProgramsX86 = path.join(browserIsolationRoot, "program-files-x86");
  const isolatedLocalApps = path.join(browserIsolationRoot, "local-app-data");
  for (const directory of [isolatedPath, isolatedPrograms, isolatedProgramsX86, isolatedLocalApps]) {
    fs.mkdirSync(directory, { recursive: true });
  }
  [apiPort, debugPort] = await reservePorts(2);
  report.capture.missingBrowserApiPort = apiPort;
  report.capture.missingBrowserDebugPort = debugPort;
  launchApp({
    PATH: isolatedPath,
    PROGRAMFILES: isolatedPrograms,
    "PROGRAMFILES(X86)": isolatedProgramsX86,
    PROGRAMW6432: isolatedPrograms,
    LOCALAPPDATA: isolatedLocalApps,
  }, "missing-browser");
  const missingBrowserTarget = await waitForTarget((target) => !target.url.includes("/monitor/"), "missing-browser Control Center target");
  report.capture.missingBrowserTarget = {
    id: missingBrowserTarget.id,
    title: missingBrowserTarget.title,
    url: missingBrowserTarget.url,
  };
  mainClient = await new CdpClient(missingBrowserTarget.webSocketDebuggerUrl).connect();
  await waitFor(async () => {
    const status = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
    return status?.state === "running" && status?.ownership === "desktop";
  }, "missing-browser Runtime ownership", 60_000, 150);
  await waitFor(
    () => mainClient.evaluate(`document.body.innerText.includes("浏览器运行环境未就绪") && document.body.innerText.includes("需要安装 Chrome 或 Edge")`),
    "missing-browser installed presentation",
    30_000,
    150,
  );
  report.capture.keyboard.missingBrowserAction = await focusRecoveryAction(mainClient, "重新检测浏览器", "missing-browser recovery action");
  await captureNext(mainClient, "control-center-browser-missing", "Installed Control Center with browser discovery isolated from every supported install root");
  await setViewport(mainClient, 390, 844);
  await waitFor(
    () => mainClient.evaluate(`matchMedia("(max-width: 920px)").matches && document.body.innerText.includes("浏览器运行环境未就绪")`),
    "compact missing-browser presentation",
    10_000,
    100,
  );
  await captureNext(mainClient, "control-center-browser-missing-mobile", "Compact installed Control Center missing-browser prerequisite state");
  report.capture.failureStates.missingBrowserCaptured = true;
  report.capture.failureStates.missingBrowserCompactCaptured = true;

  await closeScenarioApplication();

  buildSleeperExecutable();
  isolateInstalledSidecar();
  report.capture.failureStates.sidecarOriginalIsolated = true;

  [apiPort, debugPort] = await reservePorts(2);
  launchApp({}, "missing-sidecar");
  ({ client: mainClient } = await connectMainTarget("missing-sidecar"));
  report.capture.missingSidecarObservation = await waitForBoundedRuntimeFault(
    "spawn_failed",
    "无法启动 Runtime 进程",
    "missing-sidecar",
  );
  report.capture.keyboard.missingSidecarAction = await focusRecoveryAction(mainClient, "重试启动", "missing-sidecar recovery action");
  await captureNext(mainClient, "control-center-sidecar-missing", "Installed Control Center after the packaged Runtime executable is removed");
  report.capture.failureStates.missingSidecarCaptured = true;
  await closeScenarioApplication();

  fs.writeFileSync(installedSidecar, Buffer.from("WebFA audit invalid executable\r\n", "utf8"), { flag: "wx" });
  [apiPort, debugPort] = await reservePorts(2);
  launchApp({}, "corrupt-sidecar");
  ({ client: mainClient } = await connectMainTarget("corrupt-sidecar"));
  report.capture.corruptSidecarObservation = await waitForBoundedRuntimeFault(
    "spawn_failed",
    "无法启动 Runtime 进程",
    "corrupt-sidecar",
  );
  await setViewport(mainClient, 390, 844);
  report.capture.keyboard.corruptSidecarAction = await focusRecoveryAction(mainClient, "重试启动", "corrupt-sidecar recovery action");
  await captureNext(mainClient, "control-center-sidecar-corrupt-mobile", "Compact installed Control Center after the packaged Runtime executable is corrupted");
  report.capture.failureStates.corruptSidecarCompactCaptured = true;
  await closeScenarioApplication();
  clearInjectedSidecar();

  fs.copyFileSync(sleeperExecutable, installedSidecar, fs.constants.COPYFILE_EXCL);
  [apiPort, debugPort] = await reservePorts(2);
  launchApp({}, "startup-timeout");
  ({ client: mainClient } = await connectMainTarget("startup-timeout"));
  report.capture.startupTimeoutObservation = await waitForBoundedRuntimeFault(
    "startup_timeout",
    "Runtime 启动超时",
    "startup-timeout",
  );
  report.capture.keyboard.startupTimeoutAction = await focusRecoveryAction(mainClient, "重试启动", "startup-timeout recovery action");
  await captureNext(mainClient, "control-center-runtime-startup-timeout", "Installed Control Center after a real packaged Runtime process exceeds the startup deadline");
  report.capture.failureStates.startupTimeoutCaptured = true;
  await closeScenarioApplication();
  clearInjectedSidecar();

  restoreInstalledSidecar();
  [apiPort, debugPort] = await reservePorts(2);
  launchApp({}, "sidecar-recovery");
  ({ client: mainClient } = await connectMainTarget("sidecar-recovery"));
  await waitFor(async () => {
    const status = await mainClient.evaluate(`window.webfaDesktop.getRuntimeStatus()`, true);
    report.capture.sidecarRecoveryObservation = status;
    return status?.state === "running" && status?.ownership === "desktop";
  }, "restored sidecar Runtime ownership", 60_000, 150);
  await waitFor(
    () => mainClient.evaluate(`document.querySelector('[aria-label="Runtime 状态：running"]') !== null && document.body.innerText.includes("等待 Agent 打开网页")`),
    "restored sidecar Control Center projection",
    15_000,
    100,
  );
  if (hashFile(installedSidecar) !== report.mcp.commandSha256) {
    throw new Error("Recovered installed sidecar identity does not match the audited MCP executable");
  }
  await captureNext(mainClient, "control-center-sidecar-repaired", "Installed Control Center running again after exact sidecar restoration");
  report.capture.failureStates.sidecarRepairRecoveryCaptured = true;
  await closeScenarioApplication();

  validateApplicationLogs();
  removeFailureHarness();
  await uninstallAndClean();
  lifecycleStarted = false;
  report.status = "pass";
}

async function failureCleanup() {
  try { await releaseInstalledMcpFlow(); } catch (error) { report.lifecycle.mcpProbeCleanupError = String(error?.stack ?? error); }
  try { await closeApplication(); } catch (error) { report.lifecycle.closeError = String(error?.stack ?? error); }
  try { restoreInstalledSidecar(); } catch (error) { report.lifecycle.sidecarRestoreError = String(error?.stack ?? error); }
  try { removeFailureHarness(); } catch (error) { report.lifecycle.failureHarnessCleanupError = String(error?.stack ?? error); }
  try { await uninstallAndClean(); lifecycleStarted = false; } catch (error) { report.lifecycle.cleanupError = String(error?.stack ?? error); }
}

(async () => {
  try {
    await runAudit();
  } catch (error) {
    capturedError = error;
    report.status = "fail";
    report.error = String(error?.stack ?? error);
  } finally {
    if (lifecycleStarted) await failureCleanup();
    mainClient?.close();
    monitorClient?.close();
    report.capture.applicationLog = appLog.join("").slice(-100_000);
    report.capture.applicationLogs = Object.fromEntries(
      Array.from(applicationLogs, ([scenario, chunks]) => [scenario, chunks.join("").slice(-50_000)]),
    );
    if (fs.existsSync(runtimeData)) {
      assertOwnedPath(runtimeData, outputRoot);
      fs.rmSync(runtimeData, { recursive: true, force: true });
      report.lifecycle.runtimeDataRemoved = true;
    }
    if (fs.existsSync(browserIsolationRoot)) {
      assertOwnedPath(browserIsolationRoot, outputRoot);
      fs.rmSync(browserIsolationRoot, { recursive: true, force: true });
      report.lifecycle.browserIsolationRemoved = true;
    }
    fs.mkdirSync(outputRoot, { recursive: true });
    fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
    process.stdout.write(`${JSON.stringify({ status: report.status, outputRoot, reportPath, steps: report.capture.steps.length })}\n`);
  }
  if (capturedError) throw capturedError;
})().catch((error) => {
  process.stderr.write(`${error.stack ?? error}\n`);
  process.exitCode = 1;
});
