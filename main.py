"""
帕鲁Mod管理器 - Entry Point
A comprehensive mod manager for Palworld with UE4SS and PalSchema support.
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

from src.ui.main_window import MainWindow
from src.utils.config import AppConfig
from src.utils.updater import finish_pending_update, cleanup_update_leftovers


def main():
    """Main entry point."""
    # 自更新流程：若以 --apply-update 启动，这里会完成文件替换并退出
    if finish_pending_update():
        return

    # 清理上次更新可能残留的临时文件
    cleanup_update_leftovers()

    # Enable high DPI scaling
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    app = QApplication(sys.argv)
    app.setApplicationName("帕鲁Mod管理器")
    app.setOrganizationName("PalModManager")
    app.setApplicationVersion("1.0.0")
    
    # Set default font
    font = QFont("Segoe UI", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    
    # Load config
    config = AppConfig()
    
    # Create and show main window
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
