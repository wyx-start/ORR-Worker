"""Condition editing and task requirements, using synthetic records only."""
import copy
import unittest

from background_conditions import resolved_configs
from experiment_conditions import apply_conditions, missing_conditions, snapshot_conditions
from orr_core import DataError


def records():
    return {
        "sample": dict(role="样品", name="S.txt", pH=13., temperature_C=25.,
                       potential_method="理论换算", ref_V_SHE=.197, reference="Ag/AgCl",
                       filling="KCl", background_disk="bg"),
        "bg": dict(role="背景", name="Ar.txt", pH=11., temperature_C=20.,
                   potential_method="理论换算", ref_V_SHE=.241, reference="SCE", filling="KCl",
                   background_conditions_mode="follow", background_conditions_migration={},
                   background_ph_mode="auto", background_ph_legacy=False,
                   parameter_sources={"pH": "独立旧值", "temperature_C": "人工独立"}),
    }


class BackgroundConditionBusinessTests(unittest.TestCase):
    def test_follow_write_rejection_is_atomic_including_noninherited_fields(self):
        cfg = records()["bg"]
        original = copy.deepcopy(cfg)
        with self.assertRaisesRegex(DataError, "独立"):
            apply_conditions(cfg, {"electrolyte": "Ar test", "pH": 12.})
        self.assertEqual(cfg, original)

    def test_even_cache_equal_input_requires_view_based_noop_elimination(self):
        cfg = records()["bg"]
        with self.assertRaises(DataError):
            apply_conditions(cfg, {"pH": 11.})
        self.assertEqual(cfg["pH"], 11.)

    def test_noninherited_write_and_explicit_independent_copy_are_allowed(self):
        cfg = records()["bg"]
        self.assertTrue(apply_conditions(cfg, {"electrolyte": "Ar test"}))
        self.assertEqual(cfg["pH"], 11.)
        cfg["background_conditions_mode"] = "independent"
        self.assertTrue(apply_conditions(cfg, {"pH": 0., "rhe_offset_V": 0.}, "用户复制"))
        self.assertEqual(cfg["pH"], 0.)
        self.assertEqual(cfg["rhe_offset_V"], 0.)
        self.assertEqual(cfg["parameter_sources"]["pH"], "用户复制")

    def test_invalid_values_do_not_partially_modify_record_or_sources(self):
        cfg = records()["bg"]
        cfg["background_conditions_mode"] = "independent"
        before = copy.deepcopy(cfg)
        with self.assertRaises(DataError):
            apply_conditions(cfg, {"pH": 12., "collection_efficiency": 37.})
        self.assertEqual(cfg, before)

    def test_effective_projection_is_readonly_but_can_supply_reusable_profile(self):
        source = records()
        view = resolved_configs(source)["bg"]
        before = copy.deepcopy(view)
        with self.assertRaises(DataError):
            apply_conditions(view, {"pH": 12.})
        self.assertEqual(view, before)
        profile = snapshot_conditions(view)
        self.assertEqual(profile["pH"], 13.)
        self.assertNotIn("background_conditions_mode", profile)
        self.assertNotIn("background_conditions", profile)
        with self.assertRaisesRegex(DataError, "独立缓存"):
            snapshot_conditions(source["bg"])

    def test_waiting_and_independent_missing_have_distinct_task_messages(self):
        source = records()
        source["sample"].update(pH=None, ref_V_SHE=None)
        view = resolved_configs(source)["bg"]
        issues = missing_conditions(view)
        self.assertTrue(any("等待关联样品填写 pH" in item for item in issues))
        self.assertTrue(any("等待关联样品填写 参比电位" in item for item in issues))
        self.assertEqual(missing_conditions(view, axis="原始"), [])
        source["bg"].update(background_conditions_mode="independent", pH=None)
        view = resolved_configs(source)["bg"]
        self.assertIn("背景自身缺少 pH", missing_conditions(view))

    def test_method_dependencies_keep_valid_zero_and_do_not_add_unused_requirements(self):
        source = records()
        source["sample"].update(potential_method="实测 RHE 总偏移", rhe_offset_V=0., pH=None)
        self.assertEqual(missing_conditions(resolved_configs(source)["bg"]), [])
        source["sample"].update(potential_method="已是 RHE", rhe_offset_V=None)
        self.assertEqual(missing_conditions(resolved_configs(source)["bg"]), [])

    def test_known_conflicts_still_block_raw_background_use(self):
        source = records()
        source["other"] = dict(source["sample"], pH=12., name="Other.txt")
        issues = missing_conditions(resolved_configs(source)["bg"], axis="原始")
        self.assertTrue(any("pH" in item and "冲突" in item for item in issues))

    def test_legacy_batch_does_not_write_effective_ph_into_independent_record(self):
        cfg = records()["bg"]
        cfg.update(background_conditions_mode="legacy_ph", background_ph_mode="follow", pH=None)
        apply_conditions(cfg, {"pH": 13., "temperature_C": 25.}, background_ph_edit=False)
        self.assertIsNone(cfg["pH"])
        self.assertEqual(cfg["parameter_sources"]["pH"], "独立旧值")
        self.assertEqual(cfg["temperature_C"], 25.)
        apply_conditions(cfg, {"pH": 12.}, background_ph_edit=True)
        self.assertEqual(cfg["background_ph_mode"], "manual")
        self.assertEqual(cfg["pH"], 12.)


if __name__ == "__main__":
    unittest.main()
