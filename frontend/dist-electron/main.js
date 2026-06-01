import { BrowserWindow, app, ipcMain } from "electron";
import { fileURLToPath } from "node:url";
import path from "node:path";
//#region electron/main.ts
var __dirname = path.dirname(fileURLToPath(import.meta.url));
process.env.DIST = path.join(__dirname, "../dist");
process.env.VITE_PUBLIC = app.isPackaged ? process.env.DIST : path.join(process.env.DIST, "../public");
var win;
var VITE_DEV_SERVER_URL = process.env["VITE_DEV_SERVER_URL"];
function createWindow() {
	win = new BrowserWindow({
		width: 1200,
		height: 800,
		titleBarStyle: "hidden",
		trafficLightPosition: {
			x: 16,
			y: 16
		},
		webPreferences: {
			nodeIntegration: true,
			contextIsolation: false
		}
	});
	win.webContents.on("did-finish-load", () => {
		win?.webContents.send("main-process-message", (/* @__PURE__ */ new Date()).toLocaleString());
	});
	if (VITE_DEV_SERVER_URL) win.loadURL(VITE_DEV_SERVER_URL);
	else win.loadFile(path.join(process.env.DIST, "index.html"));
}
app.on("window-all-closed", () => {
	if (process.platform !== "darwin") {
		app.quit();
		win = null;
	}
});
app.on("activate", () => {
	if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
app.whenReady().then(() => {
	createWindow();
	ipcMain.on("window-min", () => {
		win?.minimize();
	});
	ipcMain.on("window-max", () => {
		if (win?.isMaximized()) win?.unmaximize();
		else win?.maximize();
	});
	ipcMain.on("window-close", () => {
		win?.close();
	});
});
//#endregion
export {};
