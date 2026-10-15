"""Experimental profiles and task-specific validation, independent of Streamlit."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile

from orr_core import DataError, require_number, rhe_shift

PROFILE_PATH = Path(__file__).resolve().parent / "user_settings" / "experiment_presets.json"
CONDITION_FIELDS = (
    "reference", "filling", "potential_method", "ref_V_SHE", "reference_source",
    "reference_preset_C", "pH", "temperature_C", "rhe_offset_V", "electrolyte",
    "area_cm2", "disk_diameter_mm", "area_mode", "collection_efficiency",
    "ring_material", "ring_potential_V",
)
AREA_FIELDS = ("area_cm2", "disk_diameter_mm", "area_mode")
NUMERIC_FIELDS = {"ref_V_SHE", "reference_preset_C", "pH", "temperature_C", "rhe_offset_V",
                  "area_cm2", "disk_diameter_mm", "collection_efficiency", "ring_potential_V"}


def area_from_diameter(diameter_mm):
    return math.pi * (require_number(diameter_mm, "盘直径（mm）", positive=True) / 20.)**2


def snapshot_conditions(cfg):
    """Only reusable conditions; never copy file identity or confirmations."""
    result = {k:copy.deepcopy(cfg[k]) for k in CONDITION_FIELDS if k in cfg}
    result["parameter_sources"] = {k:copy.deepcopy(v) for k,v in cfg.get("parameter_sources", {}).items()
                                   if k in CONDITION_FIELDS}
    return result


def validate_conditions(values):
    """Accept incomplete drafts but reject invalid supplied values."""
    for key in NUMERIC_FIELDS:
        if values.get(key) is not None:
            require_number(values[key], key, positive=key in ("area_cm2", "disk_diameter_mm", "collection_efficiency"))
    if values.get("collection_efficiency") is not None and float(values["collection_efficiency"]) > 1:
        raise DataError("收集效率 N 必须满足 0 < N ≤ 1，不能将百分数直接填入。")
    if values.get("temperature_C") is not None and float(values["temperature_C"]) <= -273.15:
        raise DataError("温度必须高于绝对零度。")
    if values.get("potential_method", "理论换算") not in ("理论换算", "实测 RHE 总偏移", "已是 RHE"):
        raise DataError("不支持的电位换算方式。")
    if values.get("area_mode", "area") not in ("area", "diameter"):
        raise DataError("不支持的盘面积输入方式。")
    if values.get("area_mode") == "diameter":
        area = area_from_diameter(values.get("disk_diameter_mm"))
        if values.get("area_cm2") is None or not math.isclose(area, float(values["area_cm2"]), rel_tol=1e-10):
            raise DataError("盘直径与几何面积不一致，请重新应用电极尺寸。")
    return values


def apply_conditions(cfg, values, source="人工输入", overwrite=True):
    values = snapshot_conditions(values)
    validate_conditions(values)
    sources = cfg.setdefault("parameter_sources", {})
    prior_sources = values.pop("parameter_sources", {})
    area_allowed = overwrite or cfg.get("area_cm2") is None or str(sources.get("area_cm2", "")).startswith("软件默认")
    ref_fields = ("reference", "filling", "ref_V_SHE", "reference_source", "reference_preset_C")
    ref_allowed = overwrite or all(cfg.get(k) in (None, "", "未设置") or
        cfg.get(k) == values.get(k) or str(sources.get(k, "")).startswith("软件默认")
        for k in ("reference", "filling", "ref_V_SHE") if k in values)
    changed = False
    for key, value in values.items():
        if key in AREA_FIELDS:
            allowed = area_allowed
        elif key in ref_fields:
            allowed = ref_allowed
        else:
            allowed = overwrite or cfg.get(key) in (None, "", "未设置") or str(sources.get(key, "")).startswith("软件默认")
        if not allowed:
            continue
        origin = prior_sources.get(key)
        field_source = f"{source}；原始来源：{origin}" if origin and origin != source else source
        if source == "人工输入" and cfg.get(key) == value and key in sources:
            field_source = sources[key]
        elif source == "人工输入" and key in ref_fields and str(values.get("reference_source", "")).startswith("https://"):
            field_source = "文献预设：" + values["reference_source"]
        changed |= cfg.get(key) != value or sources.get(key) != field_source
        cfg[key] = copy.deepcopy(value)
        sources[key] = field_source
    # A legacy project profile may carry only area; do not keep a stale 5 mm label.
    if "area_cm2" in values and "disk_diameter_mm" not in values and area_allowed:
        cfg.update(disk_diameter_mm=None, area_mode="area")
    return changed


def missing_conditions(cfg, purpose="curves", axis="RHE", density=False):
    issues = []
    if axis == "RHE":
        try:
            rhe_shift(cfg)
        except (DataError, ValueError, TypeError) as exc:
            issues.append(str(exc))
    if purpose == "kl" or density:
        try:
            require_number(cfg.get("area_cm2"), "盘几何面积（cm²）", positive=True)
        except DataError as exc:
            issues.append(str(exc))
    if purpose == "kl":
        try:
            require_number(cfg.get("rpm"), "转速（rpm）", positive=True)
        except DataError as exc:
            issues.append(str(exc))
    if purpose == "rrde":
        try:
            n = require_number(cfg.get("collection_efficiency"), "RRDE 收集效率 N（0–1）", positive=True)
            if n > 1:
                raise DataError("收集效率 N 不能大于 1。")
            if cfg.get("ring_channel") is None:
                raise DataError("需要有效的环电流通道。")
        except DataError as exc:
            issues.append(str(exc))
    return issues


def linked_backgrounds(cfg, configs):
    """Explicit background dependencies, de-duplicated without copying values."""
    return list(dict.fromkeys(cfg.get(field) for field in ("background_disk", "background_ring")
                              if cfg.get(field) in configs))


def unapplied_changes(cfg, draft):
    # Source text alone can differ for an unchanged selected preset.
    return any(cfg.get(key) != value for key,value in draft.items() if key != "reference_source")


def load_profiles(path=None):
    path = Path(path) if path is not None else PROFILE_PATH
    if not path.exists():
        return {}, None
    try:
        if path.stat().st_size > 1_000_000:
            raise ValueError("配置文件过大")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1 or not isinstance(data.get("presets"), dict):
            raise ValueError("配置格式不支持")
        profiles = {}
        for name, values in data["presets"].items():
            if not isinstance(name, str) or not name.strip() or not isinstance(values, dict):
                raise ValueError("预设结构不正确")
            if any(k not in CONDITION_FIELDS + ("parameter_sources",) for k in values):
                raise ValueError("预设包含非实验条件")
            for key, value in values.items():
                if key == "parameter_sources":
                    if not isinstance(value, dict) or any(k not in CONDITION_FIELDS or not isinstance(v, str) for k,v in value.items()):
                        raise ValueError("来源格式不正确")
                elif value is not None and (isinstance(value, bool) or
                        not isinstance(value, (int, float) if key in NUMERIC_FIELDS else str)):
                    raise ValueError(f"{key} 的类型不正确")
            profiles[name] = validate_conditions(snapshot_conditions(values))
        return profiles, None
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return {}, f"本机常用条件无法读取：{exc}。可继续手工设置或载入项目；原文件未修改。"


def save_profile(name, cfg, path=None):
    name = str(name).strip() or "常用条件"
    values = validate_conditions(snapshot_conditions(cfg))
    path = Path(path) if path is not None else PROFILE_PATH
    profiles, error = load_profiles(path)
    if error:
        raise DataError(error + " 请先检查该文件，再保存本机预设。")
    profiles[name] = values
    temp_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".presets-", suffix=".json", delete=False) as stream:
            temp_path = Path(stream.name)
            json.dump({"schema":1, "presets":profiles}, stream, ensure_ascii=False, indent=2, allow_nan=False)
        os.replace(temp_path, path)
    except (OSError, ValueError, TypeError) as exc:
        raise DataError(f"本机常用条件保存失败：{exc}；当前项目仍可使用。") from exc
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink()
    return profiles
