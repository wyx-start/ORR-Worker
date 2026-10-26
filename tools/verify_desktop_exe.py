"""Exercise the frozen native executable with OS-only PATH and generated inputs."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--executable',type=Path,required=True);args=p.parse_args()
    base=ROOT/'verification';base.mkdir(exist_ok=True)
    output=Path(tempfile.mkdtemp(prefix='native_exe_',dir=base))/'中文 测试';output.mkdir()
    env=dict(os.environ,PATH=str(Path(os.environ['WINDIR'])/'System32')+os.pathsep+os.environ['WINDIR'],
             PYTHONNOUSERSITE='1',QT_QPA_PLATFORM='offscreen')
    for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):env.pop(key,None)
    exe=args.executable.resolve()
    result=subprocess.run([str(exe),'--smoke-dir',str(output)],cwd=output,env=env,timeout=120,capture_output=True)
    report=json.loads((output/'report.json').read_text()) if (output/'report.json').exists() else {'passed':False}
    report.update(executable=str(exe),exit_code=result.returncode,external_python_on_path=False,
                  clean_machine=False,passed=bool(report.get('passed')) and result.returncode==0)
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'report':str(output/'report.json'),'passed':report['passed']}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
