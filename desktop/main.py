"""Native desktop entry; never starts a web server or browser."""
import argparse
import os
from pathlib import Path
import sys
import hashlib


def instance_path():
    key=hashlib.sha256((str(Path(sys.executable).resolve())+str(Path(__file__).resolve().parent)).encode()).hexdigest()[:20]
    folder=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ORR Worker'/'desktop'/'instances'
    folder.mkdir(parents=True,exist_ok=True);return folder/(key+'.lock')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--smoke-dir',type=Path)
    parser.add_argument('--quit-after-ms',type=int,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.smoke_dir:os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
    from PySide6.QtWidgets import QApplication
    from desktop.fonts import ui_font
    from desktop.window import MainWindow
    app=QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName('ORR Worker');app.setOrganizationName('ORR Worker');app.setStyle('Fusion')
    app.setFont(ui_font())
    lock=None
    if not args.smoke_dir:
        from PySide6.QtCore import QLockFile
        lock=QLockFile(str(instance_path()));lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            if args.quit_after_ms is None:
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.information(None,'ORR Worker 已在运行','请切换到已经打开的 ORR Worker 窗口。')
            return 2
    window=MainWindow()
    if args.smoke_dir:
        from desktop.smoke import verify
        verify(window,args.smoke_dir);window.force_close=True;window.close();return 0
    window.show()
    if args.quit_after_ms is not None:
        from PySide6.QtCore import QTimer
        window.force_close=True;QTimer.singleShot(args.quit_after_ms,window.close)
    try:return app.exec()
    finally:
        if lock:lock.unlock()


if __name__=='__main__':raise SystemExit(main())
