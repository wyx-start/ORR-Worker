"""Progressive experimental-condition controls shared by the analysis pages."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import streamlit as st
import pandas as pd

from experiment_conditions import (apply_conditions, area_from_diameter, load_profiles,
    linked_backgrounds, missing_conditions, save_profile, snapshot_conditions,
    validate_conditions)
from orr_core import DataError
from ui_shared import (REFERENCE_PRESETS, apply_pending_settings, file_formatter,
                       get_draft_configs, get_draft_settings, has_draft,
                       stage_config_updates)

METHODS = ["理论换算", "实测 RHE 总偏移", "已是 RHE"]


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


def condition_updates(configs, targets, values, *, source="人工输入", overwrite=True,
                      background_ph_edit=False):
    """Build isolated candidate patches without committing or modifying inputs."""
    updates = {}
    for ident in targets:
        before = configs[ident]
        after = copy.deepcopy(before)
        apply_conditions(after, values, source=source, overwrite=overwrite,
                         background_ph_edit=background_ph_edit)
        patch = {field:copy.deepcopy(value) for field,value in after.items()
                 if field not in before or before[field] != value}
        if patch:
            updates[ident] = patch
    return updates


def _fingerprint(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def _profiles(cfg, source_id, targets, prefix, editor_context):
    with st.expander("常用条件：保存与复用"):
        local, error = load_profiles()
        if error:
            st.warning(error)
        project = st.session_state.settings.setdefault("presets", {})
        options = {f"本机 · {name}":(values, f"本机预设：{name}") for name,values in local.items()}
        options.update({f"项目 · {name}":(values, f"项目预设：{name}") for name,values in project.items()})
        if options:
            picked = st.selectbox("选择常用条件", list(options), key=prefix+"profile")
            overwrite = st.checkbox("覆盖所选文件已有的非空条件", value=False, key=prefix+"overwrite")
            st.caption(f"应用到上方明确选择的 {len(targets)} 个文件；默认只补空白和软件初始默认。不会继承新文件的核对状态。")
            with st.expander("查看所选预设的内容"):
                st.json(options[picked][0])
            if st.button("载入预设到草稿", disabled=not targets, key=prefix+"apply_profile"):
                values, source = options[picked]
                try:
                    seed = copy.deepcopy(cfg)
                    apply_conditions(seed, values, source=source, overwrite=overwrite,
                                     background_ph_edit=cfg.get("role") == "背景")
                    updates = condition_updates(get_draft_configs(), targets, values,
                        source=source, overwrite=overwrite,
                        background_ph_edit=cfg.get("role") == "背景")
                    if not stage_config_updates(f"conditions:{source_id}", updates):
                        raise DataError(st.session_state.get("draft_error", "预设未能加入草稿。"))
                    # The candidate is now authoritative. A fresh input view
                    # prevents retained widget values from undoing this load.
                    # Keep the loaded template visible even if the reading
                    # source is deliberately excluded from the target set.
                    st.session_state.setdefault("condition_editor_views", {})[editor_context] = {
                        "epoch":0, "seed":seed}
                    st.session_state["condition_editor_epoch"] = st.session_state.get("condition_editor_epoch", 0)+1
                    st.session_state.conditions_notice = "预设已载入草稿；点击统一“应用设置”后生效。"
                    st.rerun()
                except (DataError, TypeError, ValueError) as exc:
                    st.error(str(exc))
        else:
            st.caption("尚无常用条件。完成配置并应用后，可保存到当前项目或本机供下一批选用。")
        name = st.text_input("配置名称（选填）", value="常用条件", key=prefix+"profile_name")
        location = st.selectbox("预设保存位置", ["当前项目", "本机"],
            key=prefix+"location", persist_state="session")
        pending = has_draft()
        st.caption("保存读取来源文件的整套可复用条件；有草稿时先统一校验并应用。同名保存会更新该预设，不保存身份、转速、背景或核对状态。")
        if st.button("应用并保存预设" if pending else "保存预设", key=prefix+"save"):
            try:
                if pending and not apply_pending_settings():
                    raise DataError("设置未能应用，预设尚未保存。请修正草稿后重试。")
                applied_cfg = st.session_state.configs[source_id]
                values = validate_conditions(snapshot_conditions(applied_cfg))
                if location == "当前项目":
                    st.session_state.settings.setdefault("presets", {})[name.strip() or "常用条件"] = values
                    st.session_state.exports.pop("parameters.json", None)
                    st.session_state.conditions_notice = "已保存到当前项目；下载项目后可继续使用。"
                else:
                    save_profile(name, applied_cfg)
                    st.session_state.conditions_notice = "已保存到本机；重启后可选用，不会自动覆盖下一批文件。"
                st.rerun()
            except (DataError, TypeError, ValueError) as exc:
                st.error(str(exc))


def common_parameter_form(purpose="curves", ids=None, density=False, expanded=False, channels="all", subtract_background=True):
    """Read candidates into a scoped view; explicit changes enter shared draft."""
    allowed_ids = list(st.session_state.traces)
    candidates = get_draft_configs()
    ids = [i for i in ids if i in candidates] if ids is not None else [i for i in allowed_ids if candidates[i].get("role") != "背景"]
    if not ids:
        ids = allowed_ids
    if not ids:
        return
    applied_axis = st.session_state.settings.get("axis", "RHE")
    axis = get_draft_settings().get("axis", "RHE")
    def relevant_backgrounds(config):
        if not subtract_background:
            return []
        if channels in ("ring", "disk"):
            bgid = config.get("background_"+channels)
            return [bgid] if bgid in candidates else []
        return linked_backgrounds(config, candidates)
    st.subheader("当前实验条件")
    notice = st.session_state.pop("conditions_notice", None)
    if notice:
        st.success(notice)
    st.caption("标记 `*` 的项目为当前操作必填；默认值或预设已填入的项目可直接使用。自动识别及默认值仍请按实际实验核对。")
    rows, has_potential_issue = [], False
    for ident in ids:
        cfg = candidates[ident]
        applied_cfg = st.session_state.configs[ident]
        issues = missing_conditions(cfg, purpose, axis, density)
        has_potential_issue |= bool(missing_conditions(cfg, "curves", axis))
        background_details = []
        for bgid in relevant_backgrounds(cfg):
            bgcfg = candidates[bgid]
            background_details.append(f"{st.session_state.traces[bgid].name}：{bgcfg.get('background_ph_detail', 'pH 独立设置')}")
            bg_issues = missing_conditions(bgcfg, "curves", axis)
            if bg_issues:
                has_potential_issue = True
                issues.append(f"背景“{st.session_state.traces[bgid].name}”：" + "；".join(bg_issues))
        rows.append({"文件":st.session_state.traces[ident].name,
                     "已应用条件":_source_summary(applied_cfg, purpose, density, applied_axis),
                     "待应用修改":_source_summary(cfg, purpose, density, axis) if cfg != applied_cfg or axis != applied_axis else "无",
                     "背景 pH":"；".join(background_details) or "未关联背景",
                     "当前待完成":"；".join(issues) if issues else "本页基础参数齐备"})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    if has_potential_issue and axis == "RHE":
        st.info("RHE 换算条件未齐。可展开下方修改条件，或在侧栏将电位坐标改为“原始”后应用设置。")
    with st.expander("修改实验条件", expanded=expanded, key=f"condition_editor_{purpose}", on_change="rerun"):
        source_options = list(dict.fromkeys(ids + [i for i in allowed_ids if candidates[i].get("role") == "背景"]))
        source = st.selectbox("读取设置的文件", source_options, format_func=file_formatter(),
            key=f"condition_source_{purpose}", persist_state="session")
        cfg = candidates[source]
        is_background = cfg.get("role") == "背景"
        group = cfg.get("group")
        scope_prefix = f"condition_scope_{purpose}_{source}_{st.session_state.revision}_"
        scope = st.segmented_control("应用范围", ["仅此文件", "当前组", "自选"],
            default="当前组", key=scope_prefix+"scope", persist_state="session")
        if scope == "自选":
            targets = st.multiselect("应用到文件", allowed_ids,
                default=[i for i in ids if candidates[i].get("group") == group] or [source],
                format_func=file_formatter(), key=scope_prefix+"custom", persist_state="session")
        elif scope == "仅此文件":
            targets = [source]
        else:
            targets = [i for i in ids if candidates[i].get("group") == group] if source in ids else [source]
        st.caption(f"读取来源只用于显示。本次修改将把当前显示的整套条件复制到明确范围：{len(targets)} 个文件；切换来源或范围本身不复制条件。")
        with st.expander("查看应用范围"):
            st.write([st.session_state.traces[i].name for i in targets])
        background_ids = list(dict.fromkeys(bgid for ident in targets
            for bgid in relevant_backgrounds(candidates[ident]) if bgid not in targets))
        if background_ids:
            names = "、".join(st.session_state.traces[i].name for i in background_ids)
            st.info(f"关联背景：{names}。背景 pH 按其模式联动或独立保存；其他条件需要一致时，请在“自选”范围中明确加入背景。背景 pH 模式在“扫描与背景”中修改。")
        context = _fingerprint([purpose, source, targets, st.session_state.revision,
                                axis, density, st.session_state.get("draft_epoch", 0)])
        views = st.session_state.setdefault("condition_editor_views", {})
        state = views.setdefault(context, {"epoch":0})
        source_fingerprint = _fingerprint(snapshot_conditions(cfg))
        if state.get("source_fingerprint") not in (None, source_fingerprint):
            state["epoch"] += 1
            state.pop("values", None)
            state.pop("seed", None)
        state["source_fingerprint"] = source_fingerprint
        cfg = state.get("seed", cfg)
        prefix = f"conditions_{context}_{state['epoch']}_{st.session_state.get('condition_editor_epoch',0)}_"
        draft_notice = st.empty()
        values = {}
        if axis == "RHE":
            method = st.selectbox("原始电位的换算方式 *", METHODS,
                index=METHODS.index(cfg.get("potential_method", "理论换算")), key=prefix+"method", persist_state="session")
            values["potential_method"] = method
            if method == "理论换算":
                values["pH"] = st.number_input("pH *", value=_number_value(cfg, "pH"), step=.1,
                    format="%.3f", key=prefix+"ph", persist_state="session")
                values["temperature_C"] = st.number_input("温度 / °C *", value=_number_value(cfg, "temperature_C", lower=-20., upper=150., default=25.),
                    min_value=-20., max_value=150., step=1., key=prefix+"temperature", persist_state="session")
                st.caption("默认温度 25 °C；pH 不从不明确的文件名猜测。")
                options = ["请选择参比", *REFERENCE_PRESETS]
                saved_preset = "自定义 / 实测标定" if cfg.get("ref_V_SHE") is not None else "请选择参比"
                for name, preset in REFERENCE_PRESETS.items():
                    if preset and cfg.get("reference_preset_C") == 25 and cfg.get("reference") == preset[0] and cfg.get("filling") == preset[1] and cfg.get("ref_V_SHE") == preset[2]:
                        saved_preset = name
                picked = st.selectbox("参比方案 *", options, index=options.index(saved_preset),
                    key=prefix+"reference_preset", persist_state="session")
                preset = REFERENCE_PRESETS.get(picked)
                if preset:
                    values.update(reference=preset[0], filling=preset[1], ref_V_SHE=preset[2],
                                  reference_source=preset[3], reference_preset_C=25.)
                    st.caption(f"{preset[0]} / {preset[1]} · E_ref vs SHE = {preset[2]:.3f} V · 仅限 25 °C · [文献来源]({preset[3]})；不是实测标定。")
                elif picked == "自定义 / 实测标定":
                    with st.expander("自定义参比参数", expanded=True):
                        values["reference"] = st.text_input("参比电极名称", value=cfg.get("reference", "未设置"), key=prefix+"reference", persist_state="session")
                        values["filling"] = st.text_input("参比内充液", value=cfg.get("filling", ""), key=prefix+"filling", persist_state="session")
                        values["ref_V_SHE"] = st.number_input("该温度下 E_ref vs SHE / V *", value=_number_value(cfg, "ref_V_SHE"),
                            format="%.5f", step=.001, key=prefix+"ref_v", persist_state="session")
                        values.update(reference_source="用户输入", reference_preset_C=None)
                else:
                    values.update(ref_V_SHE=None, reference="未设置", filling="", reference_preset_C=None, reference_source="未选择")
            elif method == "实测 RHE 总偏移":
                values["rhe_offset_V"] = st.number_input("实测 RHE 总偏移 / V *", value=_number_value(cfg, "rhe_offset_V"),
                    format="%.5f", step=.001, key=prefix+"offset", persist_state="session")
                st.caption("总偏移直接加到原始电位，不再叠加 pH。0 V 是有效输入。")
            else:
                st.caption("按用户选择将原始电位视为 RHE，不再平移，不要求 pH 或参比。")
        else:
            st.caption("当前使用原始电位，绘图不要求填写 pH、参比换算值或 RHE 总偏移。")
        if (purpose == "kl" or density) and not is_background:
            values.update(_area_controls(cfg, prefix))
        if purpose == "rrde" and not is_background:
            values["collection_efficiency"] = st.number_input("RRDE 收集效率 N（0–1） *", value=_number_value(cfg, "collection_efficiency", lower=.000001, upper=1.),
                min_value=.000001, max_value=1., step=.01, format="%.5f", key=prefix+"N", persist_state="session")
            st.caption(f"通道建议：盘 {cfg.get('disk_channel', 0) + 1} / 环 {cfg.get('ring_channel') + 1 if cfg.get('ring_channel') is not None else '未设置'}；请在“扫描与背景”中核对或修改。N 不设通用校准值。")
        with st.expander("补充实验记录（选填）"):
            electrolyte = st.text_input("电解液、浓度与气氛", value=cfg.get("electrolyte", ""),
                placeholder="例如 O₂ 饱和 0.1 M NaOH", key=prefix+"electrolyte", persist_state="session")
            # Apply the displayed source condition to every explicitly selected
            # target, even when the source text itself was not edited.
            values["electrolyte"] = electrolyte
            st.json({"参数来源":cfg.get("parameter_sources", {}), "当前盘面积_cm2":cfg.get("area_cm2")})
        previous_values = state.get("values")
        copy_requested = st.button("复制当前条件到所选范围", disabled=not targets,
                                   key=prefix+"copy_scope")
        st.caption("复制仅加入本批草稿，不立即生效；下方统一应用设置。")
        if copy_requested or previous_values is not None and values != previous_values:
            try:
                updates = condition_updates(candidates, targets, values,
                    background_ph_edit=is_background)
            except (DataError, ValueError, TypeError) as exc:
                st.session_state.setdefault("draft_errors", {})[f"conditions:{source}"] = str(exc)
                st.session_state["draft_error"] = str(exc)
                draft_notice.error(str(exc))
            else:
                accepted = stage_config_updates(f"conditions:{source}", updates)
                if accepted and updates:
                    updated_source = get_draft_configs()[source]
                    state["source_fingerprint"] = _fingerprint(snapshot_conditions(updated_source))
        state["values"] = copy.deepcopy(values)
        if has_draft():
            draft_notice.warning("有未应用修改：已加入本批草稿。下方统一应用，或使用“应用并计算／导出”；当前结果仍对应已应用设置。")
        _profiles(get_draft_configs()[source], source, targets,
                  f"profiles_{purpose}_{source}_", context)
