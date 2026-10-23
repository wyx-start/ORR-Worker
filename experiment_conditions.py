"""Experimental profiles and task-specific validation, independent of Streamlit."""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import tempfile

from orr_core import DataError, require_number, rhe_shift
from background_ph import ph_link_error
from background_conditions import INHERITED_FIELDS, condition_error, controlled_fields

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
    if cfg.get("role") == "背景" and controlled_fields(cfg) and "background_conditions" not in cfg:
        raise DataError("背景正在沿用关联样品条件；请使用已解析的有效条件保存或复制预设，不能读取独立缓存代替。")
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


def _apply_conditions(cfg, values, source="人工输入", overwrite=True, background_ph_edit=True):
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
        if key == "pH" and cfg.get("role") == "背景":
            if background_ph_edit and (cfg.get("pH") != value or value is not None and cfg.get("background_ph_mode") != "follow"):
                cfg.update(background_ph_mode="manual", background_ph_legacy=False)
            elif not background_ph_edit and cfg.get("background_ph_mode") in ("auto", "follow"):
                # Applying a sample's settings to its included background is
                # still a sample edit; it must not silently disable following.
                cfg.update(background_ph_mode="follow", background_ph_legacy=False)
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


def apply_conditions(cfg, values, source="人工输入", overwrite=True, background_ph_edit=True):
    """Update an independent record atomically; never accept a resolved view.

    Followed equal-value intents must first be removed using the caller's one
    resolved view. This function cannot infer the associated samples from cfg.
    Explicit legacy pH edits retain their old manual-switch semantics.
    """
    if "background_conditions" in cfg:
        raise DataError("有效条件视图不能直接修改；请使用 get_draft_view() 的 records 构建设置补丁。")
    supplied = snapshot_conditions(values)
    mode = cfg.get("background_conditions_mode", "legacy_ph")
    if cfg.get("role") == "背景" and mode == "follow":
        requested = set(INHERITED_FIELDS).intersection(supplied)
        if requested:
            raise DataError("背景的 " + "、".join(sorted(requested)) +
                            " 正在跟随关联样品；请先明确切到独立设置，或从有效视图消除真正的同值操作。")
    proposed = copy.deepcopy(cfg)
    keep_ph = (cfg.get("role") == "背景" and mode == "legacy_ph"
               and not background_ph_edit and "pH" in controlled_fields(cfg))
    changed = _apply_conditions(proposed, supplied, source, overwrite, background_ph_edit)
    if keep_ph:
        # Bulk sample changes only update the source; do not populate a legacy
        # background's independent record with its new effective pH.
        if "pH" in cfg:
            proposed["pH"] = copy.deepcopy(cfg["pH"])
        else:
            proposed.pop("pH", None)
        sources = proposed.setdefault("parameter_sources", {})
        if "pH" in cfg.get("parameter_sources", {}):
            sources["pH"] = copy.deepcopy(cfg["parameter_sources"]["pH"])
        else:
            sources.pop("pH", None)
    changed = proposed != cfg
    cfg.clear()
    cfg.update(proposed)
    return changed


def missing_conditions(cfg, purpose="curves", axis="RHE", density=False):
    issues = []
    link_error = condition_error(cfg) or ph_link_error(cfg)
    if link_error:
        issues.append(link_error)
    if axis == "RHE" and not link_error:
        method = cfg.get("potential_method", "理论换算")
        required = {"理论换算": ("pH", "temperature_C", "ref_V_SHE"),
                    "实测 RHE 总偏移": ("rhe_offset_V",), "已是 RHE": ()}.get(method, ("potential_method",))
        labels = {"pH": "pH", "temperature_C": "温度", "ref_V_SHE": "参比电位",
                  "rhe_offset_V": "实测 RHE 总偏移", "potential_method": "电位换算方式"}
        states = cfg.get("background_conditions", {}).get("field_states", {})
        if cfg.get("role") == "背景":
            for field in required:
                if cfg.get(field) is None:
                    waiting = not states.get(field, {}).get("editable", True)
                    issues.append(("等待关联样品填写 " if waiting else "背景自身缺少 ") + labels[field])
        try:
            rhe_shift(cfg)
        except (DataError, ValueError, TypeError) as exc:
            if not issues:
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
