"""Independent plot/export agreement and scientific input isolation."""
from copy import deepcopy
from io import BytesIO
import json
import unittest
import numpy as np
import pandas as pd
from application.workspace import Workspace,State
from application.curves import calculate_curves
from application.results import complete_kl,complete_rrde,complete_data
from migration_fixtures import workspace
from orr_core import DataError,KOH_PRESET,rrde_calculate
from plot_smoothing import SMOOTH_MA


class NativeAnalysisServiceTests(unittest.TestCase):
    def setUp(self):
        traces,configs,settings=workspace();self.w=Workspace(State(traces=traces,configs=configs,settings=settings))
        self.ids=[i for i,c in configs.items() if c['role']!='背景']

    def test_smoothed_plot_csv_is_display_and_scientific_currents_stay_original(self):
        ident=self.ids[0];before,_=self.w.process_selected([ident]);raw=before[ident]['data'].copy()
        self.w.state.settings['plot']={'smoothing':{'enabled':True,'window_points':11}}
        result=calculate_curves(self.w,[ident]);frame=result['plotted'][ident]['data']
        np.testing.assert_array_equal(frame.I_disk_A,raw.I_disk_A)
        np.testing.assert_array_equal(frame.plotted_current_value,frame[SMOOTH_MA])
        wide=pd.read_csv(BytesIO(self.w.state.exports['polarization_plot.csv']['bytes']),float_precision='round_trip')
        np.testing.assert_array_equal(wide.iloc[:,1],frame.plotted_current_value)
        self.assertIn('smoothed',wide.columns[1])
        rrde=self.w.calculate_rrde([ident])['frames'][ident]
        pd.testing.assert_frame_equal(rrde,rrde_calculate(before[ident],before[ident]['config']))

    def test_preview_does_not_commit_pending_scientific_change(self):
        ident=self.ids[0];self.w.stage_config_updates('conditions',{ident:{'collection_efficiency':.4}})
        revision=self.w.state.revision;result=calculate_curves(self.w,[ident],commit=False)
        self.assertEqual(result['outputs'][ident]['config']['collection_efficiency'],.4)
        self.assertEqual(self.w.state.configs[ident]['collection_efficiency'],.369)
        self.assertTrue(self.w.has_draft());self.assertEqual(self.w.state.revision,revision)
        self.assertNotIn('polarization_plot.csv',self.w.state.exports)

    def test_ring_units_background_and_allowed_differences(self):
        self.w.state.configs[self.ids[0]]['ring_potential_V']=.8
        self.w.state.configs[self.ids[1]]['ring_potential_V']=1.0
        self.w.state.settings['ring_plot']={'unit':'uA','background_view':'处理后'}
        result=calculate_curves(self.w,self.ids[:2],'ring');self.assertTrue(result['comparison_audit']['allowed'])
        for output in result['plotted'].values():np.testing.assert_allclose(output['data'].plotted_current_value,output['data'].I_ring_A*1e6)
        self.w.state.settings['ring_plot']['background_view']='未扣背景'
        untreated=calculate_curves(self.w,self.ids[:2],'ring')
        for ident in self.ids[:2]:
            corrected=result['outputs'][ident]['data'].I_ring_A.to_numpy();uncorrected=untreated['outputs'][ident]['data'].I_ring_A.to_numpy()
            np.testing.assert_allclose(uncorrected-corrected,2e-7,rtol=1e-10)

    def test_ring_known_conflict_blocks_and_clears_old_exports(self):
        calculate_curves(self.w,self.ids[:2],'ring')
        for ident in self.ids[:2]:self.w.state.configs[ident].update(background_disk=None,background_ring=None)
        self.w.state.configs[self.ids[1]]['pH']=12.
        with self.assertRaisesRegex(DataError,'已知条件冲突'):calculate_curves(self.w,self.ids[:2],'ring')
        self.assertNotIn('ring_current_plot.csv',self.w.state.exports)

    def test_full_kl_exports_match_known_answer_and_audit_records(self):
        outputs,_=self.w.process_selected(self.ids[:3]);pot=outputs[self.ids[0]]['data'].E_V.iloc[[2,8]].to_numpy()
        args=dict(C=KOH_PRESET['C'],D=KOH_PRESET['D'],nu=KOH_PRESET['nu'],start=float(min(pot)),end=float(max(pot)),count=3,selected=self.ids[:3],confirmed=True,scheme='koh_25C')
        saved,figures=complete_kl(self.w,args);np.testing.assert_allclose(saved['data'].n_KL,3.2,rtol=1e-10)
        self.assertEqual(set(figures),{'kl_electron_number','kl_two_four_e_model','kl_fit'})
        for name in ('kl_plot.csv','kl_fit_plot.csv','kl_results.csv','kl_fit_points.csv','kl_parameters.json','kl_fit.png','kl_fit.svg'):self.assertIn(name,self.w.state.exports)
        record=json.loads(self.w.state.exports['kl_parameters.json']['bytes']);self.assertIn('stored_config',record['files'][0]);self.assertIn('analysis_kl',record)

    def test_full_rrde_exports_invalid_reasons_and_unsmoothed_snapshot(self):
        saved,figures=complete_rrde(self.w,self.ids)
        np.testing.assert_allclose(saved['frames'][self.ids[0]].n_RRDE,3.2,rtol=1e-12)
        np.testing.assert_allclose(saved['frames'][self.ids[0]].peroxide_pct,40.,rtol=1e-12)
        self.assertEqual(set(figures),{'rrde_selectivity','rrde_two_four_e'})
        self.assertFalse(saved['frames'][self.ids[-1]].valid_two_product_model.all())
        for name in ('rrde_plot.csv','rrde_results.csv','rrde_parameters.json','rrde_selectivity.svg','rrde_two_four_e.png'):self.assertIn(name,self.w.state.exports)
        record=json.loads(self.w.state.exports['rrde_parameters.json']['bytes']);self.assertIn('stored_config',record['files'][0])

    def test_invalid_style_or_missing_task_does_not_leave_old_plot_download(self):
        calculate_curves(self.w,self.ids[:1]);self.w.state.settings['plot']['xmin']=2;self.w.state.settings['plot']['xmax']=1
        with self.assertRaises(DataError):calculate_curves(self.w,self.ids[:1])
        self.assertNotIn('polarization.png',self.w.state.exports)

    def test_complete_data_partial_errors_are_explicit_and_parameters_include_snapshot(self):
        self.w.state.configs[self.ids[-1]]['disk_channel']=99
        outputs,errors=complete_data(self.w);self.assertEqual(len(outputs),8);self.assertEqual(len(errors),1)
        frame=pd.read_csv(BytesIO(self.w.state.exports['all_curves.csv']['bytes']))
        self.assertEqual(frame.file_id.nunique(),8)
        record=json.loads(self.w.state.exports['parameters.json']['bytes']);self.assertEqual(len(record['files']),10)

    def test_native_default_origin_table_matches_frozen_browser_baseline(self):
        from pathlib import Path
        from migration_fixtures import table
        from test_migration_baseline import MigrationBaselineTests
        expected=json.loads((Path(__file__).parent/'fixtures'/'migration_baseline.json').read_text(encoding='utf-8'))
        result=calculate_curves(self.w,self.ids)
        MigrationBaselineTests().compare(table(result['plot']),expected['curve_csv'])
