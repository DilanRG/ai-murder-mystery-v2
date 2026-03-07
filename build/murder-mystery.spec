# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for AI Murder Mystery v2.
Bundles the backend + pre-built static frontend into a single executable.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / 'backend'
STATIC = BACKEND / 'static'
CHARACTERS = BACKEND / 'characters'

block_cipher = None

a = Analysis(
    [str(BACKEND / 'launcher.py')],
    pathex=[str(BACKEND)],
    binaries=[],
    datas=[
        (str(STATIC), 'static'),
        (str(CHARACTERS), 'characters'),
        (str(BACKEND / 'config'), 'config'),
        (str(BACKEND / 'routers'), 'routers'),
    ],
    hiddenimports=[
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'starlette',
        'starlette.routing',
        'starlette.middleware',
        'starlette.responses',
        'starlette.staticfiles',
        'starlette.websockets',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        'httpcore',
        'anyio',
        'anyio._backends',
        'anyio._backends._asyncio',
        'pydantic',
        'main',
        'config.settings',
        'config.user_settings',
        'llm.client',
        'llm.prompt_builder',
        'story.characters',
        'story.generator',
        'story.models',
        'story.partitioner',
        'world.state',
        'world.event_bus',
        'world.clock',
        'agents.base',
        'agents.manager',
        'agents.memory',
        'agents.perception',
        'agents.tools',
        'routers._deps',
        'routers.game',
        'routers.ws',
        'routers.settings',
        'aiofiles',
        'aiofiles.os',
        'aiofiles.ospath',
        'email.mime.multipart',
        'email.mime.text',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'PIL',
        'IPython',
        'jupyter',
        'pytest',
        'setuptools',
        'pkg_resources',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ai-murder-mystery',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / 'build' / 'icon.ico'),
)
