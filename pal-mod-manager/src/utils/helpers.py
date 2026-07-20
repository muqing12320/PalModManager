"""
Utility helper functions for the 帕鲁Mod管理器.
"""
import os
import re
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime


def _find_steam_install_path() -> Optional[Path]:
    """Find Steam installation path via registry or common locations."""
    # Method 1: Windows Registry
    try:
        import winreg
        for reg_path in [
            r"SOFTWARE\Valve\Steam",
            r"SOFTWARE\WOW6432Node\Valve\Steam",
        ]:
            try:
                key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, reg_path)
                steam_path, _ = winreg.QueryValueEx(key, "InstallPath")
                winreg.CloseKey(key)
                p = Path(steam_path)
                if p.exists():
                    return p
            except OSError:
                continue
    except Exception:
        pass
    
    # Method 2: Common locations
    common_locations = [
        Path("C:/Program Files (x86)/Steam"),
        Path("D:/Steam"),
        Path("E:/Steam"),
        Path("F:/Steam"),
        Path("G:/Steam"),
    ]
    for loc in common_locations:
        if loc.exists():
            return loc
    
    return None


def _get_steam_library_folders(steam_path: Path) -> List[Path]:
    """Get all Steam library folders."""
    libraries = [steam_path]  # Default library is Steam install dir itself
    
    vdf_path = steam_path / "steamapps" / "libraryfolders.vdf"
    if not vdf_path.exists():
        return libraries
    
    try:
        content = vdf_path.read_text(encoding='utf-8')
        
        # Steam VDF format uses escaped backslashes in paths
        # Example: "path"		"D:\\\\SteamLibrary"
        for match in re.finditer(r'"path"\s+"([^"]+)"', content):
            raw_path = match.group(1)
            # Unescape double backslashes
            raw_path = raw_path.replace('\\\\', '\\')
            lib_path = Path(raw_path)
            if lib_path.exists() and lib_path not in libraries:
                libraries.append(lib_path)
    except Exception:
        pass
    
    return libraries


def find_palworld_installation() -> Optional[str]:
    """Auto-detect Palworld installation directory using multiple strategies."""
    possible_paths = []
    checked = set()
    
    def add_path(p: Path):
        """Add a candidate path if not already checked."""
        key = str(p).lower()
        if key not in checked:
            checked.add(key)
            possible_paths.append(p)
    
    if platform.system() == "Windows":
        # ---- Strategy 1: Find via Steam + libraryfolders.vdf ----
        steam_path = _find_steam_install_path()
        if steam_path:
            libraries = _get_steam_library_folders(steam_path)
            for lib in libraries:
                add_path(lib / "steamapps" / "common" / "Palworld")
        
        # ---- Strategy 2: Scan appmanifest files for Palworld AppID (1623730) ----
        # Check all known library folders' steamapps directories
        manifest_dirs = []
        if steam_path:
            for lib in _get_steam_library_folders(steam_path):
                manifest_dirs.append(lib / "steamapps")
        # Also check common locations
        for loc in [Path("C:/Program Files (x86)/Steam/steamapps"),
                    Path("D:/Steam/steamapps"),
                    Path("E:/Steam/steamapps")]:
            if loc.exists() and loc not in manifest_dirs:
                manifest_dirs.append(loc)
        
        for manifest_dir in manifest_dirs:
            if not manifest_dir.exists():
                continue
            for manifest in manifest_dir.glob("appmanifest_*.acf"):
                try:
                    content = manifest.read_text(encoding='utf-8', errors='ignore')
                    # Palworld AppID is 1623730
                    if '"appid"\\s+"1623730"' not in content and '1623730' not in content:
                        # Also check by name
                        if 'Palworld' not in content:
                            continue
                    
                    # Extract install dir name
                    dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                    if dir_match:
                        install_dir = dir_match.group(1)
                        # The library path is the parent of steamapps
                        lib_path = manifest_dir.parent
                        pal_path = lib_path / "steamapps" / "common" / install_dir
                        add_path(pal_path)
                except Exception:
                    continue
        
        # ---- Strategy 3: Common hardcoded paths as fallback ----
        fallback_paths = [
            Path("C:/Program Files (x86)/Steam/steamapps/common/Palworld"),
            Path("D:/Steam/steamapps/common/Palworld"),
            Path("E:/Steam/steamapps/common/Palworld"),
            Path("F:/Steam/steamapps/common/Palworld"),
            Path("G:/Steam/steamapps/common/Palworld"),
            Path(os.path.expanduser("~")) / "Steam/steamapps/common/Palworld",
            # Xbox Game Pass
            Path("C:/XboxGames/Palworld/Content"),
            Path("D:/XboxGames/Palworld/Content"),
            Path("E:/XboxGames/Palworld/Content"),
        ]
        for p in fallback_paths:
            add_path(p)
        
        # ---- Strategy 4: Quick scan common game drives for Palworld folder ----
        for drive_letter in ['C', 'D', 'E', 'F', 'G']:
            # Check SteamLibrary/steamapps/common/Palworld pattern (common for additional libraries)
            steam_lib = Path(f"{drive_letter}:/SteamLibrary/steamapps/common/Palworld")
            add_path(steam_lib)
    
    # Verify all collected paths
    for path in possible_paths:
        if is_valid_palworld_path(str(path)):
            return str(path)
    
    return None


def is_valid_palworld_path(path: str) -> bool:
    """Check if a path appears to be a valid Palworld installation."""
    p = Path(path)
    
    if not p.exists():
        return False
    
    # Check for key Palworld files
    indicators = [
        p / "Palworld.exe",
        p / "Pal" / "Binaries" / "Win64" / "Palworld-Win64-Shipping.exe",
        p / "Pal" / "Content" / "Paks" / "Pal-Windows.pak",
    ]
    
    # At least one indicator should exist
    return any(indicator.exists() for indicator in indicators)


def is_valid_palserver_path(path: str) -> bool:
    """Check if a path appears to be a valid PalServer installation."""
    p = Path(path)
    
    if not p.exists():
        return False
    
    # Check for key PalServer files
    indicators = [
        p / "PalServer.exe",
        p / "Pal" / "Binaries" / "Win64" / "PalServer-Win64-Shipping.exe",
        p / "Pal" / "Content" / "Paks" / "Pal-WindowsServer.pak",
    ]
    
    return any(indicator.exists() for indicator in indicators)


def find_palserver_installation() -> Optional[str]:
    """Auto-detect PalServer installation directory."""
    possible_paths = []
    checked = set()
    
    def add_path(p: Path):
        key = str(p).lower()
        if key not in checked:
            checked.add(key)
            possible_paths.append(p)
    
    if platform.system() == "Windows":
        # Strategy 1: Via Steam library folders
        steam_path = _find_steam_install_path()
        if steam_path:
            for lib in _get_steam_library_folders(steam_path):
                add_path(lib / "steamapps" / "common" / "PalServer")
        
        # Strategy 2: Scan appmanifest for PalServer (AppID 2394010)
        manifest_dirs = []
        if steam_path:
            for lib in _get_steam_library_folders(steam_path):
                manifest_dirs.append(lib / "steamapps")
        for loc in [Path("C:/Program Files (x86)/Steam/steamapps"),
                    Path("D:/Steam/steamapps"),
                    Path("E:/Steam/steamapps")]:
            if loc.exists() and loc not in manifest_dirs:
                manifest_dirs.append(loc)
        
        for manifest_dir in manifest_dirs:
            if not manifest_dir.exists():
                continue
            for manifest in manifest_dir.glob("appmanifest_*.acf"):
                try:
                    content = manifest.read_text(encoding='utf-8', errors='ignore')
                    if 'PalServer' not in content and '2394010' not in content:
                        continue
                    dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                    if dir_match:
                        lib_path = manifest_dir.parent
                        pal_path = lib_path / "steamapps" / "common" / dir_match.group(1)
                        add_path(pal_path)
                except Exception:
                    continue
        
        # Strategy 3: Common paths
        for drive in ['C', 'D', 'E', 'F', 'G']:
            add_path(Path(f"{drive}:/SteamLibrary/steamapps/common/PalServer"))
            add_path(Path(f"{drive}:/Program Files (x86)/Steam/steamapps/common/PalServer"))
    
    for path in possible_paths:
        if is_valid_palserver_path(str(path)):
            return str(path)
    
    return None


def get_game_version(game_path: str) -> Optional[str]:
    """Get the installed Palworld game version."""
    p = Path(game_path)
    
    # Try to find the corresponding appmanifest by scanning all Steam library folders
    steam_path = _find_steam_install_path()
    manifest_dirs = []
    if steam_path:
        for lib in _get_steam_library_folders(steam_path):
            md = lib / "steamapps"
            if md.exists():
                manifest_dirs.append(md)
    
    # Also add common locations
    for loc in [Path("C:/Program Files (x86)/Steam/steamapps"),
                Path("D:/Steam/steamapps"),
                Path("E:/Steam/steamapps")]:
        if loc.exists() and loc not in manifest_dirs:
            manifest_dirs.append(loc)
    
    for manifest_dir in manifest_dirs:
        for manifest in manifest_dir.glob("appmanifest_*.acf"):
            try:
                content = manifest.read_text(encoding='utf-8', errors='ignore')
                
                # Check if this manifest corresponds to our game path
                dir_match = re.search(r'"installdir"\s+"([^"]+)"', content)
                if not dir_match:
                    continue
                
                install_dir = dir_match.group(1)
                if install_dir != p.name:
                    continue
                
                # Must also be Palworld (AppID 1623730)
                if 'Palworld' not in content and '1623730' not in content:
                    continue
                
                # Extract build ID
                build_match = re.search(r'"buildid"\s+"(\d+)"', content)
                if build_match:
                    return f"Build {build_match.group(1)}"
            except Exception:
                continue
    
    # Fallback: try from game executable timestamp
    exe = p / "Pal" / "Binaries" / "Win64" / "Palworld-Win64-Shipping.exe"
    if not exe.exists():
        exe = p / "Palworld.exe"
    
    if exe.exists():
        try:
            mtime = os.path.getmtime(str(exe))
            return f"Build {datetime.fromtimestamp(mtime).strftime('%Y%m%d')}"
        except Exception:
            pass
    
    return None


def compute_file_hash(file_path: str, algorithm: str = 'md5') -> Optional[str]:
    """Compute hash of a file."""
    try:
        h = hashlib.new(algorithm)
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def format_size(size_bytes: int) -> str:
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def format_date(iso_string: str) -> str:
    """Format ISO date string to readable format."""
    try:
        dt = datetime.fromisoformat(iso_string)
        return dt.strftime('%Y-%m-%d %H:%M')
    except Exception:
        return iso_string


def safe_filename(name: str) -> str:
    """Convert a string to a safe filename."""
    # Replace invalid characters
    invalid = '<>:"/\\|?*'
    for c in invalid:
        name = name.replace(c, '_')
    # Trim whitespace and dots
    name = name.strip('. ')
    return name or 'unnamed'


def get_mod_type_icon(mod_type: str) -> str:
    """Get an icon name for a mod type."""
    icons = {
        'ue4ss_lua': '📜',
        'ue4ss_bp': '🔷',
        'pak': '📦',
        'palschema': '⚙️',
        'logic_mod': '🧩',
        'unknown': '❓',
    }
    return icons.get(mod_type, '📄')


def get_mod_type_display(mod_type: str) -> str:
    """Get display name for a mod type."""
    names = {
        'ue4ss_lua': 'UE4SS Lua脚本',
        'ue4ss_bp': 'UE4SS 蓝图',
        'pak': 'PAK Mod',
        'palschema': 'PalSchema 配置',
        'logic_mod': 'LogicMod',
        'unknown': '未知类型',
    }
    return names.get(mod_type, mod_type)


def get_status_display(status: str) -> str:
    """Get display name for a mod status."""
    names = {
        'enabled': '已启用',
        'disabled': '已禁用',
        'conflict': '冲突',
        'error': '错误',
        'unknown': '未知',
    }
    return names.get(status, status)


def get_status_color(status: str) -> str:
    """Get color for a mod status."""
    colors = {
        'enabled': '#4CAF50',
        'disabled': '#9E9E9E',
        'conflict': '#FF9800',
        'error': '#F44336',
        'unknown': '#757575',
    }
    return colors.get(status, '#757575')


def launch_game(game_path: str, args: List[str] = None) -> Tuple[bool, str]:
    """Launch Palworld with optional arguments."""
    if not is_valid_palworld_path(game_path):
        return False, "无效的游戏路径"
    
    p = Path(game_path)
    
    # Find the executable
    exe_paths = [
        p / "Palworld.exe",
        p / "Pal" / "Binaries" / "Win64" / "Palworld-Win64-Shipping.exe",
    ]
    
    exe = None
    for ep in exe_paths:
        if ep.exists():
            exe = ep
            break
    
    if not exe:
        return False, "未找到游戏可执行文件"
    
    try:
        cmd = [str(exe)]
        if args:
            cmd.extend(args)
        
        subprocess.Popen(cmd, cwd=str(p))
        return True, "游戏已启动"
    except Exception as e:
        return False, f"启动失败: {str(e)}"


def launch_palserver(server_path: str, args: List[str] = None) -> Tuple[bool, str]:
    """Launch PalServer with optional arguments."""
    if not is_valid_palserver_path(server_path):
        return False, "无效的服务器路径"
    
    p = Path(server_path)
    
    exe_paths = [
        p / "PalServer.exe",
        p / "Pal" / "Binaries" / "Win64" / "PalServer-Win64-Shipping-Cmd.exe",
        p / "Pal" / "Binaries" / "Win64" / "PalServer-Win64-Shipping.exe",
    ]
    
    exe = None
    for ep in exe_paths:
        if ep.exists():
            exe = ep
            break
    
    if not exe:
        return False, "未找到服务器可执行文件"
    
    try:
        cmd = [str(exe)]
        if args:
            cmd.extend(args)
        
        subprocess.Popen(cmd, cwd=str(p))
        return True, "服务器已启动"
    except Exception as e:
        return False, f"启动失败: {str(e)}"
