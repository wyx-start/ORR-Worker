"""Native simplified import behavior and protection of stored scientific records."""
from copy import deepcopy
import importlib.util
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')


@unittest.skipUnless(importlib.util.find_spec('PySide6'),'Native dependency environment required')
class QuickImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from migration_fixtures import workspace
        from application.workspace import Workspace,State
        from desktop.window import MainWindow
        traces,configs,settings=workspace();self.w=Workspace(State(traces=traces,configs=configs,settings=settings))
        self.ids=[i for i,c in configs.items() if c['role']!='背景'];self.bg=next(i for i,c in configs.items() if c['role']=='背景')
        self.win=MainWindow(self.w);self.win.force_close=True;self.p=self.win.settings_pane;self.q=self.p.quick
        self.addCleanup(self.cleanup)
    def cleanup(self):
        from desktop.jobs import wait_for_idle
        if self.win.jobs.busy:self.win.jobs.cancel();wait_for_idle(self.win.jobs)
        self.win.close()

    def test_default_overview_has_no_visible_form_and_does_not_write(self):
        before=deepcopy(self.w.state.configs);self.win.show();self.app.processEvents()
        self.assertFalse(self.p.details_body.isVisible());self.assertFalse(self.q.body.isVisible())
        self.assertTrue(all(self.p.table.isColumnHidden(c) for c in (1,2,6)))
        self.assertIn('pH 13',self.q.summary.text());self.assertFalse(self.p.apply_button.isVisible())
        self.q.toggle.click();self.q.toggle.click();self.q.refresh()
        self.assertEqual(self.w.state.configs,before);self.assertFalse(self.w.has_draft())

    def test_batch_ph_edits_only_ph_and_keeps_background_independent_cache(self):
        before=deepcopy(self.w.state.configs);self.q.ph.setText('12');self.q.stage_ph();self.win.apply()
        for ident in self.ids:
            self.assertEqual(self.w.state.configs[ident]['pH'],12.)
            for field in ('reference','temperature_C','area_cm2','collection_efficiency','rpm','manual_segment'):
                self.assertEqual(self.w.state.configs[ident].get(field),before[ident].get(field))
        self.assertEqual(self.w.state.configs[self.bg],before[self.bg])
        self.assertEqual(self.w.get_draft_view()['configs'][self.bg]['pH'],12.)

    def test_mixed_and_unknown_values_are_not_replaced_by_defaults(self):
        self.w.state.configs[self.ids[0]].update(pH=None,collection_efficiency=None)
        self.w.state.configs[self.ids[1]]['pH']=12.;before=deepcopy(self.w.state.configs)
        self.p.refresh();self.assertIn('各文件不同',self.q.summary.text());self.assertEqual(self.q.ph.text(),'')
        self.q.stage_ph();self.assertFalse(self.w.has_draft());self.assertEqual(self.w.state.configs,before)
        self.assertIn('需处理',self.q.issues.text())

    def test_invalid_text_preserved_and_repair_back_to_applied_value_clears_old_intent(self):
        from orr_core import DataError
        self.q.ph.setText('12');self.q.stage_ph()
        self.q.ph.setText('wrong')
        with self.assertRaises(DataError):self.q.stage_ph()
        self.q.refresh();self.assertEqual(self.q.ph.text(),'wrong');self.assertIn('草稿待修正',self.q.issues.text())
        self.q.ph.setText('13');self.q.stage_ph();self.win.apply()
        self.assertTrue(all(self.w.state.configs[i]['pH']==13 for i in self.ids))

    def test_selected_scope_excludes_background_and_other_samples(self):
        from PySide6.QtCore import QItemSelectionModel
        self.q.scope.setCurrentText('表格选中')
        for ident in (self.ids[0],self.bg):
            self.p.table.selectionModel().select(self.p.model.index(self.p.model.ids.index(ident),0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        self.assertEqual(self.q.targets(),[self.ids[0]])
        self.q.ph.setText('12');self.q.stage_ph();self.win.apply()
        self.assertEqual(self.w.state.configs[self.ids[0]]['pH'],12.)
        self.assertEqual(self.w.state.configs[self.ids[1]]['pH'],13.)
        self.assertEqual(self.w.state.configs[self.bg]['pH'],11.)

    def test_background_binding_pairs_channels_and_keep_does_not_clear(self):
        self.q.background.setCurrentIndex(self.q.background.findData(self.bg));self.q.stage_background()
        before=deepcopy(self.w.state.settings_draft);self.q.background.setCurrentIndex(0);self.q.stage_background()
        self.assertEqual(self.w.state.settings_draft,before);self.win.apply()
        for ident in self.ids:
            self.assertEqual(self.w.state.configs[ident]['background_disk'],self.bg)
            self.assertEqual(self.w.state.configs[ident]['background_ring'],self.bg)
        self.q.background.setCurrentIndex(self.q.background.findData('none'));self.q.stage_background();self.win.apply()
        self.assertTrue(all(self.w.state.configs[i]['background_disk'] is None and self.w.state.configs[i]['background_ring'] is None for i in self.ids))

    def test_reference_change_preserves_measured_method_and_unknown_temperature(self):
        self.w.state.configs[self.ids[0]].update(potential_method='实测 RHE 总偏移',rhe_offset_V=0.,temperature_C=None)
        self.p.refresh();self.assertFalse(self.q.ph.isEnabled());self.assertFalse(self.q.reference.isEnabled())
        self.assertEqual(self.w.state.configs[self.ids[0]]['rhe_offset_V'],0.)
        self.assertIsNone(self.w.state.configs[self.ids[0]]['temperature_C'])

    def test_analysis_shortcut_opens_the_hidden_editor(self):
        self.win.analyses['rrde'].open_conditions();self.assertTrue(self.p.details_toggle.isChecked())
        self.assertEqual(self.p.scope.currentText(),'表格选中')

    def test_direct_plot_applies_draft_once_and_runs_background_pipeline(self):
        from desktop.jobs import wait_for_idle
        from unittest.mock import patch
        self.q.ph.setText('12');self.q.stage_ph();self.assertTrue(self.w.has_draft())
        with patch('desktop.window.QMessageBox.warning') as warning:
            self.p.plot_button.click();wait_for_idle(self.win.jobs);warning.assert_not_called()
        self.assertEqual(self.win._last_job_state,'accepted');self.assertFalse(self.w.has_draft())
        self.assertEqual(self.win.tabs.currentIndex(),1)
        self.assertTrue(all(self.w.state.configs[i]['pH']==12 for i in self.ids))
        self.assertIn('polarization_plot.csv',self.w.state.exports)

    def test_missing_rpm_is_optional_for_curves_and_remains_manually_editable(self):
        self.w.state.configs[self.ids[0]]['rpm']=None;self.p.refresh()
        self.assertIn('仅 K–L 需要',self.q.issues.text())
        index=self.p.model.index(self.p.model.ids.index(self.ids[0]),4)
        self.assertTrue(self.p.model.setData(index,'1600'));self.win.apply()
        self.assertEqual(self.w.state.configs[self.ids[0]]['rpm_source'],'manual')
