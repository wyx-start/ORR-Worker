"""Check real source processes reuse the per-installation lock and release it."""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def main():
    from desktop.main import instance_path
    output=Path(tempfile.mkdtemp(prefix='native_instance_',dir=ROOT/'verification'))
    path=instance_path()
    if path.exists():raise RuntimeError('An existing instance lock is present; this verifier will not disturb it.')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen');command=[sys.executable,'-m','desktop.main']
    report={'passed':False,'user_processes_touched':False}
    with (output/'process.log').open('w',encoding='utf-8') as log:
        first=subprocess.Popen(command+['--quit-after-ms','5000'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        try:
            for _ in range(80):
                if first.poll() is not None:raise RuntimeError('First native process failed')
                if path.exists():break
                time.sleep(.05)
            else:raise RuntimeError('Instance lock was not created')
            second=subprocess.run(command+['--quit-after-ms','100'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=15)
            report['duplicate_exit_code']=second.returncode
            report['first_exit_code']=first.wait(timeout=15)
            third=subprocess.run(command+['--quit-after-ms','100'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=15)
            report['relaunch_exit_code']=third.returncode;report['lock_released']=not path.exists()
            report['passed']=second.returncode==2 and report['first_exit_code']==0 and third.returncode==0 and report['lock_released']
        finally:
            if first.poll() is None:
                subprocess.run(['taskkill','/PID',str(first.pid),'/T','/F'],capture_output=True);first.wait(timeout=10)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(output/'report.json')
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
