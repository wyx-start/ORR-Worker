from copy import deepcopy

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from condition_ui import common_parameter_form
from download_ui import result_downloads
from origin_export import csv_bytes, rrde_plot_table
from orr_core import DataError, SOURCES, json_bytes, parameter_record, rrde_calculate, require_number
from ui_shared import (apply_pending_settings, apply_settings_button, axis_label,
                       figure_style, file_formatter, get_draft_configs,
                       get_draft_settings, has_draft, label, offer_figure,
                       pending_candidate, process_selected, require_files, get_draft_view,
                       show_errors, show_notes, store_table)


def clear_rrde():
    st.session_state.results.pop("rrde", None)
    for name in list(st.session_state.exports):
        if name.startswith("rrde_"):
            st.session_state.exports.pop(name)


st.title("RRDE 选择性")
st.write("用同期盘、环电流计算过氧化物产率和电子转移数；盘、环先分别扣背景。")
st.caption("过氧化物产率包括碱性条件下的 HO₂⁻ 表述；这里的产物比例不是法拉第效率。四电子比例采用两产物模型。[公式来源]("+SOURCES["rrde"]+")")
require_files()
workspace = st.session_state.get("workspace_epoch", 0)
configs, settings = get_draft_configs(), get_draft_settings()
options = [ident for ident, trace in st.session_state.traces.items()
           if configs[ident].get("role") != "背景" and len(trace.columns) >= 3]
if not options:
    clear_rrde()
    st.info("请导入双通道数据，并在扫描与背景中核对盘环通道。")
    st.stop()
opts = deepcopy(settings.get("rrde", {}))
defaults = [ident for ident in opts.get("selected", options) if ident in options]
selected = st.multiselect("RRDE 文件", options, default=defaults,
                          format_func=file_formatter(), key=f"rrde_files_{workspace}", persist_state="session")
if selected:
    common_parameter_form(purpose="rrde", ids=selected)
apply_settings_button(key=f"rrde_apply_settings_{workspace}")
preview_view = get_draft_view()
configs, settings = preview_view["configs"], preview_view["settings"]
if preview_view["view_basis"] == "applied_fallback":
    outputs, errors = {}, []
    st.warning("草稿待修正；下方条件基于已应用设置，暂不生成分析预览。")
else:
    outputs, errors = process_selected(selected, configs=preview_view["records"], settings=settings)
show_errors(errors)
if not selected:
    clear_rrde()
    st.info("至少选择一个 RRDE 文件。")
    st.stop()
floor = settings.get("rrde", {}).get("floor_A", 1e-9)
current_inputs = dict(floor_A=floor, selected=list(selected))
signature = json_bytes(current_inputs)
saved = st.session_state.results.get("rrde")
if saved and (saved.get("input_signature") != signature or saved.get("revision") != st.session_state.revision):
    clear_rrde()
    st.info("分析输入已修改，请重新计算。")


def compute_current():
    clear_rrde()
    require_number(floor, "最小盘电流幅值（A）", positive=True)
    candidate_configs, candidate_settings = pending_candidate()
    processed, failures = process_selected(selected, configs=candidate_configs, settings=candidate_settings)
    results, chosen = {}, {}
    for ident, output in processed.items():
        try:
            results[ident] = rrde_calculate(output, output["config"], floor)
            chosen[ident] = output
        except (DataError, ValueError, TypeError, IndexError) as exc:
            failures.append({"文件": output["name"], "原因": str(exc)})
    if not results:
        detail = "；".join(f"{row['文件']}：{row['原因']}" for row in failures)
        raise DataError("选中文件没有可计算的 RRDE 结果。"+detail)
    frames = []
    for ident, frame in results.items():
        export = frame.copy()
        export.insert(0, "file_id", ident)
        export.insert(1, "filename", chosen[ident]["name"])
        export.insert(2, "potential_axis", chosen[ident]["axis"])
        export.insert(3, "rpm", chosen[ident]["config"].get("rpm"))
        export.insert(4, "rpm_source", chosen[ident]["config"].get("rpm_source"))
        frames.append(export)
    merged = pd.concat(frames, ignore_index=True)
    used = deepcopy(candidate_settings.get("rrde", {}))
    used.update(current_inputs)
    used["axis"] = candidate_settings.get("axis", "RHE")
    wide = rrde_plot_table(results, chosen)
    apply_pending_settings()
    st.session_state.settings["rrde"] = deepcopy(used)
    params = parameter_record(st.session_state.traces, st.session_state.configs,
                               st.session_state.settings, chosen)
    saved_result = dict(data=merged, frames=results, outputs=chosen, selected=list(selected),
                        params=params, inputs=used, errors=failures, plot=wide,
                        revision=st.session_state.revision, input_signature=signature)
    st.session_state.results["rrde"] = saved_result
    store_table("rrde_results.csv", merged)
    return saved_result


if st.button("应用并计算 RRDE" if has_draft() else "计算 RRDE", type="primary", key=f"rrde_calculate_{workspace}"):
    try:
        compute_current()
    except (DataError, ValueError, TypeError, IndexError) as exc:
        st.error(str(exc))


def prepare_download():
    result = compute_current()
    return csv_bytes(result["plot"]), "rrde_plot.csv", "text/csv"


saved = st.session_state.results.get("rrde")
figures, extras, plot_payload = [], [], None
if saved:
    results, chosen, merged = saved["frames"], saved["outputs"], saved["data"]
    if has_draft():
        st.warning("下方是已应用设置的计算结果。草稿尚未应用；导出绘图 CSV 将先应用并重新计算。")
    show_errors(saved["errors"])
    for ident, output in chosen.items():
        if not output["config"].get("ring_detection_confirmed"):
            st.warning(label(ident)+"：尚未确认环电位可定量检测过氧化物，当前结果仅供核对。请在扫描与背景中记录检测条件。")
    figure_style()
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True, layout="constrained")
    for ident, frame in results.items():
        name = chosen[ident]["config"]["name"]
        axes[0].plot(frame.E_V, frame.peroxide_pct, label=name, lw=1.5)
        axes[1].plot(frame.E_V, frame.n_RRDE, label=name, lw=1.5)
    axes[0].set(ylabel="Peroxide yield / %", title="RRDE analysis")
    axes[1].set(xlabel=axis_label(chosen), ylabel="Electron number n")
    axes[0].axhline(100, color="#B5BDC1", ls="--", lw=.8)
    axes[1].axhline(2, color="#B5BDC1", ls="--", lw=.8)
    axes[1].axhline(4, color="#B5BDC1", ls="--", lw=.8)
    axes[0].legend(frameon=False, fontsize=8)
    offer_figure(fig, "rrde_selectivity")
    figures.append("rrde_selectivity")
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    for ident, frame in results.items():
        name = chosen[ident]["config"]["name"]
        line, = ax.plot(frame.E_V, frame.peroxide_pct, label=name+" · 2e", lw=1.5)
        ax.plot(frame.E_V, frame.four_e_pct_model, label=name+" · 4e (model)",
                color=line.get_color(), ls="--", lw=1.5)
    ax.set(xlabel=axis_label(chosen), ylabel="Product fraction / %", title="RRDE two-product model")
    ax.legend(frameon=False, fontsize=8)
    offer_figure(fig, "rrde_two_four_e")
    figures.append("rrde_two_four_e")
    valid = int(merged.valid_two_product_model.sum())
    st.caption(f"结果修订 {saved['revision']} · 共 {len(merged)} 个点；{valid} 个点符合符号、阈值和两产物模型范围检查。其余点保留原因；超范围值没有裁剪。")
    with st.expander("全部结果与异常点"):
        only_issues = st.checkbox("只显示需要检查的点")
        st.dataframe(merged[~merged.valid_two_product_model] if only_issues else merged, hide_index=True)
    plot_payload = csv_bytes(saved["plot"])
    extras = [("完整数据 CSV · 含异常原因", "rrde_results.csv", csv_bytes(merged), "text/csv"),
              ("参数 JSON", "rrde_parameters.json", json_bytes(saved["params"]), "application/json")]
    show_notes(chosen)
st.caption("Origin 绘图 CSV 为每个样品的独立电位／产率／电子数列组；不同网格与缺口保留。完整数据 CSV 另含原始、背景、处理电流及状态。")
result_downloads(plot_payload, "rrde_plot.csv", figures=figures, extras=extras,
                 key=f"rrde_download_{workspace}", prepare=prepare_download)

