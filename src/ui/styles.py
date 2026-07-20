"""
Styles and theme definitions for the 帕鲁Mod管理器 UI.
"""
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

# Global current theme name
_current_theme_name = 'dark'


DARK_THEME = {
    'bg_primary': '#0d1117',
    'bg_secondary': '#161b22',
    'bg_card': '#1c2128',
    'bg_input': '#0d1117',
    'bg_hover': '#1f2937',
    'bg_selected': '#1a3a5c',
    'text_primary': '#e6edf3',
    'text_secondary': '#8b949e',
    'text_muted': '#484f58',
    'text_bright': '#ffffff',
    'accent': '#58a6ff',
    'accent_hover': '#79c0ff',
    'accent_secondary': '#7c3aed',
    'success': '#3fb950',
    'warning': '#d29922',
    'error': '#f85149',
    'info': '#58a6ff',
    'border': '#30363d',
    'border_focus': '#58a6ff',
    'divider': '#21262d',
    'scrollbar_handle': '#30363d',
    'scrollbar_handle_hover': '#484f58',
}

LIGHT_THEME = {
    'bg_primary': '#ffffff',
    'bg_secondary': '#f6f8fa',
    'bg_card': '#ffffff',
    'bg_input': '#f6f8fa',
    'bg_hover': '#eaeef2',
    'bg_selected': '#ddf4ff',
    'text_primary': '#1f2328',
    'text_secondary': '#656d76',
    'text_muted': '#8b949e',
    'text_bright': '#0d1117',
    'accent': '#0969da',
    'accent_hover': '#0550ae',
    'accent_secondary': '#8250df',
    'success': '#1a7f37',
    'warning': '#9a6700',
    'error': '#cf222e',
    'info': '#0969da',
    'border': '#d0d7de',
    'border_focus': '#0969da',
    'divider': '#d8dee4',
    'scrollbar_handle': '#c1c7cd',
    'scrollbar_handle_hover': '#8b949e',
}


def get_theme(theme_name='dark'):
    global _current_theme_name
    _current_theme_name = theme_name
    return LIGHT_THEME if theme_name == 'light' else DARK_THEME


def get_current_theme_name():
    return _current_theme_name


def is_dark_theme():
    return _current_theme_name == 'dark'


def get_toolbar_button_style(btn_type='default'):
    """Get toolbar button style based on current theme and button type.
    
    btn_type can be: 'default', 'mode', 'install', 'delete', 'sync', 'launch'
    """
    dark = is_dark_theme()
    base = "padding: 6px 16px; font-size: 12px; font-weight: 600; border-radius: 6px;"
    
    if btn_type == 'mode':
        if dark:
            return base + """
                QPushButton {
                    background-color: #1c2840;
                    color: #58a6ff;
                    border: 1px solid #58a6ff44;
                }
                QPushButton:hover { background-color: #243860; border-color: #58a6ff; }
            """
        else:
            return base + """
                QPushButton {
                    background-color: #ddf4ff;
                    color: #0969da;
                    border: 1px solid #0969da44;
                }
                QPushButton:hover { background-color: #b6e3ff; border-color: #0969da; }
            """
    
    elif btn_type == 'install':
        if dark:
            return base + """
                QPushButton {
                    background-color: #1a3324;
                    color: #3fb950;
                    border: 1px solid #3fb95044;
                }
                QPushButton:hover { background-color: #2a4434; border-color: #3fb950; }
            """
        else:
            return base + """
                QPushButton {
                    background-color: #dafbe1;
                    color: #1a7f37;
                    border: 1px solid #1a7f3744;
                }
                QPushButton:hover { background-color: #b3e6c3; border-color: #1a7f37; }
            """
    
    elif btn_type == 'delete':
        if dark:
            return """
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
            """
        else:
            return """
                QPushButton {
                    background-color: #ffebe9;
                    color: #cf222e;
                    border: 1px solid #cf222e44;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #ffd4d1; border-color: #cf222e; }
            """
    
    elif btn_type == 'sync':
        if dark:
            return """
                QPushButton {
                    background-color: #1a2f3d;
                    color: #58a6ff;
                    border: 1px solid #58a6ff44;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #243860; border-color: #58a6ff; }
            """
        else:
            return """
                QPushButton {
                    background-color: #ddf4ff;
                    color: #0969da;
                    border: 1px solid #0969da44;
                    border-radius: 6px;
                    padding: 6px 16px;
                    font-size: 12px;
                    font-weight: 600;
                }
                QPushButton:hover { background-color: #b6e3ff; border-color: #0969da; }
            """
    
    elif btn_type == 'launch':
        if dark:
            return base + """
                QPushButton {
                    background-color: #331b1b;
                    color: #f85149;
                    border: 1px solid #f8514944;
                }
                QPushButton:hover { background-color: #442a2a; border-color: #f85149; }
            """
        else:
            return base + """
                QPushButton {
                    background-color: #ffebe9;
                    color: #cf222e;
                    border: 1px solid #cf222e44;
                }
                QPushButton:hover { background-color: #ffd4d1; border-color: #cf222e; }
            """
    elif btn_type == 'update':
        if dark:
            return base + """
                QPushButton {
                    background-color: #1b332b;
                    color: #3fb950;
                    border: 1px solid #3fb95044;
                }
                QPushButton:hover { background-color: #2a4435; border-color: #3fb950; }
            """
        else:
            return base + """
                QPushButton {
                    background-color: #dafbe1;
                    color: #1a7f37;
                    border: 1px solid #1a7f3744;
                }
                QPushButton:hover { background-color: #b8eec5; border-color: #1a7f37; }
            """
    
    else:  # default
        return base


def get_settings_group_style(group_type='default'):
    """Get settings page group box style based on current theme.
    
    group_type can be: 'default', 'quick_setup'
    """
    dark = is_dark_theme()
    
    if group_type == 'quick_setup':
        if dark:
            return """
                QGroupBox {
                    background-color: #1a2f3d;
                    border: 1px solid #58a6ff44;
                    border-radius: 10px;
                    margin-top: 20px;
                    padding: 18px 16px 16px 16px;
                    font-weight: 600;
                }
                QGroupBox::title {
                    color: #58a6ff;
                }
            """
        else:
            return """
                QGroupBox {
                    background-color: #f0f8ff;
                    border: 1px solid #0969da44;
                    border-radius: 10px;
                    margin-top: 20px;
                    padding: 18px 16px 16px 16px;
                    font-weight: 600;
                }
                QGroupBox::title {
                    color: #0969da;
                }
            """
    
    return ""


def create_stylesheet(theme_name='dark'):
    t = get_theme(theme_name)
    bg, bg2, card, inp = t['bg_primary'], t['bg_secondary'], t['bg_card'], t['bg_input']
    hov, sel = t['bg_hover'], t['bg_selected']
    tp, ts, tm, tb = t['text_primary'], t['text_secondary'], t['text_muted'], t['text_bright']
    ac, ach, ac2 = t['accent'], t['accent_hover'], t['accent_secondary']
    succ, warn, err, info = t['success'], t['warning'], t['error'], t['info']
    bd, bdf = t['border'], t['border_focus']
    sbar, sbarh = t['scrollbar_handle'], t['scrollbar_handle_hover']

    return f"""
    * {{
        font-family: 'Microsoft YaHei', 'Segoe UI', system-ui, sans-serif;
    }}

    QWidget {{
        background-color: {bg};
        color: {tp};
    }}


    QMainWindow {{
        background-color: {bg};
        color: {tp};
    }}

    QMenuBar {{
        background-color: {bg2};
        color: {tp};
        border-bottom: 1px solid {bd};
        padding: 2px 4px;
        font-size: 13px;
    }}
    QMenuBar::item {{
        padding: 4px 10px;
        border-radius: 4px;
        margin: 2px 1px;
    }}
    QMenuBar::item:selected {{ background-color: {hov}; }}

    QMenu {{
        background-color: {bg2};
        color: {tp};
        border: 1px solid {bd};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 7px 32px 7px 16px;
        border-radius: 4px;
        color: {tp};
    }}
    QMenu::item:selected {{ background-color: {ac}; color: white; }}
    QMenu::separator {{ height: 1px; background: {bd}; margin: 4px 8px; }}

    QToolBar {{
        background-color: {bg2};
        border-bottom: 1px solid {bd};
        spacing: 4px;
        padding: 6px 10px;
    }}

    QPushButton {{
        background-color: {ac};
        color: white;
        border: none;
        border-radius: 6px;
        padding: 7px 18px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{ background-color: {ach}; }}
    QPushButton:disabled {{ background-color: {tm}; color: {ts}; }}

    QPushButton#secondaryBtn {{
        background-color: transparent;
        border: 1px solid {bd};
        color: {tp};
        font-weight: normal;
    }}
    QPushButton#secondaryBtn:hover {{ background-color: {hov}; border-color: {ac}; }}

    QPushButton#dangerBtn {{ background-color: {err}; }}
    QPushButton#dangerBtn:hover {{ background-color: #ff6b6b; }}

    QPushButton#successBtn {{ background-color: {succ}; }}
    QPushButton#successBtn:hover {{ background-color: #56d364; }}

    QPushButton#refreshBtn {{ background-color: {succ}; color: white; }}
    QPushButton#refreshBtn:hover {{ background-color: #56d364; }}

    QPushButton#enableAllBtn {{ background-color: {succ}; color: white; font-weight: 600; }}
    QPushButton#enableAllBtn:hover {{ background-color: #56d364; }}

    QPushButton#disableAllBtn {{ background-color: {warn}; color: white; font-weight: 600; }}
    QPushButton#disableAllBtn:hover {{ background-color: #e2b03d; }}

    QListWidget {{
        background-color: {bg};
        border: 1px solid {bd};
        border-radius: 8px;
        padding: 6px;
        outline: none;
    }}
    QListWidget::item {{
        background-color: {card};
        border: 1px solid {bd};
        border-radius: 8px;
        padding: 0px;
        margin: 2px 0px;
    }}
    QListWidget::item:hover {{ border-color: {ac}66; }}
    QListWidget::item:selected {{ border-color: {ac}; background-color: {sel}; }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {sbar};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background-color: {sbarh}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 8px; }}
    QScrollBar::handle:horizontal {{
        background-color: {sbar};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{ background-color: {sbarh}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

    QTabWidget::pane {{ background-color: {bg}; border: none; }}
    QTabBar::tab {{
        background: transparent;
        color: {ts};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 8px 20px;
        margin-right: 4px;
        font-weight: 500;
    }}
    QTabBar::tab:selected {{ color: {ac}; border-bottom-color: {ac}; }}
    QTabBar::tab:hover {{ color: {tp}; }}

    QGroupBox {{
        background-color: {card};
        border: 1px solid {bd};
        border-radius: 10px;
        margin-top: 20px;
        padding: 18px 16px 16px 16px;
        font-weight: 600;
        font-size: 13px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 16px;
        padding: 0 10px;
        color: {ac};
    }}

    QLineEdit {{
        background-color: {inp};
        border: 1px solid {bd};
        border-radius: 6px;
        padding: 8px 12px;
        color: {tp};
        selection-background-color: {ac}66;
    }}
    QLineEdit:focus {{ border-color: {bdf}; }}

    QComboBox {{
        background-color: {inp};
        border: 1px solid {bd};
        border-radius: 6px;
        padding: 7px 12px;
        color: {tp};
        min-width: 100px;
    }}
    QComboBox:hover {{ border-color: {ac}; }}
    QComboBox::drop-down {{ border: none; width: 24px; }}
    QComboBox QAbstractItemView {{
        background-color: {bg2};
        border: 1px solid {bd};
        border-radius: 6px;
        padding: 4px;
        selection-background-color: {ac};
        selection-color: white;
    }}

    QCheckBox {{
        spacing: 8px;
        color: {tp};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border: 2px solid {bd};
        border-radius: 4px;
        background-color: {inp};
    }}
    QCheckBox::indicator:checked {{ background-color: {ac}; border-color: {ac}; }}

    QProgressBar {{
        background-color: {inp};
        border: 1px solid {bd};
        border-radius: 6px;
        height: 14px;
        text-align: center;
        font-size: 10px;
        color: {tp};
    }}
    QProgressBar::chunk {{ background-color: {ac}; border-radius: 4px; }}

    QSplitter::handle {{
        background-color: {bd};
        width: 1px;
    }}
    QSplitter::handle:hover {{ background-color: {ac}; }}

    QTextEdit, QPlainTextEdit {{
        background-color: {inp};
        border: 1px solid {bd};
        border-radius: 8px;
        padding: 10px;
        color: {tp};
        selection-background-color: {ac}66;
    }}

    QLabel {{
        color: {tp};
        background: transparent;
    }}

    QLabel#titleLabel {{
        font-size: 20px;
        font-weight: 700;
        color: {tb};
    }}
    QLabel#subtitleLabel {{
        font-size: 12px;
        color: {tm};
    }}
    QLabel#statLabel {{
        font-size: 13px;
        color: {ts};
    }}

    QStatusBar {{
        background-color: {bg2};
        border-top: 1px solid {bd};
        color: {ts};
        padding: 2px 10px;
        font-size: 12px;
    }}

    QDialog {{ background-color: {bg2}; }}

    QToolTip {{
        background-color: {bg2};
        border: 1px solid {bd};
        border-radius: 6px;
        padding: 6px 10px;
        color: {tp};
        font-size: 12px;
    }}

    QScrollArea {{ border: none; background-color: {bg}; }}
    QScrollArea > QWidget > QWidget {{ background-color: {bg}; }}

    QFrame[frameShape="4"] {{ color: {bd}; }}
    QFrame[frameShape="5"] {{ color: {bd}; }}
    """
