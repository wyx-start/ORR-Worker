"""Prepare explicit UTF-8 stage changes for atomic GitHub tree/commit upload."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage",required=True)
    parser.add_argument("--path",action="append",default=[])
    args = parser.parse_args()
    if not args.stage.replace("-","").isalnum():
        raise SystemExit("Invalid stage identifier")
    folder = ROOT/".release"/"stages"/args.stage
    folder.mkdir(parents=True,exist_ok=True)
    pieces,expected = [],{}
    for name in dict.fromkeys(args.path):
        path = (ROOT/name).resolve()
        relative = path.relative_to(ROOT).as_posix()
        if any(part in (".release",".runtime","verification","user_settings","examples",".venv","__pycache__") for part in path.relative_to(ROOT).parts):
            raise SystemExit(f"Private/generated path excluded: {relative}")
        if path.suffix not in (".py",".cjs",".md",".json",".txt",".toml",".spec",".cmd",".yml",".yaml",".svg") and path.name != ".gitignore":
            raise SystemExit(f"Unsupported publication path: {relative}")
        content = path.read_text(encoding="utf-8").replace("\r\n","\n")
        raw = content.encode()
        expected[relative] = hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()
        parts = [content[i:i+7000] for i in range(0,len(content),7000)] or [""]
        pieces += [{"path":relative,"part":i,"parts":len(parts),"content":part} for i,part in enumerate(parts)]
    chunks = [pieces[i:i+3] for i in range(0,len(pieces),3)]
    for index,chunk in enumerate(chunks):
        (folder/f"payload_{index:03}.json").write_text(json.dumps(chunk,ensure_ascii=False),encoding="utf-8")
    manifest = {"stage":args.stage,"files":expected,"chunks":len(chunks)}
    (folder/"expected.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"stage":args.stage,"files":len(expected),"chunks":len(chunks)}))


if __name__ == "__main__":
    main()
