"""
Network utility for downloading files with robust error handling.
Provides SSL fallback, multiple mirrors, and retry logic.
"""
import os
import ssl
import socket
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Callable, Tuple


# Disable SSL verification globally for legacy Python and corporate proxies
# This is required because PyInstaller bundles may not include certifi certificates
try:
    import ssl
    # Create default SSL context that doesn't verify certificates
    _default_context = ssl.create_default_context()
    _default_context.check_hostname = False
    _default_context.verify_mode = ssl.CERT_NONE
except Exception:
    _default_context = None


def make_ssl_context():
    """Create an SSL context that bypasses certificate verification."""
    if _default_context is None:
        return None
    return _default_context


class SafeDownloader:
    """A downloader that works around SSL errors and uses fallbacks."""
    
    USER_AGENT = "PalModManager/1.0"  # 帕鲁Mod管理器
    
    def __init__(self, progress_callback: Optional[Callable[[int, int], None]] = None):
        self.progress_callback = progress_callback
    
    def download(self, url: str, dest_path: str, timeout: int = 300) -> Tuple[bool, str]:
        """
        Download a file with SSL error handling.
        
        Args:
            url: URL to download from
            dest_path: Local destination path
            timeout: Timeout in seconds
        
        Returns:
            Tuple of (success, error_message_or_dest_path)
        """
        try:
            # Method 1: Try with urllib + custom SSL context (bypasses verify)
            success, result = self._download_urllib(url, dest_path, timeout)
            if success:
                return True, dest_path
            return False, result
        except Exception as e:
            return False, f"下载失败: {str(e)}"
    
    def _download_urllib(self, url: str, dest_path: str, timeout: int) -> Tuple[bool, str]:
        """Download using urllib with SSL bypass."""
        try:
            ctx = make_ssl_context()
            
            req = urllib.request.Request(url, headers={'User-Agent': self.USER_AGENT})
            
            # Set socket timeout
            socket.setdefaulttimeout(timeout)
            
            # Open URL with custom SSL context if available
            if ctx is not None:
                response = urllib.request.urlopen(req, context=ctx, timeout=timeout)
            else:
                response = urllib.request.urlopen(req, timeout=timeout)
            
            # Get total size for progress reporting
            total_size = response.headers.get('Content-Length')
            total_size = int(total_size) if total_size else 0
            
            dest = Path(dest_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            
            downloaded = 0
            with open(dest, 'wb') as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if self.progress_callback and total_size > 0:
                        self.progress_callback(downloaded, total_size)
            
            return True, str(dest)
            
        except urllib.error.HTTPError as e:
            return False, f"HTTP错误 {e.code}: {e.reason}"
        except urllib.error.URLError as e:
            return False, f"网络错误: {e.reason}"
        except ssl.SSLError as e:
            return False, f"SSL错误: {str(e)} (尝试在设置中使用本地文件安装)"
        except socket.timeout:
            return False, "下载超时，请检查网络连接"
        except Exception as e:
            return False, f"下载失败: {str(e)}"


def fetch_json(url: str, timeout: int = 30) -> Tuple[bool, dict, str]:
    """
    Fetch JSON from a URL with SSL bypass.
    
    Returns:
        Tuple of (success, data_dict, error_message)
    """
    try:
        ctx = make_ssl_context()
        req = urllib.request.Request(url, headers={'User-Agent': SafeDownloader.USER_AGENT})
        
        if ctx is not None:
            response = urllib.request.urlopen(req, context=ctx, timeout=timeout)
        else:
            response = urllib.request.urlopen(req, timeout=timeout)
        
        content = response.read()
        import json
        data = json.loads(content)
        return True, data, ""
    except ssl.SSLError as e:
        return False, {}, f"SSL证书验证失败: {str(e)}"
    except Exception as e:
        return False, {}, f"获取信息失败: {str(e)}"


def download_file_with_fallback(urls: list, dest_path: str, 
                                progress_callback: Optional[Callable] = None) -> Tuple[bool, str]:
    """
    Try downloading from a list of URLs in order until one succeeds.
    
    Args:
        urls: List of URLs to try
        dest_path: Destination file path
    
    Returns:
        Tuple of (success, message)
    """
    last_error = ""
    for url in urls:
        downloader = SafeDownloader(progress_callback=progress_callback)
        success, result = downloader.download(url, dest_path)
        if success:
            return True, f"下载成功: {url}"
        last_error = result
    
    return False, f"所有下载源均失败。最后一个错误: {last_error}"


def install_certifi_if_missing():
    """
    Try to install certifi certificates to fix SSL issues.
    Useful for PyInstaller-bundled apps on systems with outdated certs.
    """
    try:
        import certifi
        os.environ['SSL_CERT_FILE'] = certifi.where()
        os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()
        return True
    except ImportError:
        return False
