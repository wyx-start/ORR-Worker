"""Verify the actual frozen native bundle, with generated data and OS-only PATH."""
from pathlib import Path
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]


def peak_working_set(pid):
    if os.name!='nt':return None
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    memory=ctypes.WinDLL('psapi',use_last_error=True);memory.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    handle=kernel.OpenProcess(0x0400|0x0010,False,pid)
    if not handle:return None
    try:
        counters=Counters();counters.cb=ctypes.sizeof(counters)
        return int(counters.PeakWorkingSetSize) if memory.GetProcessMemoryInfo(handle,ctypes.byref(counters),counters.cb) else None
    finally:kernel.CloseHandle(handle)


def tree_hashes(folder):
    return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*') if p.is_file()}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--executable',type=Path,required=True)
    parser.add_argument('--minimum',action='store_true',help='Use the historical minimum smoke workflow')
    args=parser.parse_args();source=args.executable.resolve()
    base=ROOT/'verification';base.mkdir(exist_ok=True);output=Path(tempfile.mkdtemp(prefix='native_exe_',dir=base))
    program=output/'中文 程序'/'ORR Worker';shutil.copytree(source.parent,program)
    assert program.resolve().is_relative_to(base.resolve())
    before=tree_hashes(program);exe=program/source.name
    for path in program.rglob('*'):
        if path.is_file():path.chmod(stat.S_IREAD)
    env=dict(os.environ,PATH=str(Path(os.environ['WINDIR'])/'System32')+os.pathsep+os.environ['WINDIR'],PYTHONNOUSERSITE='1')
    for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):env.pop(key,None)
    report={'source_executable':str(source),'tested_executable':str(exe),'external_python_on_path':False,'clean_machine':False,
            'program_files_readonly':True,'actual_directory_acl_readonly':False,'cases':[],'instance':{}}
    cases=[('scale1','1','offscreen')] if args.minimum else [('scale1','1','offscreen'),('scale150','1.5','offscreen'),('windows','1','windows')]
    try:
        for name,scale,backend in cases:
            destination=output/name;destination.mkdir();case_env=dict(env,QT_QPA_PLATFORM=backend,QT_SCALE_FACTOR=scale)
            command=[str(exe),'--smoke-dir',str(destination)]+([] if args.minimum else ['--smoke-full'])
            started=time.perf_counter();peak=0
            with (destination/'process.log').open('wb') as log:
                process=subprocess.Popen(command,cwd=destination,env=case_env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                try:
                    while process.poll() is None:
                        value=peak_working_set(process.pid)
                        if value:peak=max(peak,value)
                        if time.perf_counter()-started>120:process.kill();raise TimeoutError('Frozen workflow exceeded 120 seconds')
                        time.sleep(.025)
                    code=process.wait(timeout=10)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=10)
            path=destination/'report.json';data=json.loads(path.read_text()) if path.exists() else {'passed':False}
            data.update(exit_code=code,total_seconds=time.perf_counter()-started,peak_working_set_bytes=peak or None)
            data['passed']=bool(data.get('passed')) and code==0 and (args.minimum or bool(data.get('full_workflow')))
            path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
            report['cases'].append({'name':name,'report':str(path),**data});print(json.dumps({'case':name,'passed':data['passed']}),flush=True)
            if not data['passed']:break
        if all(case['passed'] for case in report['cases']) and not args.minimum:
            case_env=dict(env,QT_QPA_PLATFORM='offscreen',QT_SCALE_FACTOR='1')
            with (output/'instance.log').open('wb') as log:
                first=subprocess.Popen([str(exe),'--quit-after-ms','5000'],cwd=output,env=case_env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    time.sleep(1.5)
                    second=subprocess.run([str(exe),'--quit-after-ms','100'],cwd=output,env=case_env,stdout=log,stderr=subprocess.STDOUT,timeout=15)
                    code=first.wait(timeout=15)
                    third=subprocess.run([str(exe),'--quit-after-ms','100'],cwd=output,env=case_env,stdout=log,stderr=subprocess.STDOUT,timeout=15)
                    report['instance']=dict(duplicate_exit_code=second.returncode,first_exit_code=code,relaunch_exit_code=third.returncode,
                        passed=second.returncode==2 and code==0 and third.returncode==0)
                finally:
                    if first.poll() is None:first.kill();first.wait(timeout=10)
        after=tree_hashes(program);report['program_unchanged']=before==after
        forbidden=[name for name in before if any(part in name.lower() for part in ('streamlit/','qt6webengine','qt6virtualkeyboard','qt6pdf.dll','qpdf.dll','qtvirtualkeyboardplugin','user_settings/','examples/','verification/'))]
        report['unexpected_resources']=forbidden
        if (program/'CHECKSUMS.sha256').exists():
            checks={}
            for line in (program/'CHECKSUMS.sha256').read_text(encoding='utf-8').splitlines():
                digest,name=line.split('  ',1);checks[name]=digest
            report['checksums_valid']=all(before.get(name)==digest for name,digest in checks.items()) and len(before)==len(checks)+1
        report['passed']=len(report['cases'])==len(cases) and all(c['passed'] for c in report['cases']) and report['program_unchanged'] and not forbidden and (args.minimum or (report['instance'].get('passed',False) and report.get('checksums_valid',False)))
    finally:
        # Restore only generated-copy attributes; no user's program directory is changed.
        for path in program.rglob('*'):
            if path.is_file():path.chmod(stat.S_IREAD|stat.S_IWRITE)
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(output/'report.json',flush=True)
    return 0 if report.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
