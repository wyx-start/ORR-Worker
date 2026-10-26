"""Use Windows CJK fonts even when Qt's offscreen plugin has no font database."""
import os
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase


def ui_font():
    if not QFontDatabase.families():
        path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
        if path.exists():QFontDatabase.addApplicationFont(str(path))
    return QFont('Microsoft YaHei',10)
