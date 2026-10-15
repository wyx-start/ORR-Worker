from io import BytesIO
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest
from orr_core import default_config, pack_project, parse_chi, set_manual_rpm, unpack_project
from plot_smoothing import SMOOTH_A, SMOOTH_MA

ROOT = Path(__file__).resolve().parents[1]


def widget(elements, label):
    return next(e for e in elements if e.label == label)


class AppTests(unittest.TestCase):
    def assert_clean(self, at):
        self.assertEqual(len(at.exception), 0, str([e.value for e in at.exception]))

    def test_full_workflow(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        self.assert_clean(at)
        widget(at.button, "载入四份示例").click().run()
        self.assert_clean(at)
        self.assertEqual(len(at.session_state.traces), 4)
        widget(at.button, "确认并应用分组与背景").click().run()
        self.assert_clean(at)
        # Test fixture only, not inferred real experimental parameters.
        for cfg in at.session_state.configs.values():
            cfg.update(pH=13., ref_V_SHE=.197, reference="Ag/AgCl", filling="sat KCl", area_cm2=.196,
                       collection_efficiency=.37, electrolyte="test fixture", ring_detection_confirmed=True)
        at.run()
        self.assert_clean(at)
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        self.assert_clean(at)
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertIn("polarization.png", at.session_state.exports)
        unsmoothed_csv = pd.read_csv(BytesIO(at.session_state.exports["polarization_data.csv"]["bytes"]))
        at.switch_page("app_pages/kl.py").run()
        self.assert_clean(at)
        widget(at.number_input, "氧浓度 C / mol·cm⁻³ *").set_value(1.2e-6)
        widget(at.number_input, "扩散系数 D / cm²·s⁻¹ *").set_value(1.9e-5)
        widget(at.number_input, "运动黏度 ν / cm²·s⁻¹ *").set_value(.01)
        widget(at.checkbox, "已核对：各文件属于同一电极和相同实验条件，以上物性参数适用").check()
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        self.assertIn("kl", at.session_state.results)
        at.switch_page("app_pages/rrde.py").run()
        self.assert_clean(at)
        self.assertIn("rrde_results.csv", at.session_state.exports)
        kl_before = at.session_state.results["kl"]["data"].copy(deep=True)
        rrde_before = at.session_state.results["rrde"]["data"].copy(deep=True)
        revision_before = at.session_state.revision
        at.switch_page("app_pages/curves.py").run()
        widget(at.toggle, "启用曲线平滑").set_value(True).run()
        self.assert_clean(at)
        smooth_csv = pd.read_csv(BytesIO(at.session_state.exports["polarization_data.csv"]["bytes"]))
        self.assertIn(SMOOTH_A, smooth_csv)
        self.assertIn(SMOOTH_MA, smooth_csv)
        pd.testing.assert_frame_equal(smooth_csv[unsmoothed_csv.columns], unsmoothed_csv)
        pd.testing.assert_frame_equal(at.session_state.results["kl"]["data"], kl_before)
        pd.testing.assert_frame_equal(at.session_state.results["rrde"]["data"], rrde_before)
        self.assertEqual(at.session_state.revision, revision_before)
        widget(at.selectbox, "平滑强度").set_value("中").run()
        widget(at.toggle, "显示浅色未平滑参考线").set_value(False).run()
        self.assert_clean(at)
        project = pack_project(at.session_state.traces, at.session_state.configs, at.session_state.settings)
        _, _, saved_settings = unpack_project(project)
        self.assertTrue(saved_settings["plot"]["smoothing"]["enabled"])
        self.assertEqual(saved_settings["plot"]["smoothing"]["window_points"], 21)
        self.assertFalse(saved_settings["plot"]["smoothing"]["show_unsmoothed"])
        widget(at.toggle, "启用曲线平滑").set_value(False).run()
        disabled_csv = pd.read_csv(BytesIO(at.session_state.exports["polarization_data.csv"]["bytes"]))
        pd.testing.assert_frame_equal(disabled_csv, unsmoothed_csv)
        at.switch_page("app_pages/export.py").run()
        self.assert_clean(at)
        self.assertIn("parameters.json", at.session_state.exports)

    def test_missing_parameters_reported_without_crash(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertTrue(any("未处理" in w.value for w in at.warning))

    def test_conditional_rhe_forms_keep_inactive_values(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        self.assertNotIn("盘几何面积 / cm² *", [e.label for e in at.number_input])
        self.assertNotIn("RRDE 收集效率 N（0–1） *", [e.label for e in at.number_input])
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        self.assertNotIn("该温度下 E_ref vs SHE / V *", [e.label for e in at.number_input])
        widget(at.button, "应用实验参数").click().run()
        source = widget(at.selectbox, "读取设置的文件").value
        self.assertEqual(at.session_state.configs[source]["ref_V_SHE"], .197)
        widget(at.selectbox, "原始电位的换算方式 *").set_value("实测 RHE 总偏移").run()
        self.assertNotIn("pH *", [e.label for e in at.number_input])
        self.assertNotIn("参比方案 *", [e.label for e in at.selectbox])
        widget(at.number_input, "实测 RHE 总偏移 / V *").set_value(0.).run()
        widget(at.button, "应用实验参数").click().run()
        self.assertEqual(at.session_state.configs[source]["pH"], 13.)
        self.assertEqual(at.session_state.configs[source]["ref_V_SHE"], .197)
        self.assertEqual(at.session_state.configs[source]["rhe_offset_V"], 0.)
        widget(at.selectbox, "原始电位的换算方式 *").set_value("已是 RHE").run()
        self.assertNotIn("实测 RHE 总偏移 / V *", [e.label for e in at.number_input])
        widget(at.button, "应用实验参数").click().run()
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertIn("polarization.png", at.session_state.exports)
        self.assertEqual(at.session_state.configs[source]["potential_method"], "已是 RHE")

    def test_default_geometry_and_group_scoped_edits(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        widget(at.button, "先查看原始电位曲线").click().run()
        at.switch_page("app_pages/curves.py").run()
        widget(at.selectbox, "纵坐标").set_value("电流密度 / mA·cm⁻²").run()
        self.assertEqual(widget(at.number_input, "盘直径 / mm *").value, 5.)
        source = widget(at.selectbox, "读取设置的文件").value
        targets = widget(at.multiselect, "应用到文件（默认当前组，可加入背景或其他文件）").value
        self.assertEqual(len(targets), 2)
        widget(at.number_input, "盘直径 / mm *").set_value(4.).run()
        widget(at.button, "应用实验参数").click().run()
        self.assert_clean(at)
        for ident, cfg in at.session_state.configs.items():
            self.assertEqual(cfg["disk_diameter_mm"], 4. if ident in targets else 5.)
        self.assertAlmostEqual(at.session_state.configs[source]["area_cm2"], math.pi*.04)
        widget(at.selectbox, "盘面积输入方式").set_value("直接输入面积").run()
        widget(at.number_input, "盘几何面积 / cm² *").set_value(.25).run()
        widget(at.button, "应用实验参数").click().run()
        self.assertEqual(at.session_state.configs[source]["area_cm2"], .25)
        self.assertIsNone(at.session_state.configs[source]["disk_diameter_mm"])

    def test_single_channel_and_ir_controls_are_conditional(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        self.assertNotIn("环电流通道", [e.label for e in at.selectbox])
        self.assertNotIn("尚未补偿的电阻 / Ω *", [e.label for e in at.number_input])
        widget(at.toggle, "追加 iR 校正").set_value(True).run()
        self.assertIn("尚未补偿的电阻 / Ω *", [e.label for e in at.number_input])
        widget(at.toggle, "追加 iR 校正").set_value(False).run()
        self.assertNotIn("尚未补偿的电阻 / Ω *", [e.label for e in at.number_input])
        self.assert_clean(at)

    def test_invalid_saved_area_can_be_repaired_without_blocking_current(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        for cfg in at.session_state.configs.values():
            cfg.update(area_cm2=-1., area_mode="area", disk_diameter_mm=None)
        widget(at.button, "先查看原始电位曲线").click().run()
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertIn("polarization.png", at.session_state.exports)
        widget(at.selectbox, "纵坐标").set_value("电流密度 / mA·cm⁻²").run()
        self.assert_clean(at)
        self.assertIsNone(widget(at.number_input, "盘几何面积 / cm² *").value)
        widget(at.number_input, "盘几何面积 / cm² *").set_value(.25).run()
        widget(at.button, "应用实验参数").click().run()
        self.assert_clean(at)
        self.assertIn("polarization.png", at.session_state.exports)

    def test_local_profile_reuse_requires_explicit_application(self):
        with tempfile.TemporaryDirectory() as directory, patch("experiment_conditions.PROFILE_PATH", Path(directory)/"presets.json"):
            at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
            widget(at.button, "载入四份示例").click().run()
            widget(at.selectbox, "原始电位的换算方式 *").set_value("实测 RHE 总偏移").run()
            widget(at.number_input, "实测 RHE 总偏移 / V *").set_value(.95).run()
            widget(at.button, "应用实验参数").click().run()
            widget(at.button, "设为本机常用条件").click().run()
            self.assert_clean(at)
            restarted = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
            widget(restarted.button, "载入四份示例").click().run()
            source = widget(restarted.selectbox, "读取设置的文件").value
            self.assertEqual(restarted.session_state.configs[source]["potential_method"], "理论换算")
            widget(restarted.button, "套用常用条件").click().run()
            self.assert_clean(restarted)
            cfg = restarted.session_state.configs[source]
            self.assertEqual(cfg["potential_method"], "实测 RHE 总偏移")
            self.assertEqual(cfg["rhe_offset_V"], .95)
            self.assertFalse(cfg["background_reviewed"])
            self.assertFalse(cfg["ring_detection_confirmed"])

    def test_unapplied_ph_is_explicit_and_cannot_save_a_stale_profile(self):
        with tempfile.TemporaryDirectory() as directory, patch("experiment_conditions.PROFILE_PATH", Path(directory)/"presets.json"):
            at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
            widget(at.button, "载入四份示例").click().run()
            widget(at.number_input, "pH *").set_value(13.).run()
            self.assertTrue(any("修改尚未应用" in e.value for e in at.warning))
            widget(at.button, "设为本机常用条件").click().run()
            self.assertFalse((Path(directory)/"presets.json").exists())
            self.assertTrue(any("请先点击" in e.value for e in at.error))
            widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
            widget(at.button, "应用实验参数").click().run()
            source = widget(at.selectbox, "读取设置的文件").value
            self.assertEqual(at.session_state.configs[source]["pH"], 13.)
            widget(at.button, "设为本机常用条件").click().run()
            from experiment_conditions import load_profiles
            profiles, error = load_profiles(Path(directory)/"presets.json")
            self.assertIsNone(error)
            self.assertEqual(profiles["常用条件"]["pH"], 13.)
            self.assert_clean(at)

    def test_kl_background_ph_can_be_included_and_applied_explicitly(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        widget(at.button, "确认并应用分组与背景").click().run()
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        widget(at.button, "应用实验参数").click().run()
        background = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertEqual(at.session_state.configs[background]["pH"], 13.)
        at.switch_page("app_pages/kl.py").run()
        self.assert_clean(at)
        self.assertTrue(any("盘背景" in str(frame.value) and "参比" in str(frame.value) for frame in at.dataframe))
        widget(at.button, "将关联背景加入应用范围").click().run()
        targets = widget(at.multiselect, "应用到文件（默认当前组，可加入背景或其他文件）").value
        self.assertIn(background, targets)
        self.assertEqual(len(targets), 3)
        widget(at.button, "应用实验参数").click().run()
        self.assertEqual(at.session_state.configs[background]["pH"], 13.)
        self.assertEqual(at.session_state.configs[background]["ref_V_SHE"], .197)
        self.assertIn("电解液参数方案 *", [e.label for e in at.selectbox])
        widget(at.selectbox, "读取设置的文件").set_value(background).run()
        self.assertEqual(widget(at.multiselect, "应用到文件（默认当前组，可加入背景或其他文件）").value, [background])
        self.assertNotIn("盘直径 / mm *", [e.label for e in at.number_input])
        self.assert_clean(at)

    def test_rpm_edit_fill_invalidation_and_reimport(self):
        at=AppTest.from_file(str(ROOT/"streamlit_app.py"),default_timeout=30).run()
        raw=(ROOT/"examples"/"O-0.1MNa-5mv-900.txt").read_bytes()
        traces=[parse_chi(name,raw) for name in ("CoPc_1600转.txt","CoPc_900转_1600转.txt","O-0.1MNa-5mv-900.txt")]
        at.session_state.traces={t.id:t for t in traces}
        at.session_state.configs={t.id:default_config(t) for t in traces}
        set_manual_rpm(at.session_state.configs[traces[2].id],1200)
        at.run()
        self.assert_clean(at)
        editor_key=f"metadata_table_{at.session_state.revision}"
        at.session_state[editor_key]={"edited_rows":{0:{"转速/rpm":900.}},"added_rows":[],"deleted_rows":[]}
        widget(at.button,"确认并应用分组与背景").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm"],900)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm_source"],"manual")
        set_manual_rpm(at.session_state.configs[traces[0].id],None)
        at.session_state.configs[traces[0].id]["group"]="保留手动分组"
        at.session_state.results={"old_result":{"obsolete":True}}
        at.session_state.exports={"obsolete.csv":{"bytes":b"old","mime":"text/csv"}}
        at.run()
        widget(at.button,"根据文件名补全空白转速").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm"],1600)
        self.assertEqual(at.session_state.configs[traces[0].id]["group"],"保留手动分组")
        self.assertIsNone(at.session_state.configs[traces[1].id]["rpm"])
        self.assertEqual(at.session_state.configs[traces[2].id]["rpm"],1200)
        self.assertEqual(at.session_state.results,{})
        self.assertEqual(at.session_state.exports,{})
        widget(at.button,"载入四份示例").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[traces[2].id]["rpm"],1200)
        self.assertEqual(at.session_state.configs[traces[2].id]["rpm_source"],"manual")

    def test_background_ph_follows_applied_values_and_detects_shared_conflict(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.button, "确认并应用分组与背景").click().run()
        self.assertEqual(at.session_state.configs[bg]["background_ph_status"], "waiting")
        widget(at.number_input, "pH *").set_value(13.).run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        widget(at.button, "应用实验参数").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 13.)
        self.assertIsNone(at.session_state.configs[bg]["ref_V_SHE"])
        self.assertEqual(len(at.session_state.configs[bg]["background_ph_sources"]), 2)
        source = widget(at.selectbox, "读取设置的文件").value
        widget(at.multiselect, "应用到文件（默认当前组，可加入背景或其他文件）").set_value([source]).run()
        widget(at.number_input, "pH *").set_value(12.).run()
        at.session_state.results = {"old":{"must_expire":True}}
        at.session_state.exports = {"old.csv":{"bytes":b"old", "mime":"text/csv"}}
        widget(at.button, "应用实验参数").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertEqual(at.session_state.configs[bg]["background_ph_status"], "conflict")
        self.assertEqual(at.session_state.results, {})
        self.assertEqual(at.session_state.exports, {})
        self.assertTrue(any("共享背景 pH 冲突" in str(frame.value) for frame in at.dataframe))
        self.assert_clean(at)

    def test_background_manual_mode_and_following_switch(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        widget(at.button, "确认并应用分组与背景").click().run()
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.button, "应用实验参数").click().run()
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        widget(at.selectbox, "背景 pH 模式").set_value("独立填写背景 pH").run()
        widget(at.number_input, "背景独立 pH（允许 0）").set_value(12.).run()
        widget(at.button, "应用背景 pH 设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["background_ph_mode"], "manual")
        self.assertEqual(at.session_state.configs[bg]["pH"], 12.)
        widget(at.number_input, "pH *").set_value(14.).run()
        widget(at.button, "应用实验参数").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 12.)
        widget(at.selectbox, "背景 pH 模式").set_value("跟随关联样品（默认）").run()
        widget(at.button, "应用背景 pH 设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 14.)
        self.assert_clean(at)

    def test_scan_background_commit_activates_link_and_file_removal_cleans_it(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        widget(at.button, "载入四份示例").click().run()
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.button, "应用实验参数").click().run()
        sample = widget(at.selectbox, "读取设置的文件").value
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        widget(at.selectbox, "要检查的文件").set_value(sample).run()
        widget(at.selectbox, "盘背景").set_value(bg).run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.button, "应用扫描与背景设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 13.)
        widget(at.multiselect, "选择移除（原始文件不会删除）").set_value([sample]).run()
        widget(at.button, "从本次分析移除").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertEqual(at.session_state.configs[bg]["background_ph_status"], "unbound")
        self.assert_clean(at)


if __name__ == "__main__":
    unittest.main()
