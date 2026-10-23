import copy
from io import BytesIO
import json
import unittest
import zipfile

import numpy as np
import pandas as pd

from background_pairing import apply_background_binding
from background_ph import activate_ph_links, synchronize_ph_links
from orr_core import DataError, default_config, pack_project, parse_chi, process_trace, unpack_project
from plot_smoothing import smooth_for_plot, SMOOTH_RING_A
from ring_comparison import audit_ring_comparison


def ring_fixture(name="sample.txt", disk=-10e-6, ring=2e-6, low=0., high=1.):
    rows="\n".join(f"{e:.5f},{disk:.12g},{ring:.12g}" for e in np.linspace(high, low, 101))
    raw=(f"Linear Sweep Voltammetry\nHigh E (V) = {high}\nLow E (V) = {low}\n"
         "Scan Rate (V/s) = 0.005\nSample Interval (V) = 0.01\nPotential/V,i1/A,i2/A\n"+rows).encode()
    trace=parse_chi(name, raw)
    cfg=default_config(trace)
    cfg.update(manual_segment=1, area_cm2=None, collection_efficiency=None)
    return trace,cfg


class RingProcessingTests(unittest.TestCase):
    def setUp(self):
        self.t,self.c=ring_fixture()
        self.b,self.bc=ring_fixture("background.txt",-1e-6,.2e-6)
        self.bc["role"]="背景"
        self.traces={self.t.id:self.t,self.b.id:self.b}
        self.configs={self.t.id:self.c,self.b.id:self.bc}

    def bind(self):
        apply_background_binding(self.t.id,self.c,self.traces,self.configs,"paired",self.b.id)

    def run_trace(self, **kwargs):
        return process_trace(self.t,self.c,self.traces,self.configs,"原始",**kwargs)

    def test_paired_known_answer_and_swapped_background_mapping(self):
        self.bind()
        df=self.run_trace()["data"]
        np.testing.assert_allclose(df.I_disk_A,-9e-6)
        np.testing.assert_allclose(df.I_ring_A,1.8e-6)

        self.c['ring_sign']=0
        with self.assertRaisesRegex(DataError,'符号'):
            self.run_trace(channels='ring')
        self.c['ring_sign']=1
        self.b.values[:,[1,2]]=self.b.values[:,[2,1]]
        self.bc.update(disk_channel=1,ring_channel=0)
        df=self.run_trace()["data"]
        np.testing.assert_allclose(df.I_disk_A,-9e-6)
        np.testing.assert_allclose(df.I_ring_A,1.8e-6)

    def test_pair_rejects_single_channel_and_self_without_mutation(self):
        before=copy.deepcopy(self.c)
        self.bc["ring_channel"]=None
        with self.assertRaises(DataError): self.bind()
        self.assertEqual(self.c,before)
        with self.assertRaises(DataError):
            apply_background_binding(self.t.id,self.c,self.traces,self.configs,"paired",self.t.id)

    def test_independent_and_unbinding_are_explicit(self):
        self.bind()
        apply_background_binding(self.t.id,self.c,self.traces,self.configs,"independent",self.b.id,None)
        self.assertEqual(self.c["background_disk"],self.b.id)
        self.assertIsNone(self.c["background_ring"])
        apply_background_binding(self.t.id,self.c,self.traces,self.configs,"paired",None)
        self.assertIsNone(self.c["background_disk"])
        self.assertIsNone(self.c["background_ring"])

    def test_ring_only_ignores_unrelated_disk_but_ir_keeps_raw_dependency(self):
        self.c.update(disk_channel=99,background_disk="absent")
        result=self.run_trace(channels="ring")
        np.testing.assert_allclose(result["data"].I_ring_A,2e-6)
        self.assertNotIn("I_disk_A",result["data"])
        self.c.update(ir_enabled=True,ir_confirmed=True,ir_ohm=10)
        with self.assertRaisesRegex(DataError,"iR"):
            self.run_trace(channels="ring")
        self.c["disk_channel"]=0
        df=self.run_trace(channels="ring")["data"]
        np.testing.assert_allclose(df.E_V,df.E_original_V-df.I_disk_raw_A*10)

    def test_raw_view_bypasses_background_and_does_not_mutate_binding(self):
        self.c.update(background_ring="absent",background_disk="absent")
        before=copy.deepcopy(self.c)
        df=self.run_trace(channels="ring",subtract_background=False)["data"]
        np.testing.assert_allclose(df.I_ring_A,2e-6)
        self.assertTrue(df.I_ring_background_A.isna().all())
        self.assertTrue((df.ring_background_status=="未参与").all())
        self.assertEqual(self.c,before)
        with self.assertRaises(DataError): self.run_trace(channels="ring")

    def test_ring_background_does_not_need_background_disk_unless_ir_enabled(self):
        self.bind()
        self.bc["disk_channel"]=99
        df=self.run_trace(channels="ring")["data"]
        np.testing.assert_allclose(df.I_ring_A,1.8e-6)
        self.bc.update(ir_enabled=True,ir_confirmed=True,ir_ohm=1)
        with self.assertRaises(DataError): self.run_trace(channels="ring")

    def test_partial_background_preserves_gaps(self):
        b,bc=ring_fixture("partial.txt",-1e-6,.2e-6,low=.2,high=.8)
        bc["role"]="背景"
        self.traces[b.id]=b; self.configs[b.id]=bc
        self.c["background_ring"]=b.id
        df=self.run_trace(channels="ring")["data"]
        self.assertTrue(df.I_ring_A.isna().any())
        np.testing.assert_allclose(df.I_ring_A.dropna(),1.8e-6)
        self.assertTrue(df.loc[df.I_ring_A.isna(),"ring_background_status"].str.contains("不外推").all())

    def test_paired_ph_sources_deduplicate_and_legacy_migration_preserves(self):
        self.c["pH"]=13.
        self.bind()
        activate_ph_links(self.configs,[self.b.id])
        synchronize_ph_links(self.configs)
        self.assertEqual(len(self.bc["background_ph_sources"]),1)
        raw=pack_project(self.traces,self.configs,{"axis":"原始","plot_channel":"ring","ring_plot":{"unit":"uA"}})
        _,restored,settings=unpack_project(raw)
        self.assertEqual(restored[self.t.id]["background_mode"],"paired")
        self.assertEqual(settings["ring_plot"]["unit"],"uA")
        old=BytesIO()
        with zipfile.ZipFile(BytesIO(raw)) as source,zipfile.ZipFile(old,"w") as target:
            for item in source.namelist():
                content=source.read(item)
                if item=="project.json":
                    manifest=json.loads(content)
                    manifest["schema"]=1
                    for f in manifest["files"]:
                        f["config"].pop("background_mode",None)
                        f["config"].pop("background_conditions_mode",None)
                        f["config"].pop("background_conditions_migration",None)
                    content=json.dumps(manifest).encode()
                target.writestr(item,content)
        _,legacy,_=unpack_project(old.getvalue())
        self.assertEqual(legacy[self.t.id]["background_mode"],"independent")
        self.assertEqual(legacy[self.t.id]["background_ring"],self.b.id)

    def test_ring_units_and_smoothing_use_only_ring_and_retain_gaps(self):
        df=self.run_trace(channels="ring")["data"]
        np.testing.assert_allclose(df.I_ring_uA,2.)
        np.testing.assert_allclose(df.I_ring_mA,.002)
        df.loc[40:45,"I_ring_A"]=np.nan
        df["I_disk_A"]=-100.
        before=df.copy(deep=True)
        smooth,report=smooth_for_plot(df,{"enabled":True,"window_points":11},channel="ring")
        pd.testing.assert_frame_equal(df,before)
        self.assertTrue(smooth[SMOOTH_RING_A].iloc[40:46].isna().all())
        np.testing.assert_allclose(smooth[SMOOTH_RING_A].dropna(),2e-6)
        np.testing.assert_allclose(smooth.I_disk_A,-100.)
        self.assertEqual(report["scope"],"ring_current_plot_only")


class RingConditionTests(unittest.TestCase):
    def outputs(self):
        outputs={}
        for index in range(3):
            t,c=ring_fixture(f"sample{index}.txt")
            c.update(rpm=400+index*400,ring_potential_V=.2+index*.1,group=str(index))
            outputs[t.id]=process_trace(t,c,{t.id:t},{t.id:c},"原始",channels="ring")
        return outputs

    def test_different_samples_rpms_ring_potentials_and_missing_allowed(self):
        outputs=self.outputs()
        first=next(iter(outputs.values()))
        first["config"].update(pH=13.,ring_potential_V=None)
        audit=audit_ring_comparison(outputs)
        self.assertTrue(audit["allowed"])
        self.assertTrue(audit["missing"])
        self.assertIn("未完整核对",audit["status"])

    def test_known_conflicts_cannot_be_hidden_by_a_missing_third_value(self):
        for field,a,b in (("pH",13.,12.),("pH","invalid saved value",13.),("electrolyte","NaOH","KOH"),("reference","SCE","Ag/AgCl"),
                          ("temperature_C",25.,30.),("ir_enabled",False,True)):
            with self.subTest(field=field):
                outputs=self.outputs()
                records=list(outputs.values())
                records[0]["config"][field]=a; records[1]["config"][field]=b
                self.assertFalse(audit_ring_comparison(outputs)["allowed"])
        outputs=self.outputs()
        list(outputs.values())[1]["segment"]["direction"]="递增"
        self.assertFalse(audit_ring_comparison(outputs)["allowed"])

    def test_harmless_text_spacing_and_float_noise_do_not_conflict(self):
        outputs=self.outputs()
        for index,o in enumerate(outputs.values()):
            o["config"].update(electrolyte=" NaOH " if index else "naoh",pH=13.+index*1e-11)
        self.assertTrue(audit_ring_comparison(outputs)["allowed"])
