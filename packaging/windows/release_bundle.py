"""Prepare a documented native directory package, license copies and hashes."""
from pathlib import Path
from importlib.metadata import distribution
import datetime
import hashlib
import json
import platform
import shutil
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[2]


def icon(output):
    from PIL import Image,ImageDraw
    image=Image.new('RGBA',(256,256),(0,0,0,0));draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((0,0,255,255),48,fill='#167d8d');draw.ellipse((42,42,214,214),outline='white',width=14);draw.ellipse((75,75,181,181),fill='white')
    draw.line((128,20,128,49),fill='#a3e4d6',width=10);draw.line((128,207,128,236),fill='#a3e4d6',width=10)
    path=output/'ORR Worker.ico';image.save(path,sizes=[(v,v) for v in (16,24,32,48,64,128,256)]);return path


def finalize(output):
    sys.path.insert(0,str(ROOT));from orr_core import VERSION
    bundle=output/'dist'/'ORR Worker';license_root=bundle/'licenses';license_root.mkdir(exist_ok=True)
    packages={}
    for line in (ROOT/'requirements/native-build-lock.txt').read_text().splitlines():
        if not line or line.startswith('#'):continue
        name,version=line.split('==');package=distribution(name)
        if package.version!=version:raise RuntimeError('Unpinned package: '+name)
        packages[name]=version
        for member in package.files or []:
            parts=Path(str(member)).parts
            if not any('license' in part.lower() or 'copying' in part.lower() for part in parts):continue
            source=Path(package.locate_file(member))
            if not source.is_file():continue
            destination=license_root/name/Path(*parts)
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
    for source in (ROOT/'packaging/windows/licenses').glob('*.txt'):shutil.copy2(source,license_root/source.name)
    for name in ('NATIVE_USER_GUIDE.md','BUILD_WINDOWS.md'):
        shutil.copy2(ROOT/'docs'/name,bundle/name)
    (bundle/'README.txt').write_text('ORR Worker 原生桌面候选版\n\n解压后双击 ORR Worker.exe；保留整个文件夹及 _internal。\n无需执行命令或安装 Python。数据在本机处理，不启动浏览器服务。\n关闭前保存分析项目。详细步骤见 NATIVE_USER_GUIDE.md。\n\n已在本机 Windows 11 x64 验证；全新无 Python 系统尚未验收。\n',encoding='utf-8')
    notices='''# Third-party components

This directory uses dynamically loaded Python, Qt for Python / Qt, NumPy, SciPy,
pandas, Matplotlib and their dependencies. Unmodified distributed license files
are copied under licenses/. Build-time packages are listed separately in VERSION.json.

Python 3.13.7 source and license: https://github.com/python/cpython/tree/v3.13.7
Qt for Python source: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.12.0
Qt 6.12 source: https://download.qt.io/official_releases/qt/6.12/6.12.0/submodules/
Qt licensing: https://doc.qt.io/qt-6/licensing.html
ORR Worker source/build instructions: https://github.com/wyx-start/ORR-Worker

The package is directory-based. Qt libraries remain separate replaceable DLLs.
Unused PDF and virtual-keyboard plugins are excluded. No third-party library
source is modified by this application; the PyInstaller collection hook only
selects the plugins required by this Widgets application.
'''
    (bundle/'THIRD_PARTY_NOTICES.md').write_text(notices,encoding='utf-8')
    sources=[ROOT/name for name in ('orr_core.py','background_conditions.py','background_ph.py','background_pairing.py','settings_draft.py','batch_settings.py','experiment_conditions.py','origin_export.py','plot_smoothing.py','ring_comparison.py')]
    sources+=list((ROOT/'application').glob('*.py'))+list((ROOT/'desktop').glob('*.py'))+[ROOT/'assets/icon.svg']
    manifest={str(path.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(path.read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest() for path in sources}
    (bundle/'SOURCE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    metadata=dict(application='ORR Worker',version=VERSION,edition='native-local-candidate',python=platform.python_version(),
        platform=platform.platform(),architecture=platform.machine(),built_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),build_packages=packages,
        source_digest=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest(),source_digest_format='utf8-lf-sha256',clean_machine_tested=False)
    (bundle/'VERSION.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    members=sorted(path for path in bundle.rglob('*') if path.is_file() and path!=bundle/'CHECKSUMS.sha256')
    checksums='\n'.join(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.relative_to(bundle).as_posix() for path in members)+'\n'
    (bundle/'CHECKSUMS.sha256').write_text(checksums,encoding='utf-8')
    archive=output/f'ORR-Worker-{VERSION}-Windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
        for path in sorted(bundle.rglob('*')):
            if path.is_file():target.write(path,path.relative_to(bundle.parent).as_posix())
    digest=hashlib.sha256(archive.read_bytes()).hexdigest();archive.with_suffix('.zip.sha256').write_text(digest+'  '+archive.name+'\n',encoding='utf-8')
    report=dict(bundle=str(bundle),zip=str(archive),zip_bytes=archive.stat().st_size,zip_sha256=digest,
        bundle_files=len(members)+1,bundle_bytes=sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file()),metadata=metadata)
    (output/'bundle-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');return report
