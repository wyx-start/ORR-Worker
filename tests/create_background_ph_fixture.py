"""Build a background-pH conflict fixture from the local example set."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orr_core import default_config, pack_project, parse_chi


def build():
    traces = {t.id:t for p in sorted((ROOT/"examples").glob("*.txt"))
              for t in [parse_chi(p.name, p.read_bytes())]}
    configs = {ident:default_config(t) for ident,t in traces.items()}
    bgid = next(k for k,c in configs.items() if c["role"] == "背景")
    configs[bgid].update(ref_V_SHE=.197, reference="Ag/AgCl", filling="饱和 KCl")
    samples = [k for k,c in configs.items() if c["role"] == "样品"]
    for ident, ph in zip(samples, (13., 12.)):
        configs[ident].update(pH=ph, ref_V_SHE=.197, reference="Ag/AgCl", filling="饱和 KCl", background_disk=bgid)
    for cfg in configs.values():
        if cfg["role"] == "RRDE":
            cfg["potential_method"] = "已是 RHE"  # fixture only; unrelated curve can continue
    directory = ROOT/"verification"
    directory.mkdir(exist_ok=True)
    target = directory/"background_ph_conflict_fixture.orrproj"
    target.write_bytes(pack_project(traces, configs, {"axis":"RHE", "plot":{}, "kl":{}, "presets":{}}))
    print(target.name)


if __name__ == "__main__":
    build()
