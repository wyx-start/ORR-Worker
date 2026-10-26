"""Native desktop entry; never starts a web server or browser."""
import argparse
import os
from pathlib import Path
import sys


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke-dir',type=Path)
    args=parser.parse_args()
    if args.smoke_dir:os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from desktop.fonts import ui_font
    from desktop.window import MainWindow
    app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('ORR Worker');app.setOrganizationName('ORR Worker');app.setStyle('Fusion')
    app.setFont(ui_font())
    window=MainWindow()
    if args.smoke_dir:
        from desktop.smoke import verify
        verify(window,args.smoke_dir);window.force_close=True;window.close();return 0
    window.show()
    return app.exec()


if __name__=='__main__':raise SystemExit(main())
