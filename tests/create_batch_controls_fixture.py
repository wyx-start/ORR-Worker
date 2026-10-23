"""Ten synthetic records plus blank-rpm and legacy fixtures; no real files read."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from orr_core import default_config, pack_project, parse_chi


def make(name, scale=1.):
    e = [i/10 for i in range(11)]+[i/10 for i in range(9,-1,-1)]+[i/10 for i in range(1,11)]+[i/10 for i in range(9,4,-1)]
    text = ("SYNTHETIC BROWSER TEST\nCyclic Voltammetry\nLow E (V) = 0\nHigh E (V) = 1\n"
            "Sample Interval (V) = 0.1\nScan Rate (V/s) = 0.005\nPotential/V,i1/A,i2/A\n")
    text += "\n".join(f"{x},{-scale*1e-3*(1+x)},{scale*1e-5*(1+x)}" for x in e)
    return parse_chi(name, text.encode())


def build():
    output = Path(__file__).resolve().parents[1]/"verification"
    output.mkdir(exist_ok=True)
    traces, records = {}, {}
    names = ["sample-unknown.txt", "sample-900rpm-1600rpm.txt"]+[f"sample-{rpm}rpm.txt" for rpm in (400,625,900,1225,1600,2025,2500)]
    for index, name in enumerate(names+["Ar-background.txt"]):
        trace = make(name, .1 if name.startswith("Ar-") else 1+index/10)
        cfg = default_config(trace)
        cfg.update(group="batch", pH=13., ref_V_SHE=.197, reference="Ag/AgCl", filling="饱和 KCl",
                   reference_preset_C=25., manual_segment=2, electrolyte="O2 synthetic electrolyte")
        if index == 2:
            cfg["collection_efficiency"] = .4
        if name.startswith("Ar-"):
            cfg.update(role="背景", background_mode="independent", pH=11., electrolyte="Ar synthetic background")
        traces[trace.id], records[trace.id] = trace, cfg
    settings = {"axis":"原始", "plot":{}, "kl":{}, "rrde":{"floor_A":8e-9}, "presets":{"old":{"pH":7.}}}
    (output/"batch_controls.orrproj").write_bytes(pack_project(traces, records, settings))
    blank = [make("unmarked-a.txt"),make("unmarked-b.txt")]
    (output/"blank_rpm_controls.orrproj").write_bytes(pack_project({t.id:t for t in blank},
        {t.id:dict(default_config(t), manual_segment=2) for t in blank}, settings))
    # A genuine legacy strategy remains legacy within a schema=2 container.
    bgid = next(i for i,c in records.items() if c["role"] == "背景")
    records[bgid].update(background_conditions_mode="legacy_ph", background_ph_mode="follow", background_ph_legacy=False)
    for ident,cfg in records.items():
        if ident != bgid:
            cfg.update(background_disk=bgid, background_ring=bgid, background_mode="paired")
    records[next(iter(records))]["pH"] = 12.
    (output/"background_ph_conflict_fixture.orrproj").write_bytes(pack_project(traces, records, settings))
    print("Synthetic batch/blank-rpm/legacy fixtures ready")


if __name__ == "__main__":
    build()
