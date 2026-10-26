from pathlib import Path
import os
import sys

if not getattr(sys,'frozen',False):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
directory=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ORR Worker'/'desktop'
directory.mkdir(parents=True,exist_ok=True)
os.environ['MPLCONFIGDIR']=str(directory/'matplotlib')
os.environ['QT_API']='pyside6'
os.environ['MPLBACKEND']='Agg'
if getattr(sys,'frozen',False):
    plugins=Path(sys._MEIPASS)/'PySide6'/'plugins'
    os.environ['QT_PLUGIN_PATH']=str(plugins)
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH']=str(plugins/'platforms')
from desktop.main import main

if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        import traceback
        (directory/'last_error.log').write_text(traceback.format_exc(),encoding='utf-8')
        if '--smoke-dir' in sys.argv:raise SystemExit(1)
        raise
