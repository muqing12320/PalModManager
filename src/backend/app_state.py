"""Shared application state for the backend API."""
from __future__ import annotations

from typing import Optional

from ..core.manager import ModManager
from ..utils.config import AppConfig


class AppState:
    """Holds shared state across API requests."""

    def __init__(self):
        self.config = AppConfig()
        self.game_manager: Optional[ModManager] = None
        self.server_manager: Optional[ModManager] = None

    def get_game_manager(self, game_path: str = None) -> Optional[ModManager]:
        """Get or create the game client ModManager."""
        path = game_path or self.config.game_path
        if not path:
            return None
        if self.game_manager is None or str(self.game_manager.game_dir) != str(path):
            self.game_manager = ModManager(str(path))
        return self.game_manager

    def get_server_manager(self, server_path: str = None) -> Optional[ModManager]:
        """Get or create the server ModManager."""
        path = server_path or self.config.server_path
        if not path:
            return None
        if self.server_manager is None or str(self.server_manager.game_dir) != str(path):
            self.server_manager = ModManager(str(path))
        return self.server_manager

    def refresh_managers(self):
        """Refresh all active managers."""
        if self.game_manager is not None:
            self.game_manager.refresh()
        if self.server_manager is not None:
            self.server_manager.refresh()


# Global state instance
_state: Optional[AppState] = None


def get_state() -> AppState:
    """Get the global app state instance."""
    global _state
    if _state is None:
        _state = AppState()
    return _state
