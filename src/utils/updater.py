"""Auto-update checker for the application.

Uses a lightweight HTTP approach — no SSL verification (acceptable for
GitHub raw URLs).  Supports download progress reporting.
"""

import json
import urllib.request
import urllib.error
import ssl
import tempfile
import os
import sys
from pathlib import Path
from typing import Optional, Callable


CURRENT_VERSION = "1.0.0"
UPDATE_URL = "https://raw.githubusercontent.com/muqing12320/PalModManager/main/version.json"


def _make_ssl_context():
    """Create an SSL context that works around PyInstaller limitations."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def check_for_update(url: str = UPDATE_URL) -> tuple:
    """Check for a newer version.  Returns (info_dict, error_str)."""
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        remote = data.get('version', '')
        if not remote:
            return None, "No version field"
        if _version_le(remote, CURRENT_VERSION):
            return {}, ""
        return data, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def download_update(url: str,
                    progress: Optional[Callable[[int, int], None]] = None,
                    ) -> Optional[str]:
    """Download the update EXE to a temp file.
    
    *progress(downloaded_bytes, total_bytes)* is called during download.
    Returns the path to the downloaded file, or None on failure.
    """
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
            try:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    tmp.write(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total or downloaded)
            finally:
                tmp.close()
            return tmp.name
    except Exception:
        return None


def apply_update(downloaded_path: str) -> bool:
    """Replace the running EXE via a helper batch script."""
    current_exe = sys.executable
    if not current_exe.lower().endswith('.exe'):
        return False
    try:
        batch = os.path.join(tempfile.gettempdir(), 'palmod_update.bat')
        with open(batch, 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write('ping 127.0.0.1 -n 3 >nul\n')
            f.write(f'copy /y "{downloaded_path}" "{current_exe}"\n')
            f.write(f'del "{downloaded_path}"\n')
            f.write(f'del "%~f0"\n')
            f.write(f'start "" "{current_exe}"\n')
        os.startfile(batch)
        return True
    except Exception:
        return False


def _version_le(a: str, b: str) -> bool:
    try:
        return tuple(int(x) for x in a.split('.')) <= tuple(int(x) for x in b.split('.'))
    except Exception:
        return True
