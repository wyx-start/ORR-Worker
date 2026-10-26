"""Standalone browser-edition process management, including frozen executables."""
from contextlib import contextmanager
from pathlib import Path
import ctypes
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from urllib.request import ProxyHandler,build_opener

from launch import process_stamp


def resource_root():
    return Path(sys._MEIPASS) if getattr(sys,"frozen",False) else Path(__file__).resolve().parent


def user_root():
    return Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".local"/"share")))/"ORR Worker"/"browser"


def identity(root):
    data = b"".join((root/name).read_bytes() for name in ("streamlit_app.py","orr_core.py"))
    return hashlib.sha256(str(root.resolve()).encode()+data).hexdigest()[:20]


@contextmanager
def instance_lock(key):
    if os.name != "nt":
        yield; return
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE,wintypes.DWORD]
    kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateMutexW(None,False,"Local\\ORRWorkerBrowser_"+key)
    if not handle:
        raise RuntimeError("无法创建启动锁。")
    try:
        result = kernel.WaitForSingleObject(handle,60000)
        if result not in (0,128):
            raise RuntimeError("另一个启动操作尚未完成，请稍后重试。")
        try:
            yield
        finally:
            kernel.ReleaseMutex(handle)
    finally:
        kernel.CloseHandle(handle)


class BrowserService:
    def __init__(self,state_dir=None):
        self.root = resource_root()
        self.key = identity(self.root)
        self.directory = Path(state_dir) if state_dir else user_root()/self.key
        self.directory.mkdir(parents=True,exist_ok=True)
        self.path = self.directory/"instance.json"

    def read(self):
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value,dict) else {}
        except (ValueError,OSError):
            return {}

    def owned(self,state):
        return (state.get("key") == self.key and state.get("stamp") is not None
                and process_stamp(state.get("pid",0)) == state["stamp"])

    @staticmethod
    def healthy(url):
        try:
            with build_opener(ProxyHandler({})).open(url+"_stcore/health",timeout=.5) as reply:
                return reply.status == 200 and reply.read().strip() == b"ok"
        except (OSError,ValueError):
            return False

    def start(self,port=None):
        with instance_lock(hashlib.sha256(str(self.directory.resolve()).encode()).hexdigest()[:24]):
            state = self.read()
            if state and state.get("key") != self.key:
                raise RuntimeError("所选运行目录属于其他软件实例，请使用独立运行目录。")
            if self.owned(state):
                if self.healthy(state["url"]):
                    return state
                raise RuntimeError("本软件服务仍在运行但未就绪；请查看启动日志或明确停止后重试。")
            ports = [port] if port else range(17665,17700)
            chosen = None
            for candidate in ports:
                with socket.socket() as probe:
                    try:
                        probe.bind(("127.0.0.1",int(candidate)));chosen=int(candidate);break
                    except OSError:
                        pass
            if chosen is None:
                raise RuntimeError("本机端口被占用，请选择其他端口。")
            command = [sys.executable]
            if not getattr(sys,"frozen",False):
                command.append(str(self.root/"packaging"/"windows"/"browser_entry.py"))
            command += ["--serve","--port",str(chosen),"--state-dir",str(self.directory)]
            env = dict(os.environ,PYTHONUTF8="1",MPLCONFIGDIR=str(self.directory/"matplotlib"))
            with (self.directory/"server.log").open("ab") as log:
                process = subprocess.Popen(command,cwd=self.directory,env=env,stdout=log,stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            stamp = process_stamp(process.pid)
            state = {"key":self.key,"pid":process.pid,"stamp":stamp,
                     "url":f"http://127.0.0.1:{chosen}/orr-workbench/","executable":sys.executable}
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state),encoding="utf-8");os.replace(temporary,self.path)
            for _ in range(240):
                if process.poll() is not None:
                    self.path.unlink(missing_ok=True)
                    raise RuntimeError("启动失败，详情见："+str(self.directory/"server.log"))
                if self.healthy(state["url"]):
                    return state
                time.sleep(.25)
            self.stop()
            raise RuntimeError("启动等待超时，请查看启动日志。")

    def stop(self):
        state = self.read()
        if self.owned(state):
            subprocess.run(["taskkill","/PID",str(state["pid"]),"/F"],capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            for _ in range(40):
                if not self.owned(state):break
                time.sleep(.1)
        if state.get("key") == self.key and not self.owned(state):
            self.path.unlink(missing_ok=True)


def serve(directory,port):
    root = resource_root()
    directory = Path(directory);directory.mkdir(parents=True,exist_ok=True)
    if sys.stdout is None:sys.stdout=(directory/"server.log").open("a",encoding="utf-8")
    if sys.stderr is None:sys.stderr=sys.stdout
    os.environ["MPLCONFIGDIR"] = str(directory/"matplotlib")
    os.chdir(directory)
    sys.path.insert(0,str(root))
    from streamlit.web import bootstrap
    flags = {"global.developmentMode":False,"server.address":"127.0.0.1","server.port":int(port),"server.baseUrlPath":"orr-workbench",
             "server.headless":True,"server.fileWatcherType":"none","browser.gatherUsageStats":False,
             "logger.hideWelcomeMessage":True,"theme.primaryColor":"#167D8D","theme.base":"light"}
    bootstrap.load_config_options(flags)
    bootstrap.run(str(root/"streamlit_app.py"),False,[],flags)
