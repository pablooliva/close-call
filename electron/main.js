// Electron shell for Close Call (ADR 0001).
//
// Starts the Python server ("sidecar", built by build_desktop.py) on a free
// localhost port, waits until it answers, then shows the existing frontend in
// an app window. Quitting the app stops the server; if this process dies, the
// sidecar exits on its own because its stdin closes.

const { app, BrowserWindow, dialog, session, shell, systemPreferences } = require("electron");
const { spawn } = require("node:child_process");
const fs = require("node:fs");
const net = require("node:net");
const path = require("node:path");

// Generous: on first start, antivirus software may scan every file of the server
const STARTUP_TIMEOUT_MS = 180_000;

let server = null;
let quitting = false;

const LOADING_PAGE =
  "data:text/html;charset=utf-8," +
  encodeURIComponent(
    '<body style="font-family:system-ui;display:flex;align-items:center;justify-content:center;height:90vh;color:#555">' +
      "<div style=\"text-align:center\">Close Call wird gestartet …" +
      '<div style="font-size:0.85em;margin-top:0.6em;color:#888">Der erste Start kann einige Minuten dauern.</div>' +
      "</div></body>",
  );

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer();
    probe.once("error", reject);
    probe.listen(0, "127.0.0.1", () => {
      const { port } = probe.address();
      probe.close(() => resolve(port));
    });
  });
}

function serverCommand() {
  if (app.isPackaged) {
    const dir = path.join(process.resourcesPath, "server");
    const exe = process.platform === "win32" ? "closecall-server.exe" : "closecall-server";
    return { command: path.join(dir, exe), args: [], cwd: dir };
  }
  // Development: run the Python source from the repo root
  return { command: "uv", args: ["run", "python", "desktop.py"], cwd: path.join(__dirname, "..") };
}

function logPath() {
  return path.join(app.getPath("userData"), "logs", "server.log");
}

// Show the error once, name the log file, and quit (which stops the server)
function fail(message) {
  if (quitting) return;
  quitting = true;
  dialog.showErrorBox("Close Call", `${message}\n\nLog: ${logPath()}`);
  app.quit();
}

function startFailureMessage(err, command) {
  if (err.code === "ENOENT") {
    return `Die Serverdatei fehlt:\n${command}\n\nMöglicherweise hat der Virenschutz sie entfernt (Schutzverlauf prüfen).`;
  }
  if (err.code === "EACCES" || err.code === "EPERM") {
    return `Der Start des Servers wurde blockiert (${err.code}), möglicherweise durch Virenschutz oder eine IT-Richtlinie.`;
  }
  return `Der Server konnte nicht gestartet werden: ${err.message}`;
}

function startServer(port) {
  const userData = app.getPath("userData");
  fs.mkdirSync(path.dirname(logPath()), { recursive: true });
  const log = fs.openSync(logPath(), "a");
  const note = (text) => fs.writeSync(log, `[${new Date().toISOString()}] ${text}\n`);

  const { command, args, cwd } = serverCommand();
  // Written by the app itself, so the log is never empty even if the server never runs
  note(`Close Call ${app.getVersion()} (${process.platform}): starting ${command}`);
  server = spawn(command, args, {
    cwd,
    env: {
      ...process.env,
      PORT: String(port),
      CLOSECALL_SIDECAR: "1",
      CLOSECALL_ENV_FILE: path.join(userData, ".env"),
      CLOSECALL_DATA_DIR: userData,
    },
    stdio: ["pipe", log, log],
    windowsHide: true,
  });

  // Spawning itself failed: missing file, or blocked by antivirus / IT policy
  server.on("error", (err) => {
    note(`Could not start server: ${err.code || ""} ${err.message}`);
    server = null;
    fail(startFailureMessage(err, command));
  });

  server.on("exit", (code, signal) => {
    note(`Server exited (code ${code}, signal ${signal})`);
    server = null;
    fail(`Der Server wurde unerwartet beendet (Code ${code}).`);
  });
}

async function waitForServer(url) {
  const deadline = Date.now() + STARTUP_TIMEOUT_MS;
  while (Date.now() < deadline && server) {
    try {
      const res = await fetch(url, { redirect: "manual" });
      if (res.status < 500) return true;
    } catch {
      // Not listening yet
    }
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return false;
}

function restrictToApp(origin) {
  // Only the local frontend may use the microphone
  const allowed = (permission, requestingUrl) =>
    permission === "media" && (requestingUrl || "").startsWith(origin);
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) =>
    callback(allowed(permission, details.requestingUrl)),
  );
  session.defaultSession.setPermissionCheckHandler((_wc, permission, requestingOrigin) =>
    allowed(permission, requestingOrigin),
  );

  // Same-origin pages (e.g. the demo feedback) open in the app; anything else in the browser
  app.on("web-contents-created", (_event, contents) => {
    contents.setWindowOpenHandler(({ url }) => {
      if (url.startsWith(origin)) return { action: "allow" };
      shell.openExternal(url);
      return { action: "deny" };
    });
    contents.on("will-navigate", (event, url) => {
      if (!url.startsWith(origin)) {
        event.preventDefault();
        shell.openExternal(url);
      }
    });
  });
}

async function createWindow() {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  restrictToApp(origin); // before the window exists, so it is covered too

  const win = new BrowserWindow({
    width: 1100,
    height: 820,
    title: "Close Call",
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  win.loadURL(LOADING_PAGE);
  startServer(port);

  if (await waitForServer(`${origin}/`)) {
    win.loadURL(`${origin}/`);
  } else if (server) {
    fail(`Der Server hat nach ${STARTUP_TIMEOUT_MS / 60_000} Minuten noch nicht geantwortet.`);
  }
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const [win] = BrowserWindow.getAllWindows();
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });

  app.whenReady().then(async () => {
    // Ask for the mic up front (macOS shows its prompt once); don't block startup on the answer
    if (process.platform === "darwin") {
      systemPreferences.askForMediaAccess("microphone");
    }
    await createWindow();
  });

  app.on("before-quit", () => {
    quitting = true;
    if (server) server.kill();
  });

  // One window per app: closing it quits (and stops the server) on every platform
  app.on("window-all-closed", () => app.quit());
}
