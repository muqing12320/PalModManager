"""
Profile Management Dialog - for saving and loading mod profiles.
"""
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QTextEdit, QListWidget, QListWidgetItem,
    QMessageBox, QGroupBox, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont

from ..core.models import ModProfile
from ..utils.helpers import format_date


class ProfileDialog(QDialog):
    """Dialog for managing mod profiles."""
    
    profile_selected = pyqtSignal(str)  # profile name
    
    def __init__(self, profiles: list, parent=None):
        super().__init__(parent)
        self._profiles = profiles
        self._init_ui()
        self._populate_profiles()
    
    def _init_ui(self):
        self.setWindowTitle("Mod方案管理")
        self.setMinimumSize(500, 400)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        
        # 标题
        title = QLabel("Mod方案管理")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        
        desc = QLabel("方案允许您保存和切换不同的Mod配置组合。")
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #a0a0b0; font-size: 12px;")
        layout.addWidget(desc)
        
        # 方案列表
        self.profile_list = QListWidget()
        self.profile_list.itemClicked.connect(self._on_profile_selected)
        layout.addWidget(self.profile_list)
        
        # 创建新方案
        create_group = QGroupBox("创建新方案")
        create_layout = QVBoxLayout()
        
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("名称:"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("方案名称...")
        name_layout.addWidget(self.name_input)
        create_layout.addLayout(name_layout)
        
        self.desc_input = QTextEdit()
        self.desc_input.setPlaceholderText("描述（可选）...")
        self.desc_input.setMaximumHeight(60)
        create_layout.addWidget(self.desc_input)
        
        create_btn = QPushButton("保存当前配置为方案")
        create_btn.clicked.connect(self._on_create_profile)
        create_layout.addWidget(create_btn)
        
        create_group.setLayout(create_layout)
        layout.addWidget(create_group)
        
        # 按钮
        btn_layout = QHBoxLayout()
        
        self.load_btn = QPushButton("加载选中")
        self.load_btn.setObjectName("successBtn")
        self.load_btn.clicked.connect(self._on_load_profile)
        self.load_btn.setEnabled(False)
        btn_layout.addWidget(self.load_btn)
        
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("dangerBtn")
        self.delete_btn.clicked.connect(self._on_delete_profile)
        self.delete_btn.setEnabled(False)
        btn_layout.addWidget(self.delete_btn)
        
        btn_layout.addStretch()
        
        close_btn = QPushButton("关闭")
        close_btn.setObjectName("secondaryBtn")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(close_btn)
        
        layout.addLayout(btn_layout)
    
    def _populate_profiles(self):
        """Populate the profile list."""
        self.profile_list.clear()
        
        for profile in self._profiles:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, profile.name)
            
            text = f"{profile.name}"
            if profile.description:
                text += f"\n  {profile.description}"
            text += f"\n  {len(profile.enabled_mods)} 个Mod · {format_date(profile.created_date)}"
            
            item.setText(text)
            self.profile_list.addItem(item)
    
    def _on_profile_selected(self, item: QListWidgetItem):
        """Handle profile selection."""
        self.load_btn.setEnabled(True)
        self.delete_btn.setEnabled(True)
    
    def _on_load_profile(self):
        """Load the selected profile."""
        item = self.profile_list.currentItem()
        if item:
            profile_name = item.data(Qt.UserRole)
            self.profile_selected.emit(profile_name)
            self.accept()
    
    def _on_delete_profile(self):
        """Delete the selected profile."""
        item = self.profile_list.currentItem()
        if item:
            profile_name = item.data(Qt.UserRole)
            
            reply = QMessageBox.question(
                self,
                "删除方案",
                f"确定要删除方案 '{profile_name}' 吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            
            if reply == QMessageBox.Yes:
                # Parent will handle the actual deletion
                self.profile_selected.emit(f"__delete__{profile_name}")
                self._profiles = [p for p in self._profiles if p.name != profile_name]
                self._populate_profiles()
    
    def _on_create_profile(self):
        """Create a new profile."""
        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "错误", "请输入方案名称。")
            return
        
        # Signal parent to save profile
        self.profile_selected.emit(f"__create__{name}")
        
        desc = self.desc_input.toPlainText().strip()
        self.name_input.clear()
        self.desc_input.clear()
        
        QMessageBox.information(self, "成功", f"方案 '{name}' 已保存！")
        self.accept()
    
    def get_create_info(self) -> tuple:
        """Get the create profile info."""
        name = self.name_input.text().strip()
        desc = self.desc_input.toPlainText().strip()
        return name, desc
