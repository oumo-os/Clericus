#!/usr/bin/env bash
# build.sh — Build Clericus desktop distributable
#
# Usage:
#   ./build.sh              — build for current OS
#   ./build.sh --clean      — clean dist/ and build/  first
#   ./build.sh --skip-deps  — skip pip install step
#
# Output:
#   dist/Clericus/          — runnable app folder
#   dist/Clericus-linux.tar.gz   (Linux)
#   dist/Clericus-mac.zip        (macOS)
#   dist/Clericus-win.zip        (Windows, run in Git Bash or WSL)
#
# Requirements:
#   pip install pyinstaller pywebview uvicorn fastapi python-multipart
#   pip install -r requirements.txt

set -euo pipefail
cd "$(dirname "$0")"

CLEAN=0; SKIP_DEPS=0
for arg in "$@"; do
  [[ "$arg" == "--clean" ]]     && CLEAN=1
  [[ "$arg" == "--skip-deps" ]] && SKIP_DEPS=1
done

echo "=== Clericus Build ==="
echo "Platform: $(uname -s)"
echo "Python:   $(python3 --version)"

# ── Clean ──────────────────────────────────────────────────────────────────
if [[ $CLEAN -eq 1 ]]; then
  echo "Cleaning dist/ and build/…"
  rm -rf dist build
fi

# ── Dependencies ───────────────────────────────────────────────────────────
if [[ $SKIP_DEPS -eq 0 ]]; then
  echo "Installing dependencies…"
  pip install -q -r requirements.txt
  pip install -q -r requirements-gui.txt
  pip install -q pyinstaller pywebview
fi

# ── PyInstaller build ──────────────────────────────────────────────────────
echo "Running PyInstaller…"
pyinstaller clericus.spec --noconfirm

echo "Build complete: dist/Clericus/"

# ── Platform archive ───────────────────────────────────────────────────────
OS="$(uname -s | tr '[:upper:]' '[:lower:]')"
case "$OS" in
  linux*)
    ARCHIVE="dist/Clericus-linux.tar.gz"
    tar -czf "$ARCHIVE" -C dist Clericus
    echo "Archive: $ARCHIVE"
    ;;
  darwin*)
    ARCHIVE="dist/Clericus-mac.zip"
    cd dist && zip -r "../$ARCHIVE" Clericus && cd ..
    echo "Archive: $ARCHIVE"
    # Optional: create a .app bundle with create-dmg
    if command -v create-dmg &>/dev/null; then
      create-dmg \
        --volname "Clericus" \
        --window-size 540 380 \
        --icon-size 128 \
        --app-drop-link 380 205 \
        "dist/Clericus.dmg" \
        "dist/Clericus/"
      echo "DMG: dist/Clericus.dmg"
    else
      echo "Tip: install create-dmg for a proper .dmg installer"
    fi
    ;;
  msys*|cygwin*|mingw*)
    ARCHIVE="dist/Clericus-win.zip"
    cd dist && zip -r "../$ARCHIVE" Clericus && cd ..
    echo "Archive: $ARCHIVE"
    echo "Tip: use NSIS or Inno Setup for a proper Windows installer"
    ;;
esac

echo ""
echo "=== Done ==="
echo "To run directly: ./dist/Clericus/Clericus"
