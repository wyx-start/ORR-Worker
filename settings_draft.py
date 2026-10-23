"""Pure, atomic candidates for the application's explicitly applied settings.

Stages contain patches rather than replacement configurations.  A stage can be
edited repeatedly; independently named stages cannot disagree on a leaf field.
No function commits to the caller's configurations or checks task completeness.
"""
from __future__ import annotations

import copy
import math
from numbers import Integral, Real

from background_pairing import apply_background_binding
from background_ph import MODES as PH_MODES
from background_conditions import MODES, activate_links, canonical_configs, controlled_fields
from orr_core import DataError, default_config, migrate_background_config, scan_segments


class DraftConflictError(DataError):
    """A rejected domain may be retried when its conflicting peer is edited."""


def new_draft(base_revision):
    if isinstance(base_revision, bool) or not isinstance(base_revision, Integral) or base_revision < 0:
        raise DataError("草稿基础修订号必须是非负整数。")
    return {"base_revision": int(base_revision), "configs": {}, "settings": {}}


def _mapping(value, label):
    if not isinstance(value, dict):
        raise DataError(f"{label}必须是字典。")
    return value


def _name(value, label):
    if not isinstance(value, str) or not value.strip():
        raise DataError(f"{label}必须是非空文字。")


def _check_draft(draft):
    _mapping(draft, "草稿")
    new_draft(draft.get("base_revision"))
    for section in ("configs", "settings"):
        _mapping(draft.get(section), f"草稿 {section}")
        for domain, patch in draft[section].items():
            _name(domain, "编辑域")
            _mapping(patch, "修改内容")
            if section == "configs":
                for ident, values in patch.items():
                    _name(ident, "文件标识")
                    _mapping(values, "文件修改内容")


def _merge(target, patch):
    """Merge nested source records/settings without erasing unrelated leaves."""
    for key, value in patch.items():
        _name(key, "设置字段")
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _conflict(left, right, path=()):
    for key in left.keys() & right.keys():
        a, b = left[key], right[key]
        if isinstance(a, dict) and isinstance(b, dict):
            found = _conflict(a, b, (*path, key))
            if found:
                return found
        elif a != b:
            return ".".join((*path, key))
    return None


def _check_conflicts(draft):
    entries = list(draft["configs"].items())
    for index, (domain, files) in enumerate(entries):
        for other_domain, other_files in entries[index + 1:]:
            for ident in files.keys() & other_files.keys():
                field = _conflict(files[ident], other_files[ident])
                if field:
                    raise DraftConflictError(f"文件 {ident} 的 {field} 在“{domain}”与“{other_domain}”中有矛盾修改，请先统一。")
    entries = list(draft["settings"].items())
    for index, (domain, patch) in enumerate(entries):
        for other_domain, other_patch in entries[index + 1:]:
            field = _conflict(patch, other_patch)
            if field:
                raise DraftConflictError(f"全局 {field} 在“{domain}”与“{other_domain}”中有矛盾修改，请先统一。")


def stage_config(draft, domain, ident, updates):
    """Stage a file patch atomically; later edits in this domain replace leaves."""
    _check_draft(draft)
    _name(domain, "编辑域")
    _name(ident, "文件标识")
    _mapping(updates, "文件修改内容")
    staged = copy.deepcopy(draft)
    _merge(staged["configs"].setdefault(domain, {}).setdefault(ident, {}), updates)
    _check_conflicts(staged)
    draft.clear()
    draft.update(staged)
    return draft


def stage_settings(draft, domain, updates):
    """Stage global settings (including axis) under the same conflict rules."""
    _check_draft(draft)
    _name(domain, "编辑域")
    _mapping(updates, "全局修改内容")
    staged = copy.deepcopy(draft)
    _merge(staged["settings"].setdefault(domain, {}), updates)
    _check_conflicts(staged)
    draft.clear()
    draft.update(staged)
    return draft


def has_changes(draft):
    _check_draft(draft)
    return any(bool(patch) for files in draft["configs"].values() for patch in files.values()) or any(
        bool(patch) for patch in draft["settings"].values())


def _number(cfg, field, label, *, positive=False, nonnegative=False):
    value = cfg.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise DataError(f"{label}必须是有限数值或留空。")
    if positive and value <= 0 or nonnegative and value < 0:
        raise DataError(f"{label}必须{'大于零' if positive else '不小于零'}。")
    return float(value)


def _validate_config(ident, trace, cfg):
    _mapping(cfg, f"文件 {ident} 的配置")
    for key, choices in (("role", ("样品", "RRDE", "背景")),
                         ("mode", ("A", "B")), ("direction", ("递增", "递减")),
                         ("background_mode", ("paired", "independent")),
                         ("background_ph_mode", PH_MODES),
                         ("background_conditions_mode", MODES),
                         ("potential_method", ("理论换算", "实测 RHE 总偏移", "已是 RHE")),
                         ("area_mode", ("area", "diameter"))):
        if key in cfg and cfg[key] not in choices:
            raise DataError(f"“{trace.name}”的 {key} 无效。")
    count = len(trace.columns) - 1
    for key in ("disk_channel", "ring_channel"):
        channel = cfg.get(key, 0 if key == "disk_channel" else None)
        if key == "ring_channel" and channel is None:
            continue
        if isinstance(channel, bool) or not isinstance(channel, Integral) or not 0 <= channel < count:
            raise DataError(f"“{trace.name}”的{'盘' if key == 'disk_channel' else '环'}电流通道无效。")
    if cfg.get("ring_channel") is not None and cfg.get("ring_channel") == cfg.get("disk_channel", 0):
        raise DataError(f"“{trace.name}”的盘、环不能使用同一个通道。")
    for key in ("disk_sign", "ring_sign"):
        if key in cfg and (isinstance(cfg[key], bool) or cfg[key] not in (-1, 1)):
            raise DataError(f"“{trace.name}”的电流符号无效。")
    for key in ("ir_enabled", "ir_confirmed", "background_reviewed", "background_ph_legacy", "ring_detection_confirmed"):
        if key in cfg and not isinstance(cfg[key], bool):
            raise DataError(f"“{trace.name}”的 {key} 必须是明确的开关值。")
    _mapping(cfg.get("parameter_sources", {}), "参数来源")
    _mapping(cfg.get("background_conditions_migration", {}), "背景迁移记录")
    _number(cfg, "pH", "pH")
    temp = _number(cfg, "temperature_C", "温度")
    if temp is not None and temp <= -273.15:
        raise DataError("温度必须高于绝对零度。")
    for key in ("ref_V_SHE", "reference_preset_C", "rhe_offset_V", "ring_potential_V"):
        _number(cfg, key, key)
    area = _number(cfg, "area_cm2", "盘面积", positive=True)
    diameter = _number(cfg, "disk_diameter_mm", "盘直径", positive=True)
    if cfg.get("area_mode") == "diameter" and diameter is not None and area is not None:
        expected = math.pi * (diameter / 20.) ** 2
        if not math.isclose(area, expected, rel_tol=1e-10):
            raise DataError("盘直径与几何面积不一致，请一并修改。")
    efficiency = _number(cfg, "collection_efficiency", "RRDE 收集效率 N", positive=True)
    if efficiency is not None and efficiency > 1:
        raise DataError("收集效率 N 必须满足 0 < N ≤ 1。")
    _number(cfg, "rpm", "转速", nonnegative=True)
    _number(cfg, "ir_ohm", "未补偿电阻", nonnegative=True)
    manual = cfg.get("manual_segment")
    if manual is not None:
        if isinstance(manual, bool) or not isinstance(manual, Integral) or manual <= 0:
            raise DataError("人工扫描段必须是有效的段编号。")
        if manual not in {segment["segment"] for segment in scan_segments(trace)}:
            raise DataError(f"“{trace.name}”的手选扫描段不存在，请重新选择。")


def validate_config_patch(trace, cfg, patch):
    """Reject projections and writes to followed records, before any mutation.

    Incomplete numeric/scan records are validated by ``candidate`` so that an
    invalid draft remains available for repair. This guard covers persistence
    and ownership of fields, including metadata-only changes to followed values.
    """
    _mapping(patch, "文件修改内容")
    forbidden = {"background_conditions", "background_ph_status", "background_ph_sources",
                 "background_ph_detail"}
    unknown = set(patch) - set(default_config(trace))
    if forbidden.intersection(patch) or unknown:
        fields = sorted(forbidden.intersection(patch) | unknown)
        raise DataError(f"“{trace.name}”包含不可写入的派生或未知字段：{'、'.join(fields)}。请以持久化记录构建补丁。")
    updated = copy.deepcopy(cfg)
    _merge(updated, patch)
    blocked = controlled_fields(updated) if updated.get("role") == "背景" else set()
    writes = {field for field in blocked if field in patch and patch[field] != cfg.get(field)}
    source_patch = patch.get("parameter_sources", {})
    if not isinstance(source_patch, dict):
        raise DataError("参数来源必须是字典。")
    original_sources = cfg.get("parameter_sources", {})
    if not isinstance(original_sources, dict):
        raise DataError("原记录的参数来源必须是字典。")
    writes.update(field for field in blocked if field in source_patch
                  and source_patch[field] != original_sources.get(field))
    if writes:
        raise DataError(f"“{trace.name}”的 {'、'.join(sorted(writes))} 正在跟随关联样品；请明确切到独立设置后，在同一草稿中修改。")
    return updated


def _validate_background_graph(configs):
    visiting, done = set(), set()

    def visit(ident):
        if ident in visiting:
            raise DataError("背景关联形成循环，请解除循环引用。")
        if ident in done:
            return
        visiting.add(ident)
        cfg = configs[ident]
        for field in ("background_disk", "background_ring"):
            bgid = cfg.get(field)
            if bgid is None:
                continue
            if bgid == ident:
                raise DataError("背景不能选择文件自身。")
            if not isinstance(bgid, str) or bgid not in configs or configs[bgid].get("role") != "背景":
                raise DataError("背景文件不存在或用途不是背景。")
            visit(bgid)
        visiting.remove(ident)
        done.add(ident)

    for ident in configs:
        visit(ident)


def candidate(draft, traces, configs, settings, revision):
    """Return detached ``(configs, settings)`` or raise without any side effects.

    Missing task inputs, automatic-scan failure and shared-background pH conflicts
    remain valid saved records.  Task-specific preflight belongs to the caller.
    """
    _check_draft(draft)
    if draft["base_revision"] != revision:
        raise DataError("草稿基于旧修订，当前项目设置已改变；请核对或放弃草稿后重新编辑。")
    _mapping(traces, "原始数据")
    _mapping(configs, "已应用配置")
    _mapping(settings, "全局设置")
    if traces.keys() != configs.keys():
        raise DataError("文件与配置标识不一致，请重新载入项目。")
    _check_conflicts(draft)
    stored = canonical_configs(configs)
    stored = {ident: migrate_background_config(cfg, schema=1)
              if "background_conditions_mode" not in cfg else cfg for ident, cfg in stored.items()}
    proposed, global_settings = copy.deepcopy(stored), copy.deepcopy(settings)
    patches = {}
    for files in draft["configs"].values():
        for ident, patch in files.items():
            if ident not in proposed:
                raise DataError(f"草稿引用的文件 {ident} 已不存在。")
            _merge(patches.setdefault(ident, {}), patch)
            _merge(proposed[ident], patch)
    for patch in draft["settings"].values():
        _merge(global_settings, patch)
    if global_settings.get("axis", "RHE") not in ("RHE", "原始"):
        raise DataError("电位坐标必须是 RHE 或原始。")
    for ident, patch in patches.items():
        validate_config_patch(traces[ident], stored[ident], patch)
    for ident, cfg in proposed.items():
        _validate_config(ident, traces[ident], cfg)
    activated = []
    binding_fields = {"background_mode", "background_disk", "background_ring"}
    for ident, cfg in proposed.items():
        patch = patches.get(ident, {})
        mode = cfg.get("background_mode", "independent")
        if mode == "paired" and "background_ring" in patch and patch["background_ring"] != cfg.get("background_disk"):
            raise DataError("配对背景的盘、环必须选择同一个背景文件。")
        checked = copy.deepcopy(cfg)
        apply_background_binding(ident, checked, traces, proposed, mode,
                                 cfg.get("background_disk"), cfg.get("background_ring"))
        if binding_fields.intersection(patch):
            cfg.update({field: checked[field] for field in (*binding_fields, "background_reviewed")})
            activated.extend((cfg.get("background_disk"), cfg.get("background_ring")))
    _validate_background_graph(proposed)
    activate_links(proposed, activated)
    return proposed, global_settings
