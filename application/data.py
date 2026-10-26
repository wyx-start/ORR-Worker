"""Detached tables and export bytes, shared by all frontends."""
from io import BytesIO
import zipfile
import pandas as pd

def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8-sig")

def merged_data(outputs):
    frames = []
    for ident, output in outputs.items():
        frame = output["data"].copy()
        frame.insert(0, "file_id", ident)
        frame.insert(1, "filename", output["name"])
        frame.insert(2, "potential_axis", output["axis"])
        frame.insert(3, "rpm", output["config"].get("rpm"))
        frame.insert(4, "rpm_source", output["config"].get("rpm_source"))
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def axis_label(outputs):
    if all(o["axis"] == "RHE" or o["config"].get("potential_method") == "已是 RHE" for o in outputs.values()):
        return "E / V vs. RHE"
    refs = {(o["config"].get("reference", "未设置"), o["config"].get("filling", "")) for o in outputs.values()}
    if len(refs) == 1 and next(iter(refs))[0] != "未设置":
        ref, filling = next(iter(refs))
        return f"E / V vs. {ref} ({filling})"
    return "E / V (original reference)"

def zip_exports(exports):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, info in exports.items():
            archive.writestr(name, info["bytes"])
    return buf.getvalue()
