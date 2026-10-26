"""Collect Qt Widgets graphics without unused PDF or virtual-keyboard plugins."""
from pathlib import Path
from PyInstaller.utils.hooks.qt import add_qt6_dependencies

hiddenimports,binaries,datas=add_qt6_dependencies(__file__)
UNUSED={'qpdf.dll','qtvirtualkeyboardplugin.dll'}
binaries=[(source,target) for source,target in binaries if Path(source).name.lower() not in UNUSED]
