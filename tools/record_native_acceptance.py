"""Export a path-free public summary from successful local acceptance reports."""
from pathlib import Path
import argparse
import datetime
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('regression','native','browser','frozen','bundle','output'):
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    regression,native,browser,frozen,bundle=[read(getattr(args,name)) for name in ('regression','native','browser','frozen','bundle')]
    for report in (regression,native):
        if not report.get('successful') or report.get('failures') or report.get('errors'):raise ValueError('Unsuccessful regression')
    if not browser.get('passed') or len(browser.get('checks',[]))!=4 or not all(c['passed'] for c in browser['checks']):raise ValueError('Browser checks failed')
    if not frozen.get('passed') or len(frozen.get('cases',[]))!=3:raise ValueError('Frozen checks failed')
    for key in ('program_unchanged','checksums_valid'):
        if not frozen.get(key):raise ValueError('Frozen gate failed: '+key)
    if frozen.get('unexpected_resources') or not frozen.get('instance',{}).get('passed'):raise ValueError('Resources or instance check failed')
    archive=Path(bundle['zip'])
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=bundle['zip_sha256']:raise ValueError('Archive changed')
    manifest=read(Path(bundle['bundle'])/'SOURCE_MANIFEST.json')
    if not all(hashlib.sha256((ROOT/name).read_text(encoding='utf-8').replace('\r\n','\n').encode()).hexdigest()==digest for name,digest in manifest.items()):
        raise ValueError('Runtime source changed after build')
    fields=('name','passed','full_workflow','files','invalid_file_isolated','manual_rpm','batch_pairing','manual_segment',
        'smoothing_display_only','kl_known_n','rrde_known_n','peroxide_pct','invalid_rrde_preserved','ring_comparison',
        'csv_png_svg_json_zip','schema1_reader','schema2_roundtrip','background_cache_and_conflict','cancellation',
        'stale_result_discarded','readonly_file_checked','frozen','bundled_sys_path','streamlit_imported','platform',
        'python','qt_scale_factor','startup_seconds','workflow_seconds','window_logical_size',
        'screenshot_device_pixel_ratio','qt_platform','icon_loaded','exit_code','total_seconds','peak_working_set_bytes')
    for case in frozen['cases']:
        if not all(case.get(key) for key in ('passed','full_workflow','frozen','bundled_sys_path')) or case.get('streamlit_imported'):
            raise ValueError('Frozen workflow gate failed')
    result=dict(stage='M7',version=bundle['metadata']['version'],edition='native-local-candidate',
        recorded_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        regression={key:regression[key] for key in ('tests_run','successful','duration_seconds')},
        native_checks={key:native[key] for key in ('tests_run','successful','duration_seconds')},
        browser_checks=browser['checks'],frozen_cases=[{key:case[key] for key in fields if key in case} for case in frozen['cases']],
        instance=frozen['instance'],program_unchanged=True,checksums_valid=True,source_manifest_matches=True,
        external_python_on_path=frozen['external_python_on_path'],program_files_readonly=frozen['program_files_readonly'],
        actual_directory_acl_readonly=frozen['actual_directory_acl_readonly'],clean_machine_tested=False,
        real_samples_read=False,formal_github_release_created=False,
        archive=dict(name=archive.name,bytes=bundle['zip_bytes'],sha256=bundle['zip_sha256']),
        bundle=dict(files=bundle['bundle_files'],bytes=bundle['bundle_bytes'],source_digest=bundle['metadata']['source_digest'],
                    source_digest_format=bundle['metadata']['source_digest_format']),
        performance_scope='Generated batch of 9 samples plus 1 background, 26 raw points per file; startup_seconds measures application window initialization, not full cold boot.',
        pending=['Clean Windows without installed Python','Physical monitor scaling and manual interaction','Other Windows versions','Directory ACL read-only installation'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'output':str(args.output),'source_manifest_matches':True,'passed':True}))


if __name__=='__main__':main()
