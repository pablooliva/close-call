"""Start the built sidecar like the desktop app does and check that it answers.

Passes when a fresh install (no key, empty data folder) gets redirected to the
setup page within the timeout. Run in CI after build_desktop.py:

    uv run python scripts/smoke_test_sidecar.py dist/closecall-server
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

TIMEOUT_SECS = 180  # same as electron/main.js


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_setup_page(proc: subprocess.Popen, port: int) -> str | None:
    """Return None on success, else the reason for failure."""
    deadline = time.monotonic() + TIMEOUT_SECS
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return f"server exited with code {proc.returncode}"
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as res:
                page = res.read().decode("utf-8")
                if res.url.endswith("/setup") and 'id="setup-form"' in page:
                    return None
                return f"expected the setup page, got {res.url}"
        except OSError:
            time.sleep(0.5)  # not listening yet
    return f"no answer within {TIMEOUT_SECS}s"


def main() -> int:
    server_dir = os.path.abspath(sys.argv[1])
    exe = os.path.join(server_dir, "closecall-server.exe" if os.name == "nt" else "closecall-server")
    data_dir = tempfile.mkdtemp(prefix="closecall-smoke-")
    port = free_port()
    env = {
        **os.environ,
        "PORT": str(port),
        "CLOSECALL_DATA_DIR": data_dir,
        "CLOSECALL_ENV_FILE": os.path.join(data_dir, ".env"),
    }
    env.pop("AZURE_OPENAI_API_KEY", None)

    log_path = os.path.join(data_dir, "server.log")
    started = time.monotonic()
    with open(log_path, "wb") as log:
        proc = subprocess.Popen([exe], cwd=server_dir, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            failure = wait_for_setup_page(proc, port)
        finally:
            proc.terminate()
            proc.wait(timeout=30)
    elapsed = time.monotonic() - started

    with open(log_path, encoding="utf-8", errors="replace") as f:
        print(f.read())
    if failure:
        print(f"FAIL after {elapsed:.1f}s: {failure}")
        return 1
    print(f"OK: server answered with the setup page after {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
