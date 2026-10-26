"""Browser edition: one exe with explicit launcher and server modes."""
from pathlib import Path
import argparse
import json
import os
import sys
import webbrowser

if not getattr(sys,"frozen",False):
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from browser_runtime import BrowserService,serve


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve",action="store_true")
    parser.add_argument("--stop",action="store_true")
    parser.add_argument("--headless",action="store_true")
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--port",type=int)
    parser.add_argument("--state-dir",type=Path)
    args = parser.parse_args()
    if args.serve:
        serve(args.state_dir,args.port);return
    service = BrowserService(args.state_dir)
    if args.stop:
        service.stop();return
    if args.headless:
        state=service.start(args.port)
        if sys.stdout is not None:print(json.dumps(state))
        return
    import tkinter as tk
    from tkinter import messagebox
    window=tk.Tk();window.title("ORR Worker Browser");window.geometry("470x210")
    state={}
    label=tk.Label(window,text="正在启动本机分析服务…",wraplength=440,pady=15);label.pack()
    tk.Label(window,text="浏览器版 · 请在停止服务前下载分析项目。",wraplength=440).pack()
    def opened():
        if state and not args.no_browser:webbrowser.open(state["url"])
    def stopped():
        service.stop();window.destroy()
    def close():
        if messagebox.askyesno("退出 ORR Worker Browser","确认已保存项目，并停止本软件服务？",parent=window):stopped()
    tk.Button(window,text="打开分析界面",command=opened).pack(pady=5)
    tk.Button(window,text="停止服务并退出",command=close).pack()
    def start():
        try:
            state.update(service.start(args.port));label.config(text="服务已就绪："+state["url"]);opened()
        except Exception as exc:
            label.config(text=str(exc));messagebox.showerror("启动失败",str(exc),parent=window)
    window.protocol("WM_DELETE_WINDOW",close)
    window.after(100,start);window.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        if sys.stderr is not None:print(str(exc),file=sys.stderr)
        from browser_runtime import user_root
        directory=user_root();directory.mkdir(parents=True,exist_ok=True)
        (directory/"last_startup_error.txt").write_text(str(exc),encoding="utf-8")
        sys.exit(1)
