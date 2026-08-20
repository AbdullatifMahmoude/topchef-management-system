# -*- mode: python ; coding: utf-8 -*-
import os

PROJECT_ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(PROJECT_ROOT, "print_agent", "settings.json"), "print_agent"),
    (os.path.join(PROJECT_ROOT, "print_agent", "assets"), "print_agent/assets"),
]

hiddenimports = [
    "uvicorn", "uvicorn.logging", "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto", "uvicorn.lifespan.on",
    "fastapi", "pydantic", "starlette", "PIL", "PIL.ImageWin",
    "win32print", "win32ui", "qrcode", "arabic_reshaper", "bidi.algorithm",
]

a = Analysis(
    [os.path.join(PROJECT_ROOT, "print_agent", "service.py")],
    pathex=[PROJECT_ROOT], binaries=[], datas=datas, hiddenimports=hiddenimports,
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["pytest", "matplotlib", "scipy", "numpy", "sqlalchemy", "webview"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True, name="TopChefPrintAgent",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False,
    icon=os.path.join(PROJECT_ROOT, "print_agent", "assets", "icon.ico"),
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True,
               upx_exclude=[], name="TopChefPrintAgent")
