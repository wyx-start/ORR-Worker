"""Actual Streamlit controls: defaults, atomic bulk edits and blank numeric rpm."""
from copy import deepcopy
from pathlib import Path
import unittest

from streamlit.testing.v1 import AppTest
from orr_core import default_config, parse_chi
from test_background_conditions_draft import fixtures

ROOT = Path(__file__).resolve().parents[1]

APP = '''
import streamlit as st
from ui_shared import initialize, apply_settings_button, get_draft_view
from test_background_conditions_draft import fixtures
from condition_ui import common_parameter_form
from settings_editor import batch_scan_background_form, per_file_form
initialize()
if not st.session_state.traces:
    traces, records, settings, ids = fixtures()
    st.session_state.traces = traces
    st.session_state.configs = records
    st.session_state.settings = dict(settings, axis="原始")
page = st.selectbox("测试页面", ["RRDE", "批量"])
if page == "RRDE":
    common_parameter_form(purpose="rrde", expanded=True)
else:
    batch_scan_background_form()
    per_file_form()
st.session_state.test_view = get_draft_view()
apply_settings_button()
'''


def widget(elements, label):
    return next(e for e in elements if e.label == label)


class SimplifiedControlsTests(unittest.TestCase):
    def app(self):
        at = AppTest.from_string(APP, default_timeout=30).run()
        self.clean(at)
        return at

    def clean(self, at):
        self.assertEqual(len(at.exception), 0, str([e.value for e in at.exception]))

    def ids(self, at):
        return [i for i,c in at.session_state.configs.items() if c["role"] != "背景"]

    def test_old_empty_n_offered_in_draft_and_other_values_preserved(self):
        at = self.app()
        a, b = self.ids(at)
        at.session_state.configs[a]["collection_efficiency"] = None
        at.session_state.configs[b]["collection_efficiency"] = .4
        at.session_state.revision += 1
        at.session_state.settings_draft["base_revision"] = at.session_state.revision
        at.run()
        self.clean(at)
        self.assertEqual(widget(at.number_input, "RRDE 收集效率 N（0–1） *").value, .369)
        self.assertIsNone(at.session_state.configs[a]["collection_efficiency"])
        cfg = at.session_state.test_view["records"]
        self.assertEqual(cfg[a]["collection_efficiency"], .369)
        self.assertEqual(cfg[b]["collection_efficiency"], .4)
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[a]["collection_efficiency"], .369)
        self.assertEqual(at.session_state.configs[b]["collection_efficiency"], .4)
        self.assertIn("软件默认", at.session_state.configs[a]["parameter_sources"]["collection_efficiency"])
        self.assertFalse(at.session_state.configs[a]["ring_detection_confirmed"])
        at.session_state.settings["axis"] = "RHE"
        at.run()
        widget(at.number_input, "pH *").set_value(14.).run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[b]["collection_efficiency"], .4)

    def test_n_edit_applies_actual_value_and_keeps_hidden_records(self):
        at = self.app()
        before = {i:c["electrolyte"] for i,c in at.session_state.configs.items()}
        widget(at.number_input, "RRDE 收集效率 N（0–1） *").set_value(.4).run()
        widget(at.button, "应用设置").click().run()
        self.clean(at)
        for i in self.ids(at):
            self.assertEqual(at.session_state.configs[i]["collection_efficiency"], .4)
        self.assertEqual(before, {i:c["electrolyte"] for i,c in at.session_state.configs.items()})
        labels = [e.label for e in at.expander]
        self.assertNotIn("补充实验记录（选填）", labels)
        self.assertNotIn("常用条件：保存与复用", labels)

    def test_invalid_saved_n_is_not_silently_defaulted(self):
        at = self.app()
        a, _ = self.ids(at)
        at.session_state.configs[a]["collection_efficiency"] = 37.
        at.run()
        self.clean(at)
        self.assertIsNone(widget(at.number_input, "RRDE 收集效率 N（0–1） *").value)
        self.assertEqual(at.session_state.configs[a]["collection_efficiency"], 37.)

    def test_batch_preview_stage_and_one_apply(self):
        at = self.app()
        widget(at.selectbox, "测试页面").set_value("批量").run()
        before = deepcopy(dict(at.session_state.configs))
        widget(at.selectbox, "批量自动选择规则").set_value("B").run()
        self.assertEqual(dict(at.session_state.configs), before)
        widget(at.button, "加入本批草稿").click().run()
        self.assertEqual(dict(at.session_state.configs), before)
        self.assertTrue(any("清除" in w.value for w in at.warning))
        widget(at.button, "应用设置").click().run()
        self.clean(at)
        for i in self.ids(at):
            self.assertEqual(at.session_state.configs[i]["mode"], "B")
            self.assertIsNone(at.session_state.configs[i]["manual_segment"])
            self.assertEqual(at.session_state.configs[i]["rpm"], before[i]["rpm"])
        bg = next(i for i,c in before.items() if c["role"] == "背景")
        self.assertEqual(at.session_state.configs[bg], before[bg])

    def test_custom_background_target_rejects_binding_all_targets(self):
        at = self.app()
        widget(at.selectbox, "测试页面").set_value("批量").run()
        widget(at.segmented_control, "批量应用范围").set_value("自选").run()
        widget(at.multiselect, "批量目标文件").set_value(list(at.session_state.configs)).run()
        widget(at.selectbox, "批量背景操作").set_value("none").run()
        widget(at.button, "加入本批草稿").click().run()
        self.clean(at)
        self.assertIn("背景文件只能", at.session_state.draft_error)
        self.assertEqual(at.session_state.settings_draft["configs"], {})

    def test_keep_operation_does_not_clear_previously_staged_batch(self):
        at = self.app()
        widget(at.selectbox, "测试页面").set_value("批量").run()
        widget(at.selectbox, "批量自动选择规则").set_value("B").run()
        widget(at.button, "加入本批草稿").click().run()
        before = deepcopy(at.session_state.settings_draft)
        widget(at.selectbox, "批量自动选择规则").set_value("保持").run()
        widget(at.button, "加入本批草稿").click().run()
        self.clean(at)
        self.assertEqual(at.session_state.settings_draft, before)

    def import_app(self, names):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        original = next(iter(fixtures()[0].values())).raw
        traces = [parse_chi(name, original) for name in names]
        at.session_state.traces = {t.id:t for t in traces}
        at.session_state.configs = {t.id:default_config(t) for t in traces}
        at.run()
        return at, traces

    def edit_rpms(self, at, values):
        key = f"metadata_{at.session_state.revision}_{at.session_state.draft_epoch}"
        at.session_state[key] = {"edited_rows":{i:{"转速/rpm":v} for i,v in values.items()}, "added_rows":[], "deleted_rows":[]}
        at.run()
        self.clean(at)

    def test_all_unknown_rpm_column_is_editable_numeric_and_applies(self):
        at, traces = self.import_app(["unmarked-a.txt", "unmarked-b.txt"])
        frame = next(e.value for e in at.dataframe if "转速/rpm" in e.value.columns)
        self.assertEqual(frame["转速/rpm"].dtype.kind, "f")
        self.edit_rpms(at, {0:1600., 1:900.})
        self.assertIsNone(at.session_state.configs[traces[0].id]["rpm"])
        widget(at.button, "应用设置").click().run()
        self.clean(at)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm"], 1600.)
        self.assertEqual(at.session_state.configs[traces[1].id]["rpm_source"], "manual")

    def test_conflict_and_recognized_rpm_are_both_manually_editable(self):
        at, traces = self.import_app(["conflict-900rpm-1600rpm.txt", "sample-1600rpm.txt"])
        self.edit_rpms(at, {0:900., 1:1200.})
        widget(at.button, "应用设置").click().run()
        self.clean(at)
        self.assertEqual([at.session_state.configs[t.id]["rpm"] for t in traces], [900.,1200.])
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm_candidates"], [900,1600])

    def test_negative_rpm_rejects_whole_table_and_preserves_input(self):
        at, traces = self.import_app(["a-900rpm.txt", "b-1600rpm.txt"])
        self.edit_rpms(at, {0:1200., 1:-1.})
        self.assertIn("不能为负", at.session_state.draft_error)
        self.assertEqual(at.session_state.settings_draft["configs"], {})
        self.assertEqual([at.session_state.configs[t.id]["rpm"] for t in traces], [900.,1600.])


if __name__ == "__main__":
    unittest.main()
