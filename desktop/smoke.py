"""Generated-only closed-loop verification available in source and frozen builds."""
from pathlib import Path
import json
import os
import platform
import stat
import sys
import time
import zipfile
from io import BytesIO
import numpy as np
from PySide6.QtWidgets import QApplication


def verify(window, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    name=output/'中文 样品 1600转.txt'
    potentials=[i/10 for i in range(11)]+[i/10 for i in range(9,-1,-1)]
    raw='SYNTHETIC DESKTOP SMOKE - NO MEASURED DATA\nHigh E (V) = 1\nLow E (V) = 0\nPotential/V,Current/A\n'
    raw+='\n'.join(f'{e},{-0.001*(1+e)}' for e in potentials)
    name.write_text(raw,encoding='utf-8')
    assert window.import_paths([name])==1
    ident=next(iter(window.workspace.state.traces))
    assert window.workspace.state.configs[ident]['pH']==13
    assert window.workspace.state.configs[ident]['rpm']==1600
    window.fields['pH'].setText('12');window.stage_field('pH');window.apply()
    assert window.workspace.state.configs[ident]['pH']==12
    assert not window.workspace.state.configs[ident]['parameter_sources']['pH'].startswith('软件默认')
    window.segment.setCurrentIndex(window.segment.findData(2));window.apply()
    result=window.calculate()
    assert result['outputs'][ident]['segment']['segment']==2
    for name in ('polarization_plot.csv','polarization.png','polarization.svg'):
        window.export_file(name,output/name);assert (output/name).stat().st_size>10
    project=output/'中文 项目.orrproj';window.save_project(project);window.open_project(project)
    assert window.workspace.state.configs[ident]['pH']==12
    window.calculate();window.show();QApplication.processEvents()
    assert window.grab().save(str(output/'desktop.png'))
    report=dict(passed=True,real_data_read=False,native_window=True,imports=1,manual_segment=2,
        csv_png_svg=True,project_roundtrip=True,clean_machine=False)
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


def verify_full(window,output):
    """Actual native controls and async jobs on ten generated experimental files."""
    from PySide6.QtCore import Qt
    from desktop.demo import generated_workspace
    from desktop.jobs import wait_for_idle
    from orr_core import unpack_project
    started=time.perf_counter();window.force_close=True;window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen,True);window.resize(1150,720)
    assert not QApplication.windowIcon().pixmap(32,32).isNull()
    output=Path(output);output.mkdir(parents=True,exist_ok=True);inputs=output/'中文 转速批次';inputs.mkdir(exist_ok=True)
    generated,configs,_=generated_workspace();paths=[]
    for trace in generated.values():
        name='Synthetic-unmarked.txt' if '3600rpm' in trace.name else trace.name
        path=inputs/name;path.write_bytes(trace.raw);paths.append(path)
    bad=inputs/'invalid.txt';bad.write_text('SYNTHETIC invalid input',encoding='utf-8');paths.append(bad)
    window.request_import(paths);wait_for_idle(window.jobs)
    assert window._last_job_state=='accepted' and len(window.workspace.state.traces)==10
    assert len(window.workspace.state.import_errors)==1
    w=window.workspace;p=window.settings_pane
    samples=[i for i,c in w.state.configs.items() if c['role']!='背景'];bg=next(i for i,c in w.state.configs.items() if c['role']=='背景')
    assert p.details_body.isHidden() and p.quick.body.isHidden()
    window.tabs.setCurrentIndex(0);window.show();QApplication.processEvents()
    assert window.grab().save(str(output/'simple_import.png'))
    p.plot_button.click();wait_for_idle(window.jobs)
    assert window._last_job_state=='accepted' and 'polarization_plot.csv' in w.state.exports
    window.tabs.setCurrentIndex(0);p.quick.toggle.click()
    p.quick.background.setCurrentIndex(p.quick.background.findData(bg));p.quick.background.activated.emit(p.quick.background.currentIndex())
    assert w.has_draft();p.apply_button.click();p.quick.toggle.click()
    for ident in samples:assert w.state.configs[ident]['background_disk']==bg and w.state.configs[ident]['background_ring']==bg
    unknown=next(i for i,t in w.state.traces.items() if t.name=='Synthetic-unmarked.txt')
    assert w.state.configs[unknown]['rpm'] is None
    for ident in samples:assert w.state.configs[ident]['pH']==13 and w.state.configs[ident]['reference']=='SCE' and w.state.configs[ident]['collection_efficiency']==.369
    row=p.model.ids.index(unknown);assert p.model.setData(p.model.index(row,4),'3600')
    assert p.model.setData(p.model.index(row,2),w.state.configs[samples[0]]['group'])
    p.source.setCurrentIndex(p.source.findData(samples[0]));p.sections.setCurrentIndex(0);p.scope.setCurrentText('全部样品')
    p.fields['electrolyte'].setText('O2 synthetic electrolyte');p.stage_field('electrolyte')
    p.batch_direction.setCurrentText('递减');p.batch_mode.setCurrentText('A');p.batch_action.setCurrentIndex(p.batch_action.findData('paired'));p.batch_disk.setCurrentIndex(p.batch_disk.findData(bg))
    p.sections.setCurrentIndex(2);updates=p.stage_batch();assert len(updates)==9;p.apply_button.click()
    for ident in samples:assert w.state.configs[ident]['background_disk']==bg and w.state.configs[ident]['background_ring']==bg
    assert w.state.configs[unknown]['rpm']==3600 and w.state.configs[unknown]['rpm_source']=='manual'
    p.sections.setCurrentIndex(1);p.segment.setCurrentIndex(p.segment.findData(2));p.apply_button.click()
    assert w.state.configs[samples[0]]['manual_segment']==2
    window.show();QApplication.processEvents()

    def selected(kind,ids):
        pane=window.analyses[kind];pane.loading=True
        for index in range(pane.files.count()):
            item=pane.files.item(index);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)
        pane.loading=False;pane.selection_changed();return pane
    def complete():
        wait_for_idle(window.jobs);assert window._last_job_state=='accepted',window.statusBar().currentMessage()
    curve=selected('curves',samples[:3]);curve.smooth.setChecked(True);curve.calculate_button.click();complete()
    window.tabs.setCurrentIndex(1);QApplication.processEvents();assert window.grab().save(str(output/'polarization.png'))
    curve.request_csv(output/'Origin 曲线.csv');complete();curve.request_png(output/'curve.png');complete()
    curve.extra.setCurrentText('polarization.svg');curve.request_extra(output/'curve.svg');complete()
    assert (output/'curve.png').read_bytes().startswith(b'\x89PNG') and '<svg' in (output/'curve.svg').read_text(encoding='utf-8')
    kl=selected('kl',samples[:3]);kl.request_coverage();complete();kl.count.setValue(3);kl.confirmed.setChecked(True)
    kl.calculate_button.click();complete();np.testing.assert_allclose(w.state.results['kl']['data'].n_KL,3.2,rtol=1e-10)
    kl.fit_potential.setCurrentIndex(0);complete()
    assert json.loads(w.state.exports['kl_parameters.json']['bytes'])['analysis_display']['fit_potential_V']==kl.fit_potential.currentData()
    window.tabs.setCurrentIndex(2);QApplication.processEvents();assert window.grab().save(str(output/'kl.png'))
    kl.request_csv(output/'Origin KL.csv');complete()
    rrde=selected('rrde',samples);rrde.calculate_button.click();complete()
    rrde_result=w.state.results['rrde'];np.testing.assert_allclose(rrde_result['frames'][samples[0]].n_RRDE,3.2,rtol=1e-12)
    np.testing.assert_allclose(rrde_result['frames'][samples[0]].peroxide_pct,40.,rtol=1e-12)
    assert not rrde_result['frames'][unknown].valid_two_product_model.all()
    window.tabs.setCurrentIndex(3);QApplication.processEvents();assert window.grab().save(str(output/'rrde.png'))
    rrde.request_csv(output/'Origin RRDE.csv');complete()
    curve=selected('curves',samples[:2]);curve.channel.setCurrentIndex(curve.channel.findData('ring'));curve.calculate_button.click();complete()
    assert w.state.results['ring_curves']['comparison_audit']['allowed']
    window.tabs.setCurrentIndex(1);QApplication.processEvents();assert window.grab().save(str(output/'ring.png'))
    window.start_task('data',{'target':str(output/'complete.csv'),'asset':'all_curves.csv'});complete()
    window.start_task('parameters',{'target':str(output/'configuration.json')});complete()
    window.start_task('zip',{'target':str(output/'results.zip')});complete()
    with zipfile.ZipFile(output/'results.zip') as archive:assert all(n in archive.namelist() for n in ('kl_plot.csv','rrde_plot.csv','ring_current_plot.csv','all_curves.csv'))
    project=output/'中文 项目.orrproj';window.start_task('project',{'target':str(project),'inputs':window.collect_project_inputs()});complete()
    assert not window.has_unsaved_work()
    original_raw={i:t.raw for i,t in w.state.traces.items()}
    window.request_load(project,discard=True);complete()
    assert w.state.configs[unknown]['rpm']==3600 and w.state.configs[unknown]['rpm_source']=='manual'
    assert all(w.state.traces[i].raw==raw for i,raw in original_raw.items()) and not w.state.exports
    # Exercise the legacy reader in the actual frozen runtime, without private files.
    legacy=BytesIO()
    with zipfile.ZipFile(project) as source,zipfile.ZipFile(legacy,'w') as target:
        for name in source.namelist():
            raw=source.read(name)
            if name=='project.json':
                data=json.loads(raw);data['schema']=1
                for item in data['files']:
                    item['config'].pop('background_conditions_mode',None);item['config'].pop('background_conditions_migration',None)
                    if item['config']['role']=='背景':item['config'].update(background_ph_mode='manual',background_ph_legacy=False)
                raw=json.dumps(data).encode()
            target.writestr(name,raw)
    assert unpack_project(legacy.getvalue())[1][unknown]['rpm']==3600
    p.source.setCurrentIndex(p.source.findData(bg));p.sections.setCurrentIndex(3);p.to_independent.click();p.apply_button.click()
    p.sections.setCurrentIndex(0);p.scope.setCurrentText('仅此文件');p.fields['pH'].setText('10');p.stage_field('pH');p.apply_button.click()
    p.sections.setCurrentIndex(3);p.to_follow.click();p.apply_button.click();assert w.state.configs[bg]['pH']==10.
    p.source.setCurrentIndex(p.source.findData(samples[1]));p.sections.setCurrentIndex(0);p.fields['pH'].setText('12');p.stage_field('pH');p.apply_button.click()
    p.source.setCurrentIndex(p.source.findData(bg));p.sections.setCurrentIndex(3)
    assert not p.adopt.isEnabled() and not p.fields['pH'].isEnabled() and '条件冲突' in p.bg_summary.text()
    window.tabs.setCurrentIndex(0);QApplication.processEvents();assert window.grab().save(str(output/'background_conflict.png'))
    p.to_independent.click();p.apply_button.click();assert w.state.configs[bg]['pH']==10.
    window.request_load(project,discard=True);complete()
    curve=selected('curves',samples[:2]);cancelled=output/'cancelled.csv';cancelled.write_bytes(b'original')
    curve.request_csv(cancelled);window.jobs.cancel();wait_for_idle(window.jobs)
    assert cancelled.read_bytes()==b'original' and window._last_job_state=='discarded'
    stale=output/'stale.csv';stale.write_bytes(b'original');curve.request_csv(stale)
    w.stage_config_updates('synthetic_future',{samples[0]:{'collection_efficiency':.4}});wait_for_idle(window.jobs)
    assert stale.read_bytes()==b'original' and window._last_job_state=='discarded' and w.has_draft()
    assert w.state.configs[samples[0]]['collection_efficiency']==.369;w.reset_draft();window.refresh()
    readonly_checked=False
    if os.name=='nt':
        readonly=output/'readonly.csv';readonly.write_bytes(b'original');readonly.chmod(stat.S_IREAD)
        try:
            curve.request_csv(readonly);wait_for_idle(window.jobs)
            assert readonly.read_bytes()==b'original' and window._last_job_state=='failed'
            readonly_checked=True
        finally:readonly.chmod(stat.S_IREAD|stat.S_IWRITE)
    # A separate analytic wave exercises useful onset/half-wave answers in the
    # actual runtime; the ten-file fixture above is deliberately not sigmoid.
    from application.workspace import Workspace
    e=np.r_[np.linspace(0,1.2,61),np.linspace(1.18,0,60)]
    current=np.where(e>=1.,0.,np.where(e<=.6,1.,(1.-e)/.4))
    raw='SYNTHETIC ANALYTIC WAVE\nHigh E (V) = 1.2\nLow E (V) = 0\nPotential/V,Current/A\n'
    raw+='\n'.join(f'{potential:.10f},{-value/1000:.15f}' for potential,value in zip(e,current))
    wave=Workspace();wave.add_files([('Synthetic-potential-wave-1600rpm.txt',raw.encode())]);wave_id=next(iter(wave.state.traces))
    wave.state.configs[wave_id].update(potential_method='已是 RHE',area_cm2=.2,area_mode='area',disk_diameter_mm=None)
    wave.state.settings['plot']['potentials']={'plateau_mode':'manual','plateau_start':.1,'plateau_end':.3,'show_markers':True}
    wave_project=output/'analytic-wave.orrproj';wave_project.write_bytes(wave.project_bytes())
    window.request_load(wave_project,discard=True);complete();curve=window.analyses['curves']
    curve.calculate_button.click();complete();row=w.state.results['curves']['potentials'].iloc[0]
    assert abs(row.E_onset_V-.992)<1e-10 and abs(row.E_half_V-.8)<1e-10
    assert curve.potential_table.rowCount()==1
    curve.request_export('polarization_potentials.csv',recompute=True,path=output/'potential_metrics.csv');complete()
    import pandas as pd
    exported=pd.read_csv(output/'potential_metrics.csv');assert abs(exported.E_half_V.iloc[0]-.8)<1e-10
    assert json.loads(w.state.exports['parameters.json']['bytes'])['analysis_polarization_potentials']['current_source']=='processed_unsmoothed_disk'
    window.tabs.setCurrentIndex(1);QApplication.processEvents();assert window.grab().save(str(output/'potential_metrics.png'))
    frozen=bool(getattr(sys,'frozen',False));root=Path(sys.executable).resolve().parent
    isolated_paths=all(Path(path).resolve().is_relative_to(root) for path in sys.path) if frozen else None
    if frozen:assert isolated_paths and not any(name=='streamlit' or name.startswith('streamlit.') for name in sys.modules)
    report=dict(passed=True,full_workflow=True,simple_import=True,polarization_potentials=True,known_E_onset_V=float(row.E_onset_V),known_E_half_V=float(row.E_half_V),
        real_data_read=False,native_window=True,files=10,additional_analytic_wave=1,invalid_file_isolated=True,
        manual_rpm=True,batch_pairing=True,manual_segment=True,smoothing_display_only=True,kl_known_n=3.2,rrde_known_n=3.2,
        peroxide_pct=40.,invalid_rrde_preserved=True,ring_comparison=True,csv_png_svg_json_zip=True,schema1_reader=True,
        schema2_roundtrip=True,background_cache_and_conflict=True,cancellation=True,stale_result_discarded=True,
        readonly_file_checked=readonly_checked,clean_machine=False,frozen=frozen,bundled_sys_path=isolated_paths,
        streamlit_imported='streamlit' in sys.modules,platform=platform.platform(),python=platform.python_version(),
        qt_scale_factor=os.environ.get('QT_SCALE_FACTOR','1'),startup_seconds=getattr(window,'startup_seconds',None),
        workflow_seconds=time.perf_counter()-started,window_logical_size=[window.width(),window.height()],
        screenshot_device_pixel_ratio=window.devicePixelRatioF())
    report['qt_platform']=QApplication.platformName();report['icon_loaded']=True
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');return report
