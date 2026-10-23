from copy import deepcopy
import math
import unittest

from background_conditions import (INHERITED_FIELDS, activate_links, canonical_config,
    canonical_configs, condition_error, controlled_fields, default_background_conditions,
    resolved_configs)


def fixture():
    sample = dict(role="样品", potential_method="理论换算", pH=13., temperature_C=25.,
                  reference="Ag/AgCl", filling="3 M KCl", ref_V_SHE=.207,
                  reference_source="source A", reference_preset_C=25., rhe_offset_V=.9,
                  background_disk="bg", background_ring="bg", parameter_sources={"pH": "manual"})
    background = dict(role="背景", potential_method="实测 RHE 总偏移", pH=11., temperature_C=20.,
                      reference="SCE", filling="KCl", ref_V_SHE=.241, reference_source="independent",
                      reference_preset_C=None, rhe_offset_V=.1, electrolyte="Ar saturated",
                      area_cm2=.5, collection_efficiency=.4, disk_channel=1, ring_channel=0,
                      direction="递增", manual_segment=7, ir_enabled=True, ir_ohm=12.,
                      parameter_sources={"pH": "independent measurement", "electrolyte": "Ar log"},
                      background_ph_mode="manual", background_ph_legacy=True,
                      **default_background_conditions())
    return {"a": dict(sample, name="A", rpm=900), "b": dict(sample, name="B", rpm=1600), "bg": background}


class BackgroundConditionsTests(unittest.TestCase):
    def test_follow_is_pure_and_canonical_roundtrip_restores_every_independent_value(self):
        configs = fixture(); before = deepcopy(configs)
        view = resolved_configs(configs)
        self.assertEqual(configs, before)
        self.assertEqual(view["bg"]["pH"], 13.)
        self.assertEqual(view["bg"]["ref_V_SHE"], .207)
        self.assertIsNone(view["bg"]["rhe_offset_V"])
        self.assertEqual(canonical_configs(view), before)
        self.assertEqual(resolved_configs(view), view)
        self.assertEqual(view, resolved_configs(configs))
        bg = view["bg"]["background_conditions"]
        self.assertEqual(bg["independent"]["pH"], 11.)
        self.assertEqual(bg["independent_sources"]["pH"], "independent measurement")
        self.assertEqual(len(bg["linked_samples"]), 2)
        self.assertTrue(all(not state["editable"] for state in bg["field_states"].values()))

    def test_sparse_record_roundtrip_does_not_add_none_fields_or_sources(self):
        configs = {"a": dict(role="样品", pH=13., background_disk="bg"),
                   "bg": dict(role="背景", **default_background_conditions())}
        self.assertEqual(canonical_configs(resolved_configs(configs)), configs)

    def test_independent_follow_independent_keeps_original_and_noninherited_fields(self):
        configs = fixture()
        for field in ("electrolyte", "area_cm2", "collection_efficiency", "disk_channel", "ring_channel", "direction", "manual_segment", "ir_enabled", "ir_ohm"):
            self.assertEqual(resolved_configs(configs)["bg"][field], configs["bg"][field])
        configs["a"]["pH"] = configs["b"]["pH"] = 12.
        self.assertEqual(resolved_configs(configs)["bg"]["pH"], 12.)
        configs["bg"]["background_conditions_mode"] = "independent"
        bg = resolved_configs(configs)["bg"]
        self.assertEqual(bg["pH"], 11.)
        self.assertEqual(bg["rhe_offset_V"], .1)
        self.assertEqual(controlled_fields(configs["bg"]), set())

    def test_shared_conflicts_are_order_independent_and_record_details(self):
        configs = fixture(); configs["b"]["pH"] = 12.
        for ordered in (configs, dict(reversed(list(configs.items())))):
            bg = resolved_configs(ordered)["bg"]
            self.assertIsNone(bg["pH"])
            self.assertEqual(bg["background_conditions"]["status"], "conflict")
            self.assertIn("pH", condition_error(bg))
            self.assertEqual({s["id"] for s in bg["background_conditions"]["field_states"]["pH"]["conflicts"]}, {"a", "b"})
            self.assertEqual(controlled_fields(bg), set(INHERITED_FIELDS))

    def test_missing_one_source_never_backfills_it_and_known_zero_is_valid(self):
        configs = fixture(); configs["a"]["pH"] = 0.; configs["b"]["pH"] = None
        bg = resolved_configs(configs)["bg"]
        self.assertEqual(bg["pH"], 0.)
        self.assertIsNone(configs["b"]["pH"])
        self.assertEqual(len(bg["background_conditions"]["field_states"]["pH"]["sources"]), 2)

    def test_unbound_and_waiting_follow_remain_readonly_without_cached_fallback(self):
        configs = fixture()
        for sid in ("a", "b"):
            configs[sid]["background_disk"] = configs[sid]["background_ring"] = None
        view = resolved_configs(configs)["bg"]
        self.assertEqual(view["background_conditions"]["status"], "unbound")
        self.assertIsNone(view["pH"])
        self.assertEqual(view["background_conditions"]["independent"]["pH"], 11.)
        self.assertTrue(all(not state["editable"] for state in view["background_conditions"]["field_states"].values()))
        configs = fixture(); configs["a"]["pH"] = configs["b"]["pH"] = None
        self.assertEqual(resolved_configs(configs)["bg"]["background_conditions"]["status"], "waiting")

    def test_reference_is_one_stable_whole_snapshot_and_source_text_is_not_conflict(self):
        configs = fixture(); configs["a"].update(reference=None, filling=None, reference_source="source A")
        configs["b"]["reference_source"] = "source B"
        bg = resolved_configs(configs)["bg"]
        self.assertIsNone(condition_error(bg))
        self.assertEqual(bg["reference"], "Ag/AgCl")
        self.assertEqual(bg["reference_source"], "source B")
        self.assertEqual(bg["background_conditions"]["field_states"]["ref_V_SHE"]["representative_source"], "b")
        # The only voltage-bearing source has unknown metadata. Do not borrow
        # the other source's name/filling to construct a new reference scheme.
        configs["b"]["ref_V_SHE"] = None
        bg = resolved_configs(configs)["bg"]
        self.assertIsNone(bg["reference"])
        self.assertIsNone(bg["filling"])
        self.assertEqual(bg["ref_V_SHE"], .207)

    def test_known_partial_reference_difference_is_not_hidden_by_representative(self):
        configs = fixture(); configs["b"].update(ref_V_SHE=None, reference="SCE")
        bg = resolved_configs(configs)["bg"]
        self.assertIn("reference", condition_error(bg))

    def test_active_method_and_offset_zero_ignore_inactive_reference_caches(self):
        configs = fixture()
        for sid in ("a", "b"):
            configs[sid].update(potential_method="实测 RHE 总偏移", rhe_offset_V=0.)
        configs["b"].update(reference="old SCE", ref_V_SHE=-999.)
        bg = resolved_configs(configs)["bg"]
        self.assertIsNone(condition_error(bg))
        self.assertEqual(bg["rhe_offset_V"], 0.)
        self.assertIsNone(bg["ref_V_SHE"])
        self.assertFalse(bg["background_conditions"]["field_states"]["ref_V_SHE"]["active"])
        for sid in ("a", "b"):
            configs[sid]["potential_method"] = "已是 RHE"
        configs["b"]["rhe_offset_V"] = 42.
        self.assertIsNone(condition_error(resolved_configs(configs)["bg"]))
        configs["b"]["temperature_C"] = 30.
        self.assertIn("temperature_C", condition_error(resolved_configs(configs)["bg"]))

    def test_method_conflict_and_invalid_values_remain_explicit_states(self):
        configs = fixture(); configs["b"]["potential_method"] = "已是 RHE"
        self.assertIn("potential_method", condition_error(resolved_configs(configs)["bg"]))
        for value in (float("nan"), float("inf"), True, "bad"):
            configs = fixture(); configs["a"]["pH"] = value
            bg = resolved_configs(configs)["bg"]
            self.assertEqual(bg["background_conditions"]["field_states"]["pH"]["status"], "invalid")
            self.assertIsNotNone(condition_error(bg))

    def test_legacy_only_ph_preserves_other_conditions_and_canonical_submode(self):
        configs = fixture(); configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode="follow", pH=None)
        view = resolved_configs(configs)
        self.assertEqual(view["bg"]["pH"], 13.)
        self.assertEqual(view["bg"]["ref_V_SHE"], .241)
        self.assertEqual(view["bg"]["temperature_C"], 20.)
        self.assertEqual(controlled_fields(view["bg"]), {"pH"})
        self.assertEqual(canonical_configs(view), configs)

    def test_legacy_activation_matrix_does_not_expand_to_full_follow(self):
        for old_mode, ph, legacy, expected in (("auto", 0., False, "manual"), ("auto", None, False, "follow"),
                ("manual", None, True, "follow"), ("manual", 11., True, "manual"),
                ("manual", None, False, "manual"), ("follow", None, True, "follow")):
            with self.subTest(mode=old_mode, ph=ph, legacy=legacy):
                configs = fixture(); configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode=old_mode,
                                                        background_ph_legacy=legacy, pH=ph)
                independent = {field: configs["bg"].get(field) for field in INHERITED_FIELDS}
                activate_links(configs, ["bg", "bg"])
                self.assertEqual(configs["bg"]["background_ph_mode"], expected)
                self.assertEqual(configs["bg"]["background_conditions_mode"], "legacy_ph")
                self.assertFalse(configs["bg"]["background_ph_legacy"])
                self.assertEqual({field: configs["bg"].get(field) for field in INHERITED_FIELDS}, independent)

    def test_legacy_auto_read_and_manual_empty_permissions(self):
        configs = fixture(); configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode="auto", pH=None)
        self.assertEqual(controlled_fields(configs["bg"]), {"pH"})
        self.assertEqual(resolved_configs(configs)["bg"]["pH"], 13.)
        self.assertEqual(configs["bg"]["background_ph_mode"], "auto")
        configs["bg"].update(background_ph_mode="manual", background_ph_legacy=True)
        self.assertEqual(controlled_fields(configs["bg"]), set())
        self.assertIsNone(resolved_configs(configs)["bg"]["pH"])
        self.assertEqual(resolved_configs(configs)["bg"]["background_conditions"]["field_states"]["pH"]["editable"], True)

    def test_migration_history_is_never_rewritten_and_samples_are_not_controlled(self):
        configs = fixture(); configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode="follow", pH=None,
            background_conditions_migration={"source_schema": 1, "saved_ph_snapshot": 11., "saved_ph_source": "unknown", "independent_ph_status": "unknown_legacy_follow"})
        view = resolved_configs(configs)
        self.assertEqual(canonical_config(view["bg"]), configs["bg"])
        self.assertEqual(view["bg"]["background_conditions"]["migration"], configs["bg"]["background_conditions_migration"])
        self.assertEqual(controlled_fields(dict(configs["a"], **default_background_conditions())), set())

    def test_legacy_unbound_and_conflict_sources_are_not_misreported(self):
        configs = fixture(); configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode="follow", pH=None)
        configs["b"]["pH"] = 12.
        configs["c"] = dict(configs["a"], name="C", pH=None)
        state = resolved_configs(configs)["bg"]["background_conditions"]["field_states"]["pH"]
        self.assertEqual({source["id"] for source in state["conflicts"]}, {"a", "b"})
        configs = {"bg": configs["bg"]}
        self.assertEqual(resolved_configs(configs)["bg"]["background_conditions"]["status"], "unbound")
        self.assertFalse(resolved_configs(configs)["bg"]["background_conditions"]["field_states"]["pH"]["editable"])

    def test_unused_invalid_cache_does_not_become_an_active_independent_error(self):
        configs = fixture(); configs["bg"].update(background_conditions_mode="independent", potential_method="实测 RHE 总偏移", ref_V_SHE=float("nan"))
        bg = resolved_configs(configs)["bg"]
        self.assertIsNone(condition_error(bg))
        self.assertEqual(bg["background_conditions"]["field_states"]["ref_V_SHE"]["status"], "not_required")
        self.assertTrue(math.isnan(bg["background_conditions"]["independent"]["ref_V_SHE"]))

    def test_missing_controlled_values_never_reuse_independent_provenance(self):
        for case in ("waiting", "conflict", "unbound", "legacy_waiting"):
            with self.subTest(case=case):
                configs = fixture()
                if case in ("waiting", "legacy_waiting"):
                    configs["a"]["pH"] = configs["b"]["pH"] = None
                elif case == "conflict":
                    configs["b"]["pH"] = 12.
                else:
                    configs.pop("a"); configs.pop("b")
                if case == "legacy_waiting":
                    configs["bg"].update(background_conditions_mode="legacy_ph", background_ph_mode="follow")
                before = deepcopy(configs)
                bg = resolved_configs(configs)["bg"]
                view = bg["background_conditions"]
                self.assertIsNone(view["effective"]["pH"])
                self.assertNotIn("independent measurement", view["effective_sources"]["pH"])
                self.assertNotIn("independent measurement", bg["parameter_sources"]["pH"])
                self.assertIn("沿用关联样品", view["effective_sources"]["pH"])
                self.assertEqual(view["independent_sources"]["pH"], "independent measurement")
                self.assertEqual(canonical_configs(resolved_configs(configs)), before)
                self.assertEqual(configs, before)

    def test_missing_reference_and_inactive_offset_do_not_leak_cached_sources(self):
        configs = fixture()
        configs["bg"]["parameter_sources"].update(ref_V_SHE="independent reference source", rhe_offset_V="independent offset source")
        configs["a"]["ref_V_SHE"] = configs["b"]["ref_V_SHE"] = None
        bg = resolved_configs(configs)["bg"]
        view = bg["background_conditions"]
        for field, cached_source in (("ref_V_SHE", "independent reference source"), ("rhe_offset_V", "independent offset source")):
            self.assertIsNone(view["effective"][field])
            self.assertNotIn(cached_source, view["effective_sources"][field])
            self.assertEqual(view["independent_sources"][field], cached_source)

    def test_structural_errors_raise_valueerror_without_touching_input(self):
        for configs in ([], {"bg": []}, {"bg": dict(role="背景", background_conditions_mode="bad")}):
            with self.subTest(configs=configs):
                before = deepcopy(configs)
                with self.assertRaises(ValueError):
                    resolved_configs(configs)
                self.assertEqual(configs, before)


if __name__ == "__main__":
    unittest.main()
