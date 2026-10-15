"""Progressive experimental-condition controls shared by the analysis pages."""
from __future__ import annotations

import copy
import math
import streamlit as st
import pandas as pd

from experiment_conditions import (apply_conditions, area_from_diameter, load_profiles,
    linked_backgrounds, missing_conditions, save_profile, snapshot_conditions,
    unapplied_changes, validate_conditions)
from orr_core import DataError
from ui_shared import REFERENCE_PRESETS, background_ph_panel, file_formatter, invalidate

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


def _profiles(cfg, targets, prefix, pending=False):
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
            if st.button("套用常用条件", disabled=not targets, key=prefix+"apply_profile"):
                values, source = options[picked]
                try:
                    updated = copy.deepcopy(st.session_state.configs)
                    for ident in targets:
                        apply_conditions(updated[ident], values, source=source, overwrite=overwrite,
                                         background_ph_edit=cfg.get("role") == "背景")
                    st.session_state.configs = updated
                    invalidate()
                    st.rerun()
                except (DataError, TypeError, ValueError) as exc:
                    st.error(str(exc))
        else:
            st.caption("尚无常用条件。完成配置并应用后，可保存到当前项目或本机供下一批选用。")
        name = st.text_input("配置名称（选填）", value="常用条件", key=prefix+"profile_name")
        st.caption("保存的是当前文件已应用的参数；请先点击“应用实验参数”。同名保存会更新该预设。")
        with st.container(horizontal=True):
            if st.button("保存到当前项目", key=prefix+"save_project"):
                try:
                    if pending:
                        raise DataError("修改尚未应用：请先点击“应用实验参数”，再保存常用条件。")
                    values = validate_conditions(snapshot_conditions(cfg))
                    project[name.strip() or "常用条件"] = values
                    st.session_state.exports.pop("parameters.json", None)
                    st.success("已保存到当前项目；下载项目后可继续使用。")
                except (DataError, TypeError, ValueError) as exc:
                    st.error(str(exc))
            if st.button("设为本机常用条件", key=prefix+"save_local"):
                try:
                    if pending:
                        raise DataError("修改尚未应用：请先点击“应用实验参数”，再保存常用条件。")
                    save_profile(name, cfg)
                    st.success("已保存到本机；重启后可选用，不会自动覆盖下一批文件。")
                except (DataError, TypeError, ValueError) as exc:
                    st.error(str(exc))


def _include_background_targets(target_key, background_ids):
    st.session_state[target_key] = list(dict.fromkeys(list(st.session_state.get(target_key, [])) + background_ids))


def common_parameter_form(purpose="curves", ids=None, density=False, expanded=False):
    """Show only the inputs needed by this page; stage edits until Apply."""
    allowed_ids = list(st.session_state.traces)
    ids = list(ids) if ids is not None else [i for i in allowed_ids if st.session_state.configs[i].get("role") != "背景"]
    if not ids:
        ids = allowed_ids
    if not ids:
        return
    axis = st.session_state.settings.get("axis", "RHE")
    st.subheader("当前实验条件")
    notice = st.session_state.pop("conditions_notice", None)
    if notice:
        st.success(notice)
    st.caption("标记 `*` 的项目为当前操作必填；默认值或预设已填入的项目可直接使用。自动识别及默认值仍请按实际实验核对。")
    rows, has_potential_issue = [], False
    for ident in ids:
        cfg = st.session_state.configs[ident]
        issues = missing_conditions(cfg, purpose, axis, density)
        has_potential_issue |= bool(missing_conditions(cfg, "curves", axis))
        background_details = []
        for bgid in linked_backgrounds(cfg, st.session_state.configs):
            bgcfg = st.session_state.configs[bgid]
            background_details.append(f"{st.session_state.traces[bgid].name}：{bgcfg.get('background_ph_detail', 'pH 独立设置')}")
            bg_issues = missing_conditions(st.session_state.configs[bgid], "curves", axis)
            if bg_issues:
                has_potential_issue = True
                issues.append(f"背景“{st.session_state.traces[bgid].name}”：" + "；".join(bg_issues))
        rows.append({"文件":st.session_state.traces[ident].name,
                     "条件摘要":_source_summary(cfg, purpose, density, axis),
                     "背景 pH":"；".join(background_details) or "未关联背景",
                     "当前待完成":"；".join(issues) if issues else "本页基础参数齐备"})
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    if has_potential_issue and axis == "RHE":
        st.info("RHE 换算条件未齐。可展开下方修改条件，或先查看原始电位曲线。")
        if st.button("先查看原始电位曲线", key=f"raw_preview_{purpose}"):
            st.session_state.settings["axis"] = "原始"
            st.session_state.conditions_notice = "已切换为原始电位，当前不执行 RHE 换算。"
            invalidate()
            st.rerun()
    with st.expander("修改实验条件", expanded=expanded, key=f"condition_editor_{purpose}", on_change="rerun"):
        source_options = list(dict.fromkeys(ids + [i for i in allowed_ids if st.session_state.configs[i].get("role") == "背景"]))
        source = st.selectbox("读取设置的文件", source_options, format_func=file_formatter(),
            key=f"condition_source_{purpose}", persist_state="session")
        cfg = st.session_state.configs[source]
        is_background = cfg.get("role") == "背景"
        prefix = f"conditions_{source}_{st.session_state.revision}_"
        group = cfg.get("group")
        defaults = [i for i in ids if st.session_state.configs[i].get("group") == group]
        if source not in ids:
            defaults = [source]
        target_key = f"targets_{purpose}_{source}_{st.session_state.revision}"
        targets = st.multiselect("应用到文件（默认当前组，可加入背景或其他文件）", allowed_ids,
            default=defaults if target_key not in st.session_state else None,
            format_func=file_formatter(), key=target_key, persist_state="session")
        st.caption(f"本次应用范围：{len(targets)} 个文件。跨组和背景文件请在上方明确选入。")
        background_ids = list(dict.fromkeys(bgid for ident in targets
            for bgid in linked_backgrounds(st.session_state.configs[ident], st.session_state.configs) if bgid not in targets))
        if background_ids:
            names = "、".join(st.session_state.traces[i].name for i in background_ids)
            st.info(f"关联背景：{names}。背景 pH 按其当前模式联动或独立保存。若其他实验条件也相同，可加入范围后一并应用；参比等不同则单独设置。")
            st.button("将关联背景加入应用范围", key=f"include_backgrounds_{purpose}",
                on_click=_include_background_targets, args=(target_key, background_ids))
        all_backgrounds = list(dict.fromkeys(bgid for ident in targets
            for bgid in linked_backgrounds(st.session_state.configs[ident], st.session_state.configs)))
        if is_background:
            all_backgrounds = [source]
        background_ph_panel(all_backgrounds, f"conditions_ph_{purpose}_{source}")
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
            if electrolyte != cfg.get("electrolyte", ""):
                values["electrolyte"] = electrolyte
            st.json({"参数来源":cfg.get("parameter_sources", {}), "当前盘面积_cm2":cfg.get("area_cm2")})
        pending = unapplied_changes(cfg, values)
        if pending:
            draft_notice.warning("修改尚未应用：输入框是草稿，当前待完成项和计算仍读取已应用参数。请点击下方“应用实验参数”。")
        if st.button("应用实验参数", type="primary", disabled=not targets, key=f"apply_conditions_{purpose}"):
            try:
                validate_conditions(values)
                if values.get("potential_method") == "理论换算" and values.get("reference_preset_C") is not None and values.get("temperature_C") is not None and not math.isclose(values["temperature_C"], values["reference_preset_C"]):
                    raise DataError("该参比预设仅限 25 °C。请选择对应温度的自定义值或实测 RHE 总偏移。")
                updated = copy.deepcopy(st.session_state.configs)
                for ident in targets:
                    apply_conditions(updated[ident], values, background_ph_edit=is_background)
                st.session_state.configs = updated
                st.session_state.conditions_notice = f"已应用实验条件到 {len(targets)} 个文件。"
                invalidate()
                st.rerun()
            except (DataError, ValueError, TypeError) as exc:
                st.error(str(exc))
        _profiles(cfg, targets, f"profiles_{purpose}_{source}_", pending=pending)
