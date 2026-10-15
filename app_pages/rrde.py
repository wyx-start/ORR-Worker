import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st
from condition_ui import common_parameter_form
from orr_core import DataError, SOURCES, json_bytes, rrde_calculate
from ui_shared import (axis_label, figure_style, file_formatter, label, offer_figure, parameters,
                       process_all, require_files, show_errors, show_notes, store_table)

st.title("RRDE 选择性")
st.write("用同期盘、环电流计算过氧化物产率和电子转移数；盘、环先分别扣背景。")
st.caption("过氧化物产率包括碱性条件下的 HO₂⁻ 表述；这里的产物比例不是法拉第效率。四电子比例采用两产物模型。[公式来源]("+SOURCES["rrde"]+")")
require_files()
rrde_ids = [k for k,t in st.session_state.traces.items() if len(t.columns) >= 3 and st.session_state.configs[k].get("role") != "背景"]
if rrde_ids:
    common_parameter_form(purpose="rrde", ids=rrde_ids)
outputs, errors = process_all()
show_errors(errors)
options = [k for k,o in outputs.items() if "I_ring_A" in o["data"]]
if not options:
    st.info("请导入双通道数据，在导入页核对盘环对应并填写收集效率 N；RHE 坐标还需电位换算参数。")
    st.stop()
opts = st.session_state.settings.setdefault("rrde", {})
default_selection = [k for k in opts.get("selected", options) if k in options]
selected = st.multiselect("RRDE 文件", options, default=default_selection, format_func=file_formatter())
with st.expander("高级：低电流阈值"):
    floor = st.number_input("最小盘还原电流幅值 / A", min_value=1e-15, value=float(opts.get("floor_A",1e-9)), format="%.3e", help="低于阈值的点不计算比值；不对异常符号取绝对值。")
opts.update(floor_A=floor, selected=selected)
results, rrde_errors, chosen = {}, [], {}
for ident in selected:
    cfg = st.session_state.configs[ident]
    try:
        result = rrde_calculate(outputs[ident], cfg, floor)
        results[ident] = result
        chosen[ident] = outputs[ident]
        if not cfg.get("ring_detection_confirmed"):
            st.warning(label(ident)+"：尚未确认环电位可定量检测过氧化物，当前结果仅供核对。请在“扫描与背景”中记录检测条件。")
    except (DataError, ValueError, TypeError) as exc:
        rrde_errors.append({"文件":outputs[ident]["name"], "原因":str(exc)})
show_errors(rrde_errors)
if not results:
    st.stop()
figure_style()
fig, axes = plt.subplots(2,1, figsize=(8,7), sharex=True, layout="constrained")
frames = []
for ident, frame in results.items():
    name = st.session_state.configs[ident]["name"]
    axes[0].plot(frame.E_V, frame.peroxide_pct, label=name, lw=1.5)
    axes[1].plot(frame.E_V, frame.n_RRDE, label=name, lw=1.5)
    export = frame.copy()
    export.insert(0,"file_id",ident)
    export.insert(1,"filename",outputs[ident]["name"])
    export.insert(2,"potential_axis",outputs[ident]["axis"])
    frames.append(export)
axes[0].set(ylabel="Peroxide yield / %", title="RRDE analysis")
axes[1].set(xlabel=axis_label(chosen), ylabel="Electron number n")
axes[0].axhline(100, color="#B5BDC1", ls="--", lw=.8)
axes[1].axhline(2, color="#B5BDC1", ls="--", lw=.8)
axes[1].axhline(4, color="#B5BDC1", ls="--", lw=.8)
axes[0].legend(frameon=False, fontsize=8)
offer_figure(fig,"rrde_selectivity")
fig, ax = plt.subplots(figsize=(8,4.5), layout="constrained")
for ident, frame in results.items():
    name = st.session_state.configs[ident]["name"]
    line, = ax.plot(frame.E_V, frame.peroxide_pct, label=name+" · 2e", lw=1.5)
    ax.plot(frame.E_V, frame.four_e_pct_model, label=name+" · 4e (model)", color=line.get_color(), ls="--", lw=1.5)
ax.set(xlabel=axis_label(chosen), ylabel="Product fraction / %", title="RRDE two-product model")
ax.legend(frameon=False, fontsize=8)
offer_figure(fig,"rrde_two_four_e")
merged = pd.concat(frames, ignore_index=True)
valid = int(merged.valid_two_product_model.sum())
st.caption(f"共 {len(merged)} 个点；{valid} 个点符合符号、阈值和两产物模型范围检查。其余点保留原因；超范围值没有裁剪。")
with st.container(horizontal=True):
    st.download_button("单独导出 RRDE CSV",store_table("rrde_results.csv",merged),"rrde_results.csv","text/csv")
    st.download_button("单独导出参数 JSON",json_bytes(parameters(outputs)),"rrde_parameters.json","application/json")
st.session_state.results["rrde"] = dict(data=merged, revision=st.session_state.revision)
with st.expander("全部结果与异常点"):
    only_issues = st.checkbox("只显示需要检查的点")
    st.dataframe(merged[~merged.valid_two_product_model] if only_issues else merged, hide_index=True)
show_notes(chosen)
