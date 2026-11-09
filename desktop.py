"""Headless server entry point for the Close Call desktop app (the "sidecar").

The Electron shell (electron/main.js) starts this process, waits until it
answers on 127.0.0.1:$PORT and shows the frontend in its own window.

Auth is bypassed via DESKTOP_MODE.

Environment set by Electron:
    PORT                  Free localhost port chosen by Electron.
    CLOSECALL_ENV_FILE    The user's .env in the app-data folder, written by the
                          setup page; overrides the bundled .env.example template.
    CLOSECALL_DATA_DIR    Writable folder for transcripts (the install folder
                          may be read-only, e.g. C:\\Program Files).
    CLOSECALL_SIDECAR=1   Exit when stdin closes, so the server never outlives
                          the app, even if Electron crashes.

Run with: uv run python desktop.py
Build with: uv run python build_desktop.py
"""

import logging
import os
import sys
import threading

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


def exit_when_stdin_closes():
    """Block until the parent closes our stdin (quit or crash), then exit."""
    sys.stdin.read()
    logger.info("Parent process closed stdin — shutting down")
    os._exit(0)


def main():
    # Set desktop mode so server skips auth
    os.environ["DESKTOP_MODE"] = "true"

    if os.environ.get("CLOSECALL_SIDECAR") == "1":
        threading.Thread(target=exit_when_stdin_closes, daemon=True).start()

    # Change to bundle dir so static files, scenarios and the template resolve
    os.chdir(get_bundle_dir())

    # Settings: the .env.example template, then the user's .env on top
    import desktop_env
    desktop_env.load()
    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        logger.info("No API key yet — the app shows the setup page")

    port = int(os.environ.get("PORT", "7860"))

    # Import app after env is loaded and cwd is set
    from server import app

    logger.info("Starting Close Call server on port %d ...", port)
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
