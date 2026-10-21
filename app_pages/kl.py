from copy import deepcopy

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from condition_ui import common_parameter_form
from download_ui import result_downloads
from origin_export import effective_axis, csv_bytes, kl_fit_plot_table
from orr_core import DataError, KOH_PRESET, SOURCES, json_bytes, kl_calculate
from ui_shared import (apply_pending_settings, apply_settings_button, axis_label,
                       figure_style, file_formatter, get_draft_configs,
                       get_draft_settings, has_draft, offer_figure,
                       pending_candidate, process_selected, require_files,
                       show_errors, show_notes, store_table)


def clear_kl():
    st.session_state.results.pop("kl", None)
    for name in list(st.session_state.exports):
        if name.startswith("kl_"):
            st.session_state.exports.pop(name)


st.title("多转速 K–L 分析")
st.write("在共同电位上拟合 1/j 与 ω⁻¹ᐟ²，输出表观电子转移数和两路径模型估算。")
st.caption("K–L 不能无条件等同于实测产物选择性；数值超范围时保留并标注。[方法限制]("+SOURCES["kl_limits"]+")")
require_files()
workspace = st.session_state.get("workspace_epoch", 0)
configs, settings = get_draft_configs(), get_draft_settings()
params = deepcopy(settings.get("kl", {}))
sample_ids = [ident for ident, cfg in configs.items() if cfg.get("role") != "背景"]
groups = list(dict.fromkeys(configs[ident].get("group", "") for ident in sample_ids))
if not groups:
    st.info("请先载入样品文件。")
    st.stop()
saved_group = params.get("group")
group = st.selectbox("实验组", groups, index=groups.index(saved_group) if saved_group in groups else 0,
                     key=f"kl_group_{workspace}", persist_state="session")
options = [ident for ident in sample_ids if configs[ident].get("group", "") == group]
defaults = [ident for ident in params.get("selected", options) if ident in options] if saved_group == group else options
selected = st.multiselect("参与拟合的文件（每个转速一条）", options, default=defaults,
                          format_func=file_formatter(), key=f"kl_files_{group}_{workspace}", persist_state="session")
if selected:
    common_parameter_form(purpose="kl", ids=selected, channels="disk")
apply_settings_button(key=f"kl_apply_settings_{workspace}")

# Common edits staged in this run are reflected in the selected-file preview.
configs, settings = get_draft_configs(), get_draft_settings()
outputs, errors = process_selected(selected, configs=configs, settings=settings, channels="disk")
show_errors(errors)
if len(selected) < 2:
    clear_kl()
    st.info("请把至少两个不同转速文件设置为同一组，并在上方选择。")
    st.stop()
with st.expander("核对实际参与计算的文件参数"):
    st.dataframe([{
        "文件": st.session_state.traces[ident].name,
        "转速 / rpm": configs[ident].get("rpm"), "盘面积 / cm²": configs[ident].get("area_cm2"),
        "pH": configs[ident].get("pH"), "温度 / °C": configs[ident].get("temperature_C"),
        "电解液": configs[ident].get("electrolyte", ""), "电位坐标": settings.get("axis", "RHE"),
        "扫描方向": outputs[ident]["segment"]["direction"] if ident in outputs else configs[ident].get("direction"),
        "处理状态": "可预览" if ident in outputs else "需要修正",
    } for ident in selected], hide_index=True)
    st.caption(("草稿预览，尚未应用。" if has_draft() else "以上是已应用参数。")+
               "5 mm 盘对应约 0.19635 cm²；转速填 rpm，程序自动换算为 rad/s。")

low = max((float(o["data"].E_V.min()) for o in outputs.values()), default=None)
high = min((float(o["data"].E_V.max()) for o in outputs.values()), default=None)
if len(selected) == 2:
    st.caption("只有两个转速：可以求斜率，但不报告有意义的 R² 或斜率标准误。")
scheme = st.selectbox("电解液参数方案 *", ["自定义", "O₂ 饱和 0.1 M KOH · 25 °C（文献近似值）"],
                      index=1 if params.get("scheme") == "koh_25C" else 0,
                      key=f"kl_scheme_{workspace}", persist_state="session")
use_preset = scheme != "自定义"
if use_preset:
    C, D, nu, source = (KOH_PRESET[key] for key in ("C", "D", "nu", "source"))
    st.caption("仅适用于 O₂ 饱和 0.1 M KOH、25 °C。C=1.2×10⁻⁶ mol/cm³；D=1.9×10⁻⁵ cm²/s；ν=0.01 cm²/s。[文献来源]("+KOH_PRESET["source"]+")。不能自动套用于 Na 电解液。")
else:
    a, b, c = st.columns(3)
    with a:
        C = st.number_input("氧浓度 C / mol·cm⁻³ *", value=params.get("C"), min_value=1e-12,
            format="%.8e", step=1e-7, key=f"kl_custom_C_{workspace}", persist_state="session",
            help="填写溶解氧浓度，不是电解液浓度。若来源单位为 mol/L，需除以 1000 后填入。")
    with b:
        D = st.number_input("扩散系数 D / cm²·s⁻¹ *", value=params.get("D"), min_value=1e-12,
            format="%.8e", step=1e-6, key=f"kl_custom_D_{workspace}", persist_state="session",
            help="若来源单位为 m²/s，需乘以 10000 后填入。请使用实际电解液和温度下的氧扩散系数。")
    with c:
        nu = st.number_input("运动黏度 ν / cm²·s⁻¹ *", value=params.get("nu"), min_value=1e-12,
            format="%.8e", step=.001, key=f"kl_custom_nu_{workspace}", persist_state="session",
            help="需要运动黏度，不是动力黏度。若来源单位为 m²/s，需乘以 10000；若为 cSt，需乘以 0.01。")
    source = st.text_input("参数来源与适用条件（选填记录）", value=params.get("source", ""),
        placeholder="文献 DOI 或测定记录，包括温度、电解液、氧饱和情况", key=f"kl_custom_source_{workspace}", persist_state="session")
with st.expander("分析区间与点数（请核对）", expanded=True):
    if low is not None and high is not None:
        st.caption(f"共同覆盖预览：{low:.5f} ～ {high:.5f} V（{settings.get('axis', 'RHE')}）。"+
                   ("仍有选中文件未处理，计算时将重新核对全部文件。" if errors else ""))
    st.caption("初始范围只表示数据覆盖，并未识别 ORR 适用区间。避开电流过小、反向及其他反应区；不要以 n 是否落在 2–4 内反推区间。")
    a, b, c = st.columns(3)
    with a:
        start = st.number_input("分析起点 / V", value=params.get("start", low), format="%.5f",
                                key=f"kl_start_{workspace}", persist_state="session")
    with b:
        end = st.number_input("分析终点 / V", value=params.get("end", high), format="%.5f",
                              key=f"kl_end_{workspace}", persist_state="session")
    with c:
        count = st.number_input("等间距电位点数", min_value=1, max_value=500,
                                value=int(params.get("count", 30)), step=1,
                                key=f"kl_count_{workspace}", persist_state="session")
confirmed = st.checkbox("已核对：各文件属于同一电极和相同实验条件，以上物性参数适用",
                        key=f"kl_confirmed_{workspace}", persist_state="session")
current_inputs = dict(C=C, D=D, nu=nu, source=source, start=start, end=end, count=count,
                      selected=list(selected), group=group, confirmed=confirmed,
                      scheme="koh_25C" if use_preset else "custom")
signature = json_bytes(current_inputs)
saved = st.session_state.results.get("kl")
if saved and (saved.get("input_signature") != signature or saved.get("revision") != st.session_state.revision):
    clear_kl()
    st.info("分析输入已修改，请重新计算。")


def compute_current():
    clear_kl()
    candidate_configs, candidate_settings = pending_candidate()
    if not confirmed:
        raise DataError("请先核对实验条件和物性参数。")
    chosen, failures = process_selected(selected, configs=candidate_configs, settings=candidate_settings,
                                        channels="disk")
    if failures or len(chosen) != len(selected):
        detail = "；".join(f"{row['文件']}：{row['原因']}" for row in failures)
        raise DataError("K–L 必须使用全部选中文件，不能跳过某个转速。"+detail)
    actual_low = max(float(o["data"].E_V.min()) for o in chosen.values())
    actual_high = min(float(o["data"].E_V.max()) for o in chosen.values())
    if actual_low >= actual_high:
        raise DataError("这些曲线没有共同电位区间。")
    if start is None or end is None or not np.isfinite([start, end]).all():
        raise DataError("请填写有限的分析起点和终点。")
    if start > end or start < actual_low-1e-9 or end > actual_high+1e-9:
        raise DataError("分析区间应位于全部选中文件的共同覆盖范围内，且起点不能大于终点。")
    if isinstance(count, bool) or int(count) != count or not 1 <= count <= 500:
        raise DataError("分析点数应为 1–500 的整数。")
    if count > 1 and start == end:
        raise DataError("分析单个电位请把点数设为 1。")
    if use_preset and any(o["config"].get("temperature_C") is None or
                          abs(float(o["config"]["temperature_C"])-25.) > 1e-8 for o in chosen.values()):
        raise DataError("所选文献方案仅限 25 °C，请修正实验温度或选择自定义物性参数。")
    potentials = np.linspace(start, end, int(count)) if count > 1 else np.array([start])
    result, points = kl_calculate(list(chosen.values()), potentials, C, D, nu)
    used = deepcopy(candidate_settings.get("kl", {}))
    used.update({key: value for key, value in current_inputs.items() if key != "confirmed"})
    used.update(axis=candidate_settings.get("axis", "RHE"),
        units={"C": "mol/cm³", "D": "cm²/s", "nu": "cm²/s", "current_density": "A/cm²",
               "rotation_input": "rpm", "rotation_fit": "rad/s"},
        condition=KOH_PRESET["electrolyte"] if use_preset else "用户自定义")
    apply_pending_settings()
    st.session_state.settings["kl"] = deepcopy(used)
    saved_result = dict(data=result, points=points, selected=list(selected), params=used,
                        outputs=chosen, revision=st.session_state.revision, input_signature=signature)
    st.session_state.results["kl"] = saved_result
    store_table("kl_results.csv", result)
    store_table("kl_fit_points.csv", points)
    return saved_result


if st.button("应用并计算 K–L" if has_draft() else "计算 K–L", type="primary", key=f"kl_calculate_{workspace}"):
    try:
        compute_current()
    except (DataError, ValueError, TypeError, IndexError) as exc:
        st.error(str(exc))


def plot_table(saved_result):
    axis = "RHE" if all(effective_axis(o)=="RHE" for o in saved_result["outputs"].values()) else saved_result["params"]["axis"]
    column = "E_RHE_V" if axis == "RHE" else "E_original_reference_V"
    return saved_result["data"][["E_V", "n_KL", "two_e_pct_model", "four_e_pct_model"]].rename(columns={"E_V": column})


def prepare_download():
    result = compute_current()
    return csv_bytes(plot_table(result)), "kl_plot.csv", "text/csv"


saved = st.session_state.results.get("kl")
figures, extras, plot_payload = [], [], None
if saved:
    result, points, used, chosen = saved["data"], saved["points"], saved["params"], saved["outputs"]
    if has_draft():
        st.warning("下方是已应用设置的计算结果。草稿尚未应用；导出绘图 CSV 将先应用并重新计算。")
    st.caption(f"结果修订 {saved['revision']}：C={used['C']:.6g} mol/cm³，D={used['D']:.6g} cm²/s，ν={used['nu']:.6g} cm²/s；{used['start']:.5f} ～ {used['end']:.5f} V（{used['axis']}）。")
    invalid_count = int((~result.valid_two_path_model).sum())
    if invalid_count:
        st.warning(f"{len(result)} 个电位中有 {invalid_count} 个不满足两路径模型检查。电流过小或反向、斜率非正、负截距、n 超出 2–4 均需核对；数值保留，异常模型比例不可作为有效选择性。")
    figure_style()
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    ax.plot(result.E_V, result.n_KL, color="#167D8D", marker="o", ms=3)
    ax.axhline(2, color="#B5BDC1", ls="--", lw=.8)
    ax.axhline(4, color="#B5BDC1", ls="--", lw=.8)
    ax.set(xlabel=axis_label(chosen), ylabel="Apparent electron number n", title="Koutecky–Levich analysis")
    offer_figure(fig, "kl_electron_number")
    figures.append("kl_electron_number")
    fig, ax = plt.subplots(figsize=(8, 4.5), layout="constrained")
    ax.plot(result.E_V, result.two_e_pct_model, color="#167D8D", label="2e (model)")
    ax.plot(result.E_V, result.four_e_pct_model, color="#D66A3C", label="4e (model)")
    ax.set(xlabel=axis_label(chosen), ylabel="Selectivity estimate / %", title="K–L two-path model estimate")
    ax.legend(frameon=False)
    offer_figure(fig, "kl_two_four_e_model")
    figures.append("kl_two_four_e_model")
    if not points.empty:
        available = sorted(points.E_V.unique())
        potential = st.select_slider("查看某个电位的拟合", options=available,
            value=available[len(available)//2], format_func=lambda value: f"{value:.4f} V")
        fit = points[points.E_V == potential].sort_values("omega_inv_sqrt")
        fig, ax = plt.subplots(figsize=(7, 4), layout="constrained")
        ax.scatter(fit.omega_inv_sqrt, fit.inverse_j_cm2_A, color="#167D8D", label="Data")
        ax.plot(fit.omega_inv_sqrt, fit.fit_inverse_j_cm2_A, color="#D66A3C", label="Linear fit")
        ax.set(xlabel="ω$^{-1/2}$ / (rad s$^{-1}$)$^{-1/2}$", ylabel="1/j / cm$^2$ A$^{-1}$", title=f"K–L fit at {potential:.4f} V")
        ax.legend(frameon=False)
        offer_figure(fig, "kl_fit")
        figures.append("kl_fit")
    plot_payload = csv_bytes(plot_table(saved))
    extras = [
        ("完整数据 CSV · K–L 结果与异常状态", "kl_results.csv", csv_bytes(result), "text/csv"),
        ("Origin 拟合绘图 CSV · 各电位独立 XY 与拟合值", "kl_fit_plot.csv", csv_bytes(kl_fit_plot_table(points, "RHE" if all(effective_axis(o)=="RHE" for o in chosen.values()) else used["axis"])), "text/csv"),
        ("完整拟合点 CSV · 长表", "kl_fit_points.csv", csv_bytes(points), "text/csv"),
        ("参数 JSON", "kl_parameters.json", json_bytes(used), "application/json"),
    ]
    with st.expander("完整结果与异常状态"):
        st.dataframe(result, hide_index=True)
    show_notes(chosen)
st.caption("绘图 CSV 含共用电位、电子数及两路径模型比例；更多导出保留每个分析电位的独立 XY 拟合表和完整长表。")
result_downloads(plot_payload, "kl_plot.csv", figures=figures, extras=extras,
                 key=f"kl_download_{workspace}", prepare=prepare_download)

