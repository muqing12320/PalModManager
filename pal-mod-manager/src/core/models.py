"""
Mod data model - represents a single mod installation.
"""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from enum import Enum


class ModType(Enum):
    """Types of mods supported."""
    UE4SS_LUA = "ue4ss_lua"          # Lua script mod (UE4SS)
    UE4SS_BLUEPRINT = "ue4ss_bp"     # Blueprint mod (UE4SS)
    PAK = "pak"                       # .pak file mod
    PALSCHEMA = "palschema"           # PalSchema config mod
    LOGIC = "logic_mod"               # LogicMod
    UNKNOWN = "unknown"


class ModStatus(Enum):
    """Installation/activation status of a mod."""
    ENABLED = "enabled"
    DISABLED = "disabled"
    CONFLICT = "conflict"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ModInfo:
    """Represents metadata and state for a single mod."""
    id: str                                    # Unique mod identifier
    name: str                                  # Display name
    version: str = "1.0.0"                     # Mod version
    author: str = "Unknown"                    # Mod author
    description: str = ""                      # Mod description
    mod_type: ModType = ModType.UNKNOWN        # Type of mod
    status: ModStatus = ModStatus.UNKNOWN      # Current status
    
    # File system paths
    install_path: str = ""                     # Where the mod is installed
    source_path: str = ""                      # Original source path
    
    # Dependencies
    dependencies: List[str] = field(default_factory=list)
    required_frameworks: List[str] = field(default_factory=list)  # e.g. ["UE4SS", "PalSchema"]
    
    # PalSchema specific
    palschema_configs: List[str] = field(default_factory=list)  # Config file paths
    
    # UE4SS specific
    ue4ss_main_script: str = ""                # Main Lua script path
    ue4ss_enabled_scripts: List[str] = field(default_factory=list)
    
    # Compatibility
    game_version_min: str = ""                 # Minimum game version
    game_version_max: str = ""                 # Maximum game version
    conflicts_with: List[str] = field(default_factory=list)
    
    # Metadata
    website: str = ""                          # Mod webpage / nexus URL
    tags: List[str] = field(default_factory=list)
    installed_date: str = ""                   # ISO date string
    last_updated: str = ""                     # ISO date string
    is_auto_managed: bool = True               # Whether managed by this tool
    
    # Raw metadata dict for extensibility
    raw_metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Convert to serializable dict."""
        d = asdict(self)
        d['mod_type'] = self.mod_type.value
        d['status'] = self.status.value
        return d
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ModInfo':
        """Create from dict, handling enum fields."""
        data = data.copy()
        if isinstance(data.get('mod_type'), str):
            data['mod_type'] = ModType(data['mod_type'])
        if isinstance(data.get('status'), str):
            data['status'] = ModStatus(data['status'])
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ModProfile:
    """A named profile (collection of enabled mods)."""
    name: str
    enabled_mods: List[str] = field(default_factory=list)  # Mod IDs
    description: str = ""
    created_date: str = ""
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'ModProfile':
        return cls(**data)
