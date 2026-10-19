"""Audit known comparison conditions without treating missing records as agreement."""
import math
import re


FIELDS = {
    "pH":"pH", "temperature_C":"温度 / °C", "electrolyte":"电解液/浓度/气氛",
    "reference":"盘扫描参比", "filling":"参比内充液", "ref_V_SHE":"参比 vs SHE / V",
    "potential_method":"电位换算方式", "rhe_offset_V":"实测 RHE 偏移 / V",
    "direction":"实际扫描方向", "scan_rate":"扫描速率 / V·s⁻¹", "axis":"实际电位坐标",
    "ir_enabled":"追加 iR", "ir_ohm":"剩余补偿电阻 / Ω", "ring_sign":"环电流符号约定",
}
NUMBERS = {"pH", "temperature_C", "ref_V_SHE", "rhe_offset_V", "scan_rate", "ir_ohm", "ring_sign"}


def _known(value):
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ("", "未设置", "未记录")
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    return True


def _equal(a, b, numeric):
    if numeric:
        try:
            return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-10)
        except (TypeError, ValueError, OverflowError):
            return False  # A malformed saved record must not crash the page.
    return re.sub(r"\s+", " ", str(a).strip()).casefold() == re.sub(r"\s+", " ", str(b).strip()).casefold()


def audit_ring_comparison(outputs):
    rows, values = [], []
    for ident, output in outputs.items():
        cfg = output["config"]
        effective_axis = "RHE" if output["axis"] == "RHE" or cfg.get("potential_method") == "已是 RHE" else "原始"
        record = {key:cfg.get(key) for key in FIELDS}
        record.update(direction=output["segment"]["direction"], scan_rate=output.get("scan_rate_V_s"), axis=effective_axis,
                      ir_enabled=bool(cfg.get("ir_enabled", False)), ring_sign=cfg.get("ring_sign", 1))
        row = {"文件":output["name"], "样品":cfg.get("name"), "转速 / rpm":cfg.get("rpm"),
               "环设定电位 / V（仅记录）":cfg.get("ring_potential_V"),
               **{label:record[key] for key,label in FIELDS.items()}}
        values.append((output["name"], record))
        rows.append(row)
    conflicts, missing = [], []
    for key, label in FIELDS.items():
        applicable = [(name,record[key]) for name,record in values
                      if (key != "rhe_offset_V" or record["potential_method"] == "实测 RHE 总偏移")
                      and (key != "ir_ohm" or record["ir_enabled"])]
        known = [(name,val) for name,val in applicable if _known(val)]
        unknown = [name for name,val in applicable if not _known(val)]
        if unknown:
            missing.append({"条件":label, "未记录文件":"、".join(unknown)})
        if len(known) > 1 and any(not _equal(known[0][1], val, key in NUMBERS) for _,val in known[1:]):
            conflicts.append({"条件":label, "差异":"；".join(f"{name}：{val}" for name,val in known)})
    return dict(rows=rows, conflicts=conflicts, missing=missing,
                status="存在已知冲突" if conflicts else ("通过已知项检查，未完整核对" if missing else "通过已知项检查"),
                allowed=not conflicts, exceptions=["转速", "环设定电位"], view=next(iter(outputs.values()),{}).get("processing",{}))
