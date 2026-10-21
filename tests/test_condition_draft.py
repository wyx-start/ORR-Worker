"""Regression checks for condition editing scopes and shared, explicit apply."""
import copy
import unittest

from streamlit.testing.v1 import AppTest


APP = '''
import numpy as np
import streamlit as st
from orr_core import Trace, default_config
from ui_shared import initialize, apply_settings_button, get_draft_configs
from condition_ui import common_parameter_form
initialize()
if not st.session_state.traces:
    for name, group in [("sample_a", "group_one"), ("sample_b", "group_one"), ("sample_c", "group_two")]:
        trace = Trace(name+".txt", name.encode(), {}, ["Potential/V", "Current/A"],
                      np.array([[1., -.0001], [.5, -.0002], [0., -.0003]]), "utf-8", [])
        cfg = default_config(trace)
        cfg.update(group=group, electrolyte="source electrolyte" if name == "sample_a" else "other electrolyte")
        st.session_state.traces[trace.id] = trace
        st.session_state.configs[trace.id] = cfg
    st.session_state.settings["presets"] = {"test preset": {"pH":12., "electrolyte":"preset electrolyte"}}
purpose = st.selectbox("Test purpose", ["curves", "rrde", "kl"], key="test_purpose")
common_parameter_form(purpose=purpose)
st.session_state.test_candidate = get_draft_configs()
apply_settings_button()
'''


def widget(elements, label):
    return next(element for element in elements if element.label == label)


class ConditionDraftTests(unittest.TestCase):
    def app(self):
        at = AppTest.from_string(APP, default_timeout=30).run()
        self.assert_clean(at)
        return at

    def assert_clean(self, at):
        self.assertEqual(len(at.exception), 0, str([e.value for e in at.exception]))

    def ids(self, at):
        return list(at.session_state.traces)

    def test_edit_is_group_scoped_and_commits_only_at_shared_apply(self):
        at = self.app()
        first, second, third = self.ids(at)
        self.assertFalse(at.session_state.settings_draft["configs"])
        widget(at.number_input, "pH *").set_value(13.).run()
        self.assert_clean(at)
        self.assertIsNone(at.session_state.configs[first]["pH"])
        self.assertIsNone(at.session_state.configs[second]["pH"])
        self.assertEqual(at.session_state.test_candidate[first]["pH"], 13.)
        self.assertEqual(at.session_state.test_candidate[second]["pH"], 13.)
        self.assertEqual(at.session_state.test_candidate[second]["electrolyte"], "source electrolyte")
        self.assertIsNone(at.session_state.test_candidate[third]["pH"])
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[second]["pH"], 13.)
        self.assertIsNone(at.session_state.configs[third]["pH"])

    def test_source_and_target_switches_do_not_copy_old_inputs(self):
        at = self.app()
        first, second, third = self.ids(at)
        widget(at.number_input, "pH *").set_value(13.).run()
        before = copy.deepcopy(at.session_state.settings_draft)
        widget(at.selectbox, "读取设置的文件").set_value(third).run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.settings_draft, before)
        self.assertIsNone(widget(at.number_input, "pH *").value)
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([first]).run()
        self.assertEqual(at.session_state.settings_draft, before)
        self.assertIsNone(at.session_state.test_candidate[third]["pH"])
        widget(at.number_input, "pH *").set_value(11.).run()
        self.assert_clean(at)
        # A different source must report a conflicting edit, not override it.
        self.assertIn("矛盾", at.session_state.draft_error)
        self.assertEqual(at.session_state.test_candidate[first]["pH"], 13.)

    def test_explicit_copy_keeps_unchanged_source_and_discard_clears_out_of_source_view(self):
        at = self.app()
        first, second, third = self.ids(at)
        widget(at.button, "复制当前条件到所选范围").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.test_candidate[second]["electrolyte"], "source electrolyte")
        self.assertEqual(at.session_state.configs[second]["electrolyte"], "other electrolyte")
        widget(at.button, "放弃未应用修改").click().run()
        self.assertEqual(at.session_state.test_candidate[second]["electrolyte"], "other electrolyte")
        widget(at.selectbox, "读取设置的文件").set_value(third).run()
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([first]).run()
        widget(at.number_input, "pH *").set_value(11.).run()
        self.assertEqual(at.session_state.test_candidate[first]["pH"], 11.)
        self.assertIsNone(at.session_state.test_candidate[third]["pH"])
        widget(at.button, "放弃未应用修改").click().run()
        self.assert_clean(at)
        self.assertIsNone(widget(at.number_input, "pH *").value)
        self.assertIsNone(at.session_state.test_candidate[first]["pH"])

    def test_profile_then_manual_edit_is_one_draft_and_uses_one_save_entry(self):
        at = self.app()
        first, second, _ = self.ids(at)
        widget(at.selectbox, "选择常用条件").set_value("项目 · test preset").run()
        widget(at.button, "载入预设到草稿").click().run()
        self.assert_clean(at)
        self.assertEqual(widget(at.number_input, "pH *").value, 12.)
        self.assertIsNone(at.session_state.configs[first]["pH"])
        widget(at.number_input, "pH *").set_value(14.).run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.test_candidate[first]["pH"], 14.)
        self.assertEqual(at.session_state.test_candidate[second]["pH"], 14.)
        widget(at.text_input, "配置名称（选填）").set_value("edited preset").run()
        widget(at.button, "应用并保存预设").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[first]["pH"], 14.)
        self.assertEqual(at.session_state.settings["presets"]["edited preset"]["pH"], 14.)
        self.assertNotIn("保存到当前项目", [e.label for e in at.button])
        self.assertNotIn("设为本机常用条件", [e.label for e in at.button])

    def test_profile_template_remains_visible_when_source_is_not_a_target(self):
        at = self.app()
        first, second, _ = self.ids(at)
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([second]).run()
        widget(at.selectbox, "选择常用条件").set_value("项目 · test preset").run()
        widget(at.button, "载入预设到草稿").click().run()
        self.assert_clean(at)
        self.assertIsNone(at.session_state.test_candidate[first]["pH"])
        self.assertEqual(at.session_state.test_candidate[second]["pH"], 12.)
        self.assertEqual(widget(at.number_input, "pH *").value, 12.)
        widget(at.number_input, "pH *").set_value(14.).run()
        self.assert_clean(at)
        self.assertIsNone(at.session_state.test_candidate[first]["pH"])
        self.assertEqual(at.session_state.test_candidate[second]["pH"], 14.)

    def test_hidden_method_values_and_zero_offset_survive_shared_apply(self):
        at = self.app()
        first, second, _ = self.ids(at)
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        widget(at.selectbox, "原始电位的换算方式 *").set_value("实测 RHE 总偏移").run()
        widget(at.number_input, "实测 RHE 总偏移 / V *").set_value(0.).run()
        widget(at.selectbox, "原始电位的换算方式 *").set_value("已是 RHE").run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        for ident in (first, second):
            cfg = at.session_state.configs[ident]
            self.assertEqual(cfg["pH"], 13.)
            self.assertEqual(cfg["ref_V_SHE"], .197)
            self.assertEqual(cfg["rhe_offset_V"], 0.)
            self.assertEqual(cfg["potential_method"], "已是 RHE")

    def test_invalid_local_input_stays_blocking_until_same_editor_corrects_it(self):
        at = self.app()
        first, _, _ = self.ids(at)
        # An incomplete legacy geometry can be viewed and repaired, but copying
        # it must register a persistent local validation failure.
        at.session_state.configs[first].update(disk_diameter_mm=None, area_cm2=None)
        widget(at.selectbox, "Test purpose").set_value("kl").run()
        widget(at.button, "复制当前条件到所选范围").click().run()
        self.assert_clean(at)
        self.assertIn("盘直径", at.session_state.draft_error)
        widget(at.button, "应用设置").click().run()
        self.assertIsNone(at.session_state.configs[first]["disk_diameter_mm"])
        widget(at.selectbox, "Test purpose").set_value("curves").run()
        self.assertIn("盘直径", at.session_state.draft_error)
        widget(at.selectbox, "Test purpose").set_value("kl").run()
        widget(at.number_input, "盘直径 / mm *").set_value(5.).run()
        self.assert_clean(at)
        self.assertNotIn("draft_error", at.session_state)


if __name__ == "__main__":
    unittest.main()
