"""Native settings acceptance: actual Qt models, controls and transaction state."""
from copy import deepcopy
import importlib.util
import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QT=importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(QT,'Install requirements/desktop.txt for native settings acceptance')
class DesktopSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from migration_fixtures import workspace
        from application.workspace import Workspace,State
        from desktop.window import MainWindow
        traces,records,settings=workspace();self.w=Workspace(State(traces=traces,configs=records,settings=settings))
        self.ids=[i for i,c in records.items() if c['role']!='背景'];self.bg=next(i for i,c in records.items() if c['role']=='背景')
        self.win=MainWindow(self.w);self.win.force_close=True;self.p=self.win.settings_pane;self.addCleanup(self.win.close)
    def select(self,ident):self.p.source.setCurrentIndex(self.p.source.findData(ident))

    def test_manual_rpm_model_edit_preserves_other_records(self):
        self.w.state.configs[self.ids[0]]['rpm']=None;self.p.refresh()
        before=deepcopy(self.w.state.configs[self.ids[1]])
        index=self.p.model.index(self.p.model.ids.index(self.ids[0]),4)
        self.assertTrue(self.p.model.setData(index,'1600'));self.win.apply()
        self.assertEqual(self.w.state.configs[self.ids[0]]['rpm'],1600)
        self.assertEqual(self.w.state.configs[self.ids[0]]['rpm_source'],'manual')
        self.assertEqual(self.w.state.configs[self.ids[1]],before)

    def test_batch_pairing_preview_and_all_keep_do_not_erase_pending(self):
        self.select(self.ids[0]);self.p.scope.setCurrentText('全部样品')
        self.p.batch_mode.setCurrentText('A');self.p.batch_direction.setCurrentText('递减')
        self.p.batch_action.setCurrentIndex(self.p.batch_action.findData('paired'))
        self.p.batch_disk.setCurrentIndex(self.p.batch_disk.findData(self.bg))
        updates,rows=self.p.preview_batch();self.assertEqual(len(updates),9);self.assertEqual(len(rows),9)
        self.p.stage_batch();before=deepcopy(self.w.state.settings_draft)
        self.p.batch_mode.setCurrentIndex(0);self.p.batch_direction.setCurrentIndex(0);self.p.batch_action.setCurrentIndex(0)
        self.p.stage_batch();self.assertEqual(self.w.state.settings_draft,before)
        self.win.apply()
        for ident in self.ids:
            c=self.w.state.configs[ident];self.assertEqual(c['background_disk'],self.bg);self.assertEqual(c['background_ring'],self.bg)
        self.assertEqual(self.w.state.configs[self.bg]['pH'],11)

    def test_conflict_is_read_only_and_modes_preserve_independent_cache(self):
        self.w.state.configs[self.ids[1]]['pH']=12.;self.select(self.bg)
        self.assertFalse(self.p.fields['pH'].isEnabled());self.assertFalse(self.p.adopt.isEnabled())
        self.assertIn('条件冲突',self.p.bg_summary.text())
        self.p.switch_mode('independent');self.win.apply();self.assertEqual(self.p.fields['pH'].text(),'11.0')
        self.p.fields['pH'].setText('10');self.p.stage_field('pH');self.win.apply()
        self.p.switch_mode('follow');self.win.apply();self.assertEqual(self.w.state.configs[self.bg]['pH'],10)
        self.assertFalse(self.p.fields['pH'].isEnabled())
        self.p.switch_mode('independent');self.win.apply();self.assertEqual(self.p.fields['pH'].text(),'10.0')

    def test_adopt_copies_only_active_effective_fields_with_sources(self):
        self.select(self.bg);self.assertTrue(self.p.adopt.isEnabled());self.p.adopt_effective();self.win.apply()
        c=self.w.state.configs[self.bg];self.assertEqual(c['pH'],13)
        self.assertEqual(c['background_conditions_mode'],'independent')
        self.assertTrue(c['parameter_sources']['pH'].startswith('用户复制'))
        self.assertIsNone(c['rhe_offset_V'])

    def test_legacy_only_ph_is_locked(self):
        self.w.state.configs[self.bg].update(background_conditions_mode='legacy_ph',background_ph_mode='follow',background_ph_legacy=False)
        self.select(self.bg);self.assertFalse(self.p.fields['pH'].isEnabled())
        self.assertTrue(self.p.fields['reference'].isEnabled());self.assertTrue(self.p.fields['temperature_C'].isEnabled())
        self.p.fields['temperature_C'].setText('20');self.p.stage_field('temperature_C');self.win.apply()
        self.assertEqual(self.w.state.configs[self.bg]['temperature_C'],20)
        self.assertEqual(self.w.state.configs[self.bg]['background_ph_mode'],'follow')

    def test_rejected_text_survives_source_changes_and_repair(self):
        self.select(self.ids[0]);self.p.fields['pH'].setText('wrong');self.p.stage_field('pH')
        self.assertEqual(self.w.get_draft_view()['view_basis'],'applied_fallback')
        self.assertEqual(self.p.fields['pH'].text(),'wrong')
        self.select(self.ids[1]);self.select(self.ids[0]);self.assertEqual(self.p.fields['pH'].text(),'wrong')
        self.p.fields['pH'].setText('12');self.p.stage_field('pH');self.win.apply()
        self.assertEqual(self.w.state.configs[self.ids[0]]['pH'],12)

    def test_mode_switch_does_not_erase_scan_edits(self):
        self.select(self.bg);self.p.stage_scan({'mode':'B'})
        self.p.switch_mode('independent');self.win.apply()
        self.assertEqual(self.w.state.configs[self.bg]['mode'],'B')

    def test_diameter_uses_full_precision_and_scoped_multi_target_edit(self):
        self.select(self.ids[0]);self.p.scope.setCurrentText('当前组')
        self.p.fields['disk_diameter_mm'].setText('4');self.p.stage_field('disk_diameter_mm');self.win.apply()
        import math
        for ident in self.ids:self.assertAlmostEqual(self.w.state.configs[ident]['area_cm2'],math.pi*.04,places=15)
        self.assertEqual(self.w.state.configs[self.bg]['disk_diameter_mm'],5.)

    def test_source_changes_and_preview_do_not_apply_implicitly(self):
        before=deepcopy(self.w.state.configs);revision=self.w.state.revision
        for ident in (self.ids[1],self.bg,self.ids[0]):self.select(ident)
        self.p.preview_batch()
        self.assertEqual(self.w.state.configs,before);self.assertEqual(self.w.state.revision,revision)
        self.assertFalse(self.w.has_draft())

    def test_manual_segment_updates_direction_and_highlights_source_rows(self):
        self.select(self.ids[0]);self.p.segment.setCurrentIndex(self.p.segment.findData(1));self.win.apply()
        c=self.w.state.configs[self.ids[0]];self.assertEqual(c['manual_segment'],1);self.assertEqual(c['direction'],'递增')
        self.assertEqual(len(self.p.scan_canvas.figure.axes[0].lines),2)

    def test_background_table_is_effective_view_not_storage(self):
        self.select(self.bg);info=self.w.get_draft_view()['configs'][self.bg]['background_conditions']
        self.assertEqual(info['effective']['pH'],13);self.assertEqual(info['independent']['pH'],11)
        self.assertNotIn('background_conditions',self.w.state.configs[self.bg])
        self.assertEqual(self.p.bg_table.rowCount(),9)

    def test_preset_checks_actual_mixed_targets_atomically(self):
        from PySide6.QtCore import QItemSelectionModel
        self.select(self.ids[0]);self.p.scope.setCurrentText('表格选中')
        for ident in (self.ids[0],self.bg):
            self.p.table.selectionModel().select(self.p.model.index(self.p.model.ids.index(ident),0),QItemSelectionModel.SelectionFlag.Select|QItemSelectionModel.SelectionFlag.Rows)
        before=deepcopy(self.w.state.configs)
        self.p.apply_preset('Ag/AgCl · 饱和 KCl · 25 °C')
        self.assertEqual(self.w.state.configs,before)
        self.assertEqual(self.w.get_draft_view()['view_basis'],'applied_fallback')
        self.assertTrue(self.w.state.rejected_config_edits)

    def test_import_error_list_remains_available_after_condition_edit(self):
        self.w.state.import_errors=[{'文件':'bad.txt','原因':'没有有效数据列'}];self.p.refresh()
        self.select(self.ids[0]);self.p.fields['pH'].setText('12');self.p.stage_field('pH')
        self.assertEqual(self.p.import_errors.rowCount(),1)
        self.assertEqual(self.p.import_errors.item(0,1).text(),'没有有效数据列')

    def test_unchanged_reference_field_keeps_preset_and_sources(self):
        self.select(self.ids[0]);before=deepcopy(self.w.state.configs)
        self.p.stage_field('reference')
        self.assertFalse(self.w.has_draft());self.assertEqual(self.w.state.configs,before)

    def test_per_file_page_does_not_apply_group_scope(self):
        self.select(self.ids[0]);self.p.scope.setCurrentText('全部样品');self.p.sections.setCurrentIndex(1)
        self.assertEqual(self.p.targets(),[self.ids[0]]);self.assertFalse(self.p.scope.isEnabled())
        old=self.w.state.configs[self.ids[1]]['electrolyte']
        self.p.fields['electrolyte'].setText('changed record');self.p.stage_field('electrolyte');self.win.apply()
        self.assertEqual(self.w.state.configs[self.ids[0]]['electrolyte'],'changed record')
        self.assertEqual(self.w.state.configs[self.ids[1]]['electrolyte'],old)
