"""Pure background-condition views; persisted fields remain independent records."""
from __future__ import annotations

from copy import deepcopy
import math
import re

from background_ph import (activate_ph_links, finite_ph, resolved_configs as legacy_resolve,
                           same_ph)

INHERITED_FIELDS = ("potential_method", "pH", "temperature_C", "reference", "filling",
                    "ref_V_SHE", "reference_source", "reference_preset_C", "rhe_offset_V")
MODES = ("follow", "independent", "legacy_ph")
METHODS = ("理论换算", "实测 RHE 总偏移", "已是 RHE")
REFERENCE_FIELDS = ("reference", "filling", "ref_V_SHE", "reference_source", "reference_preset_C")
NUMERIC = {"pH", "temperature_C", "ref_V_SHE", "reference_preset_C", "rhe_offset_V"}
DERIVED = {"background_conditions", "background_ph_status", "background_ph_sources", "background_ph_detail"}


def default_background_conditions():
    return {"background_conditions_mode": "follow", "background_conditions_migration": {}}


def canonical_config(cfg):
    """Detach a stored record, or restore one from this module's effective view."""
    if not isinstance(cfg, dict):
        raise ValueError("文件配置必须是字典。")
    result = deepcopy(cfg)
    view = result.get("background_conditions")
    if view is not None:
        if not isinstance(view, dict) or not isinstance(view.get("independent"), dict) or not isinstance(view.get("independent_sources"), dict):
            raise ValueError("背景解析视图缺少独立记录或来源，不能作为持久化输入。")
        present = view.get("independent_present_fields", list(view["independent"]))
        for field in INHERITED_FIELDS:
            if field in present:
                result[field] = deepcopy(view["independent"].get(field))
            else:
                result.pop(field, None)
        if view.get("independent_sources_present", True):
            result["parameter_sources"] = deepcopy(view["independent_sources"])
        else:
            result.pop("parameter_sources", None)
    for field in DERIVED:
        result.pop(field, None)
    return result


def canonical_configs(configs):
    if not isinstance(configs, dict):
        raise ValueError("文件配置集合必须是字典。")
    if any(not isinstance(ident, str) or not ident for ident in configs):
        raise ValueError("文件标识必须是非空文字。")
    return {ident: canonical_config(cfg) for ident, cfg in configs.items()}


def _mode(cfg):
    mode = cfg.get("background_conditions_mode", "legacy_ph")
    if mode not in MODES:
        raise ValueError("背景实验条件策略无效。")
    return mode


def controlled_fields(cfg):
    """Write permissions, independent of whether a value is currently usable."""
    if cfg.get("role") not in (None, "背景") and "background_conditions" not in cfg:
        return set()
    record = canonical_config(cfg)
    mode = _mode(record)
    if mode == "follow":
        return set(INHERITED_FIELDS)
    if mode == "legacy_ph":
        old = record.get("background_ph_mode", "manual")
        if old == "follow" or old == "auto" and record.get("pH") is None:
            return {"pH"}
    return set()


def activate_links(configs, ids):
    """Only an explicit candidate binding can change legacy policy flags."""
    before = deepcopy(configs)
    legacy_ids = [ident for ident in set(ids) if ident in configs and _mode(configs[ident]) == "legacy_ph"]
    activate_ph_links(configs, legacy_ids)
    return configs != before


def _value(field, value):
    if value is None or isinstance(value, str) and value.strip() in ("", "未设置", "未记录"):
        return None, "missing"
    if field in NUMERIC:
        if isinstance(value, bool):
            return None, "invalid"
        try:
            value = float(value)
        except (TypeError, ValueError, OverflowError):
            return None, "invalid"
        if not math.isfinite(value) or field == "temperature_C" and value <= -273.15:
            return None, "invalid"
        return value, "known"
    if not isinstance(value, str) or field == "potential_method" and value not in METHODS:
        return None, "invalid"
    return value, "known"


def _equal(field, a, b):
    if field in NUMERIC:
        return math.isclose(float(a), float(b), rel_tol=0., abs_tol=1e-9)
    clean = lambda text: re.sub(r"\s+", " ", text.strip()).casefold()
    return clean(a) == clean(b)


def _source(ident, configs, names, field):
    cfg = configs[ident]
    value = cfg.get(field, "理论换算" if field == "potential_method" else None)
    return {"id": ident, "filename": names.get(ident, cfg.get("name", str(ident))), "value": deepcopy(value)}


def _consensus(field, entries, active, editable=False):
    normalized = [(source, *_value(field, source["value"])) for source in entries]
    known = [(source, value) for source, value, kind in normalized if kind == "known"]
    invalid = [source for source, _, kind in normalized if kind == "invalid"]
    conflicts = [source for source, value in known] if known and any(not _equal(field, known[0][1], value) for _, value in known[1:]) else []
    if invalid:
        status, value, detail = "invalid", None, "关联样品的数值或记录无效：" + "；".join(f"{s['filename']}：{s['value']}" for s in invalid)
    elif conflicts:
        status, value, detail = "conflict", None, "共享背景条件冲突：" + "；".join(f"{s['filename']}：{s['value']}" for s in conflicts)
    elif known:
        status, value, detail = "following", deepcopy(known[0][1]), "沿用关联样品实验条件（用户默认约定）。"
    else:
        status, value = ("waiting" if active else "not_required"), None
        detail = "等待关联样品填写。" if active else "当前换算方式不需要此条件。"
    return dict(status=status, value=value, active=bool(active), editable=editable,
                sources=deepcopy(entries), conflicts=deepcopy(conflicts), detail=detail)


def _active(field, method):
    if field == "potential_method":
        return True
    if field in ("pH", "temperature_C", *REFERENCE_FIELDS):
        return method == "理论换算"
    return field == "rhe_offset_V" and method == "实测 RHE 总偏移"


def _independent_states(record, ident, names):
    method = record.get("potential_method", "理论换算")
    states = {}
    for field in INHERITED_FIELDS:
        raw = record.get(field, "理论换算" if field == "potential_method" else None)
        value, kind = _value(field, raw)
        active = _active(field, method)
        required = field in ("potential_method", "pH", "temperature_C", "ref_V_SHE", "rhe_offset_V") and active
        status = ("not_required" if not active and field not in ("pH", "temperature_C") else
                  "invalid" if kind == "invalid" else
                  "waiting" if kind == "missing" and required else "independent")
        states[field] = dict(status=status, value=deepcopy(value), active=active, editable=True,
                             sources=[dict(id=ident, filename=names.get(ident, record.get("name", str(ident))), value=deepcopy(raw))],
                             conflicts=[], detail="背景自身缺少此条件。" if status == "waiting" else "背景独立记录。")
    return states


def _follow_states(ids, configs, names):
    entries = lambda field: [_source(ident, configs, names, field) for ident in ids]
    states = {"potential_method": _consensus("potential_method", entries("potential_method"), True)}
    method = states["potential_method"]["value"]
    for field in ("pH", "temperature_C"):
        states[field] = _consensus(field, entries(field), _active(field, method))
    theory_ids = [ident for ident in ids if configs[ident].get("potential_method", "理论换算") == "理论换算"]
    ref_entries = lambda field: [_source(ident, configs, names, field) for ident in theory_ids]
    for field in REFERENCE_FIELDS:
        if method == "理论换算" or states["potential_method"]["status"] == "conflict":
            states[field] = _consensus(field, ref_entries(field), method == "理论换算")
        else:
            states[field] = dict(status="not_required", value=None, active=False, editable=False,
                                 sources=[], conflicts=[], detail="当前方法不使用参比缓存。")
    # A provenance URL is not a physical-condition conflict.
    if states["reference_source"]["status"] == "conflict":
        states["reference_source"].update(status="following", conflicts=[], value=None,
                                          detail="采用代表参比方案的来源说明；其他来源保留在明细中。")
    complete = []
    for ident in theory_ids:
        cfg = configs[ident]
        if _value("ref_V_SHE", cfg.get("ref_V_SHE"))[1] == "known":
            score = sum(_value(field, cfg.get(field))[1] == "known" for field in REFERENCE_FIELDS)
            complete.append((-score, str(ident), ident))
    if method == "理论换算":
        if complete:
            representative = min(complete)[2]
            for field in REFERENCE_FIELDS:
                state = states[field]
                if state["status"] not in ("conflict", "invalid"):
                    value, kind = _value(field, configs[representative].get(field))
                    state.update(value=deepcopy(value), representative_source=representative,
                                 status="following" if kind == "known" else ("waiting" if field == "ref_V_SHE" else "not_required"),
                                 detail="整组取自同一相容参比方案；未记录的元数据保持未知。")
        else:
            for field in REFERENCE_FIELDS:
                state = states[field]
                if state["status"] not in ("conflict", "invalid"):
                    state.update(value=None, status="waiting", detail="等待同一个来源提供可用参比方案，不能跨来源拼装。")
    offset_ids = [ident for ident in ids if configs[ident].get("potential_method") == "实测 RHE 总偏移"]
    states["rhe_offset_V"] = _consensus("rhe_offset_V", [_source(ident, configs, names, "rhe_offset_V") for ident in offset_ids], method == "实测 RHE 总偏移")
    if method != "实测 RHE 总偏移" and states["potential_method"]["status"] != "conflict":
        states["rhe_offset_V"].update(status="not_required", value=None, sources=[], conflicts=[], detail="当前方法不使用实测偏移缓存。")
    return states


def resolved_configs(configs, names=None):
    """Resolve one global effective condition set per background, without writes."""
    records = canonical_configs(configs)
    names = names or {}
    if not isinstance(names, dict):
        raise ValueError("文件名称映射必须是字典。")
    result = deepcopy(records)
    inbound = {}
    for ident, sample in records.items():
        if sample.get("role") == "背景":
            continue
        for field in ("background_disk", "background_ring"):
            bgid = sample.get(field)
            if bgid is not None and not isinstance(bgid, str):
                raise ValueError("背景文件标识必须是文字或空值。")
            if bgid in records and bgid != ident:
                inbound.setdefault(bgid, set()).add(ident)
    legacy = legacy_resolve(records, names)
    for ident, record in records.items():
        if record.get("role") != "背景" and ident not in inbound:
            continue
        mode = _mode(record)
        if not isinstance(record.get("parameter_sources", {}), dict) or not isinstance(record.get("background_conditions_migration", {}), dict):
            raise ValueError("背景来源和迁移记录必须是字典。")
        ids = sorted(inbound.get(ident, ()))
        independent = {field: deepcopy(record.get(field)) for field in INHERITED_FIELDS}
        independent_sources = deepcopy(record.get("parameter_sources", {}))
        states = _follow_states(ids, records, names) if mode == "follow" else _independent_states(record, ident, names)
        legacy_view = legacy.get(ident, record)
        if mode == "legacy_ph":
            state = states["pH"]
            old_status = legacy_view.get("background_ph_status", "unbound")
            old_mode = legacy_view.get("background_ph_mode", record.get("background_ph_mode", "manual"))
            follows = old_mode == "follow" or record.get("background_ph_mode") == "auto" and record.get("pH") is None
            statuses = {"following": "following", "conflict": "conflict", "invalid": "invalid", "waiting": "waiting", "manual_missing": "waiting"}
            state.update(status=statuses.get(old_status, "waiting" if follows else "independent"),
                         value=finite_ph(legacy_view.get("pH")), editable=not follows,
                         sources=[dict(id=s["id"], filename=s["filename"], value=s["pH"]) for s in legacy_view.get("background_ph_sources", [])],
                         detail=legacy_view.get("background_ph_detail", "旧版 pH 兼容规则。"))
            if old_status == "conflict":
                state["conflicts"] = [deepcopy(source) for source in state["sources"] if finite_ph(source["value"]) is not None]
            for field in INHERITED_FIELDS:
                if field != "pH":
                    states[field]["editable"] = True
        if mode == "follow" and not ids:
            status, detail = "unbound", "尚未关联样品；不会使用独立缓存代替跟随值。"
        elif mode == "legacy_ph" and not ids and legacy_view.get("background_ph_status") == "unbound":
            status, detail = "unbound", legacy_view.get("background_ph_detail", "旧版 pH 规则尚未关联样品。")
        else:
            bad = [field for field, state in states.items() if state["status"] in ("invalid", "conflict")]
            required = [field for field, state in states.items() if state["status"] == "waiting" and state["active"] and field in ("potential_method", "pH", "temperature_C", "ref_V_SHE", "rhe_offset_V")]
            if bad:
                status = "invalid" if any(states[field]["status"] == "invalid" for field in bad) else "conflict"
                detail = "；".join(f"{field}：{states[field]['detail']}" for field in bad)
            elif required:
                status, detail = "waiting", "等待填写：" + "、".join(required)
            elif mode == "follow":
                status, detail = "following", "沿用关联样品实验条件（用户默认约定）。"
            elif mode == "legacy_ph" and states["pH"]["status"] == "following":
                status, detail = "following", "旧版仅 pH 跟随；其他条件使用原独立记录。"
            else:
                status, detail = "independent", "使用背景独立记录。"
        if mode == "follow":
            for state in states.values():
                state["editable"] = False
        effective = {field: deepcopy(state["value"]) for field, state in states.items()}
        effective_sources = {}
        for field, state in states.items():
            if not state["editable"]:
                if state["value"] is None:
                    # A missing derived value has no independent fallback, in
                    # provenance any more than in the effective numeric fields.
                    effective_sources[field] = ("沿用关联样品（用户默认约定）；当前方式不使用此字段，未采用背景独立缓存。"
                        if state["status"] == "not_required" else
                        "沿用关联样品（用户默认约定）；" + state["detail"])
                else:
                    chosen = state.get("representative_source")
                    origins = "、".join(source["filename"] for source in state["sources"] if source["value"] is not None and (chosen is None or source["id"] == chosen))
                    effective_sources[field] = "沿用关联样品（用户默认约定）" + (f"；来源：{origins}" if origins else "")
            elif field in independent_sources:
                effective_sources[field] = deepcopy(independent_sources[field])
        view = dict(mode=mode, legacy_ph_mode=record.get("background_ph_mode", "manual") if mode == "legacy_ph" else None,
                    status=status, effective=effective, independent=independent,
                    independent_sources=independent_sources,
                    independent_present_fields=[field for field in INHERITED_FIELDS if field in record],
                    independent_sources_present="parameter_sources" in record,
                    linked_samples=[dict(id=sid, filename=names.get(sid, records[sid].get("name", str(sid)))) for sid in ids],
                    field_states=states, effective_sources=effective_sources,
                    assumptions=["背景与关联样品采用相同电位表达（用户默认约定）。"] if mode == "follow" else [],
                    migration=deepcopy(record.get("background_conditions_migration", {})), detail=detail)
        result[ident].update(effective)
        result[ident]["parameter_sources"] = dict(independent_sources, **effective_sources)
        result[ident]["background_conditions"] = view
        # Compatibility aliases are views only; canonical_config removes them.
        if mode == "legacy_ph":
            for field in ("background_ph_status", "background_ph_sources", "background_ph_detail"):
                result[ident][field] = deepcopy(legacy_view.get(field))
        else:
            result[ident].update(background_ph_status=status,
                                 background_ph_sources=[dict(id=sid, filename=names.get(sid, records[sid].get("name", str(sid))), pH=records[sid].get("pH")) for sid in ids],
                                 background_ph_detail=detail)
    return result


def condition_error(cfg):
    view = cfg.get("background_conditions", {})
    if not isinstance(view, dict):
        raise ValueError("背景解析视图必须是字典。")
    if view.get("status") in ("conflict", "invalid"):
        return view.get("detail") or "背景实验条件冲突或无效。"
    return None
