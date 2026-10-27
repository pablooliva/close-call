---
adr: 0001
title: Package the desktop app as an Electron shell with a Python sidecar
status: Accepted
date: 2026-10-27
supersedes: null
superseded_by: null
tags: [cross-cutting, distribution, desktop]
---

# ADR 0001: Package the desktop app as an Electron shell with a Python sidecar

## Status

Accepted (2026-10-27)

## Context

Close Call must be installable by Memodo salespeople on both Windows and macOS. Until now it shipped only as a macOS app: PyInstaller bundles the FastAPI + Pipecat server (`desktop.py`), a small tkinter window keeps the process alive, and the user's default browser opens `static/index.html`. There is no Windows build, and the call quality depends on whichever browser each user has set as default — a real risk for an app whose core is live WebRTC audio.

The server cannot simply be rewritten in another language: Pipecat's pipeline (turn detection, interruptions, context aggregation, recording) exists only in Python. Its JavaScript libraries are clients that connect to a Python server.

The choice binds every future release, the build tooling, CI, and how secrets reach users' machines, so it is recorded here rather than in a feature spec. See also `SDD/research/RESEARCH-003-model-provider-alternatives.md` (Azure OpenAI as the model provider).

## Decision

Ship Close Call as an **Electron** desktop app for Windows and macOS:

- The existing Python server is built with PyInstaller into a headless executable (the "sidecar"). No Python code is ported.
- A small Electron main process (plain JavaScript, no build step, matching the vanilla-JS frontend) picks a free localhost port, starts the sidecar, waits until it answers, and loads the existing frontend in its own window. Quitting the app stops the sidecar.
- `electron-builder` produces the macOS DMG and the Windows installer from one configuration. This replaces `create_dmg.sh`, the tkinter status window and the system-browser hand-off.
- Platform builds run on native runners (macOS and Windows), because PyInstaller cannot cross-compile.

## Alternatives Considered

### Electron shell + Python sidecar (chosen)

Electron bundles its own Chromium, so WebRTC and microphone handling behave identically on every machine. One `electron-builder` configuration yields both installers and enables auto-update later. The Python code stays unchanged.

### Keep PyInstaller + tkinter + default browser, add a Windows build

Rejected because: call quality would still depend on each user's default browser, and the tkinter status window plus a separate browser tab is a poor installed-app experience. It would have been the smallest change.

### pywebview (Python-only, system web engine)

Rejected because: on macOS it embeds WebKit (Safari's engine), where microphone access and WebRTC inside an embedded window need extra permission handling and are less predictable than Chromium. Smallest download and no Node toolchain, but the riskiest option for live audio.

### Tauri (Rust shell, system web engine)

Rejected because: same WebKit-on-macOS risk as pywebview, plus a Rust toolchain. Much smaller downloads than Electron.

### Full TypeScript port (drop Pipecat)

Rejected because: Pipecat's server side is Python-only, so a port means rebuilding turn detection, interruption handling, context management and recording on top of the raw realtime API. Large effort and risk with no user-facing gain.

### Centrally hosted web app (optionally installable as a PWA) on Azure

Rejected for now by the project owner in favour of installable desktop distribution. This option had the strongest technical benefits: the Azure key stays on the server, updates reach everyone instantly, and no signing is needed. It would require HTTPS, real authentication (e.g. Entra ID), a firewall-proof audio transport (TURN or WebSocket), and a data-protection and works-council review for centrally stored call recordings. Revisit if key exposure, update friction or signing costs become a problem.

## Consequences

### Positive

- Identical audio and microphone behaviour on Windows and macOS (bundled Chromium).
- Proper installed-app experience: own window and icon, standard installers for both platforms.
- Auto-update becomes possible via `electron-updater` (on macOS only once the app is signed).
- No rewrite: the Python/Pipecat server is reused as-is.

### Negative / Trade-offs accepted

- **The Azure API key remains on every installed machine** and can be extracted from the app. Because the repository is public, CI-built installers must not contain the key; it has to reach users through a separate channel.
- **Code signing is needed** to avoid macOS Gatekeeper and Windows SmartScreen warnings (and outright blocking on managed Windows laptops), and for macOS auto-update. This means an Apple Developer account and a Windows signing service, both paid.
- **A second toolchain** (Node.js, npm, Electron and its security-update cadence) is maintained alongside Python and uv.
- **Larger downloads:** Chromium adds roughly 100 MB or more on top of the ~460 MB Python bundle.
- Every platform must be built on that platform; releases depend on CI with macOS and Windows runners.

### Neutral observations

- The frontend keeps talking to `http://127.0.0.1:<port>`, so the server code and WebRTC transport do not change.
- Moving to hosting later stays possible: the frontend and server are unchanged, only the packaging layer would be dropped.

## References

- `SDD/research/RESEARCH-003-model-provider-alternatives.md`
- Electron: https://www.electronjs.org/
- electron-builder: https://www.electron.build/
- Pipecat: https://github.com/pipecat-ai/pipecat
