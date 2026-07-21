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

    # ------------------------------------------------------------------
    # Collection scanning (整理好的 mod 合集目录，如 "幻兽帕鲁Mod合集")
    # ------------------------------------------------------------------
    def scan_collection(self, collection_path: str) -> List[ModInfo]:
        """Scan an organized mod collection directory.

        Recognizes the common palworld collection layout, e.g.:
            <collection>/
                1_mod/<ModName>/Pal/Content/... (+ 使用说明.txt in <ModName>)
                分类文件夹/<ModName>/Pal/Content/... (+ 使用说明.txt)
                <ModName>.pak / <ModName>.lua (flat, with optional <ModName>.txt)

        Returns a list of ModInfo discovered inside that collection. The
        discovered mods carry an extra ``raw_metadata['collection_path']``
        so the UI can offer one-click import.
        """
        root = Path(collection_path)
        if not root.is_dir():
            return []

        # Skip non-standard bundle directories whose internal layout we cannot
        # reliably parse (e.g. 游侠/ali213 汉化整合包 uses a '*/files/' layout
        # that would otherwise surface the literal name "files" as a mod name).
        excluded = {p for p in root.iterdir()
                    if p.is_dir() and p.name.lower().startswith('ali213')}

        def _in_excluded(p: Path) -> bool:
            return any(parent in excluded for parent in p.parents)

        mods: List[ModInfo] = []
        seen: set = set()

        def _add(mod: Optional[ModInfo]):
            if mod and mod.id not in seen:
                seen.add(mod.id)
                mods.append(mod)

        # 1) Flat .pak / .lua files directly under the collection (and one level deep)
        for base in (root, *[p for p in root.iterdir() if p.is_dir() and p not in excluded]):
            for item in base.iterdir():
                if not item.is_file():
                    continue
                lower = item.name.lower()
                if lower.endswith('.pak'):
                    _add(self._scan_pak_file(item, collection_mode=True))
                elif lower.endswith('.lua'):
                    _add(self._scan_lua_file(item, collection_mode=True))

        # 2) Mod subfolders that contain a 'Pal' directory (Pal-root layout)
        for item in root.rglob('*'):
            if _in_excluded(item):
                continue
            if not item.is_dir():
                continue
            if item.name.lower() != 'pal':
                continue
            pal_dir = item
            mod_root = pal_dir.parent  # the mod's own folder
            # skip nested Paks/Content etc. — only the top Pal-root qualifies
            if (pal_dir / 'Content').is_dir() or (pal_dir / 'Binaries').is_dir():
                _add(self._scan_palroot_mod(mod_root, collection_path))

        return mods

    def _scan_palroot_mod(self, mod_root: Path, collection_path: str) -> Optional[ModInfo]:
        """Scan a Pal-root mod folder (contains Pal/Content)."""
        pal_dir = mod_root / 'Pal'
        if not pal_dir.is_dir():
            return None

        # Gather the actual content files to decide type & name
        paks = list((pal_dir / 'Content' / 'Paks').rglob('*.pak')) if (pal_dir / 'Content' / 'Paks').is_dir() else []
        lua_dir = pal_dir / 'Content' / 'Paks' / 'LogicMods'
        luas = list(lua_dir.rglob('*.lua')) if lua_dir.is_dir() else []

        if paks:
            primary = paks[0]
            mod = self._scan_pak_file(primary, collection_mode=True)
            mod.install_path = str(mod_root)
        elif luas:
            primary = luas[0]
            mod = self._scan_lua_file(primary, collection_mode=True)
            mod.install_path = str(mod_root)
        else:
            # Pal-root without recognizable content
            return None

        mod.name = mod_root.name
        mod.source_path = str(mod_root)
        # Description: look in mod root (parent_lookup=True handles Pal/ nesting)
        desc = self._read_usage_instructions(pal_dir, mod_name=mod_root.name, parent_lookup=True)
        if not desc:
            desc = self._read_usage_instructions(mod_root)
        mod.description = desc
        mod.raw_metadata['collection_path'] = str(mod_root)
        mod.tags = list(mod.tags) + ['合集']
        mod.is_auto_managed = False
        return mod

    def _scan_lua_file(self, lua_file: Path, collection_mode: bool = False) -> Optional[ModInfo]:
        """Scan a standalone .lua file (used for flat collection entries)."""
        mod_name = lua_file.stem
        mod_info = ModInfo(
            id=f"lua_{lua_file.resolve()}",
            name=mod_name,
            version="1.0.0",
            author="Unknown",
            mod_type=ModType.UE4SS_LUA,
            status=ModStatus.UNKNOWN,
            install_path=str(lua_file.parent),
            source_path=str(lua_file),
            ue4ss_main_script=str(lua_file),
        )
        desc = self._read_usage_instructions(lua_file.parent, mod_name=mod_name)
        mod_info.description = desc
        if collection_mode:
            mod_info.is_auto_managed = False
            mod_info.tags = list(mod_info.tags) + ['合集']
            mod_info.raw_metadata['collection_path'] = str(lua_file.parent)
        return mod_info

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
    
    def _read_usage_instructions(self, directory: Path, mod_name: str = None,
                                  parent_lookup: bool = False) -> str:
        """Read usage instructions from 使用说明.txt, README.md, etc.

        If mod_name is provided (e.g. for a .pak mod), only files clearly
        belonging to that mod are considered: name-prefixed text files
        ('CoolMod.txt', 'CoolMod.md', 'CoolMod使用说明.txt', ...). A secondary
        attempt with a trailing '_P' suffix stripped matches companion files
        named after the original mod (Vortex convention, e.g. 'CoolMod.txt'
        for 'CoolMod_P.pak'). Keyword files (说明/使用/readme/...) are preferred
        but any name-prefixed text file is accepted, so client .pak mods that
        ship a plain readme next to the .pak now get a description too.
        Generic fallback is only used when mod_name is NOT provided
        (for UE4SS/Logic mod directories where one 使用说明.txt describes one mod).

        If parent_lookup is True, the parent directory is also searched for a
        generic instruction file (e.g. '使用说明.txt' sitting in the mod's own
        folder while the .pak/.lua lives in a nested 'Pal/' subfolder).
        """
        if not directory.is_dir():
            return ""

        text_suffixes = ('.txt', '.md', '.markdown')
        skip_keywords = ('changelog', 'license', 'licence', '版权', 'disabled', '_disabled')
        prefer_keywords = ('说明', '使用', 'readme', '指南', 'info', '描述', '介绍')

        # --- mod_name aware search within `directory` ---
        if mod_name:
            def _candidate_text(f: Path) -> str:
                lower = f.name.lower()
                if not lower.startswith(prefix.lower()):
                    return ""
                if not lower.endswith(text_suffixes):
                    return ""
                if any(k in lower for k in skip_keywords):
                    return ""
                return self._read_and_trim(f)

            # Exact name prefix first, then prefix with a trailing '_P' stripped
            prefixes = [mod_name]
            if mod_name.lower().endswith('_p'):
                prefixes.append(mod_name[:-2])

            best_any = ""
            for prefix in prefixes:
                preferred = ""
                for f in directory.iterdir():
                    if not f.is_file():
                        continue
                    text = _candidate_text(f)
                    if not text:
                        continue
                    if any(k in f.name.lower() for k in prefer_keywords):
                        preferred = text
                        break
                    if not best_any:
                        best_any = text
                if preferred:
                    return preferred
            if best_any:
                return best_any

        # Generic keyword search within `directory`
        for f in directory.iterdir():
            if f.is_file():
                lower = f.name.lower()
                if not lower.endswith(text_suffixes):
                    continue
                # keyword check (with parent_lookup, also accept any plain
                # instruction file living in the same folder as the .pak)
                if '说明' in f.name or '使用' in f.name or 'readme' in lower or '指南' in f.name \
                        or (parent_lookup and '说明' in f.name):
                    return self._read_and_trim(f)

        # --- parent folder lookup (mod folder root holding the .pak in Pal/) ---
        if parent_lookup:
            parent = directory.parent
            if parent.is_dir() and parent != directory:
                for f in parent.iterdir():
                    if f.is_file():
                        lower = f.name.lower()
                        if not lower.endswith(text_suffixes):
                            continue
                        if '说明' in f.name or '使用' in f.name or 'readme' in lower or '指南' in f.name:
                            return self._read_and_trim(f)
                # also accept a generic description file in the mod root
                for f in parent.iterdir():
                    if f.is_file() and f.name.lower().endswith(text_suffixes) \
                            and not any(k in f.name.lower() for k in skip_keywords):
                        # avoid grabbing unrelated changelog/license; require a
                        # descriptive name or fall back only when nothing else matched
                        if any(k in f.name for k in prefer_keywords):
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
    
    def _scan_pak_file(self, pak_file: Path, collection_mode: bool = False) -> Optional[ModInfo]:
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
            description = self._read_usage_instructions(
                pak_file.parent, mod_name=pak_file.stem, parent_lookup=collection_mode)
        
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
        
        # Write description back to companion JSON so it persists (skip in
        # collection mode to avoid polluting the user's shared mod collection)
        if description and not metadata.get('description') and not collection_mode:
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
            install_path=str(pak_file.parent) if collection_mode else str(pak_file),
            source_path=str(pak_file),
            dependencies=metadata.get('dependencies', []),
            required_frameworks=[],
            website=metadata.get('website', metadata.get('url', '')),
            tags=(list(metadata.get('tags', [])) + ['合集']) if collection_mode else metadata.get('tags', []),
            installed_date=datetime.fromtimestamp(pak_file.stat().st_ctime).isoformat(),
            last_updated=datetime.fromtimestamp(pak_file.stat().st_mtime).isoformat(),
            is_auto_managed=not collection_mode,
            raw_metadata={**metadata, 'collection_path': str(pak_file.parent)} if collection_mode else metadata,
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
