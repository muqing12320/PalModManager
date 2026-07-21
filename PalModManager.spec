# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path

block_cipher = None

# 项目根目录
PROJECT_ROOT = Path(SPECPATH)

# 把 certifi 的 CA 证书包一起打包，使 requests 在冻结环境能做正规 HTTPS 校验
try:
    import certifi
    _cacert = certifi.where()
except Exception:
    _cacert = None

a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=[
        # 打包资源文件（如果有的话）
        ('resources', 'resources'),
        # CA 证书包（requests 校验用），放到冻结根目录下的 cacert.pem
        *([(_cacert, 'cacert.pem')] if _cacert else []),
    ],
    hiddenimports=[
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.QtWidgets',
        'PyQt5.sip',
        'yaml',
        'toml',
        'json',
        'hashlib',
        'shutil',
        'zipfile',
        'tempfile',
        're',
        'struct',
        'subprocess',
        'platform',
        'collections',
        'dataclasses',
        'enum',
        'typing',
        'pathlib',
        'datetime',
        'py7zr',
        'py7zr.py7zr',
        'py7zr.archive',
        'py7zr.compressor',
        'py7zr.crypto',
        'py7zr.helpers',
        'py7zr.lzma',
        'urllib',
        'urllib.request',
        'urllib.error',
        'requests',
        'requests.adapters',
        'requests.sessions',
        'urllib3',
        'urllib3.util.retry',
        'charset_normalizer',
        'tempfile',
        'ssl',
        '_ssl',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'pandas',
        'jedi',
        'IPython',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PalModManager',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='resources/app_icon.ico',
)
