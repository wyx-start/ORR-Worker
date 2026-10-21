"""Finite synthetic inputs for the UI/Origin workflow; never reads examples."""
from pathlib import Path
import json
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orr_core import (FARADAY, KOH_PRESET, default_config, pack_project, parse_chi,
                      rhe_shift)


def build():
    root = Path(__file__).resolve().parents[1]
    output = root / "verification"
    output.mkdir(exist_ok=True)
    area, efficiency, electrons = np.pi * (.25 ** 2), .37, 3.2
    C, D, nu = (KOH_PRESET[key] for key in ("C", "D", "nu"))
    coefficient = .62 * FARADAY * C * D ** (2 / 3) * nu ** (-1 / 6)
    traces, configs, samples = {}, {}, []

    def make(name, e, disk, ring):
        rows = "\n".join(f"{x:.12g},{d:.16g},{r:.16g}" for x, d, r in zip(e, disk, ring))
        raw = ("SYNTHETIC UI TEST - NOT EXPERIMENTAL DATA\nLinear Sweep Voltammetry\n"
               f"High E (V) = {max(e):.12g}\nLow E (V) = {min(e):.12g}\n"
               f"Scan Rate (V/s) = 0.005\nSample Interval (V) = {abs(e[1] - e[0]):.12g}\n"
               "Potential/V,i1/A,i2/A\n" + rows).encode()
        trace = parse_chi(name, raw)
        cfg = default_config(trace)
        cfg.update(manual_segment=1, mode="B", pH=13., reference="Ag/AgCl", filling="saturated KCl",
                   ref_V_SHE=.197, reference_preset_C=None, potential_method="理论换算",
                   electrolyte="O2 saturated 0.1 M KOH", collection_efficiency=efficiency,
                   ring_detection_confirmed=True, ring_potential_V=.3, ring_material="Pt")
        traces[trace.id], configs[trace.id] = trace, cfg
        return trace, cfg

    for rpm, count in ((900, 101), (1225, 81), (1600, 121)):
        e = np.linspace(.9, .1, count)
        kinetic = .005 + (.9 - e) * .02
        limiting = electrons * coefficient * np.sqrt(rpm * 2 * np.pi / 60)
        j = 1 / (1 / kinetic + 1 / limiting)
        disk = -area * j
        ring = efficiency * abs(disk) * .25
        trace, cfg = make(f"Synthetic_{rpm}rpm.txt", e, disk - 1e-5, ring + 2e-7)
        cfg.update(name=f"Sample {rpm}", group="KL", rpm=float(rpm))
        samples.append(dict(id=trace.id, name=trace.name, label=cfg["name"], count=count))
    e = np.linspace(.9, .1, 91)
    disk = np.full(len(e), -8e-4)
    disk[len(e) // 2] = 0.  # A real threshold failure, without NaN in raw input.
    gap, gapcfg = make("Synthetic_gap_1600rpm.txt", e, disk - 1e-5,
                       np.full(len(e), efficiency * 8e-4 * .25 + 2e-7))
    gapcfg.update(name="Gap sample", group="Gap", rpm=1600.)
    background, bgcfg = make("Ar_synthetic_RRDE.txt", np.linspace(.9, .1, 161),
                            np.full(161, -1e-5), np.full(161, 2e-7))
    bgcfg.update(role="背景", name="Ar background", group="Background", background_mode="independent",
                 background_ph_mode="manual", background_ph_legacy=False)
    for ident, cfg in configs.items():
        if ident != background.id:
            cfg.update(background_mode="paired", background_disk=background.id,
                       background_ring=background.id, background_reviewed=True)
    settings = {"axis": "RHE", "plot": {"group": "KL"}, "ring_plot": {"group": "KL"},
                # Endpoints and midpoint are on every sample grid, allowing a
                # strict known-answer n check without interpolation error.
                "kl": {"group": "KL", "scheme": "koh_25C", "count": 3}, "rrde": {}, "presets": {}}
    fixture = output / "ui_simplification_initial.orrproj"
    fixture.write_bytes(pack_project(traces, configs, settings))
    expected = dict(samples=samples, gap=dict(id=gap.id, name=gap.name, label=gapcfg["name"], count=91, gap_row=45),
                    background=background.id, raw_first_E=.9, raw_last_E=.1,
                    initial_offset=rhe_shift(configs[samples[0]["id"]]),
                    ph_shift_per_unit=rhe_shift(dict(configs[samples[0]["id"]], pH=14.)) - rhe_shift(configs[samples[0]["id"]]),
                    collection_efficiency=efficiency, expected_n=electrons)
    (output / "ui_simplification_expected.json").write_text(json.dumps(expected, indent=2), encoding="utf-8")
    print(f"Synthetic UI fixture ready: {fixture.name}; {len(traces)} files")


if __name__ == "__main__":
    build()
