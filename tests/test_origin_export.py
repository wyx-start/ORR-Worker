import copy
from io import BytesIO
import unittest

import numpy as np
import pandas as pd

from origin_export import (csv_bytes, curve_plot_table, kl_fit_plot_table,
                           rrde_plot_table)


def curve(e, y, *, name="sample", axis="RHE", unit="mA", channel="disk", smooth=False):
    return {
        "data": pd.DataFrame({"E_V": e, "plotted_current_value": y,
                              "plotted_current_unit": unit}),
        "axis": axis, "config": {"name": name}, "name": name + ".txt",
        "plot_channel": channel, "plot_smoothing_enabled": smooth,
    }


class OriginCurveExportTests(unittest.TestCase):
    def test_different_grids_lengths_and_gaps_are_preserved_by_position(self):
        first = curve([.9, .87, .82, .8], [-1., np.nan, -3., -4.])
        first["data"].index = [40, 42, 45, 47]
        second = curve([.895, .88], [12., 14.], unit="uA", channel="ring")
        second["data"].index = [7, 9]
        table = curve_plot_table({"first0001": first, "second002": second})
        self.assertEqual(table.shape, (4, 4))
        np.testing.assert_array_equal(table.iloc[:, 0], [.9, .87, .82, .8])
        np.testing.assert_array_equal(table.iloc[:, 1], [-1., np.nan, -3., -4.])
        np.testing.assert_array_equal(table.iloc[:, 2], [.895, .88, np.nan, np.nan])
        np.testing.assert_array_equal(table.iloc[:, 3], [12., 14., np.nan, np.nan])

    def test_duplicate_names_and_colliding_short_ids_have_unique_stable_headers(self):
        first, second = curve([.7], [1.], name="同名"), curve([.8], [2.], name="同名")
        outputs = {"abcdefgh111": first, "abcdefgh222": second}
        table = curve_plot_table(outputs)
        reversed_table = curve_plot_table(dict(reversed(list(outputs.items()))))
        self.assertTrue(table.columns.is_unique)
        self.assertTrue(all("abcdefgh1" in c for c in table.columns[:2]))
        self.assertTrue(all("abcdefgh2" in c for c in table.columns[2:]))
        self.assertEqual(list(table.columns[:2]), list(reversed_table.columns[2:]))
        self.assertEqual(list(table.columns[2:]), list(reversed_table.columns[:2]))

    def test_exact_current_graph_values_units_axis_and_smoothing_label(self):
        output = curve([.91, .90], [-1.2345678901234567, -1.4567890123456789],
                       unit="mA/cm2", smooth=True, axis="原始")
        output["data"]["I_disk_mA"] = [-200., -300.]
        before = copy.deepcopy(output)
        table = curve_plot_table({"abcdef123": output})
        self.assertTrue(table.columns[0].endswith("E_original_reference_V"))
        self.assertTrue(table.columns[1].endswith("j_disk_smoothed_plot_only_mA_cm2"))
        np.testing.assert_array_equal(table.iloc[:, 1], output["data"].plotted_current_value)
        pd.testing.assert_frame_equal(output["data"], before["data"])
        self.assertEqual(output["config"], before["config"])
        self.assertEqual(output["plot_smoothing_enabled"], before["plot_smoothing_enabled"])

    def test_false_smoothing_and_ring_microamp_alias(self):
        output = curve([.9], [2.], unit="μA", channel="ring", smooth=np.bool_(False))
        table = curve_plot_table({"r": output})
        self.assertTrue(table.columns[1].endswith("I_ring_uA"))
        self.assertNotIn("smoothed", table.columns[1])

    def test_original_mode_already_rhe_curve_labels_rhe_without_changing_values(self):
        output = curve([.9, .8, .7], [-1.2, np.nan, -1.8], axis="原始")
        output["config"]["potential_method"] = "已是 RHE"
        before = output["data"].copy(deep=True)
        table = curve_plot_table({"already_rhe": output})
        self.assertTrue(table.columns[0].endswith("E_RHE_V"))
        np.testing.assert_array_equal(table.iloc[:, 0], before.E_V)
        np.testing.assert_array_equal(table.iloc[:, 1], before.plotted_current_value)
        pd.testing.assert_frame_equal(output["data"], before)

    def test_metadata_in_frame_is_supported_and_ambiguous_metadata_is_rejected(self):
        output = curve([.9, .8], [2., 3.])
        output["data"]["plot_channel"] = output.pop("plot_channel")
        output["data"]["plot_smoothing_enabled"] = output.pop("plot_smoothing_enabled")
        self.assertEqual(curve_plot_table({"i": output}).shape, (2, 2))
        output["data"].loc[1, "plotted_current_unit"] = "uA"
        with self.assertRaisesRegex(ValueError, "记录不一致"):
            curve_plot_table({"i": output})

    def test_missing_current_values_do_not_fall_back_to_another_current(self):
        output = curve([.9], [2.])
        output["data"] = output["data"].drop(columns="plotted_current_value")
        output["data"]["I_disk_A"] = [2.]
        with self.assertRaisesRegex(ValueError, "plotted_current_value"):
            curve_plot_table({"i": output})
        output = curve([.9], [2.], smooth="False")
        with self.assertRaisesRegex(ValueError, "布尔值"):
            curve_plot_table({"i": output})

    def test_csv_bom_header_only_and_float_roundtrip(self):
        output = curve([.12345678901234567, .9999999999999999],
                       [-1.2345678901234567e-8, np.nan], name="中文,样品")
        table = curve_plot_table({"roundtrip": output})
        payload = csv_bytes(table)
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        self.assertEqual(len(payload.decode("utf-8-sig").splitlines()), 3)
        loaded = pd.read_csv(BytesIO(payload), float_precision="round_trip")
        self.assertEqual(list(loaded.columns), list(table.columns))
        self.assertFalse(any(c.startswith("Unnamed") for c in loaded.columns))
        np.testing.assert_array_equal(loaded.to_numpy(), table.to_numpy())

    def test_empty_selection_is_an_empty_numeric_table(self):
        self.assertTrue(curve_plot_table({}).empty)
        self.assertTrue(rrde_plot_table({}, {}).empty)


class OriginAnalysisExportTests(unittest.TestCase):
    def test_original_mode_already_rhe_rrde_labels_rhe_without_shifting_potential(self):
        output = curve([.8, .7], [0., 0.], axis="原始")
        output["config"]["potential_method"] = "已是 RHE"
        result = pd.DataFrame({"E_V": [.8, .7], "peroxide_pct": [120., np.nan],
                               "n_RRDE": [1.6, np.nan], "four_e_pct_model": [-20., np.nan]})
        before = result.copy(deep=True)
        table = rrde_plot_table({"rrde_rhe": result}, {"rrde_rhe": output})
        self.assertTrue(table.columns[0].endswith("E_RHE_V"))
        np.testing.assert_array_equal(table.to_numpy(), before.to_numpy())
        pd.testing.assert_frame_equal(result, before)

    def test_rrde_keeps_independent_grids_and_out_of_range_values(self):
        outputs = {"aaaa1111": curve([.8, .7, .6], [0., 0., 0.]),
                   "bbbb2222": curve([.795], [0.], axis="原始")}
        results = {
            "aaaa1111": pd.DataFrame({"E_V": [.8, .7, .6], "peroxide_pct": [120., np.nan, 20.],
                                      "n_RRDE": [1.6, np.nan, 3.6],
                                      "four_e_pct_model": [-20., np.nan, 80.]}),
            "bbbb2222": pd.DataFrame({"E_V": [.795], "peroxide_pct": [30.],
                                      "n_RRDE": [3.4], "four_e_pct_model": [70.]}),
        }
        before = {i: frame.copy(deep=True) for i, frame in results.items()}
        table = rrde_plot_table(results, outputs)
        self.assertEqual(table.shape, (3, 8))
        np.testing.assert_array_equal(table.iloc[:, 1], [120., np.nan, 20.])
        np.testing.assert_array_equal(table.iloc[:, 3], [-20., np.nan, 80.])
        np.testing.assert_array_equal(table.iloc[:, 4], [.795, np.nan, np.nan])
        for ident in before:
            pd.testing.assert_frame_equal(before[ident], results[ident])

    def test_kl_fit_preserves_existing_values_order_gaps_and_unequal_group_lengths(self):
        points = pd.DataFrame({
            "E_V": [.7, .8, .7, .8, .7], "rpm": [400, 900, 1600, 1600, 900],
            "omega_inv_sqrt": [.15, .10, .07, .08, .11],
            "inverse_j_cm2_A": [1.001, 2.002, np.nan, 4.004, 5.005],
            "fit_inverse_j_cm2_A": [1.111, 2.222, 3.333, 4.444, 5.555],
        }, index=[10, 20, 30, 40, 50])
        before = points.copy(deep=True)
        table = kl_fit_plot_table(points, "RHE")
        self.assertEqual(table.shape, (3, 6))
        self.assertTrue(all("=0.7__" in c for c in table.columns[:3]))
        np.testing.assert_array_equal(table.iloc[:, 0], [.15, .07, .11])
        np.testing.assert_array_equal(table.iloc[:, 1], [1.001, np.nan, 5.005])
        np.testing.assert_array_equal(table.iloc[:, 2], [1.111, 3.333, 5.555])
        np.testing.assert_array_equal(table.iloc[:, 3], [.10, .08, np.nan])
        pd.testing.assert_frame_equal(points, before)

    def test_kl_adjacent_float_potentials_do_not_merge(self):
        e1 = .3
        e2 = float(np.nextafter(e1, 1.))
        points = pd.DataFrame({"E_V": [e1, e2], "omega_inv_sqrt": [.1, .2],
                               "inverse_j_cm2_A": [10., 20.], "fit_inverse_j_cm2_A": [11., 21.]})
        table = kl_fit_plot_table(points, "原始")
        self.assertEqual(table.shape, (1, 6))
        self.assertTrue(table.columns.is_unique)
        self.assertTrue(all("E_original_reference_V" in c for c in table.columns))

    def test_invalid_fit_potential_and_missing_rrde_identity_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "有效的分析电位"):
            kl_fit_plot_table(pd.DataFrame({"E_V": [np.nan]}), "RHE")
        with self.assertRaisesRegex(ValueError, "处理记录"):
            rrde_plot_table({"unknown": pd.DataFrame()}, {})
        self.assertTrue(kl_fit_plot_table(pd.DataFrame(), "RHE").empty)


if __name__ == "__main__":
    unittest.main()
