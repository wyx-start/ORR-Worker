"""Synthetic browser project; contains no user's experimental files or presets."""
from pathlib import Path
import copy
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from orr_core import pack_project
from test_ring_comparison import ring_fixture

ROOT=Path(__file__).resolve().parents[1]


def build():
    t,c=ring_fixture('Sample-A_900rpm.txt')
    u,uc=ring_fixture('Sample-B_1600rpm.txt',-12e-6,3e-6)
    b,bc=ring_fixture('Ar_RRDE_background.txt',-1e-6,.2e-6)
    c.update(group='Sample A',ring_potential_V=.2)
    uc.update(group='Sample B',ring_potential_V=.5)
    bc['role']='背景'
    traces={t.id:t,u.id:u,b.id:b}
    configs={t.id:c,u.id:uc,b.id:bc}
    settings={'axis':'原始','plot':{},'kl':{},'presets':{}}
    output=ROOT/'verification'
    output.mkdir(exist_ok=True)
    (output/'ring_initial.orrproj').write_bytes(pack_project(traces,configs,settings))
    conflict=copy.deepcopy(configs)
    conflict[t.id]['pH']=13.; conflict[u.id]['pH']=12.
    (output/'ring_conflict.orrproj').write_bytes(pack_project(traces,conflict,settings))
    print('Synthetic ring browser fixtures ready')


if __name__=='__main__': build()
