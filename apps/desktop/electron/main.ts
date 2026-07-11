import { randomBytes } from "crypto";
import {
  app,
  BrowserWindow,
  ipcMain,
  Menu,
  nativeImage,
  shell,
  Tray,
  type IpcMainInvokeEvent,
} from "electron";
import path from "path";
import { AuthSurfaceBounds, AuthSurfaceManager } from "./authSurface";
import { McpProcessManager, McpStatus } from "./mcpProcess";
import { RuntimeProcessManager, RuntimeStatus } from "./runtimeProcess";

const API_HOST = process.env.WEBFA_API_HOST ?? "127.0.0.1";
const API_PORT = Number(process.env.WEBFA_API_PORT ?? "8787");
const CONSOLE_URL = process.env.WEBFA_DEV_RENDERER_URL ?? "http://127.0.0.1:8788";
const CONSOLE_LOCATION = new URL(CONSOLE_URL);
const CONSOLE_ORIGIN = CONSOLE_LOCATION.origin;
const CONSOLE_FILE_BASE =
  CONSOLE_LOCATION.protocol === "file:" ? new URL(".", CONSOLE_LOCATION).href : null;
const APP_ROOT = process.env.WEBFA_ROOT ?? path.resolve(__dirname, "../../../..");
const VISUALIZER_CONTROL_TOKEN =
  process.env.WEBFA_VISUALIZER_CONTROL_TOKEN ?? randomBytes(32).toString("base64url");

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let runtimeManager: RuntimeProcessManager;
let mcpManager: McpProcessManager;
let authSurfaceManager: AuthSurfaceManager;
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

function requireTrustedRenderer(event: IpcMainInvokeEvent): void {
  if (!mainWindow || event.sender.id !== mainWindow.webContents.id) {
    throw new Error("WebFA Desktop IPC rejected an untrusted renderer");
  }
  const senderUrl = event.senderFrame?.url || event.sender.getURL();
  if (!isTrustedConsoleUrl(senderUrl)) {
    throw new Error("WebFA Desktop IPC rejected a renderer outside the Console location");
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
      sandbox: false
    }
  });

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedConsoleUrl(url)) event.preventDefault();
  });
  mainWindow.webContents.on("will-redirect", (event, url) => {
    if (!isTrustedConsoleUrl(url)) event.preventDefault();
  });
  void mainWindow.loadURL(CONSOLE_URL);

  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
    }
  });

  mainWindow.on("resize", () => {
    if (mainWindow && authSurfaceManager) {
      mainWindow.webContents.send("auth-surface:request-bounds");
    }
  });
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
  authSurfaceManager = new AuthSurfaceManager();
  runtimeManager = new RuntimeProcessManager({
    appRoot: APP_ROOT,
    host: API_HOST,
    port: API_PORT,
    visualizerControlToken: VISUALIZER_CONTROL_TOKEN,
    onStatus: broadcastRuntimeStatus
  });

  mcpManager = new McpProcessManager({
    appRoot: APP_ROOT,
    runtimeUrl: `http://${API_HOST}:${API_PORT}`,
    onStatus: broadcastMcpStatus
  });

  ipcMain.handle("runtime:getStatus", (event) => {
    requireTrustedRenderer(event);
    return runtimeManager.getStatus();
  });
  ipcMain.handle("runtime:start", (event) => {
    requireTrustedRenderer(event);
    return runtimeManager.start();
  });
  ipcMain.handle("runtime:stop", (event) => {
    requireTrustedRenderer(event);
    return runtimeManager.stop();
  });
  ipcMain.handle("mcp:getStatus", (event) => {
    requireTrustedRenderer(event);
    return mcpManager.getStatus();
  });
  ipcMain.handle("mcp:start", (event) => {
    requireTrustedRenderer(event);
    return mcpManager.start();
  });
  ipcMain.handle("mcp:stop", (event) => {
    requireTrustedRenderer(event);
    return mcpManager.stop();
  });
  ipcMain.handle("mcp:restart", (event) => {
    requireTrustedRenderer(event);
    return mcpManager.restart();
  });
  ipcMain.handle("desktop:getConfig", (event) => {
    requireTrustedRenderer(event);
    return {
      apiUrl: `http://${API_HOST}:${API_PORT}`,
      consoleUrl: CONSOLE_URL,
      authSurfaceProfilePath: authSurfaceManager.getProfilePath(),
      visualizerControlToken: VISUALIZER_CONTROL_TOKEN
    };
  });
  ipcMain.handle("auth-surface:getStatus", (event) => {
    requireTrustedRenderer(event);
    return authSurfaceManager.getStatus();
  });
  ipcMain.handle("auth-surface:show", (event, payload: { url: string; bounds: AuthSurfaceBounds }) => {
    requireTrustedRenderer(event);
    if (!mainWindow) {
      throw new Error("main window is not available");
    }
    return authSurfaceManager.show(mainWindow, payload.bounds, payload.url);
  });
  ipcMain.handle("auth-surface:hide", (event) => {
    requireTrustedRenderer(event);
    return authSurfaceManager.hide();
  });
  ipcMain.handle("auth-surface:destroy", (event) => {
    requireTrustedRenderer(event);
    return authSurfaceManager.destroy();
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
  authSurfaceManager?.destroy();
  mcpManager?.stop();
  runtimeManager?.stop();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
