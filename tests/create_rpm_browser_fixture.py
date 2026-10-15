"""Synthetic names/metadata over a real CV payload, for local browser regression only."""
from io import BytesIO
import json
from pathlib import Path
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from orr_core import RPM_FIELDS, default_config, pack_project, parse_chi


if __name__=="__main__":
    raw=(ROOT/"examples"/"O-0.1MNa-5mv-900.txt").read_bytes()
    names=["CoPc_1600转.txt","CoPc_900转.txt","CoPc_900转_1600转.txt"]
    traces={}
    configs={}
    for name,rpm,group in zip(names,[None,1200,None],["保留分组","人工组","冲突组"]):
        trace=parse_chi(name,raw)
        traces[trace.id]=trace
        configs[trace.id]=default_config(trace)
        configs[trace.id].update(rpm=rpm,group=group)
    source=zipfile.ZipFile(BytesIO(pack_project(traces,configs,{"axis":"原始"})))
    output=BytesIO()
    with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
        for name in source.namelist():
            contents=source.read(name)
            if name=="project.json":
                manifest=json.loads(contents)
                manifest["app_version"]="1.1.0"
                for entry in manifest["files"]:
                    for field in RPM_FIELDS:
                        if field!="rpm": entry["config"].pop(field,None)
                contents=json.dumps(manifest,ensure_ascii=False).encode()
            archive.writestr(name,contents)
    folder=ROOT/"verification"
    folder.mkdir(exist_ok=True)
    path=folder/"rpm_legacy_fixture.orrproj"
    path.write_bytes(output.getvalue())
    print(path)
