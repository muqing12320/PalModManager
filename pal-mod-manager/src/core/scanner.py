"""
Mod Scanner - scans game directories and discovers installed mods.
Detects UE4SS Lua mods, .pak mods, PalSchema configs, and LogicMods.
"""
import os
import json
import yaml
import re
import hashlib
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path

from .models import ModInfo, ModType, ModStatus


class ModScanner:
    """Scans the Palworld game directory for installed mods."""
    
    # Known mod metadata files
    METADATA_FILES = ['mod.json', 'mod.yml', 'mod.yaml', 'mod.toml', 'meta.json', '.modinfo']
    
    # File extensions for different mod types
    PAK_EXTENSIONS = ('.pak',)
    LUA_EXTENSIONS = ('.lua',)
    PALSCHEMA_CONFIG_DIRS = ['PalSchema', 'configs', 'Config']
    
    # UE4SS built-in mod directories (ship with UE4SS itself, not user mods)
    UE4SS_BUILTIN_MODS = {
        'actordumpermod', 'bpmodloadermod', 'cheatmanagerenablermod',
        'consolecommandsmod', 'consoleenablermod', 'jsbluaprofilermod',
        'linetracemod', 'splitscreenmod', 'keybinds', 'shared',
        'palschema', 'ue4ss',
        # BPML_GenericFunctions is a sub-module of BPModLoaderMod
        'bpml_genericfunctions',
        # Common framework sub-dirs
        'dumper', 'console', 'debug', 'helper', 'utils', 'common', 'scripts',
    }
    
    def __init__(self, game_path: str):
        self.game_path = Path(game_path)
        self._validate_game_path()
    
    def _validate_game_path(self):
        """Ensure the game path looks valid."""
        if not self.game_path.exists():
            raise FileNotFoundError(f"Game path does not exist: {self.game_path}")
        
        # Check for Palworld executable
        exe_path = self.game_path / "Palworld.exe"
        pal_exe = self.game_path / "Pal" / "Binaries" / "Win64" / "Palworld-Win64-Shipping.exe"
        if not exe_path.exists() and not pal_exe.exists():
            # Don't raise, just warn - user might have custom setup
            pass
    
    @property
    def mods_dir(self) -> Path:
        """Get the Mods directory path."""
        return self.game_path / "Pal" / "Binaries" / "Win64" / "Mods"
    
    @property
    def logic_mods_dir(self) -> Path:
        """Get the LogicMods directory path."""
        return self.game_path / "Pal" / "Binaries" / "Win64" / "Mods"
    
    @property
    def ue4ss_dir(self) -> Path:
        """Get the UE4SS directory path."""
        return self.game_path / "Pal" / "Binaries" / "Win64" / "ue4ss"
    
    @property
    def palschema_dir(self) -> Path:
        """Get the PalSchema config directory."""
        return self.game_path / "Pal" / "Binaries" / "Win64" / "Mods" / "PalSchema"
    
    @property
    def paks_dir(self) -> Path:
        """Get the ~mods directory for .pak files."""
        return self.game_path / "Pal" / "Content" / "Paks" / "~mods"
    
    @property
    def logicmods_paks_dir(self) -> Path:
        """Get the LogicMods directory for logic .pak files."""
        return self.game_path / "Pal" / "Content" / "Paks" / "LogicMods"
    
    def scan_all(self) -> List[ModInfo]:
        """Run all scanners and return combined results."""
        mods = []
        mods.extend(self.scan_ue4ss_lua_mods())
        mods.extend(self.scan_logic_mods())
        mods.extend(self.scan_pak_mods())
        mods.extend(self.scan_logicmods_paks())
        mods.extend(self.scan_palschema_mods())
        return self._deduplicate_mods(mods)
    
    def scan_ue4ss_lua_mods(self) -> List[ModInfo]:
        """Scan for UE4SS Lua script mods in the Mods directory.
        Excludes UE4SS built-in modules and framework directories."""
        mods = []
        mods_dir = self.mods_dir
        
        if not mods_dir.exists():
            return mods
        
        for item in mods_dir.iterdir():
            if not item.is_dir():
                continue
            
            # Skip UE4SS built-in modules and framework directories
            if item.name.lower() in self.UE4SS_BUILTIN_MODS:
                continue
            
            mod_info = self._scan_lua_mod_directory(item)
            if mod_info:
                mods.append(mod_info)
        
        return mods
    
    def scan_logic_mods(self) -> List[ModInfo]:
        """Scan for LogicMods."""
        mods = []
        mods_dir = self.mods_dir
        
        if not mods_dir.exists():
            return mods
        
        for item in mods_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.lower().startswith('logicmod') or item.name.lower().startswith('logic_mod'):
                mod_info = self._scan_logic_mod_directory(item)
                if mod_info:
                    mods.append(mod_info)
        
        return mods
    
    def scan_pak_mods(self) -> List[ModInfo]:
        """Scan for .pak mod files. The disabled state of a pak is determined
        by checking for the corresponding .pak_disabled marker file, not by
        scanning it as a separate mod."""
        mods = []
        paks_dir = self.paks_dir
        
        if not paks_dir.exists():
            return mods
        
        # Track which base names have a .pak (so .pak_disabled of the same name is ignored)
        seen_stems = set()
        
        for item in paks_dir.iterdir():
            if not item.is_file():
                continue
            
            name_lower = item.name.lower()
            
            # Only scan actual .pak files, NOT .pak_disabled
            # .pak_disabled is the disabled state of a .pak, not a separate mod
            if not name_lower.endswith('.pak'):
                continue
            
            # Skip patches and base game files
            stem_lower = item.stem.lower()
            if 'pal-windows' in stem_lower or stem_lower.startswith('pakchunk'):
                continue
            
            seen_stems.add(stem_lower)
            mod_info = self._scan_pak_file(item)
            if mod_info:
                mods.append(mod_info)
        
        # Now also scan for orphaned .pak_disabled (no corresponding .pak)
        # These represent a disabled mod that we should still show
        for item in paks_dir.iterdir():
            if not item.is_file():
                continue
            
            name_lower = item.name.lower()
            if not name_lower.endswith('.pak_disabled'):
                continue
            
            # The base stem of "foo.pak_disabled" is "foo" (Path.stem removes last suffix)
            stem = item.name[:-len('.pak_disabled')]  # strip the .pak_disabled suffix
            if stem.lower() in seen_stems:
                continue  # Already handled by the .pak file
            
            mod_info = self._scan_pak_file(item)
            if mod_info:
                mods.append(mod_info)
        
        return mods
    
    def scan_logicmods_paks(self) -> List[ModInfo]:
        """Scan for .pak mod files installed in the LogicMods directory."""
        mods = []
        logicmods_dir = self.logicmods_paks_dir
        
        if not logicmods_dir.exists():
            return mods
        
        seen_stems = set()
        
        for item in logicmods_dir.iterdir():
            if not item.is_file():
                continue
            
            name_lower = item.name.lower()
            if not name_lower.endswith('.pak'):
                continue
            
            stem = item.stem.lower()
            seen_stems.add(stem)
            mod_info = self._scan_pak_file(item)
            if mod_info:
                mod_info.mod_type = ModType.LOGIC  # Mark as logic mod
                mods.append(mod_info)
        
        # Also scan .pak_disabled variants
        for item in logicmods_dir.iterdir():
            if not item.is_file():
                continue
            name_lower = item.name.lower()
            if not name_lower.endswith('.pak_disabled'):
                continue
            stem = item.name[:-len('.pak_disabled')].lower()
            if stem in seen_stems:
                continue
            mod_info = self._scan_pak_file(item)
            if mod_info:
                mod_info.mod_type = ModType.LOGIC
                mods.append(mod_info)
        
        return mods
    
    def scan_palschema_mods(self) -> List[ModInfo]:
        """Scan for PalSchema configuration mods."""
        mods = []
        
        # Check PalSchema mods directory
        ps_dir = self.palschema_dir
        if not ps_dir.exists():
            # Also check alternative locations
            alt_dir = self.mods_dir / "PalSchema"
            if alt_dir.exists():
                ps_dir = alt_dir
            else:
                return mods
        
        for item in ps_dir.iterdir():
            if not item.is_dir():
                continue
            
            # Look for config files inside
            config_files = list(item.glob('*.json')) + list(item.glob('*.yml')) + list(item.glob('*.yaml'))
            if config_files:
                mod_info = self._scan_palschema_mod_directory(item, config_files)
                if mod_info:
                    mods.append(mod_info)
        
        return mods
    
    def _scan_lua_mod_directory(self, directory: Path) -> Optional[ModInfo]:
        """Scan a Lua mod directory and extract metadata."""
        mod_id = hashlib.md5(str(directory).encode()).hexdigest()[:12]
        
        # Try to read metadata
        metadata = self._read_metadata_files(directory)
        
        # Find main Lua script
        lua_files = list(directory.glob('*.lua'))
        main_script = ""
        enabled_scripts = []
        
        for lf in lua_files:
            enabled_scripts.append(lf.name)
            if lf.stem.lower() == 'main' or lf.stem.lower() == directory.name.lower():
                main_script = str(lf)
        
        if not main_script and enabled_scripts:
            main_script = str(enabled_scripts[0])
        
        # Check if disabled (renamed with _disabled suffix or in disabled folder)
        is_disabled = any(
            d.name.lower().endswith('_disabled') or 
            'disabled' in d.name.lower()
            for d in [directory] + list(directory.parents)
        )
        
        # Check for enable.txt or disable.txt marker files
        enable_file = directory / "enabled.txt"
        disable_file = directory / "disabled.txt"
        if enable_file.exists():
            is_disabled = False
        elif disable_file.exists():
            is_disabled = True
        
        name = metadata.get('name', directory.name)
        version = metadata.get('version', '1.0.0')
        author = metadata.get('author', 'Unknown')
        description = metadata.get('description', '')
        dependencies = metadata.get('dependencies', [])
        website = metadata.get('website', metadata.get('url', ''))
        tags = metadata.get('tags', [])
        
        # Auto-read usage instructions if description is empty
        if not description:
            description = self._read_usage_instructions(directory)
        
        return ModInfo(
            id=mod_id,
            name=name,
            version=version,
            author=author,
            description=description,
            mod_type=ModType.UE4SS_LUA,
            status=ModStatus.DISABLED if is_disabled else ModStatus.ENABLED,
            install_path=str(directory),
            source_path=str(directory),
            dependencies=dependencies if isinstance(dependencies, list) else [],
            required_frameworks=['UE4SS'],
            ue4ss_main_script=main_script,
            ue4ss_enabled_scripts=enabled_scripts,
            website=website,
            tags=tags if isinstance(tags, list) else [],
            installed_date=datetime.fromtimestamp(directory.stat().st_ctime).isoformat(),
            last_updated=datetime.fromtimestamp(directory.stat().st_mtime).isoformat(),
            raw_metadata=metadata,
        )
    
    def _read_usage_instructions(self, directory: Path, mod_name: str = None) -> str:
        """Read usage instructions from 使用说明.txt, README.md, etc.
        If mod_name is provided, only match files specifically for that mod
        (e.g. 'NoBuildingCost_P_使用说明.txt' for 'NoBuildingCost_P.pak').
        Generic fallback is only used when mod_name is NOT provided
        (for UE4SS mod directories where one 使用说明.txt describes one mod).
        """
        if not directory.is_dir():
            return ""
        
        # First, look for mod-specific instruction files (only when mod_name provided)
        if mod_name:
            for f in directory.iterdir():
                if f.is_file():
                    lower = f.name.lower()
                    # Only match text files (skip .pak, .json, etc.)
                    if not lower.endswith(('.txt', '.md')):
                        continue
                    if lower.startswith(mod_name.lower()) and ('说明' in f.name or '使用' in f.name or 'readme' in lower or '指南' in f.name):
                        return self._read_and_trim(f)
            # When mod_name is provided, do NOT fall back to generic files
            # (otherwise all PAK mods in the same directory share the first mod's instructions)
            return ""
        
        # Generic fallback only when no mod_name is provided
        # (for UE4SS mod directories where one 使用说明.txt describes one mod)
        for f in directory.iterdir():
            if f.is_file():
                lower = f.name.lower()
                if not lower.endswith(('.txt', '.md')):
                    continue
                if '说明' in f.name or '使用' in f.name or 'readme' in lower or '指南' in f.name:
                    return self._read_and_trim(f)
        
        return ""
    
    def _read_and_trim(self, file: Path) -> str:
        """Read text file and trim to 2000 chars max."""
        try:
            content = file.read_text('utf-8', errors='ignore')
            content = content.strip()
            if len(content) > 2000:
                content = content[:1997] + "..."
            return content
        except Exception:
            return ""
    
    def _ensure_mod_metadata_file(self, directory: Path, mod_name: str, version: str = "1.0.0"):
        """Create mod.json with display name if it doesn't exist yet.
        This ensures every mod has a user-editable display name."""
        import json
        meta_file = directory / "mod.json"
        if meta_file.exists():
            return
        
        try:
            metadata = {
                'name': mod_name,
                'display_name': mod_name,
                'version': version,
                'author': 'Unknown',
                'description': '',
            }
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def _scan_logic_mod_directory(self, directory: Path) -> Optional[ModInfo]:
        """Scan a LogicMod directory."""
        mod_id = hashlib.md5(str(directory).encode()).hexdigest()[:12]
        metadata = self._read_metadata_files(directory)
        
        # Find main script
        lua_files = list(directory.glob('*.lua'))
        main_script = str(lua_files[0]) if lua_files else ""
        
        # Check enabled.txt
        enable_file = directory / "enabled.txt"
        is_enabled = enable_file.exists()
        
        name = metadata.get('name', directory.name)
        
        description = metadata.get('description', '')
        if not description:
            description = self._read_usage_instructions(directory)
        
        return ModInfo(
            id=mod_id,
            name=name,
            version=metadata.get('version', '1.0.0'),
            author=metadata.get('author', 'Unknown'),
            description=description,
            mod_type=ModType.LOGIC,
            status=ModStatus.ENABLED if is_enabled else ModStatus.DISABLED,
            install_path=str(directory),
            source_path=str(directory),
            dependencies=metadata.get('dependencies', []),
            required_frameworks=['UE4SS'],
            ue4ss_main_script=main_script,
            ue4ss_enabled_scripts=[f.name for f in lua_files],
            website=metadata.get('website', metadata.get('url', '')),
            tags=metadata.get('tags', []),
            installed_date=datetime.fromtimestamp(directory.stat().st_ctime).isoformat(),
            last_updated=datetime.fromtimestamp(directory.stat().st_mtime).isoformat(),
            raw_metadata=metadata,
        )
    
    def _scan_pak_file(self, pak_file: Path) -> Optional[ModInfo]:
        """Scan a .pak mod file."""
        mod_id = hashlib.md5(str(pak_file).encode()).hexdigest()[:12]
        
        # Check for sidecar metadata (use base stem without _P or _disabled suffixes)
        metadata = {}
        # For .pak_disabled files, still look for the base .json
        json_path = pak_file.with_name(pak_file.stem + '.json')
        if not json_path.exists():
            json_path = pak_file.with_suffix('.json')
        if json_path.exists():
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
            except (json.JSONDecodeError, IOError):
                pass
        
        name = metadata.get('name', pak_file.stem)
        description = metadata.get('description', '')
        
        # Auto-read usage instructions if description is empty
        # For PAK files, only look for files specifically named for this PAK
        if not description:
            description = self._read_usage_instructions(pak_file.parent, mod_name=pak_file.stem)
        
        # If still no description, try the LogicMods counterpart
        if not description and self.logicmods_paks_dir.exists():
            lm_json = self.logicmods_paks_dir / (pak_file.stem + '.json')
            if lm_json.exists():
                try:
                    with open(lm_json, 'r', encoding='utf-8') as f:
                        lm_meta = json.load(f)
                    description = lm_meta.get('description', '')
                except Exception:
                    pass
        
        # Write description back to companion JSON so it persists
        if description and not metadata.get('description'):
            metadata['description'] = description
            try:
                json_file = json_path or pak_file.with_name(pak_file.stem + '.json')
                with open(json_file, 'w', encoding='utf-8') as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            except Exception:
                pass
        
        # Check if disabled: only consider non-.pak extension as disabled
        # _P suffix in PAK files is a marker from some mod managers (Vortex),
        # NOT a disabled indicator. Actual disable convention is .pak_disabled.
        is_disabled = pak_file.suffix.lower() != '.pak'
        
        return ModInfo(
            id=mod_id,
            name=name,
            version=metadata.get('version', '1.0.0'),
            author=metadata.get('author', 'Unknown'),
            description=description,
            mod_type=ModType.PAK,
            status=ModStatus.DISABLED if is_disabled else ModStatus.ENABLED,
            install_path=str(pak_file),
            source_path=str(pak_file),
            dependencies=metadata.get('dependencies', []),
            required_frameworks=[],
            website=metadata.get('website', metadata.get('url', '')),
            tags=metadata.get('tags', []),
            installed_date=datetime.fromtimestamp(pak_file.stat().st_ctime).isoformat(),
            last_updated=datetime.fromtimestamp(pak_file.stat().st_mtime).isoformat(),
            raw_metadata=metadata,
        )
    
    def _scan_palschema_mod_directory(self, directory: Path, config_files: List[Path]) -> Optional[ModInfo]:
        """Scan a PalSchema config mod directory."""
        mod_id = hashlib.md5(str(directory).encode()).hexdigest()[:12]
        metadata = self._read_metadata_files(directory)
        
        # Read PalSchema config content
        config_data = {}
        for cf in config_files:
            try:
                if cf.suffix in ('.json',):
                    with open(cf, 'r', encoding='utf-8') as f:
                        config_data[cf.name] = json.load(f)
                elif cf.suffix in ('.yml', '.yaml'):
                    with open(cf, 'r', encoding='utf-8') as f:
                        config_data[cf.name] = yaml.safe_load(f)
            except Exception:
                pass
        
        name = metadata.get('name', directory.name)
        description = metadata.get('description', '')
        if not description:
            description = self._read_usage_instructions(directory)
        
        return ModInfo(
            id=mod_id,
            name=name,
            version=metadata.get('version', '1.0.0'),
            author=metadata.get('author', 'Unknown'),
            description=description,
            mod_type=ModType.PALSCHEMA,
            status=ModStatus.ENABLED,
            install_path=str(directory),
            source_path=str(directory),
            dependencies=metadata.get('dependencies', []),
            required_frameworks=['PalSchema', 'UE4SS'],
            palschema_configs=[str(cf) for cf in config_files],
            website=metadata.get('website', metadata.get('url', '')),
            tags=metadata.get('tags', []),
            installed_date=datetime.fromtimestamp(directory.stat().st_ctime).isoformat(),
            last_updated=datetime.fromtimestamp(directory.stat().st_mtime).isoformat(),
            raw_metadata={'configs': config_data},
        )
    
    def _read_metadata_files(self, directory: Path) -> dict:
        """Read metadata from supported file formats in a directory."""
        metadata = {}
        
        for meta_file in self.METADATA_FILES:
            meta_path = directory / meta_file
            if not meta_path.exists():
                continue
            
            try:
                with open(meta_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if meta_file.endswith('.json'):
                    metadata = json.loads(content)
                elif meta_file.endswith(('.yml', '.yaml')):
                    metadata = yaml.safe_load(content) or {}
                elif meta_file.endswith('.toml'):
                    try:
                        import toml
                        metadata = toml.loads(content)
                    except ImportError:
                        pass
                
                if metadata:
                    break
            except Exception:
                continue
        
        return metadata if isinstance(metadata, dict) else {}
    
    def _deduplicate_mods(self, mods: List[ModInfo]) -> List[ModInfo]:
        """Remove duplicate mods based on install path."""
        seen = {}
        for mod in mods:
            path_key = mod.install_path.lower()
            if path_key not in seen:
                seen[path_key] = mod
            else:
                # Keep the one with more metadata
                existing = seen[path_key]
                if len(mod.description) > len(existing.description):
                    seen[path_key] = mod
        return list(seen.values())
        
        return result
    
    def check_conflicts(self, mods: List[ModInfo]) -> Dict[str, List[str]]:
        """Detect mod conflicts based on declared conflicts and overlapping files."""
        conflicts = {}
        
        for i, mod in enumerate(mods):
            # Check declared conflicts
            for conflict_id in mod.conflicts_with:
                for other in mods:
                    if other.id == conflict_id or other.name == conflict_id:
                        if mod.id not in conflicts:
                            conflicts[mod.id] = []
                        conflicts[mod.id].append(other.id)
        
        # Check for mods modifying same game assets
        palschema_mods = [m for m in mods if m.mod_type == ModType.PALSCHEMA]
        for i, mod1 in enumerate(palschema_mods):
            for mod2 in palschema_mods[i+1:]:
                configs1 = set(os.path.basename(c) for c in mod1.palschema_configs)
                configs2 = set(os.path.basename(c) for c in mod2.palschema_configs)
                common = configs1 & configs2
                if common:
                    if mod1.id not in conflicts:
                        conflicts[mod1.id] = []
                    if mod2.id not in conflicts:
                        conflicts[mod2.id] = []
                    conflicts[mod1.id].append(mod2.id)
                    conflicts[mod2.id].append(mod1.id)
        
        return conflicts
