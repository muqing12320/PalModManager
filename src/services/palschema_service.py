"""
PalSchema Integration Service - manages PalSchema configuration mods.
PalSchema is a modding framework for Palworld that uses JSON config files
to modify game data (creatures, items, recipes, etc.).
"""
import os
import json
import shutil
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
from collections import OrderedDict


class PalSchemaService:
    """Manages PalSchema configuration and mod editing."""
    
    # PalSchema configuration file categories
    CONFIG_CATEGORIES = {
        'pals': 'Pal data (stats, skills, drops)',
        'items': 'Item data (weapons, armor, consumables)',
        'recipes': 'Crafting recipes',
        'buildings': 'Building/structure data',
        'technologies': 'Technology/tech tree data',
        'skills': 'Active/passive skills',
        'npcs': 'NPC and merchant data',
        'dungeons': 'Dungeon/boss data',
        'world': 'World settings and spawns',
        'localization': 'Text/translation overrides',
    }
    
    # Known PalSchema config file patterns
    KNOWN_CONFIGS = {
        'DT_PalMonsterParameter.json': 'pals',
        'DT_PalItemData.json': 'items',
        'DT_RecipeData.json': 'recipes',
        'DT_BuildObjectData.json': 'buildings',
        'DT_TechnologyData.json': 'technologies',
        'DT_PalSkillData.json': 'skills',
        'DT_PalNPCData.json': 'npcs',
        'DT_DungeonData.json': 'dungeons',
        'DT_FieldLotteryNameData.json': 'world',
    }
    
    def __init__(self, game_path: str):
        self.game_path = Path(game_path)
        self._palschema_path = self.game_path / "Pal" / "Binaries" / "Win64" / "Mods" / "PalSchema"
        self._cache: Dict[str, Any] = {}
    
    @property
    def palschema_dir(self) -> Path:
        return self._palschema_path
    
    def is_installed(self) -> bool:
        """Check if PalSchema is installed.
        PalSchema v0.5+ is installed as a UE4SS mod under Mods/PalSchema/.
        Older versions had a separate PalSchema.dll.
        """
        target_dir = self.game_path / "Pal" / "Binaries" / "Win64"
        mods_palschema = target_dir / "Mods" / "PalSchema"
        
        # 1. Check for the older PalSchema.dll (legacy v0.4 and below)
        dll_locations = [
            target_dir / "PalSchema.dll",
            mods_palschema / "PalSchema.dll",
            target_dir / "ue4ss" / "Mods" / "PalSchema" / "PalSchema.dll",
        ]
        
        for dll_path in dll_locations:
            if dll_path.exists():
                return True
        
        # Glob for any palschema-named DLL
        for pattern in ["*palschema*.dll", "*PalSchema*.dll", "*PSchema*.dll"]:
            for candidate in target_dir.glob(pattern):
                return True
            for candidate in mods_palschema.glob(pattern):
                return True
        
        # 2. Check for v0.5+ UE4SS mod structure
        # The mod should contain: a main.lua script OR a Scripts/ folder OR .json config files
        if mods_palschema.is_dir():
            # Check for main.lua directly in the mod folder
            if (mods_palschema / "main.lua").exists():
                return True
            
            # Check for Scripts/ subdirectory
            if (mods_palschema / "Scripts").is_dir():
                scripts_dir = mods_palschema / "Scripts"
                if any(scripts_dir.glob("*.lua")):
                    return True
            
            # Check for any lua files anywhere
            if any(mods_palschema.rglob("*.lua")):
                return True
            
            # Check for .json or .jsonc config files (PalSchema config format)
            if any(mods_palschema.rglob("*.json")) or any(mods_palschema.rglob("*.jsonc")):
                return True
            
            # Check for any DLL anywhere in the mod (PalSchema 0.6+ uses dlls/main.dll)
            if any(mods_palschema.rglob("*.dll")):
                return True
            
            # Check for assets / scripts / schemas / dlls subdirectory
            for subdir_name in ["assets", "schemas", "config", "data", "src", "dlls", "libs"]:
                if (mods_palschema / subdir_name).is_dir():
                    if any((mods_palschema / subdir_name).iterdir()):
                        return True
        
        return False
    
    def get_version(self) -> Optional[str]:
        """Get PalSchema version if available."""
        version_file = self._palschema_path / "version.txt"
        if version_file.exists():
            try:
                return version_file.read_text().strip()
            except Exception:
                pass
        return None
    
    def get_all_config_mods(self) -> List[Dict]:
        """Get all PalSchema config mod directories and their contents."""
        mods = []
        
        if not self._palschema_path.exists():
            return mods
        
        for item in self._palschema_path.iterdir():
            if not item.is_dir():
                continue
            
            config_files = list(item.glob('*.json')) + list(item.glob('*.yml'))
            if not config_files:
                continue
            
            mod_info = {
                'name': item.name,
                'path': str(item),
                'enabled': (item / 'enabled.txt').exists(),
                'disabled': (item / 'disabled.txt').exists(),
                'config_files': [cf.name for cf in config_files],
                'category': self._detect_category(config_files),
                'size': sum(f.stat().st_size for f in config_files),
                'modified': datetime.fromtimestamp(max(f.stat().st_mtime for f in config_files)).isoformat(),
            }
            
            mods.append(mod_info)
        
        return mods
    
    def read_config(self, config_path: str) -> Optional[Dict]:
        """Read a PalSchema JSON config file."""
        path = Path(config_path)
        
        if not path.exists():
            return None
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            self._cache[config_path] = data
            return data
        except (json.JSONDecodeError, IOError) as e:
            return None
    
    def write_config(self, config_path: str, data: Dict) -> bool:
        """Write a PalSchema JSON config file."""
        path = Path(config_path)
        
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._cache[config_path] = data
            return True
        except IOError as e:
            return False
    
    def create_config_mod(self, name: str, config_files: Dict[str, Dict]) -> Tuple[bool, str]:
        """Create a new PalSchema config mod directory with config files."""
        mod_dir = self._palschema_path / name
        
        if mod_dir.exists():
            return False, f"Mod '{name}' already exists"
        
        try:
            mod_dir.mkdir(parents=True, exist_ok=True)
            
            # Create enabled.txt
            (mod_dir / "enabled.txt").write_text("enabled")
            
            # Write config files
            for filename, content in config_files.items():
                file_path = mod_dir / filename
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(content, f, indent=2, ensure_ascii=False)
            
            return True, str(mod_dir)
        except Exception as e:
            return False, str(e)
    
    def delete_config_mod(self, mod_name: str) -> Tuple[bool, str]:
        """Delete a PalSchema config mod directory."""
        mod_dir = self._palschema_path / mod_name
        
        if not mod_dir.exists():
            return False, f"Mod '{mod_name}' not found"
        
        try:
            shutil.rmtree(mod_dir)
            return True, f"Deleted '{mod_name}'"
        except Exception as e:
            return False, str(e)
    
    def enable_config_mod(self, mod_name: str) -> Tuple[bool, str]:
        """Enable a PalSchema config mod."""
        mod_dir = self._palschema_path / mod_name
        
        if not mod_dir.exists():
            return False, f"Mod '{mod_name}' not found"
        
        try:
            (mod_dir / "enabled.txt").write_text("enabled")
            disable_file = mod_dir / "disabled.txt"
            if disable_file.exists():
                disable_file.unlink()
            return True, f"Enabled '{mod_name}'"
        except Exception as e:
            return False, str(e)
    
    def disable_config_mod(self, mod_name: str) -> Tuple[bool, str]:
        """Disable a PalSchema config mod."""
        mod_dir = self._palschema_path / mod_name
        
        if not mod_dir.exists():
            return False, f"Mod '{mod_name}' not found"
        
        try:
            (mod_dir / "disabled.txt").write_text("disabled")
            enable_file = mod_dir / "enabled.txt"
            if enable_file.exists():
                enable_file.unlink()
            return True, f"Disabled '{mod_name}'"
        except Exception as e:
            return False, str(e)
    
    def merge_configs(self, source_mod: str, target_mod: str) -> Tuple[bool, str]:
        """Merge config files from one mod into another."""
        source_dir = self._palschema_path / source_mod
        target_dir = self._palschema_path / target_mod
        
        if not source_dir.exists():
            return False, f"Source mod '{source_mod}' not found"
        if not target_dir.exists():
            return False, f"Target mod '{target_mod}' not found"
        
        try:
            for config_file in source_dir.glob('*.json'):
                source_data = self.read_config(str(config_file))
                target_file = target_dir / config_file.name
                
                if target_file.exists():
                    target_data = self.read_config(str(target_file))
                    if isinstance(source_data, dict) and isinstance(target_data, dict):
                        merged = self._deep_merge(target_data, source_data)
                        self.write_config(str(target_file), merged)
                else:
                    shutil.copy2(config_file, target_file)
            
            return True, f"Merged '{source_mod}' into '{target_mod}'"
        except Exception as e:
            return False, str(e)
    
    def validate_config(self, config_path: str) -> Tuple[bool, List[str]]:
        """Validate a PalSchema config file."""
        path = Path(config_path)
        issues = []
        
        if not path.exists():
            return False, ["File not found"]
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Basic structure validation
            if not isinstance(data, (dict, list)):
                issues.append("Root must be an object or array")
            
            # Check for common issues
            if isinstance(data, list):
                for i, item in enumerate(data):
                    if isinstance(item, dict) and 'Id' not in item and 'id' not in item:
                        issues.append(f"Item {i} missing 'Id' field")
            
            return len(issues) == 0, issues
        except json.JSONDecodeError as e:
            return False, [f"JSON parse error: {str(e)}"]
        except Exception as e:
            return False, [str(e)]
    
    def get_config_templates(self) -> Dict[str, Dict]:
        """Get template config structures for common PalSchema mods."""
        return {
            'new_pal': {
                'Id': 'CustomPal_001',
                'Name': 'TEXT_CustomPal_001',
                'HP': 100,
                'MeleeAttack': 70,
                'ShotAttack': 50,
                'Defense': 50,
                'Support': 100,
                'CraftSpeed': 100,
                'EnemyReceiveDamageRate': 1.0,
                'CaptureRateCorrect': 1.0,
                'ExpRatio': 1.0,
                'Price': 1000,
                'SlowWalkSpeed': 100,
                'WalkSpeed': 150,
                'RunSpeed': 350,
                'RideSprintSpeed': 500,
                'TransportSpeed': 200,
                'Stamina': 100,
                'FullStomach': 300,
                'MaleProbability': 50,
                'CombiRank': 500,
                'Size': '中型',
            },
            'new_item': {
                'Id': 'CustomItem_001',
                'Name': 'TEXT_CustomItem_001',
                'Description': 'TEXT_CustomItem_001_DESC',
                'TypeA': 'Weapon',
                'TypeB': 'HandGun',
                'Rank': 1,
                'Rarity': 1,
                'Price': 500,
                'MaxStackCount': 1,
                'SortID': 9999,
                'Weight': 5.0,
                'Durability': 100,
                'PhysicalAttackValue': 50,
                'TechnologyTreeLock': 'None',
                'ItemStaticClass': 'None',
                'Icon': {
                    'StaticMesh': 'None',
                },
            },
            'new_recipe': {
                'Id': 'CustomRecipe_001',
                'Product_Id': 'CustomItem_001',
                'Product_Count': 1,
                'Material1_Id': 'Stone',
                'Material1_Count': 10,
                'Material2_Id': 'Wood',
                'Material2_Count': 5,
                'WorkAmount': 50.0,
                'EnergyType': 'Electricity',
                'ProductType': 'Weapon',
            },
        }
    
    def export_config_mod(self, mod_name: str, output_path: str) -> Tuple[bool, str]:
        """Export a config mod to a zip file."""
        import zipfile
        
        mod_dir = self._palschema_path / mod_name
        
        if not mod_dir.exists():
            return False, f"Mod '{mod_name}' not found"
        
        try:
            with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file_path in mod_dir.rglob('*'):
                    if file_path.is_file():
                        arcname = file_path.relative_to(mod_dir)
                        zf.write(file_path, arcname)
            
            return True, output_path
        except Exception as e:
            return False, str(e)
    
    def import_config_mod(self, archive_path: str) -> Tuple[bool, str]:
        """Import a config mod from a zip file."""
        import zipfile
        
        archive = Path(archive_path)
        if not archive.exists():
            return False, f"Archive not found: {archive_path}"
        
        mod_name = archive.stem
        mod_dir = self._palschema_path / mod_name
        
        try:
            mod_dir.mkdir(parents=True, exist_ok=True)
            
            with zipfile.ZipFile(archive, 'r') as zf:
                zf.extractall(mod_dir)
            
            # Auto-enable
            (mod_dir / "enabled.txt").write_text("enabled")
            
            return True, mod_name
        except Exception as e:
            return False, str(e)
    
    # ---- Internal helpers ----
    
    def _detect_category(self, config_files: List[Path]) -> str:
        """Detect the category of a config mod based on its files."""
        for cf in config_files:
            name_lower = cf.name.lower()
            
            if 'pal' in name_lower and ('monster' in name_lower or 'parameter' in name_lower):
                return 'pals'
            if 'item' in name_lower:
                return 'items'
            if 'recipe' in name_lower:
                return 'recipes'
            if 'build' in name_lower:
                return 'buildings'
            if 'tech' in name_lower:
                return 'technologies'
            if 'skill' in name_lower:
                return 'skills'
            if 'npc' in name_lower:
                return 'npcs'
            if 'dungeon' in name_lower:
                return 'dungeons'
        
        return 'other'
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dicts, with override taking precedence."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                # For lists of dicts with Id, merge by Id
                if result[key] and isinstance(result[key][0], dict) and 'Id' in result[key][0]:
                    result[key] = self._merge_by_id(result[key], value)
                else:
                    result[key] = value
            else:
                result[key] = value
        
        return result
    
    def _merge_by_id(self, base_list: List[Dict], override_list: List[Dict]) -> List[Dict]:
        """Merge two lists of dicts by matching 'Id' field."""
        result = {item.get('Id', i): item for i, item in enumerate(base_list)}
        
        for item in override_list:
            item_id = item.get('Id', len(result))
            if item_id in result:
                result[item_id].update(item)
            else:
                result[item_id] = item
        
        return list(result.values())
