# PyInstaller spec for the GroupThink macOS desktop app.
# Build with: bash packaging/build_macos.sh

from pathlib import Path

# SPECPATH is provided by PyInstaller and points at this file's directory.
ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH injected by PyInstaller
APP_PKG = ROOT / "groupthink"

# Data files that need to be packaged inside the .app and reachable at runtime.
# The destination path is RELATIVE to the bundle root (PyInstaller's _MEIPASS).
datas = [
    (str(APP_PKG / "web" / "static"), "groupthink/web/static"),
    (str(APP_PKG / "assets"), "groupthink/assets"),
]

# Bundle ffmpeg / ffprobe under vendor/bin/ if the build script staged them
# there. groupthink.runtime.find_binary() looks at exactly this path inside
# the frozen bundle.
binaries = []
vendor_bin = ROOT / "packaging" / "vendor" / "bin"
for name in ("ffmpeg", "ffprobe"):
    src = vendor_bin / name
    if src.exists():
        binaries.append((str(src), "vendor/bin"))

# Imports PyInstaller's static analysis can miss (uvicorn loads these lazily).
hidden_imports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "anthropic",
    "assemblyai",
    "docx",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL.ImageFont",
]

block_cipher = None

a = Analysis(  # noqa: F821 — provided by PyInstaller
    [str(APP_PKG / "desktop.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],  # not used and bloats the bundle
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GroupThink",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    target_arch=None,
)
coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="GroupThink",
)

# The .app bundle that ends up in dist/GroupThink.app.
icon = ROOT / "packaging" / "icon.icns"
app = BUNDLE(  # noqa: F821
    coll,
    name="GroupThink.app",
    icon=str(icon) if icon.exists() else None,
    bundle_identifier="com.specialforcesny.groupthink",
    info_plist={
        "CFBundleDisplayName": "GroupThink",
        "CFBundleShortVersionString": "0.1.0",
        "CFBundleVersion": "0.1.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        # Quietly tell macOS this app doesn't need media access, so it never
        # silently prompts on launch from inside the WebKit window.
        "NSCameraUsageDescription": "GroupThink does not use the camera.",
        "NSMicrophoneUsageDescription": "GroupThink does not use the microphone.",
        # The app talks to its own localhost server.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    },
)
