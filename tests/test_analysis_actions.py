from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest

from orr_core import default_config, parse_chi
from settings_draft import new_draft, stage_config


ROOT = Path(__file__).resolve().parents[1]


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def fixture(rpm, *, ring=False, efficiency=.37):
    current = -1e-4 * (rpm / 400.) ** .5
    rows = "\n".join(f"{e:.4f},{current:.12g}"+(",0.000004" if ring else "")
                     for e in np.linspace(.8, .2, 31))
    header = ("Linear Sweep Voltammetry\nHigh E (V) = 0.8\nLow E (V) = 0.2\n"
              "Scan Rate (V/s) = 0.005\nSample Interval (V) = 0.02\n"
              + ("Potential/V,i1/A,i2/A\n" if ring else "Potential/V,Current/A\n"))
    trace = parse_chi(f"synthetic-{rpm}rpm.txt", (header+rows).encode())
    cfg = default_config(trace)
    cfg.update(group="synthetic", manual_segment=1, pH=13., ref_V_SHE=.197,
               reference="Ag/AgCl", filling="sat KCl", electrolyte="synthetic only",
               collection_efficiency=efficiency, ring_detection_confirmed=True)
    return trace, cfg


def app(page, fixtures):
    source = ("import runpy\nfrom ui_shared import initialize\ninitialize()\n"
              f"runpy.run_path({str(ROOT/'app_pages'/page)!r})")
    at = AppTest.from_string(source, default_timeout=30)
    at.session_state.traces = {trace.id: trace for trace, _ in fixtures}
    at.session_state.configs = {trace.id: cfg for trace, cfg in fixtures}
    at.session_state.settings = {"axis": "RHE", "kl": {}, "rrde": {}, "plot": {}, "presets": {}}
    at.session_state.revision = 0
    return at.run()


def kl_inputs(at):
    widget(at.number_input, "氧浓度 C / mol·cm⁻³ *").set_value(1.2e-6)
    widget(at.number_input, "扩散系数 D / cm²·s⁻¹ *").set_value(1.9e-5)
    widget(at.number_input, "运动黏度 ν / cm²·s⁻¹ *").set_value(.01)
    widget(at.checkbox, "已核对：各文件属于同一电极和相同实验条件，以上物性参数适用").check()


class AnalysisActionTests(unittest.TestCase):
    def assert_clean(self, at):
        self.assertEqual(len(at.exception), 0, str([element.value for element in at.exception]))

    def test_kl_native_compute_reads_latest_inputs(self):
        at = app("kl.py", [fixture(400), fixture(900)])
        self.assert_clean(at)
        self.assertNotIn("kl", at.session_state.results)
        kl_inputs(at)
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        saved = at.session_state.results["kl"]
        self.assertEqual(saved["params"]["C"], 1.2e-6)
        self.assertEqual(saved["params"]["axis"], "RHE")
        self.assertEqual(len(saved["outputs"]), 2)
        self.assertIn("kl_plot.csv", at.session_state.exports)
        table = pd.read_csv(BytesIO(at.session_state.exports["kl_plot.csv"]["bytes"]))
        self.assertEqual(list(table.columns), ["E_RHE_V", "n_KL", "two_e_pct_model", "four_e_pct_model"])
        selection = widget(at.multiselect, "参与拟合的文件（每个转速一条）")
        selection.set_value(selection.value[:1]).run()
        self.assert_clean(at)
        self.assertNotIn("kl", at.session_state.results)
        self.assertFalse(any(name.startswith("kl_") for name in at.session_state.exports))

    def test_kl_failed_selected_file_keeps_draft_and_does_not_drop_speed(self):
        fixtures = [fixture(400), fixture(900)]
        at = app("kl.py", fixtures)
        kl_inputs(at)
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        ident = fixtures[0][0].id
        draft = new_draft(at.session_state.revision)
        stage_config(draft, "test", ident, {"pH": None})
        at.session_state.settings_draft = draft
        at.run()
        widget(at.button, "应用并计算 K–L").click().run()
        self.assert_clean(at)
        self.assertNotIn("kl", at.session_state.results)
        self.assertFalse(any(name.startswith("kl_") for name in at.session_state.exports))
        self.assertEqual(at.session_state.configs[ident]["pH"], 13.)
        self.assertTrue(at.session_state.settings_draft["configs"])
        self.assertTrue(any("不能跳过某个转速" in item.value for item in at.error))

    def test_rrde_requires_explicit_calculation_and_combines_pending_N(self):
        fixtures = [fixture(400, ring=True, efficiency=None)]
        at = app("rrde.py", fixtures)
        self.assert_clean(at)
        self.assertNotIn("rrde", at.session_state.results)
        ident = fixtures[0][0].id
        draft = new_draft(at.session_state.revision)
        stage_config(draft, "test", ident, {"collection_efficiency": .4})
        at.session_state.settings_draft = draft
        at.run()
        widget(at.button, "应用并计算 RRDE").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[ident]["collection_efficiency"], .4)
        self.assertEqual(at.session_state.results["rrde"]["revision"], at.session_state.revision)
        self.assertEqual(at.session_state.results["rrde"]["plot"].shape[1], 4)

    def test_rrde_partial_failure_keeps_usable_file_and_names_failed_file(self):
        fixtures = [fixture(400, ring=True), fixture(900, ring=True, efficiency=None)]
        at = app("rrde.py", fixtures)
        widget(at.button, "计算 RRDE").click().run()
        self.assert_clean(at)
        result = at.session_state.results["rrde"]
        self.assertEqual(set(result["outputs"]), {fixtures[0][0].id})
        self.assertEqual(result["errors"][0]["文件"], fixtures[1][0].name)
        self.assertIn("收集效率", result["errors"][0]["原因"])
        widget(at.multiselect, "RRDE 文件").set_value([]).run()
        self.assert_clean(at)
        self.assertNotIn("rrde", at.session_state.results)
        self.assertFalse(any(name.startswith("rrde_") for name in at.session_state.exports))

    def test_rrde_analysis_input_change_removes_previous_downloads(self):
        at = app("rrde.py", [fixture(400, ring=True)])
        widget(at.button, "计算 RRDE").click().run()
        self.assert_clean(at)
        self.assertIn("rrde_plot.csv", at.session_state.exports)
        at.session_state.settings["rrde"] = dict((at.session_state.settings["rrde"] if "rrde" in at.session_state.settings else {}), floor_A=2e-9)
        at.run()
        self.assert_clean(at)
        self.assertNotIn("rrde", at.session_state.results)
        self.assertFalse(any(name.startswith("rrde_") for name in at.session_state.exports))

    def test_rrde_one_click_export_computes_from_latest_pending_settings(self):
        fixtures = [fixture(400, ring=True)]
        at = app("rrde.py", fixtures)
        ident = fixtures[0][0].id
        draft = new_draft(at.session_state.revision)
        stage_config(draft, "test", ident, {"collection_efficiency": .5})
        at.session_state.settings_draft = draft
        at.run()
        with patch("download_ui.send_download") as download:
            widget(at.button, "应用并导出绘图 CSV").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[ident]["collection_efficiency"], .5)
        self.assertEqual(download.call_count, 1)
        payload, name, mime = download.call_args.args
        self.assertEqual((name, mime), ("rrde_plot.csv", "text/csv"))
        table = pd.read_csv(BytesIO(payload))
        np.testing.assert_allclose(table.iloc[:, 1], 200*(4e-6/.5)/(1e-4+4e-6/.5))
        self.assertEqual(at.session_state.exports[name]["bytes"], payload)

    def restore_settings(self, at, settings):
        # The real restore handler replaces settings and changes workspace_epoch
        # before invalidating scientific outputs and the shared settings draft.
        at.session_state.settings = settings
        at.session_state.workspace_epoch += 1
        at.session_state.revision += 1
        at.session_state.draft_epoch += 1
        at.session_state.settings_draft = new_draft(at.session_state.revision)
        at.session_state.results = {}
        at.session_state.exports = {}
        at.run()

    def test_project_restore_uses_saved_kl_inputs_instead_of_previous_widgets(self):
        at = app("kl.py", [fixture(400), fixture(900)])
        kl_inputs(at)
        widget(at.button, "计算 K–L").click().run()
        restored = dict(at.session_state.settings)
        restored["kl"] = dict(restored["kl"], C=5e-6, count=9, start=1.4, end=1.6)
        self.restore_settings(at, restored)
        self.assert_clean(at)
        self.assertEqual(widget(at.number_input, "氧浓度 C / mol·cm⁻³ *").value, 5e-6)
        self.assertEqual(widget(at.number_input, "等间距电位点数").value, 9)
        self.assertEqual(widget(at.number_input, "分析起点 / V").value, 1.4)
        self.assertEqual(widget(at.number_input, "分析终点 / V").value, 1.6)

    def test_project_restore_uses_saved_rrde_threshold(self):
        at = app("rrde.py", [fixture(400, ring=True)])
        at.session_state.settings["rrde"] = dict((at.session_state.settings["rrde"] if "rrde" in at.session_state.settings else {}), floor_A=2e-9)
        at.run()
        restored = dict(at.session_state.settings)
        restored["rrde"] = {"floor_A": 8e-9}
        self.restore_settings(at, restored)
        self.assert_clean(at)
        self.assertNotIn("最小盘还原电流幅值 / A", [e.label for e in at.number_input])
        widget(at.button, "计算 RRDE").click().run()
        self.assertEqual(at.session_state.results["rrde"]["inputs"]["floor_A"], 8e-9)
        self.assertEqual(at.session_state.results["rrde"]["params"]["settings"]["rrde"]["floor_A"], 8e-9)

    def test_invalid_saved_rrde_threshold_reports_error_without_old_downloads(self):
        at = app("rrde.py", [fixture(400, ring=True)])
        widget(at.button, "计算 RRDE").click().run()
        self.assertIn("rrde", at.session_state.results)
        at.session_state.settings["rrde"]["floor_A"] = -1.
        at.run()
        widget(at.button, "计算 RRDE").click().run()
        self.assert_clean(at)
        self.assertTrue(any("最小盘电流幅值" in e.value for e in at.error))
        self.assertNotIn("rrde", at.session_state.results)
        self.assertFalse(any(name.startswith("rrde_") for name in at.session_state.exports))

    def test_kl_electrolyte_difference_has_targeted_repair_and_keeps_other_records(self):
        fixtures = [fixture(400), fixture(900)]
        fixtures[0][1]["electrolyte"] = "electrolyte A"
        fixtures[1][1]["electrolyte"] = "electrolyte B"
        at = app("kl.py", fixtures)
        self.assertIn("修正阻断计算的电解液差异", [e.label for e in at.expander])
        before = {i:cfg["pH"] for i,cfg in at.session_state.configs.items()}
        widget(at.text_input, "实际电解液与气氛记录").set_value("verified electrolyte").run()
        widget(at.button, "将电解液修正加入草稿").click().run()
        at.run()
        self.assertEqual(at.session_state.configs[fixtures[0][0].id]["electrolyte"], "electrolyte A")
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        for ident,cfg in at.session_state.configs.items():
            self.assertEqual(cfg["electrolyte"], "verified electrolyte")
            self.assertEqual(cfg["pH"], before[ident])

    def test_kl_already_rhe_in_original_mode_exports_correct_coordinate_without_shift(self):
        fixtures = [fixture(400), fixture(900)]
        for _, cfg in fixtures:
            cfg["potential_method"] = "已是 RHE"
        at = app("kl.py", fixtures)
        at.session_state.settings["axis"] = "原始"
        at.run()
        kl_inputs(at)
        # Keep the actual analysis interval inside the unshifted input data.
        widget(at.number_input, "分析起点 / V").set_value(.3)
        widget(at.number_input, "分析终点 / V").set_value(.7)
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        saved = at.session_state.results["kl"]
        self.assertEqual(saved["params"]["axis"], "原始")
        plot = pd.read_csv(BytesIO(at.session_state.exports["kl_plot.csv"]["bytes"]))
        self.assertEqual(plot.columns[0], "E_RHE_V")
        np.testing.assert_allclose(plot.iloc[:, 0], saved["data"].E_V, rtol=0, atol=1e-15)
        np.testing.assert_allclose(saved["data"].E_V.iloc[[0, -1]], [.3, .7], rtol=0, atol=1e-15)
        fit = pd.read_csv(BytesIO(at.session_state.exports["kl_fit_plot.csv"]["bytes"]))
        self.assertTrue(all("E_RHE_V=" in column for column in fit.columns))
        np.testing.assert_allclose(fit.iloc[:, 0], saved["points"].omega_inv_sqrt.iloc[:2])


if __name__ == "__main__":
    unittest.main()
