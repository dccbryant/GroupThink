#!/usr/bin/env bash
# Build GroupThink.app on macOS.
#
# Usage:
#   bash packaging/build_macos.sh
#
# Output: dist/GroupThink.app  (drag into /Applications and double-click)
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$PWD"

# ---------------------------------------------------------------------- #
# 0. Sanity checks
# ---------------------------------------------------------------------- #
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "✗ This builder only runs on macOS (uname=$(uname -s))." >&2
  exit 1
fi

if ! command -v python3 >/dev/null; then
  echo "✗ Python 3 is required. Install it via Homebrew: brew install python" >&2
  exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "→ Using Python $PY_VERSION"

# ---------------------------------------------------------------------- #
# 1. Build venv (kept across builds for speed)
# ---------------------------------------------------------------------- #
if [[ ! -d build-venv ]]; then
  echo "→ Creating build virtualenv (build-venv/)…"
  python3 -m venv build-venv
fi
# shellcheck disable=SC1091
source build-venv/bin/activate
python -m pip install --quiet --upgrade pip setuptools wheel
echo "→ Installing runtime dependencies…"
pip install --quiet -r requirements.txt
echo "→ Installing desktop build dependencies…"
pip install --quiet -r requirements-desktop.txt

# ---------------------------------------------------------------------- #
# 2. Stage ffmpeg / ffprobe under packaging/vendor/bin/
# ---------------------------------------------------------------------- #
VENDOR="packaging/vendor/bin"
mkdir -p "$VENDOR"

stage_bin() {
  local bin="$1"
  if [[ -x "$VENDOR/$bin" ]]; then
    return 0
  fi
  for src in "/opt/homebrew/bin/$bin" "/usr/local/bin/$bin" "$(command -v "$bin" 2>/dev/null || true)"; do
    if [[ -n "$src" && -x "$src" ]]; then
      cp "$src" "$VENDOR/$bin"
      chmod +x "$VENDOR/$bin"
      echo "  ✓ staged $bin from $src"
      return 0
    fi
  done
  echo "  ⚠ $bin not found. Install with 'brew install ffmpeg' or drop a static" >&2
  echo "    build at $VENDOR/$bin and re-run this script." >&2
  return 1
}

echo "→ Staging ffmpeg / ffprobe under $VENDOR/…"
stage_bin ffmpeg
stage_bin ffprobe

# ---------------------------------------------------------------------- #
# 3. Build the .app with PyInstaller
# ---------------------------------------------------------------------- #
echo "→ Cleaning previous build artifacts…"
rm -rf build dist

echo "→ Running PyInstaller…"
pyinstaller --noconfirm packaging/GroupThink.spec

# ---------------------------------------------------------------------- #
# 4. Result
# ---------------------------------------------------------------------- #
APP="dist/GroupThink.app"
if [[ -d "$APP" ]]; then
  SIZE=$(du -sh "$APP" | cut -f1)
  echo
  echo "✓ Built $APP  ($SIZE)"
  echo "  Drag it to /Applications and double-click to launch."
  echo "  First launch on macOS Gatekeeper: right-click → Open → Open."
else
  echo "✗ Build did not produce $APP — check the PyInstaller output above." >&2
  exit 1
fi
