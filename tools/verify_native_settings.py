"""Capture native M4 acceptance using generated migration fixtures only."""
from pathlib import Path
import json
import os
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(1,str(ROOT/'tests'))
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


def main():
    from PySide6.QtWidgets import QApplication
    from application.workspace import Workspace,State
    from desktop.window import MainWindow
    from migration_fixtures import workspace
    app=QApplication.instance() or QApplication([])
    traces,records,settings=workspace();ids=[i for i,c in records.items() if c['role']!='背景'];bg=next(i for i,c in records.items() if c['role']=='背景')
    records[ids[1]]['pH']=12.
    w=Workspace(State(traces=traces,configs=records,settings=settings));win=MainWindow(w);win.force_close=True
    output=Path(tempfile.mkdtemp(prefix='native_settings_',dir=ROOT/'verification'))
    try:
        win.resize(1440,1000);win.show();p=win.settings_pane;p.source.setCurrentIndex(p.source.findData(bg));p.sections.setCurrentIndex(3);app.processEvents()
        assert not p.fields['pH'].isEnabled() and not p.adopt.isEnabled()
        assert win.grab().save(str(output/'background_conflict.png'))
        p.to_independent.click();p.apply_button.click();p.sections.setCurrentIndex(0)
        p.fields['pH'].setText('10');p.fields['pH'].editingFinished.emit();p.apply_button.click();app.processEvents()
        assert w.state.configs[bg]['pH']==10.
        assert win.grab().save(str(output/'independent_conditions.png'))
        p.sections.setCurrentIndex(3);p.to_follow.click();p.apply_button.click();app.processEvents()
        assert w.state.configs[bg]['pH']==10. and not p.fields['pH'].isEnabled()
        assert win.grab().save(str(output/'follow_preserves_cache.png'))
        payload=w.project_bytes();other=Workspace();other.restore_project(payload)
        assert other.state.configs==w.state.configs
        report=dict(passed=True,files=len(traces),real_data_read=False,native_controls=True,
            conflict_locked=True,mode_and_values_staged=True,follow_preserves_cache=True,project_roundtrip=True)
        (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(output/'report.json')
    finally:win.close()


if __name__=='__main__':main()
