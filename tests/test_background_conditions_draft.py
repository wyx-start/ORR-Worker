"""Canonical background records and guarded scientific drafts (synthetic only)."""
from __future__ import annotations

import copy
import unittest

import numpy as np

from orr_core import DataError, default_config, parse_chi
import settings_draft as drafts


def fixtures():
    """A shared background has independent records different from its sources."""
    traces, records, ids = {}, {}, {}
    for label, name in (("a", "Synthetic_A_900rpm.txt"),
                        ("b", "Synthetic_B_1600rpm.txt"),
                        ("bg", "Ar_synthetic_background.txt")):
        rows = "\n".join(f"{potential:.1f},-0.0001,0.000002"
                         for potential in np.linspace(1., 0., 11))
        raw = ("SYNTHETIC TEST INPUT - NOT EXPERIMENTAL DATA\n"
               "Linear Sweep Voltammetry\nHigh E (V) = 1\nLow E (V) = 0\n"
               "Scan Rate (V/s) = 0.005\nSample Interval (V) = 0.1\n"
               "Potential/V,i1/A,i2/A\n"+rows).encode("utf-8")
        trace = parse_chi(name, raw)
        config = default_config(trace)
        config.update(group="synthetic", manual_segment=1, pH=13., temperature_C=25.,
                      potential_method="理论换算", reference="Ag/AgCl",
                      filling="饱和 KCl", ref_V_SHE=.197, reference_preset_C=None,
                      reference_source="synthetic reference record", rhe_offset_V=0.,
                      electrolyte="O2 synthetic sample", collection_efficiency=.37,
                      background_conditions_mode="follow", background_conditions_migration={})
        config["parameter_sources"].update({
            "pH":"synthetic source", "temperature_C":"synthetic source",
            "reference":"synthetic source", "ref_V_SHE":"synthetic source"})
        traces[trace.id], records[trace.id], ids[label] = trace, config, trace.id
    background = records[ids["bg"]]
    background.update(role="背景", group="background", pH=11., temperature_C=20.,
                      reference="Independent reference", filling="independent filling",
                      ref_V_SHE=.110, reference_source="independent reference record",
                      rhe_offset_V=.81, electrolyte="Ar synthetic background")
    background["parameter_sources"].update({
        "pH":"independent pH record", "temperature_C":"independent temperature record",
        "reference":"independent reference record", "ref_V_SHE":"independent reference record"})
    for label in ("a", "b"):
        records[ids[label]].update(background_mode="paired", background_disk=ids["bg"],
                                   background_ring=ids["bg"], background_reviewed=True)
    return traces, records, {"axis":"RHE", "plot":{}, "presets":{}}, ids


class BackgroundConditionDraftTests(unittest.TestCase):
    def setUp(self):
        self.traces, self.records, self.settings, self.ids = fixtures()
        self.draft = drafts.new_draft(7)
        self.a, self.b, self.bg = (self.ids[key] for key in ("a", "b", "bg"))

    def build(self):
        return drafts.candidate(self.draft, self.traces, self.records, self.settings, 7)

    def test_candidate_keeps_independent_records_in_follow_mode(self):
        before = copy.deepcopy((self.records, self.settings, self.draft))
        records, settings = self.build()
        self.assertEqual(records[self.bg]["background_conditions_mode"], "follow")
        self.assertEqual(records[self.bg]["pH"], 11.)
        self.assertEqual(records[self.bg]["temperature_C"], 20.)
        self.assertEqual(records[self.bg]["ref_V_SHE"], .110)
        self.assertNotIn("background_conditions", records[self.bg])
        self.assertEqual((self.records, self.settings, self.draft), before)
        records[self.bg]["parameter_sources"]["pH"] = "detached"
        settings["axis"] = "原始"
        self.assertEqual(self.records[self.bg]["parameter_sources"]["pH"], "independent pH record")
        self.assertEqual(self.settings["axis"], "RHE")

    def test_derived_projection_keys_cannot_be_used_as_persistent_patches(self):
        patches = ({"background_conditions":{"effective":{"pH":13.}}},
                   {"background_ph_status":"following"},
                   {"background_ph_sources":[]},
                   {"background_ph_detail":"synthetic projection"})
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(DataError):
                drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], patch)

    def test_follow_controlled_fields_require_an_explicit_independent_mode(self):
        patches = ({"pH":12.}, {"temperature_C":30.}, {"ref_V_SHE":.207},
                   {"potential_method":"实测 RHE 总偏移"}, {"rhe_offset_V":0.},
                   {"parameter_sources":{"pH":"overwrite independent provenance"}})
        for patch in patches:
            with self.subTest(patch=patch), self.assertRaises(DataError):
                drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], patch)

    def test_forbidden_follow_write_does_not_partially_commit_candidate(self):
        drafts.stage_config(self.draft, "conditions", self.a, {"pH":14.})
        drafts.stage_config(self.draft, "background", self.bg, {"pH":12.})
        before = copy.deepcopy((self.records, self.settings, self.draft))
        with self.assertRaises(DataError):
            self.build()
        self.assertEqual((self.records, self.settings, self.draft), before)

    def test_mode_and_independent_values_in_one_patch_are_valid_and_canonical(self):
        patch = {"background_conditions_mode":"independent", "pH":12.,
                 "temperature_C":22., "parameter_sources":{"pH":"explicit independent edit"}}
        drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], patch)
        drafts.stage_config(self.draft, "background_conditions:"+self.bg, self.bg, patch)
        records, _ = self.build()
        self.assertEqual(records[self.bg]["background_conditions_mode"], "independent")
        self.assertEqual(records[self.bg]["pH"], 12.)
        self.assertEqual(records[self.bg]["temperature_C"], 22.)
        self.assertEqual(records[self.bg]["parameter_sources"]["pH"], "explicit independent edit")
        self.assertEqual(records[self.bg]["ref_V_SHE"], .110)
        self.assertEqual(self.records[self.bg]["pH"], 11.)

    def test_switching_only_strategy_never_copies_source_values_into_records(self):
        self.records[self.bg]["background_conditions_mode"] = "independent"
        drafts.stage_config(self.draft, "background_conditions:"+self.bg, self.bg,
                            {"background_conditions_mode":"follow"})
        records, _ = self.build()
        self.assertEqual(records[self.bg]["pH"], 11.)
        self.assertEqual(records[self.bg]["ref_V_SHE"], .110)
        next_draft = drafts.new_draft(8)
        drafts.stage_config(next_draft, "background_conditions:"+self.bg, self.bg,
                            {"background_conditions_mode":"independent"})
        restored, _ = drafts.candidate(next_draft, self.traces, records, self.settings, 8)
        self.assertEqual(restored[self.bg]["pH"], 11.)
        self.assertEqual(restored[self.bg]["parameter_sources"]["pH"], "independent pH record")

    def test_noninherited_fields_remain_editable_while_following(self):
        patch = {"electrolyte":"Ar only independent note", "ring_material":"Pt"}
        drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], patch)
        drafts.stage_config(self.draft, "notes", self.bg, patch)
        records, _ = self.build()
        self.assertEqual(records[self.bg]["electrolyte"], "Ar only independent note")
        self.assertEqual(records[self.bg]["background_conditions_mode"], "follow")
        self.assertEqual(records[self.bg]["pH"], 11.)

    def test_equal_record_value_does_not_implicitly_change_strategy(self):
        drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], {"pH":11.})
        drafts.stage_config(self.draft, "same_value", self.bg, {"pH":11.})
        records, _ = self.build()
        self.assertEqual(records[self.bg]["background_conditions_mode"], "follow")
        self.assertEqual(records[self.bg]["pH"], 11.)

    def test_legacy_ph_controls_only_the_currently_followed_ph(self):
        self.records[self.bg].update(background_conditions_mode="legacy_ph", background_ph_mode="follow")
        drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], {"ref_V_SHE":.207})
        with self.assertRaises(DataError):
            drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg], {"pH":12.})
        drafts.validate_config_patch(self.traces[self.bg], self.records[self.bg],
                                     {"pH":12., "background_ph_mode":"manual"})

    def test_missing_and_conflicting_sources_are_saved_without_materializing_effective_values(self):
        for value in (None, 12.):
            with self.subTest(source_ph=value):
                draft = drafts.new_draft(7)
                drafts.stage_config(draft, "conditions", self.b, {"pH":value})
                records, _ = drafts.candidate(draft, self.traces, self.records, self.settings, 7)
                self.assertEqual(records[self.bg]["pH"], 11.)
                self.assertEqual(records[self.b]["pH"], value)
                self.assertNotIn("background_conditions", records[self.bg])


if __name__ == "__main__":
    unittest.main()
