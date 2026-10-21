"""Synthetic regression coverage for the shared staging and editor adapters."""
import copy
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import ui_shared
from background_ph import synchronize_ph_links
from orr_core import DataError
from settings_draft import new_draft
from test_settings_draft import fixtures


class State(dict):
    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


class SharedDraftAdapterTests(unittest.TestCase):
    def setUp(self):
        traces, configs, settings = fixtures()
        self.a, self.b, self.bg, self.bg2 = traces
        self.state = State(traces=traces, configs=configs, settings=settings, revision=4,
                           settings_draft=new_draft(4), draft_epoch=0,
                           results={"kl": "existing"}, exports={"old.csv": "existing"})
        self.mock_state = patch.object(ui_shared.st, "session_state", self.state)
        self.mock_state.start()
        self.addCleanup(self.mock_state.stop)

    def test_reverting_config_and_global_axis_removes_pending_change(self):
        self.assertTrue(ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}}))
        self.assertTrue(ui_shared.has_draft())
        self.assertTrue(ui_shared.stage_config_updates("conditions", {self.a: {"pH": None}}))
        self.assertFalse(ui_shared.has_draft())
        ui_shared.stage_settings_updates("axis", {"axis": "原始"})
        self.assertTrue(ui_shared.has_draft())
        ui_shared.stage_settings_updates("axis", {"axis": "RHE"})
        self.assertFalse(ui_shared.has_draft())
        self.assertEqual(self.state.revision, 4)
        self.assertEqual(self.state.results, {"kl": "existing"})

    def test_conflicting_visible_draft_is_not_unblocked_by_editing_unrelated_domain(self):
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}})
        self.assertFalse(ui_shared.stage_config_updates("background_editor", {self.a: {"pH": 12.}}))
        self.assertTrue(self.state.get("draft_error"))
        ui_shared.stage_config_updates("scan", {self.b: {"direction": "递增"}})
        with self.assertRaises(DataError):
            ui_shared.apply_pending_settings()
        self.assertIsNone(self.state.configs[self.a]["pH"])
        self.assertEqual(self.state.revision, 4)

    def test_resolving_the_failed_domain_clears_its_error(self):
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}})
        self.assertFalse(ui_shared.stage_config_updates("other", {self.a: {"pH": 12.}}))
        self.assertTrue(ui_shared.stage_config_updates("other", {self.a: {"pH": 13.}}))
        self.assertFalse(self.state.get("draft_error"))
        self.assertTrue(ui_shared.apply_pending_settings())
        self.assertEqual(self.state.configs[self.a]["pH"], 13.)
        self.assertEqual(self.state.revision, 5)
        self.assertFalse(ui_shared.has_draft())

    def test_rejected_visible_edit_is_retried_when_its_conflicting_peer_is_resolved(self):
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}})
        self.assertFalse(ui_shared.stage_config_updates("other", {self.a: {"pH": 12.}}))
        self.assertTrue(ui_shared.stage_config_updates("conditions", {self.a: {"pH": 12.}}))
        self.assertFalse(self.state.get("draft_error"))
        self.assertEqual(ui_shared.get_draft_configs()[self.a]["pH"], 12.)
        self.assertTrue(ui_shared.apply_pending_settings())
        self.assertEqual(self.state.configs[self.a]["pH"], 12.)

    def test_import_does_not_silently_clear_other_pending_scientific_settings(self):
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}})
        draft = copy.deepcopy(self.state.settings_draft)
        with patch.object(ui_shared, "cached_parse") as parse:
            with self.assertRaisesRegex(DataError, "草稿|未应用"):
                ui_shared.add_files([("new.txt", b"synthetic")])
            parse.assert_not_called()
        self.assertEqual(self.state.settings_draft, draft)
        self.assertEqual(self.state.revision, 4)
        self.assertIsNone(self.state.configs[self.a]["pH"])

    def test_failed_preflight_keeps_configs_settings_results_and_draft(self):
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 13.}})
        ui_shared.stage_settings_updates("axis", {"axis": "原始"})
        before = copy.deepcopy({key: value for key, value in self.state.items() if key != "traces"})

        def rejected(configs, settings):
            self.assertEqual(configs[self.a]["pH"], 13.)
            self.assertEqual(settings["axis"], "原始")
            raise DataError("synthetic preflight failure")

        with self.assertRaisesRegex(DataError, "synthetic"):
            ui_shared.apply_pending_settings(rejected)
        self.assertEqual({key: value for key, value in self.state.items() if key != "traces"}, before)

    def test_preview_resolves_background_ph_without_changing_applied_config(self):
        self.state.configs[self.a].update(pH=13., background_disk=self.bg, background_ring=self.bg)
        synchronize_ph_links(self.state.configs)
        self.assertEqual(self.state.configs[self.bg]["pH"], 13.)
        ui_shared.stage_config_updates("conditions", {self.a: {"pH": 12.}})
        preview = ui_shared.get_draft_configs()
        self.assertEqual(preview[self.bg]["pH"], 12.)
        self.assertEqual(self.state.configs[self.bg]["pH"], 13.)
        self.assertIn("12", preview[self.bg]["background_ph_detail"])

    def test_invalid_preview_keeps_applied_values_and_draft_available_for_repair(self):
        ui_shared.stage_config_updates("scan", {self.a: {"disk_channel": 99}})
        self.assertEqual(ui_shared.get_draft_configs()[self.a]["disk_channel"], 99)
        with self.assertRaises(DataError):
            ui_shared.apply_pending_settings()
        self.assertEqual(self.state.configs[self.a]["disk_channel"], 0)
        self.assertTrue(ui_shared.has_draft())
        self.assertEqual(self.state.results, {"kl": "existing"})


EDITOR_APP = '''
import streamlit as st
from test_settings_draft import fixtures
from settings_draft import new_draft
from ui_shared import initialize
import settings_editor

initialize()
if "synthetic_editor_ready" not in st.session_state:
    traces, configs, settings = fixtures()
    for trace in traces.values():
        trace.header["raw_text"] = "SYNTHETIC TEST HEADER"
    st.session_state.update(traces=traces, configs=configs, settings=settings,
        revision=4, settings_draft=new_draft(4), synthetic_editor_ready=True)
settings_editor.per_file_form()
'''


class SharedEditorTests(unittest.TestCase):
    def test_opening_editor_and_switching_source_never_stages_implicit_changes(self):
        at = AppTest.from_string(EDITOR_APP, default_timeout=30).run()
        self.assertEqual(len(at.exception), 0)
        before = copy.deepcopy(at.session_state.configs)
        source = next(widget for widget in at.selectbox if widget.label == "要检查的文件")
        source.set_value(list(at.session_state.traces)[2]).run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state.configs, before)
        self.assertFalse(any(at.session_state.settings_draft["configs"].values()))

    def test_unsegmentable_trace_has_repair_message_instead_of_page_crash(self):
        at = AppTest.from_string(EDITOR_APP, default_timeout=30).run()
        first = next(iter(at.session_state.traces))
        at.session_state.traces[first].values[:, 0] = .5
        at.run()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(at.warning or at.error)


if __name__ == "__main__":
    unittest.main()
