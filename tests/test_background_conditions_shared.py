"""Shared candidate views and commit isolation for background inheritance."""
from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

from orr_core import DataError
from settings_draft import new_draft
from test_background_conditions_draft import fixtures
import ui_shared as ui


class State(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class BackgroundConditionSharedTests(unittest.TestCase):
    def setUp(self):
        traces, records, settings, ids = fixtures()
        self.a, self.b, self.bg = (ids[key] for key in ("a", "b", "bg"))
        self.state = State(traces=traces, configs=records, settings=settings,
                           revision=7, settings_draft=new_draft(7), draft_epoch=0,
                           workspace_epoch=0, import_errors=[], common_defaults={},
                           results={"kl":"existing result"},
                           exports={"existing.csv":{"bytes":b"previous", "mime":"text/csv"}})
        self.state_patch = patch.object(ui.st, "session_state", self.state)
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def snapshot(self):
        return copy.deepcopy({key:self.state[key] for key in
                              ("configs", "settings", "revision", "settings_draft", "results", "exports")})

    def assert_stored_background_unchanged(self):
        self.assertEqual(self.state.configs[self.bg]["pH"], 11.)
        self.assertEqual(self.state.configs[self.bg]["temperature_C"], 20.)
        self.assertEqual(self.state.configs[self.bg]["ref_V_SHE"], .110)
        self.assertEqual(self.state.configs[self.bg]["parameter_sources"]["pH"], "independent pH record")
        self.assertNotIn("background_conditions", self.state.configs[self.bg])

    def test_applied_view_separates_effective_values_and_independent_records(self):
        before = self.snapshot()
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied")
        self.assertFalse(view["has_pending"])
        self.assertEqual(view["records"][self.bg]["pH"], 11.)
        self.assertEqual(view["configs"][self.bg]["pH"], 13.)
        info = view["configs"][self.bg]["background_conditions"]
        self.assertEqual(info["mode"], "follow")
        self.assertEqual(info["independent"]["pH"], 11.)
        self.assertEqual(info["effective"]["pH"], 13.)
        self.assertFalse(info["field_states"]["pH"]["editable"])
        self.assertEqual({sample["id"] for sample in info["linked_samples"]}, {self.a, self.b})
        self.assertEqual(view["settings"]["axis"], "RHE")
        self.assertEqual(ui.get_draft_configs()[self.bg]["pH"], 13.)
        self.assertEqual(self.snapshot(), before)
        view["records"][self.bg]["pH"] = -1.
        view["configs"][self.bg]["background_conditions"]["independent"]["pH"] = -2.
        self.assert_stored_background_unchanged()

    def test_valid_candidate_is_resolved_but_pending_candidate_stays_canonical(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.a:{"pH":14.}, self.b:{"pH":14.}}))
        ui.stage_settings_updates("axis", {"axis":"原始"})
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "candidate")
        self.assertTrue(view["has_pending"])
        self.assertEqual(view["records"][self.bg]["pH"], 11.)
        self.assertEqual(view["configs"][self.bg]["pH"], 14.)
        self.assertEqual(view["settings"]["axis"], "原始")
        records, settings = ui.pending_candidate()
        self.assertEqual(records[self.bg]["pH"], 11.)
        self.assertNotIn("background_conditions", records[self.bg])
        self.assertEqual(settings["axis"], "原始")
        self.assertEqual(self.state.settings["axis"], "RHE")
        self.assert_stored_background_unchanged()

    def test_invalid_structure_uses_real_applied_fallback_and_preserves_raw_domain_edits(self):
        # Per-patch gates must allow a repairable structural error into staging;
        # strict candidate construction is where an invalid channel is rejected.
        self.assertTrue(ui.stage_config_updates("scan", {self.a:{"disk_channel":99}}))
        ui.stage_settings_updates("axis", {"axis":"原始"})
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied_fallback")
        self.assertEqual(view["records"][self.a]["disk_channel"], 0)
        self.assertEqual(view["configs"][self.a]["disk_channel"], 0)
        self.assertEqual(view["configs"][self.bg]["pH"], 13.)
        self.assertEqual(view["settings"]["axis"], "RHE")
        self.assertEqual(view["staged_edits"]["scan"][self.a]["disk_channel"], 99)
        self.assertEqual(view["staged_setting_edits"]["axis"]["axis"], "原始")
        self.assertTrue(view["errors"])
        self.assertEqual(ui.get_draft_configs()[self.a]["disk_channel"], 0)
        with self.assertRaises(DataError):
            ui.apply_pending_settings()
        self.assertEqual(self.state.configs[self.a]["disk_channel"], 0)
        self.assertEqual(self.state.revision, 7)
        self.assertTrue(ui.has_draft())

    def test_local_validation_error_alone_marks_fallback_and_blocks_strict_commit(self):
        domain = "conditions:local-invalid-input"
        self.state.draft_errors = {domain:"synthetic local validation failure"}
        self.state.pop("draft_error", None)
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied_fallback")
        self.assertTrue(view["has_pending"])
        self.assertIn(domain, view["rejected_domains"])
        self.assertTrue(any(error.get("domain") == domain for error in view["errors"]))
        self.assertEqual(view["records"][self.bg]["pH"], 11.)
        self.assertEqual(view["configs"][self.bg]["pH"], 13.)
        self.assertEqual(view["rejected_edits"], {})
        with self.assertRaises(DataError):
            ui.pending_candidate()

    def test_rejected_domain_forces_fallback_even_when_accepted_candidate_can_parse(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.a:{"pH":14.}}))
        self.assertFalse(ui.stage_config_updates("conflicting_editor", {self.a:{"pH":12.}}))
        self.assertTrue(ui.stage_config_updates("unrelated_scan", {self.b:{"direction":"递增"}}))
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied_fallback")
        self.assertEqual(view["configs"][self.a]["pH"], 13.)
        self.assertEqual(view["staged_edits"]["conditions"][self.a]["pH"], 14.)
        self.assertEqual(view["rejected_edits"]["conflicting_editor"][self.a]["pH"], 12.)
        self.assertIn("conflicting_editor", view["rejected_domains"])
        self.assertTrue(any(error.get("domain") == "conflicting_editor" for error in view["errors"]))
        with self.assertRaises(DataError):
            ui.apply_pending_settings()
        self.assertEqual(self.state.revision, 7)

    def test_new_local_error_cannot_be_cleared_by_replaying_an_older_conflict(self):
        domain = "conditions:local-editor"
        old_edits = {self.a:{"pH":12.}}
        self.assertTrue(ui.stage_config_updates("conditions:peer", {self.a:{"pH":14.}}))
        self.assertFalse(ui.stage_config_updates(domain, old_edits))
        self.assertTrue(self.state.draft_retryable_domains[domain])
        self.assertFalse(ui.reject_config_updates(domain, None, "new synthetic invalid input"))
        self.assertFalse(self.state.draft_retryable_domains[domain])

        # Resolving the former conflict must not resurrect an input superseded
        # by a newer local failure in the same editor.
        self.assertTrue(ui.stage_config_updates("conditions:peer", {self.a:{"pH":12.}}))
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied_fallback")
        self.assertEqual(view["rejected_edits"][domain], old_edits)
        self.assertNotIn(domain, view["staged_edits"])
        self.assertEqual(self.state.draft_errors[domain], "new synthetic invalid input")
        self.assertEqual(self.state.configs[self.a]["pH"], 13.)
        with self.assertRaisesRegex(DataError, "new synthetic invalid input"):
            ui.apply_pending_settings()
        self.assertEqual(self.state.revision, 7)

        # Only a fresh successful edit by this domain clears its local error.
        self.assertTrue(ui.stage_config_updates(domain, old_edits))
        self.assertNotIn(domain, self.state.get("draft_errors", {}))
        self.assertNotIn(domain, self.state.get("rejected_config_edits", {}))
        self.assertTrue(ui.apply_pending_settings())
        self.assertEqual(self.state.configs[self.a]["pH"], 12.)
        self.assertEqual(self.state.revision, 8)

    def test_stale_revision_preserves_edits_without_showing_them_as_applied(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.a:{"pH":14.}}))
        self.state.revision = 8
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied_fallback")
        self.assertEqual(view["revision"], 8)
        self.assertEqual(view["records"][self.a]["pH"], 13.)
        self.assertEqual(view["staged_edits"]["conditions"][self.a]["pH"], 14.)
        with self.assertRaises(DataError):
            ui.pending_candidate()

    def test_multi_target_rejection_keeps_all_previous_records_and_accepted_drafts(self):
        before = self.snapshot()
        domain = "conditions:mixed-targets"
        edits = {self.a:{"pH":14.}, self.bg:{"pH":12.}}
        self.assertFalse(ui.stage_config_updates(domain, edits))
        self.assertEqual(self.snapshot(), before)
        view = ui.get_draft_view()
        self.assertEqual(view["rejected_edits"][domain], edits)
        self.assertEqual(view["staged_edits"], {})
        self.assertEqual(view["view_basis"], "applied_fallback")

    def test_mode_and_value_share_a_single_accepted_domain_before_commit(self):
        domain = "background_conditions:"+self.bg
        edits = {self.bg:{"background_conditions_mode":"independent", "pH":12.,
                          "parameter_sources":{"pH":"explicit independent input"}}}
        self.assertTrue(ui.stage_config_updates(domain, edits))
        view = ui.get_draft_view()
        self.assertEqual(view["staged_edits"][domain][self.bg]["background_conditions_mode"], "independent")
        self.assertEqual(view["staged_edits"][domain][self.bg]["pH"], 12.)
        self.assertEqual(view["configs"][self.bg]["pH"], 12.)
        self.assertEqual(self.state.configs[self.bg]["background_conditions_mode"], "follow")
        self.assertTrue(ui.apply_pending_settings())
        self.assertEqual(self.state.configs[self.bg]["background_conditions_mode"], "independent")
        self.assertEqual(self.state.configs[self.bg]["pH"], 12.)
        self.assertEqual(self.state.configs[self.bg]["parameter_sources"]["pH"], "explicit independent input")
        self.assertEqual(self.state.revision, 8)

    def test_failed_preflight_receives_canonical_candidate_and_commits_nothing(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.a:{"pH":14.}, self.b:{"pH":14.}}))
        ui.stage_settings_updates("axis", {"axis":"原始"})
        before = self.snapshot()

        def reject(records, settings):
            self.assertEqual(records[self.bg]["pH"], 11.)
            self.assertNotIn("background_conditions", records[self.bg])
            self.assertEqual(records[self.a]["pH"], 14.)
            self.assertEqual(settings["axis"], "原始")
            raise DataError("synthetic task preflight failure")

        with self.assertRaisesRegex(DataError, "synthetic task"):
            ui.apply_pending_settings(preflight=reject)
        self.assertEqual(self.snapshot(), before)

    def test_mode_only_replacement_does_not_replay_unapplied_independent_fields(self):
        domain = "background_conditions:"+self.bg
        self.assertTrue(ui.stage_config_updates(domain, {self.bg:{
            "background_conditions_mode":"independent", "pH":12.,
            "parameter_sources":{"pH":"unapplied independent edit"}}}))
        self.assertEqual(ui.get_draft_view()["configs"][self.bg]["pH"], 12.)
        self.assertTrue(ui.stage_config_updates(domain, {self.bg:{
            "background_conditions_mode":"follow"}}, replace=True))
        self.assertFalse(ui.has_draft())
        self.assert_stored_background_unchanged()
        self.assertEqual(ui.get_draft_view()["configs"][self.bg]["pH"], 13.)

    def test_preflight_also_checks_the_unchanged_applied_snapshot(self):
        before = self.snapshot()

        def reject(records, settings):
            self.assertEqual(records[self.bg]["pH"], 11.)
            self.assertNotIn("background_conditions", records[self.bg])
            raise DataError("synthetic applied preflight failure")

        with self.assertRaisesRegex(DataError, "applied preflight"):
            ui.apply_pending_settings(preflight=reject)
        self.assertEqual(self.snapshot(), before)

    def test_stale_empty_draft_cannot_bypass_the_shared_apply_entry(self):
        self.state.settings_draft["base_revision"] = 6
        with self.assertRaisesRegex(DataError, "旧修订"):
            ui.apply_pending_settings()
        self.assertEqual(self.state.revision, 7)
        self.assert_stored_background_unchanged()

    def test_successful_apply_and_invalidate_never_materialize_followed_values(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.a:{"pH":14.}, self.b:{"pH":14.}}))
        self.assertTrue(ui.apply_pending_settings())
        self.assert_stored_background_unchanged()
        self.assertEqual(self.state.results, {})
        self.assertEqual(self.state.exports, {})
        self.assertEqual(self.state.revision, 8)
        self.assertFalse(ui.has_draft())
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "applied")
        self.assertEqual(view["configs"][self.bg]["pH"], 14.)
        ui.invalidate()
        self.assert_stored_background_unchanged()

    def test_effective_projection_cannot_be_written_back_as_a_configuration(self):
        projected = ui.get_draft_view()["configs"][self.bg]
        before = self.snapshot()
        self.assertFalse(ui.stage_config_updates("incorrect_projection_copy", {self.bg:projected}))
        self.assertEqual(self.snapshot(), before)
        self.assertIn("background_conditions", ui.get_draft_view()["rejected_edits"]["incorrect_projection_copy"][self.bg])
        self.assert_stored_background_unchanged()

    def test_legal_shared_conflict_is_candidate_state_not_a_persistent_value(self):
        self.assertTrue(ui.stage_config_updates("conditions", {self.b:{"pH":12.}}))
        view = ui.get_draft_view()
        self.assertEqual(view["view_basis"], "candidate")
        self.assertEqual(view["configs"][self.bg]["background_conditions"]["status"], "conflict")
        self.assertEqual(view["records"][self.bg]["pH"], 11.)
        self.assertTrue(ui.apply_pending_settings())
        self.assert_stored_background_unchanged()

    def test_initialize_migrates_an_old_follow_session_once_and_keeps_draft_revision(self):
        for record in self.state.configs.values():
            record.pop("background_conditions_mode", None)
            record.pop("background_conditions_migration", None)
        background = self.state.configs[self.bg]
        background.update(pH=13., background_ph_mode="follow", background_ph_legacy=False)
        saved_source = background["parameter_sources"]["pH"]
        self.state.settings_draft["configs"] = {"conditions":{self.a:{"electrolyte":"pending synthetic note"}}}
        before_draft = copy.deepcopy(self.state.settings_draft)
        ui.initialize()
        migrated = self.state.configs[self.bg]
        self.assertEqual(migrated["background_conditions_mode"], "legacy_ph")
        self.assertEqual(migrated["background_ph_mode"], "follow")
        self.assertIsNone(migrated["pH"])
        self.assertEqual(migrated["background_conditions_migration"]["saved_ph_snapshot"], 13.)
        self.assertEqual(migrated["background_conditions_migration"]["saved_ph_source"], saved_source)
        self.assertEqual(self.state.revision, 7)
        self.assertEqual(self.state.settings_draft, before_draft)
        self.assertEqual(self.state.results, {})
        self.assertEqual(self.state.exports, {})
        migrated_once = copy.deepcopy(self.state.configs)
        ui.initialize()
        self.assertEqual(self.state.configs, migrated_once)

    def test_initialize_keeps_earliest_manual_record_and_reference_independent(self):
        background = self.state.configs[self.bg]
        for field in ("background_conditions_mode", "background_conditions_migration",
                      "background_ph_mode", "background_ph_legacy"):
            background.pop(field, None)
        ui.initialize()
        migrated = self.state.configs[self.bg]
        self.assertEqual(migrated["background_conditions_mode"], "legacy_ph")
        self.assertEqual(migrated["background_ph_mode"], "manual")
        self.assertTrue(migrated["background_ph_legacy"])
        self.assertEqual(migrated["pH"], 11.)
        self.assertEqual(migrated["ref_V_SHE"], .110)
        self.assertEqual(migrated["temperature_C"], 20.)


if __name__ == "__main__":
    unittest.main()
