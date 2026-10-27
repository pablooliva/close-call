"""Build the Close Call server sidecar with PyInstaller.

Usage:
    uv run python build_desktop.py

This produces a single-folder distribution in dist/closecall-server/ that the
Electron app (electron/) bundles and starts. Must be run on each target
platform: PyInstaller cannot cross-compile.

A local .env is bundled when present (handy for builds you hand out yourself).
CI builds have none: the repo is public, so its installers must not contain the
Azure key; users put their .env in the app-data folder instead.
"""

import os

import PyInstaller.__main__

# Console app (not --windowed): Electron hides the window and needs stdin.
env_data = ["--add-data=.env:."] if os.path.exists(".env") else []

PyInstaller.__main__.run([
    "desktop.py",
    "--name=closecall-server",
    "--noconfirm",                   # Overwrite previous build without asking
    # Bundle data directories
    "--add-data=static:static",
    "--add-data=scenarios:scenarios",
    *env_data,
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
    "--collect-submodules=pipecat.services.azure",
    "--collect-submodules=pipecat.services.openai",
    "--collect-submodules=pipecat.adapters",
    "--collect-submodules=pipecat.workers",
    "--collect-submodules=pipecat.transcriptions",
    "--collect-submodules=pipecat.transports",
    "--collect-submodules=pipecat.audio",
    "--collect-submodules=pipecat.serializers",
    "--collect-submodules=pipecat.metrics",
    "--collect-submodules=pipecat.clocks",
    "--collect-submodules=pipecat.utils",
    "--collect-submodules=openai",
    # Ensure certifi's CA bundle is included
    "--collect-data=certifi",
    # Pipecat data files (ONNX model for smart turn detection, etc.)
    "--collect-data=pipecat",
    # Package metadata needed at runtime (importlib.metadata.version() calls)
    "--copy-metadata=pipecat-ai",
    "--copy-metadata=openai",
    "--copy-metadata=fastapi",
    "--copy-metadata=uvicorn",
])
