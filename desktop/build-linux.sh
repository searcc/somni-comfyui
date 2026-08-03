#!/usr/bin/env bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "============================================================"
echo "  somni desktop — building linux appimage"
echo "============================================================"
echo

# Get the directory where the script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/somni-app"

# Ensure dependencies are installed
if [ ! -d "node_modules" ]; then
    echo "node_modules not found. Running npm install..."
    npm install
fi

echo "Building somni-app (Linux AppImage)..."

# USE_HARD_LINKS=false helps prevent symlink issues across Linux filesystems
export USE_HARD_LINKS=false

# Run electron-builder for Linux targets
npx electron-builder --linux AppImage

echo
echo "============================================================"
echo "  Done!"
echo
echo "  Linux AppImage: $SCRIPT_DIR/dist/somni-app/*.AppImage"
echo "============================================================"
echo