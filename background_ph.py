"""Resolve background pH from committed sample configurations, without UI state."""
from __future__ import annotations

import copy
import math

PH_TOLERANCE = 1e-9
MODES = ("auto", "follow", "manual")


def default_ph_link():
    return dict(background_ph_mode="auto", background_ph_status="unbound",
                background_ph_sources=[], background_ph_detail="尚未关联样品",
                background_ph_legacy=False)


def finite_ph(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def same_ph(left, right):
    left, right = finite_ph(left), finite_ph(right)
    return left is not None and right is not None and math.isclose(left, right, rel_tol=0., abs_tol=PH_TOLERANCE)


def activate_ph_links(configs, background_ids):
    """Called only when a user commits background selection, never for candidates."""
    for ident in set(background_ids):
        if ident not in configs:
            continue
        cfg = configs[ident]
        mode = cfg.get("background_ph_mode", "manual")
        if mode == "auto" or (cfg.get("background_ph_legacy") and cfg.get("pH") is None):
            cfg["background_ph_mode"] = "follow" if cfg.get("pH") is None else "manual"
        cfg["background_ph_legacy"] = False


def resolved_configs(configs, names=None):
    """Return a fresh snapshot; one background has one effective pH globally."""
    names = names or {}
    result = copy.deepcopy(configs)
    inbound = {}
    for sample_id, sample in configs.items():
        if sample.get("role") == "背景":
            continue
        for field in ("background_disk", "background_ring"):
            ident = sample.get(field)
            if ident in configs and ident != sample_id:
                inbound.setdefault(ident, set()).add(sample_id)
    for ident, cfg in result.items():
        if cfg.get("role") != "背景" and ident not in inbound:
            continue
        sources = [dict(id=sid, filename=names.get(sid, configs[sid].get("name", sid)),
                        pH=finite_ph(configs[sid].get("pH"))) for sid in sorted(inbound.get(ident, ())) ]
        cfg["background_ph_sources"] = sources
        mode = cfg.get("background_ph_mode", "manual")
        if mode not in MODES:
            cfg.update(background_ph_status="invalid", background_ph_detail="背景 pH 模式无效，请重新设置。")
            continue
        if mode == "auto" and sources:
            mode = "follow" if cfg.get("pH") is None else "manual"
            cfg["background_ph_mode"] = mode
        known = [s for s in sources if s["pH"] is not None]
        values = [s["pH"] for s in known]
        description = "；".join(f"{s['filename']}：{s['pH']:g}" for s in known)
        if mode == "follow":
            cfg.setdefault("parameter_sources", {})["pH"] = "沿用关联样品 pH（用户默认约定）"
            if not sources:
                cfg.update(pH=None, background_ph_status="unbound", background_ph_detail="已解除关联，自动 pH 已清理。")
            elif not values:
                cfg.update(pH=None, background_ph_status="waiting", background_ph_detail="等待关联样品填写并应用 pH。")
            elif max(values) - min(values) > PH_TOLERANCE:
                cfg.update(pH=None, background_ph_status="conflict",
                           background_ph_detail=f"共享背景 pH 冲突：{description}。请核对样品条件或更换适用背景。")
            else:
                cfg.update(pH=min(values), background_ph_status="following",
                           background_ph_detail=f"沿用关联样品 pH {min(values):g}（{len(sources)} 个文件）；{description}。")
        elif mode == "manual":
            value = finite_ph(cfg.get("pH"))
            if value is None:
                cfg.update(background_ph_status="manual_missing", background_ph_detail="背景独立 pH 未填写或无效；可填写，或主动改为跟随样品。")
            elif any(not same_ph(value, v) for v in values):
                cfg.update(background_ph_status="manual_difference",
                           background_ph_detail=f"背景独立 pH {value:g} 与关联样品不同：{description}。请核对；原值已保留。")
            else:
                cfg.update(background_ph_status="manual", background_ph_detail=f"独立填写背景 pH {value:g}，不随样品自动更新。")
        else:
            cfg.update(background_ph_status="unbound", background_ph_detail="尚未关联样品")
    return result


def synchronize_ph_links(configs, names=None):
    snapshot = resolved_configs(configs, names)
    changed = False
    for ident, values in snapshot.items():
        if configs[ident] != values:
            configs[ident].clear()
            configs[ident].update(values)
            changed = True
    return changed


def ph_link_error(cfg):
    if cfg.get("background_ph_status") in ("conflict", "invalid"):
        return cfg.get("background_ph_detail") or "背景 pH 联动状态无效。"
    return None
