"""
Main Application Window for 帕鲁Mod管理器.
"""
import os
import sys
import json
import time
import zipfile
import subprocess
from pathlib import Path
from datetime import datetime

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QToolBar, QAction, QMenu, QMenuBar, QStatusBar, QTabWidget,
    QMessageBox, QFileDialog, QApplication, QLabel, QPushButton,
    QSizePolicy,
)
from PyQt5.QtCore import Qt, QTimer, QSize, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont

from ..core.manager import ModManager
from ..core.models import ModInfo, ModStatus
from ..services.ue4ss_service import UE4SSService
from ..services.palschema_service import PalSchemaService
from ..utils.config import AppConfig
from ..utils.helpers import (
    get_status_display, format_date, launch_game, launch_palserver,
    is_valid_palworld_path, is_valid_palserver_path,
)

from .mod_list import ModListWidget
from .mod_detail import ModDetailPanel
from .settings_page import SettingsPage
from .profile_dialog import ProfileDialog
from .styles import create_stylesheet, get_toolbar_button_style, is_dark_theme


def _fmt_time(seconds: float) -> str:
    """把秒数格式化为 人类可读 的剩余/已用时间。"""
    if seconds is None or seconds < 0:
        return "-"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds} 秒"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m} 分 {s} 秒"
    h, m = divmod(m, 60)
    return f"{h} 时 {m} 分"


class UpdateDownloader(QThread):
    """在独立线程中下载更新，通过信号回报进度，避免卡住 UI。"""

    progress_changed = pyqtSignal(int, int, str)  # done, total, method
    download_finished = pyqtSignal(str)           # 临时文件路径
    download_failed = pyqtSignal(str)             # 错误信息
    canceled = pyqtSignal()                       # 用户取消

    def __init__(self, url: str, mirror: str = ''):
        super().__init__()
        self.url = url
        self.mirror = mirror
        self._cancelled = False

    def run(self):
        try:
            from ..utils.updater import download_update

            def on_progress(done, total):
                if self._cancelled:
                    return
                self.progress_changed.emit(done, total, "")

            # 让下载器在切换下载方式时通知 UI
            def on_method(method):
                if not self._cancelled:
                    self.progress_changed.emit(0, 0, method)

            saved = download_update(
                self.url,
                progress=on_progress,
                mirror=self.mirror,
                cancel_check=lambda: self._cancelled,
                method_cb=on_method,
            )
            if self._cancelled:
                return
            if saved:
                self.download_finished.emit(saved)
            else:
                self.download_failed.emit(
                    "下载失败：所有下载源均不可用或网络异常，请稍后重试。")
        except Exception as e:
            if not self._cancelled:
                self.download_failed.emit(f"下载出错：{e}")

    def cancel(self):
        if not self._cancelled:
            self._cancelled = True
            self.canceled.emit()


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self._config = AppConfig()
        self._mod_manager: ModManager = None
        self._server_mod_manager: ModManager = None
        self._current_mode = 'game'  # 'game' or 'server'
        
        self._init_window()
        self._init_ui()
        self.apply_theme()
        self._load_game_path()
        self._load_server_path()
        # 启动后自动检查更新（静默：只更新工具栏状态标签，不弹窗）
        QTimer.singleShot(2000, lambda: self._check_update(silent=True))
    
    def _init_window(self):
        """Initialize window properties."""
        self.setWindowTitle("帕鲁Mod管理器")
        self.setMinimumSize(1100, 700)
        self.resize(1200, 800)
        
        # Enable drag and drop
        self.setAcceptDrops(True)
        
        # Restore window geometry
        geometry = self._config.get('window_geometry')
        if geometry:
            try:
                self.restoreGeometry(bytes.fromhex(geometry))
            except Exception:
                pass
        
        state = self._config.get('window_state')
        if state:
            try:
                self.restoreState(bytes.fromhex(state))
            except Exception:
                pass
    
    def _init_ui(self):
        """Initialize the UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        # Menu bar
        self._create_menu_bar()
        
        # 顶部条（检查更新按钮 + 状态，独占最上方一行，不被启动游戏行挤压）
        self._create_top_bar()
        
        # Toolbar
        self._create_toolbar()
        
        # Main content
        self._create_content()
        
        # Status bar
        self._create_status_bar()
    
    def _create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("文件")
        
        export_action = QAction("导出Mod列表...", self)
        export_action.triggered.connect(self._export_mod_list)
        file_menu.addAction(export_action)
        
        import_action = QAction("导入Mod列表...", self)
        import_action.triggered.connect(self._import_mod_list)
        file_menu.addAction(import_action)
        
        scan_collection_action = QAction("扫描Mod合集目录...", self)
        scan_collection_action.triggered.connect(self._scan_mod_collection)
        file_menu.addAction(scan_collection_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("退出", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Mod菜单
        mods_menu = menubar.addMenu("Mod")
        
        refresh_action = QAction("刷新Mod列表", self)
        refresh_action.setShortcut("F5")
        refresh_action.triggered.connect(self._refresh_mods)
        mods_menu.addAction(refresh_action)
        
        mods_menu.addSeparator()
        
        enable_all_action = QAction("全部启用", self)
        enable_all_action.triggered.connect(self._enable_all_mods)
        mods_menu.addAction(enable_all_action)
        
        disable_all_action = QAction("全部禁用", self)
        disable_all_action.triggered.connect(self._disable_all_mods)
        mods_menu.addAction(disable_all_action)
        
        mods_menu.addSeparator()
        
        profiles_action = QAction("管理方案...", self)
        profiles_action.setShortcut("Ctrl+P")
        profiles_action.triggered.connect(self._manage_profiles)
        mods_menu.addAction(profiles_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu("工具")
        
        launch_action = QAction("启动幻兽帕鲁", self)
        launch_action.triggered.connect(self._launch_game)
        tools_menu.addAction(launch_action)
        
        tools_menu.addSeparator()
        
        open_game_dir_action = QAction("打开游戏目录", self)
        open_game_dir_action.triggered.connect(self._open_game_dir)
        tools_menu.addAction(open_game_dir_action)
        
        open_mods_dir_action = QAction("打开Mod目录", self)
        open_mods_dir_action.triggered.connect(self._open_mods_dir)
        tools_menu.addAction(open_mods_dir_action)
        
        tools_menu.addSeparator()
        
        view_logs_action = QAction("查看UE4SS日志", self)
        view_logs_action.triggered.connect(self._view_ue4ss_logs)
        tools_menu.addAction(view_logs_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("帮助")
        
        about_action = QAction("关于", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)
        
    def _create_top_bar(self):
        """顶部条（最上方独立一行，宽度自适应内容）：左侧放「检查更新」按钮与状态标签。
        启动自动检查不弹窗，仅在此处显示状态；不与「启动游戏」同一行。"""
        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_bar.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 6, 12, 6)
        top_layout.setSpacing(10)

        update_btn = QPushButton("检查更新")
        update_btn.setObjectName("checkUpdateBtn")
        update_btn.setToolTip("点击手动检查更新")
        update_btn.clicked.connect(self._check_update)
        update_btn.setStyleSheet(
            "QPushButton { background:#21262d; color:#c9d1d9; border:1px solid #30363d;"
            " border-radius:6px; padding:4px 14px; font-size:12px; font-weight:600; }"
            " QPushButton:hover { background:#30363d; }")
        top_layout.addWidget(update_btn)

        self.update_status_lbl = QLabel("")
        self.update_status_lbl.setObjectName("updateStatusLabel")
        top_layout.addWidget(self.update_status_lbl)

        self.centralWidget().layout().addWidget(top_bar)
    
    def _create_toolbar(self):
        """Create the toolbar."""
        toolbar = QToolBar("主工具栏")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.centralWidget().layout().addWidget(toolbar)
        
        # 客户端/服务器切换
        self.mode_switch_btn = QPushButton("客户端")
        self.mode_switch_btn.setToolTip("点击切换到服务器模式")
        self.mode_switch_btn.setStyleSheet(get_toolbar_button_style('mode'))
        self.mode_switch_btn.clicked.connect(self._toggle_mode)
        toolbar.addWidget(self.mode_switch_btn)
        
        toolbar.addSeparator()
        
        # 刷新
        refresh_btn = QPushButton("刷新")
        refresh_btn.setObjectName("refreshBtn")
        refresh_btn.clicked.connect(self._refresh_mods)
        toolbar.addWidget(refresh_btn)
        
        toolbar.addSeparator()
        
        # 安装
        # 全部启用/禁用
        enable_all_btn = QPushButton("全部启用")
        enable_all_btn.setObjectName("enableAllBtn")
        enable_all_btn.clicked.connect(self._enable_all_mods)
        toolbar.addWidget(enable_all_btn)
        
        disable_all_btn = QPushButton("全部禁用")
        disable_all_btn.setObjectName("disableAllBtn")
        disable_all_btn.clicked.connect(self._disable_all_mods)
        toolbar.addWidget(disable_all_btn)
        
        toolbar.addSeparator()
        
        # 批量操作
        delete_selected_btn = QPushButton("删除选中")
        delete_selected_btn.setStyleSheet(get_toolbar_button_style('delete'))
        delete_selected_btn.setToolTip("删除所有选中的Mod (按住Ctrl多选)")
        delete_selected_btn.clicked.connect(self._delete_selected_mods)
        toolbar.addWidget(delete_selected_btn)
        
        delete_all_btn = QPushButton("删除所有")
        delete_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #331b1b;
                color: #f85149;
                border: 1px solid #f8514944;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #442a2a; border-color: #f85149; }
        """)
        delete_all_btn.setToolTip("删除所有Mod（不可恢复！）")
        delete_all_btn.clicked.connect(self._delete_all_mods)
        toolbar.addWidget(delete_all_btn)
        
        toolbar.addSeparator()
        
        # 启动游戏
        launch_btn = QPushButton("启动游戏")
        launch_btn.setStyleSheet(get_toolbar_button_style('launch'))
        launch_btn.clicked.connect(self._launch_game)
        toolbar.addWidget(launch_btn)
        
        # Spacer
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        toolbar.addWidget(spacer)
        
        # Mode indicator
        self.mode_label = QLabel("客户端")
        self.mode_label.setStyleSheet("color: #58a6ff; padding: 0 8px; font-size: 11px; font-weight: 600;")
        toolbar.addWidget(self.mode_label)
        
        # Stats
        self.stats_label = QLabel("未设置游戏路径")
        self.stats_label.setObjectName("statLabel")
        toolbar.addWidget(self.stats_label)
    
    def _create_content(self):
        """Create the main content area."""
        # Tab widget for main views
        self.tab_widget = QTabWidget()
        
        # Mods tab
        mods_tab = QWidget()
        mods_layout = QVBoxLayout(mods_tab)
        mods_layout.setContentsMargins(0, 0, 0, 0)
        
        # Splitter for mod list and detail
        splitter = QSplitter(Qt.Horizontal)
        
        # Mod list (left)
        self.mod_list_widget = ModListWidget()
        self.mod_list_widget.mod_selected.connect(self._on_mod_selected)
        self.mod_list_widget.mod_toggled.connect(self._on_mod_toggled)
        splitter.addWidget(self.mod_list_widget)
        
        # Mod detail (right)
        self.mod_detail_panel = ModDetailPanel()
        self.mod_detail_panel.enable_clicked.connect(self._enable_mod)
        self.mod_detail_panel.disable_clicked.connect(self._disable_mod)
        self.mod_detail_panel.uninstall_clicked.connect(self._uninstall_mod)
        self.mod_detail_panel.open_folder_clicked.connect(self._open_mod_folder)
        self.mod_detail_panel.rename_clicked.connect(self._rename_mod)
        splitter.addWidget(self.mod_detail_panel)
        
        # Restore splitter sizes
        sizes = self._config.get('splitter_sizes', [350, 750])
        splitter.setSizes(sizes)
        splitter.splitterMoved.connect(
            lambda pos, index: self._config.set('splitter_sizes', splitter.sizes())
        )
        
        mods_layout.addWidget(splitter)
        self.tab_widget.addTab(mods_tab, "Mod管理")
        
        # 设置标签页
        self.settings_page = SettingsPage(self._config)
        self.settings_page.game_path_changed.connect(self._on_game_path_changed)
        self.settings_page.server_path_changed.connect(self._on_server_path_changed)
        self.tab_widget.addTab(self.settings_page, "设置")
        
        # Set as central widget
        layout = self.centralWidget().layout()
        layout.addWidget(self.tab_widget)
    
    def _create_status_bar(self):
        """Create the status bar."""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")
        
        # Framework status indicator (permanent widget on right side)
        self.framework_status_label = QLabel("")
        self.framework_status_label.setStyleSheet("font-size: 11px; padding: 0 8px;")
        self.status_bar.addPermanentWidget(self.framework_status_label)
    
    def apply_theme(self, theme_name: str = None):
        """Apply the current theme. Can be called externally with a specific theme name."""
        if theme_name:
            self._config.set('theme', theme_name)
        
        theme = theme_name or self._config.get('theme', 'dark')
        stylesheet = create_stylesheet(theme)
        self.setStyleSheet(stylesheet)
        
        # Re-apply toolbar button styles for theme awareness
        self._update_toolbar_styles()
        
        # Update mode label style
        self._update_mode_label_style()
        
        # Refresh mod list to rebuild item widgets with new theme colors
        if hasattr(self, 'mod_list_widget') and self._get_active_manager():
            self._refresh_mods()
        
        # Re-select current mod to refresh detail panel
        if hasattr(self, 'mod_list_widget'):
            current = self.mod_list_widget.mod_list.currentItem()
            if current:
                mod_id = current.data(Qt.UserRole)
                if mod_id:
                    self._on_mod_selected(mod_id)
        
        # Refresh settings page theme-dependent styles
        if hasattr(self, 'settings_page'):
            self.settings_page.refresh_theme()
    
    def _update_toolbar_styles(self):
        """Update toolbar button styles to match the current theme."""
        if hasattr(self, 'mode_switch_btn'):
            self.mode_switch_btn.setStyleSheet(get_toolbar_button_style('mode'))
        
    
    def _update_mode_label_style(self):
        """Update mode label style based on theme."""
        if is_dark_theme():
            color = "#58a6ff"
        else:
            color = "#0969da"
        self.mode_label.setStyleSheet(
            f"color: {color}; padding: 0 8px; font-size: 11px; font-weight: 600;"
        )
    
    def _load_game_path(self):
        """Load and initialize the game path."""
        game_path = self._config.get('game_path', '')
        
        if game_path and is_valid_palworld_path(game_path):
            self._init_mod_manager(game_path, is_server=False)
            if self._current_mode == 'game':
                self._refresh_mods()
                self._update_framework_status_bar()
                self._check_and_offer_framework_setup(game_path)
        else:
            if self._current_mode == 'game':
                self.status_bar.showMessage("请在设置中配置幻兽帕鲁的安装路径")
                self.framework_status_label.setText("UE4SS ✗ | PalSchema ✗")
    
    def _load_server_path(self):
        """Load and initialize the server path."""
        server_path = self._config.get('server_path', '')
        
        if server_path and is_valid_palserver_path(server_path):
            self._init_mod_manager(server_path, is_server=True)
            if self._current_mode == 'server':
                self._check_and_offer_framework_setup(server_path)
    
    def _check_and_offer_framework_setup(self, path: str):
        """Check if frameworks are missing and offer to install them."""
        from ..services.framework_setup import FrameworkSetupService
        
        setup = FrameworkSetupService(path)
        if setup.needs_setup():
            status = setup.get_status()
            missing = []
            if not status['ue4ss_installed']:
                missing.append("UE4SS")
            if not status['palschema_installed']:
                missing.append("PalSchema")
            
            reply = QMessageBox.question(
                self,
                "框架未安装",
                f"检测到以下框架未安装: {', '.join(missing)}\n\n"
                "Mod 需要这些框架才能正常运行。\n"
                "是否自动下载并安装？\n\n"
                "(需要网络连接，点击「否」可稍后手动安装)",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes,
            )
            
            if reply == QMessageBox.Yes:
                self._auto_setup_frameworks(path)
    
    def _auto_setup_frameworks(self, path: str):
        """Automatically download and install missing frameworks."""
        from ..services.framework_setup import FrameworkSetupService
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt as QtCore
        
        setup = FrameworkSetupService(path)
        
        # Create progress dialog
        progress = QProgressDialog("正在准备安装框架...", "取消", 0, 100, self)
        progress.setWindowTitle("安装框架")
        progress.setWindowModality(QtCore.WindowModal)
        progress.setMinimumDuration(0)
        progress.setValue(0)
        progress.show()
        
        def on_progress(message: str, percentage: int):
            progress.setLabelText(message)
            progress.setValue(percentage)
        
        setup.on_progress(on_progress)
        
        # Run setup in the background via QTimer to allow UI updates
        self.status_bar.showMessage("正在安装框架，请稍候...")
        
        try:
            success, messages = setup.setup_all(use_local_archives=False)
            
            progress.setValue(100)
            progress.close()
            
            if success:
                QMessageBox.information(
                    self, "安装完成",
                    "所有框架已成功安装并配置！\n\n" + "\n".join(messages)
                )
            else:
                QMessageBox.warning(
                    self, "部分安装",
                    "部分框架安装可能存在问题:\n\n" + "\n".join(messages) +
                    "\n\n请检查网络连接后重试，或手动下载安装。"
                )
        except Exception as e:
            progress.close()
            QMessageBox.critical(
                self, "安装失败",
                f"框架安装失败:\n{str(e)}\n\n"
                "请确保网络连接正常，或前往设置页面手动安装。"
            )
        finally:
            self._update_framework_status_bar()
            self.settings_page.refresh_status()
            self.status_bar.showMessage("就绪")
    
    def _setup_frameworks_from_local(self, path: str):
        """Install frameworks from local archive files."""
        from ..services.framework_setup import FrameworkSetupService
        from PyQt5.QtWidgets import QFileDialog
        
        setup = FrameworkSetupService(path)
        status = setup.get_status()
        messages = []
        
        # UE4SS
        if not status['ue4ss_installed']:
            archive, _ = QFileDialog.getOpenFileName(
                self, "选择 UE4SS 压缩包", "",
                "ZIP 压缩包 (*.zip);;所有文件 (*.*)"
            )
            if archive:
                success, msg = setup.install_ue4ss_from_archive(archive)
                messages.append(f"UE4SS: {msg}")
                if success:
                    setup._ue4ss.configure_for_palworld()
            else:
                messages.append("UE4SS: 用户取消")
        
        # PalSchema
        if not status['palschema_installed']:
            archive, _ = QFileDialog.getOpenFileName(
                self, "选择 PalSchema 压缩包", "",
                "ZIP 压缩包 (*.zip);;所有文件 (*.*)"
            )
            if archive:
                success, msg = setup.install_palschema_from_archive(archive)
                messages.append(f"PalSchema: {msg}")
            else:
                messages.append("PalSchema: 用户取消")
        
        if messages:
            QMessageBox.information(self, "安装结果", "\n".join(messages))
        
        self._update_framework_status_bar()
        self.settings_page.refresh_status()
    
    def _init_mod_manager(self, path: str, is_server: bool = False):
        """Initialize the mod manager for the given path."""
        mgr = ModManager(path)
        mgr.on_change(self._update_stats)
        mgr._load_profiles()
        
        if is_server:
            self._server_mod_manager = mgr
        else:
            self._mod_manager = mgr
    
    def _get_active_manager(self) -> ModManager:
        """Get the currently active mod manager based on mode."""
        if self._current_mode == 'server' and self._server_mod_manager:
            return self._server_mod_manager
        return self._mod_manager
    
    # ---- Actions ----
    
    def _refresh_mods(self):
        """Refresh the mod list from disk and check framework status."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        self.status_bar.showMessage("正在扫描Mod...")
        
        try:
            mods = mgr.refresh()
            self.mod_list_widget.set_mods(mods)
            self._update_stats()
            self._update_framework_status_bar()
            self.settings_page.refresh_status()
            mode_text = "服务器" if self._current_mode == 'server' else ""
            self.status_bar.showMessage(f"发现 {len(mods)} 个Mod {mode_text}")
        except Exception as e:
            self.status_bar.showMessage(f"扫描Mod出错: {str(e)}")
            QMessageBox.critical(self, "错误", f"扫描Mod失败:\n{str(e)}")
    
    def _update_framework_status_bar(self):
        """Update status bar with framework installation info."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        # Check framework on the active path
        from ..services.ue4ss_service import UE4SSService
        from ..services.palschema_service import PalSchemaService
        
        path = str(mgr.game_dir)
        ue4ss = UE4SSService(path)
        ps = PalSchemaService(path)
        
        parts = []
        if ue4ss.is_installed():
            ver = ue4ss.get_version() or ''
            parts.append(f"UE4SS ✓ {ver}")
        else:
            parts.append("UE4SS ✗")
        
        if ps.is_installed():
            ver = ps.get_version() or ''
            parts.append(f"PalSchema ✓ {ver}")
        else:
            parts.append("PalSchema ✗")
        
        self.framework_status_label.setText(" | ".join(parts))
    
    def _on_mod_selected(self, mod_id: str):
        """Handle mod selection in the list."""
        mgr = self._get_active_manager()
        if mgr:
            mod = mgr.get_mod(mod_id)
            self.mod_detail_panel.set_mod(mod)
    
    def _on_mod_toggled(self, mod_id: str):
        """Handle mod toggle from the list (via checkbox)."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        # Save scroll position
        scrollbar = self.mod_list_widget.mod_list.verticalScrollBar()
        scroll_value = scrollbar.value()
        
        success = mgr.toggle_mod(mod_id)
        if success:
            # Update stats without full refresh to preserve scroll position
            self._update_stats()
            # Refresh the list preserving scroll position
            self._refresh_mods_preserving_scroll(scroll_value)
            self.mod_list_widget.select_mod(mod_id)
            self._on_mod_selected(mod_id)
    
    def _refresh_mods_preserving_scroll(self, scroll_value: int = None):
        """Refresh mod list while preserving scroll position."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        try:
            mods = mgr.refresh()
            self.mod_list_widget.set_mods(mods)
            self._update_stats()
            self._update_framework_status_bar()
            
            # Restore scroll position
            if scroll_value is not None:
                sb = self.mod_list_widget.mod_list.verticalScrollBar()
                sb.setValue(scroll_value)
        except Exception as e:
            self.status_bar.showMessage(f"刷新Mod出错: {str(e)}")

    
    def _enable_mod(self, mod_id: str):
        """Enable a specific mod."""
        mgr = self._get_active_manager()
        if mgr:
            if mgr.enable_mod(mod_id):
                self._refresh_mods()
                self.mod_list_widget.select_mod(mod_id)
                self._on_mod_selected(mod_id)
    
    def _disable_mod(self, mod_id: str):
        """Disable a specific mod."""
        mgr = self._get_active_manager()
        if mgr:
            if mgr.disable_mod(mod_id):
                self._refresh_mods()
                self.mod_list_widget.select_mod(mod_id)
                self._on_mod_selected(mod_id)
    
    def _enable_all_mods(self):
        """Enable all mods."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        reply = QMessageBox.question(
            self, "全部启用",
            "确认启用所有Mod？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        
        if reply == QMessageBox.Yes:
            count = mgr.enable_all()
            self._refresh_mods()
            self.status_bar.showMessage(f"已启用 {count} 个Mod")
    
    def _disable_all_mods(self):
        """Disable all mods."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        if self._config.get('confirm_before_disable_all', True):
            reply = QMessageBox.question(
                self, "全部禁用",
                "确定要禁用所有Mod吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        
        count = mgr.disable_all()
        self._refresh_mods()
        self.status_bar.showMessage(f"已禁用 {count} 个Mod")
    
    def _delete_selected_mods(self):
        """Batch delete selected mods from the list."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        selected_ids = self.mod_list_widget.get_selected_mod_ids()
        
        if not selected_ids:
            QMessageBox.information(self, "提示", "请先在Mod列表中选择要删除的Mod (按住Ctrl多选)。")
            return
        
        # Get mod names for confirmation
        mod_names = []
        for mod_id in selected_ids:
            mod = mgr.get_mod(mod_id)
            if mod:
                mod_names.append(mod.name)
        
        if not mod_names:
            return
        
        names_preview = "\n".join(mod_names[:10])
        if len(mod_names) > 10:
            names_preview += f"\n... 及其他 {len(mod_names) - 10} 个"
        
        reply = QMessageBox.question(
            self, "批量删除确认",
            f"确定要删除以下 {len(mod_names)} 个Mod？\n\n"
            f"{names_preview}\n\n"
            "此操作不可恢复！",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        
        if reply != QMessageBox.Yes:
            return
        
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt as QtCore
        
        total = len(selected_ids)
        success = 0
        failed = []
        
        progress = QProgressDialog("正在批量删除...", "取消", 0, total, self)
        progress.setWindowTitle("批量删除")
        progress.setWindowModality(QtCore.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        for i, mod_id in enumerate(selected_ids):
            if progress.wasCanceled():
                break
            
            mod = mgr.get_mod(mod_id)
            if not mod:
                continue
            
            progress.setLabelText(f"[{i+1}/{total}] 删除: {mod.name}")
            progress.setValue(i)
            
            if mgr.uninstall_mod(mod_id):
                success += 1
            else:
                failed.append(mod.name)
        
        progress.setValue(total)
        progress.close()
        
        self._refresh_mods()
        self.status_bar.showMessage(f"批量删除完成: {success}/{total} 成功")
        
        if failed:
            QMessageBox.warning(self, "部分失败", f"成功 {success} 个，失败 {len(failed)} 个:\n" + "\n".join(failed[:10]))
    
    def _delete_all_mods(self):
        """Delete ALL mods from the current active mode (client or server)."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        mgr.refresh()
        all_mods = [m for m in mgr.mods if m.name.lower() not in mgr.scanner.UE4SS_BUILTIN_MODS]
        if not all_mods:
            QMessageBox.information(self, "提示", "没有可删除的 Mod。")
            return
        
        mode_text = "服务器" if self._current_mode == 'server' else "客户端"
        reply = QMessageBox.question(
            self, "确认删除所有Mod",
            f"确定要删除{mode_text}的全部 {len(all_mods)} 个Mod吗？\n\n"
            "此操作不可恢复！所有Mod文件将被永久删除。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        
        from PyQt5.QtWidgets import QProgressDialog
        from PyQt5.QtCore import Qt as QtCore
        
        total = len(all_mods)
        success = 0
        failed = []
        
        progress = QProgressDialog("正在删除所有Mod...", "取消", 0, total, self)
        progress.setWindowTitle("删除所有Mod")
        progress.setWindowModality(QtCore.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        
        for i, mod in enumerate(all_mods):
            if progress.wasCanceled():
                break
            progress.setLabelText(f"[{i+1}/{total}] 删除: {mod.name}")
            progress.setValue(i)
            if mgr.uninstall_mod(mod.id):
                success += 1
            else:
                failed.append(mod.name)
        
        progress.setValue(total)
        progress.close()
        
        self._refresh_mods()
        self.status_bar.showMessage(f"删除完成: {success}/{total} 成功")
        
        if failed:
            QMessageBox.warning(self, "部分失败", f"成功 {success} 个，失败 {len(failed)} 个:\n" + "\n".join(failed[:10]))
        else:
            QMessageBox.information(self, "完成", f"已删除{mode_text}的 {success} 个Mod。")
    
    def _uninstall_mod(self, mod_id: str):
        """Uninstall a mod."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        mod = mgr.get_mod(mod_id)
        if not mod:
            return
        
        if self._config.get('confirm_before_uninstall', True):
            reply = QMessageBox.question(
                self, "确认卸载",
                f"确定要卸载 '{mod.name}' 吗？\n\n"
                "这将永久删除Mod文件。",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return
        
        if mgr.uninstall_mod(mod_id):
            self._refresh_mods()
            self.mod_detail_panel.set_mod(None)
            self.status_bar.showMessage(f"已卸载: {mod.name}")
    
    def _open_mod_folder(self, mod_id: str):
        """Open the mod's folder in Explorer."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        mod = mgr.get_mod(mod_id)
        if not mod:
            return
        
        mod_path = Path(mod.install_path)
        if mod_path.is_file():
            mod_path = mod_path.parent
        
        if mod_path.exists():
            subprocess.Popen(f'explorer "{mod_path}"')
    
    def _rename_mod(self, mod_id: str):
        """Rename a mod - only changes display name in mod.json, not folder name."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        mod = mgr.get_mod(mod_id)
        if not mod:
            return
        
        from PyQt5.QtWidgets import QInputDialog
        
        new_name, ok = QInputDialog.getText(
            self, "重命名 Mod",
            "输入显示名称（不会修改文件夹名）:",
            text=mod.name
        )
        
        if not ok or not new_name.strip():
            return
        
        new_name = new_name.strip()
        old_name = mod.name
        mod.name = new_name
        mod.last_updated = datetime.now().isoformat()
        
        # Save to mod.json in the mod's directory
        self._save_mod_metadata(mod, new_name)
        
        self._refresh_mods()
        self.status_bar.showMessage(f"已重命名: {old_name} → {new_name}")
    
    def _save_mod_metadata(self, mod: 'ModInfo', custom_name: str):
        """Save mod metadata (custom name) to a mod.json file in the mod directory."""
        mod_path = Path(mod.install_path)
        if mod_path.is_file():
            mod_path = mod_path.parent
        
        meta_file = mod_path / "mod.json"
        
        # Read existing metadata if present
        existing = {}
        if meta_file.exists():
            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass
        
        # Update with custom name
        existing['name'] = custom_name
        existing['display_name'] = custom_name
        existing['author'] = mod.author
        existing['version'] = mod.version
        existing['description'] = mod.description
        existing['tags'] = mod.tags
        existing['renamed_by_manager'] = True
        
        try:
            with open(meta_file, 'w', encoding='utf-8') as f:
                json.dump(existing, f, indent=2, ensure_ascii=False)
        except Exception:
            pass
    
    def _sync_mods_to_server(self):
        """Mirror sync: make server mods identical to client mods.
        Copies missing mods to server, deletes extra mods on server.
        Client is always the source of truth.
        """
        client_path = self._config.get('game_path', '')
        server_path = self._config.get('server_path', '')
        
        if not client_path:
            QMessageBox.warning(self, "错误", "请先在设置中配置游戏客户端路径。")
            return
        if not server_path:
            QMessageBox.warning(self, "错误", "请先在设置中配置 PalServer 路径。")
            return
        
        from ..utils.helpers import is_valid_palserver_path
        if not is_valid_palserver_path(server_path):
            QMessageBox.warning(self, "错误", f"PalServer 路径无效:\n{server_path}")
            return
        
        if not self._mod_manager:
            QMessageBox.warning(self, "错误", "请先在客户端模式刷新 Mod 列表。")
            return
        
        # Ensure server manager is initialized
        if not self._server_mod_manager:
            self._init_mod_manager(server_path, is_server=True)
        
        # Count current mods on both sides
        client_mods = [m for m in self._mod_manager.refresh()
                      if m.name.lower() not in self._mod_manager.scanner.UE4SS_BUILTIN_MODS]
        server_mods = self._server_mod_manager.refresh() if self._server_mod_manager else []
        server_mods_filtered = [m for m in server_mods 
                               if m.name.lower() not in self._server_mod_manager.scanner.UE4SS_BUILTIN_MODS]
        
        client_names = {m.name for m in client_mods}
        server_names = {m.name for m in server_mods_filtered}
        
        missing_on_server = client_names - server_names  # Need to copy to server
        extra_on_server = server_names - client_names    # Need to delete from server
        
        reply = QMessageBox.question(
            self, "镜像同步确认",
            f"将服务器 Mod 与客户端完全同步（以客户端为准）。\n\n"
            f"客户端: {len(client_mods)} 个 Mod\n"
            f"服务器: {len(server_mods_filtered)} 个 Mod\n\n"
            f"操作预览:\n"
            f"• 复制到服务器: {len(missing_on_server)} 个\n"
            f"• 从服务器删除: {len(extra_on_server)} 个\n\n"
            f"服务器将被覆盖为与客户端完全一致，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        
        if reply != QMessageBox.Yes:
            return
        
        self.status_bar.showMessage("正在镜像同步...")
        
        try:
            copied, deleted, fail, messages = \
                self._mod_manager.sync_mirror(server_path)
            
            # Refresh both sides
            self._mod_manager.refresh()
            if self._server_mod_manager:
                self._server_mod_manager.refresh()
            
            # Refresh UI
            self._refresh_mods()
            
            self.status_bar.showMessage(
                f"同步完成: 复制 {copied}, 删除 {deleted}" + 
                (f", 失败 {fail}" if fail > 0 else "")
            )
            
            result_msg = (
                f"已复制: {copied} 个\n"
                f"已删除: {deleted} 个\n"
            )
            if fail > 0:
                result_msg += f"失败: {fail} 个\n\n"
                result_msg += "\n".join(messages[:10])
                QMessageBox.warning(self, "同步结果", result_msg)
            else:
                result_msg += f"\n服务器 Mod 已与客户端完全一致！"
                QMessageBox.information(self, "同步完成", result_msg)
                
        except Exception as e:
            self.status_bar.showMessage("同步失败")
            QMessageBox.critical(self, "错误", f"同步过程出错:\n{str(e)}")
    
    def _manage_profiles(self):
        """Open the profile management dialog."""
        mgr = self._get_active_manager()
        if not mgr:
            QMessageBox.warning(self, "错误", "请先在设置中配置路径。")
            return
        
        profiles = mgr.get_profiles()
        dialog = ProfileDialog(profiles, self)
        
        def handle_profile(action: str):
            if action.startswith("__create__"):
                name = action[len("__create__"):]
                desc = dialog.get_create_info()[1]
                mgr.save_profile(name, desc)
                self._refresh_mods()
            elif action.startswith("__delete__"):
                name = action[len("__delete__"):]
                mgr.delete_profile(name)
            else:
                mgr.load_profile(action)
                self._refresh_mods()
        
        dialog.profile_selected.connect(handle_profile)
        dialog.exec_()
    
    def _export_mod_list(self):
        """Export all mods to a shareable archive (same result as drag-import supports)."""
        mgr = self._get_active_manager()
        if not mgr:
            QMessageBox.warning(self, "提示", "请先在设置中配置路径。")
            return
        
        mgr.refresh()
        mods = [m for m in mgr.mods if m.name.lower() not in mgr.scanner.UE4SS_BUILTIN_MODS]
        if not mods:
            QMessageBox.information(self, "提示", "没有可导出的 Mod。")
            return
        
        # Save as compressed archive (zip/7z) or folder
        default_name = f"PalModPack_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        save_path, _ = QFileDialog.getSaveFileName(
            self, "保存 Mod 包", default_name,
            "ZIP 压缩包 (*.zip);;7z 压缩包 (*.7z);;文件夹 (*)")
        if not save_path:
            return
        
        save_path = Path(save_path)
        is_folder = save_path.suffix == ''
        
        if is_folder:
            # Export directly to folder
            export_dir = str(save_path)
            self.status_bar.showMessage("正在导出 Mod 包...")
            try:
                count, errors = mgr.export_mod_pack(export_dir)
                self.status_bar.showMessage(f"已导出 {count} 个Mod到文件夹")
                msg = f"成功导出 {count} 个 Mod！\n\n文件夹: {export_dir}\n\n拖入任意文件/文件夹即可导入"
                if errors:
                    msg += f"\n\n警告:\n" + "\n".join(errors[:5])
                QMessageBox.information(self, "导出完成", msg)
            except Exception as e:
                self.status_bar.showMessage("导出失败")
                QMessageBox.critical(self, "错误", f"导出失败:\n{str(e)}")
            return
        
        # Compressed export: temp folder → archive
        import tempfile, shutil
        tmp_dir = None
        try:
            tmp_dir = tempfile.mkdtemp(prefix='pal_export_')
            export_root = Path(tmp_dir) / "Pal"
            
            self.status_bar.showMessage("正在导出 Mod 包...")
            count, errors = mgr.export_mod_pack(str(export_root.parent))
            
            is_7z = save_path.suffix.lower() == '.7z'
            if is_7z:
                import py7zr
                with py7zr.SevenZipFile(save_path, 'w') as zf:
                    zf.writeall(str(export_root.parent), arcname='')
            else:
                with zipfile.ZipFile(save_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for f in export_root.parent.rglob('*'):
                        zf.write(str(f), str(f.relative_to(export_root.parent)))
            
            size_mb = save_path.stat().st_size / (1024 * 1024)
            self.status_bar.showMessage(f"已导出 {count} 个Mod ({size_mb:.1f}MB)")
            
            msg = f"成功导出 {count} 个 Mod！\n\n文件: {save_path.name} ({size_mb:.1f} MB)\n\n分享方法: 拖入管理器即可一键导入"
            if errors:
                msg += f"\n\n警告:\n" + "\n".join(errors[:5])
            QMessageBox.information(self, "导出完成", msg)
        except Exception as e:
            self.status_bar.showMessage("导出失败")
            QMessageBox.critical(self, "错误", f"导出失败:\n{str(e)}")
        finally:
            if tmp_dir:
                shutil.rmtree(tmp_dir, ignore_errors=True)
    
    def _import_mod_list(self):
        """Import mods — same flow as drag-and-drop: just calls import_mod_pack."""
        mgr = self._get_active_manager()
        if not mgr:
            QMessageBox.warning(self, "提示", "请先在设置中配置路径。")
            return
        
        # Ask: file (zip/7z/pak) or folder?
        reply = QMessageBox.question(
            self, "选择导入来源",
            "要导入文件/压缩包还是整个文件夹？\n\n"
            "「是」= 选择文件（zip / 7z / pak）\n"
            "「否」= 选择文件夹",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        
        if reply == QMessageBox.Cancel:
            return
        if reply == QMessageBox.Yes:
            path, _ = QFileDialog.getOpenFileName(
                self, "选择 Mod 包", "",
                "Mod 包 (*.zip *.7z *.pak);;所有文件 (*.*)")
        else:
            path = QFileDialog.getExistingDirectory(self, "选择 Mod 文件夹", "")
        
        if not path:
            return
        
        self.status_bar.showMessage("正在导入 Mod 包...")
        try:
            success, skip, errors = mgr.import_mod_pack(path)
            self._refresh_mods()
            self.status_bar.showMessage(f"导入完成: {success} 成功, {skip} 跳过")
            
            msg = f"成功: {success} 个\n跳过（已存在）: {skip} 个"
            if errors:
                msg += f"\n\n错误:\n" + "\n".join(errors[:10])
                QMessageBox.warning(self, "导入结果", msg)
            else:
                msg += "\n\n导入完成！"
                QMessageBox.information(self, "导入完成", msg)
        except Exception as e:
            self.status_bar.showMessage("导入失败")
            QMessageBox.critical(self, "错误", f"导入失败:\n{str(e)}")
    
    def _scan_mod_collection(self):
        """Scan an organized mod collection directory and show the mods found."""
        mgr = self._get_active_manager()
        if not mgr:
            QMessageBox.warning(self, "提示", "请先在设置中配置路径。")
            return

        path = QFileDialog.getExistingDirectory(
            self, "选择 Mod 合集目录",
            self._config.get('last_collection_path', ''))
        if not path:
            return
        self._config.set('last_collection_path', path)

        self.status_bar.showMessage("正在扫描合集目录...")
        try:
            collection_mods = mgr.scan_collection(path)
        except Exception as e:
            self.status_bar.showMessage("扫描失败")
            QMessageBox.critical(self, "错误", f"扫描合集目录失败:\n{str(e)}")
            return

        if not collection_mods:
            QMessageBox.information(
                self, "扫描结果",
                "未在该目录中发现可识别的 Mod。\n\n"
                "支持的格式：\n"
                "• 含 Pal/ 子目录的 Mod 文件夹（如 分类/Mod名/Pal/Content/...）\n"
                "• 平铺的 .pak / .lua 文件（可带同名 .txt 说明）")
            self.status_bar.showMessage("就绪")
            return

        # Merge with currently installed mods and display
        try:
            installed = mgr.refresh()
        except Exception:
            installed = []
        merged = list(installed) + collection_mods
        self.mod_list_widget.set_mods(merged)

        n_collection = len(collection_mods)
        self.status_bar.showMessage(
            f"扫描完成：发现 {n_collection} 个合集 Mod（已并入列表，带「合集」标签）")

        reply = QMessageBox.question(
            self, "导入合集 Mod",
            f"发现 {n_collection} 个合集 Mod。\n\n"
            "是否将全部合集 Mod 导入到当前游戏/服务器目录？\n"
            "（取消则仅预览，可稍后在列表中选择性处理）",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        if reply == QMessageBox.Cancel:
            return
        if reply == QMessageBox.No:
            return

        self._import_collection_mods(collection_mods)

    def _import_collection_mods(self, collection_mods: list):
        """Import the scanned collection mods into the active game/server dir."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        success = skip = 0
        errors = []
        for mod in collection_mods:
            src = mod.raw_metadata.get('collection_path')
            if not src or not os.path.isdir(src):
                # Fallback: try the mod's own folder via source_path's parent
                src = os.path.dirname(mod.source_path)
            if not src or not os.path.isdir(src):
                errors.append(f"{mod.name}: 找不到来源文件夹")
                continue
            try:
                s, sk, err = mgr.import_mod_pack(src)
                success += s
                skip += sk
                errors.extend(err)
            except Exception as e:
                errors.append(f"{mod.name}: {str(e)}")
        self._refresh_mods()
        msg = f"成功: {success} 个\n跳过（已存在）: {skip} 个"
        if errors:
            msg += f"\n\n错误:\n" + "\n".join(errors[:10])
            QMessageBox.warning(self, "导入结果", msg)
        else:
            QMessageBox.information(self, "导入完成", msg + "\n\n导入完成！")

    def _launch_game(self):
        """Launch Palworld or PalServer based on current mode."""
        if self._current_mode == 'server':
            server_path = self._config.get('server_path', '')
            if not server_path:
                QMessageBox.warning(self, "错误", "请先设置PalServer路径。")
                return
            success, msg = launch_palserver(server_path)
        else:
            game_path = self._config.get('game_path', '')
            if not game_path:
                QMessageBox.warning(self, "错误", "请先设置游戏路径。")
                return
            success, msg = launch_game(game_path)
        
        if success:
            self.status_bar.showMessage("已启动！")
        else:
            QMessageBox.critical(self, "错误", msg)
    
    def _open_game_dir(self):
        """Open the active game/server directory in Explorer."""
        mgr = self._get_active_manager()
        if mgr:
            subprocess.Popen(f'explorer "{mgr.game_dir}"')
        else:
            QMessageBox.warning(self, "错误", "路径未设置或未找到。")
    
    def _open_mods_dir(self):
        """Open the Mods directory in Explorer."""
        mgr = self._get_active_manager()
        if mgr:
            mods_dir = mgr.scanner.mods_dir
            if mods_dir.exists():
                subprocess.Popen(f'explorer "{mods_dir}"')
            else:
                QMessageBox.information(self, "提示", "Mod目录未找到，将在需要时自动创建。")
        else:
            QMessageBox.warning(self, "错误", "请先在设置中配置路径。")
    
    def _view_ue4ss_logs(self):
        """View UE4SS log file."""
        mgr = self._get_active_manager()
        if not mgr:
            return
        
        ue4ss = UE4SSService(mgr.game_dir)
        logs = ue4ss.get_recent_logs(100)
        
        if logs:
            from PyQt5.QtWidgets import QDialog, QTextEdit
            
            dialog = QDialog(self)
            dialog.setWindowTitle("UE4SS 日志")
            dialog.resize(700, 500)
            
            layout = QVBoxLayout(dialog)
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setPlainText(logs)
            text_edit.setStyleSheet("""
                QTextEdit {
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 12px;
                }
            """)
            layout.addWidget(text_edit)
            
            close_btn = QPushButton("关闭")
            close_btn.clicked.connect(dialog.accept)
            layout.addWidget(close_btn)
            
            dialog.exec_()
        else:
            QMessageBox.information(self, "提示", "未找到UE4SS日志。")
    
    def _set_update_status(self, text: str, level: str = 'ok'):
        """更新工具栏「检查更新」按钮旁的状态标签。

        level: ok(绿,已是最新) / update(黄,有可用更新) / error(红,失败) / loading(蓝,检查中)
        """
        if not hasattr(self, 'update_status_lbl'):
            return
        colors = {
            'ok': '#3fb950',
            'update': '#d29922',
            'error': '#f85149',
            'loading': '#58a6ff',
        }
        color = colors.get(level, '#8b949e')
        self.update_status_lbl.setText(text)
        self.update_status_lbl.setStyleSheet(
            f"color: {color}; padding: 0 8px; font-size: 11px; font-weight: 600;")

    def _check_update(self, silent: bool = False):
        """Check for updates; the actual download runs in a worker thread
        so the UI stays responsive.

        When silent=True (启动自动检查) no dialog is shown — only the toolbar
        status label is updated with "已是最新版本" / "有可用版本: x".
        """
        self.status_bar.showMessage("正在检查更新...")
        self._set_update_status("检查更新中…", "loading")
        try:
            from ..utils.updater import check_for_update, apply_update, CURRENT_VERSION, UPDATE_URL
        except Exception as e:
            self.status_bar.showMessage(f"加载失败: {e}")
            self._set_update_status("更新模块加载失败", "error")
            if not silent:
                QMessageBox.warning(self, "错误", f"加载更新模块失败:\n{e}")
            return
        
        try:
            info, err = check_for_update(UPDATE_URL)
        except Exception as e:
            self.status_bar.showMessage(f"检查失败: {e}")
            self._set_update_status("更新检查失败", "error")
            if not silent:
                QMessageBox.warning(self, "检查更新", f"检查更新时出错:\n{e}")
            return
        
        if info is None:
            self.status_bar.showMessage("连接失败")
            self._set_update_status("更新检查失败", "error")
            if not silent:
                QMessageBox.warning(self, "检查更新",
                    f"无法连接到更新服务器。\n{err}\n\n"
                    "请确认网络正常，或稍后重试。")
            return
        
        if not info:
            self.status_bar.showMessage(f"已是最新版本 ({CURRENT_VERSION})")
            self._set_update_status(f"已是最新版本 ({CURRENT_VERSION})", "ok")
            if not silent:
                QMessageBox.information(self, "检查更新",
                    f"已是最新版本 ({CURRENT_VERSION})。")
            return
        
        ver = info.get('version', CURRENT_VERSION)
        # 发现新版本：静默模式只更新标签，不弹窗（用户可点击按钮升级）
        self.status_bar.showMessage(f"发现新版本 {ver}")
        self._set_update_status(f"有可用版本: {ver}", "update")
        if silent:
            return
        notes = info.get('notes', '')
        reply = QMessageBox.question(
            self, "发现新版本",
            f"发现新版本: {ver}\n当前版本: {CURRENT_VERSION}\n\n"
            + (f"更新内容:\n{notes}\n\n" if notes else "")
            + "是否立即下载？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply != QMessageBox.Yes:
            return
        
        url = info.get('download_url', '')
        if not url:
            QMessageBox.warning(self, "错误", "没有下载地址。")
            return
        
        from PyQt5.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                      QLabel, QProgressBar, QPushButton,
                                      QGridLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle("下载更新")
        dlg.setFixedSize(460, 260)
        dlg.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        title_lbl = QLabel(f"正在下载新版本 {ver}")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title_lbl)

        bar = QProgressBar(dlg)
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setMinimumHeight(22)
        layout.addWidget(bar)

        # 两列信息网格
        grid = QGridLayout()
        grid.setSpacing(4)
        lbl_size = QLabel("大小：")
        lbl_speed = QLabel("速度：")
        lbl_remain = QLabel("剩余：")
        lbl_elapsed = QLabel("已用：")
        lbl_method = QLabel("方式：")
        val_size = QLabel("-")
        val_speed = QLabel("-")
        val_remain = QLabel("-")
        val_elapsed = QLabel("0 秒")
        val_method = QLabel("准备中…")
        for lbl in (lbl_size, lbl_speed, lbl_remain, lbl_elapsed, lbl_method):
            lbl.setStyleSheet("color: #888;")
        grid.addWidget(lbl_size, 0, 0)
        grid.addWidget(val_size, 0, 1)
        grid.addWidget(lbl_method, 0, 2)
        grid.addWidget(val_method, 0, 3)
        grid.addWidget(lbl_speed, 1, 0)
        grid.addWidget(val_speed, 1, 1)
        grid.addWidget(lbl_elapsed, 1, 2)
        grid.addWidget(val_elapsed, 1, 3)
        grid.addWidget(lbl_remain, 2, 0)
        grid.addWidget(val_remain, 2, 1)
        layout.addLayout(grid)

        status_lbl = QLabel("正在连接更新服务器…")
        status_lbl.setStyleSheet("color: #0969da;")
        layout.addWidget(status_lbl)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedWidth(100)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        dlg.show()

        # ---- 进度与速度计算 ----
        start_ts = time.time()
        last_ts = [start_ts]
        last_done = [0]

        def on_progress_changed(done, total, method=""):
            now = time.time()
            dt = now - last_ts[0]
            if dt >= 0.15 or method:
                dd = done - last_done[0]
                speed = dd / dt if dt > 0 else 0
                last_ts[0] = now
                last_done[0] = done

                pct = int(done * 100 / total) if total > 0 else 0
                bar.setValue(min(100, pct))
                val_size.setText(
                    f"{done/1048576:.1f} / {total/1048576:.1f} MB")
                if speed > 0:
                    val_speed.setText(f"{speed/1048576:.2f} MB/s")
                else:
                    val_speed.setText("-")
                if speed > 0 and total > done:
                    rem = (total - done) / speed
                    val_remain.setText(_fmt_time(rem))
                else:
                    val_remain.setText("-")
                val_elapsed.setText(_fmt_time(now - start_ts))
                if method:
                    val_method.setText(method)
                status_lbl.setText("正在下载更新文件…")

        def on_finished(saved):
            dlg.close()
            if apply_update(saved):
                self.status_bar.showMessage("更新已就绪，正在关闭...")
                self.status_bar.repaint()
                self.close()
                QApplication.quit()
                os._exit(0)
            else:
                QMessageBox.critical(self, "错误", "无法应用更新。")

        def on_failed(msg):
            dlg.close()
            QMessageBox.critical(self, "错误", msg)

        def do_cancel():
            dlg.close()

        cancel_btn.clicked.connect(do_cancel)

        # 下载在独立线程中进行，UI 全程可响应、可取消
        self._update_worker = UpdateDownloader(url, mirror=info.get('_mirror', ''))
        self._update_worker.progress_changed.connect(on_progress_changed)
        self._update_worker.download_finished.connect(on_finished)
        self._update_worker.download_failed.connect(on_failed)
        self._update_worker.canceled.connect(do_cancel)
        cancel_btn.clicked.connect(self._update_worker.cancel)
        self._update_worker.start()

    def _show_about(self):
        """Show the about dialog."""
        from ..utils.updater import CURRENT_VERSION
        QMessageBox.about(
            self,
            "关于 帕鲁Mod管理器",
            "<h2>帕鲁Mod管理器</h2>"
            f"<p>版本 {CURRENT_VERSION}</p>"
            "<p>一款功能全面的幻兽帕鲁 Mod 管理工具。</p>"
            "<p><b>支持的框架:</b></p>"
            "<ul>"
            "<li>UE4SS (Lua/Blueprint Mod)</li>"
            "<li>PalSchema (配置Mod)</li>"
            "<li>PAK Mod</li>"
            "<li>LogicMod</li>"
            "</ul>"
            "<p><b>功能特性:</b></p>"
            "<ul>"
            "<li>Mod扫描与检测</li>"
            "<li>启用/禁用Mod</li>"
            "<li>Mod方案管理</li>"
            "<li>冲突检测</li>"
            "<li>UE4SS/PalSchema 管理</li>"
            "<li>配置文件编辑</li>"
            "</ul>"
        )
    
    # ---- Drag and Drop ----
    
    # Supported drop/import suffixes — all four mod types
    _IMPORT_SUFFIXES = {'.zip', '.7z', '.001', '.pak'}
    
    def dragEnterEvent(self, event):
        """Accept drag events for any supported import format."""
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                p = Path(path)
                if p.is_dir() or p.suffix.lower() in self._IMPORT_SUFFIXES:
                    event.acceptProposedAction()
                    return
        event.ignore()
    
    def dropEvent(self, event):
        """Handle drop of any supported file/folder for import."""
        mgr = self._get_active_manager()
        if not mgr:
            QMessageBox.warning(self, "提示", "请先在设置中配置路径。")
            return
        
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            p = Path(path)
            if p.is_dir() or p.suffix.lower() in self._IMPORT_SUFFIXES:
                self._import_from_drop(path, mgr)
            else:
                QMessageBox.warning(self, "不支持", f"不支持的文件格式: {p.suffix}")
    
    def _import_from_drop(self, path: str, mgr: 'ModManager'):
        """Import a mod pack from a dragged file/folder."""
        p = Path(path)
        
        reply = QMessageBox.question(
            self, "确认导入",
            f"将从此文件导入 Mod:\n{p.name}\n\n"
            f"已存在的 Mod 将被跳过，不会覆盖。是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        
        self.status_bar.showMessage(f"正在导入: {p.name}...")
        try:
            success, skip, errors = mgr.import_mod_pack(path)
            self._refresh_mods()
            self.status_bar.showMessage(f"导入完成: {success} 成功, {skip} 跳过")
            
            msg = f"成功: {success} 个\n跳过（已存在）: {skip} 个"
            if errors:
                msg += f"\n\n错误:\n" + "\n".join(errors[:10])
                QMessageBox.warning(self, "导入结果", msg)
            else:
                msg += "\n\n导入完成！"
                QMessageBox.information(self, "导入完成", msg)
        except Exception as e:
            self.status_bar.showMessage("导入失败")
            QMessageBox.critical(self, "错误", f"导入失败:\n{str(e)}")
    
    # ---- Callbacks ----
    
    def _on_game_path_changed(self, path: str):
        """Handle game path change."""
        if is_valid_palworld_path(path):
            self._init_mod_manager(path, is_server=False)
            if self._current_mode == 'game':
                self._refresh_mods()
            self.settings_page.refresh_status()
            self._update_framework_status_bar()
    
    def _on_server_path_changed(self, path: str):
        """Handle server path change."""
        if is_valid_palserver_path(path):
            self._init_mod_manager(path, is_server=True)
            if self._current_mode == 'server':
                self._refresh_mods()
                self._update_framework_status_bar()
    
    def _toggle_mode(self):
        """Switch between game client and server mode."""
        if self._current_mode == 'game':
            if not self._server_mod_manager:
                QMessageBox.warning(self, "提示", "请先在设置中配置PalServer安装路径。")
                return
            self._current_mode = 'server'
            self.mode_switch_btn.setText("服务器")
            self.mode_switch_btn.setToolTip("点击切换到客户端模式")
            self.mode_label.setText("服务器")
            self.tab_widget.setTabText(0, "服务器Mod管理")
        else:
            if not self._mod_manager:
                QMessageBox.warning(self, "提示", "请先在设置中配置游戏客户端安装路径。")
                return
            self._current_mode = 'game'
            self.mode_switch_btn.setText("客户端")
            self.mode_switch_btn.setToolTip("点击切换到服务器模式")
            self.mode_label.setText("客户端")
            self.tab_widget.setTabText(0, "Mod管理")
        
        # Re-apply mode button style and label style
        self.mode_switch_btn.setStyleSheet(get_toolbar_button_style('mode'))
        self._update_mode_label_style()
        
        self._refresh_mods()
        self._update_framework_status_bar()
    
    def _update_stats(self):
        """Update the stats display in the toolbar."""
        mgr = self._get_active_manager()
        if mgr:
            stats = mgr.get_stats()
            self.stats_label.setText(
                f"总计: {stats['total']} | 已启用: {stats['enabled']} | "
                f"已禁用: {stats['disabled']} | 冲突: {stats['conflicts']}"
            )
    
    # ---- Window events ----
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Save window geometry
        self._config.set('window_geometry', bytes(self.saveGeometry()).hex())
        self._config.set('window_state', bytes(self.saveState()).hex())

        event.accept()
