"""Native analysis controls and output provenance; generated-only workspace."""
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile
import numpy as np
import pandas as pd
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
QT=importlib.util.find_spec('PySide6') is not None


@unittest.skipUnless(QT,'Install requirements/desktop.txt for native analysis acceptance')
class DesktopAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from migration_fixtures import workspace
        from application.workspace import Workspace,State
        from desktop.window import MainWindow
        traces,records,settings=workspace();self.w=Workspace(State(traces=traces,configs=records,settings=settings))
        self.ids=[i for i,c in records.items() if c['role']!='背景']
        self.win=MainWindow(self.w);self.win.force_close=True;self.addCleanup(self.win.close)
    def select(self,kind,ids):
        from PySide6.QtCore import Qt
        pane=self.win.analyses[kind];pane.loading=True
        for index in range(pane.files.count()):
            item=pane.files.item(index);item.setCheckState(Qt.CheckState.Checked if item.data(Qt.ItemDataRole.UserRole) in ids else Qt.CheckState.Unchecked)
        pane.loading=False;pane.selection_changed();return pane
    def kl(self):
        pane=self.select('kl',self.ids[:3]);pane.use_coverage();pane.count.setValue(3);pane.confirmed.setChecked(True);return pane

    def test_kl_controls_known_answer_and_failed_selection_clears_previous_result(self):
        from orr_core import DataError
        pane=self.kl();saved=pane.calculate();np.testing.assert_allclose(saved['data'].n_KL,3.2,rtol=1e-10)
        self.assertIn('kl_plot.csv',self.w.state.exports);self.assertEqual(pane.figure_choice.count(),3)
        self.w.stage_config_updates('metadata',{self.ids[1]:{'rpm':None}})
        with self.assertRaises(DataError):pane.calculate()
        self.assertNotIn('kl_plot.csv',self.w.state.exports);self.assertIsNone(pane.saved)
        self.assertTrue(self.w.has_draft());self.assertEqual(self.w.state.configs[self.ids[1]]['rpm'],625)

    def test_kl_confirmation_failure_does_not_apply_scientific_draft(self):
        from orr_core import DataError
        pane=self.kl();pane.confirmed.setChecked(False)
        self.w.stage_config_updates('conditions',{self.ids[0]:{'collection_efficiency':.4}})
        with self.assertRaises(DataError):pane.calculate()
        self.assertEqual(self.w.state.configs[self.ids[0]]['collection_efficiency'],.369);self.assertTrue(self.w.has_draft())

    def test_rrde_retains_per_file_efficiencies_legacy_floor_and_invalid_points(self):
        from orr_core import rrde_calculate
        self.w.state.configs[self.ids[0]]['collection_efficiency']=.4;self.w.state.settings['rrde']['floor_A']=8e-9
        pane=self.select('rrde',[self.ids[0],self.ids[-1]]);self.win.refresh()
        self.assertEqual(pane.efficiency.text(),'')
        before,_=self.w.process_selected([self.ids[0],self.ids[-1]])
        result=pane.calculate();self.assertEqual(result['inputs']['floor_A'],8e-9)
        for ident,frame in result['frames'].items():pd.testing.assert_frame_equal(frame,rrde_calculate(before[ident],before[ident]['config'],8e-9))
        self.assertFalse(result['frames'][self.ids[-1]].valid_two_product_model.all())
        self.assertEqual(self.w.state.configs[self.ids[0]]['collection_efficiency'],.4)

    def test_rrde_efficiency_stages_selected_files_and_combines_apply_with_calculation(self):
        pane=self.select('rrde',self.ids[:2]);pane.efficiency.setText('0.4');pane.efficiency.setModified(True);pane.stage_efficiency()
        self.assertTrue(self.w.has_draft());self.assertEqual(self.w.state.configs[self.ids[0]]['collection_efficiency'],.369)
        pane.calculate()
        for ident in self.ids[:2]:self.assertEqual(self.w.state.configs[ident]['collection_efficiency'],.4)
        self.assertEqual(self.w.state.configs[self.ids[2]]['collection_efficiency'],.369)

    def test_rrde_rejected_input_survives_selection_changes(self):
        pane=self.select('rrde',self.ids[:2]);pane.efficiency.setText('wrong');pane.efficiency.setModified(True);pane.stage_efficiency()
        self.select('rrde',self.ids[2:4]);self.select('rrde',self.ids[:2]);self.assertEqual(pane.efficiency.text(),'wrong')
        self.assertTrue(self.w.has_draft());self.assertTrue(self.w.state.draft_errors)

    def test_display_preview_and_origin_export_use_current_units_without_implicit_apply(self):
        from orr_core import DataError
        pane=self.select('curves',self.ids[:1]);self.w.stage_config_updates('conditions',{self.ids[0]:{'collection_efficiency':.4}})
        pane.unit.setCurrentIndex(pane.unit.findData('mA/cm2'))
        self.assertTrue(self.w.has_draft());self.assertEqual(self.w.state.configs[self.ids[0]]['collection_efficiency'],.369)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'Origin 中文.csv'
            with self.assertRaises(DataError):self.win.export_file('polarization_plot.csv',path)
            self.assertFalse(path.exists());pane.export_csv(path)
            frame=pd.read_csv(path);self.assertIn('mA_cm2',frame.columns[1])
            self.assertEqual(self.w.state.configs[self.ids[0]]['collection_efficiency'],.4)

    def test_ring_comparison_ui_and_known_conflict_fail_without_old_download(self):
        from orr_core import DataError
        pane=self.select('curves',self.ids[:2]);pane.channel.setCurrentIndex(pane.channel.findData('ring'))
        result=pane.calculate();self.assertTrue(result['comparison_audit']['allowed'])
        self.assertIn('ring_current_plot.csv',self.w.state.exports)
        self.w.stage_config_updates('conditions',{self.ids[1]:{'electrolyte':'different electrolyte'}})
        with self.assertRaisesRegex(DataError,'已知条件冲突'):pane.calculate()
        self.assertNotIn('ring_current_plot.csv',self.w.state.exports)

    def test_independent_files_zip_parameters_and_project_roundtrip(self):
        from orr_core import unpack_project
        self.w.state.configs[self.ids[0]]['rpm']=None
        pane=self.select('curves',self.ids[:1]);pane.calculate()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for name in ('polarization_plot.csv','polarization.png','polarization.svg','polarization_data.csv'):
                self.win.export_file(name,root/name);self.assertGreater((root/name).stat().st_size,10)
            self.win.export_zip(root/'结果.zip')
            with zipfile.ZipFile(root/'结果.zip') as archive:self.assertIn('polarization.svg',archive.namelist())
            self.win.export_parameters(root/'参数.json');self.assertIn('stored_config',json.loads((root/'参数.json').read_bytes())['files'][0])
            self.win.save_project(root/'项目.orrproj');traces,configs,settings=unpack_project((root/'项目.orrproj').read_bytes())
            self.assertIsNone(configs[self.ids[0]]['rpm']);self.assertEqual(traces[self.ids[0]].raw,self.w.state.traces[self.ids[0]].raw)
            self.win.open_project(root/'项目.orrproj');self.assertIsNone(self.w.state.configs[self.ids[0]]['rpm']);self.assertEqual(self.w.state.exports,{})

    def test_scientific_apply_invalidates_other_analysis_display_and_exports(self):
        pane=self.select('rrde',self.ids[:1]);pane.calculate();self.assertIsNotNone(pane.saved)
        self.w.stage_config_updates('conditions',{self.ids[0]:{'collection_efficiency':.4}});self.win.apply()
        self.assertIsNone(pane.saved);self.assertNotIn('rrde_plot.csv',self.w.state.exports);self.assertEqual(pane.figure_choice.count(),0)

    def test_fit_potential_updates_display_and_export_image(self):
        import hashlib
        pane=self.kl();pane.calculate();first=hashlib.sha256(self.w.state.exports['kl_fit.png']['bytes']).hexdigest()
        pane.fit_potential.setCurrentIndex(0)
        from desktop.jobs import wait_for_idle
        wait_for_idle(self.win.jobs)
        self.assertNotEqual(first,hashlib.sha256(self.w.state.exports['kl_fit.png']['bytes']).hexdigest(),pane.note.text())
        self.assertIn(f"{pane.fit_potential.currentData():.4f}",pane.figures['kl_fit'].axes[0].get_title())
        params=json.loads(self.w.state.exports['kl_parameters.json']['bytes'])
        self.assertEqual(params['analysis_display']['fit_potential_V'],pane.fit_potential.currentData())

    def test_custom_constants_survive_preset_switch_and_condition_shortcut_preserves_targets(self):
        pane=self.select('kl',self.ids[:3]);pane.scheme.setCurrentIndex(pane.scheme.findData('custom'))
        pane.constants['C'].setText('2.4e-6');pane.source.setText('custom source')
        pane.scheme.setCurrentIndex(pane.scheme.findData('koh_25C'));pane.scheme.setCurrentIndex(pane.scheme.findData('custom'))
        self.assertEqual(pane.constants['C'].text(),'2.4e-6');self.assertEqual(pane.source.text(),'custom source')
        before=deepcopy(self.w.state.configs);pane.open_conditions()
        self.assertEqual(set(self.win.settings_pane.targets()),set(self.ids[:3]));self.assertEqual(self.w.state.configs,before);self.assertFalse(self.w.has_draft())
