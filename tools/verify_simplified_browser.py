"""Run browser checks on an existing isolated regression copy and owned service."""
from pathlib import Path
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("isolation", type=Path)
    parser.add_argument("--script", action="append", default=[])
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    root = args.isolation.resolve()
    if root.parent != (source/"verification").resolve() or not (root/"run_isolated_checks.py").is_file():
        raise SystemExit("Only an isolated regression copy inside verification is allowed")
    # Refresh test scripts only; the application under test remains the copied snapshot.
    for path in (source/"tests").glob("*.cjs"):
        shutil.copy2(path, root/"tests"/path.name)
    for filename in ("create_background_conditions_fixture.py", "create_batch_controls_fixture.py"):
        shutil.copy2(source/"tests"/filename, root/"tests"/filename)
        subprocess.run([sys.executable, "-X", "utf8", str(root/"tests"/filename)], cwd=root, check=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1",8766))  # Never reuse or stop an unrelated service.
    output = root/"verification"
    output.mkdir(exist_ok=True)
    report = {"isolation":str(root), "real_samples_read":False, "user_service_touched":False, "checks":[]}
    env = dict(os.environ, ORR_TEST_URL="http://127.0.0.1:8766/orr-workbench/")
    command = [sys.executable, "-m", "streamlit", "run", str(root/"streamlit_app.py"),
               "--server.port=8766", "--server.baseUrlPath=orr-workbench", "--server.headless=true",
               "--server.address=127.0.0.1", "--server.fileWatcherType=none"]
    with (output/"server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            opener = build_opener(ProxyHandler({}))
            for attempt in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Isolated service exited; see server.log")
                try:
                    if opener.open(env["ORR_TEST_URL"]+"_stcore/health", timeout=1).status == 200:
                        break
                except OSError:
                    time.sleep(.2)
            else:
                raise RuntimeError("Isolated service failed to become ready")
            node = shutil.which("node")
            if node is None:
                raise RuntimeError("Node is required for browser verification")
            for name in args.script or ["browser_conditions.cjs", "browser_background_conditions.cjs", "browser_background_ph.cjs", "browser_batch_controls.cjs"]:
                if Path(name).name != name or not name.endswith(".cjs"):
                    raise ValueError("Expected a test script filename")
                with (output/(name+".log")).open("w", encoding="utf-8") as testlog:
                    try:
                        result = subprocess.run([node,str(root/"tests"/name)],cwd=root, env=env,
                            stdout=testlog,stderr=subprocess.STDOUT,timeout=240)
                        check = {"script":name,"passed":result.returncode == 0}
                    except subprocess.TimeoutExpired:
                        check = {"script":name,"passed":False,"error":"Browser workflow exceeded 240 seconds"}
                report["checks"].append(check)
                print(json.dumps(report["checks"][-1]), flush=True)
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
            report["owned_service_stopped"] = server.poll() is not None
            report["passed"] = bool(report["checks"]) and all(c["passed"] for c in report["checks"])
            (output/"simplified_browser_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output/"simplified_browser_report.json")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
