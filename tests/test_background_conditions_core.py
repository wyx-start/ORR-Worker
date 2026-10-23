"""Synthetic processing and persistence checks for background condition inheritance."""
import copy
from io import BytesIO
import json
import unittest
import zipfile

import numpy as np

from background_conditions import activate_links, resolved_configs
from unconfigured_conditions import unconfigured_config
from orr_core import (DataError, default_config, migrate_background_config,
                      pack_project, parameter_record, parse_chi, potential_signature,
                      process_trace, rhe_shift, unpack_project)


def trace(name, scale=1., paired=False):
    potentials = [0., .2, .4, .6, .8, 1., .8, .6, .4, .2, 0.]
    lines = ["Cyclic Voltammetry", "Low E (V) = 0", "High E (V) = 1",
             "Sample Interval (V) = 0.2", "Scan Rate (V/s) = 0.005",
             "Potential/V, Current/A" + (", Current 2/A" if paired else "")]
    for potential in potentials:
        row = [potential, -scale * 1e-3 * (1 + potential)]
        if paired:
            row.append(scale * 1e-5 * (1 + potential))
        lines.append(",".join(map(str, row)))
    return parse_chi(name, "\n".join(lines).encode())


def fixture(*, two_samples=False, paired=False):
    sample = trace("sample-900rpm.txt", paired=paired)
    background = trace("Ar-background.txt", .1, paired=paired)
    traces = {item.id:item for item in (sample, background)}
    if two_samples:
        second = trace("sample-1600rpm.txt", paired=paired)
        traces[second.id] = second
    configs = {ident:unconfigured_config(item) for ident,item in traces.items()}
    for ident in traces:
        if ident == background.id:
            continue
        configs[ident].update(pH=13., temperature_C=25., ref_V_SHE=.197,
                             reference="Ag/AgCl", filling="3 M KCl", reference_preset_C=25.,
                             reference_source="synthetic reference", background_disk=background.id)
        configs[ident]["parameter_sources"].update(pH="synthetic sample", ref_V_SHE="synthetic calibration")
        if paired:
            configs[ident]["background_ring"] = background.id
    return sample, background, traces, configs


def rewrite_project(raw, change):
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(raw)) as source, zipfile.ZipFile(output, "w") as target:
        for name in source.namelist():
            contents = source.read(name)
            if name == "project.json":
                manifest = json.loads(contents)
                change(manifest)
                contents = json.dumps(manifest, ensure_ascii=False).encode()
            target.writestr(name, contents)
    return output.getvalue()


class BackgroundConditionCoreTests(unittest.TestCase):
    def test_new_defaults_are_canonical_follow_records(self):
        cfg = default_config(trace("Ar-new-background.txt"))
        self.assertEqual(cfg["background_conditions_mode"], "follow")
        self.assertEqual(cfg["pH"], 13.)
        self.assertEqual(cfg["reference"], "SCE")
        self.assertNotIn("background_ph_status", cfg)

    def test_processing_inherits_whole_group_without_mutating_records(self):
        sample, bg, traces, configs = fixture()
        before = copy.deepcopy(configs)
        result = process_trace(sample, configs[sample.id], traces, configs)
        np.testing.assert_allclose(result["data"].I_disk_A, -.0009 * (1 + result["data"].E_original_V))
        np.testing.assert_allclose(result["data"].E_V - result["data"].E_original_V, rhe_shift(configs[sample.id]))
        audit = result["backgrounds"][bg.id]
        self.assertEqual(audit["config"]["pH"], 13.)
        self.assertEqual(audit["config"]["ref_V_SHE"], .197)
        self.assertIsNone(audit["stored_config"]["pH"])
        self.assertEqual(configs, before)

    def test_processed_snapshots_are_detached_and_deduplicate_paired_background(self):
        sample, bg, traces, configs = fixture(paired=True)
        result = process_trace(sample, configs[sample.id], traces, configs)
        self.assertEqual(list(result["backgrounds"]), [bg.id])
        self.assertEqual(result["backgrounds"][bg.id]["channels"], ["disk", "ring"])
        self.assertEqual(set(result["backgrounds"][bg.id]["segments"]), {"disk", "ring"})
        configs[sample.id]["parameter_sources"]["pH"] = "changed later"
        configs[bg.id]["temperature_C"] = 99.
        self.assertEqual(result["stored_config"]["parameter_sources"]["pH"], "synthetic sample")
        self.assertEqual(result["backgrounds"][bg.id]["stored_config"]["temperature_C"], 25.)

    def test_conflict_blocks_used_background_on_both_axes_but_not_raw_preview(self):
        sample, _, traces, configs = fixture(two_samples=True)
        second = next(ident for ident,cfg in configs.items() if ident != sample.id and cfg["role"] != "背景")
        configs[second]["pH"] = 12.
        for axis in ("RHE", "原始"):
            with self.subTest(axis=axis), self.assertRaisesRegex(DataError, "冲突"):
                process_trace(sample, configs[sample.id], traces, configs, axis)
        preview = process_trace(sample, configs[sample.id], traces, configs, "原始", subtract_background=False)
        self.assertFalse(preview["backgrounds"])
        np.testing.assert_allclose(preview["data"].I_disk_A, preview["data"].I_disk_raw_A)

    def test_ring_only_ignores_unused_missing_disk_background(self):
        sample, bg, traces, configs = fixture(paired=True)
        configs[sample.id]["background_disk"] = "missing-unused-background"
        result = process_trace(sample, configs[sample.id], traces, configs, channels="ring")
        self.assertEqual(result["backgrounds"][bg.id]["channels"], ["ring"])
        self.assertNotIn("I_disk_A", result["data"])
        np.testing.assert_allclose(result["data"].I_ring_A, 9e-6 * (1 + result["data"].E_original_V))

    def test_independent_background_missing_ph_still_identifies_background(self):
        sample, bg, traces, configs = fixture()
        configs[bg.id]["background_conditions_mode"] = "independent"
        with self.assertRaisesRegex(DataError, "盘背景.*Ar-background.*pH"):
            process_trace(sample, configs[sample.id], traces, configs)

    def test_measured_zero_and_already_rhe_ignore_inactive_reference_caches(self):
        for method in ("实测 RHE 总偏移", "已是 RHE"):
            for axis in ("原始", "RHE"):
                with self.subTest(method=method, axis=axis):
                    sample, bg, traces, configs = fixture()
                    configs[sample.id].update(potential_method=method, rhe_offset_V=0., ref_V_SHE=123.)
                    configs[bg.id].update(ref_V_SHE=-99., reference="different old cache")
                    result = process_trace(sample, configs[sample.id], traces, configs, axis)
                    np.testing.assert_allclose(result["data"].E_V, result["data"].E_original_V)
                    np.testing.assert_allclose(result["data"].I_disk_A, -.0009 * (1 + result["data"].E_original_V))

    def test_theoretical_raw_background_accepts_unknown_optional_reference_metadata(self):
        sample, _, traces, configs = fixture(two_samples=True)
        configs[sample.id].update(reference="未设置", filling="")
        result = process_trace(sample, configs[sample.id], traces, configs, "原始")
        self.assertEqual(len(result["data"]), 6)
        np.testing.assert_allclose(result["data"].I_disk_A, -.0009 * (1 + result["data"].E_original_V))

    def test_measured_raw_signature_uses_current_offset_not_inactive_metadata(self):
        left = dict(potential_method="实测 RHE 总偏移", rhe_offset_V=0., ref_V_SHE=9., temperature_C=5.)
        right = dict(potential_method="实测 RHE 总偏移", rhe_offset_V=0., ref_V_SHE=-3., temperature_C=80.)
        self.assertEqual(potential_signature(left, "原始"), potential_signature(right, "原始"))
        right["rhe_offset_V"] = .1
        self.assertNotEqual(potential_signature(left, "原始"), potential_signature(right, "原始"))

    def test_unknown_conversion_method_cannot_silently_use_theory(self):
        for method in (None, "unrecognized"):
            with self.subTest(method=method):
                sample, bg, traces, configs = fixture()
                configs[bg.id].update(background_conditions_mode="independent", potential_method=method,
                                     pH=13., ref_V_SHE=.197, temperature_C=25.,
                                     reference="Ag/AgCl", filling="3 M KCl")
                with self.assertRaisesRegex(DataError, "电位换算方式|potential_method"):
                    process_trace(sample, configs[sample.id], traces, configs, "RHE")
                configs[sample.id]["potential_method"] = method
                with self.assertRaisesRegex(DataError, "电位换算方式"):
                    process_trace(sample, configs[sample.id], traces, configs, "RHE", subtract_background=False)
                raw = process_trace(sample, configs[sample.id], traces, configs, "原始", subtract_background=False)
                np.testing.assert_allclose(raw["data"].E_V, raw["data"].E_original_V)

    def test_missing_conversion_method_key_keeps_legacy_theory_default(self):
        sample, _, traces, configs = fixture()
        expected = rhe_shift(configs[sample.id])
        configs[sample.id].pop("potential_method")
        result = process_trace(sample, configs[sample.id], traces, configs)
        np.testing.assert_allclose(result["data"].E_V - result["data"].E_original_V, expected)

    def test_schema2_roundtrip_preserves_independent_values_and_following(self):
        sample, bg, traces, configs = fixture()
        configs[bg.id].update(pH=7., ref_V_SHE=.11, temperature_C=20.)
        configs[bg.id]["parameter_sources"]["pH"] = "old independent value"
        raw = pack_project(traces, configs, {"axis":"RHE"})
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            manifest = json.loads(archive.read("project.json"))
        self.assertEqual(manifest["schema"], 2)
        stored_bg = next(item["config"] for item in manifest["files"] if item["id"] == bg.id)
        self.assertEqual(stored_bg["pH"], 7.)
        self.assertNotIn("background_conditions", stored_bg)
        restored_traces, restored, settings = unpack_project(raw)
        self.assertEqual(restored, configs)
        self.assertEqual(restored_traces[bg.id].raw, bg.raw)
        restored[sample.id]["pH"] = 12.
        effective = resolved_configs(restored)[bg.id]
        self.assertEqual(effective["pH"], 12.)
        restored[bg.id]["background_conditions_mode"] = "independent"
        self.assertEqual(resolved_configs(restored)[bg.id]["pH"], 7.)
        self.assertEqual(settings["axis"], "RHE")

    def test_writer_recovers_independent_record_from_effective_projection(self):
        _, bg, traces, configs = fixture()
        configs[bg.id]["pH"] = 7.
        configs[bg.id]["parameter_sources"]["pH"] = "independent seven"
        view = resolved_configs(configs)
        self.assertEqual(view[bg.id]["pH"], 13.)
        _, restored, _ = unpack_project(pack_project(traces, view, {}))
        self.assertEqual(restored[bg.id]["pH"], 7.)
        self.assertEqual(restored[bg.id]["parameter_sources"]["pH"], "independent seven")

    def test_schema1_follow_migrates_history_without_inventing_independent_ph(self):
        sample, bg, traces, configs = fixture()
        configs[bg.id].update(pH=13., ref_V_SHE=.11, temperature_C=20., background_ph_mode="follow")
        configs[bg.id]["parameter_sources"]["pH"] = "legacy following snapshot"
        def old_format(manifest):
            manifest["schema"] = 1
            for item in manifest["files"]:
                item["config"].pop("background_conditions_mode")
                item["config"].pop("background_conditions_migration")
        old_raw = rewrite_project(pack_project(traces, configs, {}), old_format)
        _, restored, _ = unpack_project(old_raw)
        background = restored[bg.id]
        self.assertEqual(background["background_conditions_mode"], "legacy_ph")
        self.assertIsNone(background["pH"])
        self.assertEqual(background["ref_V_SHE"], .11)
        self.assertEqual(background["temperature_C"], 20.)
        self.assertEqual(background["background_conditions_migration"]["saved_ph_snapshot"], 13.)
        self.assertEqual(background["background_conditions_migration"]["saved_ph_source"], "legacy following snapshot")
        self.assertEqual(resolved_configs(restored)[bg.id]["pH"], 13.)
        _, again, _ = unpack_project(pack_project(traces, restored, {}))
        self.assertEqual(again, restored)
        restored[sample.id]["pH"] = 12.
        self.assertEqual(resolved_configs(restored)[bg.id]["pH"], 12.)

    def test_schema1_missing_ph_mode_keeps_manual_legacy_activation(self):
        _, bg, traces, configs = fixture()
        def old_format(manifest):
            manifest["schema"] = 1
            for item in manifest["files"]:
                for key in list(item["config"]):
                    if key.startswith("background_ph_") or key.startswith("background_conditions_"):
                        item["config"].pop(key)
        _, restored, _ = unpack_project(rewrite_project(pack_project(traces, configs, {}), old_format))
        self.assertEqual(restored[bg.id]["background_ph_mode"], "manual")
        self.assertTrue(restored[bg.id]["background_ph_legacy"])
        self.assertIsNone(resolved_configs(restored)[bg.id]["pH"])
        activate_links(restored, [bg.id])
        self.assertEqual(restored[bg.id]["background_ph_mode"], "follow")
        self.assertEqual(restored[bg.id]["background_conditions_mode"], "legacy_ph")
        self.assertEqual(resolved_configs(restored)[bg.id]["pH"], 13.)

    def test_schema2_history_is_preserved_without_replaying_legacy_migration(self):
        _, bg, traces, configs = fixture()
        history = {"source_schema":1, "saved_ph_snapshot":13., "saved_ph_source":"original legacy log",
                   "independent_ph_status":"unknown_legacy_follow", "note":{"preserve":"exactly"}}
        configs[bg.id].update(background_conditions_mode="independent", background_ph_mode="follow",
                             pH=7., background_conditions_migration=copy.deepcopy(history))
        configs[bg.id]["parameter_sources"]["pH"] = "later independent measurement"
        for _ in range(2):
            _, configs, _ = unpack_project(pack_project(traces, configs, {}))
            self.assertEqual(configs[bg.id]["background_conditions_migration"], history)
            self.assertEqual(configs[bg.id]["pH"], 7.)
            self.assertEqual(configs[bg.id]["background_conditions_mode"], "independent")
            self.assertEqual(configs[bg.id]["parameter_sources"]["pH"], "later independent measurement")

    def test_live_legacy_migration_is_detached_and_preserves_sample_values(self):
        for role in ("背景", "样品"):
            cfg = dict(role=role, pH=13., background_ph_mode="follow", background_ph_legacy=False,
                       parameter_sources={"pH":"legacy source"})
            original = copy.deepcopy(cfg)
            migrated = migrate_background_config(cfg)
            self.assertEqual(cfg, original)
            self.assertEqual(migrated["pH"], None if role == "背景" else 13.)

    def test_schema2_rejects_missing_unknown_and_malformed_strategy_records(self):
        _, bg, traces, configs = fixture()
        raw = pack_project(traces, configs, {})
        for mode in (None, "unknown", ["follow"]):
            def corrupt(manifest):
                config = next(item["config"] for item in manifest["files"] if item["id"] == bg.id)
                if mode is None:
                    config.pop("background_conditions_mode")
                else:
                    config["background_conditions_mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(DataError):
                unpack_project(rewrite_project(raw, corrupt))
        with self.assertRaises(DataError):
            migrate_background_config({"background_conditions_mode":"follow", "background_conditions_migration":[]}, 2)

    def test_parameter_record_uses_actual_processing_snapshot_after_input_changes(self):
        sample, bg, traces, configs = fixture()
        output = process_trace(sample, configs[sample.id], traces, configs)
        configs[sample.id]["pH"] = 12.
        configs[bg.id]["pH"] = 9.
        record = parameter_record(traces, configs, {}, {sample.id:output})
        by_id = {item["id"]:item for item in record["files"]}
        self.assertEqual(by_id[sample.id]["config"]["pH"], 13.)
        self.assertEqual(by_id[bg.id]["config"]["pH"], 13.)
        self.assertIsNone(by_id[bg.id]["stored_config"]["pH"])
        self.assertEqual(by_id[bg.id]["config_snapshot_basis"], "processed")
        self.assertEqual(by_id[sample.id]["backgrounds"][bg.id]["background_conditions"]["effective"]["pH"], 13.)
        record["files"][0]["config"]["parameter_sources"]["pH"] = "export mutation"
        self.assertEqual(output["config"]["parameter_sources"]["pH"], "synthetic sample")

    def test_parameter_record_without_results_distinguishes_stored_and_effective(self):
        _, bg, traces, configs = fixture()
        configs[bg.id]["pH"] = 7.
        record = parameter_record(traces, configs, {})
        background = next(item for item in record["files"] if item["id"] == bg.id)
        self.assertEqual(background["stored_config"]["pH"], 7.)
        self.assertEqual(background["config"]["pH"], 13.)
        self.assertEqual(background["config_snapshot_basis"], "current")

    def test_parameter_export_rejects_mixed_background_processing_snapshots(self):
        sample, _, traces, configs = fixture(two_samples=True)
        sample_ids = [ident for ident,cfg in configs.items() if cfg["role"] != "背景"]
        first = process_trace(sample, configs[sample.id], traces, configs)
        for ident in sample_ids:
            configs[ident]["pH"] = 12.
        second_id = next(ident for ident in sample_ids if ident != sample.id)
        second = process_trace(traces[second_id], configs[second_id], traces, configs)
        with self.assertRaisesRegex(DataError, "历史处理条件不一致"):
            parameter_record(traces, configs, {}, {sample.id:first, second_id:second})


if __name__ == "__main__":
    unittest.main()
