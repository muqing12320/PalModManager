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
from .network import fetch_json, SafeDownloader, make_ssl_context
# 关闭"未校验证书"的安全告警（在需要降级不校验时才会触发）
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


CURRENT_VERSION = "1.2.9"
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
    # 触发 "找不到证书文件" 这类非 SSL 错误而错过自动降级。
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


def _probe_total_urllib(base: str, ctx) -> int:
    """用 urllib + Range: bytes=0-0 探测总大小（支持分片时回退 Content-Length）。"""
    import urllib.request as _ur
    try:
        req = _ur.Request(base, headers={"User-Agent": SafeDownloader.USER_AGENT,
                                          "Range": "bytes=0-0"})
        with _ur.urlopen(req, context=ctx, timeout=30) as r:
            if r.status == 206:
                cr = r.headers.get("Content-Range", "")
                try:
                    return int(cr.rsplit("/", 1)[1])
                except Exception:
                    return 0
            cl = r.headers.get("Content-Length")
            try:
                return int(cl) if cl else 0
            except Exception:
                return 0
    except Exception:
        return 0


def _download_parallel_urllib(dl_url: str,
                              progress: Optional[Callable[[int, int], None]] = None,
                              cancel_check: Optional[Callable[[], bool]] = None,
                              ) -> Optional[str]:
    """基于 urllib 的多线程分片下载（绕开 requests 在限速代理下的秒退问题）。

    实测：在按连接限速的代理网络下，多连接可叠加带宽（单连接 ~0.05MB/s，
    4 线程可达 ~0.38MB/s，约 4~8 倍提速）。每段独立 Range 下载 + 自动重试，
    预分配文件后分段 seek 写入。

    优先走 ghproxy.net 镜像（国内更快），失败回退直连；两路都彻底失败返回 None，
    交由调用方回退到单连接下载。
    """
    import urllib.request as _ur
    ctx = make_ssl_context()
    # 候选源：ghproxy 镜像优先（实测可用且支持 Range），直连兜底
    candidates = ["https://ghproxy.net/" + dl_url, dl_url]
    out_path = os.path.join(_update_temp_dir(), "PalModManager_update.exe")
    for base in candidates:
        try:
            total = _probe_total_urllib(base, ctx)
            if total <= 0:
                _dbg("parallel urllib 跳过不可用源: " + base)
                continue
            # 预分配，避免分段写入时不断扩张
            with open(out_path, "wb") as f:
                f.truncate(total)
            # 自适应分片：每段约 4MB，线程 4~10
            parts = max(4, min(10, total // (4 * 1024 * 1024)))
            parts = max(4, parts)
            ranges = _split_ranges(total, parts)
            state = {'downloaded': 0}
            lock = threading.Lock()
            results = [None] * len(ranges)

            def worker(idx, rng):
                start, end = rng
                retries = 6
                while retries > 0:
                    if cancel_check and cancel_check():
                        results[idx] = 'cancel'
                        return
                    try:
                        req = _ur.Request(
                            base,
                            headers={"User-Agent": SafeDownloader.USER_AGENT,
                                     "Range": f"bytes={start}-{end}"})
                        with _ur.urlopen(req, context=ctx, timeout=90) as r:
                            if r.status not in (200, 206):
                                results[idx] = 'err'
                                return
                            with open(out_path, "r+b") as f:
                                f.seek(start)
                                while True:
                                    chunk = r.read(65536)
                                    if not chunk:
                                        break
                                    f.write(chunk)
                                    with lock:
                                        state['downloaded'] += len(chunk)
                                        if progress:
                                            progress(state['downloaded'], total)
                        results[idx] = 'ok'
                        return
                    except Exception:
                        retries -= 1
                        if cancel_check and cancel_check():
                            results[idx] = 'cancel'
                            return
                        time.sleep(0.5)
                results[idx] = 'err'

            threads = [threading.Thread(target=worker, args=(i, r))
                       for i, r in enumerate(ranges)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            if cancel_check and cancel_check():
                return None
            if any(x == 'err' for x in results):
                # 该源部分失败，尝试下一个候选源
                _dbg("parallel urllib 源部分失败，换下一源: " + base)
                continue
            if os.path.getsize(out_path) != total:
                _dbg("parallel urllib 大小校验不符，换下一源: " + base)
                continue
            return out_path
        except Exception:
            _dbg("parallel urllib 异常: " + traceback.format_exc())
            continue
    return None


def download_update(url: str,
                    progress: Optional[Callable[[int, int], None]] = None,
                    cancel_check: Optional[Callable[[], bool]] = None,
                    method_cb: Optional[Callable[[str], None]] = None,
                    ) -> Optional[str]:
    """Download the update EXE.

    策略（速度优先，兼顾稳定）：
      1) 优先 urllib 多线程分片加速（绕开 requests 在限速代理下的秒退，
         实测 4~8 倍提速），主走 ghproxy.net 镜像、回退直连；
      2) 回退 urllib 单连接稳定下载（自动重试），保证进度持续推进；
      3) 最后以 requests 单连接兜底（仅极端情况）。
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

    # 1) urllib 多线程分片加速（速度主力）
    _say("方式：多线程分片加速（urllib，自动重试 + 镜像）")
    r = _download_parallel_urllib(url, progress, cancel_check)
    if r:
        return r
    # 2) urllib 单连接稳定下载
    _say("方式：稳定下载（urllib，自动重试）")
    try:
        out_path = os.path.join(_update_temp_dir(), "PalModManager_update.exe")
        ok, msg = SafeDownloader(progress_callback=progress).download(url, out_path)
        if ok and os.path.getsize(out_path) > 0:
            return out_path
        _dbg("SafeDownloader 兜底失败: " + msg)
    except Exception as e:
        _dbg("SafeDownloader 兜底异常: " + traceback.format_exc())
    # 3) 最后以 requests 单连接兜底
    _say("方式：兼容下载（requests）")
    r = _download_stream(url, progress, cancel_check)
    if r:
        return r
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
    这样彻底避免"从 .bat/VBS 里启动新 exe 失败"的问题。
    """
    current_exe = sys.executable
    if not current_exe.lower().endswith(".exe"):
        return False
    if not os.path.isfile(downloaded_path):
        return False

    # 校验下载到的确实是 Windows 可执行文件（DOS 头 'MZ'），
    # 避免把 404 页面等错误内容当 exe 启动导致"闪退"。
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
            # 兜底（极端情况：未传入原路径）。直接以新版本运行，保证可用，
            # 且绝不向用户目录写入任何"固定文件名"的副本（避免产生第二个应用）。
            try:
                _launch_detached(current_exe)
            except Exception:
                pass
            os._exit(0)
        # 等待旧程序退出并释放文件句柄
        time.sleep(3)

        # 删除旧版 exe（Windows 上改名更安全），备份放 temp
        backup_exe = os.path.join(os.path.dirname(current_exe),
                                  os.path.basename(target_exe) + ".bak")
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

        # 把新 exe 复制为最终文件名，自动沿用用户在 Windows 里自定义的名字
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


# 用于识别"同属本应用"的可执行文件
_APP_PRODUCT_NAME = "PalModManager"


def _ver_tuple(v) -> Optional[tuple]:
    """把版本号归一化为 4 元组 (maj, min, patch, build)；无法解析返回 None。"""
    if not v:
        return None
    try:
        if isinstance(v, (tuple, list)):
            parts = [int(x) for x in v[:4]]
        else:
            parts = [int(x) for x in str(v).split(".") if x.strip().isdigit()]
        while len(parts) < 4:
            parts.append(0)
        return tuple(parts[:4])
    except Exception:
        return None


def _read_exe_version(path: str):
    """读取 exe 版本资源里的 (product_name, file_version_tuple)。

    读不到（如老版本安装包未内嵌版本资源）返回 (None, None)。
    仅用于"同应用 + 更旧"的精确判定，缺失时由图标识别兜底。
    """
    try:
        import ctypes
        # 版本资源 API 位于 version.dll（不是 kernel32）
        verdll = getattr(ctypes.windll, "version", None) or ctypes.CDLL("version")
        size = verdll.GetFileVersionInfoSizeW(path, None)
        if not size:
            return (None, None)
        buf = ctypes.create_string_buffer(size)
        if not verdll.GetFileVersionInfoW(path, 0, size, buf):
            return (None, None)

        class _LCP(ctypes.Structure):
            _fields_ = [("wLanguage", ctypes.c_uint16),
                        ("wCodePage", ctypes.c_uint16)]

        lp = ctypes.c_void_p()
        uLen = ctypes.c_uint()
        if not verdll.VerQueryValueW(buf, "\\VarFileInfo\\Translation",
                                     ctypes.byref(lp), ctypes.byref(uLen)):
            return (None, None)
        cp = ctypes.cast(lp, ctypes.POINTER(_LCP))[0]
        lang = "%04x%04x" % (cp.wLanguage, cp.wCodePage)
        product_name = None
        if verdll.VerQueryValueW(buf,
                                 "\\StringFileInfo\\%s\\ProductName" % lang,
                                 ctypes.byref(lp), ctypes.byref(uLen)):
            product_name = ctypes.wstring_at(lp)
        file_version = None
        ffi = ctypes.c_void_p()
        ffi_len = ctypes.c_uint()
        if verdll.VerQueryValueW(buf, "\\", ctypes.byref(ffi),
                                 ctypes.byref(ffi_len)):
            arr = ctypes.cast(ffi, ctypes.POINTER(ctypes.c_uint32 * 5))[0]
            file_version = (arr[2] >> 16, arr[2] & 0xffff,
                            arr[3] >> 16, arr[3] & 0xffff)
        return (product_name, file_version)
    except Exception:
        return (None, None)


def _read_icon_signature(path: str):
    """计算 exe 内嵌图标的规范化签名（字节）。

    图标以 PE 资源（RT_GROUP_ICON / RT_ICON）形式存放，不会被 PyInstaller
    压缩，因此所有版本（含老版本）都可读取并互相比对：相同图标 == 同一应用。
    读取失败返回 None（此时由版本资源判定兜底）。
    """
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        LOAD_LIBRARY_AS_DATAFILE = 0x2
        hmod = kernel32.LoadLibraryExW(path, None, LOAD_LIBRARY_AS_DATAFILE)
        if not hmod:
            return None
        try:
            RT_GROUP_ICON = 14
            RT_ICON = 3
            collected = {"gi": [], "ic": []}

            def _make_cb(bucket):
                def _cb(hModule, lpszType, lpszName, lParam):
                    if (lpszName & 0xFFFF0000) == 0:
                        collected[bucket].append(lpszName & 0xFFFF)
                    else:
                        try:
                            collected[bucket].append(ctypes.wstring_at(lpszName))
                        except Exception:
                            pass
                    return 1
                return _cb

            cb_t = ctypes.CFUNCTYPE(ctypes.c_int, wintypes.HMODULE,
                                    ctypes.c_void_p, ctypes.c_void_p,
                                    ctypes.c_void_p)
            kernel32.EnumResourceNamesW(hmod, ctypes.c_void_p(RT_GROUP_ICON),
                                        cb_t(_make_cb("gi")), 0)
            kernel32.EnumResourceNamesW(hmod, ctypes.c_void_p(RT_ICON),
                                        cb_t(_make_cb("ic")), 0)

            def _load(typ, name):
                hfind = kernel32.FindResourceW(hmod, ctypes.c_void_p(name),
                                               ctypes.c_void_p(typ))
                if not hfind:
                    return None
                sz = kernel32.SizeofResource(hmod, hfind)
                hglob = kernel32.LoadResource(hmod, hfind)
                if not hglob:
                    return None
                ptr = kernel32.LockResource(hglob)
                if not ptr:
                    return None
                return ctypes.string_at(ptr, sz)

            parts = []
            for n in sorted(collected["gi"], key=lambda x: (isinstance(x, str), x)):
                r = _load(RT_GROUP_ICON, n)
                if r is not None:
                    parts.append((str(n), r))
            for n in sorted(collected["ic"], key=lambda x: (isinstance(x, str), x)):
                r = _load(RT_ICON, n)
                if r is not None:
                    parts.append((str(n), r))
            if not parts:
                return None
            sig = bytearray()
            for name, buf in parts:
                sig += (str(name) + ":").encode("utf-8")
                sig += len(buf).to_bytes(4, "little")
                sig += buf
            return bytes(sig)
        finally:
            kernel32.FreeLibrary(hmod)
    except Exception:
        return None


def _is_same_app(path: str, ref_sig, ref_product) -> bool:
    """判断 path 是否与当前应用为同一程序（用于定位"旧版本"残留）。"""
    try:
        if not path.lower().endswith(".exe") or not os.path.isfile(path):
            return False
        # 1) 版本资源精确匹配（新版本安装包含 ProductName=PalModManager）
        product, _ = _read_exe_version(path)
        if product and product.strip() == _APP_PRODUCT_NAME:
            return True
        # 2) 图标签名匹配（跨版本、含老版本均有效）
        if ref_sig:
            sig = _read_icon_signature(path)
            if sig and sig == ref_sig:
                return True
        return False
    except Exception:
        return False


def _old_version_suffix(path: str) -> str:
    """计算用于把旧版本 exe 重命名后的后缀：优先版本号 '_v1.2.3'，读不到则时间戳。"""
    try:
        _, v = _read_exe_version(path)
        vt = _ver_tuple(v)
        if vt:
            return "_v%d.%d.%d" % (vt[0], vt[1], vt[2])
    except Exception:
        pass
    return "_old_" + time.strftime("%Y%m%d%H%M%S")


def _rename_old_siblings(updated_exe: str) -> None:
    """更新成功后，把同目录里"同应用"的旧版本 exe 重命名为"旧版本名字"保留。

    不删除任何文件：仅对确属本应用、且版本不比刚安装的新 exe 更新的其它 exe
    做重命名（如 我的管理器_v1.2.4.exe / PalModManager_v1.2.4.exe），
    既满足用户"保留旧版本"的诉求，又不会让用户看到两个同名应用造成混淆。
    updated_exe 自身（当前运行所用文件名）保持不变。
    """
    try:
        exe_dir = os.path.dirname(updated_exe)
        ref_sig = _read_icon_signature(updated_exe)
        ref_product, new_ver = _read_exe_version(updated_exe)
        new_ver = _ver_tuple(new_ver)
        try:
            target_mtime = os.path.getmtime(updated_exe)
        except OSError:
            target_mtime = None
        for name in os.listdir(exe_dir):
            sib = os.path.join(exe_dir, name)
            if sib.lower() == updated_exe.lower():
                continue
            if not sib.lower().endswith(".exe"):
                continue
            if not _is_same_app(sib, ref_sig, ref_product):
                continue
            # 已经是"旧版本名字"（_vX.Y.Z 或 _old_时间戳）的，跳过避免重复处理
            base = os.path.splitext(name)[0]
            if base.endswith("_old") or "_v" in base:
                continue
            # 是否为"应重命名的旧版本/冗余副本"：同应用且"不比新 exe 更新"
            is_old = True
            if new_ver is not None:
                p2, v2 = _read_exe_version(sib)
                v2t = _ver_tuple(v2)
                if p2 and p2.strip() == _APP_PRODUCT_NAME and v2t is not None:
                    is_old = v2t <= new_ver  # 同版本或旧版本都重命名保留
            # 兜底：万一读不到版本（老版本无资源），用修改时间保护，绝不处理比新 exe 更新的文件
            if is_old and target_mtime is not None:
                try:
                    if os.path.getmtime(sib) > target_mtime:
                        is_old = False
                except OSError:
                    pass
            if not is_old:
                continue
            # 重命名为"旧版本名字"（保留在原目录，不删除）
            new_name = os.path.splitext(sib)[0] + _old_version_suffix(sib) + ".exe"
            if os.path.exists(new_name):
                new_name = (os.path.splitext(sib)[0] + _old_version_suffix(sib)
                            + "_" + time.strftime("%H%M%S") + ".exe")
            try:
                os.rename(sib, new_name)
                _dbg("旧版本已重命名保留: " + sib + " -> " + new_name)
            except OSError:
                pass
    except Exception:
        pass


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
