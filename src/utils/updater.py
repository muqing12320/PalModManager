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
import shutil
import time
from pathlib import Path
from typing import Optional, Callable


CURRENT_VERSION = "1.1.12"
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


# 自更新专用启动参数：新版本 exe 以该参数启动时负责完成文件替换
APPLY_UPDATE_ARG = "--apply-update"


def _clean_env():
    """复制一份环境变量并清除 PyInstaller 的 _MEIPASS，避免子进程复用父进程的临时目录。"""
    env = os.environ.copy()
    env.pop("_MEIPASS", None)
    env.pop("_MEIPASS2", None)
    return env


def _launch_detached(exe_path: str, args=None, env=None):
    """以脱离父进程的方式启动一个 exe，父进程退出也不会牵连它。"""
    flags = 0
    for f in ("DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        flags |= getattr(subprocess, f, 0)
    cmd = [exe_path] + list(args or [])
    return subprocess.Popen(
        cmd,
        creationflags=flags,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env if env is not None else _clean_env(),
    )


def apply_update(downloaded_path: str) -> bool:
    """应用更新：把新版本交给一个独立的新进程去替换并自启。

    做法：将下载好的新 exe 复制为同目录下的 PalModManager_new.exe，
    由当前程序用 subprocess 直接拉起它（带 --apply-update 参数），
    随后当前程序立即退出。新进程负责等待旧程序释放后替换文件并启动最终程序。
    这样彻底避免“从 .bat/VBS 里启动新 exe 失败”的问题。
    """
    current_exe = sys.executable
    if not current_exe.lower().endswith(".exe"):
        return False
    if not os.path.isfile(downloaded_path):
        return False

    try:
        exe_dir = os.path.dirname(current_exe)
        # 暂存文件名与最终名不同，避免被运行中的文件锁住
        new_exe = os.path.join(exe_dir, "PalModManager_new.exe")
        if os.path.exists(new_exe):
            try:
                os.remove(new_exe)
            except OSError:
                pass
        shutil.copyfile(downloaded_path, new_exe)
        # 删除临时下载文件
        try:
            os.remove(downloaded_path)
        except OSError:
            pass
        # 拉起新版本去完成替换（.detached，父进程退出也存活）
        _launch_detached(new_exe, args=[APPLY_UPDATE_ARG])
        return True
    except Exception:
        return False


def finish_pending_update() -> bool:
    """若以 --apply-update 启动，则完成文件替换并启动最终程序。

    返回 True 表示已处理更新流程（调用方应直接退出，不要再显示界面）。
    """
    if APPLY_UPDATE_ARG not in sys.argv:
        return False
    try:
        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)
        # PalModManager_new.exe -> PalModManager.exe
        if current_exe.lower().endswith("_new.exe"):
            target_exe = current_exe[: -len("_new.exe")] + ".exe"
        else:
            target_exe = os.path.join(exe_dir, "PalModManager.exe")
        backup_exe = target_exe + ".bak"

        # 等待旧程序退出并释放文件句柄
        time.sleep(3)

        # 先把旧 exe 改名备份（Windows 上运行中的 exe 可被改名）
        for _ in range(20):
            try:
                if os.path.exists(target_exe):
                    if os.path.exists(backup_exe):
                        try:
                            os.remove(backup_exe)
                        except OSError:
                            pass
                    os.rename(target_exe, backup_exe)
                break
            except OSError:
                time.sleep(0.5)

        # 把新 exe 复制为最终文件名
        for _ in range(20):
            try:
                shutil.copyfile(current_exe, target_exe)
                break
            except OSError:
                time.sleep(0.5)

        # 启动最终程序
        _launch_detached(target_exe)

        # 退出当前（_new.exe）进程
        os._exit(0)
    except Exception:
        # 兜底：直接以 _new.exe 作为新版本运行，保证用户至少能用上新版本
        try:
            _launch_detached(sys.executable)
        except Exception:
            pass
        os._exit(0)
    return True


def cleanup_update_leftovers():
    """正常启动时清理上次更新留下的临时文件。"""
    try:
        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)
        for name in ("PalModManager_new.exe", "PalModManager.exe.bak"):
            p = os.path.join(exe_dir, name)
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
    except Exception:
        pass


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
