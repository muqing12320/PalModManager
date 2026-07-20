"""
Application configuration management.
Handles persistent settings like game path, window state, preferences.
"""
import os
import json
from pathlib import Path
from typing import Optional, Any, Dict


class AppConfig:
    """Manages application configuration and preferences."""
    
    DEFAULT_CONFIG = {
        'game_path': '',
        'server_path': '',
        'language': 'zh_CN',
        'theme': 'dark',
        'auto_refresh': True,
        'refresh_interval': 30,
        'backup_enabled': True,
        'backup_path': '',
        'auto_check_updates': True,
        'last_used_profile': '',
        'window_geometry': None,
        'window_state': None,
        'splitter_sizes': [300, 600],
        'show_disabled_mods': True,
        'confirm_before_uninstall': True,
        'confirm_before_disable_all': True,
        'ue4ss_auto_configure': True,
        'log_level': 'INFO',
        'nexus_api_key': '',  # Optional: for Nexus Mods integration
    }
    
    def __init__(self):
        self._config_dir = self._get_config_dir()
        self._config_file = self._config_dir / "config.json"
        self._data: Dict[str, Any] = self.DEFAULT_CONFIG.copy()
        self._load()
    
    @staticmethod
    def _get_config_dir() -> Path:
        """Get the configuration directory."""
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        config_dir = Path(base) / "帕鲁Mod管理器"
        return config_dir
    
    @property
    def config_dir(self) -> Path:
        return self._config_dir
    
    def _load(self):
        """Load configuration from disk."""
        self._config_dir.mkdir(parents=True, exist_ok=True)
        
        if self._config_file.exists():
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                # Merge with defaults (in case new options were added)
                self._data = {**self.DEFAULT_CONFIG, **saved}
            except (json.JSONDecodeError, IOError):
                self._data = self.DEFAULT_CONFIG.copy()
                self._save()
        else:
            self._save()
    
    def _save(self):
        """Save configuration to disk."""
        try:
            self._config_dir.mkdir(parents=True, exist_ok=True)
            with open(self._config_file, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except IOError:
            pass
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._data.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a configuration value and save."""
        self._data[key] = value
        self._save()
    
    def update(self, values: Dict[str, Any]):
        """Update multiple configuration values at once."""
        self._data.update(values)
        self._save()
    
    def reset(self):
        """Reset configuration to defaults."""
        self._data = self.DEFAULT_CONFIG.copy()
        self._save()
    
    @property
    def game_path(self) -> str:
        return self.get('game_path', '')
    
    @game_path.setter
    def game_path(self, value: str):
        self.set('game_path', value)
    
    @property
    def server_path(self) -> str:
        return self.get('server_path', '')
    
    @server_path.setter
    def server_path(self, value: str):
        self.set('server_path', value)
    
    @property
    def theme(self) -> str:
        return self.get('theme', 'dark')
    
    @theme.setter
    def theme(self, value: str):
        self.set('theme', value)
    
    @property
    def language(self) -> str:
        return self.get('language', 'zh_CN')
    
    @language.setter
    def language(self, value: str):
        self.set('language', value)
    
    def to_dict(self) -> Dict[str, Any]:
        return self._data.copy()
