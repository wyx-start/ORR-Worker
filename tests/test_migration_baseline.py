"""Frozen pre-rewrite scientific and project-contract oracle."""
import json
import math
from pathlib import Path
import unittest

import numpy as np
from migration_fixtures import snapshot,workspace
from orr_core import KOH_PRESET,kl_calculate,process_trace


class MigrationBaselineTests(unittest.TestCase):
    def compare(self,actual,expected,path="root"):
        if isinstance(expected,dict):
            self.assertEqual(set(actual),set(expected),path)
            for key,value in expected.items():
                self.compare(actual[key],value,path+"."+key)
        elif isinstance(expected,list):
            self.assertEqual(len(actual),len(expected),path)
            for index,(a,b) in enumerate(zip(actual,expected)):
                self.compare(a,b,path+f"[{index}]")
        elif isinstance(expected,(int,float)) and not isinstance(expected,bool):
            self.assertTrue(isinstance(actual,(int,float)) and math.isclose(actual,expected,rel_tol=1e-11,abs_tol=1e-14),f"{path}: {actual} != {expected}")
        else:
            self.assertEqual(actual,expected,path)

    def test_frozen_outputs_and_project_contracts(self):
        expected = json.loads((Path(__file__).parent/"fixtures"/"migration_baseline.json").read_text(encoding="utf-8"))
        self.compare(snapshot(),expected)

    def test_independent_known_answer_is_not_only_a_snapshot(self):
        traces,records,settings = workspace()
        ids = [i for i,c in records.items() if c["role"] != "背景"][:3]
        curves = [process_trace(traces[i],records[i],traces,records,"RHE") for i in ids]
        potentials = curves[0]["data"].E_V.iloc[[2,5,8]].to_numpy()
        result,_ = kl_calculate(curves,potentials,*(KOH_PRESET[k] for k in ("C","D","nu")))
        np.testing.assert_allclose(result.n_KL,3.2,rtol=1e-10)
