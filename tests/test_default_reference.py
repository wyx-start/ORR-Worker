"""User-selected new-import defaults, preserved historical values and compact UI."""
from io import BytesIO
import json
from pathlib import Path
import unittest
import zipfile

from streamlit.testing.v1 import AppTest
from orr_core import DataError, default_config, pack_project, parse_chi, rhe_shift, unpack_project

ROOT = Path(__file__).resolve().parents[1]


def sample():
    return parse_chi("new-1600rpm.txt", b"Cyclic Voltammetry\nLow E (V) = 0\nHigh E (V) = 1\nSample Interval (V) = 0.5\nPotential/V,Current/A\n0,-0.001\n0.5,-0.002\n1,-0.003\n0.5,-0.002\n0,-0.001")


class DefaultReferenceTests(unittest.TestCase):
    def test_new_import_has_complete_sce_and_ph_defaults_with_sources(self):
        cfg = default_config(sample())
        self.assertEqual((cfg["reference"],cfg["filling"],cfg["ref_V_SHE"],cfg["reference_preset_C"]),
                         ("SCE","饱和 KCl",.241,25.))
        self.assertEqual(cfg["pH"],13.)
        self.assertIn("软件默认",cfg["parameter_sources"]["pH"])
        self.assertIn("软件默认",cfg["parameter_sources"]["ref_V_SHE"])
        self.assertAlmostEqual(rhe_shift(cfg),1.0100715459,places=7)

    def test_sce_preset_remains_temperature_limited_and_editable(self):
        cfg = default_config(sample())
        cfg["temperature_C"] = 30.
        with self.assertRaisesRegex(DataError,"不适用于该温度"):
            rhe_shift(cfg)
        cfg.update(pH=7., reference="custom", ref_V_SHE=.2, reference_preset_C=None)
        self.assertIsInstance(rhe_shift(cfg),float)

    def test_saved_values_and_explicit_empty_values_are_not_defaulted(self):
        trace = sample()
        for ph,reference,voltage in ((7.,"Ag/AgCl",.197),(None,"未设置",None)):
            with self.subTest(ph=ph):
                cfg = dict(default_config(trace),pH=ph,reference=reference,ref_V_SHE=voltage)
                _,loaded,_ = unpack_project(pack_project({trace.id:trace},{trace.id:cfg},{"axis":"原始"}))
                self.assertEqual((loaded[trace.id]["pH"],loaded[trace.id]["reference"],loaded[trace.id]["ref_V_SHE"]),
                                 (ph,reference,voltage))

    def test_old_missing_fields_remain_unknown_in_both_schemas(self):
        trace = sample()
        data = pack_project({trace.id:trace},{trace.id:default_config(trace)},{"axis":"原始"})
        fields = ("pH","reference","filling","ref_V_SHE","reference_source","reference_preset_C")
        for schema in (1,2):
            stream = BytesIO()
            with zipfile.ZipFile(BytesIO(data)) as source, zipfile.ZipFile(stream,"w") as destination:
                for name in source.namelist():
                    raw = source.read(name)
                    if name == "project.json":
                        doc = json.loads(raw)
                        doc["schema"] = schema
                        cfg = doc["files"][0]["config"]
                        for field in fields:
                            cfg.pop(field,None)
                            cfg["parameter_sources"].pop(field,None)
                        raw = json.dumps(doc).encode()
                    destination.writestr(name,raw)
            _,records,_ = unpack_project(stream.getvalue())
            cfg = records[trace.id]
            self.assertIsNone(cfg["pH"])
            self.assertIsNone(cfg["ref_V_SHE"])
            self.assertEqual(cfg["reference"],"未设置")
            self.assertTrue(all(field not in cfg["parameter_sources"] for field in fields))

    def test_import_ui_defaults_visible_and_rpm_detail_section_removed(self):
        at = AppTest.from_file(str(ROOT/"streamlit_app.py"),default_timeout=30).run()
        next(b for b in at.button if b.label == "载入四份示例").click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(next(n for n in at.number_input if n.label == "pH *").value,13.)
        self.assertEqual(next(s for s in at.selectbox if s.label == "参比方案 *").value,"SCE · 饱和 KCl · 25 °C")
        self.assertNotIn("转速识别依据与需要核对的记录",[e.label for e in at.expander])
        self.assertEqual(at.session_state.settings_draft["configs"],{})


if __name__ == "__main__":
    unittest.main()
