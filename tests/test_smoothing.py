import unittest

import numpy as np
import pandas as pd

from orr_core import DataError
from plot_smoothing import (SMOOTH_A, SMOOTH_MA, SMOOTH_DENSITY,
                            smooth_for_plot, smoothing_defaults)


def frame(n=101):
    e = np.arange(n)*.001
    current = .002*e**2-.003*e-.0002
    return pd.DataFrame({"E_V":e, "I_disk_A":current, "I_disk_mA":current*1000,
                         "j_disk_mA_cm2":current*1000/.196})


class SmoothingTests(unittest.TestCase):
    def test_disabled_is_exactly_unchanged(self):
        original=frame()
        result, report=smooth_for_plot(original,{})
        pd.testing.assert_frame_equal(result,original)
        self.assertFalse(report["enabled"])
        self.assertNotIn(SMOOTH_A,result)

    def test_quadratic_preserved_including_edges(self):
        original=frame()
        result, report=smooth_for_plot(original,{"enabled":True,"window_points":11})
        np.testing.assert_allclose(result[SMOOTH_A],original.I_disk_A,atol=1e-15)
        pd.testing.assert_frame_equal(result[original.columns],original)
        self.assertEqual(report["applied_points"],101)
        self.assertAlmostEqual(report["segments"][0]["requested_window_span_mV"],10)

    def test_noise_reduction_with_independent_clean_signal(self):
        original=frame(301)
        clean=original.I_disk_A.to_numpy().copy()
        original.I_disk_A += np.random.default_rng(7).normal(0,1e-5,len(original))
        noisy_error=np.sqrt(np.mean((original.I_disk_A-clean)**2))
        result,_=smooth_for_plot(original,{"enabled":True,"window_points":21})
        smoothed_error=np.sqrt(np.mean((result[SMOOTH_A]-clean)**2))
        self.assertLess(smoothed_error,noisy_error*.65)

    def test_decreasing_scan_and_RHE_translation(self):
        original=frame().iloc[::-1].reset_index(drop=True)
        a,_=smooth_for_plot(original,{"enabled":True})
        translated=original.copy()
        translated.E_V += .95
        b,_=smooth_for_plot(translated,{"enabled":True})
        np.testing.assert_allclose(a[SMOOTH_A],b[SMOOTH_A],atol=1e-15)

    def test_gaps_never_joined(self):
        original=frame(121)
        original.loc[60,"I_disk_A"]=np.nan
        original.loc[61:,"I_disk_A"] += .01
        result,report=smooth_for_plot(original,{"enabled":True,"window_points":11})
        self.assertTrue(np.isnan(result[SMOOTH_A][60]))
        np.testing.assert_allclose(result[SMOOTH_A][:60],original.I_disk_A[:60],atol=1e-14)
        np.testing.assert_allclose(result[SMOOTH_A][61:],original.I_disk_A[61:],atol=1e-14)
        self.assertEqual(report["gap_points"],1)
        self.assertEqual(report["applied_points"],120)
        self.assertEqual(len(report["segments"]),2)

    def test_short_segment_kept_not_auto_reduced(self):
        original=frame(7)
        result,report=smooth_for_plot(original,{"enabled":True,"window_points":11})
        np.testing.assert_array_equal(result[SMOOTH_A],original.I_disk_A)
        self.assertEqual(report["status"],"skipped")
        self.assertEqual(report["preserved_points"],7)

    def test_uneven_or_nonmonotonic_or_duplicate_grid_not_resampled(self):
        for altered in ("uneven","reversal","duplicate"):
            original=frame()
            if altered=="uneven": original.loc[50,"E_V"] += .0001
            elif altered=="reversal": original.loc[50,"E_V"] -= .005
            else: original.loc[50,"E_V"]=original.loc[49,"E_V"]
            result,report=smooth_for_plot(original,{"enabled":True})
            np.testing.assert_array_equal(result[SMOOTH_A],original.I_disk_A)
            self.assertEqual(report["applied_points"],0)
            self.assertIn("未重采样",report["notes"][0])

    def test_current_density_and_mA_use_same_smoothed_current(self):
        original=frame()
        result,_=smooth_for_plot(original,{"enabled":True})
        np.testing.assert_allclose(result[SMOOTH_MA],result[SMOOTH_A]*1000)
        np.testing.assert_allclose(result[SMOOTH_DENSITY],result[SMOOTH_A]*1000/.196)

    def test_zero_current_and_invalid_potential_remain_gap(self):
        original=frame()
        original[["I_disk_A","I_disk_mA","j_disk_mA_cm2"]]=0.
        original.loc[50,"E_V"]=np.nan
        result,report=smooth_for_plot(original,{"enabled":True})
        self.assertTrue(np.isnan(result[SMOOTH_A][50]))
        self.assertTrue(np.isnan(result[SMOOTH_DENSITY][50]))
        self.assertTrue((result[SMOOTH_A].dropna()==0).all())

    def test_invalid_windows_are_not_silently_changed(self):
        for window in (2,10,1003,11.5,True):
            with self.assertRaises(DataError):
                smooth_for_plot(frame(),{"enabled":True,"window_points":window})

    def test_old_settings_default_off(self):
        self.assertFalse(smoothing_defaults()["enabled"])


if __name__=="__main__":
    unittest.main()
