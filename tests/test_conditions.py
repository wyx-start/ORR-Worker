from io import BytesIO
import json
import math
from pathlib import Path
import tempfile
import unittest
import zipfile

from experiment_conditions import (apply_conditions, area_from_diameter, load_profiles,
    missing_conditions, save_profile, snapshot_conditions)
from orr_core import DataError, default_config, pack_project, parse_chi, process_trace, unpack_project

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    p = ROOT / "examples" / "O-0.1MNa-5mv-900.txt"
    t = parse_chi(p.name, p.read_bytes())
    return t, default_config(t)


class ConditionTests(unittest.TestCase):
    def test_geometry_and_current_density_use_full_precision(self):
        t, cfg = fixture()
        self.assertEqual(cfg["disk_diameter_mm"], 5.)
        self.assertEqual(cfg["area_cm2"], math.pi/16)
        output = process_trace(t, cfg, {t.id:t}, {t.id:cfg}, "原始")
        self.assertAlmostEqual(output["data"].j_disk_mA_cm2[0], output["data"].I_disk_mA[0]/(math.pi/16))
        apply_conditions(cfg, {"disk_diameter_mm":4., "area_cm2":area_from_diameter(4), "area_mode":"diameter"})
        self.assertAlmostEqual(cfg["area_cm2"], math.pi*.04)
        self.assertEqual(cfg["parameter_sources"]["area_cm2"], "人工输入")

    def test_task_requirements_are_independent(self):
        t, cfg = fixture()
        cfg["area_cm2"] = -1
        self.assertEqual(missing_conditions(cfg, axis="原始"), [])
        self.assertTrue(missing_conditions(cfg, axis="原始", density=True))
        self.assertTrue(missing_conditions(cfg, "rrde", axis="原始"))
        output = process_trace(t, cfg, {t.id:t}, {t.id:cfg}, "原始")
        self.assertIn("I_disk_mA", output["data"])
        self.assertNotIn("j_disk_mA_cm2", output["data"])
        cfg.update(potential_method="实测 RHE 总偏移", rhe_offset_V=0., area_cm2=None)
        self.assertEqual(missing_conditions(cfg), [])
        cfg.update(potential_method="已是 RHE", rhe_offset_V=None)
        self.assertEqual(missing_conditions(cfg), [])

    def test_profiles_exclude_identity_and_confirmations(self):
        _, cfg = fixture()
        cfg.update(background_reviewed=True, ring_detection_confirmed=True, manual_segment=2)
        values = snapshot_conditions(cfg)
        self.assertNotIn("rpm", values)
        self.assertNotIn("name", values)
        self.assertNotIn("manual_segment", values)
        self.assertNotIn("background_reviewed", values)
        self.assertNotIn("ring_detection_confirmed", values)

    def test_profile_fill_preserves_manual_values_and_updates_defaults(self):
        _, cfg = fixture()
        cfg.update(pH=12., collection_efficiency=.4, ring_detection_confirmed=False)
        profile = dict(pH=13., temperature_C=30., potential_method="已是 RHE",
                       area_cm2=area_from_diameter(4.), disk_diameter_mm=4., area_mode="diameter",
                       ring_detection_confirmed=True, rpm=1600)
        apply_conditions(cfg, profile, "本机预设：测试", overwrite=False)
        self.assertEqual(cfg["pH"], 12.)
        self.assertEqual(cfg["temperature_C"], 30.)
        self.assertEqual(cfg["potential_method"], "已是 RHE")
        self.assertEqual(cfg["disk_diameter_mm"], 4.)
        self.assertEqual(cfg["rpm"], 900)
        self.assertFalse(cfg["ring_detection_confirmed"])
        cfg.update(area_cm2=.3, disk_diameter_mm=None, area_mode="area")
        cfg["parameter_sources"]["area_cm2"] = "人工输入"
        apply_conditions(cfg, profile, overwrite=False)
        self.assertEqual(cfg["area_cm2"], .3)
        self.assertIsNone(cfg["disk_diameter_mm"])

    def test_hidden_fields_are_preserved(self):
        _, cfg = fixture()
        cfg.update(pH=13., ref_V_SHE=.197, collection_efficiency=.37)
        apply_conditions(cfg, {"potential_method":"实测 RHE 总偏移", "rhe_offset_V":0.})
        self.assertEqual(cfg["pH"], 13.)
        self.assertEqual(cfg["ref_V_SHE"], .197)
        self.assertEqual(cfg["collection_efficiency"], .37)
        apply_conditions(cfg, {"area_cm2":.25, "area_mode":"area", "disk_diameter_mm":None})
        self.assertEqual(cfg["area_cm2"], .25)

    def test_reference_profile_does_not_mix_incompatible_values(self):
        _, cfg = fixture()
        cfg.update(reference="SCE", filling="饱和 KCl", ref_V_SHE=None)
        apply_conditions(cfg, {"reference":"Ag/AgCl", "filling":"3 M KCl", "ref_V_SHE":.207},
                         source="本机预设：Ag/AgCl", overwrite=False)
        self.assertEqual(cfg["reference"], "SCE")
        self.assertEqual(cfg["filling"], "饱和 KCl")
        self.assertIsNone(cfg["ref_V_SHE"])

    def test_local_roundtrip_and_corruption_fallback(self):
        _, cfg = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"presets.json"
            self.assertEqual(load_profiles(path), ({}, None))
            save_profile("常用条件", cfg, path)
            profiles, error = load_profiles(path)
            self.assertIsNone(error)
            self.assertEqual(profiles["常用条件"]["area_cm2"], cfg["area_cm2"])
            path.write_text("invalid json", encoding="utf-8")
            self.assertEqual(load_profiles(path)[0], {})
            with self.assertRaises(DataError):
                save_profile("不得覆盖损坏文件", cfg, path)
            self.assertEqual(path.read_text(encoding="utf-8"), "invalid json")

    def test_invalid_profile_values_rejected(self):
        _, cfg = fixture()
        for patch in ({"collection_efficiency":37}, {"pH":float("nan")},
                      {"disk_diameter_mm":4., "area_cm2":.196, "area_mode":"diameter"}):
            with self.assertRaises(DataError):
                apply_conditions(cfg, patch)

    def test_legacy_projects_keep_area_and_unknown_geometry(self):
        t, cfg = fixture()
        for area in (None, .125, .3):
            cfg.update(area_cm2=area, area_mode="area", disk_diameter_mm=None)
            project = pack_project({t.id:t}, {t.id:cfg}, {"axis":"原始"})
            dest = BytesIO()
            with zipfile.ZipFile(BytesIO(project)) as src, zipfile.ZipFile(dest, "w") as out:
                for name in src.namelist():
                    value = src.read(name)
                    if name == "project.json":
                        data = json.loads(value)
                        for key in ("disk_diameter_mm", "area_mode", "parameter_sources"):
                            data["files"][0]["config"].pop(key)
                        value = json.dumps(data).encode()
                    out.writestr(name, value)
            _, restored, _ = unpack_project(dest.getvalue())
            self.assertEqual(restored[t.id]["area_cm2"], area)
            self.assertIsNone(restored[t.id]["disk_diameter_mm"])
            if area is not None:
                self.assertIn("来源未记录", restored[t.id]["parameter_sources"]["area_cm2"])


if __name__ == "__main__":
    unittest.main()
