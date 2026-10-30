"""Actual processing, numeric exports and Qt callbacks for polarization metrics."""
from copy import deepcopy
from io import BytesIO
import importlib.util
import json
import os
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from application.workspace import Workspace
from application.curves import calculate_curves
from orr_core import DataError


def workspace():
    e=np.r_[np.linspace(0,1.2,61),np.linspace(1.18,0,60)]
    q=np.where(e>=1.,0.,np.where(e<=.6,1.,(1.-e)/.4))
    raw='SYNTHETIC ORR WAVE\nHigh E (V) = 1.2\nLow E (V) = 0\nPotential/V,Current/A\n'
    raw+='\n'.join(f'{potential:.10f},{-current/1000:.15f}' for potential,current in zip(e,q))
    w=Workspace();w.add_files([('Synthetic-wave-1600rpm.txt',raw.encode())]);ident=next(iter(w.state.traces))
    w.state.configs[ident].update(potential_method='已是 RHE',area_cm2=.2,area_mode='area',disk_diameter_mm=None)
    return w,ident


class PotentialExportTests(unittest.TestCase):
    def test_actual_processed_wave_csv_and_parameter_snapshot_agree(self):
        w,ident=workspace();result=calculate_curves(w,[ident]);row=result['potentials'].iloc[0]
        self.assertAlmostEqual(row.E_onset_V,.992,places=10);self.assertAlmostEqual(row.E_half_V,.8,places=10)
        exported=pd.read_csv(BytesIO(w.state.exports['polarization_potentials.csv']['bytes']))
        self.assertAlmostEqual(exported.E_half_V.iloc[0],.8,places=10)
        record=json.loads(w.state.exports['parameters.json']['bytes'])['analysis_polarization_potentials']
        self.assertEqual(record['current_source'],'processed_unsmoothed_disk')
        self.assertAlmostEqual(record['results'][0]['E_onset_V'],.992,places=10)
        self.assertEqual(record['results'][0]['axis'],'RHE')

    def test_display_smoothing_and_density_do_not_move_metrics(self):
        w,ident=workspace();before=calculate_curves(w,[ident])['potentials']
        w.state.settings['plot'].update(density=True,smoothing={'enabled':True,'window_points':11})
        after=calculate_curves(w,[ident])['potentials']
        pd.testing.assert_frame_equal(before,after)

    def test_raw_and_rhe_shifts_propagate_to_both_potentials(self):
        w,ident=workspace();w.state.settings['axis']='原始';w.state.configs[ident].update(potential_method='实测 RHE 总偏移',rhe_offset_V=.25)
        raw=calculate_curves(w,[ident])['potentials'].iloc[0]
        w.state.settings['axis']='RHE';converted=calculate_curves(w,[ident])['potentials'].iloc[0]
        for key in ('E_onset_V','E_half_V'):self.assertAlmostEqual(converted[key]-raw[key],.25,places=10)
        self.assertEqual(raw.axis,'原始');self.assertEqual(converted.axis,'RHE')

    def test_metric_settings_roundtrip_without_schema_change(self):
        w,ident=workspace();w.state.settings['plot']['potentials']={'plateau_mode':'manual','plateau_start':.1,'plateau_end':.3,'baseline_mA':.02,'onset_threshold':.2}
        expected=deepcopy(w.state.settings['plot']['potentials']);restored=Workspace();restored.restore_project(w.project_bytes())
        self.assertEqual(restored.state.settings['plot']['potentials'],expected)

    def test_missing_area_keeps_plot_and_half_wave_but_explains_onset(self):
        w,ident=workspace();w.state.configs[ident]['area_cm2']=None
        row=calculate_curves(w,[ident])['potentials'].iloc[0]
        self.assertIsNone(row.E_onset_V);self.assertIn('面积',row.onset_reason)
        self.assertAlmostEqual(row.E_half_V,.8,places=10);self.assertIn('polarization.png',w.state.exports)

    def test_invalid_metric_options_remove_old_metric_export(self):
        w,ident=workspace();calculate_curves(w,[ident]);w.state.settings['plot']['potentials']['onset_threshold']=-1
        with self.assertRaises(DataError):calculate_curves(w,[ident])
        self.assertNotIn('polarization_potentials.csv',w.state.exports)


os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
@unittest.skipUnless(importlib.util.find_spec('PySide6'),'Native dependency environment required')
class PotentialDesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def setUp(self):
        from desktop.window import MainWindow
        self.w,self.ident=workspace();self.win=MainWindow(self.w);self.win.force_close=True;self.p=self.win.analyses['curves'];self.addCleanup(self.cleanup)
    def cleanup(self):
        from desktop.jobs import wait_for_idle
        if self.win.jobs.busy:self.win.jobs.cancel();wait_for_idle(self.win.jobs)
        self.win.close()
    def test_real_button_results_and_metric_csv_save(self):
        from desktop.jobs import wait_for_idle
        from pathlib import Path
        import tempfile
        with patch('desktop.window.QMessageBox.warning') as warning:
            self.p.calculate_button.click();wait_for_idle(self.win.jobs);warning.assert_not_called()
        self.assertEqual(self.p.potential_table.rowCount(),1)
        self.assertEqual(self.p.potential_table.item(0,3).text(),'0.8')
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'potentials.csv'
            with patch('PySide6.QtWidgets.QFileDialog.getSaveFileName',return_value=(str(target),'')):
                self.p.potential_csv.click();wait_for_idle(self.win.jobs)
            self.assertTrue(target.exists());self.assertAlmostEqual(pd.read_csv(target).E_half_V.iloc[0],.8,places=10)
    def test_bad_raw_input_blocks_project_save_and_clears_stale_metrics(self):
        self.p.calculate();self.assertIn('polarization_potentials.csv',self.w.state.exports)
        self.p.onset_threshold.setText('wrong');self.p.display_changed()
        self.assertNotIn('polarization_potentials.csv',self.w.state.exports)
        self.assertEqual(self.p.potential_table.rowCount(),0)
        with self.assertRaises((DataError,ValueError)):self.win.collect_project_inputs()
    def test_manual_window_and_markers_are_recorded_on_actual_plot(self):
        self.p.plateau_mode.setCurrentIndex(self.p.plateau_mode.findData('manual'))
        self.p.plateau_start.setText('.1');self.p.plateau_end.setText('.3');self.p.potential_markers.setChecked(True)
        result=self.p.calculate();self.assertEqual(result['potentials'].iloc[0].plateau_mode,'manual')
        self.assertGreaterEqual(len(result['figure'].axes[0].lines),4)
        self.assertIn('curves',self.w.state.results);self.assertNotIn('E_half_V',self.w.state.results)
    def test_inactive_bad_manual_bound_does_not_block_auto(self):
        self.p.plateau_mode.setCurrentIndex(self.p.plateau_mode.findData('manual'))
        self.p.plateau_start.setText('wrong');self.p.plateau_end.setText('.3')
        self.p.plateau_mode.setCurrentIndex(self.p.plateau_mode.findData('auto'))
        result=self.p.calculate();self.assertAlmostEqual(result['potentials'].iloc[0].E_half_V,.8,places=10)
