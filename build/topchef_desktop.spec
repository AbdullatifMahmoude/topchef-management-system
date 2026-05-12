# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller Spec — Top Chef Desktop POS
────────────────────────────────────────
Build command:
    cd build
    pyinstaller topchef_desktop.spec --clean
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

# Collect data/assets
datas = [
    # Desktop package files
    (os.path.join(PROJECT_ROOT, "desktop", "settings.json"), "desktop"),
    (os.path.join(PROJECT_ROOT, "desktop", "version.txt"), "desktop"),
    (os.path.join(PROJECT_ROOT, "desktop", "assets"), "desktop/assets"),
    # Include the ENTIRE app folder (frontend, core, modules, etc.)
    (os.path.join(PROJECT_ROOT, "app"), "app"),
]

# Hidden imports that PyInstaller misses
hiddenimports = [
    "uvicorn",
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
    "uvicorn.lifespan.off",
    "fastapi",
    "pydantic",
    "pydantic_settings",
    "starlette",
    "starlette.routing",
    "starlette.middleware",
    "starlette.middleware.cors",
    "sqlalchemy",
    "sqlite3",
    "webview",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "escpos",
    "escpos.printer",
    "win32print",
    "win32ui",
    "win32api",
    "qrcode",
    "arabic_reshaper",
    "bidi.algorithm",
    "desktop",
    "desktop.config",
    "desktop.logger",
    "desktop.updater",
    "desktop.printer",
    "desktop.tray",
    "desktop.splash",
    "app.core.enums",
    "app.main",
    "aiosqlite",
    "greenlet",
    "passlib.handlers.bcrypt",
    "redis",
    "redis.asyncio",
    "bcrypt",
    "cryptography",
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "desktop", "launcher.py")],
    pathex=[PROJECT_ROOT],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "matplotlib",
        "scipy",
        "numpy",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TopChef",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                      # Enabled for debugging
    disable_windowed_traceback=False,
    icon=os.path.join(PROJECT_ROOT, "desktop", "assets", "icon.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="TopChef",
)
