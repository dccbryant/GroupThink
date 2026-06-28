# Packaging — macOS desktop app

This produces a double-clickable **`GroupThink.app`** that bundles Python,
ffmpeg, fonts, and the web UI into one self-contained Mac application. The
video never leaves the user's machine.

## Build it

On a Mac with Homebrew + Python 3 installed:

```bash
brew install ffmpeg python      # if you don't already have them
cd ~/Desktop/groupthink
bash packaging/build_macos.sh
```

That's it. Output lands at **`dist/GroupThink.app`** (~80–120 MB). Drag it
into `/Applications`.

Under the hood the script:

1. Sets up a build virtualenv (`build-venv/`).
2. Installs runtime + desktop requirements (`pywebview`, `pyinstaller`).
3. Stages `ffmpeg` and `ffprobe` from Homebrew into `packaging/vendor/bin/`.
4. Runs PyInstaller against `packaging/GroupThink.spec`.

## Run the .app

Double-click `GroupThink.app`. A native window opens running the GroupThink
UI; uvicorn runs in the background on a free localhost port.

**First-launch Gatekeeper warning.** Until the app is signed and notarized
(planned for a later release), macOS will warn that it's from an
"unidentified developer." Bypass that *once*: right-click the app →
**Open** → **Open**. After that, double-click works normally.

## What's bundled

- All Python deps from `requirements.txt`
- The web UI (`groupthink/web/static/`)
- The DejaVu Sans font used for title cards
- `ffmpeg` and `ffprobe` (staged from your Homebrew install)
- A reasonable `Info.plist` (display name, version, "no camera/mic needed")

## What lives outside the bundle

- **Per-user data** — projects, transcripts, rendered MP4s — go to
  `~/Library/Application Support/GroupThink/workspace/`.
- **Saved API keys** stay at `~/.groupthink/keys.json` (chmod 600, just like
  in the source version).
- Originals and Drive folders the user analyzes are read in place and never
  copied or uploaded.

## Iterating

After a first build, repeat builds are fast (PyInstaller caches; the venv
is reused). To force a fully clean build:

```bash
rm -rf build dist build-venv packaging/vendor
bash packaging/build_macos.sh
```

## Known gaps for v1

- **Not code-signed or notarized.** Users need the right-click → Open dance
  on first launch. Fixing this requires an Apple Developer account
  ($99/year) and a small signing step in the build script.
- **Mac-only.** Windows is a future build.
- **No auto-update.** Future versions will use Sparkle.
- **Single architecture.** The .app matches the host CPU (Apple Silicon or
  Intel). A universal build is post-v1.
- **ffmpeg is LGPL** — fine for private use. For wider distribution, swap
  in an LGPL-compliant static build (e.g. evermeet.cx).
