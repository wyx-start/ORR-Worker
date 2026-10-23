"""Batch intentions, scientific defaults and preservation of draft boundaries."""
from copy import deepcopy
from io import BytesIO
import json
import unittest
from unittest.mock import patch
import zipfile

import numpy as np

from batch_settings import build_batch_updates
from orr_core import (DataError, default_config, pack_project, parse_chi, process_trace,
                      rrde_calculate, select_segment, unpack_project, set_manual_rpm)
from settings_draft import new_draft
from settings_editor import stage_background_mode
from test_background_conditions_draft import fixtures
from test_background_conditions_shared import State
import ui_shared as ui


class BatchSettingsTests(unittest.TestCase):
    def setUp(self):
        self.traces, self.records, self.settings, self.ids = fixtures()
        self.a, self.b, self.bg = [self.ids[k] for k in ("a", "b", "bg")]

    def test_keep_does_not_copy_unselected_parameters(self):
        before = deepcopy(self.records)
        updates, rows = build_batch_updates(self.traces, self.records, [self.a, self.b])
        self.assertEqual(updates, {})
        self.assertEqual(len(rows), 2)
        self.assertEqual(before, self.records)

    def test_auto_scan_uses_each_files_own_data(self):
        updates, rows = build_batch_updates(self.traces, self.records, [self.a, self.b], mode="B", direction="递减")
        self.assertTrue(all(row["清除人工段"] for row in rows))
        for ident, update in updates.items():
            self.assertEqual(set(update), {"mode", "direction", "manual_segment"})
            cfg = dict(self.records[ident], **update)
            selected = select_segment(self.traces[ident], cfg)
            self.assertEqual(selected["direction"], "递减")
            self.assertEqual(selected["points"], 11)
            self.assertIsNotNone(self.records[ident]["manual_segment"])

    def test_direction_alone_rejects_incompatible_manual_segment(self):
        with self.assertRaisesRegex(DataError, "人工段.*不相容"):
            build_batch_updates(self.traces, self.records, [self.a, self.b], direction="递增")

    def test_missing_auto_segment_is_savable_and_described(self):
        updates, rows = build_batch_updates(self.traces, self.records, [self.a], mode="A")
        self.assertIn("需人工选段", rows[0]["扫描预检查"])
        self.assertIsNone(updates[self.a]["manual_segment"])

    def test_pairing_preserves_background_records_and_channels(self):
        before = deepcopy(self.records)
        updates, rows = build_batch_updates(self.traces, self.records, [self.a, self.b],
            background_action="paired", disk=self.bg)
        for update in updates.values():
            self.assertEqual(update["background_disk"], self.bg)
            self.assertEqual(update["background_ring"], self.bg)
            self.assertEqual(update["background_mode"], "paired")
        self.assertEqual(before, self.records)
        self.assertNotIn(self.bg, updates)

    def test_disk_binding_keeps_ring_and_explicit_unbind_keeps_cache(self):
        updates, _ = build_batch_updates(self.traces, self.records, [self.a], background_action="disk", disk=None)
        self.assertIsNone(updates[self.a]["background_disk"])
        self.assertEqual(updates[self.a]["background_ring"], self.bg)
        self.assertEqual(updates[self.a]["background_mode"], "independent")
        updates, _ = build_batch_updates(self.traces, self.records, [self.a], background_action="none")
        self.assertIsNone(updates[self.a]["background_ring"])
        self.assertEqual(self.records[self.bg]["pH"], 11.)

    def test_mixed_single_channel_pairing_fails_without_partial_mutation(self):
        raw = b'Linear Sweep Voltammetry\nPotential/V,Current/A\n1,-0.001\n0.75,-0.002\n0.5,-0.002\n0.25,-0.002\n0,-0.002'
        trace = parse_chi("single.txt", raw)
        self.traces[trace.id] = trace
        self.records[trace.id] = default_config(trace)
        before = deepcopy(self.records)
        with self.assertRaisesRegex(DataError, "single.txt"):
            build_batch_updates(self.traces, self.records, [self.a, trace.id], background_action="paired", disk=self.bg)
        self.assertEqual(before, self.records)

    def test_background_target_is_scan_only(self):
        update, _ = build_batch_updates(self.traces, self.records, [self.bg], mode="B")
        self.assertIn(self.bg, update)
        with self.assertRaisesRegex(DataError, "背景文件只能"):
            build_batch_updates(self.traces, self.records, [self.a, self.bg], background_action="none")

    def test_missing_self_and_invalid_ring_mapping_reject(self):
        for bgid in ("missing", self.a):
            with self.subTest(bgid=bgid), self.assertRaises(DataError):
                build_batch_updates(self.traces, self.records, [self.a], background_action="disk", disk=bgid)
        self.records[self.bg]["ring_channel"] = None
        with self.assertRaisesRegex(DataError, "ring.*通道"):
            build_batch_updates(self.traces, self.records, [self.a], background_action="independent", ring=self.bg)

    def state(self):
        return State(traces=self.traces, configs=self.records, settings=self.settings,
            revision=0, settings_draft=new_draft(0), draft_epoch=0, results={"old":True}, exports={"old":True})

    def test_switch_mode_preserves_unrelated_fields_sources_and_other_files(self):
        state = self.state()
        with patch.object(ui.st, "session_state", state):
            ui.stage_config_updates(f"conditions:{self.bg}", {self.bg:{"electrolyte":"Ar retained",
                "parameter_sources":{"electrolyte":"user record"}}, self.a:{"rpm":1200.}})
            self.assertTrue(stage_background_mode(self.bg, "independent"))
            state.settings_draft["configs"][f"background_conditions:{self.bg}"][self.bg]["pH"] = 9.
            self.assertTrue(stage_background_mode(self.bg, "follow"))
            configs, _ = ui.pending_candidate()
            self.assertEqual(configs[self.bg]["pH"], 11.)
            self.assertEqual(configs[self.bg]["electrolyte"], "Ar retained")
            self.assertEqual(configs[self.bg]["parameter_sources"]["electrolyte"], "user record")
            self.assertEqual(configs[self.a]["rpm"], 1200.)

    def test_batch_conflict_preserves_both_intents_and_never_commits(self):
        state = self.state()
        before = deepcopy(self.records)
        with patch.object(ui.st, "session_state", state):
            ui.stage_config_updates("scan:individual", {self.a:{"mode":"A"}})
            # This differs from the stored default so the conflict is meaningful.
            ui.stage_config_updates("scan:individual", {self.a:{"direction":"递增"}})
            updates, _ = build_batch_updates(self.traces, self.records, [self.a, self.b], direction="递减", mode="B")
            # Explicit intents that restate the applied value still conflict.
            self.assertFalse(ui.stage_config_updates("batch_scan_background", updates, replace_domain=True, retain_intent=True))
            self.assertIn("batch_scan_background", state.rejected_config_edits)
            self.assertEqual(state.settings_draft["configs"]["scan:individual"][self.a]["direction"], "递增")
            self.assertEqual(state.configs, before)

    def test_batch_restage_replaces_only_own_targets_and_commits_once(self):
        state = self.state()
        with patch.object(ui.st, "session_state", state):
            ui.stage_config_updates("metadata", {self.a:{"rpm":1200.}})
            ui.stage_config_updates("batch_scan_background", {self.a:{"mode":"B"},self.b:{"mode":"B"}}, replace_domain=True)
            ui.stage_config_updates("batch_scan_background", {self.a:{"mode":"B"}}, replace_domain=True)
            self.assertNotIn(self.b, state.settings_draft["configs"]["batch_scan_background"])
            ui.apply_pending_settings()
            self.assertEqual(state.revision, 1)
            self.assertEqual(state.configs[self.a]["rpm"], 1200.)
            self.assertEqual(state.configs[self.b]["mode"], "A")
            self.assertEqual(state.results, {})

    def test_rrde_default_known_answer_and_old_project_values(self):
        self.assertEqual(default_config(self.traces[self.a])["collection_efficiency"], .369)
        self.records[self.a]["collection_efficiency"] = .369
        output = process_trace(self.traces[self.a], self.records[self.a], self.traces, self.records, "原始")
        # Background equals sample in this fixture; disable subtraction for answer.
        output = process_trace(self.traces[self.a], self.records[self.a], self.traces, self.records, "原始", subtract_background=False)
        result = rrde_calculate(output, self.records[self.a])
        q = 2e-6/.369
        self.assertAlmostEqual(result.n_RRDE.iloc[0], 4e-4/(1e-4+q))
        for value in (.37, None):
            self.records[self.a]["collection_efficiency"] = value
            project = pack_project(self.traces, self.records, self.settings)
            _, loaded, _ = unpack_project(project)
            self.assertEqual(loaded[self.a]["collection_efficiency"], value)
        result = rrde_calculate(output, dict(self.records[self.a], collection_efficiency=.369), floor_A=.001)
        self.assertTrue(result.n_RRDE.isna().all())

    def test_manual_rpm_roundtrip_and_full_data_csv(self):
        cfg = self.records[self.a]
        matches = deepcopy(cfg["rpm_matches"])
        set_manual_rpm(cfg, 1200.)
        _, loaded, _ = unpack_project(pack_project(self.traces, self.records, self.settings))
        self.assertEqual(loaded[self.a]["rpm"], 1200.)
        self.assertEqual(loaded[self.a]["rpm_source"], "manual")
        self.assertEqual(loaded[self.a]["rpm_matches"], matches)
        output = process_trace(self.traces[self.a], cfg, self.traces, self.records, "原始")
        frame = ui.merged_data({self.a:output})
        self.assertTrue((frame.rpm == 1200.).all())
        self.assertTrue((frame.rpm_source == "manual").all())


if __name__ == "__main__":
    unittest.main()
