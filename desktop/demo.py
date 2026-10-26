"""Synthetic acceptance inputs only; never measured data or production formulas."""
import numpy as np
from orr_core import FARADAY,KOH_PRESET,parse_chi,default_config

def generated_workspace():
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
