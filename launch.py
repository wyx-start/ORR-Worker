"""Local Windows launcher: reuse this app's healthy process, otherwise choose a free port."""
from __future__ import annotations
import argparse
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
import webbrowser

ROOT = Path(__file__).resolve().parent
RUNTIME = ROOT / ".runtime"
STATE = RUNTIME / "server.json"
BASE = "orr-workbench"


def process_stamp(pid):
    if os.name != "nt":
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)]*4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, int(pid))
    if not handle:
        return None
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return None
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
            return None
        return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
    finally:
        kernel.CloseHandle(handle)


def healthy(url):
    try:
        # Local loopback traffic must not be routed through a system/HTTP proxy.
        with build_opener(ProxyHandler({})).open(url.rstrip("/")+"/_stcore/health", timeout=1) as response:
            return response.status==200 and response.read().strip()==b"ok"
    except (URLError, OSError):
        return False


def error_dialog(message):
    if os.name=="nt":
        ctypes.windll.user32.MessageBoxW(0, message, "ORR Worker", 0x10)
    else:
        print(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            pass
    same_process = bool(state.get("stamp") and process_stamp(state.get("pid",0))==state["stamp"])
    if args.stop:
        if same_process and state.get("root")==str(ROOT):
            subprocess.run(["taskkill", "/PID", str(state["pid"]), "/F"], creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True)
            STATE.unlink(missing_ok=True)
        return
    if same_process and state.get("root")==str(ROOT) and healthy(state.get("url", "")):
        if not args.no_browser:
            webbrowser.open(state["url"])
        print(state["url"])
        return
    port = None
    for candidate in range(8765, 8795):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", candidate))
                port = candidate
                break
            except OSError:
                continue
    if port is None:
        raise RuntimeError("本机端口 8765–8794 均不可用。")
    python = Path(sys.executable).with_name("python.exe") if os.name=="nt" else Path(sys.executable)
    url = f"http://127.0.0.1:{port}/{BASE}/"
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    with (RUNTIME/"server.log").open("ab") as log:
        process = subprocess.Popen([str(python),"-m","streamlit","run",str(ROOT/"streamlit_app.py"),
                                    "--server.address=127.0.0.1",f"--server.port={port}",
                                    f"--server.baseUrlPath={BASE}","--server.headless=true",
                                    "--browser.gatherUsageStats=false"], cwd=ROOT, stdout=log, stderr=log,
                                    env=env, creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    info = dict(pid=process.pid,stamp=process_stamp(process.pid),url=url,root=str(ROOT))
    STATE.write_text(json.dumps(info),encoding="utf-8")
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError("启动失败，请查看 .runtime/server.log。")
        if healthy(url):
            if not args.no_browser:
                webbrowser.open(url)
            print(url)
            return
        time.sleep(.25)
    raise RuntimeError("启动等待超时，请查看 .runtime/server.log。")


if __name__=="__main__":
    try:
        main()
    except Exception as exc:
        if "--no-browser" not in sys.argv:
            error_dialog(str(exc))
        raise
