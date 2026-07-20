"""
UE4SS Integration Service - manages UE4SS framework installation, configuration, and updates.
UE4SS (Unreal Engine 4/5 Scripting System) is the core modding framework for Palworld.
"""
import os
import json
import shutil
import zipfile
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from datetime import datetime
import hashlib
import socket

# Set longer socket timeout
socket.setdefaulttimeout(60)

# Import the network utilities for SSL bypass
try:
    from ..utils.network import SafeDownloader, fetch_json, make_ssl_context, install_certifi_if_missing
    install_certifi_if_missing()
except ImportError:
    SafeDownloader = None
    fetch_json = None


class UE4SSService:
    """Manages UE4SS framework installation and configuration."""
    
    # UE4SS GitHub releases URL
    RELEASES_API = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases"
    LATEST_RELEASE = "https://api.github.com/repos/UE4SS-RE/RE-UE4SS/releases/latest"
    
    # Configuration files
    UE4SS_SETTINGS = "UE4SS-settings.ini"
    MODS_TXT = "mods.txt"
    
    # Key configuration paths relative to game directory
    RELATIVE_UE4SS_PATH = "Pal/Binaries/Win64/ue4ss"
    RELATIVE_MODS_PATH = "Pal/Binaries/Win64/Mods"
    
    def __init__(self, game_path: str):
        self.game_path = Path(game_path)
        self._ue4ss_path = self.game_path / self.RELATIVE_UE4SS_PATH
        self._mods_path = self.game_path / self.RELATIVE_MODS_PATH
    
    @property
    def ue4ss_dir(self) -> Path:
        return self._ue4ss_path
    
    @property
    def mods_dir(self) -> Path:
        return self._mods_path
    
    def is_installed(self) -> bool:
        """Check if UE4SS is installed. Considers installed if any UE4SS component exists."""
        game_bin = self.game_path / "Pal" / "Binaries" / "Win64"
        
        # Check for UE4SS.dll in multiple locations
        dll_locations = [
            game_bin / "UE4SS.dll",
            game_bin / "ue4ss" / "UE4SS.dll",
        ]
        
        has_ue4ss_dll = any(p.exists() for p in dll_locations)
        
        # Check for proxy/injection DLLs
        # UE4SS v2.x uses xinput1_3.dll or version.dll
        # UE4SS v3.x uses dwmapi.dll
        proxy_locations = [
            game_bin / "xinput1_3.dll",
            game_bin / "version.dll",
            game_bin / "dsound.dll",
            game_bin / "dinput8.dll",
            game_bin / "dwmapi.dll",
        ]
        
        has_proxy_dll = any(p.exists() for p in proxy_locations)
        
        # Also check the ue4ss directory itself
        has_ue4ss_dir = (game_bin / "ue4ss").exists() and (game_bin / "ue4ss").is_dir()
        
        # Consider installed if: both DLL+proxy exist, OR if the ue4ss directory exists
        return (has_ue4ss_dll and has_proxy_dll) or has_ue4ss_dir
    
    def get_version(self) -> Optional[str]:
        """Get the installed UE4SS version."""
        version_file = self._ue4ss_path / "VERSION"
        if version_file.exists():
            try:
                return version_file.read_text().strip()
            except Exception:
                pass
        
        # Try to read from changelog
        changelog = self._ue4ss_path / "changelog.md"
        if changelog.exists():
            try:
                content = changelog.read_text()
                import re
                match = re.search(r'##\s*(\d+\.\d+\.\d+)', content)
                if match:
                    return match.group(1)
            except Exception:
                pass
        
        return None
    
    def install(self, archive_path: Optional[str] = None) -> Tuple[bool, str]:
        """Install UE4SS from a local archive or download latest."""
        try:
            if archive_path and Path(archive_path).exists():
                return self._install_from_archive(archive_path)
            else:
                return self._install_latest()
        except Exception as e:
            return False, str(e)
    
    def _install_from_archive(self, archive_path: str) -> Tuple[bool, str]:
        """Install UE4SS from a local zip archive."""
        archive = Path(archive_path)
        
        if not archive.exists():
            return False, f"Archive not found: {archive_path}"
        
        try:
            # Create temp extraction directory
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                
                with zipfile.ZipFile(archive, 'r') as zf:
                    zf.extractall(tmp)
                
                # Find the UE4SS root in extracted files
                ue4ss_root = self._find_ue4ss_root(tmp)
                if not ue4ss_root:
                    return False, "Could not find UE4SS files in archive"
                
                # Copy files to game directory
                self._copy_ue4ss_files(ue4ss_root)
                
                return True, "UE4SS installed successfully"
        except Exception as e:
            return False, f"Installation failed: {str(e)}"
    
    def _install_latest(self) -> Tuple[bool, str]:
        """Download and install the latest UE4SS release."""
        try:
            # Get latest release info using SSL-bypass fetcher
            if fetch_json is None:
                return False, "网络工具模块不可用"
            
            success, release, err = fetch_json(self.LATEST_RELEASE, timeout=30)
            if not success:
                return False, err
            
            assets = release.get('assets', [])
            
            # Find the appropriate zip
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
            
            # Download the zip using SSL-bypass downloader
            download_url = zip_asset['browser_download_url']
            
            with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
                tmp_path = tmp.name
            
            try:
                downloader = SafeDownloader()
                success, result = downloader.download(download_url, tmp_path, timeout=600)
                
                if not success:
                    return False, result
                
                return self._install_from_archive(tmp_path)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
                
        except Exception as e:
            return False, f"下载失败: {str(e)}"
    
    def uninstall(self) -> Tuple[bool, str]:
        """Uninstall UE4SS completely, restoring game directory to pre-UE4SS state."""
        removed = []
        errors = []
        game_bin = self.game_path / "Pal" / "Binaries" / "Win64"
        
        try:
            # Remove UE4SS directory
            if self._ue4ss_path.exists():
                shutil.rmtree(self._ue4ss_path)
                removed.append("ue4ss/")
            
            # Remove all known proxy/injection DLLs
            dll_files = [
                'xinput1_3.dll', 'version.dll', 'dsound.dll', 'dinput8.dll',
                'dwmapi.dll',  # UE4SS v3.x
            ]
            for dll in dll_files:
                dll_path = game_bin / dll
                if dll_path.exists():
                    dll_path.unlink()
                    removed.append(dll)
            
            # Remove UE4SS.dll if directly in Binaries/Win64
            ue4ss_dll = game_bin / "UE4SS.dll"
            if ue4ss_dll.exists():
                ue4ss_dll.unlink()
                removed.append("UE4SS.dll")
            
            # Remove UE4SS.log if exists
            log_file = game_bin / "UE4SS.log"
            if log_file.exists():
                log_file.unlink()
            
            # Remove UE4SS-settings.ini from Win64 root if exists
            settings_file = game_bin / "UE4SS-settings.ini"
            if settings_file.exists():
                settings_file.unlink()
            
            # Remove mods.txt if exists (generated by UE4SS)
            mods_txt = game_bin / "Mods" / "mods.txt"
            if mods_txt.exists():
                mods_txt.unlink()
            
            if removed:
                return True, f"UE4SS 已卸载，删除: {', '.join(removed)}"
            return True, "UE4SS 未检测到文件"
        except Exception as e:
            return False, f"卸载失败: {str(e)}"
    
    def get_settings(self) -> Dict:
        """Read UE4SS settings from UE4SS-settings.ini."""
        settings_file = self._ue4ss_path / self.UE4SS_SETTINGS
        
        if not settings_file.exists():
            return self._get_default_settings()
        
        settings = {}
        try:
            content = settings_file.read_text(encoding='utf-8')
            current_section = 'General'
            
            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith(';') or line.startswith('#'):
                    continue
                
                if line.startswith('[') and line.endswith(']'):
                    current_section = line[1:-1]
                    if current_section not in settings:
                        settings[current_section] = {}
                    continue
                
                if '=' in line:
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip()
                    
                    if current_section not in settings:
                        settings[current_section] = {}
                    
                    # Try to convert to appropriate type
                    settings[current_section][key] = self._parse_value(value)
        except Exception:
            return self._get_default_settings()
        
        return settings
    
    def save_settings(self, settings: Dict) -> bool:
        """Save UE4SS settings to UE4SS-settings.ini."""
        settings_file = self._ue4ss_path / self.UE4SS_SETTINGS
        
        lines = []
        lines.append("; UE4SS Settings - Managed by 帕鲁Mod管理器")
        lines.append("; Last updated: " + datetime.now().isoformat())
        lines.append("")
        
        for section, values in settings.items():
            lines.append(f"[{section}]")
            for key, value in values.items():
                if isinstance(value, bool):
                    value = 'true' if value else 'false'
                lines.append(f"{key} = {value}")
            lines.append("")
        
        try:
            settings_file.write_text('\n'.join(lines), encoding='utf-8')
            return True
        except Exception:
            return False
    
    def configure_for_palworld(self) -> bool:
        """Apply recommended UE4SS settings for Palworld."""
        settings = self.get_settings()
        
        # UE4SS settings optimized for Palworld
        ue4ss_config = {
            'General': {
                'EnableLogging': True,
                'ConsoleEnabled': False,
                'GuiConsoleEnabled': True,
                'GuiConsoleVisible': False,
            },
            'Debug': {
                'EnableDebugger': False,
                'EnableStackTrace': False,
            },
            'Mods': {
                'EnableAllMods': True,
                'ModsFolderPath': str(self._mods_path),
            },
            'Lua': {
                'EnableLuaMods': True,
                'LuaModPath': str(self._mods_path),
            },
            'BPModLoader': {
                'EnableBPMods': True,
                'BPModsPath': str(self._mods_path),
            },
        }
        
        # Merge with existing settings
        for section, values in ue4ss_config.items():
            if section not in settings:
                settings[section] = {}
            settings[section].update(values)
        
        return self.save_settings(settings)
    
    def update_mods_txt(self, enabled_mods: List[str]) -> bool:
        """Update mods.txt with the list of enabled mods."""
        mods_txt = self._mods_path / self.MODS_TXT
        
        lines = [
            "# 帕鲁Mod管理器 - Auto-generated mods.txt",
            f"# Last updated: {datetime.now().isoformat()}",
            "",
        ]
        
        for mod_name in enabled_mods:
            lines.append(f"{mod_name} : 1")
        
        try:
            mods_txt.write_text('\n'.join(lines) + '\n', encoding='utf-8')
            return True
        except Exception:
            return False
    
    def get_log_path(self) -> Optional[Path]:
        """Get the path to UE4SS log file."""
        log_path = self._ue4ss_path / "UE4SS.log"
        if log_path.exists():
            return log_path
        return None
    
    def get_recent_logs(self, lines: int = 50) -> str:
        """Get the most recent lines from the UE4SS log."""
        log_path = self.get_log_path()
        if not log_path:
            return ""
        
        try:
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                all_lines = f.readlines()
                return ''.join(all_lines[-lines:])
        except Exception:
            return ""
    
    # ---- Internal helpers ----
    
    def _find_ue4ss_root(self, extract_dir: Path) -> Optional[Path]:
        """Find the UE4SS root directory within extracted files."""
        # Check if extract_dir itself contains UE4SS.dll
        if (extract_dir / "UE4SS.dll").exists():
            return extract_dir
        
        # Search up to 3 levels deep
        candidates = [extract_dir]
        for _ in range(3):
            new_candidates = []
            for d in candidates:
                if not d.is_dir():
                    continue
                for item in d.iterdir():
                    if item.is_dir():
                        if (item / "UE4SS.dll").exists():
                            return item
                        new_candidates.append(item)
            candidates = new_candidates
        
        # Fallback: find any directory containing UE4SS.dll
        for root, dirs, files in os.walk(str(extract_dir)):
            if "UE4SS.dll" in files:
                return Path(root)
        
        return None
    
    def _copy_ue4ss_files(self, source: Path):
        """Copy UE4SS files to the game directory."""
        game_bin = self.game_path / "Pal" / "Binaries" / "Win64"
        game_bin.mkdir(parents=True, exist_ok=True)
        
        # Strategy: walk the source tree and copy EVERYTHING to game_bin,
        # preserving the relative structure
        
        for root, dirs, files in os.walk(str(source)):
            root_path = Path(root)
            rel_path = root_path.relative_to(source)
            
            # Determine target directory
            target_dir = game_bin / rel_path
            
            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Copy all files
            for file in files:
                src_file = root_path / file
                dst_file = target_dir / file
                
                # Skip if destination exists (don't overwrite existing mods)
                if dst_file.exists() and file.endswith('.lua'):
                    continue
                
                try:
                    shutil.copy2(src_file, dst_file)
                except Exception:
                    pass
    
    def _parse_value(self, value: str):
        """Parse a string value to appropriate Python type."""
        value_lower = value.lower()
        if value_lower == 'true':
            return True
        elif value_lower == 'false':
            return False
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
    
    def _get_default_settings(self) -> Dict:
        """Get default UE4SS settings."""
        return {
            'General': {
                'EnableLogging': True,
                'ConsoleEnabled': False,
                'GuiConsoleEnabled': True,
                'GuiConsoleVisible': False,
            },
            'Mods': {
                'EnableAllMods': True,
            },
        }
