"""
Mod List Widget - displays the list of installed mods with filtering and sorting.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLabel, QLineEdit, QComboBox, QPushButton, QMenu, QAction,
    QCheckBox, QFrame, QSizePolicy, QAbstractItemView
)
from PyQt5.QtCore import Qt, pyqtSignal, QSize
from PyQt5.QtGui import QIcon, QFont, QColor

from ..core.models import ModInfo, ModType, ModStatus
from ..utils.helpers import get_mod_type_display, get_status_display, get_status_color
from .styles import is_dark_theme


class ModListWidget(QWidget):
    """Widget displaying the list of mods with filtering."""
    
    mod_selected = pyqtSignal(str)  # mod_id
    mod_toggled = pyqtSignal(str)   # mod_id
    mod_context_menu = pyqtSignal(str, object)  # mod_id, position
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self._all_mods: list = []
        self._filtered_mods: list = []
        self._current_filter = ""
        self._current_type_filter = "All"
        self._current_status_filter = "All"
        self._show_disabled = True
        
        self._init_ui()
    
    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Header
        header = QHBoxLayout()
        
        title = QLabel("Mod列表")
        title.setObjectName("titleLabel")
        header.addWidget(title)
        
        header.addStretch()
        
        mod_count = QLabel("0 个Mod")
        mod_count.setObjectName("statLabel")
        mod_count.setObjectName("modCountLabel")
        header.addWidget(mod_count)
        
        layout.addLayout(header)
        
        # 搜索栏
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索Mod...")
        self.search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self.search_input)
        
        layout.addLayout(search_layout)
        
        # 筛选器
        filter_layout = QHBoxLayout()
        
        self.type_filter = QComboBox()
        self.type_filter.addItems(["全部类型", "UE4SS Lua", "LogicMod", "PAK Mod", "PalSchema"])
        self.type_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.type_filter)
        
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部状态", "已启用", "已禁用", "冲突", "错误"])
        self.status_filter.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self.status_filter)
        
        layout.addLayout(filter_layout)
        
        # Mod list
        self.mod_list = QListWidget()
        self.mod_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.mod_list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.mod_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mod_list.itemClicked.connect(self._on_item_clicked)
        self.mod_list.customContextMenuRequested.connect(self._on_context_menu)
        self.mod_list.setIconSize(QSize(40, 40))
        layout.addWidget(self.mod_list)
    
    def set_mods(self, mods: list):
        """Set the list of mods to display."""
        self._all_mods = mods
        self._apply_filters()
    
    def _apply_filters(self):
        """Apply current filters to the mod list."""
        self._filtered_mods = []
        
        search_text = self.search_input.text().lower()
        
        for mod in self._all_mods:
            # Text search
            if search_text:
                searchable = f"{mod.name} {mod.author} {mod.description} {mod.version} {' '.join(mod.tags)}".lower()
                if search_text not in searchable:
                    continue
            
            # Type filter
            type_map = {
                "UE4SS Lua": ModType.UE4SS_LUA,
                "LogicMod": ModType.LOGIC,
                "PAK Mod": ModType.PAK,
                "PalSchema": ModType.PALSCHEMA,
            }
            if self.type_filter.currentText() != "全部类型":
                if mod.mod_type != type_map.get(self.type_filter.currentText()):
                    continue
            
            # Status filter
            status_map = {
                "已启用": ModStatus.ENABLED,
                "已禁用": ModStatus.DISABLED,
                "冲突": ModStatus.CONFLICT,
                "错误": ModStatus.ERROR,
            }
            if self.status_filter.currentText() != "全部状态":
                if mod.status != status_map.get(self.status_filter.currentText()):
                    continue
            
            self._filtered_mods.append(mod)
        
        # Sort: type first, then alphabetical by name
        type_order = {
            ModType.UE4SS_LUA: 0,
            ModType.LOGIC: 1,
            ModType.PAK: 2,
            ModType.PALSCHEMA: 3,
        }
        self._filtered_mods.sort(
            key=lambda m: (type_order.get(m.mod_type, 99), m.name.lower())
        )
        
        self._update_list_display()
    
    def _update_list_display(self):
        """Update the list widget with filtered mods."""
        self.mod_list.clear()
        
        for mod in self._filtered_mods:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, mod.id)
            item.setSizeHint(QSize(0, 64))
            
            # Create custom widget for the item
            widget = self._create_mod_item_widget(mod)
            self.mod_list.addItem(item)
            self.mod_list.setItemWidget(item, widget)
        
        # Update count
        count_label = self.findChild(QLabel, "modCountLabel")
        if count_label:
            count_label.setText(f"{len(self._filtered_mods)} 个Mod")
    
    def _create_mod_item_widget(self, mod: ModInfo) -> QWidget:
        """Create a rich widget for displaying a mod in the list."""
        widget = QFrame()
        widget.setStyleSheet("QFrame { background: transparent; border: none; }")
        
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(10)
        
        # Checkbox for enable/disable
        checkbox = QCheckBox()
        checkbox.setChecked(mod.status == ModStatus.ENABLED)
        checkbox.setToolTip("勾选启用 / 取消禁用")
        checkbox.toggled.connect(lambda checked, mid=mod.id: self.mod_toggled.emit(mid))
        layout.addWidget(checkbox, alignment=Qt.AlignVCenter)
        
        # Type badge - small colored pill (theme-aware)
        dark = is_dark_theme()
        type_colors = {
            ModType.UE4SS_LUA: ('#3fb950', '#1a3324') if dark else ('#1a7f37', '#dafbe1'),
            ModType.UE4SS_BLUEPRINT: ('#58a6ff', '#1a2f3d') if dark else ('#0969da', '#ddf4ff'),
            ModType.PAK: ('#d29922', '#332b1a') if dark else ('#9a6700', '#fff8c5'),
            ModType.PALSCHEMA: ('#7c3aed', '#241a3d') if dark else ('#8250df', '#fbefff'),
            ModType.LOGIC: ('#f0883e', '#331e1a') if dark else ('#bc4c00', '#fff1e5'),
            ModType.UNKNOWN: ('#8b949e', '#1c2128') if dark else ('#656d76', '#f6f8fa'),
        }
        tc = type_colors.get(mod.mod_type, ('#8b949e', '#1c2128') if dark else ('#656d76', '#f6f8fa'))
        type_label = QLabel(f" {get_mod_type_display(mod.mod_type.value)} ")
        type_label.setFont(QFont("Segoe UI", 8, QFont.Bold))
        type_label.setStyleSheet(f"""
            QLabel {{
                background-color: {tc[1]};
                color: {tc[0]};
                border: 1px solid {tc[0]}44;
                border-radius: 10px;
                padding: 2px 8px;
            }}
        """)
        type_label.setFixedHeight(20)
        type_label.setToolTip(get_mod_type_display(mod.mod_type.value))
        
        # Mod info
        info_layout = QVBoxLayout()
        info_layout.setSpacing(3)
        
        # Row 1: Name + type badge
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        
        name_color = "#e6edf3" if dark else "#1f2328"
        name_label = QLabel(mod.name)
        name_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        name_label.setStyleSheet(f"color: {name_color}; background: transparent;")
        top_row.addWidget(name_label)
        top_row.addWidget(type_label)
        top_row.addStretch()
        info_layout.addLayout(top_row)
        
        # Row 2: Version + author
        parts = [f"v{mod.version}"]
        if mod.author and mod.author != "Unknown":
            parts.append(mod.author)
        
        sub_color = "#8b949e" if dark else "#656d76"
        subtitle_label = QLabel(" · ".join(parts))
        subtitle_label.setFont(QFont("Segoe UI", 9))
        subtitle_label.setStyleSheet(f"color: {sub_color}; background: transparent;")
        info_layout.addWidget(subtitle_label)
        
        # Row 3: Description (separate line, only if present)
        if mod.description:
            desc_color = "#c9d1d9" if dark else "#57606a"
            desc_text = mod.description
            if len(desc_text) > 120:
                desc_text = desc_text[:117] + "..."
            desc_label = QLabel(desc_text)
            desc_label.setFont(QFont("Segoe UI", 9))
            desc_label.setStyleSheet(f"color: {desc_color}; background: transparent;")
            desc_label.setWordWrap(True)
            desc_label.setMaximumHeight(36)
            info_layout.addWidget(desc_label)
        else:
            # Add empty spacer when no description, so card height stays consistent
            spacer = QLabel("")
            spacer.setFixedHeight(4)
            info_layout.addWidget(spacer)
        
        # Row 4: Tags (if any)
        if mod.tags:
            tag_widgets = QHBoxLayout()
            tag_widgets.setSpacing(4)
            tag_fg = "#58a6ff" if dark else "#0969da"
            tag_bg = "#1a2f3d" if dark else "#ddf4ff"
            for tag in mod.tags[:3]:
                tag_lbl = QLabel(tag)
                tag_lbl.setFont(QFont("Segoe UI", 8))
                tag_lbl.setStyleSheet(f"""
                    QLabel {{
                        color: {tag_fg};
                        background-color: {tag_bg};
                        border-radius: 8px;
                        padding: 1px 8px;
                    }}
                """)
                tag_widgets.addWidget(tag_lbl)
            tag_widgets.addStretch()
            info_layout.addLayout(tag_widgets)
        
        layout.addLayout(info_layout, 1)
        
        # Toggle switch - modern pill style
        toggle_btn = QPushButton()
        if mod.status == ModStatus.ENABLED:
            toggle_btn.setText(" 已启用 ")
            toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {"#1a3324" if dark else "#dafbe1"};
                    color: {"#3fb950" if dark else "#1a7f37"};
                    border: 1px solid {"#3fb95044" if dark else "#1a7f3744"};
                    border-radius: 12px;
                    padding: 5px 14px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ 
                    background-color: {"#2a4434" if dark else "#b3e6c3"}; 
                    border-color: {"#3fb950" if dark else "#1a7f37"};
                }}
            """)
        else:
            toggle_btn.setText(" 已禁用 ")
            toggle_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {"#1c2128" if dark else "#f6f8fa"};
                    color: {"#8b949e" if dark else "#656d76"};
                    border: 1px solid {"#30363d" if dark else "#d0d7de"};
                    border-radius: 12px;
                    padding: 5px 14px;
                    font-size: 11px;
                    font-weight: 600;
                }}
                QPushButton:hover {{ 
                    background-color: {"#2a2d33" if dark else "#eaeef2"}; 
                    border-color: {"#484f58" if dark else "#8b949e"};
                }}
            """)
        
        toggle_btn.setCursor(Qt.PointingHandCursor)
        toggle_btn.clicked.connect(lambda checked, mid=mod.id: self.mod_toggled.emit(mid))
        layout.addWidget(toggle_btn, alignment=Qt.AlignVCenter)
        
        return widget
    
    def _on_item_clicked(self, item: QListWidgetItem):
        """Handle mod item click."""
        mod_id = item.data(Qt.UserRole)
        if mod_id:
            self.mod_selected.emit(mod_id)
    
    def _on_search_changed(self, text: str):
        """Handle search text change."""
        self._apply_filters()
    
    def _on_filter_changed(self):
        """Handle filter combo box change."""
        self._apply_filters()
    
    def _on_context_menu(self, pos):
        """Handle right-click context menu."""
        item = self.mod_list.itemAt(pos)
        if item:
            mod_id = item.data(Qt.UserRole)
            if mod_id:
                self.mod_context_menu.emit(mod_id, pos)
    
    def _on_batch_action(self, action: str):
        """Handle batch enable/disable."""
        # These signals will be connected to the main window
        pass
    
    def get_selected_mod_ids(self) -> list:
        """Get list of selected mod IDs."""
        return [item.data(Qt.UserRole) for item in self.mod_list.selectedItems()]
    
    def select_mod(self, mod_id: str):
        """Programmatically select a mod."""
        for i in range(self.mod_list.count()):
            item = self.mod_list.item(i)
            if item.data(Qt.UserRole) == mod_id:
                self.mod_list.setCurrentItem(item)
                break
