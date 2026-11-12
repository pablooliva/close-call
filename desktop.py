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

import faulthandler
import logging
import os
import sys
import threading
import time

# One OpenBLAS thread: on a Windows PC, loading numpy hung forever while
# OpenBLAS started its thread pool. We only touch small audio buffers, so
# multithreaded maths gains nothing. Must be set before numpy is imported.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STALL_DUMP_SECONDS = 20


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
    started = time.monotonic()
    logger.info("Server process started (Python %s, %s)", sys.version.split()[0], sys.platform)

    # Startup diagnostics: if loading the app stalls (seen on a Windows PC),
    # write every thread's stack to the log every 20 s until it finishes, and
    # dump the stack on a native crash. Electron sends stderr to server.log.
    faulthandler.enable(file=sys.stderr)
    faulthandler.dump_traceback_later(STALL_DUMP_SECONDS, repeat=True, file=sys.stderr)

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
    logger.info("Loading app ...")
    from server import app
    faulthandler.cancel_dump_traceback_later()
    logger.info("App loaded in %.1fs", time.monotonic() - started)

    logger.info("Starting Close Call server on port %d ...", port)
    uvicorn.run(app, host="127.0.0.1", port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
