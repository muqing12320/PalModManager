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
import threading
from pathlib import Path
from typing import Optional, Callable


CURRENT_VERSION = "1.1.16"
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


def _split_ranges(total: int, parts: int):
    """把 [0, total) 均匀切成 parts 个 (start, end) 闭区间。"""
    ranges = []
    step = max(total // parts, 1)
    for i in range(parts):
        start = i * step
        if start >= total:
            break
        end = total - 1 if i == parts - 1 else start + step - 1
        if end >= total:
            end = total - 1
        ranges.append((start, end))
    if not ranges:
        ranges = [(0, total - 1)]
    return ranges


def _download_simple(dl_url: str,
                     progress: Optional[Callable[[int, int], None]] = None,
                     cancel_check: Optional[Callable[[], bool]] = None,
                     timeout: int = 30
                     ) -> Optional[str]:
    """单线程下载（兜底方案）。返回临时文件路径或 None。"""
    BUFFER = 512 * 1024
    tmp = None
    try:
        req = urllib.request.Request(dl_url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        ctx = _make_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
            while True:
                if cancel_check and cancel_check():
                    raise InterruptedError('cancelled')
                chunk = resp.read(BUFFER)
                if not chunk:
                    break
                tmp.write(chunk)
                downloaded += len(chunk)
                if progress:
                    progress(downloaded, total or downloaded)
            tmp.close()
            return tmp.name
    except Exception:
        if tmp is not None and os.path.exists(tmp.name):
            try:
                os.remove(tmp.name)
            except OSError:
                pass
        return None


def _download_parallel(dl_url: str,
                       progress: Optional[Callable[[int, int], None]] = None,
                       cancel_check: Optional[Callable[[], bool]] = None,
                       parts: int = 4,
                       read_timeout: int = 20
                       ) -> Optional[str]:
    """多线程分片下载（类似 FDM 的多连接加速）。

    通过 HTTP Range 把文件切成多段并行下载再合并，提升带宽利用率。
    若服务器不支持 Range / 分片失败 / 连接被卡，返回 None 交由兜底方案处理。
    read_timeout 限制单段最长阻塞时间，避免整体永久卡死。
    """
    try:
        ctx = _make_ssl_context()
        # 先用 HEAD 探明大小与是否支持 Range
        head = urllib.request.Request(dl_url, method='HEAD')
        head.add_header('User-Agent', 'PalModManager/1.0')
        with urllib.request.urlopen(head, timeout=15, context=ctx) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            accept_ranges = resp.headers.get('Accept-Ranges', '').lower()
        if total <= 0 or 'bytes' not in accept_ranges:
            return None

        out = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
        out_path = out.name
        out.close()
        # 预分配文件大小，避免分段写入时扩张
        with open(out_path, 'wb') as f:
            f.truncate(total)

        ranges = _split_ranges(total, parts)
        errors = []
        state = {'downloaded': 0}
        lock = threading.Lock()

        def worker(rng):
            if cancel_check and cancel_check():
                return
            start, end = rng
            try:
                req = urllib.request.Request(dl_url)
                req.add_header('User-Agent', 'PalModManager/1.0')
                req.add_header('Range', f'bytes={start}-{end}')
                with urllib.request.urlopen(req, timeout=read_timeout, context=ctx) as resp:
                    data = resp.read()
                if cancel_check and cancel_check():
                    return
                with open(out_path, 'r+b') as f:
                    f.seek(start)
                    f.write(data)
                with lock:
                    state['downloaded'] += len(data)
                    if progress:
                        progress(state['downloaded'], total)
            except Exception:
                errors.append(True)

        threads = [threading.Thread(target=worker, args=(r,)) for r in ranges]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if errors or (cancel_check and cancel_check()):
            try:
                os.remove(out_path)
            except OSError:
                pass
            return None
        return out_path
    except Exception:
        return None


def download_update(url: str,
                    progress: Optional[Callable[[int, int], None]] = None,
                    mirror: str = '',
                    cancel_check: Optional[Callable[[], bool]] = None,
                    method_cb: Optional[Callable[[str], None]] = None,
                    ) -> Optional[str]:
    """Download the update EXE.

    优先尝试多线程分片下载（主地址），失败/卡死则尽快退回单线程
    （主地址 -> 镜像），保证进度能持续推进、不会永久卡住。
    *progress(downloaded, total)* 报告进度；*cancel_check()* 返回 True 时中止；
    *method_cb(text)* 在切换下载方式时回调，用于 UI 显示当前阶段/方式。
    返回临时文件路径，或 None。
    """
    def _say(m):
        if method_cb:
            try:
                method_cb(m)
            except Exception:
                pass

    # 1) 并行（主地址），卡死会在 read_timeout 内暴露
    _say("方式：多线程分片加速（主服务器）")
    r = _download_parallel(url, progress, cancel_check)
    if r:
        return r
    # 2) 退回单线程（主地址 -> 镜像）
    _say("方式：单线程下载（更稳定）")
    return _download_update_fallback(url, mirror, progress, cancel_check)


def _download_update_fallback(url, mirror, progress, cancel_check):
    for dl_url in (url, mirror):
        if not dl_url:
            continue
        r = _download_simple(dl_url, progress, cancel_check)
        if r:
            return r
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

    # 校验下载到的确实是 Windows 可执行文件（DOS 头 'MZ'），
    # 避免把 404 页面等错误内容当 exe 启动导致“闪退”。
    try:
        with open(downloaded_path, "rb") as fh:
            head = fh.read(2)
        if head != b"MZ" or os.path.getsize(downloaded_path) < 1024 * 1024:
            return False
    except Exception:
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
        # 把原始 exe 路径作为参数传入，以便更新后保留用户自定义的文件名
        _launch_detached(new_exe, args=[APPLY_UPDATE_ARG, current_exe])
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
        # 原始（被替换的）exe 路径由启动参数传入，以保留用户自定义文件名
        target_exe = None
        try:
            idx = sys.argv.index(APPLY_UPDATE_ARG)
            if idx + 1 < len(sys.argv):
                cand = sys.argv[idx + 1]
                if cand.lower().endswith(".exe"):
                    target_exe = cand
        except Exception:
            target_exe = None
        if not target_exe:
            # 兜底推导（兼容旧逻辑 / 未传路径的情况）
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
        # 同时兼容：用户自定义名（<当前exe>.bak）、固定名（PalModManager.exe.bak）
        # 以及暂存文件 PalModManager_new.exe
        candidates = [
            os.path.join(exe_dir, "PalModManager_new.exe"),
            current_exe + ".bak",
            os.path.join(exe_dir, "PalModManager.exe.bak"),
        ]
        for p in candidates:
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
