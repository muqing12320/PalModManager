"""Auto-update checker for the application.

Uses a lightweight HTTP approach — no SSL verification (acceptable for
GitHub raw URLs).  Supports download progress reporting.
"""

import json
import urllib.request
import ssl
import tempfile
import os
import sys
import subprocess
import shutil
import time
import threading
from typing import Optional, Callable


CURRENT_VERSION = "1.2.4"
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
        # 仅透出必要字段
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
    BUFFER = 1024 * 1024
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


def _probe_size(dl_url: str, ctx, timeout: int = 15):
    """用 Range: bytes=0-0 探测文件总大小并确认服务器是否支持分片。

    返回 (total, supports_range)。相比 HEAD 更可靠：很多 CDN 对 HEAD 返回
    200，但对带 Range 的 GET 返回 206，这里直接以实际下载响应为准。
    """
    try:
        req = urllib.request.Request(dl_url)
        req.add_header('User-Agent', 'PalModManager/1.0')
        req.add_header('Range', 'bytes=0-0')
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            if resp.status == 206:
                cr = resp.headers.get('Content-Range', '')
                try:
                    total = int(cr.rsplit('/', 1)[1])
                except Exception:
                    total = int(resp.headers.get('Content-Length', 0) or 0)
                return total, True
            try:
                total = int(resp.headers.get('Content-Length', 0) or 0)
            except Exception:
                total = 0
            return total, False
    except Exception:
        return 0, False


def _download_parallel(dl_url: str,
                       progress: Optional[Callable[[int, int], None]] = None,
                       cancel_check: Optional[Callable[[], bool]] = None,
                       read_timeout: int = 20,
                       retries: int = 3
                       ) -> Optional[str]:
    """多线程分片下载（类似 FDM / IDM 的多连接加速）。

    提速策略：
      * 自适应分片数：按文件大小在 4~16 段间自动选择（每段约 4MB），
        充分利用带宽又不至于连接过多被限流。
      * 同一服务器多连接：分片并行下载同一地址，充分利用带宽。
      * 每个分片用 1MB 大缓冲读取，减少系统调用、提升吞吐。
      * 必须返回 206 且按分片长度限量读取，避免“整文件当成分片重复下载”。
      * 分片有限次重试，平滑瞬时连接抖动。
    任意分片失败/被取消返回 None 交由兜底单线程方案处理。
    """
    try:
        ctx = _make_ssl_context()
        # 用 GET(Range: bytes=0-0) 探测大小与 Range 支持（比 HEAD 更可靠）
        total, supports = _probe_size(dl_url, ctx)
        if total <= 0 or not supports:
            return None

        out = tempfile.NamedTemporaryFile(delete=False, suffix='.exe')
        out_path = out.name
        out.close()
        # 预分配文件大小，避免分段写入时扩张
        with open(out_path, 'wb') as f:
            f.truncate(total)

        # 自适应分片数：每片约 4MB，min 4 / max 16
        parts = max(4, min(16, total // (4 * 1024 * 1024)))
        parts = max(2, min(parts, 16))
        ranges = _split_ranges(total, parts)
        # 多源时按分片轮询分配到不同 host，叠加带宽
        state = {'downloaded': 0}
        lock = threading.Lock()
        results = [None] * len(ranges)

        BUF = 1024 * 1024

        def worker(idx, rng):
            host = dl_url
            start, end = rng
            need = end - start + 1
            for attempt in range(retries + 1):
                if cancel_check and cancel_check():
                    results[idx] = 'cancel'
                    return
                try:
                    req = urllib.request.Request(host)
                    req.add_header('User-Agent', 'PalModManager/1.0')
                    req.add_header('Range', f'bytes={start}-{end}')
                    with urllib.request.urlopen(req, timeout=read_timeout, context=ctx) as resp:
                        # 服务器必须真正支持分片，否则整段下载会撑爆尾部进度
                        if resp.status != 206:
                            results[idx] = 'nopartial'
                            return
                        remaining = need
                        with open(out_path, 'r+b') as f:
                            f.seek(start)
                            while remaining > 0:
                                if cancel_check and cancel_check():
                                    results[idx] = 'cancel'
                                    return
                                chunk = resp.read(min(BUF, remaining))
                                if not chunk:
                                    break
                                f.write(chunk)
                                remaining -= len(chunk)
                                with lock:
                                    state['downloaded'] += len(chunk)
                                    if progress:
                                        progress(state['downloaded'], total)
                    break  # 本分片成功
                except Exception:
                    if attempt >= retries:
                        results[idx] = 'error'
                        return
                    time.sleep(0.5)

        threads = [threading.Thread(target=worker, args=(i, r)) for i, r in enumerate(ranges)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        if any(r in ('error', 'nopartial', 'cancel') for r in results) or (cancel_check and cancel_check()):
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
                    cancel_check: Optional[Callable[[], bool]] = None,
                    method_cb: Optional[Callable[[str], None]] = None,
                    ) -> Optional[str]:
    """Download the update EXE.

    优先尝试多线程分片下载，失败/卡死则尽快退回单线程下载，
    保证进度能持续推进、不会永久卡住。
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

    # 1) 并行，卡死会在 read_timeout 内暴露
    _say("方式：多线程分片加速")
    r = _download_parallel(url, progress, cancel_check)
    if r:
        return r
    # 2) 退回单线程
    _say("方式：单线程下载（更稳定）")
    return _download_update_fallback(url, progress, cancel_check)


def _download_update_fallback(url, progress, cancel_check):
    r = _download_simple(url, progress, cancel_check)
    return r


# 自更新专用启动参数：新版本 exe 以该参数启动时负责完成文件替换
APPLY_UPDATE_ARG = "--apply-update"


def _update_temp_dir() -> str:
    """集中存放更新过程的中间文件（暂存新 exe、备份）。

    所有中间产物都放在系统 temp 的 PalModManagerUpdate 子目录下，
    避免污染用户的原始安装目录——原目录最终只保留一个最终版本的 exe。
    """
    d = os.path.join(tempfile.gettempdir(), "PalModManagerUpdate")
    try:
        os.makedirs(d, exist_ok=True)
    except OSError:
        pass
    return d


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
        # 暂存新 exe 放在系统 temp（而非原目录），原目录最终只保留最终版
        temp_dir = _update_temp_dir()
        new_exe = os.path.join(temp_dir, "PalModManager_new.exe")
        if os.path.exists(new_exe):
            try:
                os.remove(new_exe)
            except OSError:
                pass
        shutil.copyfile(downloaded_path, new_exe)
        # 删除下载临时文件（本身也在系统 temp）
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
            # 兜底推导（兼容旧逻辑 / 未传路径的情况）。
            # 注意：此时 current_exe 位于 temp 子目录，不能从它反推原目录，
            # 只能回退到标准名并存于 temp（边缘情况，正常流程总会传入路径）。
            target_exe = os.path.join(_update_temp_dir(), "PalModManager.exe")
        # 备份放 temp（与暂存新 exe 同目录），不污染用户原目录
        backup_exe = os.path.join(os.path.dirname(current_exe),
                                  os.path.basename(target_exe) + ".bak")

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
    """正常启动时清理上次更新留下的临时文件。

    主要清理系统 temp 的 PalModManagerUpdate 子目录（暂存新 exe、备份），
    同时兼容清理旧版可能残留在原目录的中间文件。
    """
    try:
        current_exe = sys.executable
        exe_dir = os.path.dirname(current_exe)

        # 1) 清理系统 temp 子目录中的更新中间文件
        temp_dir = _update_temp_dir()
        if os.path.isdir(temp_dir):
            for name in os.listdir(temp_dir):
                if name == "PalModManager_new.exe" or name.endswith(".bak"):
                    try:
                        os.remove(os.path.join(temp_dir, name))
                    except OSError:
                        pass

        # 2) 兼容旧版：原目录曾直接存放过中间文件（正常情况不会再有）
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
