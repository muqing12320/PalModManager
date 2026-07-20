"""
Mod Detail Panel - shows detailed information about a selected mod.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QGroupBox, QScrollArea, QFrame, QSizePolicy,
    QListWidget, QListWidgetItem, QMessageBox,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..core.models import ModInfo, ModType, ModStatus
from ..utils.helpers import (
    get_mod_type_display, get_status_display, get_status_color,
    format_date, format_size
)
from .styles import is_dark_theme
import os
from pathlib import Path


class ModDetailPanel(QWidget):
    """Panel showing detailed information about a selected mod."""

    enable_clicked = pyqtSignal(str)
    disable_clicked = pyqtSignal(str)
    uninstall_clicked = pyqtSignal(str)
    open_folder_clicked = pyqtSignal(str)
    rename_clicked = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_mod = None
        self._init_ui()
        self._show_empty_state()

    def _init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._content_widget = QWidget()
        self._content_widget.setStyleSheet("QWidget { background: transparent; }")
        self._content_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.MinimumExpanding)
        self._content_layout = QVBoxLayout(self._content_widget)
        self._content_layout.setContentsMargins(16, 16, 16, 16)
        self._content_layout.setSpacing(12)

        scroll.setWidget(self._content_widget)
        main_layout.addWidget(scroll)

    def set_mod(self, mod):
        self._current_mod = mod
        self._clear_content()
        if not mod:
            self._show_empty_state()
            return
        self._build_header(mod)
        self._build_info_section(mod)
        self._build_dependencies_section(mod)
        self._build_actions_section(mod)
        self._content_layout.addStretch(1)

    def _clear_content(self):
        while self._content_layout.count():
            item = self._content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _show_empty_state(self):
        self._clear_content()
        self._content_layout.addStretch()
        placeholder = QLabel("选择一个Mod查看详情")
        placeholder.setAlignment(Qt.AlignCenter)
        muted_color = "#484f58" if is_dark_theme() else "#8b949e"
        placeholder.setStyleSheet(f"color: {muted_color}; font-size: 15px; padding: 40px; background: transparent;")
        self._content_layout.addWidget(placeholder)
        self._content_layout.addStretch()

    def _make_label(self, text, style="", obj_name=""):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"background: transparent; {style}")
        if obj_name:
            lbl.setObjectName(obj_name)
        return lbl

    def _build_header(self, mod):
        dark = is_dark_theme()
        
        # Title
        title = self._make_label(mod.name, "font-size: 18px; font-weight: 700;", "titleLabel")
        self._content_layout.addWidget(title)

        # Sub row
        sub = QHBoxLayout()
        sec_color = "#8b949e" if dark else "#656d76"
        sub.addWidget(self._make_label(f"v{mod.version} · {mod.author}", f"font-size: 12px; color: {sec_color};"))
        sub.addStretch()

        status_color = get_status_color(mod.status.value)
        status_text = get_status_display(mod.status.value)
        badge = self._make_label(f" {status_text} ",
            f"background-color: {status_color}22; color: {status_color}; "
            f"border: 1px solid {status_color}44; border-radius: 10px; "
            f"padding: 2px 10px; font-size: 11px; font-weight: 600;")
        sub.addWidget(badge)
        self._content_layout.addLayout(sub)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep_color = "#30363d" if dark else "#d0d7de"
        sep.setStyleSheet(f"QFrame {{ color: {sep_color}; background: transparent; }}")
        self._content_layout.addWidget(sep)

        # Status toggle
        btn = QPushButton("禁用Mod" if mod.status == ModStatus.ENABLED else "启用Mod")
        btn.setObjectName("dangerBtn" if mod.status == ModStatus.ENABLED else "successBtn")
        btn.setFixedWidth(120)
        if mod.status == ModStatus.ENABLED:
            btn.clicked.connect(lambda: self.disable_clicked.emit(mod.id))
        else:
            btn.clicked.connect(lambda: self.enable_clicked.emit(mod.id))
        self._content_layout.addWidget(btn)

    def _build_info_section(self, mod):
        dark = is_dark_theme()
        grp = QGroupBox("信息")
        layout = QVBoxLayout()
        layout.setSpacing(6)

        if mod.description:
            desc_color = "#c9d1d9" if dark else "#1f2328"
            # Use QTextEdit for scrollable description text
            desc_edit = QTextEdit()
            desc_edit.setPlainText(mod.description)
            desc_edit.setReadOnly(True)
            desc_edit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            desc_edit.setStyleSheet(
                f"QTextEdit {{ "
                f"color: {desc_color}; "
                f"background: transparent; "
                f"border: none; "
                f"padding: 4px 0; "
                f"font-size: 12px; "
                f"}}"
            )
            # Fixed maximum height with scrollbar for long content
            desc_edit.setMaximumHeight(220)
            desc_edit.setMinimumHeight(40)
            desc_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            desc_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            desc_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            layout.addWidget(desc_edit)

        if mod.mod_type:
            sec_color = "#8b949e" if dark else "#656d76"
            layout.addWidget(self._make_label(f"类型: {get_mod_type_display(mod.mod_type.value)}",
                f"color: {sec_color}; font-size: 12px;"))

        p = Path(mod.install_path) if mod.install_path else None
        muted_color = "#484f58" if dark else "#8b949e"
        if p and p.exists():
            path_label = self._make_label(f"路径: {mod.install_path}",
                f"color: {muted_color}; font-size: 11px; font-family: Consolas, monospace;")
            path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            path_label.setWordWrap(True)
            layout.addWidget(path_label)
            if p.is_dir():
                try:
                    size = sum(f.stat().st_size for f in p.rglob('*') if f.is_file())
                except Exception:
                    size = 0
            else:
                size = p.stat().st_size
            layout.addWidget(self._make_label(f"大小: {format_size(size)}",
                f"color: {muted_color}; font-size: 11px;"))

        if mod.installed_date:
            layout.addWidget(self._make_label(f"安装时间: {format_date(mod.installed_date)}",
                f"color: {muted_color}; font-size: 11px;"))

        if mod.website:
            accent_color = "#58a6ff" if dark else "#0969da"
            web_label = self._make_label(f"网站: {mod.website}",
                f"color: {accent_color}; font-size: 11px;")
            web_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            layout.addWidget(web_label)

        if mod.tags:
            layout.addWidget(self._make_label(f"标签: {', '.join(mod.tags)}",
                f"color: {muted_color}; font-size: 11px;"))

        grp.setLayout(layout)
        grp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._content_layout.addWidget(grp)

    def _build_dependencies_section(self, mod):
        if not mod.dependencies and not mod.required_frameworks:
            return
        dark = is_dark_theme()
        grp = QGroupBox("依赖")
        layout = QVBoxLayout()
        layout.setSpacing(4)
        if mod.required_frameworks:
            warn_color = "#d29922" if dark else "#9a6700"
            layout.addWidget(self._make_label(f"框架: {', '.join(mod.required_frameworks)}",
                f"color: {warn_color}; font-size: 12px;"))
        if mod.dependencies:
            sec_color = "#8b949e" if dark else "#656d76"
            layout.addWidget(self._make_label(f"Mod: {', '.join(mod.dependencies)}",
                f"color: {sec_color}; font-size: 12px;"))
        grp.setLayout(layout)
        self._content_layout.addWidget(grp)

    def _build_actions_section(self, mod):
        grp = QGroupBox("操作")
        layout = QVBoxLayout()
        row = QHBoxLayout()

        rename_btn = QPushButton("重命名")
        rename_btn.setObjectName("secondaryBtn")
        rename_btn.clicked.connect(lambda: self.rename_clicked.emit(mod.id))
        row.addWidget(rename_btn)

        open_btn = QPushButton("打开文件夹")
        open_btn.setObjectName("secondaryBtn")
        open_btn.clicked.connect(lambda: self.open_folder_clicked.emit(mod.id))
        row.addWidget(open_btn)

        row.addStretch()

        uninstall_btn = QPushButton("卸载")
        uninstall_btn.setObjectName("dangerBtn")
        uninstall_btn.clicked.connect(lambda: self._confirm_uninstall(mod))
        row.addWidget(uninstall_btn)

        layout.addLayout(row)
        grp.setLayout(layout)
        self._content_layout.addWidget(grp)

    def _confirm_uninstall(self, mod):
        reply = QMessageBox.question(
            self, "确认卸载",
            f"确定要卸载 '{mod.name}' 吗？\n\n这将永久删除Mod文件。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.uninstall_clicked.emit(mod.id)
