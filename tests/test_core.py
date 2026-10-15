from io import BytesIO
import json
from pathlib import Path
import time
import unittest
import zipfile

import numpy as np
import pandas as pd

from orr_core import (DataError, FARADAY, default_config, kl_calculate,
                      pack_project, parse_chi, process_trace, rhe_shift, rrde_calculate,
                      scan_segments, select_segment, unpack_project)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def sample(name="O-0.1MNa-5mv-900.txt"):
    return parse_chi(name, (EXAMPLES/name).read_bytes())


class NumericalTests(unittest.TestCase):
    def test_real_files_complete_final_cycle(self):
        for path in EXAMPLES.glob("*.txt"):
            t = parse_chi(path.name, path.read_bytes())
            segments = scan_segments(t)
            self.assertEqual(len(segments), 4)
            self.assertEqual(select_segment(t, default_config(t))["cycle"], 2)
            self.assertAlmostEqual(segments[-1]["endpoint_gap_mV"], 1, places=7)
            self.assertTrue(segments[-1]["complete"])

    def test_cutoff_cycle_A_versus_B(self):
        t = sample()
        t.values = t.values[:-100]
        cfg = default_config(t)
        cfg["direction"] = "递增"
        self.assertEqual(select_segment(t, cfg)["segment"], 1)
        cfg["mode"] = "B"
        self.assertEqual(select_segment(t, cfg)["segment"], 3)
        cfg["manual_segment"] = 4
        self.assertFalse(select_segment(t, cfg)["complete"])

    def test_no_program_endpoints_needs_manual(self):
        t = sample()
        t.header.pop("Low E (V)")
        with self.assertRaises(DataError):
            select_segment(t, default_config(t))

    def test_initial_partial_segment_not_a_cycle(self):
        t = sample()
        t.values = t.values[200:]
        self.assertFalse(scan_segments(t)[0]["complete"])
        chosen = select_segment(t, default_config(t))
        self.assertEqual(chosen["segment"], 2)
        self.assertEqual(chosen["cycle"], 1)

    def test_malformed_data_not_silently_dropped(self):
        with self.assertRaises(DataError):
            parse_chi("bad.txt", b"Potential/V, Current/A\n0,1\nBAD\n1,2\n")

    def test_unit_conversion(self):
        t = parse_chi("u.txt", b"Potential/mV, Current/uA\n0,1\n100,2\n200,3\n")
        np.testing.assert_allclose(t.values[:, 0], [0, .1, .2])
        np.testing.assert_allclose(t.values[:, 1], [1e-6, 2e-6, 3e-6])

    def test_rhe_theory_and_calibration_exclusive(self):
        cfg = default_config(sample())
        cfg.update(pH=13., ref_V_SHE=.197, temperature_C=25.)
        self.assertAlmostEqual(rhe_shift(cfg), .197 + .0591593497 * 13, places=7)
        cfg.update(potential_method="实测 RHE 总偏移", rhe_offset_V=.95)
        self.assertEqual(rhe_shift(cfg), .95)
        cfg.update(potential_method="已是 RHE")
        self.assertEqual(rhe_shift(cfg), 0.)

    def test_missing_pH_and_wrong_temperature_fail(self):
        cfg = default_config(sample())
        with self.assertRaises(DataError):
            rhe_shift(cfg)
        cfg.update(pH=13, ref_V_SHE=.197, reference_preset_C=25, temperature_C=30)
        with self.assertRaises(DataError):
            rhe_shift(cfg)

    def test_real_background_voltage_alignment(self):
        t, b = sample(), sample("Ar-5mv-beijing.txt")
        cfg, bcfg = default_config(t), default_config(b)
        cfg["background_disk"] = b.id
        output = process_trace(t, cfg, {t.id:t, b.id:b}, {t.id:cfg, b.id:bcfg}, axis="原始")
        data = output["data"]
        self.assertEqual(len(data), 900)
        self.assertTrue(data.I_disk_A.notna().all())
        bseg = select_segment(b, bcfg)
        bvalues = b.values[bseg["start"]:bseg["end"]+1]
        lookup = {round(e, 6):i for e, i in bvalues}
        expected = np.array([lookup[round(e, 6)] for e in data.E_original_V])
        np.testing.assert_allclose(data.I_disk_A, data.I_disk_raw_A-expected, atol=1e-15)

    def test_missing_background_ph_identifies_the_background(self):
        t, b = sample(), sample("Ar-5mv-beijing.txt")
        cfg, bcfg = default_config(t), default_config(b)
        cfg.update(pH=13., ref_V_SHE=.197, background_disk=b.id)
        bcfg["background_ph_mode"] = "manual"
        with self.assertRaisesRegex(DataError, "盘背景.*Ar-5mv-beijing.*pH"):
            process_trace(t, cfg, {t.id:t, b.id:b}, {t.id:cfg, b.id:bcfg}, "RHE")

    def test_background_never_extrapolated(self):
        t, b = sample(), sample("Ar-5mv-beijing.txt")
        b.values = b.values[:4300]
        cfg, bcfg = default_config(t), default_config(b)
        cfg["background_disk"] = b.id
        bcfg["manual_segment"] = 4
        result = process_trace(t, cfg, {t.id:t, b.id:b}, {t.id:cfg, b.id:bcfg}, "原始")
        self.assertTrue(result["data"].I_disk_A.isna().any())
        self.assertTrue(any("不外推" in s for s in result["notes"]))

    def test_iR_uses_raw_signed_current(self):
        t = sample()
        cfg = default_config(t)
        cfg.update(ir_enabled=True, ir_confirmed=True, ir_ohm=10)
        result = process_trace(t, cfg, {t.id:t}, {t.id:cfg}, "原始")["data"]
        np.testing.assert_allclose(result.E_V, result.E_original_V-result.I_disk_raw_A*10)
        cfg["ir_confirmed"] = False
        with self.assertRaises(DataError):
            process_trace(t, cfg, {t.id:t}, {t.id:cfg}, "原始")

    def test_rrde_known_answer_and_invalid_signs(self):
        frame = pd.DataFrame({"E_V":[0,1,2,3], "I_disk_A":[-3e-6,-3e-6,0,-1e-6], "I_ring_A":[.4e-6,-.4e-6,.4e-6,1.2e-6]})
        cfg = {"collection_efficiency":.4, "disk_sign":-1, "ring_sign":1}
        result = rrde_calculate({"data":frame}, cfg)
        self.assertAlmostEqual(result.n_RRDE[0], 3)
        self.assertAlmostEqual(result.peroxide_pct[0], 50)
        self.assertTrue(np.isnan(result.n_RRDE[1]))
        self.assertTrue(np.isnan(result.n_RRDE[2]))
        self.assertAlmostEqual(result.peroxide_pct[3], 150)
        self.assertFalse(result.valid_two_product_model[3])

    def test_rrde_rejects_percent_entered_as_N(self):
        with self.assertRaises(DataError):
            rrde_calculate({"data":pd.DataFrame({"I_ring_A":[1], "I_disk_A":[-1]})}, {"collection_efficiency":37})

    def synthetic_kl(self, rpms=(400,900,1600,2500)):
        C, D, nu, n = 1.2e-6, 1.9e-5, .01, 3.2
        B = .62*n*FARADAY*D**(2/3)*nu**(-1/6)*C
        curves = []
        for rpm in rpms:
            j = 1/(1/.01+1/(B*np.sqrt(2*np.pi*rpm/60)))
            cfg = dict(rpm=rpm, area_cm2=.196, reference="test", filling="test", temperature_C=25., pH=13., electrolyte="synthetic", disk_sign=-1)
            frame = pd.DataFrame({"E_V":[-.7,-.6,-.5], "I_disk_A":np.full(3, -j*.196)})
            curves.append({"config":cfg, "data":frame, "axis":"原始", "segment":{"direction":"递减"}})
        return curves, C, D, nu, n

    def test_KL_known_answer_in_cgs_and_radians(self):
        curves, C, D, nu, n = self.synthetic_kl()
        result, points = kl_calculate(curves, [-.65,-.6,-.55], C, D, nu)
        np.testing.assert_allclose(result.n_KL, n, rtol=1e-10)
        np.testing.assert_allclose(result.two_e_pct_model, 40, rtol=1e-10)
        np.testing.assert_allclose(result.four_e_pct_model, 60, rtol=1e-10)
        np.testing.assert_allclose(result.R_squared, 1, rtol=1e-10)
        self.assertEqual(len(points), 12)

    def test_KL_two_speeds_and_duplicates(self):
        curves, C, D, nu, n = self.synthetic_kl((400,900))
        result, _ = kl_calculate(curves, [-.6], C, D, nu)
        self.assertTrue(np.isnan(result.R_squared[0]))
        self.assertTrue(np.isnan(result.slope_standard_error[0]))
        curves[1]["config"]["rpm"] = 400
        with self.assertRaises(DataError):
            kl_calculate(curves, [-.6], C, D, nu)

    def test_project_preserves_raw_and_parameters(self):
        t = sample()
        cfg = default_config(t)
        cfg.update(reference_source="test", reference_preset_C=25., manual_segment=3)
        project = pack_project({t.id:t}, {t.id:cfg}, {"axis":"原始", "plot":{"title":"测试"}})
        ts, cs, settings = unpack_project(project)
        self.assertEqual(ts[t.id].raw, t.raw)
        self.assertEqual(cs[t.id], cfg)
        self.assertEqual(settings["plot"]["title"], "测试")
        src = zipfile.ZipFile(BytesIO(project))
        dest = BytesIO()
        with zipfile.ZipFile(dest, "w") as out:
            for name in src.namelist():
                data = src.read(name)
                if name == "project.json":
                    obj = json.loads(data)
                    obj["files"][0]["sha256"] = "wrong"
                    data = json.dumps(obj).encode()
                out.writestr(name, data)
        with self.assertRaises(DataError):
            unpack_project(dest.getvalue())

    def test_batch_of_ten_real_traces(self):
        raw = (EXAMPLES/"O-0.1MNa-5mv-900.txt").read_bytes()
        start = time.perf_counter()
        for k in range(10):
            t = parse_chi(f"test-{k}.txt", raw)
            cfg = default_config(t)
            self.assertEqual(len(process_trace(t, cfg, {t.id:t}, {t.id:cfg}, "原始")["data"]), 900)
        print(f"10-file parse + extraction: {time.perf_counter()-start:.3f}s")


if __name__ == "__main__":
    unittest.main()
