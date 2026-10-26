"""Progressive experimental-condition controls shared by the analysis pages."""
from __future__ import annotations

import copy
from application.editing import _missing, _same_condition_value, condition_updates
import hashlib
import json
import math
import re
import streamlit as st
import pandas as pd

from background_conditions import INHERITED_FIELDS, NUMERIC, controlled_fields
from experiment_conditions import (apply_conditions, area_from_diameter,
    linked_backgrounds, missing_conditions)
from orr_core import DataError
from settings_editor import effective_independent_values, stage_background_mode
from ui_shared import (REFERENCE_PRESETS, apply_pending_settings, file_formatter,
                       get_draft_view, get_edit_configs, has_draft,
                       reject_config_updates, stage_config_updates)

METHODS = ["理论换算", "实测 RHE 总偏移", "已是 RHE"]

# Fields the editor can display; external changes to any of them re-seed widgets.
WATCH_FIELDS = ("potential_method", "pH", "temperature_C", "reference", "filling",
                "ref_V_SHE", "reference_source", "reference_preset_C", "rhe_offset_V",
                "electrolyte", "area_cm2", "disk_diameter_mm", "area_mode",
                "collection_efficiency")

MODE_LABELS = {"follow": "整组跟随关联样品", "independent": "独立设置", "legacy_ph": "旧版 pH 兼容"}
STATUS_LABELS = {"following": "跟随中", "independent": "独立", "waiting": "等待关联样品",
                 "conflict": "条件冲突", "invalid": "记录无效", "unbound": "尚未关联"}


def _number_value(cfg, field, lower=None, upper=None, default=None):
    value = cfg.get(field, default)
    if value is None:
        return None
    try:
        number = float(value)
        if not math.isfinite(number) or (lower is not None and number < lower) or (upper is not None and number > upper):
            raise ValueError
        return number
    except (TypeError, ValueError):
        st.warning(f"已保存的 {field} 数值无效，请重新填写；应用前不会改写原配置。")
        return None


def _source_summary(cfg, purpose, density, axis="RHE"):
    method = cfg.get("potential_method", "理论换算")
    if axis == "原始":
        text = "原始电位（不换算）" if method != "已是 RHE" else "原始数据已是 RHE"
    elif method == "理论换算":
        text = f"理论 RHE · pH {cfg.get('pH') if cfg.get('pH') is not None else '待填'} · {cfg.get('reference', '未设置')} · {cfg.get('temperature_C', '待填')} °C"
    elif method == "实测 RHE 总偏移":
        text = f"实测 RHE 总偏移：{cfg.get('rhe_offset_V') if cfg.get('rhe_offset_V') is not None else '待填'} V"
    else:
        text = "原始电位已是 RHE"
    if purpose == "kl" or density:
        area = cfg.get("area_cm2")
        area_text = f"{area:.6g}" if isinstance(area, (int, float)) else (str(area) if area is not None else "待填")
        text += f" · 盘面积 {area_text} cm²"
    if purpose == "rrde":
        text += f" · N = {cfg.get('collection_efficiency') if cfg.get('collection_efficiency') is not None else '待填'}"
    return text


def _background_condition_summary(name, bgcfg, axis):
    """One method-aware line from the resolved background view."""
    info = bgcfg.get("background_conditions") or {}
    status, mode = info.get("status"), info.get("mode")
    detail = info.get("detail") or ""
    if status == "following":
        head = "旧版 pH 跟随" if mode == "legacy_ph" else "整组跟随样品"
        return f"{name}：{head} · {_source_summary(bgcfg, 'curves', False, axis)}"
    if status == "independent":
        head = "旧版 pH 独立" if mode == "legacy_ph" else "独立记录"
        return f"{name}：{head} · {_source_summary(bgcfg, 'curves', False, axis)}"
    if status == "waiting":
        return f"{name}：等待关联样品（{detail}）"
    if status == "unbound":
        return f"{name}：尚未关联样品"
    return f"{name}：{detail or '背景条件冲突或无效'}"


def _area_controls(cfg, prefix):
    options = ["按盘直径计算", "直接输入面积"]
    mode = st.selectbox("盘面积输入方式", options,
        index=0 if cfg.get("area_mode") == "diameter" else 1,
        key=prefix+"area_mode", persist_state="session")
    if mode == options[0]:
        diameter = st.number_input("盘直径 / mm *", value=_number_value(cfg, "disk_diameter_mm", lower=.000001),
            min_value=.000001, format="%.6f", step=.5, key=prefix+"diameter", persist_state="session")
        area = area_from_diameter(diameter) if diameter is not None else None
        if area is not None:
            st.caption(f"盘几何面积：{area:.8f} cm²（按未舍入值计算）。")
        values = dict(area_mode="diameter", disk_diameter_mm=diameter, area_cm2=area)
    else:
        area = st.number_input("盘几何面积 / cm² *", value=_number_value(cfg, "area_cm2", lower=.000001),
            min_value=.000001, format="%.8f", step=.01, key=prefix+"area", persist_state="session")
        values = dict(area_mode="area", disk_diameter_mm=None, area_cm2=area)
    st.caption("新文件默认：5 mm RDE，约 0.19635 cm²。可按实际电极修改；面积不代表收集效率 N。")
    return values








def _fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _display_config(edit_cfg, resolved_cfg):
    """Editor seed: unresolved edit record, with locked fields showing effective values."""
    info = resolved_cfg.get("background_conditions") or {}
    states = info.get("field_states") or {}
    if not states:
        return edit_cfg, states
    display = dict(edit_cfg)
    sources = dict(display.get("parameter_sources") or {})
    effective_sources = resolved_cfg.get("parameter_sources") or {}
    for field, state in states.items():
        if not state.get("editable", True):
            display[field] = resolved_cfg.get(field)
            if field in effective_sources:
                sources[field] = effective_sources[field]
    if sources:
        display["parameter_sources"] = sources
    return display, states


def common_parameter_form(purpose="curves", ids=None, density=False, expanded=False, channels="all", subtract_background=True):
    """Read the shared draft view; explicit changes enter the shared draft."""
    view = get_draft_view()
    records, configs = view["records"], view["configs"]
    names = {ident: trace.name for ident, trace in st.session_state.traces.items()}
    allowed_ids = list(st.session_state.traces)
    ids = [i for i in ids if i in records] if ids is not None else [i for i in allowed_ids if records[i].get("role") != "背景"]
    if not ids:
        ids = allowed_ids
    if not ids:
        return
    applied_axis = st.session_state.settings.get("axis", "RHE")
    axis = view["settings"].get("axis", "RHE")
    def relevant_backgrounds(config):
        if not subtract_background:
            return []
        if channels in ("ring", "disk"):
            bgid = config.get("background_"+channels)
            return [bgid] if bgid in records else []
        return linked_backgrounds(config, records)
    st.subheader("当前实验条件")
    notice = st.session_state.pop("conditions_notice", None)
    if notice:
        st.success(notice)
    st.caption("标记 `*` 的项目为当前操作必填；已填入的默认值可直接使用。自动识别及默认值仍请按实际实验核对。")
    if view["view_basis"] == "applied_fallback":
        st.caption("草稿待修正；下方条件基于已应用设置。")
    rows, has_potential_issue = [], False
    for ident in ids:
        cfg = configs[ident]
        record = records[ident]
        applied_record = st.session_state.configs[ident]
        issues = missing_conditions(cfg, purpose, axis, density)
        has_potential_issue |= bool(missing_conditions(cfg, "curves", axis))
        background_details = []
        for bgid in relevant_backgrounds(record):
            bgcfg = configs[bgid]
            background_details.append(_background_condition_summary(st.session_state.traces[bgid].name, bgcfg, axis))
            bg_issues = missing_conditions(bgcfg, "curves", axis)
            if bg_issues:
                has_potential_issue = True
                issues.append(f"背景“{st.session_state.traces[bgid].name}”：" + "；".join(bg_issues))
        rows.append({"文件":st.session_state.traces[ident].name,
                     "已应用条件":_source_summary(applied_record, purpose, density, applied_axis),
                     "待应用修改":_source_summary(cfg, purpose, density, axis) if record != applied_record or axis != applied_axis else "无",
                     "背景条件":"；".join(background_details) or "未关联背景",
                     "当前待完成":"；".join(issues) if issues else "本页基础参数齐备"})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    if has_potential_issue and axis == "RHE":
        st.info("RHE 换算条件未齐。可展开下方修改条件，或在侧栏将电位坐标改为“原始”后应用设置。")
    with st.expander("修改实验条件", expanded=expanded, key=f"condition_editor_{purpose}", on_change="rerun"):
        source_options = list(dict.fromkeys(ids + [i for i in allowed_ids if records[i].get("role") == "背景"]))
        source = st.selectbox("读取设置的文件", source_options, format_func=file_formatter(),
            key=f"condition_source_{purpose}", persist_state="session")
        record = records[source]
        resolved = configs[source]
        is_background = record.get("role") == "背景"
        group = record.get("group")
        scope_prefix = f"condition_scope_{purpose}_{source}_{st.session_state.revision}_"
        scope = st.segmented_control("应用范围", ["仅此文件", "当前组", "自选"],
            default="当前组", key=scope_prefix+"scope", persist_state="session")
        if scope == "自选":
            targets = st.multiselect("应用到文件", allowed_ids,
                default=[i for i in ids if records[i].get("group") == group] or [source],
                format_func=file_formatter(), key=scope_prefix+"custom", persist_state="session")
        elif scope == "仅此文件":
            targets = [source]
        else:
            targets = [i for i in ids if records[i].get("group") == group] if source in ids else [source]
        st.caption(f"读取来源只用于显示。本次修改将把当前显示的整套条件复制到明确范围：{len(targets)} 个文件；切换来源或范围本身不复制条件。")
        with st.expander("查看应用范围"):
            st.write([st.session_state.traces[i].name for i in targets])
        background_ids = list(dict.fromkeys(bgid for ident in targets
            for bgid in relevant_backgrounds(records[ident]) if bgid not in targets))
        if background_ids:
            background_names = "、".join(st.session_state.traces[i].name for i in background_ids)
            st.info(f"关联背景：{background_names}。背景实验条件默认整组跟随关联样品；需要独立设置时，请在下方或在“扫描与背景”的背景面板中明确切换。")
        domain = f"conditions:{source}"
        display, states = _display_config(get_edit_configs(domain)[source], resolved)

        def locked(field):
            return not states.get(field, {}).get("editable", True)

        if is_background and states:
            info = resolved["background_conditions"]
            st.caption(f"背景条件模式：{MODE_LABELS.get(info.get('mode'), info.get('mode'))} · "
                       f"状态：{STATUS_LABELS.get(info.get('status'), info.get('status'))}。"
                       f"{info.get('detail') or ''}")
            st.caption("跟随中的字段只读并显示有效值；明确切到独立设置后才可直接修改。")
            if st.button("切到独立设置", key=scope_prefix+"to_independent",
                         disabled=info.get("mode") == "independent",
                         help="保留既有独立记录；之后的背景条件修改独立于关联样品。"):
                stage_background_mode(source, "independent", domain=domain)
                st.rerun()
            if info.get("mode") == "follow":
                usable = view["view_basis"] in ("applied", "candidate") and info.get("status") == "following"
                if st.button("用当前有效条件建立独立记录", key=scope_prefix+"adopt", disabled=not usable,
                             help="仅复制当前换算方式实际使用的已知有效字段；未启用方式的历史缓存保持不变。"):
                    stage_background_mode(source, "independent", domain=domain,
                                          values=effective_independent_values(info))
                    st.rerun()
                if not usable:
                    st.caption("等待、冲突或未绑定时没有一套完整有效条件可复制；请先补齐或统一关联样品条件。")
            if info.get("mode") == "independent":
                if st.button("改为跟随关联样品", key=scope_prefix+"to_follow",
                             help="恢复整组跟随；独立记录原样保留，未应用的独立输入不混入跟随提交。"):
                    stage_background_mode(source, "follow", domain=domain)
                    st.rerun()
            if info.get("mode") == "legacy_ph":
                st.caption("旧版记录：仅 pH 联动可在“扫描与背景”管理；升级后整组条件按新策略生效。")
                if st.button("升级为整组跟随（推荐）", key=scope_prefix+"upgrade_follow"):
                    stage_background_mode(source, "follow", domain=domain)
                    st.rerun()
        context = _fingerprint([purpose, source, targets, st.session_state.revision,
                                axis, density, st.session_state.get("draft_epoch", 0)])
        views = st.session_state.setdefault("condition_editor_views", {})
        state = views.setdefault(context, {"epoch":0})
        source_fingerprint = _fingerprint({field: display.get(field) for field in WATCH_FIELDS})
        if state.get("source_fingerprint") not in (None, source_fingerprint):
            state["epoch"] += 1
            state.pop("values", None)
            state.pop("seed", None)
        state["source_fingerprint"] = source_fingerprint
        display = state.get("seed", display)
        prefix = f"conditions_{context}_{state['epoch']}_{st.session_state.get('condition_editor_epoch',0)}_"
        draft_notice = st.empty()
        values = {}
        if axis == "RHE":
            method_value = display.get("potential_method", "理论换算")
            method = st.selectbox("原始电位的换算方式 *", METHODS,
                index=METHODS.index(method_value) if method_value in METHODS else 0,
                key=prefix+"method", persist_state="session", disabled=locked("potential_method"))
            if not locked("potential_method"):
                values["potential_method"] = method
            if method == "理论换算":
                if not locked("pH"):
                    values["pH"] = st.number_input("pH *", value=_number_value(display, "pH"), step=.1,
                        format="%.3f", key=prefix+"ph", persist_state="session")
                else:
                    st.number_input("pH *", value=_number_value(display, "pH"), step=.1,
                        format="%.3f", key=prefix+"ph", persist_state="session", disabled=True)
                if not locked("temperature_C"):
                    values["temperature_C"] = st.number_input("温度 / °C *", value=_number_value(display, "temperature_C", lower=-20., upper=150., default=25.),
                        min_value=-20., max_value=150., step=1., key=prefix+"temperature", persist_state="session")
                else:
                    st.number_input("温度 / °C *", value=_number_value(display, "temperature_C", lower=-20., upper=150., default=25.),
                        min_value=-20., max_value=150., step=1., key=prefix+"temperature", persist_state="session", disabled=True)
                st.caption("新文件默认 pH 13、25 °C、SCE（饱和 KCl）；请按实际实验修改，参比预设仅适用于 25 °C。")
                options = ["请选择参比", *REFERENCE_PRESETS]
                saved_preset = "自定义 / 实测标定" if display.get("ref_V_SHE") is not None else "请选择参比"
                for preset_name, preset in REFERENCE_PRESETS.items():
                    if preset and display.get("reference_preset_C") == 25 and display.get("reference") == preset[0] and display.get("filling") == preset[1] and display.get("ref_V_SHE") == preset[2]:
                        saved_preset = preset_name
                reference_locked = locked("ref_V_SHE")
                picked = st.selectbox("参比方案 *", options, index=options.index(saved_preset),
                    key=prefix+"reference_preset", persist_state="session", disabled=reference_locked)
                preset = REFERENCE_PRESETS.get(picked)
                if reference_locked:
                    if preset:
                        st.caption(f"{preset[0]} / {preset[1]} · E_ref vs SHE = {preset[2]:.3f} V · 仅限 25 °C · [文献来源]({preset[3]})；不是实测标定。")
                elif preset:
                    values.update(reference=preset[0], filling=preset[1], ref_V_SHE=preset[2],
                                  reference_source=preset[3], reference_preset_C=25.)
                    st.caption(f"{preset[0]} / {preset[1]} · E_ref vs SHE = {preset[2]:.3f} V · 仅限 25 °C · [文献来源]({preset[3]})；不是实测标定。")
                elif picked == "自定义 / 实测标定":
                    with st.expander("自定义参比参数", expanded=True):
                        values["reference"] = st.text_input("参比电极名称", value=display.get("reference", "未设置"), key=prefix+"reference", persist_state="session")
                        values["filling"] = st.text_input("参比内充液", value=display.get("filling", ""), key=prefix+"filling", persist_state="session")
                        values["ref_V_SHE"] = st.number_input("该温度下 E_ref vs SHE / V *", value=_number_value(display, "ref_V_SHE"),
                            format="%.5f", step=.001, key=prefix+"ref_v", persist_state="session")
                        values.update(reference_source="用户输入", reference_preset_C=None)
                else:
                    values.update(ref_V_SHE=None, reference="未设置", filling="", reference_preset_C=None, reference_source="未选择")
            elif method == "实测 RHE 总偏移":
                if not locked("rhe_offset_V"):
                    values["rhe_offset_V"] = st.number_input("实测 RHE 总偏移 / V *", value=_number_value(display, "rhe_offset_V"),
                        format="%.5f", step=.001, key=prefix+"offset", persist_state="session")
                else:
                    st.number_input("实测 RHE 总偏移 / V *", value=_number_value(display, "rhe_offset_V"),
                        format="%.5f", step=.001, key=prefix+"offset", persist_state="session", disabled=True)
                st.caption("总偏移直接加到原始电位，不再叠加 pH。0 V 是有效输入。")
            else:
                st.caption("按用户选择将原始电位视为 RHE，不再平移，不要求 pH 或参比。")
        else:
            st.caption("当前使用原始电位，绘图不要求填写 pH、参比换算值或 RHE 总偏移。")
        if (purpose == "kl" or density) and not is_background:
            values.update(_area_controls(display, prefix))
        if purpose == "rrde" and not is_background:
            n_seed = .369 if display.get("collection_efficiency") is None else _number_value(display, "collection_efficiency", lower=.000001, upper=1.)
            values["collection_efficiency"] = st.number_input("RRDE 收集效率 N（0–1） *", value=n_seed,
                min_value=.000001, max_value=1., step=.01, format="%.5f", key=prefix+"N", persist_state="session")
            st.caption("初始值 0.369，可按实际校准值修改。盘环通道可在“扫描与背景”中核对或修改。")
            if display.get("collection_efficiency") is None and values["collection_efficiency"] == .369:
                values["parameter_sources"] = {"collection_efficiency":"软件默认 0.369（可修改）"}
        copy_values = dict(values)
        for field in INHERITED_FIELDS:
            if locked(field) and field not in copy_values:
                copy_values[field] = display.get(field)
        previous_values = state.get("values")
        semantic = lambda v: {k:value for k,value in (v or {}).items() if k != "parameter_sources"}
        values_changed = previous_values is not None and semantic(values) != semantic(previous_values)
        n_changed = previous_values is not None and values.get("collection_efficiency") != previous_values.get("collection_efficiency")
        copy_requested = st.button("复制当前条件到所选范围", disabled=not targets,
                                   key=prefix+"copy_scope")
        st.caption("复制仅加入本批草稿，不立即生效；下方统一应用设置。")
        n_default_pending = (purpose == "rrde" and not is_background
                             and display.get("collection_efficiency") is None
                             and values.get("collection_efficiency") == .369)
        if copy_requested or n_default_pending or values_changed:
            intent = copy_values if copy_requested else values
            try:
                updates = {}
                default_only = n_default_pending and not copy_requested and not values_changed
                for target in targets:
                    target_intent = copy.deepcopy(intent)
                    if default_only:
                        target_intent = {"collection_efficiency":.369,
                                         "parameter_sources":{"collection_efficiency":"软件默认 0.369（可修改）"}}
                    if n_default_pending and records[target].get("collection_efficiency") is not None:
                        target_intent.pop("collection_efficiency", None)
                        target_intent.get("parameter_sources", {}).pop("collection_efficiency", None)
                    elif not copy_requested and not n_changed and not default_only:
                        target_intent.pop("collection_efficiency", None)
                        target_intent.get("parameter_sources", {}).pop("collection_efficiency", None)
                    updates.update(condition_updates(view, [target], target_intent, names=names,
                        source="软件默认 0.369（可修改）" if default_only else "人工输入",
                        background_ph_edit=is_background))
            except (DataError, ValueError, TypeError) as exc:
                reject_config_updates(domain, None, str(exc))
                draft_notice.error(str(exc))
            else:
                if stage_config_updates(domain, updates):
                    fresh_display, _ = _display_config(get_edit_configs(domain)[source],
                                                       get_draft_view()["configs"][source])
                    state["source_fingerprint"] = _fingerprint({field: fresh_display.get(field) for field in WATCH_FIELDS})
        state["values"] = copy.deepcopy(values)
        if has_draft():
            draft_notice.warning("有未应用修改：已加入本批草稿。下方统一应用，或使用“应用并计算／导出”；当前结果仍对应已应用设置。")
