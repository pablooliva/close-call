"""Build script for creating a standalone Close Call desktop app with PyInstaller.

Usage:
    uv run python build_desktop.py

This produces a single-folder distribution in dist/CloseCall/ containing
the executable plus all required data files.
"""

import PyInstaller.__main__
import sys

PyInstaller.__main__.run([
    "desktop.py",
    "--name=CloseCall",
    "--windowed",                    # Produce .app bundle on macOS, no console window
    "--noconfirm",                   # Overwrite previous build without asking
    # Bundle data directories
    "--add-data=static:static",
    "--add-data=scenarios:scenarios",
    "--add-data=.env:.",
    # Hidden imports that PyInstaller may miss
    "--hidden-import=uvicorn.logging",
    "--hidden-import=uvicorn.loops",
    "--hidden-import=uvicorn.loops.auto",
    "--hidden-import=uvicorn.protocols",
    "--hidden-import=uvicorn.protocols.http",
    "--hidden-import=uvicorn.protocols.http.auto",
    "--hidden-import=uvicorn.protocols.websockets",
    "--hidden-import=uvicorn.protocols.websockets.auto",
    "--hidden-import=uvicorn.lifespan",
    "--hidden-import=uvicorn.lifespan.on",
    "--hidden-import=uvicorn.lifespan.off",
    "--hidden-import=server",
    "--hidden-import=bot",
    "--hidden-import=scenarios",
    "--hidden-import=feedback",
    "--hidden-import=certifi",
    "--hidden-import=dotenv",
    # Collect only the pipecat submodules we actually use (not all 50+ services)
    "--collect-submodules=pipecat.pipeline",
    "--collect-submodules=pipecat.frames",
    "--collect-submodules=pipecat.processors",
    "--collect-submodules=pipecat.services.google",
    "--collect-submodules=pipecat.transcriptions",
    "--collect-submodules=pipecat.transports",
    "--collect-submodules=pipecat.audio",
    "--collect-submodules=pipecat.serializers",
    "--collect-submodules=pipecat.metrics",
    "--collect-submodules=pipecat.clocks",
    "--collect-submodules=pipecat.utils",
    "--collect-submodules=google.generativeai",
    "--collect-submodules=google.auth",
    "--collect-submodules=google.api_core",
    # Ensure certifi's CA bundle is included
    "--collect-data=certifi",
    # Package metadata needed at runtime (importlib.metadata.version() calls)
    "--copy-metadata=pipecat-ai",
    "--copy-metadata=google-generativeai",
    "--copy-metadata=fastapi",
    "--copy-metadata=uvicorn",
])
