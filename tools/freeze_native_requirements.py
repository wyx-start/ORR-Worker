"""Record the validated native/build dependency closure, excluding unrelated extras."""
from importlib.metadata import distribution
from pathlib import Path
import argparse
from packaging.requirements import Requirement


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    todo=['numpy','pandas','scipy','matplotlib','PySide6','PyInstaller','pyinstaller-hooks-contrib'];seen=set();versions={}
    while todo:
        name=todo.pop();key=name.lower().replace('_','-')
        if key in seen:continue
        seen.add(key);package=distribution(name);versions[package.metadata['Name']]=package.version
        for raw in package.requires or []:
            requirement=Requirement(raw)
            if requirement.marker is None or requirement.marker.evaluate({'extra':''}):todo.append(requirement.name)
    text='# Native Windows build closure; Python 3.13.7; validated package versions.\n'
    text+='\n'.join(name+'=='+version for name,version in sorted(versions.items(),key=lambda pair:pair[0].lower()))+'\n'
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text,encoding='utf-8')
    print(str(args.output),len(versions),'packages')


if __name__=='__main__':main()
