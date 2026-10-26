"""Small, fully generated inputs shared by both frontends' migration checks."""
from copy import deepcopy
from io import BytesIO
import json
import zipfile

import numpy as np

from orr_core import (FARADAY, KOH_PRESET, DataError, clean_json, default_config,
                      kl_calculate, pack_project, parameter_record, parse_chi,
                      process_trace, rrde_calculate, select_segment, unpack_project)
from background_conditions import resolved_configs
from origin_export import curve_plot_table, rrde_plot_table


def workspace():
    traces, records = {}, {}
    area, efficiency = np.pi/16, .369
    coefficient = .62*FARADAY*KOH_PRESET["D"]**(2/3)*KOH_PRESET["nu"]**(-1/6)*KOH_PRESET["C"]
    potentials = np.r_[np.linspace(0,1,11),np.linspace(.9,0,10),np.linspace(.1,.5,5)]
    for index, rpm in enumerate((400,625,900,1225,1600,2025,2500,3025,3600,None)):
        name = f"Synthetic-{rpm}rpm.txt" if rpm else "Ar-synthetic-background.txt"
        bg = rpm is None
        raw = ("SYNTHETIC MIGRATION FIXTURE - NO MEASURED DATA\nCyclic Voltammetry\n"
               "High E (V) = 1\nLow E (V) = 0\nSample Interval (V) = 0.1\n"
               "Scan Rate (V/s) = 0.005\nPotential/V,i1/A,i2/A\n")
        for e in potentials:
            kinetic = .005+(1-e)*.02
            limiting = 3.2*coefficient*np.sqrt(2*np.pi*rpm/60) if rpm else 0
            current = area/(1/kinetic+1/limiting) if rpm else 0
            disk, ring = -current-1e-5, efficiency*current*.25+2e-7
            if index == 8 and abs(e-.5)<1e-8:
                disk = -1e-5  # An RRDE denominator/threshold failure after subtraction.
            raw += f"{e:.12g},{disk:.16g},{ring:.16g}\n"
        trace = parse_chi(name,raw.encode())
        cfg = default_config(trace)
        cfg.update(group="migration",mode="A",electrolyte="synthetic O2 electrolyte",
                   ring_detection_confirmed=True)
        if bg:
            cfg.update(role="背景",background_mode="independent",electrolyte="synthetic Ar background",
                       pH=11.,reference="Independent record",ref_V_SHE=.11,reference_preset_C=None)
        traces[trace.id],records[trace.id] = trace,cfg
    background = next(i for i,c in records.items() if c["role"] == "背景")
    for ident,cfg in records.items():
        if ident != background:
            cfg.update(background_mode="paired",background_disk=background,background_ring=background)
    return traces,records,{"axis":"RHE","plot":{},"kl":{},"rrde":{"floor_A":1e-9},"presets":{}}


def table(frame):
    return clean_json({"columns":list(frame.columns),"rows":frame.to_numpy().tolist()})


def schema1_project(traces,records,settings):
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(pack_project(traces,records,settings))) as source, zipfile.ZipFile(output,"w") as target:
        for name in source.namelist():
            raw = source.read(name)
            if name == "project.json":
                manifest = json.loads(raw); manifest["schema"] = 1
                for item in manifest["files"]:
                    cfg = item["config"]
                    cfg.pop("background_conditions_mode",None)
                    cfg.pop("background_conditions_migration",None)
                    if cfg["role"] == "背景":
                        cfg.update(background_ph_mode="manual",background_ph_legacy=False)
                raw = json.dumps(manifest,ensure_ascii=False).encode()
            target.writestr(name,raw)
    return output.getvalue()


def snapshot():
    traces,records,settings = workspace()
    samples = [i for i,c in records.items() if c["role"] != "背景"]
    bg = next(i for i,c in records.items() if c["role"] == "背景")
    outputs = {i:process_trace(traces[i],records[i],traces,records,"RHE") for i in samples}
    rrde = {i:rrde_calculate(o,o["config"]) for i,o in outputs.items()}
    plotted = {}
    for ident,output in outputs.items():
        frame = output["data"].copy()
        frame["plotted_current_value"] = frame["I_disk_mA"]
        frame["plotted_current_unit"] = "mA"
        plotted[ident] = dict(output,data=frame,plot_channel="disk",plot_smoothing_enabled=False)
    first = outputs[samples[0]]
    e = first["data"].E_V.iloc[[2,5,8]].to_numpy()
    kl,points = kl_calculate([outputs[i] for i in samples[:3]],e,*(KOH_PRESET[k] for k in ("C","D","nu")))
    legacy = unpack_project(schema1_project(traces,records,settings))[1]
    restored = unpack_project(pack_project(traces,records,settings))[1]
    conflict = deepcopy(records); conflict[samples[1]]["pH"] = 12.
    missing = deepcopy(records); missing[samples[0]]["pH"] = None
    errors = {}
    for label,configs in (("conflict",conflict),("missing",missing)):
        try:
            process_trace(traces[samples[0]],configs[samples[0]],traces,configs,"RHE")
        except DataError as exc:
            errors[label] = str(exc)
    try:
        parse_chi("invalid.txt",b"not a CHI data file")
    except DataError as exc:
        errors["invalid_file"] = str(exc)
    return clean_json({"fixture_version":1,"source":"generated only","samples":len(samples),
        "defaults":records[samples[0]],"background_record":records[bg],
        "effective_background":resolved_configs(records)[bg]["background_conditions"],
        "segments":{i:select_segment(traces[i],records[i]) for i in samples},
        "processed":{i:table(o["data"]) for i,o in outputs.items()},
        "rrde":{i:table(f) for i,f in rrde.items()},"kl":table(kl),"kl_points":table(points),
        "curve_csv":table(curve_plot_table(plotted)),"rrde_csv":table(rrde_plot_table(rrde,outputs)),
        "roundtrip_schema2":restored,"roundtrip_schema1":legacy,"errors":errors,
        "audit_fields":list(parameter_record(traces,records,settings,outputs)["files"][0])})
