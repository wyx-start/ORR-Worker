import matplotlib.pyplot as plt
import numpy as np
import streamlit as st
from condition_ui import common_parameter_form
from orr_core import DataError, KOH_PRESET, SOURCES, json_bytes, kl_calculate
from ui_shared import (axis_label, figure_style, file_formatter, label, offer_figure, process_all,
                       require_files, show_errors, show_notes, store_table)

st.title("多转速 K–L 分析")
st.write("在共同电位上拟合 1/j 与 ω⁻¹ᐟ²，输出表观电子转移数和两路径模型估算。")
st.caption("K–L 不能无条件等同于实测产物选择性；数值超范围时保留并标注。[方法限制]("+SOURCES["kl_limits"]+")")
require_files()
common_parameter_form(purpose="kl")
outputs, errors = process_all()
show_errors(errors)
if not outputs:
    st.stop()
groups = list(dict.fromkeys(o["config"]["group"] for o in outputs.values()))
params = st.session_state.settings.setdefault("kl", {})
saved_group = params.get("group")
group = st.selectbox("实验组", groups, index=groups.index(saved_group) if saved_group in groups else 0, key="kl_group")
options = [k for k,o in outputs.items() if o["config"]["group"]==group]
default_selection = [k for k in params.get("selected", options) if k in options] if saved_group==group else options
selected = st.multiselect("参与拟合的文件（每个转速一条）", options, default=default_selection, format_func=file_formatter(), key=f"kl_files_{group}_{st.session_state.revision}")
if len(selected)<2:
    st.info("请把至少两个不同转速文件设置为同一组，并在上方选择。")
    st.stop()
chosen = {k:outputs[k] for k in selected}
with st.expander("核对实际参与计算的文件参数", expanded=True):
    st.dataframe([{
        "文件":o["name"], "转速 / rpm":o["config"].get("rpm"),
        "盘面积 / cm²":o["config"].get("area_cm2"), "pH":o["config"].get("pH"),
        "温度 / °C":o["config"].get("temperature_C"),
        "电解液":o["config"].get("electrolyte", ""),
        "电位坐标":o["axis"], "扫描方向":o["segment"]["direction"],
    } for o in chosen.values()], hide_index=True)
    st.caption("以上是已应用参数。5 mm 盘对应约 0.19635 cm²；转速填 rpm，程序自动换算为 rad/s。")
low = max(o["data"].E_V.min() for o in chosen.values())
high = min(o["data"].E_V.max() for o in chosen.values())
if low>=high:
    st.error("这些曲线没有共同电位区间。")
    st.stop()
if len(selected)==2:
    st.warning("只有两个转速：可以求斜率，但不报告有意义的 R² 或斜率标准误。")
scheme = st.selectbox("电解液参数方案 *", ["自定义", "O₂ 饱和 0.1 M KOH · 25 °C（文献近似值）"],
    index=1 if params.get("scheme") == "koh_25C" else 0, key=f"kl_scheme_{st.session_state.revision}", persist_state="session")
use_preset = scheme != "自定义"
if use_preset:
    st.caption("仅适用于 O₂ 饱和 0.1 M KOH、25 °C。C=1.2×10⁻⁶ mol/cm³；D=1.9×10⁻⁵ cm²/s；ν=0.01 cm²/s。[文献来源]("+KOH_PRESET["source"]+")。不能自动套用于 Na 电解液。")
with st.form(f"kl_input_{st.session_state.revision}_{st.session_state.get('kl_form_epoch',0)}"):
    if use_preset:
        C, D, nu, source = (KOH_PRESET[k] for k in ("C", "D", "nu", "source"))
    else:
        a, b, c = st.columns(3)
        with a:
            C = st.number_input("氧浓度 C / mol·cm⁻³ *", value=params.get("C"), min_value=1e-12, format="%.8e", step=1e-7, key="kl_custom_C", persist_state="session",
                help="填写溶解氧浓度，不是电解液浓度。若来源单位为 mol/L，需除以 1000 后填入。")
        with b:
            D = st.number_input("扩散系数 D / cm²·s⁻¹ *", value=params.get("D"), min_value=1e-12, format="%.8e", step=1e-6, key="kl_custom_D", persist_state="session",
                help="若来源单位为 m²/s，需乘以 10000 后填入。请使用实际电解液和温度下的氧扩散系数。")
        with c:
            nu = st.number_input("运动黏度 ν / cm²·s⁻¹ *", value=params.get("nu"), min_value=1e-12, format="%.8e", step=.001, key="kl_custom_nu", persist_state="session",
                help="需要运动黏度，不是动力黏度。若来源单位为 m²/s，需乘以 10000；若为 cSt，需乘以 0.01。")
        source = st.text_input("参数来源与适用条件（选填记录）", value=params.get("source", ""), placeholder="文献 DOI 或实验测定记录；包括温度、电解液、氧饱和情况", key="kl_custom_source", persist_state="session")
    st.caption(f"共同覆盖区间：{low:.5f} ～ {high:.5f} V（{st.session_state.settings['axis']}）。")
    with st.expander("分析区间与点数（请核对）", expanded=True):
        st.caption("初始范围仅表示数据共同覆盖，并未识别适用的 ORR 反应区间。请结合各转速曲线选择分析电位，避开电流过小、反向及其他反应区；不要以 n 是否落在 2–4 内反推区间。")
        a, b, c = st.columns(3)
        with a:
            start = st.number_input("分析起点 / V", value=float(max(low, min(params.get("start",low),high))), format="%.5f")
        with b:
            end = st.number_input("分析终点 / V", value=float(max(low, min(params.get("end",high),high))), format="%.5f")
        with c:
            count = st.number_input("等间距电位点数", min_value=1, max_value=500, value=int(params.get("count",30)), step=1)
    confirmed = st.checkbox("已核对：各文件属于同一电极和相同实验条件，以上物性参数适用")
    run = st.form_submit_button("计算 K–L", type="primary")
if run:
    # A failed new attempt must not leave the preceding fit looking current.
    st.session_state.results.pop("kl", None)
    for filename in list(st.session_state.exports):
        if filename.startswith("kl_"):
            st.session_state.exports.pop(filename)
    try:
        if not confirmed:
            raise DataError("请先核对实验条件和物性参数。")
        if use_preset and any(abs(float(o["config"].get("temperature_C", 25))-25.)>1e-8 for o in chosen.values()):
            raise DataError("所选文献方案仅限 25 °C，请修正实验温度或选择自定义物性参数。")
        if start>end or start<low-1e-9 or end>high+1e-9:
            raise DataError("分析区间应位于共同覆盖范围内，且起点不能大于终点。")
        if count>1 and start==end:
            raise DataError("分析单个电位请把点数设为 1。")
        potentials = np.linspace(start, end, count) if count>1 else np.array([start])
        result, points = kl_calculate(list(chosen.values()), potentials, C, D, nu)
        params.update(C=C, D=D, nu=nu, source=source, start=start, end=end, count=count, selected=selected, group=group,
                      axis=st.session_state.settings["axis"],
                      units={"C":"mol/cm³", "D":"cm²/s", "nu":"cm²/s", "current_density":"A/cm²", "rotation_input":"rpm", "rotation_fit":"rad/s"},
                      scheme="koh_25C" if use_preset else "custom", condition=KOH_PRESET["electrolyte"] if use_preset else "用户自定义")
        st.session_state.results["kl"] = dict(data=result, points=points, selected=selected, params=dict(params), revision=st.session_state.revision)
    except (DataError, ValueError) as exc:
        st.error(str(exc))
saved = st.session_state.results.get("kl")
if saved:
    st.caption("以下为上次点击“计算 K–L”的结果；修改输入后请重新计算。")
    result, points = saved["data"], saved["points"]
    used = saved["params"]
    st.caption(f"本次结果使用：C={used['C']:.6g} mol/cm³，D={used['D']:.6g} cm²/s，ν={used['nu']:.6g} cm²/s；分析范围 {used['start']:.5f} ～ {used['end']:.5f} V（{used.get('axis', st.session_state.settings['axis'])}）。")
    invalid_count = int((~result.valid_two_path_model).sum())
    if invalid_count:
        st.warning(f"{len(result)} 个电位中有 {invalid_count} 个不满足两路径模型检查。请查看 status：电流过小或反向、斜率非正、负截距、n 超出 2–4 均需核对。原始数值保留；负数或超过 100% 的模型比例不可作为有效选择性。")
    st.dataframe(result, hide_index=True)
    st.download_button("单独导出 K–L 结果 CSV", store_table("kl_results.csv", result), "kl_results.csv", "text/csv")
    st.download_button("单独导出拟合点 CSV", store_table("kl_fit_points.csv", points), "kl_fit_points.csv", "text/csv")
    st.download_button("单独导出 K–L 参数", json_bytes(saved["params"]), "kl_parameters.json", "application/json")
    figure_style()
    fig, ax = plt.subplots(figsize=(8,4.5), layout="constrained")
    ax.plot(result.E_V, result.n_KL, color="#167D8D", marker="o", ms=3)
    ax.axhline(2, color="#B5BDC1", ls="--", lw=.8)
    ax.axhline(4, color="#B5BDC1", ls="--", lw=.8)
    ax.set(xlabel=axis_label({k:outputs[k] for k in saved["selected"]}), ylabel="Apparent electron number n", title="Koutecky–Levich analysis")
    offer_figure(fig, "kl_electron_number")
    fig, ax = plt.subplots(figsize=(8,4.5), layout="constrained")
    ax.plot(result.E_V, result.two_e_pct_model, color="#167D8D", label="2e (model)")
    ax.plot(result.E_V, result.four_e_pct_model, color="#D66A3C", label="4e (model)")
    ax.set(xlabel=axis_label({k:outputs[k] for k in saved["selected"]}), ylabel="Selectivity estimate / %", title="K–L two-path model estimate")
    ax.legend(frameon=False)
    offer_figure(fig, "kl_two_four_e_model")
    if not points.empty:
        available = sorted(points.E_V.unique())
        potential = st.select_slider("查看某个电位的拟合", options=available, value=available[len(available)//2], format_func=lambda x:f"{x:.4f} V")
        fit = points[points.E_V==potential].sort_values("omega_inv_sqrt")
        fig, ax = plt.subplots(figsize=(7,4), layout="constrained")
        ax.scatter(fit.omega_inv_sqrt, fit.inverse_j_cm2_A, color="#167D8D", label="Data")
        ax.plot(fit.omega_inv_sqrt, fit.fit_inverse_j_cm2_A, color="#D66A3C", label="Linear fit")
        ax.set(xlabel="ω$^{-1/2}$ / (rad s$^{-1}$)$^{-1/2}$", ylabel="1/j / cm$^2$ A$^{-1}$", title=f"K–L fit at {potential:.4f} V")
        ax.legend(frameon=False)
        offer_figure(fig, "kl_fit")
show_notes(chosen)
