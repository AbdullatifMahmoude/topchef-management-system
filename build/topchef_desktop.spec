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

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(SPECPATH), ".."))

# Collect data/assets
datas = [
    # Desktop package files
    (os.path.join(PROJECT_ROOT, "desktop", "settings.json"), "desktop"),
    (os.path.join(PROJECT_ROOT, "desktop", "version.txt"), "desktop"),
    (os.path.join(PROJECT_ROOT, "desktop", "assets"), os.path.join("desktop", "assets")),
    # App core (needed for enums, schemas reuse)
    (os.path.join(PROJECT_ROOT, "app", "core", "enums.py"), os.path.join("app", "core")),
    (os.path.join(PROJECT_ROOT, "app", "core", "__init__.py"), os.path.join("app", "core")),
    # Desktop update module version metadata (if server runs locally for dev)
    (os.path.join(PROJECT_ROOT, "app", "modules", "desktop_updates", "version_meta.json"),
     os.path.join("app", "modules", "desktop_updates")),
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
    "desktop",
    "desktop.config",
    "desktop.logger",
    "desktop.local_db",
    "desktop.sync",
    "desktop.updater",
    "desktop.printer",
    "desktop.tray",
    "desktop.splash",
    "desktop.main",
    "app.core.enums",
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
        "asyncpg",        # PostgreSQL driver — not needed for desktop
        "psycopg2",
        "redis",
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
    console=False,                      # No console window
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
