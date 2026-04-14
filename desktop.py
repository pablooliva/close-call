"""Desktop launcher for Close Call.

Starts the FastAPI server in a background thread, opens the default
browser, and shows a small tkinter status window with a Quit button.
The tkinter window runs on the main thread (required by macOS) and
gives the app a Dock icon so users can quit normally.

Auth is bypassed via DESKTOP_MODE.

Run with: uv run python desktop.py
Build with: uv run python build_desktop.py
"""

import logging
import os
import signal
import socket
import sys
import threading
import time
import tkinter as tk
import webbrowser

import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_bundle_dir():
    """Return the directory containing bundled data files (static/, scenarios/).

    When running from source, this is the script's directory.
    When running from a PyInstaller bundle, this is sys._MEIPASS.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def get_exe_dir():
    """Return the directory containing the executable.

    When running from source, same as get_bundle_dir().
    When frozen, this is the folder containing the .exe/.app.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def wait_and_open_browser(port: int, timeout: float = 15.0):
    """Wait for the server to accept connections, then open the browser."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                url = f"http://127.0.0.1:{port}/"
                logger.info("Server ready — opening %s", url)
                webbrowser.open(url)
                return
        except OSError:
            pass
        time.sleep(0.3)
    logger.error("Server failed to start within %.0f seconds", timeout)


def run_server(app, port: int):
    """Run uvicorn in a background thread."""
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        workers=1,
        log_level="info",
    )


def create_status_window(port: int) -> None:
    """Show a small tkinter window with server status and a Quit button.

    Must be called from the main thread (macOS requirement for GUI).
    Closing the window or clicking Quit terminates the process.
    """
    root = tk.Tk()
    root.title("Close Call")
    root.resizable(False, False)

    # Center the window on screen
    width, height = 300, 130
    screen_w = root.winfo_screenwidth()
    screen_h = root.winfo_screenheight()
    x = (screen_w - width) // 2
    y = (screen_h - height) // 2
    root.geometry(f"{width}x{height}+{x}+{y}")

    frame = tk.Frame(root, padx=20, pady=15)
    frame.pack(expand=True, fill="both")

    tk.Label(
        frame,
        text="Close Call is running",
        font=("Helvetica", 14, "bold"),
    ).pack(pady=(0, 4))

    tk.Label(
        frame,
        text=f"Server: http://127.0.0.1:{port}",
        font=("Helvetica", 11),
        fg="#555555",
    ).pack(pady=(0, 12))

    def quit_app():
        logger.info("Quit requested — shutting down")
        root.destroy()
        os.kill(os.getpid(), signal.SIGTERM)

    tk.Button(
        frame,
        text="Quit Server",
        command=quit_app,
        width=14,
    ).pack()

    # Closing the window also quits
    root.protocol("WM_DELETE_WINDOW", quit_app)

    root.mainloop()


def main():
    # Set desktop mode so server skips auth
    os.environ["DESKTOP_MODE"] = "true"

    # Load .env: bundled inside the app first, then check next to executable (override)
    from dotenv import load_dotenv
    bundle_dir = get_bundle_dir()
    exe_dir = get_exe_dir()

    bundled_env = os.path.join(bundle_dir, ".env")
    if os.path.exists(bundled_env):
        load_dotenv(bundled_env, override=True)

    # An .env next to the executable overrides the bundled one,
    # so users can swap API keys without rebuilding
    external_env = os.path.join(exe_dir, ".env")
    if os.path.exists(external_env) and external_env != bundled_env:
        load_dotenv(external_env, override=True)

    # Change to bundle dir so static file and scenario paths resolve correctly
    os.chdir(bundle_dir)

    port = int(os.environ.get("PORT", "7860"))

    # Import app after env is loaded and cwd is set
    from server import app

    # Run uvicorn in a daemon thread so it dies when the main thread exits
    server_thread = threading.Thread(
        target=run_server, args=(app, port), daemon=True
    )
    server_thread.start()
    logger.info("Starting Close Call server on port %d ...", port)

    # Open browser once server is ready (background thread)
    threading.Thread(
        target=wait_and_open_browser, args=(port,), daemon=True
    ).start()

    # tkinter status window on main thread (required by macOS)
    create_status_window(port)


if __name__ == "__main__":
    main()
