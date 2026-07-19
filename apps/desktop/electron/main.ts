import { randomBytes } from "crypto";
import {
  app,
  BrowserWindow,
  dialog,
  ipcMain,
  Menu,
  nativeImage,
  shell,
  Tray,
  type IpcMainInvokeEvent,
} from "electron";
import { createReadStream, createWriteStream, promises as fs } from "fs";
import path from "path";
import { Readable } from "stream";
import { pipeline } from "stream/promises";
import { RendererAssetServer } from "./rendererServer";
import { RuntimeProcessManager, RuntimeStatus } from "./runtimeProcess";

function resolveApiHost(value: string | undefined): string {
  const host = (value ?? "127.0.0.1").trim().toLowerCase();
  if (!new Set(["127.0.0.1", "localhost"]).has(host)) {
    throw new Error("WEBFA_API_HOST must be 127.0.0.1 or localhost");
  }
  return host;
}

function resolveApiPort(value: string | undefined): number {
  const port = Number(value ?? "8787");
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error("WEBFA_API_PORT must be an integer between 1 and 65535");
  }
  return port;
}

const API_HOST = resolveApiHost(process.env.WEBFA_API_HOST);
const API_PORT = resolveApiPort(process.env.WEBFA_API_PORT);
const API_URL = `http://${API_HOST}:${API_PORT}`;
const SOURCE_CONSOLE_URL = process.env.WEBFA_DEV_RENDERER_URL ?? "http://127.0.0.1:8788";
let CONSOLE_URL = SOURCE_CONSOLE_URL;
let CONSOLE_LOCATION = new URL(CONSOLE_URL);
let MONITOR_URL = new URL("/monitor/", CONSOLE_LOCATION).href;
let CONSOLE_ORIGIN = CONSOLE_LOCATION.origin;
const APP_ROOT = app.isPackaged
  ? app.getAppPath()
  : process.env.WEBFA_ROOT ?? path.resolve(__dirname, "../../../..");
const CONFIGURED_DEV_CONTROL_TOKEN = app.isPackaged
  ? undefined
  : process.env.WEBFA_VISUALIZER_CONTROL_TOKEN;
const PROFILE_BUNDLE_CONTENT_TYPE = "application/vnd.webfa.profile-bundle";
const PROFILE_BUNDLE_EXTENSION = "webfa-profile";
const RELEASE_SMOKE_FLAG = "--webfa-release-smoke";
const RELEASE_SMOKE_RESULT_NAME = "release-smoke-result.json";
const RELEASE_SMOKE_REQUESTED = process.argv.includes(RELEASE_SMOKE_FLAG);

let mainWindow: BrowserWindow | null = null;
let mainWindowLoadPromise: Promise<void> | null = null;
let monitorWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let runtimeManager: RuntimeProcessManager;
let rendererServer: RendererAssetServer | null = null;
let isQuitting = false;
let shutdownStarted = false;
let shutdownComplete = false;
let applicationIconLoaded = false;
let releaseSmokeExitCode = 0;
let releaseSmokeEvidence: Record<string, unknown> | null = null;

function isAllowedConsoleLocation(location: URL): boolean {
  return (
    location.protocol === "http:" &&
    ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)
  );
}

if (!isAllowedConsoleLocation(CONSOLE_LOCATION)) {
  throw new Error("WEBFA console must use a local loopback HTTP URL");
}

function createVisualizerControlToken(): string {
  return CONFIGURED_DEV_CONTROL_TOKEN ?? randomBytes(32).toString("base64url");
}

function loadApplicationIcon() {
  const iconPath = app.isPackaged
    ? path.join(process.resourcesPath, "assets", "webfa.ico")
    : path.join(APP_ROOT, "packaging", "webfa.ico");
  const icon = nativeImage.createFromPath(iconPath);
  if (icon.isEmpty()) throw new Error(`WebFA application icon is missing or invalid: ${iconPath}`);
  return icon;
}

function requireOwnedRuntimeControl(): string {
  const token = runtimeManager?.getControlToken();
  if (!token) {
    throw new Error("Desktop control authority is unavailable until its owned Runtime is verified");
  }
  return token;
}

function isTrustedConsoleUrl(value: string): boolean {
  try {
    const candidate = new URL(value);
    return candidate.origin === CONSOLE_ORIGIN;
  } catch {
    return false;
  }
}

function configureConsoleLocation(value: string): void {
  const location = new URL(value);
  if (!isAllowedConsoleLocation(location)) {
    throw new Error("WEBFA console must use a local loopback HTTP URL");
  }
  CONSOLE_URL = location.href;
  CONSOLE_LOCATION = location;
  CONSOLE_ORIGIN = location.origin;
  MONITOR_URL = new URL("/monitor/", location).href;
}

function requireTrustedMainRenderer(event: IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) {
    throw new Error("WebFA Desktop IPC rejected an untrusted Control Center renderer");
  }
  const senderUrl = event.senderFrame?.url || event.sender.getURL();
  if (!isTrustedConsoleUrl(senderUrl)) {
    throw new Error("WebFA Desktop IPC rejected a renderer outside the Console location");
  }
}

function requireTrustedMonitorRenderer(event: IpcMainInvokeEvent): void {
  if (!monitorWindow || event.sender.id !== monitorWindow.webContents.id) {
    throw new Error("WebFA Desktop IPC rejected an untrusted Monitor renderer");
  }
  const senderUrl = event.senderFrame?.url || event.sender.getURL();
  if (!isTrustedConsoleUrl(senderUrl)) {
    throw new Error("WebFA Desktop IPC rejected a Monitor outside the Console location");
  }
}

function broadcastRuntimeStatus(status: RuntimeStatus): void {
  BrowserWindow.getAllWindows().forEach((window) => {
    window.webContents.send("runtime-status", status);
  });
}

function secureLocalWindow(window: BrowserWindow): void {
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedConsoleUrl(url)) event.preventDefault();
  });
  window.webContents.on("will-redirect", (event, url) => {
    if (!isTrustedConsoleUrl(url)) event.preventDefault();
  });
}

function createWindow(): BrowserWindow {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 720,
    minHeight: 640,
    title: "WebFA Desktop",
    icon: loadApplicationIcon(),
    show: !RELEASE_SMOKE_REQUESTED,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  secureLocalWindow(mainWindow);
  const loadPromise = mainWindow.loadURL(CONSOLE_URL);
  mainWindowLoadPromise = loadPromise;
  void loadPromise.catch((error) => {
    console.error("WebFA Control Center failed to load", error);
  });

  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });
  mainWindow.on("closed", () => {
    mainWindow = null;
    mainWindowLoadPromise = null;
  });
  return mainWindow;
}

async function waitForMainWindowLoad(timeoutMs = 20_000): Promise<BrowserWindow> {
  const window = mainWindow;
  const loadPromise = mainWindowLoadPromise;
  if (!window || window.isDestroyed() || !loadPromise) {
    throw new Error("Control Center window was not created for the release smoke");
  }
  let timer: NodeJS.Timeout | undefined;
  try {
    await Promise.race([
      loadPromise,
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(
          () => reject(new Error(`Control Center did not load within ${timeoutMs} ms`)),
          timeoutMs,
        );
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
  if (window.isDestroyed()) throw new Error("Control Center window was destroyed during loading");
  if (!isTrustedConsoleUrl(window.webContents.getURL())) {
    throw new Error("Control Center finished at an untrusted location");
  }
  return window;
}

async function writeReleaseSmokeResult(payload: Record<string, unknown>): Promise<void> {
  if (!RELEASE_SMOKE_REQUESTED || !app.isReady()) return;
  const resultPath = path.join(app.getPath("userData"), RELEASE_SMOKE_RESULT_NAME);
  const temporaryPath = `${resultPath}.tmp`;
  await fs.mkdir(path.dirname(resultPath), { recursive: true });
  await fs.writeFile(temporaryPath, `${JSON.stringify(payload, null, 2)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  await fs.rename(temporaryPath, resultPath);
}

async function collectReleaseSmokeEvidence(status: RuntimeStatus): Promise<Record<string, unknown>> {
  if (!app.isPackaged) throw new Error(`${RELEASE_SMOKE_FLAG} is available only in packaged builds`);
  if (
    status.state !== "running" ||
    status.ownership !== "desktop" ||
    status.releaseVersion !== app.getVersion() ||
    status.protocolVersion !== 1 ||
    !status.instanceId ||
    !status.pid
  ) {
    throw new Error(`Packaged Runtime did not reach verified desktop ownership: ${JSON.stringify(status)}`);
  }

  const window = await waitForMainWindowLoad();
  const renderer = (await window.webContents.executeJavaScript(`(() => ({
    readyState: document.readyState,
    title: document.title,
    hasMain: Boolean(document.querySelector("main")),
    hasWebfaBrand: document.body?.innerText.includes("WebFA") ?? false
  }))()`, true)) as {
    readyState?: unknown;
    title?: unknown;
    hasMain?: unknown;
    hasWebfaBrand?: unknown;
  };
  if (
    renderer.readyState !== "complete" ||
    renderer.title !== "WebFA Control Center" ||
    renderer.hasMain !== true ||
    renderer.hasWebfaBrand !== true
  ) {
    throw new Error(`Packaged Control Center did not expose the expected shell: ${JSON.stringify(renderer)}`);
  }

  const response = await fetch(`${API_URL}/health`, {
    cache: "no-store",
    headers: { Connection: "close" },
    signal: AbortSignal.timeout(5_000),
  });
  if (!response.ok) throw new Error(`Packaged Runtime health returned HTTP ${response.status}`);
  const health = (await response.json()) as Record<string, unknown>;
  if (
    health.product !== "webfa" ||
    health.release_version !== status.releaseVersion ||
    health.protocol_version !== status.protocolVersion ||
    health.instance_id !== status.instanceId
  ) {
    throw new Error(`Packaged Runtime health identity changed after startup: ${JSON.stringify(health)}`);
  }

  return {
    product: "webfa",
    releaseVersion: status.releaseVersion,
    protocolVersion: status.protocolVersion,
    runtimeInstanceId: status.instanceId,
    runtimePid: status.pid,
    runtimeOwnership: status.ownership,
    applicationIconLoaded,
    apiUrl: API_URL,
    userDataPath: app.getPath("userData"),
    consoleUrl: window.webContents.getURL(),
    renderer,
  };
}

function createMonitorWindow(): BrowserWindow {
  if (monitorWindow && !monitorWindow.isDestroyed()) {
    monitorWindow.show();
    monitorWindow.focus();
    return monitorWindow;
  }
  monitorWindow = new BrowserWindow({
    width: 1480,
    height: 920,
    minWidth: 980,
    minHeight: 640,
    title: "WebFA 会话监控",
    icon: loadApplicationIcon(),
    webPreferences: {
      preload: path.join(__dirname, "monitorPreload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: false
    }
  });
  secureLocalWindow(monitorWindow);
  void monitorWindow.loadURL(MONITOR_URL);
  monitorWindow.on("closed", () => {
    monitorWindow = null;
  });
  return monitorWindow;
}

type MonitorConfig =
  | {
      status: "ready";
      websocketUrl: string;
      token: string;
      sessionId: string;
      expiresAt: string;
    }
  | {
      status: "waiting";
      reason: "no_active_session";
      sessionId: string;
      retryAfterMs: number;
    }
  | {
      status: "unavailable";
      reason: "runtime_unavailable" | "monitor_config_failed";
      retryAfterMs: number;
    };

async function issueMonitorConfig(): Promise<MonitorConfig> {
  const status = runtimeManager?.getStatus();
  const controlToken = runtimeManager?.getControlToken();
  if (status?.state !== "running" || status.ownership !== "desktop" || !controlToken) {
    return unavailableMonitorConfig("runtime_unavailable");
  }
  const controlHeaders = { "X-WebFA-Visualizer-Token": controlToken };
  let sessionsResponse: Response;
  try {
    sessionsResponse = await fetch(`${API_URL}/v1/visualizer/sessions`, {
      cache: "no-store",
      headers: controlHeaders,
    });
  } catch {
    return unavailableMonitorConfig("runtime_unavailable");
  }
  if (!sessionsResponse.ok) {
    return unavailableMonitorConfig("monitor_config_failed");
  }
  let sessionsBody: { sessions?: unknown[] };
  try {
    sessionsBody = (await sessionsResponse.json()) as { sessions?: unknown[] };
  } catch {
    return unavailableMonitorConfig("monitor_config_failed");
  }
  if (!Array.isArray(sessionsBody.sessions) || sessionsBody.sessions.length === 0) {
    return waitingMonitorConfig();
  }
  let response: Response;
  try {
    response = await fetch(`${API_URL}/v1/visualizer/monitor-grants`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-WebFA-Visualizer-Token": controlToken
      },
      body: JSON.stringify({
        session_id: "default",
        permissions: ["events", "frames", "takeover"],
        ttl_seconds: 300
      })
    });
  } catch {
    return unavailableMonitorConfig("runtime_unavailable");
  }
  if (!response.ok) {
    const failure = await readControlApiFailure(response, "Monitor grant failed");
    if (response.status === 404 && failure.code === "monitor_session_not_found") {
      return {
        ...waitingMonitorConfig(),
      };
    }
    return unavailableMonitorConfig("monitor_config_failed");
  }
  const body = (await response.json()) as {
    grant: { token: string; session_id: string; expires_at: string };
  };
  return {
    status: "ready",
    websocketUrl: `${API_URL.replace(/^http/, "ws")}/v1/monitor/ws`,
    token: body.grant.token,
    sessionId: body.grant.session_id,
    expiresAt: body.grant.expires_at
  };
}

function unavailableMonitorConfig(
  reason: "runtime_unavailable" | "monitor_config_failed",
): Extract<MonitorConfig, { status: "unavailable" }> {
  return {
    status: "unavailable",
    reason,
    retryAfterMs: 2_000,
  };
}

function waitingMonitorConfig(): Extract<MonitorConfig, { status: "waiting" }> {
  return {
    status: "waiting",
    reason: "no_active_session",
    sessionId: "default",
    retryAfterMs: 5_000,
  };
}

async function readControlApiFailure(
  response: Response,
  fallback: string,
): Promise<{ code: string | null; message: string }> {
  try {
    const payload = (await response.json()) as {
      detail?: { code?: string; message?: string } | string;
    };
    if (typeof payload.detail === "string") {
      return { code: null, message: payload.detail };
    }
    if (payload.detail?.message) {
      return {
        code: typeof payload.detail.code === "string" ? payload.detail.code : null,
        message: payload.detail.message,
      };
    }
  } catch {
    // Fall back to the bounded generic message below.
  }
  return { code: null, message: `${fallback} (${response.status})` };
}

async function readControlApiError(response: Response, fallback: string): Promise<string> {
  return (await readControlApiFailure(response, fallback)).message;
}

function requireBundlePassphrase(value: unknown): string {
  if (typeof value !== "string" || value.length < 12 || value.length > 1024 || value.includes("\0")) {
    throw new Error("Profile Bundle passphrase must contain 12 to 1024 characters");
  }
  return value;
}

async function saveProfileBundle(args: {
  profileId: string;
  sourceVersion: number;
  previewToken: string;
  passphrase: string;
  suggestedFilename: string;
}): Promise<
  | { status: "cancelled" }
  | { status: "saved"; fileName: string; byteCount: number; sha256: string }
> {
  const controlToken = requireOwnedRuntimeControl();
  if (!mainWindow || mainWindow.isDestroyed()) throw new Error("Control Center window is unavailable");
  const passphrase = requireBundlePassphrase(args.passphrase);
  const suggestedFilename = path.basename(args.suggestedFilename || `webfa-profile.${PROFILE_BUNDLE_EXTENSION}`);
  const selection = await dialog.showSaveDialog(mainWindow, {
    title: "Export encrypted WebFA Profile Bundle",
    defaultPath: suggestedFilename,
    filters: [{ name: "WebFA Profile Bundle", extensions: [PROFILE_BUNDLE_EXTENSION] }]
  });
  if (selection.canceled || !selection.filePath) return { status: "cancelled" };

  const response = await fetch(
    `${API_URL}/v1/profiles/${encodeURIComponent(args.profileId)}/bootstrap/bundle/export`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-WebFA-Visualizer-Token": controlToken,
        "X-WebFA-Bundle-Passphrase": passphrase
      },
      body: JSON.stringify({
        preview_token: args.previewToken,
        expected_source_version: args.sourceVersion
      })
    }
  );
  if (!response.ok) {
    throw new Error(await readControlApiError(response, "Profile Bundle export failed"));
  }
  if (!response.body) throw new Error("Profile Bundle export returned no data");
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.startsWith(PROFILE_BUNDLE_CONTENT_TYPE)) {
    throw new Error("Profile Bundle export returned an unexpected content type");
  }

  try {
    await pipeline(
      Readable.fromWeb(response.body as never),
      createWriteStream(selection.filePath, { flags: "w", mode: 0o600 })
    );
  } catch (error) {
    await fs.unlink(selection.filePath).catch(() => undefined);
    throw error;
  }
  const fileStat = await fs.stat(selection.filePath);
  return {
    status: "saved",
    fileName: path.basename(selection.filePath),
    byteCount: fileStat.size,
    sha256: response.headers.get("x-webfa-bundle-sha256") ?? ""
  };
}

async function previewProfileBundleRestore(args: { passphrase: string }): Promise<
  | { status: "cancelled" }
  | { status: "previewed"; fileName: string; preview: Record<string, unknown> }
> {
  const controlToken = requireOwnedRuntimeControl();
  if (!mainWindow || mainWindow.isDestroyed()) throw new Error("Control Center window is unavailable");
  const passphrase = requireBundlePassphrase(args.passphrase);
  const selection = await dialog.showOpenDialog(mainWindow, {
    title: "Open encrypted WebFA Profile Bundle",
    properties: ["openFile"],
    filters: [{ name: "WebFA Profile Bundle", extensions: [PROFILE_BUNDLE_EXTENSION] }]
  });
  if (selection.canceled || selection.filePaths.length !== 1) return { status: "cancelled" };
  const filePath = selection.filePaths[0];
  const fileStat = await fs.stat(filePath);
  if (!fileStat.isFile() || fileStat.size <= 0) throw new Error("Selected Profile Bundle is empty or unavailable");

  const requestInit = {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      "Content-Length": String(fileStat.size),
      "X-WebFA-Visualizer-Token": controlToken,
      "X-WebFA-Bundle-Passphrase": passphrase
    },
    body: createReadStream(filePath),
    duplex: "half"
  } as unknown as RequestInit & { duplex: "half" };
  const response = await fetch(
    `${API_URL}/v1/profile-bundles/restore/preview`,
    requestInit
  );
  if (!response.ok) {
    throw new Error(await readControlApiError(response, "Profile Bundle restore preview failed"));
  }
  const preview = (await response.json()) as Record<string, unknown>;
  return { status: "previewed", fileName: path.basename(filePath), preview };
}

function createTray(): void {
  try {
    const icon = loadApplicationIcon();
    tray = new Tray(icon);
    applicationIconLoaded = true;
    tray.setToolTip("WebFA Desktop");
    tray.setContextMenu(Menu.buildFromTemplate([
      {
        label: "Open Console",
        click: () => {
          if (!mainWindow) createWindow();
          mainWindow?.show();
          mainWindow?.focus();
        }
      },
      {
        label: "Open Session Monitor",
        click: () => createMonitorWindow()
      },
      { type: "separator" },
      { label: "Start Runtime", click: () => runtimeManager.start() },
      { label: "Stop Runtime", click: () => runtimeManager.stop() },
      { type: "separator" },
      {
        label: "Open REST API",
        click: () => shell.openExternal(`${API_URL}/health`)
      },
      { type: "separator" },
      {
        label: "Quit",
        click: () => {
          isQuitting = true;
          app.quit();
        }
      }
    ]));
  } catch (error) {
    console.warn("Failed to create tray", error);
  }
}

const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  isQuitting = true;
  app.quit();
} else {
  app.on("second-instance", () => {
    if (!mainWindow && app.isReady()) createWindow();
    mainWindow?.show();
    mainWindow?.focus();
  });

  void app.whenReady().then(async () => {
    if (RELEASE_SMOKE_REQUESTED && !app.isPackaged) {
      throw new Error(`${RELEASE_SMOKE_FLAG} is available only in packaged builds`);
    }
    let sidecarExecutable: string | undefined;
    if (app.isPackaged) {
      const appArchive = app.getAppPath();
      const rendererRoot = path.join(appArchive, "apps", "desktop", "renderer", "out");
      rendererServer = new RendererAssetServer(rendererRoot, {
        integrityProtectedArchive: appArchive,
      });
      const rendererOrigin = await rendererServer.start();
      configureConsoleLocation(`${rendererOrigin}/`);
      sidecarExecutable = path.join(
        process.resourcesPath,
        "sidecar",
        process.platform === "win32" ? "webfa.exe" : "webfa",
      );
    }

    runtimeManager = new RuntimeProcessManager({
      appRoot: APP_ROOT,
      expectedReleaseVersion: app.getVersion(),
      workingDirectory: app.isPackaged ? app.getPath("userData") : APP_ROOT,
      dataDirectory: app.isPackaged ? app.getPath("userData") : undefined,
      sidecarExecutable,
      host: API_HOST,
      port: API_PORT,
      controlTokenFactory: createVisualizerControlToken,
      monitorAllowedOrigin: CONSOLE_ORIGIN,
      onStatus: broadcastRuntimeStatus
    });

    ipcMain.handle("runtime:getStatus", (event) => {
      requireTrustedMainRenderer(event);
      return runtimeManager.getStatus();
    });
    ipcMain.handle("runtime:start", (event) => {
      requireTrustedMainRenderer(event);
      return runtimeManager.start();
    });
    ipcMain.handle("runtime:stop", (event) => {
      requireTrustedMainRenderer(event);
      return runtimeManager.stop();
    });
    ipcMain.handle("desktop:getConfig", (event) => {
      requireTrustedMainRenderer(event);
      return {
        apiUrl: API_URL,
        consoleUrl: CONSOLE_URL,
        ...(runtimeManager.getControlToken()
          ? { visualizerControlToken: runtimeManager.getControlToken() }
          : {}),
      };
    });
    ipcMain.handle("monitor:open", (event) => {
      requireTrustedMainRenderer(event);
      createMonitorWindow();
      return { opened: true };
    });
    ipcMain.handle("profileBundle:save", (event, args) => {
      requireTrustedMainRenderer(event);
      return saveProfileBundle(args);
    });
    ipcMain.handle("profileBundle:previewRestore", (event, args) => {
      requireTrustedMainRenderer(event);
      return previewProfileBundleRestore(args);
    });
    ipcMain.handle("monitor:getConfig", async (event) => {
      requireTrustedMonitorRenderer(event);
      return issueMonitorConfig();
    });
    ipcMain.handle("monitor:openControlCenter", (event) => {
      requireTrustedMonitorRenderer(event);
      if (!mainWindow) createWindow();
      mainWindow?.show();
      mainWindow?.focus();
      return { opened: true };
    });

    createWindow();
    createTray();
    runtimeManager.start();

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
      mainWindow?.show();
    });

    if (RELEASE_SMOKE_REQUESTED) {
      const status = await runtimeManager.waitForStartup();
      releaseSmokeEvidence = await collectReleaseSmokeEvidence(status);
      isQuitting = true;
      app.quit();
    }
  }).catch((error) => {
    const message = error instanceof Error ? error.message : String(error);
    console.error("WebFA Desktop failed to initialize", error);
    if (RELEASE_SMOKE_REQUESTED) {
      releaseSmokeExitCode = 1;
      releaseSmokeEvidence = { error: message };
    } else {
      dialog.showErrorBox("WebFA Desktop failed to initialize", message);
    }
    isQuitting = true;
    app.quit();
  });
}

app.on("before-quit", (event) => {
  if (shutdownComplete) return;
  event.preventDefault();
  if (shutdownStarted) return;
  shutdownStarted = true;
  isQuitting = true;
  void (async () => {
    try {
      if (runtimeManager) await runtimeManager.stop();
      if (rendererServer) await rendererServer.stop();
      monitorWindow?.destroy();
      if (RELEASE_SMOKE_REQUESTED) {
        try {
          await writeReleaseSmokeResult({
            status: releaseSmokeExitCode === 0 ? "pass" : "fail",
            ...releaseSmokeEvidence,
            cleanup: {
              runtimeState: runtimeManager ? runtimeManager.getStatus().state : "uninitialized",
              rendererServerStopped: true,
            },
          });
        } catch (error) {
          releaseSmokeExitCode = 1;
          console.error("WebFA Desktop could not write release smoke evidence", error);
        }
        shutdownComplete = true;
        app.exit(releaseSmokeExitCode);
      } else {
        shutdownComplete = true;
        app.quit();
      }
    } catch (error) {
      shutdownStarted = false;
      isQuitting = false;
      const message = error instanceof Error ? error.message : String(error);
      console.error("WebFA Desktop refused to quit because owned processes remain", error);
      if (RELEASE_SMOKE_REQUESTED) {
        releaseSmokeExitCode = 1;
        await writeReleaseSmokeResult({
          status: "fail",
          ...releaseSmokeEvidence,
          error: message,
          cleanup: {
            runtimeState: runtimeManager ? runtimeManager.getStatus().state : "uninitialized",
            rendererServerStopped: false,
          },
        }).catch((writeError) => {
          console.error("WebFA Desktop could not write release smoke failure evidence", writeError);
        });
      } else {
        dialog.showErrorBox("WebFA Desktop could not shut down safely", message);
        mainWindow?.show();
        mainWindow?.focus();
      }
    }
  })();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
