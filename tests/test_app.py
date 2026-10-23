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
from background_conditions import resolved_configs
from unconfigured_conditions import clear_potential_conditions

ROOT = Path(__file__).resolve().parents[1]


def widget(elements, label):
    return next(e for e in elements if e.label == label)


def load_unconfigured_examples(at):
    """Exercise missing/historical conditions explicitly; normal defaults have separate UI coverage."""
    widget(at.button, "载入四份示例").click().run()
    for cfg in at.session_state.configs.values():
        clear_potential_conditions(cfg)
    at.run()


def raw_axis(at):
    widget(at.selectbox, "分析与导出的电位坐标").set_value("原始").run()
    widget(at.button, "应用设置").click().run()


def condition_targets(at):
    source = widget(at.selectbox, "读取设置的文件").value
    group = at.session_state.configs[source]["group"]
    return [ident for ident, cfg in at.session_state.configs.items()
            if cfg["group"] == group and cfg.get("role") != "背景"]


def effective_background(at, ident):
    return resolved_configs(at.session_state.configs,
                            {key: trace.name for key, trace in at.session_state.traces.items()})[ident]


def bind_sample_background(at):
    background = next(i for i,c in at.session_state.configs.items() if c["role"] == "背景")
    value = at.session_state.traces[background].name + " · " + background[:4]
    edits = {index:{"背景文件":value} for index,(ident,cfg) in enumerate(at.session_state.configs.items())
             if cfg["role"] == "样品"}
    key = f"metadata_{at.session_state.revision}_{at.session_state.draft_epoch}"
    at.session_state[key] = {"edited_rows":edits,"added_rows":[],"deleted_rows":[]}
    at.run()
    widget(at.button, "应用设置").click().run()


class AppTests(unittest.TestCase):
    def assert_clean(self, at):
        self.assertEqual(len(at.exception), 0, str([e.value for e in at.exception]))

    def test_condition_copy_preserves_hidden_electrolyte_per_file(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        raw_axis(at)
        source = widget(at.selectbox, "读取设置的文件").value
        targets = condition_targets(at)
        self.assertEqual(len(targets), 2)
        at.session_state.configs[source]["electrolyte"] = "O2 saturated test electrolyte"
        at.session_state.revision += 1
        at.session_state.settings_draft["base_revision"] = at.session_state.revision
        at.run()
        self.assertNotIn("电解液、浓度与气氛", [e.label for e in at.text_input])
        before = {i:at.session_state.configs[i]["electrolyte"] for i in targets}
        widget(at.button, "复制当前条件到所选范围").click().run()
        if any(e.label == "应用设置" for e in at.button):
            widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        for ident in targets:
            self.assertEqual(at.session_state.configs[ident]["electrolyte"], before[ident])

    def test_full_workflow(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        self.assert_clean(at)
        load_unconfigured_examples(at)
        self.assert_clean(at)
        self.assertEqual(len(at.session_state.traces), 4)
        bind_sample_background(at)
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
        self.assertIn("polarization.png", list(at.session_state.exports))
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
        self.assertEqual(at.session_state.results["kl"]["params"]["units"]["C"], "mol/cm³")
        self.assertEqual(at.session_state.results["kl"]["params"]["axis"], "RHE")
        at.switch_page("app_pages/rrde.py").run()
        self.assert_clean(at)
        widget(at.button, "计算 RRDE").click().run()
        self.assert_clean(at)
        self.assertIn("rrde_results.csv", list(at.session_state.exports))
        kl_before = at.session_state.results["kl"]["data"].copy(deep=True)
        rrde_before = at.session_state.results["rrde"]["data"].copy(deep=True)
        revision_before = at.session_state.revision
        at.switch_page("app_pages/curves.py").run()
        widget(at.toggle, "启用曲线平滑").set_value(True).run()
        self.assert_clean(at)
        smooth_csv = pd.read_csv(BytesIO(at.session_state.exports["polarization_data.csv"]["bytes"]))
        self.assertIn(SMOOTH_A, smooth_csv)
        self.assertIn(SMOOTH_MA, smooth_csv)
        scientific_columns = [column for column in unsmoothed_csv.columns if not column.startswith("plotted_")]
        pd.testing.assert_frame_equal(smooth_csv[scientific_columns], unsmoothed_csv[scientific_columns])
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

    def test_failed_kl_recalculation_clears_prior_result_and_exports(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        raw_axis(at)
        at.switch_page("app_pages/kl.py").run()
        widget(at.number_input, "氧浓度 C / mol·cm⁻³ *").set_value(1.2e-6)
        widget(at.number_input, "扩散系数 D / cm²·s⁻¹ *").set_value(1.9e-5)
        widget(at.number_input, "运动黏度 ν / cm²·s⁻¹ *").set_value(.01)
        widget(at.checkbox, "已核对：各文件属于同一电极和相同实验条件，以上物性参数适用").check()
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        self.assertIn("kl", at.session_state.results)
        self.assertIn("kl_results.csv", at.session_state.exports)
        self.assertTrue(any("不满足两路径模型检查" in e.value for e in at.warning))
        widget(at.checkbox, "已核对：各文件属于同一电极和相同实验条件，以上物性参数适用").uncheck()
        widget(at.button, "计算 K–L").click().run()
        self.assert_clean(at)
        self.assertNotIn("kl", at.session_state.results)
        self.assertFalse(any(name.startswith("kl_") for name in at.session_state.exports))
        self.assertTrue(any("请先核对" in e.value for e in at.error))

    def test_missing_parameters_reported_without_crash(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertTrue(any("未处理" in w.value for w in at.warning))

    def test_conditional_rhe_forms_keep_inactive_values(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        self.assertNotIn("盘几何面积 / cm² *", [e.label for e in at.number_input])
        self.assertNotIn("RRDE 收集效率 N（0–1） *", [e.label for e in at.number_input])
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        self.assertNotIn("该温度下 E_ref vs SHE / V *", [e.label for e in at.number_input])
        widget(at.button, "应用设置").click().run()
        source = widget(at.selectbox, "读取设置的文件").value
        self.assertEqual(at.session_state.configs[source]["ref_V_SHE"], .197)
        widget(at.selectbox, "原始电位的换算方式 *").set_value("实测 RHE 总偏移").run()
        self.assertNotIn("pH *", [e.label for e in at.number_input])
        self.assertNotIn("参比方案 *", [e.label for e in at.selectbox])
        widget(at.number_input, "实测 RHE 总偏移 / V *").set_value(0.).run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[source]["pH"], 13.)
        self.assertEqual(at.session_state.configs[source]["ref_V_SHE"], .197)
        self.assertEqual(at.session_state.configs[source]["rhe_offset_V"], 0.)
        widget(at.selectbox, "原始电位的换算方式 *").set_value("已是 RHE").run()
        self.assertNotIn("实测 RHE 总偏移 / V *", [e.label for e in at.number_input])
        widget(at.button, "应用设置").click().run()
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertIn("polarization.png", list(at.session_state.exports))
        self.assertEqual(at.session_state.configs[source]["potential_method"], "已是 RHE")

    def test_default_geometry_and_group_scoped_edits(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        raw_axis(at)
        at.switch_page("app_pages/curves.py").run()
        widget(at.selectbox, "纵坐标").set_value("电流密度 / mA·cm⁻²").run()
        self.assertEqual(widget(at.number_input, "盘直径 / mm *").value, 5.)
        source = widget(at.selectbox, "读取设置的文件").value
        targets = condition_targets(at)
        self.assertEqual(len(targets), 2)
        widget(at.number_input, "盘直径 / mm *").set_value(4.).run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        for ident, cfg in at.session_state.configs.items():
            self.assertEqual(cfg["disk_diameter_mm"], 4. if ident in targets else 5.)
        self.assertAlmostEqual(at.session_state.configs[source]["area_cm2"], math.pi*.04)
        widget(at.selectbox, "盘面积输入方式").set_value("直接输入面积").run()
        widget(at.number_input, "盘几何面积 / cm² *").set_value(.25).run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[source]["area_cm2"], .25)
        self.assertIsNone(at.session_state.configs[source]["disk_diameter_mm"])

    def test_single_channel_and_ir_controls_are_conditional(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        self.assertNotIn("环电流通道", [e.label for e in at.selectbox])
        self.assertNotIn("尚未补偿电阻 / Ω *", [e.label for e in at.number_input])
        widget(at.toggle, "追加 iR 校正").set_value(True).run()
        self.assertIn("尚未补偿电阻 / Ω *", [e.label for e in at.number_input])
        widget(at.toggle, "追加 iR 校正").set_value(False).run()
        self.assertNotIn("尚未补偿电阻 / Ω *", [e.label for e in at.number_input])
        self.assert_clean(at)

    def test_invalid_saved_area_can_be_repaired_without_blocking_current(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        raw_axis(at)
        for cfg in at.session_state.configs.values():
            if cfg.get("role") != "背景":
                cfg.update(area_cm2=-1., area_mode="area", disk_diameter_mm=None)
        at.run()
        at.switch_page("app_pages/curves.py").run()
        self.assert_clean(at)
        self.assertIn("polarization.png", list(at.session_state.exports))
        widget(at.selectbox, "纵坐标").set_value("电流密度 / mA·cm⁻²").run()
        self.assert_clean(at)
        self.assertIsNone(widget(at.number_input, "盘几何面积 / cm² *").value)
        widget(at.number_input, "盘几何面积 / cm² *").set_value(.25).run()
        widget(at.segmented_control, "应用范围").set_value("自选").run()
        widget(at.multiselect, "应用到文件").set_value([
            ident for ident, cfg in at.session_state.configs.items() if cfg.get("role") != "背景"]).run()
        widget(at.button, "复制当前条件到所选范围").click().run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertIn("polarization.png", at.session_state.exports)

    def test_removed_profile_controls_preserve_project_presets(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        at.session_state.settings["presets"] = {"saved": {"pH":7., "collection_efficiency":.4}}
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.button, "应用设置").click().run()
        self.assert_clean(at)
        self.assertNotIn("预设保存位置", [e.label for e in at.selectbox])
        self.assertNotIn("常用条件：保存与复用", [e.label for e in at.expander])
        _, _, settings = unpack_project(pack_project(dict(at.session_state.traces),
            dict(at.session_state.configs), dict(at.session_state.settings)))
        self.assertEqual(settings["presets"], {"saved": {"pH":7., "collection_efficiency":.4}})

    def test_hidden_profile_does_not_write_local_file_or_apply_ph(self):
        with tempfile.TemporaryDirectory() as directory, patch("experiment_conditions.PROFILE_PATH", Path(directory)/"presets.json"):
            target = Path(directory)/"presets.json"
            target.write_text('{"keep":"saved content"}', encoding="utf-8")
            before = target.read_bytes()
            at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
            load_unconfigured_examples(at)
            widget(at.number_input, "pH *").set_value(13.).run()
            source = widget(at.selectbox, "读取设置的文件").value
            self.assertIsNone(at.session_state.configs[source]["pH"])
            self.assertEqual(target.read_bytes(), before)
            widget(at.button, "应用设置").click().run()
            self.assertEqual(at.session_state.configs[source]["pH"], 13.)
            self.assertEqual(target.read_bytes(), before)
            self.assert_clean(at)
    def test_kl_background_conditions_follow_without_an_extra_background_target(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        bind_sample_background(at)
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        widget(at.button, "应用设置").click().run()
        background = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertIsNone(at.session_state.configs[background]["pH"])
        self.assertIsNone(at.session_state.configs[background]["ref_V_SHE"])
        effective = effective_background(at, background)
        self.assertEqual(effective["pH"], 13.)
        self.assertEqual(effective["ref_V_SHE"], .197)
        at.switch_page("app_pages/kl.py").run()
        self.assert_clean(at)
        self.assertFalse(any("盘背景" in str(frame.value) and "请填写" in str(frame.value) for frame in at.dataframe))
        self.assertNotIn(background, condition_targets(at))
        self.assertEqual(len(effective["background_conditions"]["linked_samples"]), 2)
        self.assertIn("电解液参数方案 *", [e.label for e in at.selectbox])
        widget(at.selectbox, "读取设置的文件").set_value(background).run()
        self.assertEqual(widget(at.segmented_control, "应用范围").value, "当前组")
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
        editor_key=f"metadata_{at.session_state.revision}_{at.session_state.draft_epoch}"
        at.session_state[editor_key]={"edited_rows":{0:{"转速/rpm":900.}},"added_rows":[],"deleted_rows":[]}
        at.run()
        widget(at.button,"应用设置").click().run()
        self.assert_clean(at)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm"],900)
        self.assertEqual(at.session_state.configs[traces[0].id]["rpm_source"],"manual")
        set_manual_rpm(at.session_state.configs[traces[0].id],None)
        at.session_state.configs[traces[0].id]["group"]="保留手动分组"
        at.session_state.results={"old_result":{"obsolete":True}}
        at.session_state.exports={"obsolete.csv":{"bytes":b"old","mime":"text/csv"}}
        at.run()
        widget(at.button,"根据文件名补全空白转速").click().run()
        widget(at.button,"应用设置").click().run()
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
        load_unconfigured_examples(at)
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        bind_sample_background(at)
        self.assertEqual(effective_background(at, bg)["background_conditions"]["status"], "waiting")
        widget(at.number_input, "pH *").set_value(13.).run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.selectbox, "参比方案 *").set_value("Ag/AgCl · 饱和 KCl · 25 °C").run()
        widget(at.button, "应用设置").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertIsNone(at.session_state.configs[bg]["ref_V_SHE"])
        effective = effective_background(at, bg)
        self.assertEqual(effective["pH"], 13.)
        self.assertEqual(effective["ref_V_SHE"], .197)
        self.assertEqual(len(effective["background_conditions"]["linked_samples"]), 2)
        source = widget(at.selectbox, "读取设置的文件").value
        widget(at.segmented_control, "应用范围").set_value("仅此文件").run()
        widget(at.number_input, "pH *").set_value(12.).run()
        at.session_state.results = {"old":{"must_expire":True}}
        at.session_state.exports = {"old.csv":{"bytes":b"old", "mime":"text/csv"}}
        widget(at.button, "应用设置").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertEqual(effective_background(at, bg)["background_conditions"]["status"], "conflict")
        self.assertEqual(at.session_state.results, {})
        self.assertEqual(at.session_state.exports, {})
        self.assertTrue(any("pH" in str(frame.value) and "冲突" in str(frame.value) for frame in at.dataframe))
        self.assert_clean(at)

    def test_background_manual_mode_and_following_switch(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        # This regression exercises the imported legacy pH panel. The new full
        # condition panel is delivered by Qoder and has its own acceptance tests.
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        at.session_state.configs[bg]["background_conditions_mode"] = "legacy_ph"
        bind_sample_background(at)
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.button, "应用设置").click().run()
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        sample = widget(at.selectbox, "读取设置的文件").value
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        widget(at.selectbox, "要检查的文件").set_value(sample).run()
        widget(at.selectbox, "背景 pH 模式").set_value("独立填写").run()
        widget(at.number_input, "背景独立 pH（允许 0）").set_value(12.).run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["background_ph_mode"], "manual")
        self.assertEqual(at.session_state.configs[bg]["pH"], 12.)
        widget(at.segmented_control, "参数设置").set_value("实验条件").run()
        widget(at.number_input, "pH *").set_value(14.).run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 12.)
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        widget(at.selectbox, "背景 pH 模式").set_value("跟随关联样品").run()
        widget(at.button, "应用设置").click().run()
        self.assertEqual(at.session_state.configs[bg]["pH"], 12.)
        self.assertEqual(effective_background(at, bg)["pH"], 14.)
        self.assert_clean(at)

    def test_scan_background_commit_activates_link_and_file_removal_cleans_it(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"), default_timeout=30).run()
        load_unconfigured_examples(at)
        widget(at.number_input, "pH *").set_value(13.).run()
        widget(at.button, "应用设置").click().run()
        sample = widget(at.selectbox, "读取设置的文件").value
        bg = next(k for k,c in at.session_state.configs.items() if c["role"] == "背景")
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.segmented_control, "参数设置").set_value("扫描与背景").run()
        widget(at.selectbox, "要检查的文件").set_value(sample).run()
        widget(at.selectbox, "盘背景文件").set_value(bg).run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        widget(at.button, "应用设置").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertEqual(effective_background(at, bg)["pH"], 13.)
        widget(at.multiselect, "选择移除（原始文件不会删除）").set_value([sample]).run()
        widget(at.button, "从本次分析移除").click().run()
        self.assertIsNone(at.session_state.configs[bg]["pH"])
        self.assertEqual(effective_background(at, bg)["background_conditions"]["status"], "unbound")
        self.assert_clean(at)


if __name__ == "__main__":
    unittest.main()
