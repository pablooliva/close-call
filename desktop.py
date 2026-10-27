"""Headless server entry point for the Close Call desktop app (the "sidecar").

The Electron shell (electron/main.js) starts this process, waits until it
answers on 127.0.0.1:$PORT and shows the frontend in its own window.

Auth is bypassed via DESKTOP_MODE.

Environment set by Electron:
    PORT                  Free localhost port chosen by Electron.
    CLOSECALL_ENV_FILE    Optional .env in the user's app-data folder; overrides
                          the .env bundled at build time (CI builds bundle none).
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

    # Load .env: bundled inside the app first, then the user's file (override)
    from dotenv import load_dotenv
    bundle_dir = get_bundle_dir()

    bundled_env = os.path.join(bundle_dir, ".env")
    if os.path.exists(bundled_env):
        load_dotenv(bundled_env, override=True)

    user_env = os.environ.get("CLOSECALL_ENV_FILE", "")
    if user_env and os.path.exists(user_env):
        load_dotenv(user_env, override=True)

    if not os.environ.get("AZURE_OPENAI_API_KEY"):
        logger.error("AZURE_OPENAI_API_KEY is not set — calls will fail. Expected .env at %s", user_env or bundled_env)

    if os.environ.get("CLOSECALL_SIDECAR") == "1":
        threading.Thread(target=exit_when_stdin_closes, daemon=True).start()

    # Change to bundle dir so static file and scenario paths resolve correctly
    os.chdir(bundle_dir)

    port = int(os.environ.get("PORT", "7860"))

    # Import app after env is loaded and cwd is set
    from server import app

    logger.info("Starting Close Call server on port %d ...", port)
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
