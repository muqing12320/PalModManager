"""Auto-update checker for 帕鲁Mod管理器.

Checks a remote version file (JSON), compares with the current version,
and downloads the new EXE if available.
"""

import json
import urllib.request
import urllib.error
import tempfile
import shutil
from pathlib import Path
from typing import Optional, Tuple
import sys
import os


# Current version — bump this with each release
CURRENT_VERSION = "1.0.0"

# Default update check URL (host your own version.json here)
# Format: { "version": "1.0.1", "download_url": "https://.../帕鲁Mod管理器.exe", "notes": "更新内容" }
DEFAULT_UPDATE_URL = ""


def check_for_update(update_url: str = "") -> Optional[dict]:
    """Check if a newer version is available.
    
    Args:
        update_url: URL to version.json. If empty, returns None.
    
    Returns:
        dict with 'version', 'download_url', 'notes' if update available, else None.
    """
    if not update_url:
        return None
    
    try:
        req = urllib.request.Request(update_url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception:
        return None
    
    remote_version = data.get('version', '')
    if not remote_version:
        return None
    
    if _version_tuple(remote_version) <= _version_tuple(CURRENT_VERSION):
        return None
    
    return {
        'version': remote_version,
        'download_url': data.get('download_url', ''),
        'notes': data.get('notes', ''),
    }


def download_update(download_url: str, progress_callback=None) -> Optional[str]:
    """Download the update EXE to a temp file.
    
    Returns the path to the downloaded file, or None on failure.
    """
    try:
        req = urllib.request.Request(download_url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        
        with urllib.request.urlopen(req, timeout=300) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                tmp.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total > 0:
                    progress_callback(downloaded, total)
            tmp.close()
            return tmp.name
    except Exception:
        return None


def apply_update(downloaded_path: str) -> bool:
    """Replace the current EXE with the downloaded one.
    
    On Windows, we can't replace the running EXE directly.
    Instead, we write a batch script to do it after exit.
    """
    current_exe = sys.executable
    
    if not current_exe.lower().endswith('.exe'):
        return False
    
    try:
        # Write a helper batch script
        batch_path = os.path.join(tempfile.gettempdir(), 'palmod_update.bat')
        with open(batch_path, 'w', encoding='utf-8') as f:
            f.write('@echo off\n')
            f.write('echo 正在更新帕鲁Mod管理器...\n')
            f.write('ping 127.0.0.1 -n 3 >nul\n')  # Wait 3 seconds
            f.write(f'copy /y "{downloaded_path}" "{current_exe}"\n')
            f.write(f'del "{downloaded_path}"\n')
            f.write(f'del "%~f0"\n')
            f.write(f'start "" "{current_exe}"\n')
        
        os.startfile(batch_path)
        return True
    except Exception:
        return False


def _version_tuple(version: str) -> tuple:
    """Convert version string to comparable tuple."""
    try:
        return tuple(int(x) for x in version.split('.'))
    except Exception:
        return (0,)
