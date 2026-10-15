from io import BytesIO
import copy
import json
from pathlib import Path
import unittest
import zipfile

from background_ph import (activate_ph_links, default_ph_link, resolved_configs,
                           synchronize_ph_links)
from experiment_conditions import apply_conditions, snapshot_conditions
from orr_core import (DataError, default_config, pack_project, parameter_record,
                      parse_chi, process_trace, unpack_project)

ROOT = Path(__file__).resolve().parents[1]


def configs():
    return {
        "a":dict(name="A.txt", role="样品", pH=13., background_disk="bg", background_ring="bg"),
        "b":dict(name="B.txt", role="样品", pH=13., background_disk="bg"),
        "bg":dict(name="Ar.txt", role="背景", pH=None, parameter_sources={}, **default_ph_link()),
    }


class BackgroundPHTests(unittest.TestCase):
    def test_one_background_has_consensus_and_deduplicated_sources(self):
        cfg = configs()
        original = copy.deepcopy(cfg)
        resolved = resolved_configs(cfg)
        self.assertEqual(cfg, original)
        self.assertEqual(resolved["bg"]["pH"], 13.)
        self.assertEqual(resolved["bg"]["background_ph_mode"], "follow")
        self.assertEqual(len(resolved["bg"]["background_ph_sources"]), 2)
        self.assertIn("沿用", resolved["bg"]["parameter_sources"]["pH"])

    def test_first_bind_then_fill_and_zero_is_valid(self):
        cfg = configs()
        cfg["a"]["pH"] = cfg["b"]["pH"] = None
        activate_ph_links(cfg, ["bg"])
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["background_ph_status"], "waiting")
        cfg["a"]["pH"] = 0.
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 0.)
        self.assertIsNone(cfg["b"]["pH"])

    def test_committed_sample_changes_follow_without_reverse_copy(self):
        cfg = configs()
        synchronize_ph_links(cfg)
        cfg["a"]["pH"] = cfg["b"]["pH"] = 12.
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 12.)
        self.assertEqual(cfg["a"]["pH"], 12.)
        self.assertEqual(cfg["b"]["pH"], 12.)

    def test_conflict_never_uses_stale_or_last_writer_value(self):
        cfg = configs()
        synchronize_ph_links(cfg)
        cfg["b"]["pH"] = 12.
        for ordered in (cfg, dict(reversed(list(cfg.items())))):
            result = resolved_configs(ordered)["bg"]
            self.assertIsNone(result["pH"])
            self.assertEqual(result["background_ph_status"], "conflict")
            self.assertIn("A.txt：13", result["background_ph_detail"])
            self.assertIn("B.txt：12", result["background_ph_detail"])

    def test_matching_numeric_representations_and_roundoff(self):
        cfg = configs()
        cfg["a"]["pH"] = 13
        cfg["b"]["pH"] = 13.0 + 5e-10
        self.assertEqual(resolved_configs(cfg)["bg"]["background_ph_status"], "following")

    def test_invalid_sample_values_do_not_supply_background_ph(self):
        cfg = configs()
        for value in (float("nan"), float("inf"), "bad", True):
            cfg["a"]["pH"], cfg["b"]["pH"] = value, None
            result = resolved_configs(cfg)["bg"]
            self.assertIsNone(result["pH"])
            self.assertEqual(result["background_ph_status"], "waiting")

    def test_existing_independent_value_is_preserved(self):
        cfg = configs()
        cfg["bg"]["pH"] = 12.
        activate_ph_links(cfg, ["bg"])
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 12.)
        self.assertEqual(cfg["bg"]["background_ph_status"], "manual_difference")
        cfg["a"]["pH"] = cfg["b"]["pH"] = 11.
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 12.)

    def test_explicit_background_edit_becomes_independent(self):
        cfg = configs()
        synchronize_ph_links(cfg)
        apply_conditions(cfg["bg"], {"pH":12.})
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["background_ph_mode"], "manual")
        self.assertEqual(cfg["bg"]["pH"], 12.)
        cfg["bg"]["background_ph_mode"] = "follow"
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 13.)

    def test_bulk_sample_application_does_not_disable_following(self):
        cfg = configs()
        synchronize_ph_links(cfg)
        for ident in ("a", "b", "bg"):
            apply_conditions(cfg[ident], {"pH":12.}, background_ph_edit=False)
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["background_ph_mode"], "follow")
        self.assertEqual(cfg["bg"]["pH"], 12.)
        cfg["a"]["pH"] = cfg["b"]["pH"] = 11.
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 11.)

    def test_unlink_cleans_only_derived_ph(self):
        cfg = configs()
        synchronize_ph_links(cfg)
        cfg["a"]["background_disk"] = cfg["a"]["background_ring"] = None
        cfg["b"]["background_disk"] = None
        synchronize_ph_links(cfg)
        self.assertIsNone(cfg["bg"]["pH"])
        self.assertEqual(cfg["bg"]["background_ph_sources"], [])
        self.assertEqual(cfg["bg"]["background_ph_status"], "unbound")
        cfg["bg"].update(pH=12., background_ph_mode="manual")
        synchronize_ph_links(cfg)
        self.assertEqual(cfg["bg"]["pH"], 12.)

    def test_rebind_updates_both_backgrounds_and_ring_dependencies(self):
        cfg = configs()
        cfg["bg2"] = dict(name="Ar2.txt", role="背景", pH=None, **default_ph_link())
        synchronize_ph_links(cfg)
        cfg["a"]["background_disk"] = cfg["b"]["background_disk"] = "bg2"
        synchronize_ph_links(cfg)
        self.assertEqual(len(cfg["bg"]["background_ph_sources"]), 1)  # still ring background
        self.assertEqual(cfg["bg2"]["pH"], 13.)
        cfg["a"]["background_ring"] = "bg2"
        synchronize_ph_links(cfg)
        self.assertIsNone(cfg["bg"]["pH"])
        self.assertEqual(len(cfg["bg2"]["background_ph_sources"]), 2)

    def traces(self):
        paths = [ROOT/"examples"/name for name in ("O-0.1MNa-5mv-900.txt", "O-0.1MNa-5mv-1225.txt", "Ar-5mv-beijing.txt")]
        traces = [parse_chi(p.name, p.read_bytes()) for p in paths]
        cfg = {t.id:default_config(t) for t in traces}
        for t in traces[:2]:
            cfg[t.id].update(pH=13., ref_V_SHE=.197, background_disk=traces[2].id)
        cfg[traces[2].id]["ref_V_SHE"] = .197
        return traces, {t.id:t for t in traces}, cfg

    def test_core_resolves_ph_and_guards_conflict_even_with_raw_axis(self):
        ts, traces, cfg = self.traces()
        output = process_trace(ts[0], cfg[ts[0].id], traces, cfg, "RHE")
        self.assertTrue(any("沿用关联样品 pH 13" in n for n in output["notes"]))
        self.assertIsNone(cfg[ts[2].id]["pH"])  # core uses a read-only snapshot
        cfg[ts[1].id]["pH"] = 12.
        for axis in ("RHE", "原始"):
            with self.assertRaisesRegex(DataError, "共享背景 pH 冲突"):
                process_trace(ts[0], cfg[ts[0].id], traces, cfg, axis)

    def test_project_and_parameters_reconstruct_and_audit_following(self):
        ts, traces, cfg = self.traces()
        project = pack_project(traces, cfg, {"axis":"RHE"})
        _, restored, _ = unpack_project(project)
        self.assertEqual(restored[ts[2].id]["pH"], 13.)
        self.assertEqual(restored[ts[2].id]["background_ph_mode"], "follow")
        self.assertEqual(len(restored[ts[2].id]["background_ph_sources"]), 2)
        record = parameter_record(traces, cfg, {})
        bg = next(f["config"] for f in record["files"] if f["id"] == ts[2].id)
        self.assertEqual(bg["pH"], 13.)
        self.assertNotIn("background_ph_mode", snapshot_conditions(bg))
        self.assertNotIn("background_ph_sources", snapshot_conditions(bg))

    def test_legacy_project_preserves_empty_and_manual_values(self):
        ts, traces, cfg = self.traces()
        for ph in (None, 12.):
            cfg[ts[2].id].update(pH=ph, background_ph_mode="manual")
            raw = pack_project(traces, cfg, {})
            output = BytesIO()
            with zipfile.ZipFile(BytesIO(raw)) as archive, zipfile.ZipFile(output, "w") as dest:
                for name in archive.namelist():
                    data = archive.read(name)
                    if name == "project.json":
                        value = json.loads(data)
                        for f in value["files"]:
                            for key in list(f["config"]):
                                if key.startswith("background_ph_"):
                                    f["config"].pop(key)
                        data = json.dumps(value).encode()
                    dest.writestr(name, data)
            _, restored, _ = unpack_project(output.getvalue())
            bg = restored[ts[2].id]
            self.assertEqual(bg["pH"], ph)
            self.assertEqual(bg["background_ph_mode"], "manual")
            activate_ph_links(restored, [ts[2].id])
            synchronize_ph_links(restored)
            self.assertEqual(bg["pH"], 13. if ph is None else 12.)


if __name__ == "__main__":
    unittest.main()
