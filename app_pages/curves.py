import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from condition_ui import common_parameter_form
from orr_core import DataError, json_bytes, potential_signature
from plot_smoothing import (PRESET_WINDOWS, SMOOTH_DENSITY, SMOOTH_MA,
                            smooth_for_plot, smoothing_defaults)
from ring_comparison import audit_ring_comparison
from ui_shared import (axis_label, figure_style, file_formatter, label, merged_data, offer_figure, parameters,
                       clear_polarization_exports, process_all, require_files, show_errors, show_notes, store_table)

st.title("极化曲线")
st.caption("从 CV 提取的单向极化曲线。可选平滑只用于这张图，K–L 与 RRDE 计算继续使用未平滑数据。")
require_files()
channel = st.selectbox("绘制通道", ["盘电流", "环电流"],
    index=1 if st.session_state.settings.get("plot_channel") == "ring" else 0,
    key=f"curve_channel_{st.session_state.revision}")
is_ring = channel == "环电流"
st.session_state.settings["plot_channel"] = "ring" if is_ring else "disk"
clear_polarization_exports("ring" if is_ring else "disk")
settings = st.session_state.settings.setdefault("ring_plot" if is_ring else "plot", {})
if is_ring:
    units = st.selectbox("纵坐标", ["环电流 / μA", "环电流 / mA"],
        index=1 if settings.get("unit") == "mA" else 0, key=f"ring_units_{st.session_state.revision}")
    settings["unit"] = "mA" if units.endswith("mA") else "uA"
    view = st.selectbox("环电流显示", ["处理后", "未扣背景"],
        index=1 if settings.get("background_view") == "未扣背景" else 0,
        key=f"ring_view_{st.session_state.revision}")
    settings["background_view"] = view
    st.caption("横轴为盘扫描电位；环设定电位仅作记录。电流保留原始符号，不除以 N。没有绑定环背景时显示未扣背景电流。")
else:
    units = st.selectbox("纵坐标", ["电流 / mA", "电流密度 / mA·cm⁻²"],
        index=1 if settings.get("density") else 0, key=f"curve_units_{st.session_state.revision}")
settings["density"] = not is_ring and units.startswith("电流密度")
subtract_background = not is_ring or view == "处理后"
ring_ids = [i for i,c in st.session_state.configs.items() if c.get("role") != "背景" and c.get("ring_channel") is not None] if is_ring else None
if is_ring and not ring_ids:
    st.info("暂无有效环通道候选，请在扫描与背景中核对盘环接线；单通道文件不加入环图。")
    st.stop()
common_parameter_form(purpose="ring" if is_ring else "curves", ids=ring_ids, density=settings["density"],
                      channels="ring" if is_ring else "all", subtract_background=subtract_background)
outputs, errors = process_all(channels="ring" if is_ring else "all", subtract_background=subtract_background)
show_errors(errors)
if not outputs:
    st.info("请补全实验参数；如需先看原始曲线，可将左侧电位坐标切为“原始”。")
    st.stop()
groups = list(dict.fromkeys(o["config"]["group"] for o in outputs.values()))
group_options = ["全部"]+groups
saved_group = settings.get("group", groups[0])
group = st.selectbox("按组筛选", group_options, index=group_options.index(saved_group) if saved_group in group_options else 0)
options = [k for k,o in outputs.items() if group=="全部" or o["config"]["group"]==group]
selection_by_group = settings.setdefault("selection_by_group", {})
default_selection = [k for k in selection_by_group.get(group, options) if k in options]
selected = st.multiselect("叠加显示的曲线", options, default=default_selection, format_func=file_formatter(), key=f"curve_selection_{group}_{st.session_state.revision}")
settings["group"] = group
selection_by_group[group] = selected
if not selected:
    st.info("至少选择一条曲线。")
    st.stop()
chosen = {k:outputs[k] for k in selected}
if is_ring:
    audit = audit_ring_comparison(chosen)
    settings["comparison_audit"] = audit
    st.subheader("环电流比较条件")
    st.dataframe(pd.DataFrame(audit["rows"]), hide_index=True)
    st.caption("允许转速和环设定电位不同；其他已知条件冲突时阻止。缺失记录仅提示，电位换算所需输入仍须有效。")
    if audit["missing"]:
        st.warning("部分比较条件未记录，允许叠加；当前仅核对已知项，不能认定全部实验条件一致。")
        with st.expander("查看未记录的条件"):
            st.dataframe(pd.DataFrame(audit["missing"]), hide_index=True)
    if audit["conflicts"]:
        st.error("环电流比较存在已知条件冲突，请修正配置、调整选择或分别绘图。")
        st.dataframe(pd.DataFrame(audit["conflicts"]), hide_index=True)
        st.stop()
signatures = {potential_signature(o["config"], o["axis"]) for o in chosen.values()}
if not is_ring and len(signatures)>1:
    st.error("选中曲线的原始参比坐标不一致。请改用 RHE 或分别绘图。")
    st.stop()
smooth_cfg = smoothing_defaults(settings.get("smoothing"))
smooth_key = f"smoothing_{st.session_state.revision}" + ("_ring" if is_ring else "")
with st.container(border=True):
    st.subheader("曲线平滑（仅绘图）")
    enabled = st.toggle("启用曲线平滑", value=bool(smooth_cfg["enabled"]), key=smooth_key+"_enabled")
    a, b = st.columns(2)
    with a:
        strength_options = list(PRESET_WINDOWS) + ["自定义"]
        saved_strength = smooth_cfg.get("preset", "弱")
        strength = st.selectbox("平滑强度", strength_options,
                                index=strength_options.index(saved_strength) if saved_strength in strength_options else 0,
                                format_func=lambda v: f"{v} · {PRESET_WINDOWS[v]} 点" if v in PRESET_WINDOWS else "自定义奇数窗口",
                                disabled=not enabled, key=smooth_key+"_strength")
        custom = smooth_cfg.get("custom_window", 11)
        if strength=="自定义":
            custom = st.number_input("自定义窗口 / 点（5–1001 的奇数）", min_value=5, max_value=1001,
                                     value=int(custom), step=2, disabled=not enabled, key=smooth_key+"_custom")
        window = PRESET_WINDOWS.get(strength, int(custom))
    with b:
        show_unsmoothed = st.toggle("显示浅色未平滑参考线", value=bool(smooth_cfg["show_unsmoothed"]),
                                     disabled=not enabled, key=smooth_key+"_reference")
    st.caption("Savitzky–Golay · 二阶多项式。窗口越大，细节可能越少；端部也可能改变。缺口不补齐，短段或不等间距段保留未平滑数据。")
smooth_cfg.update(enabled=enabled, preset=strength, window_points=int(window), custom_window=int(custom),
                  show_unsmoothed=show_unsmoothed)
settings["smoothing"] = smooth_cfg
with st.expander("图形设置", expanded=False):
    a, b = st.columns(2)
    with a:
        title = st.text_input("图标题", value=settings.get("title", "RRDE ring current comparison" if is_ring else "ORR polarization curves"), key=f"plot_title_{is_ring}_{st.session_state.revision}")
        legend = st.checkbox("显示图例", value=settings.get("legend", True))
    with b:
        line_width = st.number_input("线宽", min_value=.5, max_value=5., value=float(settings.get("line_width", 1.8)), step=.1)
        width = st.number_input("图片宽度 / 英寸", min_value=4., max_value=16., value=float(settings.get("width", 8.)), step=.5)
        height = st.number_input("图片高度 / 英寸", min_value=3., max_value=12., value=float(settings.get("height", 5.)), step=.5)
    a, b = st.columns(2)
    with a:
        xmin = st.number_input("横轴最小值（空白＝自动）", value=settings.get("xmin"), format="%.4f")
        xmax = st.number_input("横轴最大值（空白＝自动）", value=settings.get("xmax"), format="%.4f")
    with b:
        ymin = st.number_input("纵轴最小值（空白＝自动）", value=settings.get("ymin"), format="%.4f")
        ymax = st.number_input("纵轴最大值（空白＝自动）", value=settings.get("ymax"), format="%.4f")
    colors = settings.setdefault("colors", {})
    palette = ["#167D8D", "#D66A3C", "#6956A3", "#609A65", "#B7486C", "#A68138", "#416EBA", "#777777"]
    for index, ident in enumerate(selected):
        colors[ident] = st.color_picker(outputs[ident]["config"]["name"], value=colors.get(ident, palette[index%len(palette)]), key=f"color_{ident}_{st.session_state.revision}")
settings.update(density=units.startswith("电流密度"), title=title, legend=legend, line_width=line_width,
                width=width, height=height, xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax)
if (xmin is not None and xmax is not None and xmin>=xmax) or (ymin is not None and ymax is not None and ymin>=ymax):
    st.error("坐标最小值必须小于最大值。")
    st.stop()
ycol = ("I_ring_mA" if settings["unit"] == "mA" else "I_ring_uA") if is_ring else ("j_disk_mA_cm2" if settings["density"] else "I_disk_mA")
missing = [o["name"] for o in chosen.values() if ycol not in o["data"]]
if missing:
    st.error("以下文件缺少盘面积，无法绘制电流密度："+"、".join(missing))
    st.stop()
plotted = {}
smoothing_reports = {}
for ident, result in chosen.items():
    try:
        display_data, report = smooth_for_plot(result["data"], smooth_cfg, channel="ring" if is_ring else "disk")
    except DataError as exc:
        st.error(str(exc))
        st.stop()
    plotted[ident] = dict(result, data=display_data)
    smoothing_reports[ident] = dict(report, filename=result["name"], sha256=result["sha256"])
settings["smoothing_report"] = smoothing_reports
if enabled:
    summary_rows = []
    for ident, report in smoothing_reports.items():
        spans = [s["requested_window_span_mV"] for s in report["segments"] if s["requested_window_span_mV"] is not None]
        span_text = " / ".join(f"{v:.4g}" for v in dict.fromkeys(round(x,6) for x in spans)) or "—"
        summary_rows.append({"文件": report["filename"], "窗口/点":window, "窗口跨度/mV（按各连续段）":span_text,
                             "已平滑点":report["applied_points"], "保留未平滑点":report["preserved_points"], "缺口点":report["gap_points"]})
        for note in report["notes"]:
            st.warning(report["filename"]+"："+note)
    st.dataframe(pd.DataFrame(summary_rows), hide_index=True)
figure_style()
fig, ax = plt.subplots(figsize=(width, height), layout="constrained")
for ident, result in plotted.items():
    df = result["data"]
    if enabled and show_unsmoothed and smoothing_reports[ident]["applied_points"]:
        ax.plot(df.E_V, df[ycol], color=colors[ident], lw=max(.7, line_width*.65), alpha=.28, zorder=1)
    display_col = (f"I_ring_smoothed_plot_only_{settings['unit']}" if is_ring else (SMOOTH_DENSITY if settings["density"] else SMOOTH_MA)) if enabled else ycol
    if is_ring:
        df["plotted_current_value"] = df[display_col]
        df["plotted_current_unit"] = settings["unit"]
        df["background_view"] = settings["background_view"]
        df["sample_name"] = result["config"]["name"]
        df["I_ring_corrected_A"] = df["I_ring_A"] if subtract_background else float("nan")
    ax.plot(df.E_V, df[display_col], label=result["config"]["name"], color=colors[ident], lw=line_width, zorder=2)
ax.set(xlabel=axis_label(chosen), ylabel=("Ring I / mA" if settings["unit"] == "mA" else "Ring I / μA") if is_ring else ("j / mA cm$^{-2}$" if settings["density"] else "I / mA"), title=title)
ax.set_xlim(left=xmin, right=xmax)
ax.set_ylim(bottom=ymin, top=ymax)
ax.axhline(0, color="#D9DFE2", lw=.7, zorder=0)
if legend:
    ax.legend(frameon=False, fontsize=8)
if enabled:
    fig.text(.5, -.01, f"Display only · Savitzky–Golay: {window} points, order 2 · gaps and skipped segments retained",
             ha="center", fontsize=8, color="#52616B")
export_name = "ring_current" if is_ring else "polarization"
offer_figure(fig, export_name)
data = merged_data(plotted)
payload = store_table(f"{export_name}_data.csv", data)
parameter_name = "ring_current_parameters.json" if is_ring else "parameters.json"
parameter_payload = json_bytes(parameters(outputs))
if is_ring:
    from ui_shared import set_export
    set_export(parameter_name, parameter_payload, "application/json")
with st.container(horizontal=True):
    st.download_button("单独导出曲线 CSV", payload, f"{export_name}_data.csv", "text/csv")
    st.download_button("单独导出参数 JSON", parameter_payload, parameter_name, "application/json")
show_notes(chosen)
if enabled:
    st.caption("CSV 中 smoothed_plot_only 列对应图中的实线；I_disk_A / I_ring_A 等原有列仍是未平滑数据。浅色参考线可隐藏，分析计算始终不变。")
with st.expander("处理后的数据"):
    st.dataframe(data, hide_index=True)
