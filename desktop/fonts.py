"""Use Windows CJK fonts even when Qt's offscreen plugin has no font database."""
import os
from pathlib import Path
from PySide6.QtGui import QFont, QFontDatabase


def ui_font():
    if not QFontDatabase.families():
        directory=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
        for name in ('msyh.ttc','segoeui.ttf','seguisym.ttf','arial.ttf'):
            path=directory/name
            if path.exists():QFontDatabase.addApplicationFont(str(path))
    font=QFont('Microsoft YaHei',10)
    font.setFamilies(['Microsoft YaHei','Segoe UI','Segoe UI Symbol','Arial'])
    return font
