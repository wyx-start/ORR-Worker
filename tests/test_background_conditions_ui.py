"""UI acceptance for background condition inheritance (synthetic records only)."""
import unittest

from streamlit.testing.v1 import AppTest


APP = '''
import numpy as np
import streamlit as st
from orr_core import Trace, default_config
from ui_shared import initialize, apply_settings_button, get_draft_view
from condition_ui import common_parameter_form
from settings_editor import background_conditions_panel
initialize()
if not st.session_state.traces:
    for name, role in [("sample_a", "样品"), ("sample_b", "样品"), ("ar_bg", "背景")]:
        trace = Trace(name+".txt", name.encode(), {}, ["Potential/V", "Current/A"],
                      np.array([[1., -.0001], [.5, -.0002], [0., -.0003]]), "utf-8", [])
        cfg = default_config(trace)
        cfg.update(group="group_one", role=role, electrolyte="electrolyte of "+name)
        st.session_state.traces[trace.id] = trace
        st.session_state.configs[trace.id] = cfg
    samples = [i for i, c in st.session_state.configs.items() if c["role"] == "样品"]
    background = next(i for i, c in st.session_state.configs.items() if c["role"] == "背景")
    for ident in samples:
        st.session_state.configs[ident].update(
            background_disk=background, pH=13., temperature_C=25., ref_V_SHE=.197,
            reference="Ag/AgCl", filling="饱和 KCl", reference_preset_C=25.,
            reference_source="synthetic reference record")
    st.session_state.configs[background].update(
        pH=11., temperature_C=20., ref_V_SHE=.110, reference="Independent reference",
        reference_preset_C=None,
        filling="independent filling", reference_source="independent reference record")
    st.session_state.configs[background]["parameter_sources"].update(
        pH="independent pH record", temperature_C="independent temperature record")
purpose = st.selectbox("Test purpose", ["curves", "kl"], key="test_purpose")
common_parameter_form(purpose=purpose)
background_conditions_panel([i for i, c in st.session_state.configs.items() if c["role"] == "背景"])
view = get_draft_view()
st.session_state.test_view = {"basis": view["view_basis"],
    "configs": view["configs"], "records": view["records"]}
apply_settings_button()
'''


def widget(elements, label):
    return next(element for element in elements if element.label == label)


def by_key(elements, fragment):
    return next(element for element in elements if fragment in (element.key or ""))


def frame_text(frame):
    return frame.value.to_csv(index=False)


class BackgroundConditionUiTests(unittest.TestCase):
    def app(self):
        at = AppTest.from_string(APP, default_timeout=30).run()
        self.assert_clean(at)
        return at

    def assert_clean(self, at):
        self.assertEqual(len(at.exception), 0, str([e.value for e in at.exception]))

    def ids(self, at):
        traces = list(at.session_state.traces)
        background = next(i for i in traces if at.session_state.configs[i]["role"] == "背景")
        samples = [i for i in traces if i != background]
        return samples[0], samples[1], background

    def select_source(self, at, ident):
        widget(at.selectbox, "读取设置的文件").set_value(ident).run()
        self.assert_clean(at)

    def test_follow_summary_shows_effective_and_preserves_independent_record(self):
        at = self.app()
        _, _, background = self.ids(at)
        frame = next(frame for frame in at.dataframe if "背景条件" in frame.value.columns)
        self.assertIn("整组跟随样品", frame_text(frame))
        self.assertIn("pH 13", frame_text(frame))
        self.assertEqual(at.session_state.configs[background]["pH"], 11.)
        effective = at.session_state.test_view["configs"][background]
        self.assertEqual(effective["pH"], 13.)
        states = effective["background_conditions"]["field_states"]
        self.assertTrue(all(not states[field]["editable"] for field in
                            ("potential_method", "pH", "ref_V_SHE", "rhe_offset_V")))

    def test_follow_background_fields_are_readonly_and_show_effective(self):
        at = self.app()
        _, _, background = self.ids(at)
        self.select_source(at, background)
        ph = widget(at.number_input, "pH *")
        self.assertTrue(ph.disabled)
        self.assertEqual(ph.value, 13.)
        self.assertTrue(widget(at.selectbox, "原始电位的换算方式 *").disabled)
        self.assertTrue(widget(at.selectbox, "参比方案 *").disabled)
        self.assertNotIn("电解液、浓度与气氛", [e.label for e in at.text_input])
        self.assertFalse(by_key(at.button, "adopt").disabled)
        # Read-only display never stages anything by itself.
        self.assertEqual(at.session_state.settings_draft["configs"], {})

    def test_waiting_and_conflict_states_keep_fields_readonly(self):
        at = self.app()
        first, second, background = self.ids(at)
        for ident in (first, second):
            at.session_state.configs[ident]["pH"] = None
        at.run()
        frame = next(frame for frame in at.dataframe if "背景条件" in frame.value.columns)
        self.assertIn("等待关联样品", frame_text(frame))
        self.select_source(at, background)
        self.assertTrue(widget(at.number_input, "pH *").disabled)
        self.assertTrue(by_key(at.button, "adopt").disabled)
        at.session_state.configs[first]["pH"] = 13.
        at.session_state.configs[second]["pH"] = 12.
        at.run()
        self.assert_clean(at)
        frame = next(frame for frame in at.dataframe if "背景条件" in frame.value.columns)
        self.assertIn("pH", frame_text(frame))
        self.assertIn("冲突", frame_text(frame))
        self.assertTrue(widget(at.number_input, "pH *").disabled)
        self.assertTrue(by_key(at.button, "adopt").disabled)
        self.assertEqual(at.session_state.configs[background]["pH"], 11.)

    def test_mode_switch_then_value_edit_share_one_domain(self):
        at = self.app()
        _, _, background = self.ids(at)
        self.select_source(at, background)
        by_key(at.button, "condition_scope").__class__  # sanity: scoped buttons exist
        by_key(at.button, "to_independent").click().run()
        self.assert_clean(at)
        domain = f"conditions:{background}"
        staged = at.session_state.settings_draft["configs"][domain][background]
        self.assertEqual(staged, {"background_conditions_mode": "independent"})
        ph = widget(at.number_input, "pH *")
        self.assertFalse(ph.disabled)
        self.assertEqual(ph.value, 11.)
        ph.set_value(12.).run()
        self.assert_clean(at)
        staged = at.session_state.settings_draft["configs"][domain][background]
        self.assertEqual(staged["background_conditions_mode"], "independent")
        self.assertEqual(staged["pH"], 12.)
        for other, files in at.session_state.settings_draft["configs"].items():
            if other != domain:
                self.assertNotIn(background, files)
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        record = at.session_state.configs[background]
        self.assertEqual(record["background_conditions_mode"], "independent")
        self.assertEqual(record["pH"], 12.)
        self.assertEqual(record["temperature_C"], 20.)
        self.assertEqual(record["ref_V_SHE"], .110)

    def test_follow_switch_drops_unapplied_independent_inputs_across_domains(self):
        at = self.app()
        _, _, background = self.ids(at)
        by_key(at.button, "bgcond").__class__
        by_key(at.button, "to_independent").click().run()
        widget(at.number_input, "背景 pH（允许 0）").set_value(9.).run()
        panel_domain = f"background_conditions:{background}"
        staged = at.session_state.settings_draft["configs"][panel_domain][background]
        self.assertEqual(staged["pH"], 9.)
        self.select_source(at, background)
        by_key(at.button, "to_follow").click().run()
        self.assert_clean(at)
        for files in at.session_state.settings_draft["configs"].values():
            self.assertNotIn(background, files)
        self.assertEqual(at.session_state.configs[background]["background_conditions_mode"], "follow")
        self.assertEqual(at.session_state.configs[background]["pH"], 11.)
        self.assertEqual(at.session_state.test_view["configs"][background]["pH"], 13.)

    def test_copy_effective_conditions_to_scope_including_background_eliminates_same_values(self):
        at = self.app()
        first, _, background = self.ids(at)
        self.select_source(at, background)
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([first, background]).run()
        widget(at.button, "复制当前条件到所选范围").click().run()
        self.assert_clean(at)
        domain = f"conditions:{background}"
        staged = at.session_state.settings_draft["configs"][domain]
        self.assertIn(first, staged)
        self.assertNotIn(background, staged)
        self.assertNotIn("electrolyte", staged[first])
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[first]["electrolyte"], "electrolyte of sample_a")
        self.assertEqual(at.session_state.configs[background]["pH"], 11.)
        self.assertEqual(at.session_state.configs[background]["background_conditions_mode"], "follow")

    def test_real_difference_write_to_follow_background_rejects_without_partial_staging(self):
        at = self.app()
        first, second, background = self.ids(at)
        self.select_source(at, first)
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([second, background]).run()
        widget(at.number_input, "pH *").set_value(14.).run()
        self.assertIn("跟随", at.session_state.draft_error)
        self.assertEqual(at.session_state.settings_draft["configs"], {})
        self.assertEqual(at.session_state["rejected_config_edits"]
                         if "rejected_config_edits" in at.session_state else {}, {})
        self.assertIn(f"conditions:{first}", at.session_state.draft_errors)

    def test_removed_presets_cannot_write_followed_background(self):
        from condition_ui import condition_updates
        from orr_core import DataError
        at = self.app()
        first, _, background = self.ids(at)
        self.select_source(at, background)
        self.assertNotIn("选择常用条件", [e.label for e in at.selectbox])
        view = {"records":at.session_state.test_view["records"],
                "configs":at.session_state.test_view["configs"], "view_basis":"applied"}
        with self.assertRaises(DataError):
            condition_updates(view, [first, background], {"pH":7.}, source="旧项目预设")
        self.assertEqual(at.session_state.settings_draft["configs"], {})

    def test_backend_snapshot_from_follow_background_uses_effective_view(self):
        from experiment_conditions import snapshot_conditions
        at = self.app()
        _, _, background = self.ids(at)
        self.select_source(at, background)
        saved = snapshot_conditions(at.session_state.test_view["configs"][background])
        self.assertEqual(saved["pH"], 13.)
        self.assertEqual(saved["temperature_C"], 25.)
        self.assertEqual(at.session_state.configs[background]["pH"], 11.)
        self.assertNotIn("配置名称（选填）", [e.label for e in at.text_input])
    def test_area_repair_survives_scope_switch_under_applied_fallback(self):
        at = self.app()
        first, second, _ = self.ids(at)
        for ident in (first, second):
            at.session_state.configs[ident].update(area_cm2=-1., area_mode="area", disk_diameter_mm=None)
        at.run()
        widget(at.selectbox, "Test purpose").set_value("kl").run()
        self.assertIsNone(widget(at.number_input, "盘几何面积 / cm² *").value)
        widget(at.segmented_control, "应用范围").set_value("仅此文件").run()
        widget(at.number_input, "盘几何面积 / cm² *").set_value(.25).run()
        self.assertEqual(at.session_state.test_view["basis"], "applied_fallback")
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([first, second]).run()
        self.assert_clean(at)
        self.assertEqual(widget(at.number_input, "盘几何面积 / cm² *").value, .25)
        widget(at.button, "复制当前条件到所选范围").click().run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[first]["area_cm2"], .25)
        self.assertEqual(at.session_state.configs[second]["area_cm2"], .25)

    def test_legacy_panel_keeps_labels_and_upgrades_to_full_follow(self):
        at = self.app()
        _, _, background = self.ids(at)
        at.session_state.configs[background].update(
            background_conditions_mode="legacy_ph", background_ph_mode="manual",
            background_ph_legacy=False)
        at.run()
        self.assert_clean(at)
        mode = widget(at.selectbox, "背景 pH 模式")
        self.assertEqual(mode.value, "独立填写")
        by_key(at.button, "bgph").__class__
        by_key(at.button, "to_follow").click().run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        record = at.session_state.configs[background]
        self.assertEqual(record["background_conditions_mode"], "follow")
        self.assertEqual(record["pH"], 11.)
        self.assertEqual(at.session_state.test_view["configs"][background]["pH"], 13.)

    def test_independent_background_direct_edit_accepts_zero(self):
        at = self.app()
        _, _, background = self.ids(at)
        at.session_state.configs[background]["background_conditions_mode"] = "independent"
        at.run()
        self.assert_clean(at)
        panel_input = widget(at.number_input, "背景 pH（允许 0）")
        self.assertEqual(panel_input.value, 11.)
        panel_input.set_value(0.).run()
        self.assert_clean(at)
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[background]["pH"], 0.)
        self.assertEqual(at.session_state.configs[background]["parameter_sources"]["pH"],
                         "人工独立设置背景条件")
        self.select_source(at, background)
        self.assertFalse(widget(at.number_input, "pH *").disabled)


if __name__ == "__main__":
    unittest.main()
