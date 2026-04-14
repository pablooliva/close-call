"""FastAPI server for Close Call voice agent.

Serves the static frontend, handles WebRTC signaling via SmallWebRTCRequestHandler,
provides scenario list and feedback polling endpoints.

Run with: python server.py
"""

# Fix SSL: if a TLS-intercepting proxy (e.g. Socket Firewall) sets SSL_CERT_FILE
# to its own CA, the Google genai SDK loses access to public root CAs. Merge both
# bundles so the proxy CA and real CAs are both trusted.
import os
import tempfile

import certifi

_proxy_cert = os.environ.get("SSL_CERT_FILE", "")
if _proxy_cert and os.path.isfile(_proxy_cert) and _proxy_cert != certifi.where():
    with open(certifi.where()) as _base, open(_proxy_cert) as _extra:
        _combined = _base.read() + "\n" + _extra.read()
    _combined_fd, _combined_path = tempfile.mkstemp(suffix=".pem", prefix="combined-ca-")
    with os.fdopen(_combined_fd, "w") as _f:
        _f.write(_combined)
    os.environ["SSL_CERT_FILE"] = _combined_path
elif not _proxy_cert:
    os.environ["SSL_CERT_FILE"] = certifi.where()

import logging
import secrets
import time

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Cookie, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipecat.transports.smallwebrtc.request_handler import (
    SmallWebRTCPatchRequest,
    SmallWebRTCRequest,
    SmallWebRTCRequestHandler,
)

from bot import run_bot
from scenarios import SCENARIOS, get_scenario_list

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Desktop mode: skip auth when running as packaged desktop app
DESKTOP_MODE = os.environ.get("DESKTOP_MODE", "").lower() == "true"

# Auth credentials from .env
AUTH_USERNAME = os.environ.get("USERNAME", "")
AUTH_PASSWORD = os.environ.get("PASSWORD", "")

# Session secret — generated once per server start
SESSION_SECRET = secrets.token_hex(32)

# Active sessions: token -> expiry timestamp
sessions: dict[str, float] = {}
SESSION_TTL = 8 * 3600  # 8 hours


class LoginRequest(BaseModel):
    username: str
    password: str


def create_session_token() -> str:
    """Create a signed session token and store it."""
    token = secrets.token_urlsafe(32)
    sessions[token] = time.time() + SESSION_TTL
    return token


def is_authenticated(session: str | None) -> bool:
    """Check if a session token is valid. Always True in desktop mode."""
    if DESKTOP_MODE:
        return True
    if not session or session not in sessions:
        return False
    if time.time() > sessions[session]:
        del sessions[session]
        return False
    return True


app = FastAPI(title="Close Call", version="0.1.0")

# Single-worker shared state (REQ-007, SEC-002)
feedback_store: dict[str, dict | None] = {}

# Feedback TTL in seconds (SEC-002: 5 minutes)
FEEDBACK_TTL = 300

# WebRTC signaling handler
handler = SmallWebRTCRequestHandler()


def cleanup_expired_feedback():
    """Remove feedback entries older than FEEDBACK_TTL. Called on each request."""
    now = time.time()
    expired = [
        pc_id for pc_id, entry in feedback_store.items()
        if entry and entry.get("created_at") and (now - entry["created_at"]) > FEEDBACK_TTL
    ]
    for pc_id in expired:
        del feedback_store[pc_id]
        logger.info("Cleaned up expired feedback for pc_id=%s", pc_id)


# --- Auth Endpoints ---

@app.post("/api/login")
async def login(body: LoginRequest):
    """Authenticate with username/password from .env."""
    if not AUTH_USERNAME or not AUTH_PASSWORD:
        raise HTTPException(status_code=500, detail="Server authentication not configured.")
    if body.username == AUTH_USERNAME and body.password == AUTH_PASSWORD:
        token = create_session_token()
        response = JSONResponse(content={"ok": True})
        response.set_cookie(
            key="session",
            value=token,
            httponly=True,
            samesite="strict",
            max_age=SESSION_TTL,
        )
        return response
    raise HTTPException(status_code=401, detail="Ungültige Anmeldedaten.")


@app.post("/api/logout")
async def logout(session: str | None = Cookie(default=None)):
    """Clear session."""
    if session and session in sessions:
        del sessions[session]
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session")
    return response


# --- API Endpoints ---

@app.get("/api/scenarios")
async def scenarios(session: str | None = Cookie(default=None)):
    """REQ-012: Return scenario list without system prompts."""
    if not is_authenticated(session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return get_scenario_list()


@app.post("/api/offer")
async def offer(request: SmallWebRTCRequest, background_tasks: BackgroundTasks, session: str | None = Cookie(default=None)):
    """REQ-010: SDP exchange and bot spawn.

    Validates scenario_id from request_data, performs WebRTC signaling,
    and starts the bot pipeline as a background task.
    """
    if not is_authenticated(session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    cleanup_expired_feedback()

    # SEC-003: Validate scenario ID
    scenario_id = (request.request_data or {}).get("scenario", "")
    if scenario_id not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario: {scenario_id!r}. Valid: {list(SCENARIOS.keys())}",
        )

    async def webrtc_connection_callback(connection):
        background_tasks.add_task(run_bot, connection, scenario_id, feedback_store)

    answer = await handler.handle_web_request(
        request=request,
        webrtc_connection_callback=webrtc_connection_callback,
    )
    return answer


@app.patch("/api/offer")
async def ice_candidate(request: SmallWebRTCPatchRequest):
    """REQ-010: ICE trickle candidates."""
    # Filter out empty end-of-candidates signals that crash candidate_from_sdp
    if request.candidates:
        request.candidates = [
            c for c in request.candidates if c.candidate and c.candidate.strip()
        ]
    await handler.handle_patch_request(request)


@app.get("/api/feedback/{pc_id}")
async def get_feedback(pc_id: str, session: str | None = Cookie(default=None)):
    """REQ-008: Feedback polling endpoint.

    Returns:
        200 with feedback markdown when ready
        202 when still pending
        404 when pc_id not found
        500 when generation failed
    """
    if not is_authenticated(session):
        raise HTTPException(status_code=401, detail="Not authenticated")
    cleanup_expired_feedback()

    if pc_id not in feedback_store:
        raise HTTPException(status_code=404, detail="No feedback found for this call.")

    entry = feedback_store[pc_id]
    if entry is None or entry.get("status") == "pending":
        return JSONResponse(
            status_code=202,
            content={"status": "pending", "message": "Feedback wird generiert..."},
        )

    if entry.get("status") == "error":
        # SEC-002: Remove on retrieval
        feedback_text = entry.get("feedback", "Feedback konnte nicht generiert werden.")
        del feedback_store[pc_id]
        return JSONResponse(
            status_code=500,
            content={"status": "error", "feedback": feedback_text},
        )

    # status == "ready"
    feedback_text = entry.get("feedback", "")
    # SEC-002: Remove on retrieval
    del feedback_store[pc_id]
    return JSONResponse(
        status_code=200,
        content={"status": "ready", "feedback": feedback_text},
    )


# --- Static Files & Pages ---

# Mount static directory for any additional assets
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/login")
async def login_page(session: str | None = Cookie(default=None)):
    """Serve login page, or redirect to landing if already authenticated."""
    if is_authenticated(session):
        return RedirectResponse(url="/")
    return FileResponse("static/login.html")


@app.get("/")
async def index(session: str | None = Cookie(default=None)):
    """Serve landing page (requires auth)."""
    if not is_authenticated(session):
        return RedirectResponse(url="/login")
    return FileResponse("static/landing.html")


@app.get("/call")
async def call_page(session: str | None = Cookie(default=None)):
    """Serve the call/scenario selection page (requires auth)."""
    if not is_authenticated(session):
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")


# --- Entry Point ---

def main():
    """Entry point for `uv run close-call` and `python server.py`."""
    import uvicorn

    port = int(os.getenv("PORT", "7860"))
    logger.info("Starting Close Call on port %d", port)
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=port,
        workers=1,  # Single worker required for feedback_store
    )


if __name__ == "__main__":
    main()
