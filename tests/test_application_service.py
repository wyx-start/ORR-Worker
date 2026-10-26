"""Service contracts against frozen scientific inputs and actual transactions."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
import unittest
import numpy as np
import pandas as pd
from application.workspace import Workspace, State
from migration_fixtures import workspace, schema1_project
from orr_core import DataError, KOH_PRESET, rrde_calculate, unpack_project


class ApplicationServiceTests(unittest.TestCase):
    def setUp(self):
        traces, configs, settings = workspace()
        self.w = Workspace(State(traces=traces, configs=configs, settings=settings))
        self.ids = [i for i,c in configs.items() if c['role']!='背景']
        self.bg = next(i for i,c in configs.items() if c['role']=='背景')

    def test_service_imports_with_all_frontends_blocked(self):
        code = '''
import sys, importlib.abc
class NoUI(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('streamlit','PySide6','PyQt6'):
            raise RuntimeError('UI dependency: '+fullname)
sys.meta_path.insert(0,NoUI())
from application.workspace import Workspace
from application.figures import new_figure, figure_bytes
assert Workspace().state.revision == 0
assert figure_bytes(new_figure())[0].startswith(b'\\x89PNG')
'''
        result = subprocess.run([sys.executable,'-c',code],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_kl_known_answer_and_full_selection_failure(self):
        curves,_ = self.w.process_selected(self.ids[:3],channels='disk')
        potentials=curves[self.ids[0]]['data'].E_V.iloc[[2,8]].to_numpy()
        args=dict(C=KOH_PRESET['C'],D=KOH_PRESET['D'],nu=KOH_PRESET['nu'],start=float(potentials.min()),
            end=float(potentials.max()),count=3,selected=self.ids[:3],confirmed=True,scheme='koh_25C',source='synthetic')
        result=self.w.calculate_kl(args)
        np.testing.assert_allclose(result['data'].n_KL,3.2,rtol=1e-10)
        self.w.stage_config_updates('test',{self.ids[1]:{'disk_channel':99}})
        with self.assertRaises(DataError):self.w.calculate_kl(args)
        self.assertNotIn('kl',self.w.state.results)
        self.assertTrue(self.w.has_draft())

    def test_rrde_tables_and_invalid_rows_match_core(self):
        outputs,_=self.w.process_selected(self.ids)
        result=self.w.calculate_rrde(self.ids)
        for ident,frame in result['frames'].items():
            pd.testing.assert_frame_equal(frame,rrde_calculate(outputs[ident],outputs[ident]['config']))
        self.assertFalse(result['frames'][self.ids[-1]].valid_two_product_model.all())

    def test_project_roundtrip_keeps_independent_cache(self):
        payload=self.w.project_bytes();other=Workspace();other.restore_project(payload)
        self.assertEqual(other.state.configs,self.w.state.configs)
        self.assertEqual(other.get_draft_view()['records'][self.bg]['pH'],11.)
        self.assertEqual(other.get_draft_view()['configs'][self.bg]['pH'],13.)
        for ident,trace in other.state.traces.items():self.assertEqual(trace.raw,self.w.state.traces[ident].raw)

    def test_schema_one_unknown_is_not_replaced_by_defaults(self):
        configs=deepcopy(self.w.state.configs);configs[self.ids[0]]['pH']=None
        raw=schema1_project(self.w.state.traces,configs,self.w.state.settings)
        other=Workspace();other.restore_project(raw)
        self.assertIsNone(other.state.configs[self.ids[0]]['pH'])

    def test_bad_restore_and_preflight_are_atomic(self):
        before=deepcopy(self.w.state.configs)
        with self.assertRaises(Exception):self.w.restore_project(b'not a project')
        self.assertEqual(self.w.state.configs,before)
        self.w.stage_config_updates('conditions',{self.ids[0]:{'pH':12.}})
        def reject(*args):raise DataError('preflight')
        with self.assertRaises(DataError):self.w.apply_pending_settings(reject)
        self.assertEqual(self.w.state.configs,before);self.assertTrue(self.w.has_draft())

    def test_snapshot_mutation_cannot_change_live_records_or_raw_arrays(self):
        snap=self.w.snapshot();snap.state.configs[self.ids[0]]['pH']=0
        snap.state.traces[self.ids[0]].values[0,0]=99
        self.assertEqual(self.w.state.configs[self.ids[0]]['pH'],13.)
        self.assertNotEqual(self.w.state.traces[self.ids[0]].values[0,0],99)

    def test_bad_import_keeps_other_files_and_duplicate_does_not_invalidate(self):
        empty=Workspace();trace=self.w.state.traces[self.ids[0]]
        self.assertEqual(empty.add_files([('bad.txt',b'invalid'),(trace.name,trace.raw)]),1)
        self.assertEqual(len(empty.state.import_errors),1)
        rev=empty.state.revision
        self.assertEqual(empty.add_files([(trace.name,trace.raw)]),0)
        self.assertEqual(empty.state.revision,rev)
