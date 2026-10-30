"""Independent synthetic answers for threshold onset and plateau half-wave E.

The reference wave is exactly linear from 1.0 V / 0 mA to 0.6 V /
1 mA ORR current, with flat baseline and limiting regions. Its half-wave
potential is analytically 0.8 V; density threshold 0.1 mA/cm2 on 0.2 cm2
corresponds to 0.02 mA and an interpolated onset of 0.992 V.
"""
from copy import deepcopy
import unittest

import numpy as np
import pandas as pd

from application.potentials import analyze_potentials,potential_options
from orr_core import DataError


def wave(*,sign=-1,area=.2,baseline=0.,reverse=False):
    potential=np.linspace(1.2,0.,61)
    reduction=np.where(potential>=1.,0.,np.where(potential<=.6,1.,(1.-potential)/.4))+baseline
    frame=pd.DataFrame({'E_V':potential,'I_disk_A':reduction*sign/1000.})
    if reverse:frame=frame.iloc[::-1].reset_index(drop=True)
    return dict(name='generated-wave.txt',sha256='0'*64,axis='RHE',data=frame,
        config={'name':'generated wave','disk_sign':sign,'area_cm2':area,'potential_method':'理论换算'},
        segment={'segment':2,'direction':'递增' if reverse else '递减','complete':True},notes=[])


def set_current(output,potential,current_mA):
    frame=output['data'];index=np.flatnonzero(np.isclose(frame.E_V,potential,rtol=0.,atol=1e-10))
    assert len(index)==1
    frame.loc[int(index[0]),'I_disk_A']=current_mA*output['config']['disk_sign']/1000.


class PolarizationPotentialTests(unittest.TestCase):
    def test_default_options_are_independent_and_explicit(self):
        first=potential_options();second=potential_options()
        self.assertEqual(first['onset_threshold'],.1);self.assertEqual(first['onset_unit'],'mA/cm2')
        self.assertEqual(first['plateau_mode'],'auto');self.assertIsNone(first['plateau_start'])
        self.assertIsNone(first['plateau_end']);self.assertEqual(first['baseline_mA'],0.)
        self.assertFalse(first['show_markers']);first['onset_threshold']=2.
        self.assertEqual(second['onset_threshold'],.1)

    def test_exact_piecewise_wave_has_independently_known_potentials(self):
        result=analyze_potentials(wave())
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)
        self.assertAlmostEqual(result['plateau_current_mA'],1.,places=12)
        self.assertAlmostEqual(result['onset_target_mA'],.02,places=12)
        self.assertAlmostEqual(result['half_target_mA'],.5,places=12)
        self.assertGreaterEqual(result['plateau_points'],5)
        self.assertAlmostEqual(result['plateau_spread_fraction'],0.,places=12)

    def test_reversed_acquisition_gives_same_scientific_answer(self):
        direct=analyze_potentials(wave());reverse=analyze_potentials(wave(reverse=True))
        for key in ('E_onset_V','E_half_V','plateau_current_mA'):
            self.assertAlmostEqual(direct[key],reverse[key],places=12)

    def test_positive_raw_reduction_convention_uses_declared_sign(self):
        result=analyze_potentials(wave(sign=1))
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_wrong_reduction_sign_is_not_fixed_with_absolute_values(self):
        output=wave(sign=1);output['config']['disk_sign']=-1
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertIsNone(result['E_half_V'])
        self.assertTrue(result['onset_reason']);self.assertTrue(result['half_reason'])

    def test_nonzero_baseline_sets_midpoint_and_relative_onset(self):
        result=analyze_potentials(wave(baseline=.2),{'baseline_mA':.2})
        self.assertAlmostEqual(result['plateau_current_mA'],1.2,places=12)
        self.assertAlmostEqual(result['half_target_mA'],.7,places=12)
        self.assertAlmostEqual(result['onset_target_mA'],.22,places=12)
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)

    def test_missing_area_blocks_density_onset_but_not_current_half_wave(self):
        result=analyze_potentials(wave(area=None))
        self.assertIsNone(result['E_onset_V']);self.assertTrue(result['onset_reason'])
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_current_threshold_does_not_require_area(self):
        result=analyze_potentials(wave(area=None),{'onset_unit':'mA','onset_threshold':.1})
        self.assertAlmostEqual(result['onset_target_mA'],.1,places=12)
        self.assertAlmostEqual(result['E_onset_V'],.96,places=12)
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_targets_outside_current_coverage_are_not_extrapolated(self):
        result=analyze_potentials(wave(),{'onset_unit':'mA','onset_threshold':2.})
        self.assertIsNone(result['E_onset_V']);self.assertTrue(result['onset_reason'])
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_entire_curve_already_above_target_is_not_an_onset(self):
        output=wave();output['data']['I_disk_A']=-.001
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertIsNone(result['E_half_V'])

    def test_missing_onset_bracket_does_not_interpolate_across_nan(self):
        output=wave();set_current(output,.98,float('nan'))
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertTrue(result['onset_reason'])
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_missing_half_bracket_does_not_interpolate_across_nan(self):
        output=wave();set_current(output,.8,float('nan'))
        result=analyze_potentials(output)
        self.assertIsNone(result['E_half_V']);self.assertTrue(result['half_reason'])
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)

    def test_multiple_onset_crossings_are_ambiguous(self):
        output=wave();set_current(output,1.02,.04)
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertTrue(result['onset_reason'])
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)

    def test_horizontal_exact_threshold_has_no_unique_onset_potential(self):
        output=wave();set_current(output,1.0,.02);set_current(output,.98,.02)
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertTrue(result['onset_reason'])

    def test_nonmonotonic_electrode_branch_is_not_sorted_into_one_curve(self):
        output=wave();order=list(range(len(output['data'])));order[20],order[21]=order[21],order[20]
        output['data']=output['data'].iloc[order].reset_index(drop=True)
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertIsNone(result['E_half_V'])
        self.assertTrue(result['onset_reason']);self.assertTrue(result['half_reason'])

    def test_duplicate_potential_with_different_currents_is_not_merged(self):
        output=wave();output['data'].loc[21,'E_V']=output['data'].loc[20,'E_V']
        result=analyze_potentials(output)
        self.assertIsNone(result['E_onset_V']);self.assertIsNone(result['E_half_V'])

    def test_manual_plateau_window_uses_its_covered_points(self):
        result=analyze_potentials(wave(),{'plateau_mode':'manual','plateau_start':.1,'plateau_end':.3})
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)
        self.assertGreaterEqual(result['plateau_points'],10)
        self.assertAlmostEqual(result['plateau_current_mA'],1.,places=12)

    def test_manual_plateau_window_must_be_fully_covered(self):
        result=analyze_potentials(wave(),{'plateau_mode':'manual','plateau_start':-.05,'plateau_end':.3})
        self.assertIsNone(result['E_half_V']);self.assertTrue(result['half_reason'])
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)

    def test_plateau_requires_at_least_five_finite_points(self):
        output=wave();output['data']=output['data'].iloc[::6].reset_index(drop=True)
        result=analyze_potentials(output)
        self.assertIsNone(result['E_half_V']);self.assertTrue(result['half_reason'])
        self.assertIsNotNone(result['E_onset_V'])

    def test_sloping_low_potential_region_is_not_silently_a_plateau(self):
        output=wave();frame=output['data'];mask=frame.E_V<=.24
        frame.loc[mask,'I_disk_A']=-(1.+.8*(.24-frame.loc[mask,'E_V']))/1000.
        result=analyze_potentials(output)
        self.assertIsNone(result['E_half_V']);self.assertGreater(result['plateau_spread_fraction'],.10)
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)

    def test_display_smoothing_and_plot_columns_never_feed_metrics(self):
        output=wave();frame=output['data'];frame['plotted_current_value']=777.
        frame['I_disk_smoothed_plot_only_mA']=-100.
        before=deepcopy(output);result=analyze_potentials(output)
        self.assertAlmostEqual(result['E_onset_V'],.992,places=12)
        self.assertAlmostEqual(result['E_half_V'],.8,places=12)
        pd.testing.assert_frame_equal(output['data'],before['data']);self.assertEqual(output['config'],before['config'])

    def test_invalid_options_rejected_before_calculation(self):
        cases=[{'onset_threshold':0.},{'onset_threshold':-1.},{'onset_threshold':float('nan')},
            {'onset_threshold':float('inf')},{'onset_unit':'A/m2'},{'plateau_mode':'guess'},
            {'baseline_mA':float('nan')},{'plateau_mode':'manual'},
            {'plateau_mode':'manual','plateau_start':.3,'plateau_end':.1},
            {'plateau_mode':'manual','plateau_start':.3,'plateau_end':.3},
            {'plateau_mode':'manual','plateau_start':0.,'plateau_end':float('inf')}]
        for values in cases:
            with self.subTest(values=values),self.assertRaises(DataError):potential_options(values)


if __name__=='__main__':unittest.main()
