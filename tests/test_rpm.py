from io import BytesIO
import json
from pathlib import Path
import unittest
import zipfile

import pandas as pd

from orr_core import (DataError, RPM_FIELDS, default_config, fill_missing_rpms,
                      infer_rpm_from_name, kl_calculate, pack_project, parameter_record,
                      parse_chi, rpm_source_label, set_manual_rpm, unpack_project)

ROOT=Path(__file__).resolve().parents[1]
RAW=(ROOT/"examples"/"O-0.1MNa-5mv-900.txt").read_bytes()


def trace(name):
    return parse_chi(name,RAW)


def without_provenance(project, value):
    src=zipfile.ZipFile(BytesIO(project))
    output=BytesIO()
    with zipfile.ZipFile(output,"w") as archive:
        for name in src.namelist():
            raw=src.read(name)
            if name=="project.json":
                document=json.loads(raw)
                document["app_version"]="1.1.0"
                cfg=document["files"][0]["config"]
                for field in RPM_FIELDS:
                    if field!="rpm": cfg.pop(field,None)
                cfg["rpm"]=value
                cfg["group"]="人工保存的分组"
                raw=json.dumps(document,ensure_ascii=False).encode()
            archive.writestr(name,raw)
    return output.getvalue()


class FilenameRpmTests(unittest.TestCase):
    def test_explicit_spellings_and_positions(self):
        names=["CoPc_1600转.txt","CoPc_1600 转_测试.txt","CoPc_1600转每分钟.txt",
               "CoPc_1600rpm.txt","CoPc_1600 RPM_测试.txt","CoPc_RPM1600.txt",
               "CoPc_rpm=1600.txt","CoPc_转速1600.txt","CoPc_转速=1600.txt",
               "CoPc_转速：1600.txt","CoPc_1600转_第2次.txt","CoPc-1600rpm.txt",
               "CoPc1600转测试.txt","CoPc_转速1600转.txt"]
        for name in names:
            with self.subTest(name=name):
                result=infer_rpm_from_name(name)
                self.assertEqual(result["rpm"],1600)
                self.assertEqual(result["rpm_source"],"filename_explicit")
                self.assertEqual(result["rpm_candidates"],[1600])

    def test_explicit_markers_win_over_trailing_index(self):
        self.assertEqual(infer_rpm_from_name("CoPc_1600转_900.txt")["rpm"],1600)

    def test_legacy_names_compatible(self):
        for rpm in (900,1225):
            result=infer_rpm_from_name(f"O-0.1MNa-5mv-{rpm}.txt")
            self.assertEqual(result["rpm"],rpm)
            self.assertEqual(result["rpm_source"],"filename_legacy")
            self.assertEqual(result["group"],"O-0.1MNa-5mv")

    def test_duplicate_matches_are_one_candidate(self):
        result=infer_rpm_from_name("CoPc_1600rpm_1600转.txt")
        self.assertEqual(result["rpm"],1600)
        self.assertEqual(result["rpm_candidates"],[1600])
        self.assertEqual(result["group"],"CoPc")
        self.assertGreaterEqual(len(result["rpm_matches"]),2)

    def test_conflict_stays_empty_without_fallback_or_group_merge(self):
        result=infer_rpm_from_name("CoPc_900转_1600转_1225.txt")
        self.assertIsNone(result["rpm"])
        self.assertEqual(result["rpm_candidates"],[900,1600])
        self.assertEqual(result["rpm_status"],"ambiguous")
        self.assertIn("冲突",rpm_source_label(result))
        self.assertEqual(result["group"],"CoPc_900转_1600转_1225")

    def test_decimal_and_negative_not_partially_parsed(self):
        for name in ("CoPc_1600.5rpm.txt","CoPc_RPM1600.5_900.txt","CoPc_.5rpm.txt",
                     "CoPc_转速=-1600.txt","-1600rpm.txt","CoPc_-1600rpm.txt"):
            with self.subTest(name=name):
                result=infer_rpm_from_name(name)
                self.assertIsNone(result["rpm"])
                self.assertEqual(result["rpm_status"],"invalid")

    def test_unrelated_digits_and_chinese_words_not_rotation(self):
        for name in ("CoPc_0.1MNaOH_5mv.txt","CoPc_20261014.txt","CoPc_1600转化测试.txt",
                     "CoPc_1600转换.txt","CoPc_1600转移.txt"):
            with self.subTest(name=name):
                self.assertIsNone(infer_rpm_from_name(name)["rpm"])

    def test_basename_only(self):
        for name in (r"C:\1600转\CoPc.txt","/data/1600rpm/CoPc.txt"):
            self.assertIsNone(infer_rpm_from_name(name)["rpm"])

    def test_non_rpm_units_not_converted(self):
        result=infer_rpm_from_name("CoPc_26.7rps.txt")
        self.assertIsNone(result["rpm"])
        self.assertEqual(result["rpm_status"],"unsupported")

    def test_zero_preserved_but_rejected_by_KL(self):
        self.assertEqual(infer_rpm_from_name("CoPc_0转.txt")["rpm"],0)
        curve={"config":{"rpm":0},"data":pd.DataFrame()}
        with self.assertRaises(DataError): kl_calculate([curve,curve],[0],1.2e-6,1.9e-5,.01)

    def test_group_removes_only_rotation_and_empty_wrappers(self):
        for name in ("CoPc_900转_碱性.txt","CoPc_(1600转)_碱性.txt","CoPc_RPM1600_碱性.txt"):
            self.assertEqual(infer_rpm_from_name(name)["group"],"CoPc_碱性")
        self.assertEqual(infer_rpm_from_name("CoPc_1600转_第2次.txt")["group"],"CoPc_第2次")

    def test_confirmation_keeps_automatic_provenance(self):
        t=trace("CoPc_1600转.txt")
        cfg=default_config(t)
        self.assertFalse(set_manual_rpm(cfg,1600))
        self.assertEqual(cfg["rpm_source"],"filename_explicit")
        self.assertTrue(set_manual_rpm(cfg,900))
        self.assertEqual(cfg["rpm_source"],"manual")
        self.assertEqual(cfg["rpm"],900)
        self.assertEqual(cfg["rpm_candidates"],[1600])

    def test_manual_clear_and_invalid_input(self):
        cfg=default_config(trace("CoPc_1600转.txt"))
        self.assertTrue(set_manual_rpm(cfg,None))
        self.assertIsNone(cfg["rpm"])
        self.assertEqual(cfg["rpm_source"],"manual")
        for bad in (-1,float("inf"),True):
            with self.assertRaises(DataError): set_manual_rpm(cfg,bad)

    def test_fill_only_empty_preserves_zero_manual_values_and_group(self):
        ts=[trace("CoPc_1600转.txt"),trace("CoPc_900转.txt"),trace("CoPc_0转.txt"),trace("CoPc_900转_1600转.txt")]
        traces={t.id:t for t in ts}
        configs={t.id:default_config(t) for t in ts}
        set_manual_rpm(configs[ts[0].id],None)
        configs[ts[0].id]["group"]="保留分组"
        set_manual_rpm(configs[ts[1].id],1200)
        filled,unresolved=fill_missing_rpms(traces,configs)
        self.assertEqual(filled,1)
        self.assertEqual(len(unresolved),1)
        self.assertEqual(configs[ts[0].id]["rpm"],1600)
        self.assertEqual(configs[ts[0].id]["group"],"保留分组")
        self.assertEqual(configs[ts[1].id]["rpm"],1200)
        self.assertEqual(configs[ts[1].id]["rpm_source"],"manual")
        self.assertEqual(configs[ts[2].id]["rpm"],0)

    def test_project_and_parameter_export_preserve_provenance(self):
        t=trace("CoPc_1600转.txt")
        cfg=default_config(t)
        set_manual_rpm(cfg,900)
        ts,cs,settings=unpack_project(pack_project({t.id:t},{t.id:cfg},{"axis":"原始"}))
        self.assertEqual(cs[t.id],cfg)
        output=parameter_record(ts,cs,settings)
        self.assertEqual(output["files"][0]["config"]["rpm_source"],"manual")

    def test_old_project_does_not_reinfer_saved_value_or_empty(self):
        t=trace("CoPc_1600转.txt")
        project=pack_project({t.id:t},{t.id:default_config(t)},{"axis":"原始"})
        for old_value in (900,None):
            with self.subTest(value=old_value):
                _,configs,_=unpack_project(without_provenance(project,old_value))
                cfg=configs[t.id]
                self.assertEqual(cfg["rpm"],old_value)
                self.assertEqual(cfg["rpm_source"],"saved_project")
                self.assertEqual(cfg["rpm_candidates"],[])
                self.assertEqual(cfg["group"],"人工保存的分组")


if __name__=="__main__":
    unittest.main()
