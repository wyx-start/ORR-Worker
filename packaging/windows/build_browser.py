"""Build the browser edition with generated examples; no user files included."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/".release"/"M1")
    args=parser.parse_args();output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    examples=output/"synthetic_examples"
    if not examples.exists():
        subprocess.run([sys.executable,str(ROOT/"tools"/"generate_demo_data.py"),"--output",str(examples)],check=True)
    command=[sys.executable,"-m","PyInstaller","--noconfirm","--onedir","--windowed",
             "--name","ORR Worker Browser","--paths",str(ROOT),"--distpath",str(output/"dist"),
             "--workpath",str(output/"build"),"--specpath",str(output/"spec"),
             "--collect-data","streamlit","--copy-metadata","streamlit",
             "--collect-submodules","streamlit.components.v2",
             "--hidden-import","streamlit.runtime.scriptrunner.magic_funcs",
             "--hidden-import","matplotlib.backends.backend_svg",
             "--hidden-import","matplotlib.backends.backend_agg",
             "--add-data",str(ROOT/"app_pages")+":app_pages",
             "--add-data",str(ROOT/"application")+":application",
             "--collect-submodules","application",
             "--add-data",str(examples)+":examples"]
    for module in ("IPython","notebook","pytest","_pytest","streamlit.testing","PySide6","PyQt6","PyQt5","PySide2",
                   "torch","torchvision","torchaudio","tensorflow","jax","jaxlib","transformers","cv2",
                   "bokeh","plotly","openpyxl","xlsxwriter","sqlalchemy","boto3","botocore"):
        command += ["--exclude-module",module]
    for source in ROOT.glob("*.py"):
        command += ["--hidden-import",source.stem,"--add-data",str(source)+":."]
    command += [str(ROOT/"packaging"/"windows"/"browser_entry.py")]
    subprocess.run(command,cwd=ROOT,check=True)
    print(output/"dist"/"ORR Worker Browser"/"ORR Worker Browser.exe")


if __name__=="__main__":main()
