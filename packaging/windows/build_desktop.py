"""Build a native onedir executable without Streamlit or browser assets."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
from release_bundle import icon,finalize
ROOT=Path(__file__).resolve().parents[2]


def main():
    if sys.platform!='win32' or sys.maxsize<=2**32:raise RuntimeError('Build requires Windows x64.')
    if sys.version_info[:3]!=(3,13,7):raise RuntimeError('Validated build requires Python 3.13.7.')
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'.release'/'M7');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','PyInstaller','--clean','--noconfirm','--onedir','--windowed','--name','ORR Worker',
        '--paths',str(ROOT),'--distpath',str(out/'dist'),'--workpath',str(out/'build'),'--specpath',str(out/'spec'),
        '--collect-submodules','application','--collect-submodules','desktop',
        '--additional-hooks-dir',str(ROOT/'packaging/windows/hooks'),
        '--add-data',str(ROOT/'assets')+':assets','--icon',str(icon(out)),
        '--hidden-import','matplotlib.backends.backend_svg','--hidden-import','matplotlib.backends.backend_agg']
    for module in ('streamlit','IPython','notebook','pytest','_pytest','PyQt6','PyQt5','PySide2',
                   'torch','torchvision','torchaudio','tensorflow','jax','jaxlib','transformers','cv2',
                   'bokeh','plotly','openpyxl','xlsxwriter','sqlalchemy','boto3','botocore','tkinter'):
        command+=['--exclude-module',module]
    # Developer tools can put incompatible same-name DLLs (notably ICU) on
    # PATH. Let Qt use the Windows system ICU instead of a Poppler copy.
    env=dict(os.environ)
    env['MPLCONFIGDIR']=str(out/'build-matplotlib');env['QT_API']='pyside6';env['MPLBACKEND']='Agg'
    if os.name=='nt':
        windir=Path(os.environ['WINDIR'])
        env['PATH']=os.pathsep.join(map(str,(Path(sys.executable).parent,windir/'System32',windir)))
    subprocess.run(command+[str(ROOT/'packaging'/'windows'/'desktop_entry.py')],cwd=ROOT,env=env,check=True)
    finalize(out)
    print(out/'dist'/'ORR Worker'/'ORR Worker.exe')


if __name__=='__main__':main()
