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
import { McpProcessManager, McpStatus } from "./mcpProcess";
import { RuntimeProcessManager, RuntimeStatus } from "./runtimeProcess";

const API_HOST = process.env.WEBFA_API_HOST ?? "127.0.0.1";
const API_PORT = Number(process.env.WEBFA_API_PORT ?? "8787");
const CONSOLE_URL = process.env.WEBFA_DEV_RENDERER_URL ?? "http://127.0.0.1:8788";
const CONSOLE_LOCATION = new URL(CONSOLE_URL);
const MONITOR_URL =
  process.env.WEBFA_MONITOR_RENDERER_URL ??
  (CONSOLE_LOCATION.protocol === "file:"
    ? new URL("monitor/index.html", CONSOLE_LOCATION).href
    : new URL("/monitor", CONSOLE_LOCATION).href);
const CONSOLE_ORIGIN = CONSOLE_LOCATION.origin;
const CONSOLE_FILE_BASE =
  CONSOLE_LOCATION.protocol === "file:" ? new URL(".", CONSOLE_LOCATION).href : null;
const APP_ROOT = process.env.WEBFA_ROOT ?? path.resolve(__dirname, "../../../..");
const VISUALIZER_CONTROL_TOKEN =
  process.env.WEBFA_VISUALIZER_CONTROL_TOKEN ?? randomBytes(32).toString("base64url");
const PROFILE_BUNDLE_CONTENT_TYPE = "application/vnd.webfa.profile-bundle";
const PROFILE_BUNDLE_EXTENSION = "webfa-profile";

let mainWindow: BrowserWindow | null = null;
let monitorWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let runtimeManager: RuntimeProcessManager;
let mcpManager: McpProcessManager;
let isQuitting = false;

function isAllowedConsoleLocation(location: URL): boolean {
  if (location.protocol === "file:") return true;
  return (
    location.protocol === "http:" &&
    ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)
  );
}

if (!isAllowedConsoleLocation(CONSOLE_LOCATION)) {
  throw new Error("WEBFA console must use a local loopback or file URL");
}

function isTrustedConsoleUrl(value: string): boolean {
  try {
    const candidate = new URL(value);
    if (CONSOLE_FILE_BASE) {
      return candidate.protocol === "file:" && candidate.href.startsWith(CONSOLE_FILE_BASE);
    }
    return candidate.origin === CONSOLE_ORIGIN;
  } catch {
    return false;
  }
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

function broadcastMcpStatus(status: McpStatus): void {
  BrowserWindow.getAllWindows().forEach((window) => {
    window.webContents.send("mcp-status", status);
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

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1180,
    height: 780,
    minWidth: 960,
    minHeight: 640,
    title: "WebFA Desktop",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  });

  secureLocalWindow(mainWindow);
  void mainWindow.loadURL(CONSOLE_URL);

  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });
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

async function issueMonitorConfig(): Promise<{
  websocketUrl: string;
  token: string;
  sessionId: string;
  expiresAt: string;
}> {
  const response = await fetch(`http://${API_HOST}:${API_PORT}/v1/visualizer/monitor-grants`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-WebFA-Visualizer-Token": VISUALIZER_CONTROL_TOKEN
    },
    body: JSON.stringify({
      session_id: "default",
      permissions: ["events", "frames", "takeover"],
      ttl_seconds: 300
    })
  });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`Failed to issue Monitor grant (${response.status}): ${body}`);
  }
  const body = (await response.json()) as {
    grant: { token: string; session_id: string; expires_at: string };
  };
  return {
    websocketUrl: `ws://${API_HOST}:${API_PORT}/v1/monitor/ws`,
    token: body.grant.token,
    sessionId: body.grant.session_id,
    expiresAt: body.grant.expires_at
  };
}

async function readControlApiError(response: Response, fallback: string): Promise<string> {
  try {
    const payload = (await response.json()) as {
      detail?: { message?: string } | string;
    };
    if (typeof payload.detail === "string") return payload.detail;
    if (payload.detail?.message) return payload.detail.message;
  } catch {
    // Fall back to the bounded generic message below.
  }
  return `${fallback} (${response.status})`;
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
    `http://${API_HOST}:${API_PORT}/v1/profiles/${encodeURIComponent(args.profileId)}/bootstrap/bundle/export`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-WebFA-Visualizer-Token": VISUALIZER_CONTROL_TOKEN
      },
      body: JSON.stringify({
        preview_token: args.previewToken,
        expected_source_version: args.sourceVersion,
        passphrase
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
      "X-WebFA-Visualizer-Token": VISUALIZER_CONTROL_TOKEN,
      "X-WebFA-Bundle-Passphrase": passphrase
    },
    body: createReadStream(filePath),
    duplex: "half"
  } as unknown as RequestInit & { duplex: "half" };
  const response = await fetch(
    `http://${API_HOST}:${API_PORT}/v1/profile-bundles/restore/preview`,
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
    const icon = nativeImage.createEmpty();
    tray = new Tray(icon);
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
      { label: "Start MCP Server", click: () => mcpManager.start() },
      { label: "Stop MCP Server", click: () => mcpManager.stop() },
      { label: "Restart MCP Server", click: () => mcpManager.restart() },
      { type: "separator" },
      {
        label: "Open REST API",
        click: () => shell.openExternal(`http://${API_HOST}:${API_PORT}/health`)
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

app.whenReady().then(() => {
  runtimeManager = new RuntimeProcessManager({
    appRoot: APP_ROOT,
    host: API_HOST,
    port: API_PORT,
    visualizerControlToken: VISUALIZER_CONTROL_TOKEN,
    monitorAllowedOrigin: CONSOLE_LOCATION.protocol === "file:" ? "null" : CONSOLE_ORIGIN,
    onStatus: broadcastRuntimeStatus
  });

  mcpManager = new McpProcessManager({
    appRoot: APP_ROOT,
    runtimeUrl: `http://${API_HOST}:${API_PORT}`,
    onStatus: broadcastMcpStatus
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
  ipcMain.handle("mcp:getStatus", (event) => {
    requireTrustedMainRenderer(event);
    return mcpManager.getStatus();
  });
  ipcMain.handle("mcp:start", (event) => {
    requireTrustedMainRenderer(event);
    return mcpManager.start();
  });
  ipcMain.handle("mcp:stop", (event) => {
    requireTrustedMainRenderer(event);
    return mcpManager.stop();
  });
  ipcMain.handle("mcp:restart", (event) => {
    requireTrustedMainRenderer(event);
    return mcpManager.restart();
  });
  ipcMain.handle("desktop:getConfig", (event) => {
    requireTrustedMainRenderer(event);
    return {
      apiUrl: `http://${API_HOST}:${API_PORT}`,
      consoleUrl: CONSOLE_URL,
      visualizerControlToken: VISUALIZER_CONTROL_TOKEN
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
  mcpManager.start();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    mainWindow?.show();
  });
});

app.on("before-quit", () => {
  isQuitting = true;
  monitorWindow?.destroy();
  mcpManager?.stop();
  runtimeManager?.stop();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
