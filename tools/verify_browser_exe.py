"""Exercise the actual frozen browser edition with external Python removed from PATH."""
from pathlib import Path
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable",type=Path,required=True)
    parser.add_argument("--port",type=int,default=18766)
    args=parser.parse_args();exe=args.executable.resolve()
    isolation=Path(tempfile.mkdtemp(prefix="frozen_browser_",dir=ROOT/"verification"))
    output=isolation/"verification";output.mkdir()
    for folder in ("tests",):
        for source in (ROOT/folder).glob("*"):
            if source.is_file() and source.suffix in (".py",".cjs"):
                destination=isolation/source.relative_to(ROOT);destination.parent.mkdir(exist_ok=True)
                shutil.copy2(source,destination)
    for source in ROOT.glob("*.py"):
        shutil.copy2(source,isolation/source.name)
    for name in ("create_background_conditions_fixture.py","create_batch_controls_fixture.py"):
        subprocess.run([sys.executable,str(isolation/"tests"/name)],cwd=isolation,check=True,capture_output=True)
    state=output/"runtime"
    env=dict(os.environ,PATH=str(Path(os.environ["WINDIR"])/"System32")+os.pathsep+os.environ["WINDIR"],
             PYTHONNOUSERSITE="1",ORR_TEST_URL=f"http://127.0.0.1:{args.port}/orr-workbench/")
    env.pop("PYTHONHOME",None);env.pop("PYTHONPATH",None)
    report={"exe":str(exe),"external_python_on_path":False,"real_data_read":False,
            "clean_machine":False,"checks":[]}
    def run(*options):
        return subprocess.run([str(exe),*options,"--state-dir",str(state)],cwd=output,env=env,timeout=100,capture_output=True)
    try:
        with socket.socket() as probe:probe.bind(("127.0.0.1",args.port))
        result=run("--headless","--no-browser","--port",str(args.port))
        if result.returncode:
            raise RuntimeError("Frozen startup failed; inspect LOCALAPPDATA/ORR Worker/browser/last_startup_error.txt and runtime/server.log")
        first=json.loads((state/"instance.json").read_text())
        result=run("--headless","--no-browser","--port",str(args.port))
        second=json.loads((state/"instance.json").read_text())
        if result.returncode or first["pid"]!=second["pid"]:raise RuntimeError("Duplicate launch did not reuse owned service")
        report["duplicate_launch_reuses_pid"]=True
        report["server_executable"]=first["executable"]
        node=shutil.which("node")
        for script in ("browser_conditions.cjs","browser_background_conditions.cjs","browser_background_ph.cjs","browser_batch_controls.cjs"):
            with (output/(script+".log")).open("w",encoding="utf-8") as log:
                completed=subprocess.run([node,str(isolation/"tests"/script)],cwd=isolation,
                    env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240)
            check={"script":script,"passed":completed.returncode==0};report["checks"].append(check)
            print(json.dumps(check),flush=True)
            if not check["passed"]:
                break
        run("--stop")
        with socket.socket() as occupied:
            occupied.bind(("127.0.0.1",args.port));occupied.listen()
            blocked=run("--headless","--no-browser","--port",str(args.port))
            report["occupied_port_rejected"]=blocked.returncode!=0
    finally:
        stopped=run("--stop")
        report["owned_service_stopped"]=stopped.returncode==0 and not (state/"instance.json").exists()
        report["passed"]=bool(report["checks"]) and all(c["passed"] for c in report["checks"]) and report.get("occupied_port_rejected",False) and report["owned_service_stopped"]
        (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        print(output/"report.json",flush=True)
    return 0 if report["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
