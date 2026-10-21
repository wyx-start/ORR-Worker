import copy
import unittest

import numpy as np

from orr_core import DataError, Trace, default_config
from settings_draft import candidate, has_changes, new_draft, stage_config, stage_settings


def fixtures():
    traces, configs = {}, {}
    for name in ("sample_a.txt", "sample_b.txt", "Ar_background.txt", "Ar_background_2.txt"):
        trace = Trace(name, name.encode(), {"Low E (V)": 0., "High E (V)": 1.,
                      "Sample Interval (V)": .25}, ["Potential/V", "i1/A", "i2/A"],
                      np.array([[1., -1e-4, 1e-6], [.75, -2e-4, 2e-6],
                                [.5, -3e-4, 3e-6], [.25, -4e-4, 4e-6],
                                [0., -5e-4, 5e-6]]), "utf-8", [])
        traces[name] = trace
        configs[name] = default_config(trace)
    return traces, configs, {"axis": "RHE", "plot": {"color": "blue"}}


class SettingsDraftTests(unittest.TestCase):
    def setUp(self):
        self.traces, self.configs, self.settings = fixtures()
        self.draft = new_draft(4)
        self.a, self.b, self.bg, self.bg2 = self.traces

    def build(self):
        return candidate(self.draft, self.traces, self.configs, self.settings, 4)

    def test_same_domain_latest_edit_and_nested_sources_are_preserved(self):
        self.assertFalse(has_changes(self.draft))
        stage_config(self.draft, "conditions", self.a, {"pH": 12., "parameter_sources": {"pH": "preset"}})
        stage_config(self.draft, "conditions", self.a, {"pH": 13., "parameter_sources": {"pH": "manual"}})
        stage_config(self.draft, "scan", self.a, {"ring_potential_V": 1., "parameter_sources": {"ring_potential_V": "manual"}})
        result, _ = self.build()
        self.assertTrue(has_changes(self.draft))
        self.assertEqual(result[self.a]["pH"], 13.)
        self.assertEqual(result[self.a]["parameter_sources"]["pH"], "manual")
        self.assertEqual(result[self.a]["parameter_sources"]["ring_potential_V"], "manual")
        self.assertIn("area_cm2", result[self.a]["parameter_sources"])
        self.assertIsNone(self.configs[self.a]["pH"])

    def test_cross_domain_conflict_is_atomic_and_identical_values_can_coexist(self):
        stage_config(self.draft, "conditions", self.a, {"pH": 12.})
        stage_config(self.draft, "preset", self.a, {"pH": 12.})
        original = copy.deepcopy(self.draft)
        with self.assertRaisesRegex(DataError, "矛盾"):
            stage_config(self.draft, "preset", self.a, {"pH": 13., "electrolyte": "changed"})
        self.assertEqual(self.draft, original)

    def test_nested_source_conflict_reports_leaf_without_mutating_draft(self):
        stage_config(self.draft, "conditions", self.a, {"parameter_sources": {"pH": "manual"}})
        original = copy.deepcopy(self.draft)
        with self.assertRaisesRegex(DataError, "parameter_sources.pH"):
            stage_config(self.draft, "other", self.a, {"parameter_sources": {"pH": "preset"}})
        self.assertEqual(self.draft, original)

    def test_global_axis_and_nested_settings_use_detached_snapshot(self):
        stage_settings(self.draft, "axis", {"axis": "原始"})
        stage_settings(self.draft, "plot", {"plot": {"linewidth": 2}})
        configs, settings = self.build()
        self.assertEqual(settings["axis"], "原始")
        self.assertEqual(settings["plot"], {"color": "blue", "linewidth": 2})
        configs[self.a]["name"] = "detached"
        settings["plot"]["color"] = "red"
        self.assertEqual(self.settings["axis"], "RHE")
        self.assertEqual(self.settings["plot"]["color"], "blue")
        self.assertNotEqual(self.configs[self.a]["name"], "detached")

    def test_settings_conflict_and_stale_revision_leave_every_input_unchanged(self):
        stage_settings(self.draft, "axis", {"axis": "原始"})
        before = copy.deepcopy((self.draft, self.configs, self.settings))
        with self.assertRaises(DataError):
            stage_settings(self.draft, "other", {"axis": "RHE"})
        with self.assertRaisesRegex(DataError, "旧修订"):
            candidate(self.draft, self.traces, self.configs, self.settings, 5)
        self.assertEqual((self.draft, self.configs, self.settings), before)

    def test_missing_inputs_and_absent_full_cycle_are_saved_without_task_validation(self):
        stage_config(self.draft, "conditions", self.a, {"pH": None, "collection_efficiency": None,
                     "area_cm2": None, "disk_diameter_mm": None, "temperature_C": None})
        configs, settings = self.build()
        self.assertIsNone(configs[self.a]["pH"])
        self.assertIsNone(configs[self.a]["collection_efficiency"])
        self.assertEqual(settings["axis"], "RHE")

    def test_shared_ph_conflict_is_preserved_as_legal_uncomputable_record(self):
        for ident, ph in ((self.a, 13.), (self.b, 12.)):
            stage_config(self.draft, "conditions", ident, {"pH": ph})
            stage_config(self.draft, "bindings", ident, {"background_mode": "paired", "background_disk": self.bg})
        configs, _ = self.build()
        self.assertEqual(configs[self.a]["background_ring"], self.bg)
        self.assertEqual(configs[self.bg]["background_ph_status"], "conflict")
        self.assertIsNone(configs[self.bg]["pH"])
        self.assertIsNone(self.configs[self.a]["background_disk"])

    def test_old_independent_background_and_manual_ph_are_not_migrated(self):
        self.configs[self.a].pop("background_mode")
        self.configs[self.a].update(background_disk=self.bg, background_ring=self.bg2)
        self.configs[self.bg].update(background_ph_mode="manual", pH=11.)
        before = copy.deepcopy(self.configs)
        stage_config(self.draft, "conditions", self.a, {"pH": 13.})
        configs, _ = self.build()
        self.assertNotIn("background_mode", configs[self.a])
        self.assertEqual(configs[self.a]["background_disk"], self.bg)
        self.assertEqual(configs[self.a]["background_ring"], self.bg2)
        self.assertEqual(configs[self.bg]["pH"], 11.)
        self.assertEqual(self.configs, before)

    def test_legacy_empty_background_only_adopts_follow_when_binding_is_explicit(self):
        self.configs[self.bg].update(background_ph_mode="manual", background_ph_legacy=True)
        stage_config(self.draft, "conditions", self.a, {"pH": 0.})
        stage_config(self.draft, "binding", self.a, {"background_disk": self.bg})
        configs, _ = self.build()
        self.assertEqual(configs[self.bg]["pH"], 0.)
        self.assertEqual(configs[self.bg]["background_ph_mode"], "follow")

    def test_invalid_candidate_does_not_mutate_any_supplied_state(self):
        stage_config(self.draft, "binding", self.a, {"background_disk": self.bg, "background_ring": self.bg})
        stage_config(self.draft, "conditions", self.b, {"pH": float("inf")})
        before = copy.deepcopy((self.draft, self.configs, self.settings))
        with self.assertRaisesRegex(DataError, "pH"):
            self.build()
        self.assertEqual((self.draft, self.configs, self.settings), before)

    def test_invalid_numeric_values_are_rejected_but_zero_ph_and_rpm_are_legal(self):
        invalid = ({"pH": True}, {"pH": float("nan")}, {"temperature_C": -273.15},
                   {"area_cm2": -1.}, {"collection_efficiency": 37.}, {"rpm": -1.},
                   {"ir_ohm": -1.}, {"disk_diameter_mm": 4.}, {"ir_enabled": "false"})
        for patch in invalid:
            with self.subTest(patch=patch):
                draft = new_draft(4)
                stage_config(draft, "conditions", self.a, patch)
                with self.assertRaises(DataError):
                    candidate(draft, self.traces, self.configs, self.settings, 4)
        stage_config(self.draft, "conditions", self.a, {"pH": 0., "rpm": 0., "rhe_offset_V": 0.})
        configs, _ = self.build()
        self.assertEqual(configs[self.a]["pH"], 0.)

    def test_invalid_manual_segments_and_channels_are_rejected_without_requiring_complete_scan(self):
        for patch in ({"manual_segment": 99}, {"manual_segment": 1.5}, {"manual_segment": True},
                      {"disk_channel": 7}, {"ring_channel": 0}, {"disk_channel": True}):
            with self.subTest(patch=patch):
                draft = new_draft(4)
                stage_config(draft, "scan", self.a, patch)
                with self.assertRaises(DataError):
                    candidate(draft, self.traces, self.configs, self.settings, 4)
        stage_config(self.draft, "scan", self.a, {"manual_segment": 1})
        configs, _ = self.build()
        self.assertEqual(configs[self.a]["manual_segment"], 1)

    def test_self_missing_nonbackground_and_cyclic_bindings_are_rejected(self):
        for bg in (self.a, "missing", self.b):
            with self.subTest(background=bg):
                draft = new_draft(4)
                stage_config(draft, "binding", self.a, {"background_disk": bg})
                with self.assertRaises(DataError):
                    candidate(draft, self.traces, self.configs, self.settings, 4)
        stage_config(self.draft, "binding", self.bg, {"background_disk": self.bg2})
        stage_config(self.draft, "binding", self.bg2, {"background_disk": self.bg})
        with self.assertRaisesRegex(DataError, "循环"):
            self.build()

    def test_paired_mapping_and_bad_axis_rejected_atomically(self):
        stage_config(self.draft, "binding", self.a, {"background_mode": "paired", "background_disk": self.bg,
                     "background_ring": self.bg2})
        with self.assertRaisesRegex(DataError, "同一个背景"):
            self.build()
        draft = new_draft(4)
        stage_settings(draft, "axis", {"axis": "SHE"})
        with self.assertRaisesRegex(DataError, "电位坐标"):
            candidate(draft, self.traces, self.configs, self.settings, 4)

    def test_pairing_normalizes_previous_independent_ring_before_graph_validation(self):
        # A disk-only clear in the paired UI must clear both effective links,
        # rather than checking a previous independent ring binding as active.
        self.configs[self.a].update(background_mode="independent", background_ring=self.bg)
        self.configs[self.bg].update(role="样品")
        stage_config(self.draft, "binding", self.a, {"background_mode": "paired", "background_disk": None})
        configs, _ = self.build()
        self.assertIsNone(configs[self.a]["background_disk"])
        self.assertIsNone(configs[self.a]["background_ring"])


if __name__ == "__main__":
    unittest.main()
