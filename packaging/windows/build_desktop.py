"""Build a native onedir executable without Streamlit or browser assets."""
from pathlib import Path
import argparse
import os
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,default=ROOT/'.release'/'M3');args=p.parse_args()
    out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-m','PyInstaller','--clean','--noconfirm','--onedir','--windowed','--name','ORR Worker',
        '--paths',str(ROOT),'--distpath',str(out/'dist'),'--workpath',str(out/'build'),'--specpath',str(out/'spec'),
        '--collect-submodules','application','--collect-submodules','desktop',
        '--hidden-import','matplotlib.backends.backend_svg','--hidden-import','matplotlib.backends.backend_agg']
    for module in ('streamlit','IPython','notebook','pytest','_pytest','PyQt6','PyQt5','PySide2',
                   'torch','torchvision','torchaudio','tensorflow','jax','jaxlib','transformers','cv2',
                   'bokeh','plotly','openpyxl','xlsxwriter','sqlalchemy','boto3','botocore','tkinter'):
        command+=['--exclude-module',module]
    # Developer tools can put incompatible same-name DLLs (notably ICU) on
    # PATH. Let Qt use the Windows system ICU instead of a Poppler copy.
    env=dict(os.environ)
    if os.name=='nt':
        windir=Path(os.environ['WINDIR'])
        env['PATH']=os.pathsep.join(map(str,(Path(sys.executable).parent,windir/'System32',windir)))
    subprocess.run(command+[str(ROOT/'packaging'/'windows'/'desktop_entry.py')],cwd=ROOT,env=env,check=True)
    print(out/'dist'/'ORR Worker'/'ORR Worker.exe')


if __name__=='__main__':main()
