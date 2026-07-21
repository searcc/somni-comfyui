#!/bin/bash
# somni installer - Linux launcher

set -e

# Find Python 3
PYEXE=""

# Try python3 first
if command -v python3 &> /dev/null; then
    PYEXE="python3"
elif command -v python &> /dev/null; then
    # Check if 'python' is Python 3
    if python --version 2>&1 | grep -q "Python 3"; then
        PYEXE="python"
    fi
fi

if [ -z "$PYEXE" ]; then
    echo "-------------------------------------------------------------"
    echo "  No working Python 3 was found on this system."
    echo ""
    echo "  somni's installer needs any Python 3.x to run."
    echo ""
    echo "  Install Python 3 from your package manager:"
    echo "    Ubuntu/Debian: sudo apt install python3"
    echo "    Fedora:        sudo dnf install python3"
    echo "    Arch:          sudo pacman -S python"
    echo ""
    echo "  Or download from: https://www.python.org/downloads/"
    echo "-------------------------------------------------------------"
    echo ""
    exit 1
fi

echo "  Using Python: $PYEXE"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the installer
"$PYEXE" "$SCRIPT_DIR/installer.py"
RC=$?

echo ""
if [ "$RC" -eq 0 ]; then
    echo "  Installer exited normally."
else
    echo "  Installer exited with code $RC."
    echo "  If you see an error above, copy it for support."
fi
echo ""

exit $RC
