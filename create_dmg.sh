#!/usr/bin/env bash
set -euo pipefail

APP_PATH="dist/CloseCall.app"
DMG_PATH="dist/CloseCall.dmg"

if [ ! -d "$APP_PATH" ]; then
    echo "Error: $APP_PATH not found. Run 'uv run python build_desktop.py' first."
    exit 1
fi

echo "Creating DMG from $APP_PATH..."
hdiutil create -volname "CloseCall" -srcfolder "$APP_PATH" -ov -format UDZO "$DMG_PATH"
echo "Done: $DMG_PATH"
