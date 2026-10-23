"""Build a synthetic shared-background condition project fixture.

Every trace is generated in memory as parse_chi-parseable text; no example
TXT, user_settings, credential or live session is read. The packed schema=2
project stores canonical records only: two samples carry a real pH conflict
(13 vs 12) over one shared background that follows while retaining its own
independent cache (pH 11, 20 °C, an independent reference record).
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orr_core import default_config, pack_project, parse_chi


def trace(name, scale=1.):
    potentials = [0., .2, .4, .6, .8, 1., .8, .6, .4, .2, 0.]
    lines = ["Cyclic Voltammetry", "Low E (V) = 0", "High E (V) = 1",
             "Sample Interval (V) = 0.2", "Scan Rate (V/s) = 0.005",
             "Potential/V, Current/A"]
    for potential in potentials:
        lines.append(f"{potential},{-scale * 1e-3 * (1 + potential)}")
    return parse_chi(name, "\n".join(lines).encode())


def build():
    first = trace("sample-a-1600rpm.txt")
    second = trace("sample-b-1600rpm.txt", 1.2)
    background = trace("Ar-background.txt", .1)
    traces = {item.id: item for item in (first, second, background)}
    configs = {ident: default_config(item) for ident, item in traces.items()}
    for ident, ph in ((first.id, 13.), (second.id, 12.)):
        configs[ident].update(role="样品", group="group_one", pH=ph, temperature_C=25.,
                              ref_V_SHE=.197, reference="Ag/AgCl", filling="3 M KCl",
                              reference_preset_C=25., reference_source="synthetic reference record",
                              background_disk=background.id)
        configs[ident]["parameter_sources"].update(pH="synthetic sample record",
                                                   ref_V_SHE="synthetic calibration")
    configs[background.id].update(role="背景", group="group_one", pH=11., temperature_C=20.,
                                  reference_preset_C=None,
                                  ref_V_SHE=.110, reference="Independent reference",
                                  filling="independent filling",
                                  reference_source="independent reference record")
    configs[background.id]["parameter_sources"].update(
        pH="independent pH record", temperature_C="independent temperature record")
    directory = ROOT / "verification"
    directory.mkdir(exist_ok=True)
    target = directory / "background_conditions_fixture.orrproj"
    target.write_bytes(pack_project(traces, configs,
                                    {"axis": "RHE", "plot": {}, "kl": {}, "presets": {}}))
    print(target.name)


if __name__ == "__main__":
    build()
