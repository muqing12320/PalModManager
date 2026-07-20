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
import subprocess
from pathlib import Path
from typing import Optional, Callable


CURRENT_VERSION = "1.1.5"
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
        # Pass mirror URL through for download phase
        data['_mirror'] = data.get('mirror_url', '')
        if _version_le(remote, CURRENT_VERSION):
            return {}, ""
        return data, ""
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def download_update(url: str,
                    progress: Optional[Callable[[int, int], None]] = None,
                    mirror: str = '',
                    ) -> Optional[str]:
    """Download the update EXE. Tries primary URL first, then mirror.
    
    *progress(downloaded_bytes, total_bytes)* is called during download.
    Returns the path to the downloaded file, or None on failure.
    """
    BUFFER = 512 * 1024  # 512KB chunks for faster throughput
    
    def _try_download(dl_url: str) -> Optional[str]:
        try:
            req = urllib.request.Request(dl_url)
            req.add_header('User-Agent', 'PalModManager/1.0')
            ctx = _make_ssl_context()
            with urllib.request.urlopen(req, timeout=300, context=ctx) as resp:
                total = int(resp.headers.get('Content-Length', 0))
                downloaded = 0
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
                try:
                    while True:
                        chunk = resp.read(BUFFER)
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
    
    result = _try_download(url)
    if result:
        return result
    if mirror:
        return _try_download(mirror)
    return None


def apply_update(downloaded_path: str) -> bool:
    """Replace the running EXE and relaunch. Returns True on success.
    
    Two-stage: rename old EXE to .bak, copy new EXE in. The rename works
    even if the original EXE is briefly locked.
    """
    current_exe = sys.executable
    if not current_exe.lower().endswith('.exe'):
        return False
    try:
        ps1 = os.path.join(tempfile.gettempdir(), 'palmod_update.ps1')
        with open(ps1, 'w', encoding='utf-8') as f:
            f.write(
                f'$ErrorActionPreference = "Stop"\n'
                f'$new  = "{downloaded_path}"\n'
                f'$exe  = "{current_exe}"\n'
                f'$self = "{ps1}"\n'
                f'$bak  = "$exe.bak"\n'
                f'Start-Sleep -Seconds 3\n'
                f'$tried = 0\n'
                f'while ($tried -lt 10) {{\n'
                f'    try {{\n'
                f'        if (Test-Path $bak) {{ Remove-Item $bak -Force }}\n'
                f'        Rename-Item $exe $bak -Force -ErrorAction Stop\n'
                f'        Copy-Item $new $exe -Force -ErrorAction Stop\n'
                f'        Remove-Item $new -Force\n'
                f'        Remove-Item $self -Force\n'
                f'        Start-Process $exe\n'
                f'        exit 0\n'
                f'    }} catch {{\n'
                f'        Start-Sleep -Seconds 2\n'
                f'        $tried++\n'
                f'    }}\n'
                f'}}\n'
                f'Add-Content -Path "$exe.log" -Value "Update failed after 10 tries: $new -> $exe"\n'
            )
        subprocess.Popen(
            ['powershell', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden',
             '-File', ps1],
            shell=True, creationflags=0x08000000 if sys.platform == 'win32' else 0)
        return True
    except Exception:
        return False


def _version_le(a: str, b: str) -> bool:
    """Return True if a <= b.  Strips 'v' prefix and ignores non-numeric parts."""
    def _norm(v: str) -> tuple:
        v = v.lstrip('v').strip()
        parts = []
        for p in v.split('.'):
            digits = ''
            for c in p:
                if c.isdigit():
                    digits += c
                else:
                    break
            parts.append(int(digits) if digits else 0)
        return tuple(parts) if parts else (0,)
    try:
        return _norm(a) <= _norm(b)
    except Exception:
        return True
