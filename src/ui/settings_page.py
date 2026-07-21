"""
Settings Page - game path, UE4SS, PalSchema configuration, and preferences.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QGroupBox, QScrollArea, QFrame, QCheckBox,
    QComboBox, QFileDialog, QMessageBox, QSpinBox,
)
from PyQt5.QtCore import Qt, pyqtSignal

from ..utils.config import AppConfig
from ..utils.helpers import (
    is_valid_palworld_path, find_palworld_installation, get_game_version,
    is_valid_palserver_path, find_palserver_installation,
)
from ..services.ue4ss_service import UE4SSService
from ..services.palschema_service import PalSchemaService
from .styles import is_dark_theme, get_settings_group_style


class SettingsPage(QWidget):
    """Settings and configuration page."""
    
    game_path_changed = pyqtSignal(str)
    server_path_changed = pyqtSignal(str)
    refresh_requested = pyqtSignal()
    
    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._init_ui()
        self._load_settings()
    
    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        
        # Title
        title = QLabel("设置")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        
        # One-click framework setup
        layout.addWidget(self._build_quick_setup_section())
        
        # Game Path Section
        layout.addWidget(self._build_game_path_section())
        
        # UE4SS Section
        layout.addWidget(self._build_ue4ss_section())
        
        # PalSchema Section
        layout.addWidget(self._build_palschema_section())
        
        # General Settings
        layout.addWidget(self._build_general_section())
        
        # Developer settings (collapsible)
        layout.addWidget(self._build_developer_section())
        
        layout.addStretch()
        
        scroll.setWidget(content)
        main_layout.addWidget(scroll)
    
    def _build_quick_setup_section(self) -> QGroupBox:
        """Build the one-click framework setup section."""
        self.quick_setup_group = QGroupBox("框架快速安装")
        self.quick_setup_group.setStyleSheet(get_settings_group_style('quick_setup'))
        layout = QVBoxLayout()
        layout.setSpacing(10)
        
        desc = QLabel("自动检测并安装缺失的框架（UE4SS + PalSchema），配置完成后即可使用 Mod。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #8b949e; font-size: 12px; background: transparent;")
        layout.addWidget(desc)
        
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)
        
        self.quick_setup_btn = QPushButton("一键安装所有框架")
        self.quick_setup_btn.setObjectName("successBtn")
        self.quick_setup_btn.clicked.connect(self._on_quick_setup)
        btn_layout.addWidget(self.quick_setup_btn)
        
        self.local_setup_btn = QPushButton("从本地文件安装")
        self.local_setup_btn.setObjectName("secondaryBtn")
        self.local_setup_btn.setToolTip("使用已下载的 ZIP 压缩包安装框架")
        self.local_setup_btn.clicked.connect(self._on_local_setup)
        btn_layout.addWidget(self.local_setup_btn)
        
        self.uninstall_all_btn = QPushButton("卸载所有框架")
        self.uninstall_all_btn.setObjectName("dangerBtn")
        self.uninstall_all_btn.setToolTip("删除 UE4SS 和 PalSchema，恢复游戏原始状态")
        self.uninstall_all_btn.clicked.connect(self._on_uninstall_all)
        btn_layout.addWidget(self.uninstall_all_btn)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
        self.quick_setup_group.setLayout(layout)
        return self.quick_setup_group
    
    def _on_quick_setup(self):
        """Trigger one-click framework installation for game client."""
        parent = self.window()
        if hasattr(parent, '_auto_setup_frameworks'):
            game_path = self._config.get('game_path', '')
            if not game_path or not is_valid_palworld_path(game_path):
                QMessageBox.warning(self, "错误", "请先配置游戏客户端路径。")
                return
            parent._auto_setup_frameworks(game_path)
    
    def _on_local_setup(self):
        """Install frameworks from local files for game client."""
        parent = self.window()
        if hasattr(parent, '_setup_frameworks_from_local'):
            game_path = self._config.get('game_path', '')
            if not game_path or not is_valid_palworld_path(game_path):
                QMessageBox.warning(self, "错误", "请先配置游戏客户端路径。")
                return
            parent._setup_frameworks_from_local(game_path)
    
    def _build_game_path_section(self) -> QGroupBox:
        """Build the game path configuration section."""
        group = QGroupBox("游戏安装")
        layout = QVBoxLayout()
        
        # 路径输入
        path_layout = QHBoxLayout()
        
        self.game_path_input = QLineEdit()
        self.game_path_input.setPlaceholderText("选择幻兽帕鲁安装目录...")
        self.game_path_input.setReadOnly(True)
        path_layout.addWidget(self.game_path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_game_path)
        path_layout.addWidget(browse_btn)
        
        auto_detect_btn = QPushButton("自动检测")
        auto_detect_btn.setObjectName("secondaryBtn")
        auto_detect_btn.clicked.connect(self._auto_detect)
        path_layout.addWidget(auto_detect_btn)
        
        layout.addLayout(path_layout)
        
        # Status
        self.game_status_label = QLabel("")
        self.game_status_label.setStyleSheet("font-size: 12px; padding: 4px 0;")
        layout.addWidget(self.game_status_label)
        
        # Game info
        self.game_info_label = QLabel("")
        self.game_info_label.setStyleSheet("color: #6c6c7e; font-size: 11px;")
        layout.addWidget(self.game_info_label)
        
        group.setLayout(layout)
        return group
    
    def _build_developer_section(self) -> QWidget:
        """Build the developer settings section (collapsible, contains server settings)."""
        from PyQt5.QtWidgets import QToolButton
        
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)
        
        # Toggle button for developer section
        toggle_layout = QHBoxLayout()
        toggle_layout.setSpacing(8)
        
        self.dev_toggle_btn = QToolButton()
        self.dev_toggle_btn.setText("▶ 开发者设置")
        self.dev_toggle_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.dev_toggle_btn.setCheckable(True)
        self.dev_toggle_btn.setChecked(False)
        self.dev_toggle_btn.setStyleSheet("""
            QToolButton {
                color: #8b949e;
                font-size: 12px;
                font-weight: 600;
                border: none;
                background: transparent;
                padding: 4px 0;
            }
            QToolButton:hover { color: #58a6ff; }
            QToolButton:checked { color: #58a6ff; }
        """)
        self.dev_toggle_btn.clicked.connect(self._toggle_developer_section)
        toggle_layout.addWidget(self.dev_toggle_btn)
        toggle_layout.addStretch()
        container_layout.addLayout(toggle_layout)
        
        # Developer content (hidden by default)
        self.dev_content = QWidget()
        self.dev_content.setVisible(False)
        dev_layout = QVBoxLayout(self.dev_content)
        dev_layout.setContentsMargins(0, 0, 0, 0)
        dev_layout.setSpacing(16)
        
        # Server path section
        dev_layout.addWidget(self._build_server_path_section())
        
        container_layout.addWidget(self.dev_content)
        return container
    
    def _toggle_developer_section(self):
        """Toggle visibility of developer settings."""
        is_open = self.dev_toggle_btn.isChecked()
        self.dev_content.setVisible(is_open)
        self.dev_toggle_btn.setText("▼ 开发者设置" if is_open else "▶ 开发者设置")
    
    def _build_server_path_section(self) -> QGroupBox:
        """Build the server path configuration section."""
        group = QGroupBox("服务器安装 (PalServer)")
        layout = QVBoxLayout()
        
        path_layout = QHBoxLayout()
        
        self.server_path_input = QLineEdit()
        self.server_path_input.setPlaceholderText("选择PalServer安装目录...")
        self.server_path_input.setReadOnly(True)
        path_layout.addWidget(self.server_path_input)
        
        browse_btn = QPushButton("浏览...")
        browse_btn.clicked.connect(self._browse_server_path)
        path_layout.addWidget(browse_btn)
        
        auto_detect_btn = QPushButton("自动检测")
        auto_detect_btn.setObjectName("secondaryBtn")
        auto_detect_btn.clicked.connect(self._auto_detect_server)
        path_layout.addWidget(auto_detect_btn)
        
        layout.addLayout(path_layout)
        
        self.server_status_label = QLabel("")
        self.server_status_label.setStyleSheet("font-size: 12px; padding: 4px 0;")
        layout.addWidget(self.server_status_label)
        
        # 服务器框架状态
        self.server_framework_label = QLabel("")
        self.server_framework_label.setStyleSheet("color: #6c6c7e; font-size: 11px;")
        layout.addWidget(self.server_framework_label)
        
        # 服务器框架安装按钮
        svr_btn_layout = QHBoxLayout()
        
        self.server_setup_btn = QPushButton("为服务器安装框架")
        self.server_setup_btn.setObjectName("secondaryBtn")
        self.server_setup_btn.setToolTip("自动下载并安装 UE4SS + PalSchema 到服务器目录")
        self.server_setup_btn.clicked.connect(self._on_server_setup)
        svr_btn_layout.addWidget(self.server_setup_btn)
        
        self.server_local_setup_btn = QPushButton("从本地安装")
        self.server_local_setup_btn.setObjectName("secondaryBtn")
        self.server_local_setup_btn.setToolTip("使用本地 ZIP 文件安装框架到服务器")
        self.server_local_setup_btn.clicked.connect(self._on_server_local_setup)
        svr_btn_layout.addWidget(self.server_local_setup_btn)
        
        svr_btn_layout.addStretch()
        layout.addLayout(svr_btn_layout)
        
        self.server_info_label = QLabel("服务器端同样需要 UE4SS + PalSchema 框架才能使用 Mod")
        self.server_info_label.setWordWrap(True)
        self.server_info_label.setStyleSheet("color: #484f58; font-size: 11px; padding-top: 4px;")
        layout.addWidget(self.server_info_label)
        
        # 同步按钮组
        svr_sync_layout = QHBoxLayout()
        
        self.sync_server_to_client_btn = QPushButton("服务器→客户端")
        self.sync_server_to_client_btn.setObjectName("secondaryBtn")
        self.sync_server_to_client_btn.setToolTip("将服务器端Mod完全同步到客户端（以服务器为准）")
        self.sync_server_to_client_btn.clicked.connect(self._on_sync_server_to_client)
        svr_sync_layout.addWidget(self.sync_server_to_client_btn)
        
        self.sync_client_to_server_btn = QPushButton("客户端→服务器")
        self.sync_client_to_server_btn.setObjectName("secondaryBtn")
        self.sync_client_to_server_btn.setToolTip("将客户端Mod完全同步到服务器（以客户端为准）")
        self.sync_client_to_server_btn.clicked.connect(self._on_sync_client_to_server)
        svr_sync_layout.addWidget(self.sync_client_to_server_btn)
        
        # Uninstall button for server
        self.uninstall_server_btn = QPushButton("卸载服务器框架")
        self.uninstall_server_btn.setObjectName("dangerBtn")
        self.uninstall_server_btn.setToolTip("删除服务器端的 UE4SS 和 PalSchema，恢复原始状态")
        self.uninstall_server_btn.clicked.connect(self._on_uninstall_server)
        svr_sync_layout.addWidget(self.uninstall_server_btn)
        
        svr_sync_layout.addStretch()
        layout.addLayout(svr_sync_layout)
        
        group.setLayout(layout)
        return group
    
    def _build_ue4ss_section(self) -> QGroupBox:
        """Build the UE4SS configuration section."""
        group = QGroupBox("UE4SS 框架")
        layout = QVBoxLayout()
        
        # 状态
        status_layout = QHBoxLayout()
        
        self.ue4ss_status_label = QLabel("状态: 检测中...")
        status_layout.addWidget(self.ue4ss_status_label)
        
        status_layout.addStretch()
        
        self.ue4ss_install_btn = QPushButton("在线安装 UE4SS")
        self.ue4ss_install_btn.setObjectName("secondaryBtn")
        self.ue4ss_install_btn.clicked.connect(self._install_ue4ss)
        status_layout.addWidget(self.ue4ss_install_btn)
        
        self.ue4ss_local_btn = QPushButton("本地安装")
        self.ue4ss_local_btn.setObjectName("secondaryBtn")
        self.ue4ss_local_btn.setToolTip("从本地ZIP文件安装UE4SS")
        self.ue4ss_local_btn.clicked.connect(self._install_ue4ss_local)
        status_layout.addWidget(self.ue4ss_local_btn)
        
        self.ue4ss_uninstall_btn = QPushButton("卸载 UE4SS")
        self.ue4ss_uninstall_btn.setObjectName("dangerBtn")
        self.ue4ss_uninstall_btn.clicked.connect(self._uninstall_ue4ss)
        status_layout.addWidget(self.ue4ss_uninstall_btn)
        
        layout.addLayout(status_layout)
        
        # 版本信息
        self.ue4ss_version_label = QLabel("")
        self.ue4ss_version_label.setStyleSheet("color: #6c6c7e; font-size: 11px;")
        layout.addWidget(self.ue4ss_version_label)
        
        # 自动配置复选框
        self.ue4ss_auto_config = QCheckBox("自动为幻兽帕鲁配置UE4SS")
        self.ue4ss_auto_config.setChecked(self._config.get('ue4ss_auto_configure', True))
        self.ue4ss_auto_config.stateChanged.connect(
            lambda state: self._config.set('ue4ss_auto_configure', bool(state))
        )
        layout.addWidget(self.ue4ss_auto_config)
        
        # 配置按钮
        config_btn = QPushButton("配置UE4SS设置")
        config_btn.setObjectName("secondaryBtn")
        config_btn.clicked.connect(self._configure_ue4ss)
        layout.addWidget(config_btn)
        
        group.setLayout(layout)
        return group
    
    def _build_palschema_section(self) -> QGroupBox:
        """Build the PalSchema configuration section."""
        group = QGroupBox("PalSchema 框架")
        layout = QVBoxLayout()
        
        status_layout = QHBoxLayout()
        
        self.ps_status_label = QLabel("状态: 检测中...")
        status_layout.addWidget(self.ps_status_label)
        
        status_layout.addStretch()
        
        self.ps_open_btn = QPushButton("打开配置文件夹")
        self.ps_open_btn.setObjectName("secondaryBtn")
        self.ps_open_btn.clicked.connect(self._open_palschema_folder)
        status_layout.addWidget(self.ps_open_btn)
        
        layout.addLayout(status_layout)
        
        self.ps_version_label = QLabel("")
        self.ps_version_label.setStyleSheet("color: #6c6c7e; font-size: 11px;")
        layout.addWidget(self.ps_version_label)
        
        group.setLayout(layout)
        return group
    
    def _build_general_section(self) -> QGroupBox:
        """Build general preferences section."""
        group = QGroupBox("常规偏好")
        layout = QVBoxLayout()
        
        # 主题
        theme_layout = QHBoxLayout()
        theme_layout.addWidget(QLabel("主题:"))
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深色", "浅色"])
        current_theme = self._config.get('theme', 'dark')
        # Block signals during initialization to avoid premature theme application
        self.theme_combo.blockSignals(True)
        self.theme_combo.setCurrentText("深色" if current_theme == "dark" else "浅色")
        self.theme_combo.blockSignals(False)
        self.theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self.theme_combo)
        theme_layout.addStretch()
        layout.addLayout(theme_layout)
        
        # 确认选项
        self.confirm_uninstall = QCheckBox("卸载Mod前确认")
        self.confirm_uninstall.setChecked(self._config.get('confirm_before_uninstall', True))
        self.confirm_uninstall.stateChanged.connect(
            lambda state: self._config.set('confirm_before_uninstall', bool(state))
        )
        layout.addWidget(self.confirm_uninstall)

        # 跳过 HTTPS 证书校验（代理 / 自签名证书网络环境）
        self.skip_cert_verify = QCheckBox("跳过 HTTPS 证书校验（用于代理 / 自签名证书网络）")
        self.skip_cert_verify.setToolTip(
            "开启后更新检查与下载将不再验证服务器证书。\n"
            "适用于校园网 / 公司代理等会拦截 HTTPS 的网络，可解决\n"
            "“CERTIFICATE_VERIFY_FAILED”导致的更新检查失败。\n"
            "注意：关闭校验会降低安全性，仅在必要时开启。")
        self.skip_cert_verify.setChecked(bool(self._config.get('skip_cert_verify', False)))
        self.skip_cert_verify.stateChanged.connect(
            lambda state: self._apply_skip_cert_verify(bool(state)))
        layout.addWidget(self.skip_cert_verify)

        group.setLayout(layout)
        return group
    
    def _on_theme_changed(self, text: str):
        """Handle theme change - apply immediately."""
        theme = 'dark' if text == "深色" else 'light'
        
        # Apply theme to main window
        main_window = self.window()
        if main_window and hasattr(main_window, 'apply_theme'):
            main_window.apply_theme(theme)

    def _apply_skip_cert_verify(self, enabled: bool):
        """开启/关闭跳过证书校验：写入配置并实时应用到更新模块。"""
        self._config.set('skip_cert_verify', enabled)
        try:
            from ..utils.updater import set_skip_cert_verify
            set_skip_cert_verify(enabled)
        except Exception:
            pass
    
    def refresh_theme(self):
        """Update all inline styles to match the current theme."""
        # Update quick setup group style
        if hasattr(self, 'quick_setup_group'):
            self.quick_setup_group.setStyleSheet(get_settings_group_style('quick_setup'))
        
        # Refresh framework status labels
        game_path = self._config.get('game_path', '')
        if game_path:
            self._update_framework_status(game_path)
        
        # Refresh server framework status
        server_path = self._config.get('server_path', '')
        if server_path:
            self._update_server_framework_status(server_path)
    
    def _load_settings(self):
        """Load current settings into UI."""
        game_path = self._config.get('game_path', '')
        self.game_path_input.setText(game_path)
        if game_path:
            self._update_game_status(game_path)
            self._update_framework_status(game_path)
        
        server_path = self._config.get('server_path', '')
        self.server_path_input.setText(server_path)
        if server_path:
            self._update_server_status(server_path)
        
        # Update URL is built-in — no longer configurable
    
    def _browse_game_path(self):
        """Open file dialog to select game path."""
        path = QFileDialog.getExistingDirectory(
            self, "选择幻兽帕鲁安装目录",
            self.game_path_input.text() or "C:/"
        )
        
        if path:
            self.game_path_input.setText(path)
            self._config.set('game_path', path)
            self._update_game_status(path)
            self._update_framework_status(path)
            self.game_path_changed.emit(path)
    
    def _auto_detect(self):
        """Auto-detect Palworld installation."""
        path = find_palworld_installation()
        
        if path:
            self.game_path_input.setText(path)
            self._config.set('game_path', path)
            self._update_game_status(path)
            self._update_framework_status(path)
            self.game_path_changed.emit(path)
            QMessageBox.information(self, "自动检测", f"找到幻兽帕鲁安装目录:\n{path}")
        else:
            QMessageBox.warning(
                self, "未找到",
                "无法自动找到幻兽帕鲁安装目录。\n"
                "请手动选择安装目录。"
            )
    
    # ---- Server path methods ----
    
    def _browse_server_path(self):
        """Open file dialog to select server path."""
        path = QFileDialog.getExistingDirectory(
            self, "选择PalServer安装目录",
            self.server_path_input.text() or "C:/"
        )
        
        if path:
            self.server_path_input.setText(path)
            self._config.set('server_path', path)
            self._update_server_status(path)
            self.server_path_changed.emit(path)
    
    def _auto_detect_server(self):
        """Auto-detect PalServer installation."""
        path = find_palserver_installation()
        
        if path:
            self.server_path_input.setText(path)
            self._config.set('server_path', path)
            self._update_server_status(path)
            self.server_path_changed.emit(path)
            QMessageBox.information(self, "自动检测", f"找到PalServer安装目录:\n{path}")
        else:
            QMessageBox.warning(
                self, "未找到",
                "无法自动找到PalServer安装目录。\n"
                "请手动选择安装目录。"
            )
    
    def _update_server_status(self, path: str):
        """Update the server path status indicator."""
        if is_valid_palserver_path(path):
            self.server_status_label.setText("有效的 PalServer 安装")
            self.server_status_label.setStyleSheet("color: #1a7f37; font-size: 12px; padding: 4px 0;")
            self._update_server_framework_status(path)
        else:
            self.server_status_label.setText("无效或未找到")
            self.server_status_label.setStyleSheet("color: #cf222e; font-size: 12px; padding: 4px 0;")
            self.server_framework_label.setText("")
    
    def _update_server_framework_status(self, path: str):
        """Update server framework status display."""
        ue4ss = UE4SSService(path)
        ps = PalSchemaService(path)
        
        ue4ss_ok = ue4ss.is_installed()
        ps_ok = ps.is_installed()
        
        parts = []
        if ue4ss_ok:
            parts.append("UE4SS 已安装")
        else:
            parts.append("UE4SS 未安装")
        
        if ps_ok:
            parts.append("PalSchema 已安装")
        else:
            parts.append("PalSchema 未安装")
        
        self.server_framework_label.setText(" · ".join(parts))
        
        if ue4ss_ok and ps_ok:
            self.server_framework_label.setStyleSheet("color: #1a7f37; font-size: 11px;")
        else:
            self.server_framework_label.setStyleSheet("color: #9a6700; font-size: 11px;")
    
    def _on_server_setup(self):
        """Install frameworks to server directory."""
        parent = self.window()
        if hasattr(parent, '_auto_setup_frameworks'):
            server_path = self._config.get('server_path', '')
            if not server_path or not is_valid_palserver_path(server_path):
                QMessageBox.warning(self, "错误", "请先配置 PalServer 路径。")
                return
            parent._auto_setup_frameworks(server_path)
            # Refresh server status after
            self._update_server_framework_status(server_path)
    
    def _on_server_local_setup(self):
        """Install frameworks to server from local files."""
        parent = self.window()
        if hasattr(parent, '_setup_frameworks_from_local'):
            server_path = self._config.get('server_path', '')
            if not server_path or not is_valid_palserver_path(server_path):
                QMessageBox.warning(self, "错误", "请先配置 PalServer 路径。")
                return
            parent._setup_frameworks_from_local(server_path)
            self._update_server_framework_status(server_path)
    
    def _on_sync_server_to_client(self):
        """Sync mods from server to client (server is the source of truth)."""
        game_path = self._config.get('game_path', '')
        server_path = self._config.get('server_path', '')
        
        if not game_path:
            QMessageBox.warning(self, "错误", "请先配置游戏客户端路径。")
            return
        if not server_path or not is_valid_palserver_path(server_path):
            QMessageBox.warning(self, "错误", "请先配置 PalServer 路径。")
            return
        
        main_window = self.window()
        if not main_window or not hasattr(main_window, '_mod_manager'):
            QMessageBox.warning(self, "错误", "请先切换到客户端模式并刷新。")
            return
        
        # Initialize server manager if needed
        if not hasattr(main_window, '_server_mod_manager') or not main_window._server_mod_manager:
            from ..core.manager import ModManager
            main_window._server_mod_manager = ModManager(server_path)
        
        # Count mods on both sides
        client_mods = [m for m in main_window._mod_manager.refresh()
                      if m.name.lower() not in main_window._mod_manager.scanner.UE4SS_BUILTIN_MODS]
        server_mods = main_window._server_mod_manager.refresh()
        server_mods_filtered = [m for m in server_mods
                               if m.name.lower() not in main_window._server_mod_manager.scanner.UE4SS_BUILTIN_MODS]
        
        client_names = {m.name for m in client_mods}
        server_names = {m.name for m in server_mods_filtered}
        
        missing_on_client = server_names - client_names
        extra_on_client = client_names - server_names
        
        reply = QMessageBox.question(
            self, "同步确认（服务器→客户端）",
            f"将以服务器 Mod 为准，使客户端与服务器完全一致。\n\n"
            f"服务器: {len(server_mods_filtered)} 个 Mod\n"
            f"客户端: {len(client_mods)} 个 Mod\n\n"
            f"操作预览:\n"
            f"• 复制到客户端: {len(missing_on_client)} 个\n"
            f"• 从客户端删除: {len(extra_on_client)} 个\n\n"
            f"客户端将被覆盖为与服务器完全一致，是否继续？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        
        if reply != QMessageBox.Yes:
            return
        
        try:
            copied, deleted, fail, messages = main_window._server_mod_manager.sync_mirror(game_path)
            
            main_window._mod_manager.refresh()
            main_window._refresh_mods()
            main_window._update_framework_status_bar()
            
            result_msg = f"已复制: {copied} 个\n已删除: {deleted} 个"
            if fail > 0:
                result_msg += f"\n失败: {fail} 个\n\n"
                result_msg += "\n".join(messages[:10])
                QMessageBox.warning(self, "同步结果", result_msg)
            else:
                result_msg += f"\n\n客户端 Mod 已与服务器完全一致！"
                QMessageBox.information(self, "同步完成", result_msg)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"同步过程出错:\n{str(e)}")
    
    def _on_sync_client_to_server(self):
        """Sync mods from client to server (client is the source of truth)."""
        game_path = self._config.get('game_path', '')
        server_path = self._config.get('server_path', '')
        
        if not game_path:
            QMessageBox.warning(self, "错误", "请先配置游戏客户端路径。")
            return
        if not server_path or not is_valid_palserver_path(server_path):
            QMessageBox.warning(self, "错误", "请先配置 PalServer 路径。")
            return
        
        main_window = self.window()
        if not main_window or not hasattr(main_window, '_mod_manager') or not main_window._mod_manager:
            QMessageBox.warning(self, "错误", "请先在客户端模式刷新 Mod 列表。")
            return
        
        # Initialize server manager if needed
        if not hasattr(main_window, '_server_mod_manager') or not main_window._server_mod_manager:
            from ..core.manager import ModManager
            main_window._server_mod_manager = ModManager(server_path)
        
        # Count mods on both sides
        client_mods = [m for m in main_window._mod_manager.refresh()
                      if m.name.lower() not in main_window._mod_manager.scanner.UE4SS_BUILTIN_MODS]
        server_mods = main_window._server_mod_manager.refresh()
        server_mods_filtered = [m for m in server_mods
                               if m.name.lower() not in main_window._server_mod_manager.scanner.UE4SS_BUILTIN_MODS]
        
        client_names = {m.name for m in client_mods}
        server_names = {m.name for m in server_mods_filtered}
        
        missing_on_server = client_names - server_names
        extra_on_server = server_names - client_names
        
        reply = QMessageBox.question(
            self, "同步确认（客户端→服务器）",
            f"将以客户端 Mod 为准，使服务器与客户端完全一致。\n\n"
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
        
        try:
            copied, deleted, fail, messages = main_window._mod_manager.sync_mirror(server_path)
            
            main_window._server_mod_manager.refresh()
            main_window._refresh_mods()
            main_window._update_framework_status_bar()
            
            result_msg = f"已复制: {copied} 个\n已删除: {deleted} 个"
            if fail > 0:
                result_msg += f"\n失败: {fail} 个\n\n"
                result_msg += "\n".join(messages[:10])
                QMessageBox.warning(self, "同步结果", result_msg)
            else:
                result_msg += f"\n\n服务器 Mod 已与客户端完全一致！"
                QMessageBox.information(self, "同步完成", result_msg)
                
        except Exception as e:
            QMessageBox.critical(self, "错误", f"同步过程出错:\n{str(e)}")
    
    def _update_game_status(self, path: str):
        """Update the game path status indicator."""
        if is_valid_palworld_path(path):
            self.game_status_label.setText("有效的幻兽帕鲁安装")
            self.game_status_label.setStyleSheet("color: #1a7f37; font-size: 12px; padding: 4px 0;")
            
            version = get_game_version(path)
            if version:
                self.game_info_label.setText(f"版本: {version}")
            else:
                self.game_info_label.setText("")
        else:
            self.game_status_label.setText("无效或未找到")
            self.game_status_label.setStyleSheet("color: #cf222e; font-size: 12px; padding: 4px 0;")
            self.game_info_label.setText("")
    
    def _update_framework_status(self, path: str):
        """Update UE4SS and PalSchema status indicators."""
        if not is_valid_palworld_path(path):
            self.ue4ss_status_label.setText("状态: 游戏路径未设置")
            self.ps_status_label.setText("状态: 游戏路径未设置")
            return
        
        # UE4SS
        ue4ss = UE4SSService(path)
        if ue4ss.is_installed():
            version = ue4ss.get_version()
            self.ue4ss_status_label.setText("状态: 已安装")
            self.ue4ss_status_label.setStyleSheet("color: #1a7f37;")
            self.ue4ss_version_label.setText(f"版本: {version or '未知'}")
        else:
            self.ue4ss_status_label.setText("状态: 未安装")
            self.ue4ss_status_label.setStyleSheet("color: #cf222e;")
            self.ue4ss_version_label.setText("UE4SS是Lua和LogicMod必需的框架")
        
        # PalSchema
        ps = PalSchemaService(path)
        if ps.is_installed():
            version = ps.get_version()
            self.ps_status_label.setText("状态: 已安装")
            self.ps_status_label.setStyleSheet("color: #1a7f37;")
            self.ps_version_label.setText(f"版本: {version or '未知'}")
        else:
            self.ps_status_label.setText("状态: 未安装")
            self.ps_status_label.setStyleSheet("color: #cf222e;")
            self.ps_version_label.setText("PalSchema是配置类Mod必需的框架")
    
    def _install_ue4ss(self):
        """Install UE4SS online."""
        game_path = self._config.get('game_path', '')
        if not game_path:
            QMessageBox.warning(self, "错误", "请先设置游戏路径。")
            return
        
        ue4ss = UE4SSService(game_path)
        
        QMessageBox.information(
            self, "下载中",
            "正在从GitHub下载最新版UE4SS... 请稍候。\n"
            "下载完成后会弹出提示。"
        )
        success, msg = ue4ss.install()
        
        if success:
            if self._config.get('ue4ss_auto_configure', True):
                ue4ss.configure_for_palworld()
            
            QMessageBox.information(self, "成功", f"UE4SS安装成功！\n{msg}")
        else:
            QMessageBox.critical(self, "错误", f"安装UE4SS失败:\n{msg}")
        
        self._update_framework_status(game_path)
    
    def _install_ue4ss_local(self):
        """Install UE4SS from a local archive file."""
        game_path = self._config.get('game_path', '')
        if not game_path:
            QMessageBox.warning(self, "错误", "请先设置游戏路径。")
            return
        
        archive_path, _ = QFileDialog.getOpenFileName(
            self, "选择UE4SS压缩包", "",
            "ZIP压缩包 (*.zip);;所有文件 (*.*)"
        )
        if not archive_path:
            return
        
        ue4ss = UE4SSService(game_path)
        success, msg = ue4ss.install(archive_path)
        
        if success:
            if self._config.get('ue4ss_auto_configure', True):
                ue4ss.configure_for_palworld()
            QMessageBox.information(self, "成功", f"UE4SS安装成功！\n{msg}")
        else:
            QMessageBox.critical(self, "错误", f"安装UE4SS失败:\n{msg}")
        
        self._update_framework_status(game_path)
    
    def _uninstall_ue4ss(self):
        """Uninstall UE4SS."""
        game_path = self._config.get('game_path', '')
        if not game_path:
            return
        
        reply = QMessageBox.question(
            self,
            "确认卸载",
            "确定要卸载UE4SS吗？\n\n"
            "这将移除所有UE4SS文件并禁用所有Lua/LogicMod。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        
        if reply == QMessageBox.Yes:
            ue4ss = UE4SSService(game_path)
            success, msg = ue4ss.uninstall()
            
            if success:
                QMessageBox.information(self, "成功", msg)
            else:
                QMessageBox.critical(self, "错误", msg)
            
            self._update_framework_status(game_path)
    
    def _on_uninstall_all(self):
        """Uninstall all frameworks (UE4SS + PalSchema) and optionally all mods."""
        game_path = self._config.get('game_path', '')
        if not game_path or not is_valid_palworld_path(game_path):
            QMessageBox.warning(self, "错误", "请先配置游戏客户端路径。")
            return
        
        from ..services.framework_setup import FrameworkSetupService
        
        # Ask whether to include mods
        reply = QMessageBox.question(
            self,
            "确认卸载",
            "确定要卸载 UE4SS 和 PalSchema 框架吗？\n\n"
            "是否同时删除所有 Mod？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        
        if reply == QMessageBox.Cancel:
            return
        
        include_mods = (reply == QMessageBox.Yes)
        
        setup = FrameworkSetupService(game_path)
        success, messages = setup.uninstall_all(include_mods=include_mods)
        
        result = "\n".join(messages)
        QMessageBox.information(self, "卸载完成", result)
        
        self._update_framework_status(game_path)
        self.refresh_status()
    
    def _on_uninstall_server(self):
        """Uninstall frameworks (UE4SS + PalSchema) from the server."""
        server_path = self._config.get('server_path', '')
        if not server_path or not is_valid_palserver_path(server_path):
            QMessageBox.warning(self, "错误", "请先配置 PalServer 路径。")
            return
        
        from ..services.framework_setup import FrameworkSetupService
        
        reply = QMessageBox.question(
            self,
            "确认卸载",
            "确定要卸载服务器端 UE4SS 和 PalSchema 框架吗？\n\n"
            "是否同时删除服务器端所有 Mod？",
            QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        
        if reply == QMessageBox.Cancel:
            return
        
        include_mods = (reply == QMessageBox.Yes)
        setup = FrameworkSetupService(server_path)
        success, messages = setup.uninstall_all(include_mods=include_mods)
        
        result = "\n".join(messages)
        QMessageBox.information(self, "卸载完成", result)
        
        self._update_server_framework_status(server_path)
        self.refresh_status()
        
        # Notify main window to refresh
        main_window = self.window()
        if main_window and hasattr(main_window, '_refresh_mods'):
            main_window._refresh_mods()
            main_window._update_framework_status_bar()
    
    def _configure_ue4ss(self):
        """Configure UE4SS settings."""
        game_path = self._config.get('game_path', '')
        if not game_path:
            QMessageBox.warning(self, "错误", "请先设置游戏路径。")
            return
        
        ue4ss = UE4SSService(game_path)
        if not ue4ss.is_installed():
            QMessageBox.warning(self, "错误", "UE4SS未安装。")
            return
        
        success = ue4ss.configure_for_palworld()
        if success:
            QMessageBox.information(self, "成功", "UE4SS已为幻兽帕鲁配置完成。")
        else:
            QMessageBox.critical(self, "错误", "配置UE4SS失败。")
    
    def _open_palschema_folder(self):
        """Open the PalSchema config folder."""
        game_path = self._config.get('game_path', '')
        if not game_path:
            QMessageBox.warning(self, "错误", "请先设置游戏路径。")
            return
        
        import os
        import subprocess
        
        ps_path = os.path.join(game_path, "Pal", "Binaries", "Win64", "Mods", "PalSchema")
        if os.path.exists(ps_path):
            subprocess.Popen(f'explorer "{ps_path}"')
        else:
            QMessageBox.information(self, "提示", "PalSchema配置文件夹未找到。\n安装第一个PalSchema Mod时将自动创建。")
    
    def refresh_status(self):
        """Refresh all status indicators."""
        game_path = self._config.get('game_path', '')
        if game_path:
            self._update_game_status(game_path)
            self._update_framework_status(game_path)
        
        server_path = self._config.get('server_path', '')
        if server_path:
            self._update_server_status(server_path)
    
    def get_framework_status(self) -> dict:
        """Get the current framework installation status.
        Returns dict with keys: ue4ss_installed, ue4ss_version, palschema_installed, palschema_version
        """
        game_path = self._config.get('game_path', '')
        if not game_path or not is_valid_palworld_path(game_path):
            return {
                'ue4ss_installed': False, 'ue4ss_version': None,
                'palschema_installed': False, 'palschema_version': None,
            }
        
        ue4ss = UE4SSService(game_path)
        ps = PalSchemaService(game_path)
        
        return {
            'ue4ss_installed': ue4ss.is_installed(),
            'ue4ss_version': ue4ss.get_version(),
            'palschema_installed': ps.is_installed(),
            'palschema_version': ps.get_version(),
        }
