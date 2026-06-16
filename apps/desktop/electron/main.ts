import { app, BrowserWindow, ipcMain, Menu, nativeImage, shell, Tray } from "electron";
import path from "path";
import { RuntimeProcessManager, RuntimeStatus } from "./runtimeProcess";

const API_HOST = process.env.WEBFA_API_HOST ?? "127.0.0.1";
const API_PORT = Number(process.env.WEBFA_API_PORT ?? "8787");
const CONSOLE_URL = process.env.WEBFA_DEV_RENDERER_URL ?? "http://127.0.0.1:8788";
const APP_ROOT = process.env.WEBFA_ROOT ?? path.resolve(__dirname, "../../../..");

let mainWindow: BrowserWindow | null = null;
let tray: Tray | null = null;
let runtimeManager: RuntimeProcessManager;
let isQuitting = false;

function broadcastRuntimeStatus(status: RuntimeStatus): void {
  BrowserWindow.getAllWindows().forEach((window) => {
    window.webContents.send("runtime-status", status);
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

  mainWindow.loadURL(CONSOLE_URL);

  mainWindow.on("close", (event) => {
    if (!isQuitting) {
      event.preventDefault();
      mainWindow?.hide();
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
      { label: "Start Runtime", click: () => runtimeManager.start() },
      { label: "Stop Runtime", click: () => runtimeManager.stop() },
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
    onStatus: broadcastRuntimeStatus
  });

  ipcMain.handle("runtime:getStatus", () => runtimeManager.getStatus());
  ipcMain.handle("runtime:start", () => runtimeManager.start());
  ipcMain.handle("runtime:stop", () => runtimeManager.stop());
  ipcMain.handle("desktop:getConfig", () => ({
    apiUrl: `http://${API_HOST}:${API_PORT}`,
    consoleUrl: CONSOLE_URL
  }));

  createWindow();
  createTray();
  runtimeManager.start();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
    mainWindow?.show();
  });
});

app.on("before-quit", () => {
  isQuitting = true;
  runtimeManager?.stop();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});
