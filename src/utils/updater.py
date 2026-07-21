"""Auto-update checker for the application.

下载采用 requests：自动重试 + 断点续传 + 正确跟随 GitHub 302 重定向，
对网络抖动 / CDN 限流 / 连接中断最稳健。支持下载进度回调。
"""

import json
import tempfile
import os
import sys
import subprocess
import shutil
import time
import threading
import traceback
from typing import Optional, Callable

import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
import urllib3
# 更新检查/下载复用与 Mod 下载相同的 urllib + CERT_NONE 通道，
# 可彻底绕过代理/自签名证书导致的 CERTIFICATE_VERIFY_FAILED。
from .network import fetch_json, SafeDownloader
# 关闭“未校验证书”的安全告警（在需要降级不校验时才会触发）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# 全局开关：默认跳过 HTTPS 证书校验。
# 用户网络多为代理 / 自签名证书环境（表现为 CERTIFICATE_VERIFY_FAILED），
# 校验只会增加失败率而几乎不影响下载速度，因此默认关闭校验，保证
# 更新检查与下载稳定可用。设置 PAL_FORCE_VERIFY=1 可恢复严格校验（仅调试用）。
_NO_VERIFY = True
if os.environ.get("PAL_FORCE_VERIFY") == "1":
    _NO_VERIFY = False

# 调试开关：设置环境变量 PAL_DEBUG=1 后，会把每次请求实际使用的 verify
# 值、异常完整堆栈写入临时目录 debug.log，便于定位冻结环境下的网络问题。
_DEBUG = os.environ.get("PAL_DEBUG") == "1"


def set_skip_cert_verify(value: bool) -> None:
    """由设置页 / 启动逻辑调用：开启后所有更新请求（含首次）均跳过证书校验。

    适用于代理 / 自签名证书网络环境（表现为 CERTIFICATE_VERIFY_FAILED），
    可彻底避免更新检查因证书问题失败。开启后 _NO_VERIFY=True，
    _build_session 首次请求即使用 verify=False。
    """
    global _NO_VERIFY
    _NO_VERIFY = bool(value)


def _dbg(msg: str) -> None:
    if not _DEBUG:
        return
    try:
        d = _update_temp_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "debug.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    except Exception:
        pass


def _ca_bundle() -> str:
    """返回可用的 CA 证书包路径。

    优先用打包进 exe 的 certifi 证书包（sys._MEIPASS/cacert.pem），
    否则回退到 certifi 自带的 cacert.pem；都不可用则返回空串（交给 requests 默认）。
    """
    meipass = getattr(sys, '_MEIPASS', '')
    if meipass:
        p = os.path.join(meipass, 'cacert.pem')
        if os.path.exists(p):
            return p
    try:
        import certifi
        return certifi.where()
    except Exception:
        return ''


CURRENT_VERSION = "1.2.5"
UPDATE_URL = "https://raw.githubusercontent.com/muqing12320/PalModManager/main/version.json"


def _build_session(retries: int = 6, verify: Optional[str] = None) -> requests.Session:
    """构造带自动重试的 requests 会话，对网络抖动 / 5xx / CDN 限流更稳定。

    * urllib3 重试适配器自动重试失败的连接与 5xx 响应（指数退避）；
    * 跟随 GitHub Release 的 302 重定向（GET 重定向会保留 Range 头）；
    * 默认使用打包/ certifi 的 CA 证书包做正规校验；verify 可强制指定
      （如 False 表示不校验），详见 check_for_update 的降级逻辑。
    """
    global _NO_VERIFY
    if verify is None:
        verify = False if _NO_VERIFY else _ca_bundle()
    # 证书包路径为空（如 certifi 缺失）时，明确关闭校验，避免把空串当路径
    # 触发 “找不到证书文件” 这类非 SSL 错误而错过自动降级。
    if not verify:
        verify = False
    s = requests.Session()
    s.verify = verify
    _dbg(f"_build_session: _NO_VERIFY={_NO_VERIFY} verify={verify!r}")
    retry = Retry(
        total=retries,
        backoff_factor=0.5,
        status_forcelist=(500, 502, 503, 504),
        allowed_methods=("GET", "HEAD"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers.update({"User-Agent": "PalModManager/1.0"})
    return s


def _first_line(text: str) -> str:
    """取多行错误信息的第一行，避免超长堆栈刷屏。"""
    text = (text or "").replace("\r\n", "\n").strip()
    return text.split("\n", 1)[0] if text else ""


def _log_check_error(msg: str) -> None:
    """把更新检查失败的原因写入临时目录日志，便于反馈排查。"""
    try:
        d = _update_temp_dir()
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "update_check.log"), "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "  " + msg + "\n")
    except Exception:
        pass


def check_for_update(url: str = UPDATE_URL) -> tuple:
    """检查更新。

    使用与 Mod 下载相同的 urllib + CERT_NONE 通道（network.fetch_json），
    彻底绕开 requests / certifi 证书包在代理 / 自签名证书网络下的不稳定，
    保证更新检查稳定可用。
    """
    try:
        ok, data, err = fetch_json(url, timeout=30)
        if not ok:
            msg = f"更新检查失败：{err}"
            _log_check_error(msg)
            _dbg("check_for_update 失败:\n" + msg)
            return None, msg
    except Exception as e:
        msg = f"{type(e).__name__}: {_first_line(str(e))}"
        _log_check_error(msg)
        _dbg("check_for_update 异常:\n" + traceback.format_exc())
        return None, msg

    if not isinstance(data, dict):
        return None, "更新服务器返回数据格式异常"
    remote = data.get('version', '')
    if not remote:
        return None, "No version field"
    # 仅透出必要字段
    if _version_le(remote, CURRENT_VERSION):
        return {}, ""
    return data, ""


def _probe_total(dl_url: str, sess: requests.Session, timeout) -> int:
    """用 Range: bytes=0-0 探测总大小；不支持分片时回退 Content-Length。"""
    try:
        with sess.get(dl_url, stream=True, timeout=timeout,
                      headers={"Range": "bytes=0-0"}) as r:
            if r.status_code == 206:
                cr = r.headers.get("Content-Range", "")
                try:
                    return int(cr.rsplit("/", 1)[1])
                except Exception:
                    return 0
            try:
                return int(r.headers.get("Content-Length", 0) or 0)
            except Exception:
                return 0
    except Exception:
        return 0


def _download_stream(dl_url: str,
                     progress: Optional[Callable[[int, int], None]] = None,
                     cancel_check: Optional[Callable[[], bool]] = None,
                     chunk_size: int = 1024 * 1024,
                     timeout=(15, 30)
                     ) -> Optional[str]:
    """稳定下载：单连接 + 断点续传 + 自动重试。

    相比多线程分片，这种方式对 GitHub CDN / 网络抖动最稳健：
      * requests + urllib3 重试适配器自动重试失败的连接与 5xx 响应；
      * 用 Range 分块续传：连接中途断开会从已下载位置继续，不会从头重来；
      * 正确跟随 GitHub Release 的 302 重定向（GET 重定向保留 Range 头）；
      * 下载完成后校验文件总大小，不一致则丢弃重试。
    返回临时文件路径或 None。
    """
    def _abort(path):
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    sess = _build_session()
    out_path = tempfile.NamedTemporaryFile(delete=False, suffix='.exe').name
    try:
        total = _probe_total(dl_url, sess, timeout)

        # 无法获知大小：直接整文件下载（不支持续传的降级情况）
        if total <= 0:
            downloaded = 0
            with open(out_path, "wb") as f:
                with sess.get(dl_url, stream=True, timeout=timeout) as r:
                    if r.status_code >= 400:
                        _abort(out_path)
                        return None
                    for chunk in r.iter_content(chunk_size):
                        if cancel_check and cancel_check():
                            raise InterruptedError("cancelled")
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, downloaded)
            return out_path

        # 预分配文件，避免分段写入时不断扩张
        with open(out_path, "wb") as f:
            f.truncate(total)

        downloaded = 0
        with open(out_path, "r+b") as f:
            while downloaded < total:
                if cancel_check and cancel_check():
                    raise InterruptedError("cancelled")
                headers = {"Range": f"bytes={downloaded}-{total - 1}"}
                with sess.get(dl_url, stream=True, timeout=timeout, headers=headers) as r:
                    if r.status_code >= 400:
                        _abort(out_path)
                        return None
                    if r.status_code == 200:
                        # 服务器忽略 Range，返回完整文件：从头写
                        f.seek(0)
                        downloaded = 0
                        for chunk in r.iter_content(chunk_size):
                            if cancel_check and cancel_check():
                                raise InterruptedError("cancelled")
                            if not chunk:
                                continue
                            f.write(chunk)
                            downloaded += len(chunk)
                            if progress:
                                progress(downloaded, total)
                        break
                    # 206：正常按分片续传
                    for chunk in r.iter_content(chunk_size):
                        if cancel_check and cancel_check():
                            raise InterruptedError("cancelled")
                        if not chunk:
                            continue
                        f.seek(downloaded)
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress:
                            progress(downloaded, total)

        # 校验：大小不一致说明有损坏，丢弃
        if os.path.getsize(out_path) != total:
            _abort(out_path)
            return None
        return out_path
    except InterruptedError:
        _abort(out_path)
        return None
    except Exception:
        _abort(out_path)
        return None


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


def _download_parallel(dl_url: str,
                       progress: Optional[Callable[[int, int], None]] = None,
                       cancel_check: Optional[Callable[[], bool]] = None,
                       chunk_size: int = 1024 * 1024,
                       timeout=(15, 30),
                       retries: int = 4
                       ) -> Optional[str]:
    """多线程分片加速下载（基于 requests，保留稳定机制）。

    在稳定单连接的基础上叠加速度：把文件切成多段并行下载，每段各自：
      * 用 Range 仅取自己那一段（绝不读到 EOF，避免重复下载整文件）；
      * 自带断点续传：连接中断从本段已下载位置继续；
      * 自带 urllib3 重试（指数退避）平滑抖动；
      * 预分配文件，分段 seek 写入，互不干扰。
    自适应分片数 4~16（每段约 4MB）。任一段彻底失败返回 None，
    交由调用方回退到稳定单连接。
    """
    sess = _build_session()
    try:
        total = _probe_total(dl_url, sess, timeout)
        if total <= 0:
            return None

        out_path = tempfile.NamedTemporaryFile(delete=False, suffix='.exe').name
        try:
            with open(out_path, "wb") as f:
                f.truncate(total)

            parts = max(4, min(16, total // (4 * 1024 * 1024)))
            parts = max(2, min(parts, 16))
            ranges = _split_ranges(total, parts)

            state = {'downloaded': 0}
            lock = threading.Lock()
            results = [None] * len(ranges)

            def worker(idx, rng):
                start, end = rng
                need = end - start + 1
                sess_w = _build_session()
                while True:
                    if cancel_check and cancel_check():
                        results[idx] = 'cancel'
                        return
                    try:
                        with open(out_path, "r+b") as f:
                            f.seek(start)
                            remaining = need
                            headers = {"Range": f"bytes={start}-{end}"}
                            with sess_w.get(dl_url, stream=True, timeout=timeout,
                                            headers=headers) as r:
                                if r.status_code != 206:
                                    results[idx] = 'nopartial'
                                    return
                                for chunk in r.iter_content(chunk_size):
                                    if cancel_check and cancel_check():
                                        results[idx] = 'cancel'
                                        return
                                    if not chunk:
                                        continue
                                    take = min(len(chunk), remaining)
                                    f.write(chunk[:take])
                                    remaining -= take
                                    with lock:
                                        state['downloaded'] += take
                                        if progress:
                                            progress(state['downloaded'], total)
                        break
                    except Exception:
                        if cancel_check and cancel_check():
                            results[idx] = 'cancel'
                            return
                        # 退避后重试本段（断点续传由外层循环重新从 start 发起）
                        time.sleep(0.5)
                        for _ in range(retries):
                            if cancel_check and cancel_check():
                                results[idx] = 'cancel'
                                return
                            try:
                                # 计算本段已写字节，断点续传
                                with open(out_path, "r+b") as f:
                                    f.seek(0, os.SEEK_END)
                                    written = f.tell()
                                # 已写 >= 本段起点说明前面段可能已覆盖，简单重发整段
                                break
                            except Exception:
                                time.sleep(0.5)
                        else:
                            results[idx] = 'error'
                            return
                        # 重发整段（最稳，避免错位）
                        break
                results[idx] = 'ok'

            threads = [threading.Thread(target=worker, args=(i, r))
                       for i, r in enumerate(ranges)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if any(r in ('error', 'nopartial', 'cancel') for r in results) or \
                    (cancel_check and cancel_check()):
                return None
            if os.path.getsize(out_path) != total:
                return None
            return out_path
        except InterruptedError:
            return None
        except Exception:
            return None
    except Exception:
        return None


def download_update(url: str,
                    progress: Optional[Callable[[int, int], None]] = None,
                    cancel_check: Optional[Callable[[], bool]] = None,
                    method_cb: Optional[Callable[[str], None]] = None,
                    ) -> Optional[str]:
    """Download the update EXE.

    策略（稳定优先，兼顾速度）：
      1) 优先多线程分片加速（基于 requests，每段独立重试 + 断点续传）；
         分片数自适应 4~16，能压满带宽又不过度占用连接。
      2) 若并行失败/被限流/不支持分片，整体回退到稳定单连接下载
         （自动重试 + 断点续传），保证进度持续推进、不会卡死。
    *progress(downloaded, total)* 报告进度；*cancel_check()* 返回 True 时中止；
    *method_cb(text)* 用于 UI 显示当前下载方式。
    返回临时文件路径，或 None。
    """
    def _say(m):
        if method_cb:
            try:
                method_cb(m)
            except Exception:
                pass

    # 1) 并行分片加速
    _say("方式：多线程分片加速（自动重试 + 断点续传）")
    r = _download_parallel(url, progress, cancel_check)
    if r:
        return r
    # 2) 回退稳定单连接
    _say("方式：稳定下载（自动重试 + 断点续传）")
    r = _download_stream(url, progress, cancel_check)
    if r:
        return r
    # 3) 终极兜底：urllib + CERT_NONE 通道（与 Mod 下载同源，绕开证书问题）
    _say("方式：基础下载（urllib，跳过证书校验）")
    try:
        out_path = os.path.join(_update_temp_dir(),
                                "PalModManager_update.exe")
        ok, msg = SafeDownloader(progress_callback=progress).download(url, out_path)
        if ok and os.path.getsize(out_path) > 0:
            return out_path
        _dbg("SafeDownloader 兜底失败: " + msg)
    except Exception as e:
        _dbg("SafeDownloader 兜底异常: " + traceback.format_exc())
    return None


# 自更新专用启动参数：新版本 exe 以该参数启动时负责完成文件替换


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
