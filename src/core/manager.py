"""
Mod Manager - core engine for enabling/disabling/managing mods.
Handles UE4SS integration, PalSchema config management, and mod profiles.
"""
import os
import json
import shutil
import hashlib
import zipfile
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Callable

from .models import ModInfo, ModType, ModStatus, ModProfile
from .scanner import ModScanner



class ModManager:
    """Main mod management engine."""
    
    # UE4SS mods.txt path
    UE4SS_MODS_TXT = "mods.txt"
    
    def __init__(self, game_path: str):
        self.game_path = Path(game_path)
        self.scanner = ModScanner(game_path)
        self._mods: Dict[str, ModInfo] = {}
        self._profiles: Dict[str, ModProfile] = {}
        self._conflicts: Dict[str, List[str]] = {}
        self._callbacks: List[Callable] = []
        
        # Ensure required directories exist
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create necessary directories for mod management."""
        dirs = [
            self.scanner.mods_dir,
            self.scanner.paks_dir,
            self.scanner.ue4ss_dir,
            self.scanner.palschema_dir,
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)
    
    @property
    def game_dir(self) -> Path:
        return self.game_path
    
    @property
    def mods(self) -> List[ModInfo]:
        return list(self._mods.values())
    
    def on_change(self, callback: Callable):
        """Register a callback for when mod state changes."""
        self._callbacks.append(callback)
    
    def _notify_change(self):
        """Notify all registered callbacks of a state change."""
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                pass
    
    def refresh(self) -> List[ModInfo]:
        """Refresh the mod list from disk."""
        scanned = self.scanner.scan_all()
        
        # Preserve any custom status overrides
        for mod in scanned:
            if mod.id in self._mods:
                # Keep user-set status if not auto-detected differently
                old = self._mods[mod.id]
                if old.status != ModStatus.UNKNOWN and mod.status == ModStatus.UNKNOWN:
                    mod.status = old.status
        
        self._mods = {m.id: m for m in scanned}
        self._conflicts = self.scanner.check_conflicts(scanned)
        
        # Mark conflicts
        for mod_id, conflict_ids in self._conflicts.items():
            if mod_id in self._mods:
                self._mods[mod_id].status = ModStatus.CONFLICT
        
        self._notify_change()
        return self.mods
    
    def check_and_repair(self) -> Tuple[int, List[str]]:
        """Check and fix misplaced mod files automatically.
        
        Detects:
        - .pak files wrongly placed in Mods/ → move to ~mods/
        - PAK directories inside ~mods/ → flatten to individual files
        - PAK directories inside Mods/ → move to ~mods/
        
        Returns (fixed_count, messages).
        """
        import shutil
        fixed = 0
        messages = []
        mods_dir = self.scanner.mods_dir
        paks_dir = self.scanner.paks_dir
        
        def _is_pak_file(f: Path) -> bool:
            return f.suffix.lower() in ('.pak', '.ucas', '.utoc')
        
        # 1. Check Mods/ for stray PAK files and PAK directories
        if mods_dir.is_dir():
            for item in list(mods_dir.iterdir()):
                if item.is_file() and _is_pak_file(item):
                    dest = paks_dir / item.name
                    if not dest.exists():
                        paks_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(item), str(dest))
                        messages.append(f"已移动 PAK 文件: {item.name} (Mods/ -> ~mods/)")
                        fixed += 1
                elif item.is_dir() and item.name.lower() not in self.scanner.UE4SS_BUILTIN_MODS:
                    # Check if this directory contains only PAK files
                    contents = list(item.rglob('*'))
                    pak_count = sum(1 for c in contents if c.is_file() and _is_pak_file(c))
                    total_files = sum(1 for c in contents if c.is_file())
                    if pak_count > 0 and pak_count == total_files:
                        # Move the whole PAK directory to ~mods/
                        dest_dir = paks_dir / item.name
                        if not dest_dir.exists():
                            shutil.move(str(item), str(dest_dir))
                            messages.append(f"已移动 PAK 目录: {item.name}/ (Mods/ -> ~mods/)")
                            fixed += 1
        
        # 2. Flatten PAK directories in ~mods/
        if paks_dir.is_dir():
            for item in list(paks_dir.iterdir()):
                if item.is_dir():
                    contents = list(item.iterdir())
                    pak_files = [c for c in contents if c.is_file() and _is_pak_file(c)]
                    if pak_files:
                        for pf in pak_files:
                            dest = paks_dir / pf.name
                            if not dest.exists():
                                shutil.move(str(pf), str(dest))
                        # Remove the empty directory
                        try:
                            item.rmdir()
                            messages.append(f"已展平 PAK 目录: {item.name}/ -> ~mods/")
                            fixed += 1
                        except OSError:
                            pass
        
        # 3. Check Mods/ for .pak_disabled files and move
        if mods_dir.is_dir():
            for item in list(mods_dir.iterdir()):
                if item.is_file() and item.suffix.lower() == '.pak_disabled':
                    dest = paks_dir / item.name
                    if not dest.exists():
                        shutil.move(str(item), str(dest))
                        messages.append(f"已移动禁用 PAK: {item.name} (Mods/ -> ~mods/)")
                        fixed += 1
        
        if fixed > 0:
            self.refresh()
        
        return fixed, messages
    
    def get_mod(self, mod_id: str) -> Optional[ModInfo]:
        """Get a specific mod by ID."""
        return self._mods.get(mod_id)
    
    def _get_mod_by_name(self, name: str) -> Optional[ModInfo]:
        """Get a mod by its display name."""
        for mod in self._mods.values():
            if mod.name == name:
                return mod
        return None
    
    def enable_mod(self, mod_id: str) -> bool:
        """Enable a mod."""
        mod = self._mods.get(mod_id)
        if not mod:
            return False
        
        success = False
        
        # LOGIC directory mods: use enabled.txt (same as UE4SS_LUA)
        # LOGIC file mods (LogicMods/*.pak): use .pak/.pak_disabled renaming
        if mod.mod_type == ModType.UE4SS_LUA:
            success = self._enable_ue4ss_mod(mod)
        elif mod.mod_type == ModType.LOGIC:
            if Path(mod.install_path).is_file():
                success = self._enable_pak_mod(mod)
            else:
                success = self._enable_ue4ss_mod(mod)
        elif mod.mod_type == ModType.PAK:
            success = self._enable_pak_mod(mod)
        elif mod.mod_type == ModType.PALSCHEMA:
            success = self._enable_palschema_mod(mod)
        
        if success:
            mod.status = ModStatus.ENABLED
            mod.last_updated = datetime.now().isoformat()
            self._notify_change()
        
        return success
    
    def disable_mod(self, mod_id: str) -> bool:
        """Disable a mod."""
        mod = self._mods.get(mod_id)
        if not mod:
            return False
        
        success = False
        
        if mod.mod_type == ModType.UE4SS_LUA:
            success = self._disable_ue4ss_mod(mod)
        elif mod.mod_type == ModType.LOGIC:
            if Path(mod.install_path).is_file():
                success = self._disable_pak_mod(mod)
            else:
                success = self._disable_ue4ss_mod(mod)
        elif mod.mod_type == ModType.PAK:
            success = self._disable_pak_mod(mod)
        elif mod.mod_type == ModType.PALSCHEMA:
            success = self._disable_palschema_mod(mod)
        
        if success:
            mod.status = ModStatus.DISABLED
            mod.last_updated = datetime.now().isoformat()
            self._notify_change()
        
        return success
    
    def toggle_mod(self, mod_id: str) -> bool:
        """Toggle a mod's enabled state."""
        mod = self._mods.get(mod_id)
        if not mod:
            return False
        
        if mod.status == ModStatus.ENABLED:
            return self.disable_mod(mod_id)
        else:
            return self.enable_mod(mod_id)
    
    def enable_all(self) -> int:
        """Enable all mods. Returns count of successfully enabled."""
        count = 0
        for mod_id in list(self._mods.keys()):
            if self.enable_mod(mod_id):
                count += 1
        return count
    
    def disable_all(self) -> int:
        """Disable all mods. Returns count of successfully disabled."""
        count = 0
        for mod_id in list(self._mods.keys()):
            if self.disable_mod(mod_id):
                count += 1
        return count
    
    # ---- UE4SS Lua/LogicMod operations ----
    
    def _enable_ue4ss_mod(self, mod: ModInfo) -> bool:
        """Enable a UE4SS Lua/LogicMod."""
        mod_path = Path(mod.install_path)
        
        if not mod_path.exists():
            return False
        
        try:
            # Create enabled.txt marker
            enable_file = mod_path / "enabled.txt"
            if not enable_file.exists():
                enable_file.write_text("enabled")
            
            # Remove disabled.txt if exists
            disable_file = mod_path / "disabled.txt"
            if disable_file.exists():
                disable_file.unlink()
            
            # If directory was renamed with _disabled, restore it
            if mod_path.name.endswith('_disabled'):
                new_name = mod_path.name.replace('_disabled', '')
                new_path = mod_path.parent / new_name
                if not new_path.exists():
                    mod_path.rename(new_path)
                    mod.install_path = str(new_path)
            
            # Update mods.txt for UE4SS
            self._update_ue4ss_mods_txt()
            
            return True
        except Exception:
            return False
    
    def _disable_ue4ss_mod(self, mod: ModInfo) -> bool:
        """Disable a UE4SS Lua/LogicMod."""
        mod_path = Path(mod.install_path)
        
        if not mod_path.exists():
            return False
        
        try:
            # Create disabled.txt marker
            disable_file = mod_path / "disabled.txt"
            if not disable_file.exists():
                disable_file.write_text("disabled")
            
            # Remove enabled.txt if exists
            enable_file = mod_path / "enabled.txt"
            if enable_file.exists():
                enable_file.unlink()
            
            # Update mods.txt for UE4SS
            self._update_ue4ss_mods_txt()
            
            return True
        except Exception:
            return False
    
    def _update_ue4ss_mods_txt(self):
        """Update the UE4SS mods.txt configuration file."""
        mods_txt_path = self.scanner.mods_dir / self.UE4SS_MODS_TXT
        
        # Build list of enabled mods
        lines = []
        lines.append("# 帕鲁Mod管理器 - Auto-generated mods.txt")
        lines.append("# Last updated: " + datetime.now().isoformat())
        lines.append("")
        
        for mod in self._mods.values():
            if mod.mod_type in (ModType.UE4SS_LUA, ModType.LOGIC) and mod.status == ModStatus.ENABLED:
                p = Path(mod.install_path)
                if p.is_file():  # Skip file-based LogicMod PAKs
                    continue
                mod_dir_name = p.name
                lines.append(f"{mod_dir_name} : 1")
        
        # Also check for mods with manual enable state via enabled.txt
        mods_dir = self.scanner.mods_dir
        if mods_dir.exists():
            for item in mods_dir.iterdir():
                if item.is_dir():
                    enable_file = item / "enabled.txt"
                    if enable_file.exists():
                        # Only add if not already added
                        if not any(line.startswith(item.name) for line in lines):
                            lines.append(f"{item.name} : 1")
        
        try:
            mods_txt_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        except Exception:
            pass
    
    # ---- .pak mod operations ----
    
    def _enable_pak_mod(self, mod: ModInfo) -> bool:
        """Enable a .pak mod by ensuring correct extension."""
        pak_path = Path(mod.install_path)
        
        if not pak_path.exists():
            # Check if there's a disabled version
            disabled_path = pak_path.with_suffix('.pak_disabled')
            if disabled_path.exists():
                disabled_path.rename(pak_path)
                mod.install_path = str(pak_path)
                return True
            
            # Check for _P suffix
            if '_P' in pak_path.stem:
                new_name = pak_path.stem.replace('_P', '') + pak_path.suffix
                new_path = pak_path.parent / new_name
                if pak_path.exists():
                    pak_path.rename(new_path)
                    mod.install_path = str(new_path)
                    return True
            
            return False
        
        # Ensure extension is .pak
        if pak_path.suffix.lower() != '.pak':
            new_path = pak_path.with_suffix('.pak')
            if not new_path.exists():
                pak_path.rename(new_path)
                mod.install_path = str(new_path)
        
        return True
    
    def _disable_pak_mod(self, mod: ModInfo) -> bool:
        """Disable a .pak mod by renaming extension."""
        pak_path = Path(mod.install_path)
        
        if not pak_path.exists():
            return False
        
        try:
            if pak_path.suffix.lower() == '.pak':
                # Rename to _disabled
                new_path = pak_path.with_suffix('.pak_disabled')
                if not new_path.exists():
                    pak_path.rename(new_path)
                    mod.install_path = str(new_path)
            
            return True
        except Exception:
            return False
    
    # ---- PalSchema mod operations ----
    
    def _enable_palschema_mod(self, mod: ModInfo) -> bool:
        """Enable a PalSchema config mod."""
        mod_path = Path(mod.install_path)
        
        if not mod_path.exists():
            return False
        
        try:
            enable_file = mod_path / "enabled.txt"
            if not enable_file.exists():
                enable_file.write_text("enabled")
            
            disable_file = mod_path / "disabled.txt"
            if disable_file.exists():
                disable_file.unlink()
            
            return True
        except Exception:
            return False
    
    def _disable_palschema_mod(self, mod: ModInfo) -> bool:
        """Disable a PalSchema config mod."""
        mod_path = Path(mod.install_path)
        
        if not mod_path.exists():
            return False
        
        try:
            disable_file = mod_path / "disabled.txt"
            if not disable_file.exists():
                disable_file.write_text("disabled")
            
            enable_file = mod_path / "enabled.txt"
            if enable_file.exists():
                enable_file.unlink()
            
            return True
        except Exception:
            return False
    
    # ---- Mod installation ----

    @staticmethod
    def _pak_bundle_members(pak_path: Path) -> List[Path]:
        """Return the primary PAK and matching UE asset sidecars, if present.

        Modern Unreal mods commonly ship a `.pak` together with `.ucas` and
        `.utoc`.  Copying only the PAK makes the mod appear installed but it
        cannot load in game.
        """
        if pak_path.name.lower().endswith('.pak_disabled'):
            base_name = pak_path.name[:-len('_disabled')]
            base_stem = Path(base_name).stem
        else:
            base_stem = pak_path.stem

        members = [pak_path]
        for suffix in ('.ucas', '.utoc'):
            sidecar = pak_path.parent / f"{base_stem}{suffix}"
            if sidecar.is_file():
                members.append(sidecar)
        return members

    def _copy_pak_bundle(self, pak_path: Path, target_dir: Path) -> Tuple[int, int]:
        """Copy a PAK plus sidecars. Returns `(copied, skipped)`.

        Files are deliberately kept together in their existing folder when
        importing a collection; callers may pass a nested target directory.
        """
        target_dir.mkdir(parents=True, exist_ok=True)
        copied = skipped = 0
        for source in self._pak_bundle_members(pak_path):
            destination = target_dir / source.name
            if destination.exists():
                skipped += 1
                continue
            shutil.copy2(str(source), str(destination))
            copied += 1
        return copied, skipped
    
    def install_mod(self, source_path: str) -> Optional[ModInfo]:
        """Install a mod from a source path (archive or directory)."""
        source = Path(source_path)
        
        if not source.exists():
            return None
        
        if source.is_file():
            return self._install_from_archive(source)
        elif source.is_dir():
            return self._install_from_directory(source)
        
        return None
    
    def _install_from_archive(self, archive_path: Path) -> Optional[ModInfo]:
        """Install a mod from a .zip archive. Auto-detects mod type and extracts
        with proper directory nesting (e.g., Mods/<mod_name>/Scripts/...)."""
        
        if not archive_path.suffix.lower() == '.zip':
            return None
        
        try:
            with zipfile.ZipFile(archive_path, 'r') as zf:
                files = zf.namelist()
                mod_type = self._detect_mod_type_from_files(files)
                
                # Find the root directory inside the zip (strip wrapper dirs)
                root_prefix = self._find_mod_root_in_zip(files, mod_type)
                
                if mod_type == ModType.PAK:
                    # For PAK: extract the complete PAK bundle directly to ~mods/.
                    extract_dir = self.scanner.paks_dir
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    for f in files:
                        if f.endswith('/'):
                            continue
                        name = f.split('/')[-1]
                        if name.lower().endswith(('.pak', '.ucas', '.utoc')):
                            dest = extract_dir / name
                            with zf.open(f) as src, open(dest, 'wb') as dst:
                                shutil.copyfileobj(src, dst)
                else:
                    # For Lua/LogicMod/PalSchema: extract to Mods/<mod_name>/
                    # Use zip filename (without extension) as mod folder name
                    mod_name = archive_path.stem
                    if mod_type == ModType.PALSCHEMA:
                        extract_dir = self.scanner.palschema_dir / mod_name
                    else:
                        extract_dir = self.scanner.mods_dir / mod_name
                    
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    
                    for f in files:
                        if f.endswith('/'):
                            continue
                        # Get relative path, stripping wrapper directories
                        if root_prefix:
                            rel = f[len(root_prefix):] if f.startswith(root_prefix) else f
                        else:
                            rel = f
                        # Skip leading directory if it's just the zip name wrapper
                        parts = rel.split('/')
                        if len(parts) > 1 and parts[0].lower() in (mod_name.lower(), archive_path.stem.lower()):
                            rel = '/'.join(parts[1:])
                        dest = extract_dir / rel
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(f) as src, open(dest, 'wb') as dst:
                            shutil.copyfileobj(src, dst)
                
                # Write mod metadata
                self.scanner._ensure_mod_metadata_file(extract_dir, mod_name)
            
            # Refresh and find the new mod
            self.refresh()
            for mod in self._mods.values():
                if mod.name == archive_path.stem:
                    return mod
                if str(extract_dir) in mod.install_path:
                    return mod
            
            return None
        except Exception as e:
            print(f"Failed to install mod: {e}")
            return None
    
    def _find_mod_root_in_zip(self, files: List[str], mod_type: ModType) -> str:
        """Find the common root directory in zip that contains the actual mod files.
        Returns empty string if files are already at root level."""
        if not files:
            return ""
        
        # For PAK: no root needed, just extract .pak files
        if mod_type == ModType.PAK:
            return ""
        
        # Find common prefix
        prefixes = [f.split('/')[0] for f in files if '/' in f and not f.endswith('/')]
        if not prefixes:
            return ""
        
        # Count occurrences of each top-level dir
        from collections import Counter
        counter = Counter(prefixes)
        
        # If there's a dominant prefix (most files under one dir), use it as root
        total = sum(counter.values())
        for prefix, count in counter.most_common(1):
            if count > total * 0.5:
                return prefix + "/"
        
        return ""
    
    def _install_from_directory(self, source_dir: Path) -> Optional[ModInfo]:
        """Install a mod from a directory. Smartly detects nested structures like:
        ModName/Pal/Binaries/Win64/Mods/ActualMod/ or ModName/Pal/Content/Paks/~mods/*.pak
        Generates mod.json metadata preserving the original mod name.
        """
        mod_name = source_dir.name
        
        # Strategy 1: Check if this is a Palworld root-style directory (contains Pal/Binaries/...)
        pal_dir = source_dir / "Pal"
        if pal_dir.is_dir():
            result = self._install_pal_root_mod(source_dir)
            if result:
                self._write_mod_metadata(result.install_path, mod_name)
            return result
        
        # Strategy 2: Direct detection of mod type from contents
        has_pak = any(source_dir.rglob('*.pak'))
        has_lua = any(source_dir.rglob('*.lua'))
        has_json = any(source_dir.rglob('*.json'))
        
        if has_pak and not has_lua:
            target_dir = self.scanner.paks_dir
            for pak in source_dir.rglob('*.pak'):
                self._copy_pak_bundle(pak, target_dir)
                dest = target_dir / pak.name
                # Write metadata next to the pak file
                self._write_mod_metadata(str(dest), mod_name)
        elif has_lua:
            target_dir = self.scanner.mods_dir / mod_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            self._write_mod_metadata(str(target_dir), mod_name)
        elif has_json:
            target_dir = self.scanner.palschema_dir / mod_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            self._write_mod_metadata(str(target_dir), mod_name)
        else:
            target_dir = self.scanner.mods_dir / mod_name
            if target_dir.exists():
                shutil.rmtree(target_dir)
            shutil.copytree(source_dir, target_dir)
            self._write_mod_metadata(str(target_dir), mod_name)
        
        self.refresh()
        for mod in self._mods.values():
            if str(target_dir) in mod.install_path:
                return mod
        
        return None
    
    def _write_mod_metadata(self, install_path: str, display_name: str, description: str = ''):
        """Write a mod.json metadata file at the install location.
        For directories: writes mod.json inside the directory.
        For files (PAK): writes <filename>.json next to the file."""
        import json
        from datetime import datetime
        
        p = Path(install_path)
        
        if p.is_file():
            # For PAK files: write sidecar json (use stem to match scanner)
            meta_file = p.with_name(p.stem + '.json')
        else:
            # For directories: write mod.json inside
            meta_file = p / "mod.json"
        
        # If metadata already exists, update name/description if they differ
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
            changed = False
            if not existing.get('name') and display_name:
                existing['name'] = display_name
                existing['display_name'] = display_name
                changed = True
            elif display_name and display_name != existing.get('name'):
                existing['name'] = display_name
                existing['display_name'] = display_name
                changed = True
            if description and description != existing.get('description', ''):
                existing['description'] = description
                changed = True
            if changed:
                with open(meta_file, 'w', encoding='utf-8') as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)
            return
        
        metadata = {
            'name': display_name,
            'display_name': display_name,
            'version': '1.0.0',
            'author': 'Unknown',
            'description': description,
            'installed_by': 'PalModManager',
            'installed_date': datetime.now().isoformat(),
        }
        
        try:
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def _install_pal_root_mod(self, source_dir: Path, description: str = '', display_name: str = '') -> Optional[ModInfo]:
        """Install a mod that has the full Palworld directory structure (Pal/Binaries/...).
        Scans all known sub-paths: Mods/, ue4ss/Mods/, ~mods/, LogicMods/, PalSchema/ etc.
        Uses the source folder's display name (e.g. Chinese name) for all sub-mods found.
        """
        pal_dir = source_dir / "Pal"
        display_name = display_name or source_dir.name  # Chinese display name from source folder
        installed_any = False
        
        # Track newly created directories for metadata writing
        new_mod_dirs = []
        
        # Helper: merge a directory tree into target
        def merge_dir(src: Path, dst: Path):
            """Copy all files and dirs from src into dst, merging directories."""
            if not src.is_dir():
                return
            dst.mkdir(parents=True, exist_ok=True)
            for item in src.iterdir():
                if item.is_dir():
                    sub_dst = dst / item.name
                    if sub_dst.exists():
                        # Merge: recursively copy contents
                        merge_dir(item, sub_dst)
                    else:
                        shutil.copytree(item, sub_dst)
                else:
                    shutil.copy2(item, dst / item.name)
        
        target_bin = self.game_path / "Pal" / "Binaries" / "Win64"
        
        # 1. Pal/Binaries/Win64/Mods/ -> Mods/
        mods_src = pal_dir / "Binaries" / "Win64" / "Mods"
        if mods_src.is_dir():
            for item in mods_src.iterdir():
                dest = self.scanner.mods_dir / item.name
                if item.is_dir():
                    merge_dir(item, dest)
                    new_mod_dirs.append(dest)
                else:
                    shutil.copy2(item, dest)
            installed_any = True
        
        # 2. Pal/Binaries/Win64/ue4ss/Mods/ -> Mods/ (some mod packs use this structure)
        ue4ss_mods_src = pal_dir / "Binaries" / "Win64" / "ue4ss" / "Mods"
        if ue4ss_mods_src.is_dir():
            for item in ue4ss_mods_src.iterdir():
                dest = self.scanner.mods_dir / item.name
                if item.is_dir():
                    merge_dir(item, dest)
                    new_mod_dirs.append(dest)
                else:
                    shutil.copy2(item, dest)
            installed_any = True
        
        # 3. Pal/Content/Paks/~mods/ -> ~mods/ (PAK files)
        paks_src = pal_dir / "Content" / "Paks" / "~mods"
        if paks_src.is_dir():
            target_paks = self.scanner.paks_dir
            target_paks.mkdir(parents=True, exist_ok=True)
            for pak in paks_src.glob('*.pak'):
                self._copy_pak_bundle(pak, target_paks)
                dest_pak = target_paks / pak.name
                # Write metadata for PAK file
                self._write_mod_metadata(str(dest_pak), display_name, description)
            installed_any = True
        
        # 4. Pal/Content/Paks/LogicMods/ -> LogicMods/ (legacy LogicMod PAK location)
        logicmods_src = pal_dir / "Content" / "Paks" / "LogicMods"
        if logicmods_src.is_dir():
            target_lm = self.scanner.paks_dir.parent / "LogicMods"
            target_lm.mkdir(parents=True, exist_ok=True)
            for pak in logicmods_src.glob('*.pak'):
                dest_pak = target_lm / pak.name
                shutil.copy2(pak, dest_pak)
                self._write_mod_metadata(str(dest_pak), display_name, description)
            installed_any = True
        
        # 5. Copy DLL/proxy files from Pal/Binaries/Win64/ (framework files)
        # Skip UE4SS framework files to avoid version conflicts — framework
        # installation is handled separately by the framework setup tool.
        _SKIP_FRAMEWORK_FILES = {
            'ue4ss.dll', 'ue4ss-settings.ini', 'dwmapi.dll',
            'xinput1_3.dll', 'version.dll',
        }
        bin_dir = pal_dir / "Binaries" / "Win64"
        if bin_dir.is_dir():
            for item in bin_dir.iterdir():
                if item.is_file() and item.suffix.lower() in ('.dll', '.ini'):
                    if item.name.lower() in _SKIP_FRAMEWORK_FILES:
                        continue
                    dest = target_bin / item.name
                    if not dest.exists():
                        shutil.copy2(item, dest)
        
        # 6. PalSchema from Pal/Binaries/Win64/Mods/PalSchema/
        ps_mods = mods_src / "PalSchema" if mods_src.is_dir() else None
        if ps_mods and ps_mods.is_dir():
            merge_dir(ps_mods, self.scanner.palschema_dir)
        
        # 7. Any loose .lua or .json in the Pal/ dir root
        for item in pal_dir.iterdir():
            if item.is_file() and item.suffix.lower() in ('.lua', '.json', '.jsonc'):
                shutil.copy2(item, target_bin / item.name)
        
        # 8. Copy usage instructions (使用说明.txt, README.md, etc.) to each new mod location
        for item in source_dir.iterdir():
            if item.is_file():
                lower = item.name.lower()
                if lower.endswith(('.txt', '.md')) and ('说明' in item.name or 'readme' in lower or '使用' in item.name):
                    # Copy to UE4SS mod dirs (one per folder, same file)
                    for mod_dir in new_mod_dirs:
                        if mod_dir.is_dir():
                            shutil.copy2(item, mod_dir / item.name)
                    # Copy to PAK mods - each PAK gets its own copy named "<pak_stem>_说明.txt"
                    # so that PAK scanner doesn't pick up the wrong file
                    if paks_src.is_dir():
                        for pak in paks_src.glob('*.pak'):
                            dest_pak = target_paks / pak.name
                            if dest_pak.exists():
                                # Use PAK-specific filename to avoid confusion
                                target_instr = target_paks / f"{pak.stem}_{item.name}"
                                shutil.copy2(item, target_instr)
                    # Same for LogicMods
                    if logicmods_src.is_dir():
                        for pak in logicmods_src.glob('*.pak'):
                            dest_pak = target_lm / pak.name
                            if dest_pak.exists():
                                target_instr = target_lm / f"{pak.stem}_{item.name}"
                                shutil.copy2(item, target_instr)
        
        # Write mod.json with Chinese display_name BEFORE refresh,
        # so Scanner reads it and uses the correct name
        for mod_dir in new_mod_dirs:
            if mod_dir.is_dir() and mod_dir.name.lower() not in self.scanner.UE4SS_BUILTIN_MODS:
                self._write_mod_metadata(str(mod_dir), display_name, description)
        
        self.refresh()
        
        # Return the first non-builtin mod found
        for mod in self._mods.values():
            if mod.name.lower() not in self.scanner.UE4SS_BUILTIN_MODS:
                return mod
        
        return None
    
    def sync_mods_to(self, target_path: str, mod_ids: List[str] = None) -> Tuple[int, int, List[str]]:
        """Sync mods from current manager to another Palworld installation (e.g. server).
        
        Args:
            target_path: Target game/server installation path
            mod_ids: Specific mod IDs to sync, or None for all non-builtin mods
        
        Returns:
            (success_count, fail_count, error_messages)
        """
        import shutil
        target = Path(target_path)
        target_mods = target / "Pal" / "Binaries" / "Win64" / "Mods"
        target_paks = target / "Pal" / "Content" / "Paks" / "~mods"
        target_lm = target / "Pal" / "Content" / "Paks" / "LogicMods"
        
        target_mods.mkdir(parents=True, exist_ok=True)
        target_paks.mkdir(parents=True, exist_ok=True)
        
        if mod_ids is None:
            # Sync all non-builtin mods
            mods_to_sync = [m for m in self._mods.values() 
                          if m.name.lower() not in self.scanner.UE4SS_BUILTIN_MODS]
        else:
            mods_to_sync = [self._mods[mid] for mid in mod_ids if mid in self._mods]
        
        success = 0
        fail = 0
        errors = []
        
        for mod in mods_to_sync:
            try:
                src = Path(mod.install_path)
                if not src.exists():
                    fail += 1
                    errors.append(f"{mod.name}: 源文件不存在")
                    continue
                
                if mod.mod_type == ModType.PAK:
                    # PAK file -> copy to ~mods/
                    dest = target_paks / src.name
                    shutil.copy2(str(src), str(dest))
                    # Copy companion JSON if exists
                    json_src = src.with_suffix('.json')
                    if json_src.exists():
                        shutil.copy2(str(json_src), str(target_paks / json_src.name))
                    success += 1
                    
                elif mod.mod_type == ModType.LOGIC:
                    # LOGIC can be directory-based (in Mods/) or PAK-based (in LogicMods/)
                    src_parent = src.parent.name
                    if src.is_file() and src_parent == 'LogicMods':
                        # LogicMod PAK file -> copy to target LogicMods/
                        target_lm = target / "Pal" / "Content" / "Paks" / "LogicMods"
                        target_lm.mkdir(parents=True, exist_ok=True)
                        dest = target_lm / src.name
                        shutil.copy2(str(src), str(dest))
                        # Copy companion JSON
                        json_src = src.with_name(src.stem + '.json')
                        if json_src.exists():
                            shutil.copy2(str(json_src), str(target_lm / json_src.name))
                        # Sync PAK enabled/disabled via .pak/.pak_disabled renaming
                        if mod.status == ModStatus.ENABLED:
                            disabled = dest.with_suffix('.pak_disabled')
                            if disabled.exists():
                                shutil.copy2(str(disabled), str(dest.with_suffix('.pak')))
                                disabled.unlink()
                        else:
                            enabled = dest.with_suffix('.pak')
                            if not enabled.exists():
                                enabled = dest
                            if enabled.exists() and not enabled.name.endswith('.pak_disabled'):
                                shutil.copy2(str(enabled), str(dest.with_suffix('.pak_disabled')))
                                enabled.unlink()
                        success += 1
                    else:
                        # Directory-based LOGIC mod -> copy to Mods/
                        dest = target_mods / src.name
                        if dest.exists():
                            shutil.rmtree(str(dest))
                        shutil.copytree(str(src), str(dest))
                        meta_src = src / "mod.json"
                        if meta_src.exists():
                            shutil.copy2(str(meta_src), str(dest / "mod.json"))
                        self._sync_mod_enabled_state(src, dest, mod)
                        success += 1
                    
                elif mod.mod_type == ModType.PALSCHEMA:
                    # PalSchema config -> copy to Mods/PalSchema/
                    dest = target_mods / "PalSchema" / src.name
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(src), str(dest))
                    self._sync_mod_enabled_state(src, dest, mod)
                    success += 1
                    
                else:
                    # Unknown type -> copy as directory
                    dest = target_mods / src.name
                    if src.is_dir():
                        if dest.exists():
                            shutil.rmtree(str(dest))
                        shutil.copytree(str(src), str(dest))
                    else:
                        shutil.copy2(str(src), str(dest))
                    self._sync_mod_enabled_state(src, dest, mod)
                    success += 1
                    
            except Exception as e:
                fail += 1
                errors.append(f"{mod.name}: {str(e)}")
        
        # Also sync mods.txt with correct enabled states
        self._update_ue4ss_mods_txt_for_target(target_mods)
        
        # Sync mods.json if exists
        mods_json_src = self.scanner.mods_dir / "mods.json"
        if mods_json_src.exists():
            try:
                shutil.copy2(str(mods_json_src), str(target_mods / "mods.json"))
            except Exception:
                pass
        
        return success, fail, errors
    
    def sync_mirror(self, other_path: str) -> Tuple[int, int, int, List[str]]:
        """Mirror sync: make the other installation's mods identical to this one.
        
        Copies missing mods from self to other, and deletes mods on other
        that don't exist on self. The result: other side matches self exactly.
        
        Args:
            other_path: The target Palworld installation path (gets overwritten to match self)
        
        Returns:
            (copied_count, deleted_count, fail_count, messages)
        """
        other_scanner = ModScanner(other_path)
        other_mods = other_scanner.scan_all()
        other_mod_names = {m.name for m in other_mods if m.name not in self.scanner.UE4SS_BUILTIN_MODS}
        
        self_mods = self.refresh()
        self_mod_names = {m.name for m in self_mods if m.name not in self.scanner.UE4SS_BUILTIN_MODS}
        
        target_mods_dir = Path(other_path) / "Pal" / "Binaries" / "Win64" / "Mods"
        target_paks_dir = Path(other_path) / "Pal" / "Content" / "Paks" / "~mods"
        target_logicmods_dir = Path(other_path) / "Pal" / "Content" / "Paks" / "LogicMods"
        
        # Cleanup: remove duplicate PAK files (both .pak and .pak_disabled with same base name)
        # Caused by earlier bugs - now keep only one based on enabled/disabled state in scan
        self._cleanup_duplicate_paks(target_paks_dir)
        self._cleanup_duplicate_paks(target_logicmods_dir)
        
        target_mods_dir.mkdir(parents=True, exist_ok=True)
        target_paks_dir.mkdir(parents=True, exist_ok=True)
        target_logicmods_dir.mkdir(parents=True, exist_ok=True)
        
        copied = 0
        deleted = 0
        fail = 0
        messages = []
        
        # 1. Sync all mods from self -> other (copy missing, fix state mismatches)
        for mod in self_mods:
            if mod.name in self.scanner.UE4SS_BUILTIN_MODS:
                continue
            
            src = Path(mod.install_path)
            if not src.exists():
                continue
            
            if mod.mod_type == ModType.PAK:
                base = src.stem  # stem strips the last suffix (.pak or _disabled)
                # For PAK, strip _P suffix from base too for matching
                match_base = base
                other_pak = target_paks_dir / (base + '.pak')
                other_disabled = target_paks_dir / (base + '.pak_disabled')
                
                if mod.status == ModStatus.ENABLED:
                    # Self has enabled: other should have .pak, NOT .pak_disabled
                    if other_pak.exists() and not other_disabled.exists():
                        continue  # Already correct
                    if other_disabled.exists():
                        # Fix: rename .pak_disabled -> .pak (enable it)
                        # Windows rename fails if target exists, so use copy+delete
                        try:
                            shutil.copy2(str(other_disabled), str(other_pak))
                            other_disabled.unlink()
                            copied += 1  # Count as sync fix
                        except Exception as e:
                            fail += 1
                            messages.append(f"启用 {mod.name}: {e}")
                        continue
                    # Neither exists -> copy the .pak
                    dest = other_pak
                else:
                    # Self has disabled: other should have .pak_disabled, NOT .pak
                    if other_disabled.exists() and not other_pak.exists():
                        continue  # Already correct
                    if other_pak.exists():
                        # Fix: rename .pak -> .pak_disabled (disable it)
                        try:
                            shutil.copy2(str(other_pak), str(other_disabled))
                            other_pak.unlink()
                            copied += 1
                        except Exception as e:
                            fail += 1
                            messages.append(f"禁用 {mod.name}: {e}")
                        continue
                    # Neither exists -> copy the .pak_disabled
                    dest = other_disabled
            elif mod.mod_type == ModType.LOGIC and src.is_file():
                # LogicMod PAK — handle like PAK but in LogicMods/ directory
                base = src.stem
                other_pak = target_logicmods_dir / (base + '.pak')
                other_disabled = target_logicmods_dir / (base + '.pak_disabled')
                
                if mod.status == ModStatus.ENABLED:
                    if other_pak.exists() and not other_disabled.exists():
                        continue
                    if other_disabled.exists():
                        try:
                            shutil.copy2(str(other_disabled), str(other_pak))
                            other_disabled.unlink()
                            copied += 1
                        except Exception as e:
                            fail += 1
                            messages.append(f"启用 {mod.name}: {e}")
                        continue
                    dest = other_pak
                else:
                    if other_disabled.exists() and not other_pak.exists():
                        continue
                    if other_pak.exists():
                        try:
                            shutil.copy2(str(other_pak), str(other_disabled))
                            other_pak.unlink()
                            copied += 1
                        except Exception as e:
                            fail += 1
                            messages.append(f"禁用 {mod.name}: {e}")
                        continue
                    dest = other_disabled
            elif mod.mod_type == ModType.PALSCHEMA:
                dest = target_mods_dir / "PalSchema" / src.name
            elif mod.mod_type == ModType.LOGIC and src.is_file():
                # Dest was already set in the LOGIC file branch above
                pass
            else:
                dest = target_mods_dir / src.name
            
            # For non-PAK / non-LOGIC-file: skip if destination already exists
            is_pak_like = mod.mod_type in (ModType.PAK,) or (
                mod.mod_type == ModType.LOGIC and src.is_file())
            if not is_pak_like:
                if dest.exists():
                    continue
            
            try:
                if src.is_file():
                    shutil.copy2(str(src), str(dest))
                    # For PAK / LogicMod PAK: copy companion .json (contains Chinese name)
                    if mod.mod_type in (ModType.PAK, ModType.LOGIC):
                        json_src = src.with_name(src.stem + '.json')
                        if json_src.exists():
                            json_dest = dest.with_name(dest.stem + '.json')
                            shutil.copy2(str(json_src), str(json_dest))
                        # Also try with_suffix variant
                        json_src2 = src.with_suffix('.json')
                        if json_src2.exists() and json_src2 != json_src:
                            json_dest2 = dest.with_suffix('.json')
                            shutil.copy2(str(json_src2), str(json_dest2))
                    # LOGIC file mod: synced via its own LogicMods/ handling above
                else:
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(src), str(dest))
                
                self._sync_mod_enabled_state(src, dest, mod)
                copied += 1
            except Exception as e:
                fail += 1
                messages.append(f"复制 {mod.name}: {e}")
        
        # 2. Sync enabled/disabled state for mods that exist on both sides
        for mod in other_mods:
            if mod.name in self.scanner.UE4SS_BUILTIN_MODS:
                continue
            
            if mod.name not in self_mod_names:
                continue  # Will be deleted or handled below
            
            # Mod exists on both sides - sync the enabled/disabled state
            src_mod = self._get_mod_by_name(mod.name)
            if not src_mod:
                continue
            
            if src_mod.status == mod.status:
                continue  # Same state, nothing to do
            
            # State differs - fix it on the target side
            src_path = Path(mod.install_path)
            try:
                if mod.mod_type == ModType.PAK:
                    base = src_path.stem
                    if src_mod.status == ModStatus.ENABLED:
                        # Source is enabled, target should be .pak
                        other_pak = src_path.parent / (base + '.pak')
                        other_disabled = src_path.parent / (base + '.pak_disabled')
                        if other_disabled.exists():
                            shutil.copy2(str(other_disabled), str(other_pak))
                            other_disabled.unlink()
                            copied += 1
                    else:
                        # Source is disabled, target should be .pak_disabled
                        other_pak = src_path.parent / (base + '.pak')
                        other_disabled = src_path.parent / (base + '.pak_disabled')
                        if other_pak.exists():
                            shutil.copy2(str(other_pak), str(other_disabled))
                            other_pak.unlink()
                            copied += 1
                elif mod.mod_type == ModType.LOGIC and src_path.is_file():
                    # LogicMod PAK state sync (same as PAK but in LogicMods dir)
                    base = src_path.stem
                    if src_mod.status == ModStatus.ENABLED:
                        other_pak = src_path.parent / (base + '.pak')
                        other_disabled = src_path.parent / (base + '.pak_disabled')
                        if other_disabled.exists():
                            shutil.copy2(str(other_disabled), str(other_pak))
                            other_disabled.unlink()
                            copied += 1
                    else:
                        other_pak = src_path.parent / (base + '.pak')
                        other_disabled = src_path.parent / (base + '.pak_disabled')
                        if other_pak.exists():
                            shutil.copy2(str(other_pak), str(other_disabled))
                            other_pak.unlink()
                            copied += 1
                else:
                    # Non-PAK: use enabled.txt/disabled.txt markers
                    self._sync_mod_enabled_state(
                        Path(src_mod.install_path), src_path, src_mod)
                    copied += 1
            except Exception as e:
                fail += 1
                messages.append(f"状态同步 {mod.name}: {e}")
        
        # 3. Delete mods on other side that don't exist on self
        for mod in other_mods:
            if mod.name in self.scanner.UE4SS_BUILTIN_MODS:
                continue
            
            if mod.name in self_mod_names:
                continue  # Already handled above
            
            # This mod exists on other but NOT on self -> delete it
            src = Path(mod.install_path)
            try:
                if not src.exists():
                    continue
                
                if src.is_file():
                    if src.suffix.lower() == '.pak':
                        json_file = src.with_suffix('.json')
                        if json_file.exists():
                            json_file.unlink()
                    src.unlink()
                else:
                    shutil.rmtree(str(src))
                
                # Also delete variants, companion json, and LogicMod mirror
                if mod.mod_type in (ModType.PAK, ModType.LOGIC) and src.is_file():
                    base = src.stem
                    other_variant_pak = src.parent / (base + '.pak')
                    other_variant_disabled = src.parent / (base + '.pak_disabled')
                    if src.suffix.lower() == '.pak' and other_variant_disabled.exists():
                        other_variant_disabled.unlink()
                    elif src.name.lower().endswith('.pak_disabled') and other_variant_pak.exists():
                        other_variant_pak.unlink()
                    # Delete companion json
                    json_file = src.with_name(src.stem + '.json')
                    if json_file.exists():
                        json_file.unlink()
                
                deleted += 1
            except Exception as e:
                fail += 1
                messages.append(f"删除 {mod.name}: {e}")
        
        # 4. Update mods.txt on target side
        self._update_ue4ss_mods_txt_for_target(target_mods_dir)
        
        return copied, deleted, fail, messages
    
    def _cleanup_duplicate_paks(self, paks_dir: Path):
        """Remove duplicate PAK files where both .pak and .pak_disabled exist for same base name.
        When both exist, prefer the .pak (enabled) version and delete the .pak_disabled.
        """
        if not paks_dir.exists():
            return
        
        # Group files by base name
        bases: Dict[str, Dict[str, Path]] = {}
        for f in paks_dir.iterdir():
            if not f.is_file():
                continue
            name_lower = f.name.lower()
            if name_lower.endswith('.pak_disabled'):
                base = f.name[:-len('_disabled')]  # strip "_disabled" to get "foo.pak"
                # Then strip .pak to get base name "foo"
                if base.lower().endswith('.pak'):
                    base = base[:-4]
                bases.setdefault(base.lower(), {})['disabled'] = f
            elif name_lower.endswith('.pak'):
                base = f.name[:-4]  # strip ".pak" to get "foo"
                bases.setdefault(base.lower(), {})['pak'] = f
        
        # For each base that has BOTH, keep the .pak and delete the .pak_disabled
        for base, variants in bases.items():
            if 'pak' in variants and 'disabled' in variants:
                try:
                    variants['disabled'].unlink()
                except Exception:
                    pass
    
    def _update_ue4ss_mods_txt(self):
        """Regenerate mods.txt for the current installation."""
        lines = ["# 帕鲁Mod管理器 - Synced mods.txt",
                  "# Last updated: " + datetime.now().isoformat(), ""]
        
        for mod in self._mods.values():
            if mod.mod_type in (ModType.UE4SS_LUA, ModType.LOGIC):
                p = Path(mod.install_path)
                if p.is_file():  # Skip file-based LogicMod PAKs
                    continue
                mod_dir_name = p.name
                if mod.status == ModStatus.ENABLED:
                    lines.append(f"{mod_dir_name} : 1")
                else:
                    lines.append(f"{mod_dir_name} : 0")
        
        try:
            (self.scanner.mods_dir / "mods.txt").write_text('\n'.join(lines) + '\n', encoding='utf-8')
        except Exception:
            pass
    
    def _update_ue4ss_mods_txt_for_target(self, target_mods_dir: Path):
        """Generate mods.txt for the target directory based on current mod states."""
        lines = ["# 帕鲁Mod管理器 - Synced mods.txt", 
                  "# Last updated: " + datetime.now().isoformat(), ""]
        
        for mod in self._mods.values():
            if mod.mod_type in (ModType.UE4SS_LUA, ModType.LOGIC):
                mod_dir_name = Path(mod.install_path).name
                if mod.status == ModStatus.ENABLED:
                    lines.append(f"{mod_dir_name} : 1")
                else:
                    lines.append(f"{mod_dir_name} : 0")
        
        try:
            (target_mods_dir / "mods.txt").write_text('\n'.join(lines) + '\n', encoding='utf-8')
        except Exception:
            pass
    
    def _sync_mod_enabled_state(self, src_dir: Path, dst_dir: Path, mod: 'ModInfo'):
        """Sync enabled/disabled state for a single mod."""
        # For directory-based mods (Lua, PalSchema, etc.)
        if dst_dir.is_dir():
            if mod.status == ModStatus.ENABLED:
                # Create enabled.txt, remove disabled.txt
                (dst_dir / "enabled.txt").write_text("enabled")
                disable_file = dst_dir / "disabled.txt"
                if disable_file.exists():
                    disable_file.unlink()
            else:
                # Create disabled.txt, remove enabled.txt
                (dst_dir / "disabled.txt").write_text("disabled")
                enable_file = dst_dir / "enabled.txt"
                if enable_file.exists():
                    enable_file.unlink()
        # For PAK files, state is controlled by extension
        elif mod.mod_type == ModType.PAK:
            if mod.status == ModStatus.ENABLED:
                # Ensure .pak extension
                if dst_dir.suffix.lower() != '.pak':
                    new_path = dst_dir.with_suffix('.pak')
                    dst_dir.rename(new_path)
            else:
                # Rename to .pak_disabled
                if dst_dir.suffix.lower() == '.pak':
                    new_path = dst_dir.with_suffix('.pak_disabled')
                    dst_dir.rename(new_path)
    
    def uninstall_mod(self, mod_id: str) -> bool:
        """Completely remove a mod and all its associated files."""
        mod = self._mods.get(mod_id)
        if not mod:
            return False
        
        mod_path = Path(mod.install_path)
        
        try:
            if mod_path.is_dir():
                shutil.rmtree(mod_path)
            elif mod_path.is_file():
                mod_path.unlink()
                
                # For PAK / LogicMod PAK files: delete variants and companion json
                if mod.mod_type in (ModType.PAK, ModType.LOGIC):
                    # `foo.pak_disabled` is still the foo PAK bundle.
                    name = mod_path.name
                    stem = (name[:-len('.pak_disabled')]
                            if name.lower().endswith('.pak_disabled')
                            else mod_path.stem)
                    for variant in ['.pak', '.pak_disabled']:
                        other = mod_path.parent / (stem + variant)
                        if other != mod_path and other.exists():
                            other.unlink()
                    # UE5 IO Store mods need these alongside their PAK.  Do
                    # not leave them behind after uninstalling the mod.
                    for suffix in ('.ucas', '.utoc'):
                        sidecar = mod_path.parent / (stem + suffix)
                        if sidecar.exists():
                            sidecar.unlink()
                    for json_name in (stem + '.json', mod_path.with_suffix('.json').name):
                        json_file = mod_path.parent / json_name
                        if json_file.exists():
                            json_file.unlink()
            
            del self._mods[mod_id]
            self._update_ue4ss_mods_txt()
            self._notify_change()
            return True
        except Exception:
            return False
    
    def _detect_mod_type_from_files(self, files: List[str]) -> ModType:
        """Detect mod type based on file list (from archive)."""
        for f in files:
            f_lower = f.lower()
            if f_lower.endswith('.pak'):
                return ModType.PAK
            if f_lower.endswith('.lua') and 'script' in f_lower:
                return ModType.UE4SS_LUA
            if f_lower.endswith('.lua'):
                return ModType.LOGIC
            if 'palschema' in f_lower:
                return ModType.PALSCHEMA
            if f_lower.endswith('.json') and ('config' in f_lower or 'data' in f_lower):
                return ModType.PALSCHEMA
        
        # Default
        if any(f.endswith('.lua') for f in files):
            return ModType.UE4SS_LUA
        if any(f.endswith('.pak') for f in files):
            return ModType.PAK
        return ModType.UNKNOWN
    
    # ---- Profiles ----
    
    def save_profile(self, name: str, description: str = "") -> ModProfile:
        """Save current mod state as a profile."""
        enabled_ids = [m.id for m in self._mods.values() if m.status == ModStatus.ENABLED]
        
        profile = ModProfile(
            name=name,
            enabled_mods=enabled_ids,
            description=description,
            created_date=datetime.now().isoformat(),
        )
        
        self._profiles[name] = profile
        self._save_profiles()
        return profile
    
    def load_profile(self, name: str) -> bool:
        """Load a profile - enables mods in profile, disables others."""
        profile = self._profiles.get(name)
        if not profile:
            return False
        
        # Disable all first
        for mod_id in self._mods:
            if self._mods[mod_id].status == ModStatus.ENABLED:
                self._disable_mod_silent(mod_id)
        
        # Enable mods in profile
        for mod_id in profile.enabled_mods:
            if mod_id in self._mods:
                self._enable_mod_silent(mod_id)
        
        self.refresh()
        self._notify_change()
        return True
    
    def _enable_mod_silent(self, mod_id: str):
        """Enable mod without triggering callbacks."""
        mod = self._mods.get(mod_id)
        if mod:
            self.enable_mod(mod_id)
    
    def _disable_mod_silent(self, mod_id: str):
        """Disable mod without triggering callbacks."""
        mod = self._mods.get(mod_id)
        if mod:
            self.disable_mod(mod_id)
    
    def delete_profile(self, name: str) -> bool:
        """Delete a saved profile."""
        if name in self._profiles:
            del self._profiles[name]
            self._save_profiles()
            return True
        return False
    
    def get_profiles(self) -> List[ModProfile]:
        """Get all saved profiles."""
        return list(self._profiles.values())
    
    def _save_profiles(self):
        """Persist profiles to disk."""
        profiles_dir = self._get_data_dir()
        profiles_dir.mkdir(parents=True, exist_ok=True)
        
        profiles_file = self._get_profiles_file()
        data = {name: p.to_dict() for name, p in self._profiles.items()}
        
        try:
            with open(profiles_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def _load_profiles(self):
        """Load profiles from disk."""
        profiles_file = self._get_data_dir() / "profiles.json"

        # Profiles used to be stored in one shared file.  Retain that file as
        # a one-time fallback, while new saves are isolated by game/server
        # path so switching modes cannot overwrite or apply the wrong setup.
        scoped_file = self._get_profiles_file()
        if scoped_file.exists():
            profiles_file = scoped_file
        
        if profiles_file.exists():
            try:
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._profiles = {
                    name: ModProfile.from_dict(p) for name, p in data.items()
                }
            except Exception:
                self._profiles = {}
    
    def _get_data_dir(self) -> Path:
        """Get the data directory for persistent storage."""
        data_dir = Path(os.environ.get('APPDATA', os.path.expanduser('~'))) / "帕鲁Mod管理器"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    def _get_profiles_file(self) -> Path:
        """Return a stable, path-specific profile storage file."""
        normalized_path = os.path.normcase(os.path.abspath(str(self.game_path)))
        path_hash = hashlib.sha256(normalized_path.encode('utf-8')).hexdigest()[:16]
        return self._get_data_dir() / f"profiles_{path_hash}.json"
    
    # ---- Statistics and utilities ----
    
    def get_stats(self) -> dict:
        """Get mod statistics."""
        total = len(self._mods)
        enabled = sum(1 for m in self._mods.values() if m.status == ModStatus.ENABLED)
        disabled = sum(1 for m in self._mods.values() if m.status == ModStatus.DISABLED)
        conflicts = sum(1 for m in self._mods.values() if m.status == ModStatus.CONFLICT)
        errors = sum(1 for m in self._mods.values() if m.status == ModStatus.ERROR)
        
        by_type = {}
        for m in self._mods.values():
            t = m.mod_type.value
            by_type[t] = by_type.get(t, 0) + 1
        
        return {
            'total': total,
            'enabled': enabled,
            'disabled': disabled,
            'conflicts': conflicts,
            'errors': errors,
            'by_type': by_type,
        }
    
    def get_conflicts_for_mod(self, mod_id: str) -> List[str]:
        """Get list of mod IDs that conflict with the given mod."""
        return self._conflicts.get(mod_id, [])
    
    def export_mod_pack(self, output_dir: str) -> Tuple[int, List[str]]:
        """Export all mods to a folder that mirrors the game's Pal/ directory structure.
        
        Creates:
        output_dir/
        └── Pal/
            ├── Binaries/Win64/Mods/     (UE4SS Lua, LogicMod, PalSchema + mods.txt)
            └── Content/Paks/~mods/      (PAK mods)
        
        User can just copy the Pal/ folder into their game directory to install all mods.
        
        Returns (mod_count, error_messages).
        """
        import shutil
        output = Path(output_dir)
        errors = []
        mod_count = 0
        
        # Mirror game directory structure
        pal_export = output / "Pal"
        mods_export = pal_export / "Binaries" / "Win64" / "Mods"
        paks_export = pal_export / "Content" / "Paks" / "~mods"
        logicmods_export = pal_export / "Content" / "Paks" / "LogicMods"
        mods_export.mkdir(parents=True, exist_ok=True)
        paks_export.mkdir(parents=True, exist_ok=True)
        logicmods_export.mkdir(parents=True, exist_ok=True)
        
        for mod in self._mods.values():
            if mod.name.lower() in self.scanner.UE4SS_BUILTIN_MODS:
                continue
            
            src = Path(mod.install_path)
            if not src.exists():
                errors.append(f"{mod.name}: 源文件不存在")
                continue
            
            try:
                if mod.mod_type == ModType.PAK:
                    dest = paks_export / src.name
                    shutil.copy2(str(src), str(dest))
                    json_src = src.with_name(src.stem + '.json')
                    if json_src.exists():
                        shutil.copy2(str(json_src), str(paks_export / json_src.name))
                elif mod.mod_type == ModType.LOGIC and src.is_file():
                    # LogicMod PAK -> export to LogicMods/
                    dest = logicmods_export / src.name
                    shutil.copy2(str(src), str(dest))
                    json_src = src.with_name(src.stem + '.json')
                    if json_src.exists():
                        shutil.copy2(str(json_src), str(logicmods_export / json_src.name))
                elif mod.mod_type == ModType.PALSCHEMA:
                    dest = mods_export / "PalSchema" / src.name
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(src), str(dest))
                    self._sync_mod_enabled_state(src, dest, mod)
                else:
                    dest = mods_export / src.name
                    if dest.exists():
                        shutil.rmtree(str(dest))
                    shutil.copytree(str(src), str(dest))
                    self._sync_mod_enabled_state(src, dest, mod)
                
                mod_count += 1
            except Exception as e:
                errors.append(f"{mod.name}: {e}")
        
        # Copy mods.txt
        mods_txt = self.scanner.mods_dir / "mods.txt"
        if mods_txt.exists():
            shutil.copy2(str(mods_txt), str(mods_export / "mods.txt"))
        else:
            self._update_ue4ss_mods_txt()
            mods_txt_new = self.scanner.mods_dir / "mods.txt"
            if mods_txt_new.exists():
                shutil.copy2(str(mods_txt_new), str(mods_export / "mods.txt"))
        
        # Write pack metadata
        pack_info = {
            'name': f"Palworld Mod Pack - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
            'exported': datetime.now().isoformat(),
            'mod_count': mod_count,
            'mods': [{
                'name': m.name,
                'type': m.mod_type.value if m.mod_type else 'unknown',
                'status': m.status.value if m.status else 'unknown',
                'version': m.version,
                'author': m.author,
            } for m in self._mods.values() 
              if m.name.lower() not in self.scanner.UE4SS_BUILTIN_MODS],
        }
        (output / "modpack.json").write_text(
            json.dumps(pack_info, indent=2, ensure_ascii=False), encoding='utf-8')
        
        return mod_count, errors
    
    def _unwrap_single_child(self, dir_path: Path) -> Path:
        """If the directory contains a single subdirectory (and no other files),
        unwrap to that subdirectory. Recursively continues.
        Stops when:
        - Directory has more than one entry (likely real mods)
        - The only entry is a system directory like 'Pal'
        - Max depth reached
        """
        if not dir_path.is_dir():
            return dir_path
        
        SYSTEM_DIRS = {'Pal', 'Mods', '~mods', 'Content', 'Binaries'}
        MAX_DEPTH = 5
        
        for _ in range(MAX_DEPTH):
            entries = [e for e in dir_path.iterdir()
                      if e.name not in ('.DS_Store', 'Thumbs.db', 'modpack.json')]
            if len(entries) != 1 or not entries[0].is_dir():
                break
            child = entries[0]
            # Always unwrap system dirs
            if child.name in SYSTEM_DIRS:
                dir_path = child
            # Also unwrap a single wrapper directory if it contains Pal/ inside
            elif (child / 'Pal').is_dir():
                dir_path = child
            else:
                break
        return dir_path
    
    def import_mod_pack(self, pack_path: str) -> Tuple[int, int, List[str]]:
        """Smart import — auto-detects and imports any mod format.
        
        Handles:
        - Single .pak file
        - Single Lua mod directory / zip
        - Pal-root mod (中文名/Pal/Content/...)
        - Multi-mod pack folder / zip
        - Exported mod pack (Pal/Binaries/Win64/Mods + Pal/Content/Paks/~mods)
        
        Returns (success_count, skip_count, error_messages).
        """
        import shutil, tempfile
        
        source = Path(pack_path)
        tmp_dir = None
        zip_stem = None  # zip 文件名（用于中文显示名）
        
        # ── Phase 1: Unpack ──
        if source.is_file():
            if source.suffix.lower() == '.zip':
                zip_stem = source.stem
                try:
                    tmp_dir = tempfile.mkdtemp(prefix='pal_import_')
                    with zipfile.ZipFile(source, 'r') as zf:
                        zf.extractall(tmp_dir)
                    source = Path(tmp_dir)
                except Exception as e:
                    if tmp_dir:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    return 0, 0, [f"解压失败: {e}"]
            elif source.suffix.lower() in ('.7z', '.001'):
                # 7z archive support
                zip_stem = source.stem
                try:
                    import py7zr
                    tmp_dir = tempfile.mkdtemp(prefix='pal_import_')
                    with py7zr.SevenZipFile(source, mode='r') as zf:
                        zf.extractall(path=tmp_dir)
                    source = Path(tmp_dir)
                except ImportError:
                    if tmp_dir:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    return 0, 0, ["需要 py7zr 才能解压 7z 文件"]
                except Exception as e:
                    if tmp_dir:
                        shutil.rmtree(tmp_dir, ignore_errors=True)
                    return 0, 0, [f"7z 解压失败: {e}"]
            elif source.suffix.lower() == '.pak':
                # Single PAK file — install directly
                return self._import_raw_pak(source)
            else:
                return 0, 0, [f"不支持的文件格式: {source.suffix}"]
        
        if not source.is_dir():
            return 0, 0, ["来源不存在"]
        
        try:
            # ── Phase 2: Flatten wrapper layers ──
            source = self._flatten_for_import(source)
            
            # ── Phase 3: Discover what we have ──
            # Pass parent name as fallback display name (e.g. when user
            # drops a single Pal-root mod folder like 更好的夜晚/)
            items = self._classify_import_items(source, zip_stem, parent_name=source.parent.name)
            
            if not items:
                # Nothing classified — try raw PAK files
                pak_files = list(source.glob('*.pak'))
                if pak_files:
                    return self._import_raw_pak_files(pak_files)
                return 0, 0, ["未识别到可导入的 Mod"]
            
            # ── Phase 4: Install each item ──
            success, skip = 0, 0
            errors = []
            
            for item in items:
                s, sk = self._install_classified_mod(item)
                success += s
                skip += sk
            
            self.refresh()
            self._update_ue4ss_mods_txt()
            
            return success, skip, errors
            
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    
    def _flatten_for_import(self, root: Path) -> Path:
        """Strip unnecessary single-directory wrappers.
        
        Unwraps if the directory contains exactly one subdirectory AND
        that subdirectory either contains Pal/ inside or IS the Pal/ dir itself.
        Stops as soon as we reach Pal/ or real mod content.
        """
        for _ in range(5):
            entries = [e for e in root.iterdir()
                       if e.name not in ('.DS_Store', 'Thumbs.db', 'modpack.json')
                       and not (e.is_file() and e.name.lower().endswith(('.txt','.md')))]
            if len(entries) != 1 or not entries[0].is_dir():
                break
            child = entries[0]
            # If child IS Pal/ — unwrap into it then STOP
            if child.name == 'Pal':
                root = child
                break
            # If child contains Pal/ — it's a wrapper, unwrap and continue
            if (child / 'Pal').is_dir():
                root = child
            else:
                break
        return root
    
    def _classify_import_items(self, root: Path, zip_stem: str = None, parent_name: str = None) -> list:
        """Scan root and classify everything inside into import-ready items.
        
        Each item is a dict:
          { 'type': 'pal_root'|'lua_mod'|'pak_mods'|'exported_pack',
            'path': Path,
            'display_name': str or None }
        
        parent_name: name of the directory that CONTAINS root/ (used for
        display name when root is the Pal/ subtree and zip_stem is not set).
        """
        items = []
        
        # Helper: read name from mod.json / info.json inside a mod directory
        import json as _json
        def _dir_mod_name(dir_path: Path) -> str:
            for fname in ('mod.json', 'info.json'):
                mj = dir_path / fname
                if mj.is_file():
                    try:
                        meta = _json.loads(mj.read_text('utf-8', errors='ignore'))
                        return meta.get('name') or meta.get('display_name') or meta.get('title') or ''
                    except Exception:
                        pass
            return ''
        
        # ── Already inside Pal/ — delegate to direct path detection ──
        if root.name == 'Pal':
            # Direct mods path: Pal/Binaries/Win64/Mods/
            # Also: Pal/Binaries/Win64/ue4ss/Mods/ (some mod packs)
            mods_dir = root / 'Binaries' / 'Win64' / 'Mods'
            ue4ss_mods_dir = root / 'Binaries' / 'Win64' / 'ue4ss' / 'Mods'
            paks_dir = root / 'Content' / 'Paks' / '~mods'
            paks_mods_dir = root / 'Content' / 'Paks' / 'Mods'  # some mod packs use Mods/ under Paks/
            logicmods_dir = root / 'Content' / 'Paks' / 'LogicMods'
            
            # Helper: read companion .json for PAK file (exported packs
            # have a <pak_stem>.json next to each PAK with proper display name)
            import json
            def _pak_display_name(pak_file: Path) -> str:
                # First check stem-based json
                json_file = pak_file.with_name(pak_file.stem + '.json')
                if not json_file.exists():
                    # Try suffix-based json
                    json_file = pak_file.with_suffix('.json')
                if json_file.exists():
                    try:
                        meta = json.loads(json_file.read_text('utf-8', errors='ignore'))
                        name = meta.get('name') or meta.get('display_name')
                        if name:
                            return name
                    except Exception:
                        pass
                return ''
            
            # Display name for PAKs inside Pal/: prefer the companion JSON
            # (correct Chinese name from export), then zip_stem, then parent
            pak_display = zip_stem or parent_name
            
            # Read description from parent folder's 说明.txt
            def _read_parent_desc(parent: Path) -> str:
                for fname in ('说明.txt', '使用说明.txt', 'README.txt', 'readme.txt'):
                    f = parent / fname
                    if f.is_file():
                        try:
                            return f.read_text('utf-8', errors='ignore').strip()[:2000]
                        except Exception:
                            return ''
                return ''
            
            parent_desc = _read_parent_desc(root.parent)
            
            if mods_dir.exists():
                for entry in mods_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    if entry.name.lower() in self.scanner.UE4SS_BUILTIN_MODS:
                        continue
                    # Read description from mod's own 说明.txt if present
                    mod_desc = ''
                    for fname in ('说明.txt', '使用说明.txt', 'README.txt'):
                        f = entry / fname
                        if f.is_file():
                            try:
                                mod_desc = f.read_text('utf-8', errors='ignore').strip()[:2000]
                            except Exception:
                                pass
                            break
                    json_name = _dir_mod_name(entry)
                    items.append({
                        'type': 'lua_mod',
                        'path': entry,
                        'display_name': json_name or zip_stem or parent_name or entry.name,
                        'description': mod_desc,
                    })
            # Also scan ue4ss/Mods/ (some mod packs place mods there)
            if ue4ss_mods_dir.exists():
                for entry in ue4ss_mods_dir.iterdir():
                    if not entry.is_dir():
                        continue
                    if entry.name.lower() in self.scanner.UE4SS_BUILTIN_MODS:
                        continue
                    mod_desc = ''
                    for fname in ('说明.txt', '使用说明.txt', 'README.txt'):
                        f = entry / fname
                        if f.is_file():
                            try:
                                mod_desc = f.read_text('utf-8', errors='ignore').strip()[:2000]
                            except Exception:
                                pass
                            break
                    json_name = _dir_mod_name(entry)
                    items.append({
                        'type': 'lua_mod',
                        'path': entry,
                        'display_name': json_name or zip_stem or parent_name or entry.name,
                        'description': mod_desc,
                    })
            if paks_dir.exists():
                for pak in paks_dir.iterdir():
                    if pak.suffix.lower() == '.pak' or pak.name.lower().endswith('.pak_disabled'):
                        json_name = _pak_display_name(pak)
                        items.append({
                            'type': 'pak_mods',
                            'path': pak,
                            'display_name': json_name or pak_display or pak.stem.replace('_P', ''),
                            'description': parent_desc,
                        })
            # Also scan Paks/Mods/ (some mod packs use this instead of ~mods)
            if paks_mods_dir.exists():
                for pak in paks_mods_dir.iterdir():
                    if pak.suffix.lower() == '.pak' or pak.name.lower().endswith('.pak_disabled'):
                        json_name = _pak_display_name(pak)
                        items.append({
                            'type': 'pak_mods',
                            'path': pak,
                            'display_name': json_name or pak_display or pak.stem.replace('_P', ''),
                            'description': parent_desc,
                        })
            if logicmods_dir.exists():
                for pak in logicmods_dir.iterdir():
                    if pak.suffix.lower() == '.pak' or pak.name.lower().endswith('.pak_disabled'):
                        json_name = _pak_display_name(pak)
                        items.append({
                            'type': 'logicmod_pak',
                            'path': pak,
                            'display_name': json_name or pak_display or pak.stem,
                            'description': parent_desc,
                        })
            return items
        
        # ── Exported mod pack: Pal/Binaries/Win64/Mods + ~mods ──
        if (root / 'Pal').is_dir():
            # Has Pal/ inside — treat as exported pack root
            return self._classify_import_items(root / 'Pal', zip_stem, parent_name=root.name)
        
        # ── Flat Mods/ and ~mods/ ──
        src_mods = root / 'Mods'
        src_paks = root / '~mods'
        
        # ── Collect mod directories ──
        mod_dirs = []
        if src_mods.exists():
            mod_dirs.extend(src_mods.iterdir())
        else:
            # No Mods/ dir — scan root directly for mod candidates
            # But skip system dirs and Pal/
            for entry in root.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name in ('Pal', 'Mods', '~mods', 'Content', 'Binaries'):
                    continue
                mod_dirs.append(entry)
        
        for entry in mod_dirs:
            if not entry.is_dir():
                continue
            name_lower = entry.name.lower()
            # Skip UE4SS builtins
            if name_lower in self.scanner.UE4SS_BUILTIN_MODS:
                continue
            # Skip mods.txt
            if name_lower == 'mods.txt':
                continue
            
            # Ali213 installer format: empty tree + files/Pal/ containing actual files
            # e.g. 100%掉落率/files/Pal/Content/Paks/~mods/xxx.pak
            ali213_pal = entry / 'files' / 'Pal'
            if ali213_pal.is_dir():
                # Read description from modinfo.ini or 说明.txt
                desc = ''
                for fn in ('说明.txt', '使用说明.txt', 'modinfo.ini'):
                    f = entry / fn
                    if f.is_file():
                        try:
                            desc = f.read_text('utf-8', errors='ignore').strip()[:2000]
                        except Exception:
                            pass
                        break
                items.append({
                    'type': 'pal_root',
                    'path': ali213_pal.parent,  # 'files/' (contains Pal/)
                    'display_name': entry.name,
                    'description': desc,
                })
                continue
            
            # Pal-root mod: xxx/Pal/Content/... or xxx/Pal/Binaries/...
            if (entry / 'Pal').is_dir():
                # Read description from root level (e.g. 一秒下蛋/说明.txt)
                desc = ''
                for fname in ('说明.txt', '使用说明.txt', 'README.txt'):
                    f = entry / fname
                    if f.is_file():
                        try:
                            desc = f.read_text('utf-8', errors='ignore').strip()[:2000]
                        except Exception:
                            pass
                        break
                items.append({
                    'type': 'pal_root',
                    'path': entry,
                    'display_name': entry.name,
                    'description': desc,
                })
            # PAK mod directory (folder with .pak+.ucas+.utoc, no Pal/ or LogicMods/ prefix)
            # → 拆成扁平文件安装到 ~mods/，跟其他 PAK mod 一样
            pak_files = [
                f for f in entry.iterdir()
                if f.suffix.lower() in ('.pak', '.ucas', '.utoc')
            ]
            if pak_files:
                display = zip_stem or entry.name
                for pf in pak_files:
                    items.append({
                        'type': 'pak_file',
                        'path': pf,
                        'display_name': display,
                        'description': '',
                    })
            # Lua mod directory
            else:
                # Quick check: does it have scripts or lua files?
                has_content = (entry / 'Scripts').is_dir() or list(entry.glob('*.lua'))
                if has_content or any(entry.glob('*')):
                    # Read description from mod's own files
                    mod_desc = ''
                    for fname in ('说明.txt', '使用说明.txt', 'README.txt'):
                        f = entry / fname
                        if f.is_file():
                            try:
                                mod_desc = f.read_text('utf-8', errors='ignore').strip()[:2000]
                            except Exception:
                                pass
                            break
                    json_name = _dir_mod_name(entry)
                    items.append({
                        'type': 'lua_mod',
                        'path': entry,
                        'display_name': json_name or zip_stem or entry.name,
                        'description': mod_desc,
                    })
        
        # ── Collect ~mods/ PAK files ──
        if src_paks.exists():
            import json as _json
            for pak_file in src_paks.iterdir():
                if pak_file.suffix.lower() == '.pak' or pak_file.name.lower().endswith('.pak_disabled'):
                    # Try companion JSON first
                    display = ''
                    json_file = pak_file.with_name(pak_file.stem + '.json')
                    if not json_file.exists():
                        json_file = pak_file.with_suffix('.json')
                    if json_file.exists():
                        try:
                            meta = _json.loads(json_file.read_text('utf-8', errors='ignore'))
                            display = meta.get('name') or meta.get('display_name') or ''
                        except Exception:
                            pass
                    items.append({
                        'type': 'pak_mods',
                        'path': pak_file,
                        'display_name': display or zip_stem or pak_file.stem.replace('_P', ''),
                        'description': '',
                    })
        
        # ── Collect LogicMods/ PAK files ──
        src_logicmods = root / 'LogicMods'
        if src_logicmods.exists():
            import json as _json
            for pak_file in src_logicmods.iterdir():
                if pak_file.suffix.lower() == '.pak' or pak_file.name.lower().endswith('.pak_disabled'):
                    display = ''
                    json_file = pak_file.with_name(pak_file.stem + '.json')
                    if not json_file.exists():
                        json_file = pak_file.with_suffix('.json')
                    if json_file.exists():
                        try:
                            meta = _json.loads(json_file.read_text('utf-8', errors='ignore'))
                            display = meta.get('name') or meta.get('display_name') or ''
                        except Exception:
                            pass
                    items.append({
                        'type': 'logicmod_pak',
                        'path': pak_file,
                        'display_name': display or zip_stem or pak_file.stem,
                        'description': '',
                    })
        
        return items
    
    def _install_classified_mod(self, item: dict) -> Tuple[int, int]:
        """Install a single classified mod item. Returns (success, skip)."""
        import shutil
        target_mods = self.scanner.mods_dir
        target_paks = self.scanner.paks_dir
        target_mods.mkdir(parents=True, exist_ok=True)
        target_paks.mkdir(parents=True, exist_ok=True)
        
        if item['type'] == 'pal_root':
            result = self._install_pal_root_mod(item['path'],
                description=item.get('description', ''),
                display_name=item.get('display_name', ''))
            return (1, 0) if result else (0, 1)
        
        elif item['type'] == 'lua_mod':
            dest = target_mods / item['path'].name
            if dest.exists():
                return (0, 1)
            shutil.copytree(str(item['path']), str(dest))
            display = item.get('display_name')
            desc = item.get('description', '')
            if (display and display != item['path'].name) or desc:
                self._write_mod_metadata(str(dest), display or item['path'].name, desc)
            return (1, 0)
        
        elif item['type'] == 'pak_mods':
            dest = target_paks / item['path'].name
            display = item.get('display_name')
            desc = item.get('description', '')
            if dest.exists():
                # Already installed — always update metadata
                if display:
                    self._write_mod_metadata(str(dest), display, desc)
                return (0, 1)
            self._copy_pak_bundle(item['path'], target_paks)
            if display:
                self._write_mod_metadata(str(dest), display, desc)
            return (1, 0)
        
        elif item['type'] == 'logicmod_pak':
            target_lm = self.scanner.paks_dir.parent / 'LogicMods'
            target_lm.mkdir(parents=True, exist_ok=True)
            dest = target_lm / item['path'].name
            display = item.get('display_name')
            desc = item.get('description', '')
            if dest.exists():
                if display:
                    self._write_mod_metadata(str(dest), display, desc)
                return (0, 1)
            self._copy_pak_bundle(item['path'], target_lm)
            if display:
                self._write_mod_metadata(str(dest), display, desc)
            return (1, 0)
        
        elif item['type'] == 'pak_file':
            # Single .pak/.ucas/.utoc file → flat copy to ~mods/
            dest = target_paks / item['path'].name
            if dest.exists():
                return (0, 1)
            self._copy_pak_bundle(item['path'], target_paks)
            display = item.get('display_name')
            if display:
                self._write_mod_metadata(str(dest), display, item.get('description', ''))
            return (1, 0)
        
        elif item['type'] == 'pak_dir':
            dest = target_paks / item['path'].name
            if dest.exists():
                return (0, 1)
            shutil.copytree(str(item['path']), str(dest))
            display = item.get('display_name')
            if display:
                self._write_mod_metadata(str(dest), display, item.get('description', ''))
            return (1, 0)
        
        return (0, 1)
    
    def _import_raw_pak(self, pak_path: Path) -> Tuple[int, int, List[str]]:
        """Import a single .pak file directly."""
        import shutil
        target = self.scanner.paks_dir / pak_path.name
        if target.exists():
            return 0, 1, []
        copied, skipped = self._copy_pak_bundle(pak_path, self.scanner.paks_dir)
        self.refresh()
        return copied, skipped, []
    
    def _import_raw_pak_files(self, pak_paths: List[Path]) -> Tuple[int, int, List[str]]:
        """Import a list of .pak files."""
        import shutil
        target_paks = self.scanner.paks_dir
        target_paks.mkdir(parents=True, exist_ok=True)
        success, skip = 0, 0
        for p in pak_paths:
            dest = target_paks / p.name
            if dest.exists():
                skip += 1
            else:
                copied, skipped = self._copy_pak_bundle(p, target_paks)
                success += copied
                skip += skipped
        self.refresh()
        return success, skip, []
