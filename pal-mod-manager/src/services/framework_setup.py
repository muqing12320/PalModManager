"""
Framework Setup Service - orchestrates automatic installation and configuration
of UE4SS and PalSchema frameworks for Palworld (client and server).
"""
import os
import sys
import json
import shutil
import zipfile
import tempfile
import socket
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable
from datetime import datetime

from .ue4ss_service import UE4SSService
from .palschema_service import PalSchemaService
from ..utils.network import (
    SafeDownloader, fetch_json, make_ssl_context, install_certifi_if_missing
)

# Set longer socket timeout as default
socket.setdefaulttimeout(60)


def _get_bundled_resource_path(filename: str) -> Optional[str]:
    """Get path to a bundled resource file (works in both dev and PyInstaller modes).
    
    In PyInstaller: resources are extracted to sys._MEIPASS/resources/
    In dev mode: resources/ folder relative to this file's package
    """
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller exe
        base = Path(sys._MEIPASS) / "resources"
    else:
        # Running as dev
        base = Path(__file__).parent.parent.parent / "resources"
    
    path = base / filename
    return str(path) if path.exists() else None


class FrameworkSetupService:
    """Orchestrates automatic installation and setup of modding frameworks."""
    
    UE4SS_LATEST = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/latest"
    PALSCHEMA_LATEST = "https://api.github.com/repos/Okaetsu/PalSchema/releases/latest"
    
    def __init__(self, game_path: str):
        self.game_path = Path(game_path)
        self._ue4ss = UE4SSService(game_path)
        self._palschema = PalSchemaService(game_path)
        self._progress_callback: Optional[Callable[[str, int], None]] = None
        self._download_progress: Optional[Callable[[int, int], None]] = None
        self._last_error: str = ""
        
        # Try to install certifi for better SSL support
        install_certifi_if_missing()
    
    def on_progress(self, callback: Callable[[str, int], None]):
        """Register a progress callback: callback(message, percentage)."""
        self._progress_callback = callback
    
    def on_download_progress(self, callback: Callable[[int, int], None]):
        """Register a download progress callback: callback(downloaded, total)."""
        self._download_progress = callback
    
    @property
    def last_error(self) -> str:
        """Get the last error message."""
        return self._last_error
    
    def _report(self, message: str, percentage: int):
        """Report progress to callback."""
        if self._progress_callback:
            self._progress_callback(message, percentage)
    
    def get_status(self) -> dict:
        """Get current framework installation status."""
        return {
            'ue4ss_installed': self._ue4ss.is_installed(),
            'ue4ss_version': self._ue4ss.get_version(),
            'palschema_installed': self._palschema.is_installed(),
            'palschema_version': self._palschema.get_version(),
            'all_ready': self._ue4ss.is_installed() and self._palschema.is_installed(),
        }
    
    def needs_setup(self) -> bool:
        """Check if any framework needs to be installed."""
        return not self._ue4ss.is_installed() or not self._palschema.is_installed()
    
    def setup_all(self, use_local_archives: bool = False) -> Tuple[bool, List[str]]:
        """Install and configure all missing frameworks.
        Prefers bundled archives first, falls back to download."""
        messages = []
        all_ok = True
        
        if not self._ue4ss.is_installed():
            self._report("正在安装 UE4SS...", 10)
            success, msg = self._install_ue4ss_bundled()
            messages.append(f"UE4SS: {msg}")
            if not success:
                all_ok = False
                messages.append(f"  提示: {self._get_ssl_hint()}")
            else:
                self._report("正在配置 UE4SS...", 40)
                self._ue4ss.configure_for_palworld()
        else:
            messages.append("UE4SS: 已安装")
        
        if not self._palschema.is_installed():
            self._report("正在安装 PalSchema...", 60)
            success, msg = self._install_palschema_bundled()
            messages.append(f"PalSchema: {msg}")
            if not success:
                all_ok = False
                messages.append(f"  提示: {self._get_ssl_hint()}")
        else:
            messages.append("PalSchema: 已安装")
        
        self._report("正在创建目录结构...", 85)
        self._ensure_directories()
        
        self._report("正在生成配置文件...", 95)
        self._ue4ss.update_mods_txt([])
        
        self._report("框架安装完成！", 100)
        
        return all_ok, messages
    
    def _install_ue4ss_bundled(self) -> Tuple[bool, str]:
        """Install UE4SS, preferring bundled archive over download."""
        bundled = _get_bundled_resource_path("UE4SS_v3.0.1.zip")
        if bundled:
            self._report("使用内置 UE4SS 安装包...", 15)
            return self._ue4ss.install(bundled)
        
        self._report("未找到内置包，尝试在线下载...", 15)
        return self._install_ue4ss()
    
    def _install_palschema_bundled(self) -> Tuple[bool, str]:
        """Install PalSchema, preferring bundled archive over download."""
        bundled = _get_bundled_resource_path("PalSchema_0.6.0.zip")
        if bundled:
            self._report("使用内置 PalSchema 安装包...", 65)
            return self.install_palschema_from_archive(bundled)
        
        self._report("未找到内置包，尝试在线下载...", 65)
        return self._install_palschema()
    
    def _get_ssl_hint(self) -> str:
        """Get a hint message for SSL/network errors."""
        if "SSL" in self._last_error or "证书" in self._last_error:
            return "SSL证书验证失败，请使用「从本地文件安装」"
        if "timeout" in self._last_error.lower() or "超时" in self._last_error:
            return "网络连接超时，请检查网络后重试"
        if "HTTP" in self._last_error:
            return "无法访问 GitHub，请检查网络或使用本地安装"
        return "请检查网络连接，或使用「从本地文件安装」"
    
    def _install_ue4ss(self) -> Tuple[bool, str]:
        """Install UE4SS framework using SSL-bypass downloader."""
        try:
            self._report("正在获取 UE4SS 版本信息...", 15)
            
            # Get latest release info
            success, release, err = fetch_json(self.UE4SS_LATEST, timeout=30)
            
            if not success:
                self._last_error = err
                return False, err
            
            tag = release.get('tag_name', 'unknown')
            assets = release.get('assets', [])
            
            if not assets:
                return False, "UE4SS 仓库中未找到任何资源文件"
            
            # Find the UE4SS zip
            zip_asset = None
            for asset in assets:
                name = asset.get('name', '').lower()
                if name.endswith('.zip') and 'ue4ss' in name:
                    zip_asset = asset
                    break
            
            if not zip_asset:
                # Fallback: take any .zip
                for asset in assets:
                    name = asset.get('name', '').lower()
                    if name.endswith('.zip'):
                        zip_asset = asset
                        break
            
            if not zip_asset:
                return False, "未找到 UE4SS 下载文件"
            
            self._report(f"正在下载 UE4SS v{tag}...", 25)
            
            download_url = zip_asset['browser_download_url']
            
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                downloader = SafeDownloader(progress_callback=self._download_progress)
                success, result = downloader.download(download_url, tmp_path, timeout=600)
                
                if not success:
                    self._last_error = result
                    return False, result
                
                self._report("正在安装 UE4SS...", 35)
                # Use the existing UE4SS service to install
                install_success, install_msg = self._ue4ss.install(tmp_path)
                return install_success, install_msg
            finally:
                Path(tmp_path).unlink(missing_ok=True)
                
        except Exception as e:
            self._last_error = str(e)
            return False, f"安装失败: {str(e)}"
    
    def _install_palschema(self) -> Tuple[bool, str]:
        """Install PalSchema framework using SSL-bypass downloader."""
        try:
            self._report("正在获取 PalSchema 版本信息...", 65)
            
            success, release, err = fetch_json(self.PALSCHEMA_LATEST, timeout=30)
            
            if not success:
                self._last_error = err
                return False, err
            
            tag = release.get('tag_name', 'unknown')
            assets = release.get('assets', [])
            
            if not assets:
                return False, "PalSchema 仓库中未找到任何资源文件"
            
            # Find PalSchema files
            zip_asset = None
            dll_asset = None
            
            for asset in assets:
                name = asset.get('name', '').lower()
                if name.endswith('.zip') and 'palschema' in name:
                    zip_asset = asset
                    break
                elif name.endswith('.dll') and 'palschema' in name:
                    dll_asset = asset
            
            # Try downloading zip
            if zip_asset:
                self._report(f"正在下载 PalSchema v{tag}...", 75)
                
                download_url = zip_asset['browser_download_url']
                
                with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                    tmp_path = tmp.name
                
                try:
                    downloader = SafeDownloader(progress_callback=self._download_progress)
                    success, result = downloader.download(download_url, tmp_path, timeout=300)
                    
                    if not success:
                        self._last_error = result
                        return False, result
                    
                    self._report("正在解压 PalSchema...", 85)
                    self._extract_palschema(tmp_path, tag)
                    return True, f"PalSchema 安装成功 (v{tag})"
                finally:
                    Path(tmp_path).unlink(missing_ok=True)
            
            # Direct DLL download
            elif dll_asset:
                self._report(f"正在下载 PalSchema v{tag}...", 75)
                dll_url = dll_asset['browser_download_url']
                target = self.game_path / "Pal" / "Binaries" / "Win64" / dll_asset['name']
                target.parent.mkdir(parents=True, exist_ok=True)
                
                downloader = SafeDownloader(progress_callback=self._download_progress)
                success, result = downloader.download(dll_url, str(target), timeout=300)
                
                if not success:
                    self._last_error = result
                    return False, result
                
                version_file = target.parent / "Mods" / "PalSchema" / "version.txt"
                version_file.parent.mkdir(parents=True, exist_ok=True)
                version_file.write_text(tag)
                
                return True, f"PalSchema 安装成功 (v{tag})"
            
            return False, "未找到 PalSchema 安装文件 (zip 或 dll)"
                
        except Exception as e:
            self._last_error = str(e)
            return False, f"安装失败: {str(e)}"
    
    def _extract_palschema(self, archive_path: str, version: str):
        """Extract PalSchema files to the correct location.
        PalSchema is a UE4SS mod that lives under Mods/PalSchema/.
        All files (dll, lua, json, etc.) should go there preserving directory structure."""
        mods_palschema = self.game_path / "Pal" / "Binaries" / "Win64" / "Mods" / "PalSchema"
        mods_palschema.mkdir(parents=True, exist_ok=True)
        
        with zipfile.ZipFile(archive_path, 'r') as zf:
            all_members = zf.namelist()
            
            # Check if there's a single root directory (e.g., "PalSchema/")
            root_dirs = set()
            for member in all_members:
                if '/' in member:
                    root_dirs.add(member.split('/')[0])
            
            # If there's a common root dir like "PalSchema", strip it
            strip_root = ""
            if len(root_dirs) == 1:
                strip_root = list(root_dirs)[0] + "/"
            
            for member in all_members:
                if member.endswith('/'):
                    continue
                
                # Get relative path (strip the root dir if present)
                if strip_root and member.startswith(strip_root):
                    rel_path = member[len(strip_root):]
                else:
                    rel_path = member
                
                # ALL files go under Mods/PalSchema/, preserving subdirectories
                subdir = os.path.dirname(rel_path)
                if subdir and subdir != '.':
                    dest = mods_palschema / subdir / os.path.basename(rel_path)
                else:
                    dest = mods_palschema / os.path.basename(rel_path)
                
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(dest, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        
        # Write version file
        (mods_palschema / "version.txt").write_text(version)
    
    def _ensure_directories(self):
        """Ensure all required mod directories exist."""
        dirs = [
            self.game_path / "Pal" / "Binaries" / "Win64" / "Mods",
            self.game_path / "Pal" / "Binaries" / "Win64" / "Mods" / "PalSchema",
            self.game_path / "Pal" / "Content" / "Paks" / "~mods",
            self.game_path / "Pal" / "Binaries" / "Win64" / "ue4ss",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    
    def install_ue4ss_from_archive(self, archive_path: str) -> Tuple[bool, str]:
        """Install UE4SS from a local archive file."""
        return self._ue4ss.install(archive_path)
    
    def install_palschema_from_archive(self, archive_path: str) -> Tuple[bool, str]:
        """Install PalSchema from a local archive file."""
        try:
            self._extract_palschema(archive_path, "local")
            return True, "PalSchema 从本地文件安装成功"
        except Exception as e:
            return False, f"安装失败: {str(e)}"
    
    def uninstall_all(self, include_mods: bool = False) -> Tuple[bool, List[str]]:
        """Uninstall all frameworks and optionally all mods.
        
        Args:
            include_mods: If True, also delete all Mods/ and ~mods/ directories.
        
        Removes:
        - UE4SS directory and proxy DLLs
        - PalSchema directory
        - mods.txt
        - If include_mods: entire Mods/, ~mods/, and LogicMods/ directories
        """
        messages = []
        
        # Uninstall UE4SS
        success, msg = self._ue4ss.uninstall()
        messages.append(f"UE4SS: {msg}")
        
        # Uninstall PalSchema
        palschema_dir = self.game_path / "Pal" / "Binaries" / "Win64" / "Mods" / "PalSchema"
        if palschema_dir.exists():
            try:
                shutil.rmtree(str(palschema_dir))
                messages.append("PalSchema: 已卸载")
            except Exception as e:
                messages.append(f"PalSchema: 卸载失败 - {e}")
        else:
            messages.append("PalSchema: 未安装")
        
        # Optionally remove all mods
        if include_mods:
            mods_dir = self.game_path / "Pal" / "Binaries" / "Win64" / "Mods"
            paks_dir = self.game_path / "Pal" / "Content" / "Paks" / "~mods"
            logicmods_dir = self.game_path / "Pal" / "Content" / "Paks" / "LogicMods"
            
            for d, name in [(mods_dir, "Mods/"), (paks_dir, "~mods/"), (logicmods_dir, "LogicMods/")]:
                if d.exists():
                    try:
                        shutil.rmtree(str(d))
                        messages.append(f"{name}: 已删除")
                    except Exception as e:
                        messages.append(f"{name}: 删除失败 - {e}")
        
        return True, messages
