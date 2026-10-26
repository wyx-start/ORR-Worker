"""Generated-only full native analysis, export and project screenshot acceptance."""
from pathlib import Path
import json
import os
import sys
import tempfile
import zipfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(1,str(ROOT/'tests'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from migration_fixtures import workspace
    from application.workspace import Workspace,State
    from desktop.window import MainWindow
    from desktop.jobs import wait_for_idle
    app=QApplication.instance() or QApplication([]);traces,records,settings=workspace()
    w=Workspace(State(traces=traces,configs=records,settings=settings));ids=[i for i,c in records.items() if c['role']!='背景']
    win=MainWindow(w);win.force_close=True;win.resize(1440,1000);win.show()
    output=Path(tempfile.mkdtemp(prefix='native_analysis_',dir=ROOT/'verification'))
    def selected(kind,chosen):
        pane=win.analyses[kind];pane.loading=True
        for index in range(pane.files.count()):
            item=pane.files.item(index);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in chosen else Qt.CheckState.Unchecked)
        pane.loading=False;pane.selection_changed();return pane
    try:
        curve=selected('curves',ids[:3]);curve.smooth.setChecked(True);curve.calculate_button.click();wait_for_idle(win.jobs);win.tabs.setCurrentIndex(1);app.processEvents();win.grab().save(str(output/'polarization.png'))
        kl=selected('kl',ids[:3]);kl.use_coverage();kl.count.setValue(3);kl.confirmed.setChecked(True);kl.calculate_button.click();wait_for_idle(win.jobs)
        np.testing.assert_allclose(w.state.results['kl']['data'].n_KL,3.2,rtol=1e-10)
        win.tabs.setCurrentIndex(2);app.processEvents();win.grab().save(str(output/'kl.png'))
        rrde=selected('rrde',ids);rrde.calculate_button.click();wait_for_idle(win.jobs);assert not w.state.results['rrde']['data'].valid_two_product_model.all()
        win.tabs.setCurrentIndex(3);app.processEvents();win.grab().save(str(output/'rrde.png'))
        curve.channel.setCurrentIndex(curve.channel.findData('ring'));curve.calculate_button.click();wait_for_idle(win.jobs);assert curve.figures
        win.tabs.setCurrentIndex(1);app.processEvents();win.grab().save(str(output/'ring.png'))
        win.export_complete_data(output/'complete.csv');win.export_parameters(output/'configuration.json');win.export_zip(output/'results.zip')
        with zipfile.ZipFile(output/'results.zip') as archive:assert all(name in archive.namelist() for name in ('kl_plot.csv','rrde_plot.csv','ring_current_plot.csv','all_curves.csv'))
        before=w.state.configs.copy();win.save_project(output/'project.orrproj');win.open_project(output/'project.orrproj');assert w.state.configs==before
        report=dict(passed=True,real_data_read=False,files=10,kl_known_n=3.2,rrde_invalid_preserved=True,curve_and_ring=True,zip_and_project=True)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(output/'report.json')
    finally:win.close()


if __name__=='__main__':main()
