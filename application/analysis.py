"""Analysis transactions shared by browser and desktop; formulas live in orr_core."""
from copy import deepcopy
import numpy as np
import pandas as pd
from orr_core import (DataError, KOH_PRESET, json_bytes, kl_calculate,
                      parameter_record, require_number, rrde_calculate)
from origin_export import rrde_plot_table


def clear_result(workspace, kind):
    workspace.state.results.pop(kind, None)
    for name in list(workspace.state.exports):
        if name.startswith(kind + "_"):
            workspace.state.exports.pop(name)


def calculate_rrde(workspace, selected):
    clear_result(workspace, "rrde")
    configs, settings = workspace.pending_candidate()
    floor = settings.get("rrde", {}).get("floor_A", 1e-9)
    require_number(floor, "最小盘电流幅值（A）", positive=True)
    current_inputs = dict(floor_A=floor, selected=list(selected))
    processed, failures = workspace.process_selected(selected, configs, settings)
    results, chosen = {}, {}
    for ident, output in processed.items():
        try:
            results[ident] = rrde_calculate(output, output["config"], floor)
            chosen[ident] = output
        except (DataError, ValueError, TypeError, IndexError) as exc:
            failures.append({"文件": output["name"], "原因": str(exc)})
    if not results:
        raise DataError("选中文件没有可计算的 RRDE 结果。" + "；".join(
            f"{row['文件']}：{row['原因']}" for row in failures))
    frames = []
    for ident, frame in results.items():
        export = frame.copy()
        for index, (name, value) in enumerate((("file_id", ident), ("filename", chosen[ident]["name"]),
                ("potential_axis", chosen[ident]["axis"]), ("rpm", chosen[ident]["config"].get("rpm")),
                ("rpm_source", chosen[ident]["config"].get("rpm_source")))):
            export.insert(index, name, value)
        frames.append(export)
    merged = pd.concat(frames, ignore_index=True)
    wide = rrde_plot_table(results, chosen)
    used = deepcopy(settings.get("rrde", {}))
    used.update(current_inputs, axis=settings.get("axis", "RHE"))
    workspace.apply_pending_settings()
    workspace.state.settings["rrde"] = deepcopy(used)
    saved = dict(data=merged, frames=results, outputs=chosen, selected=list(selected),
                 params=parameter_record(workspace.state.traces, workspace.state.configs,
                     workspace.state.settings, chosen), inputs=used, errors=failures, plot=wide,
                 revision=workspace.state.revision, input_signature=json_bytes(current_inputs))
    workspace.state.results["rrde"] = saved
    workspace.store_table("rrde_results.csv", merged)
    return saved


def calculate_kl(workspace, inputs):
    clear_result(workspace, "kl")
    configs, settings = workspace.pending_candidate()
    if not inputs.get("confirmed"):
        raise DataError("请先核对实验条件和物性参数。")
    selected = list(inputs.get("selected", []))
    chosen, failures = workspace.process_selected(selected, configs, settings, channels="disk")
    if failures or len(chosen) != len(selected):
        raise DataError("K–L 必须使用全部选中文件，不能跳过某个转速。" + "；".join(
            f"{row['文件']}：{row['原因']}" for row in failures))
    if not chosen:
        raise DataError("请至少选择三个不同转速的文件。")
    low = max(float(o["data"].E_V.min()) for o in chosen.values())
    high = min(float(o["data"].E_V.max()) for o in chosen.values())
    if low >= high:
        raise DataError("这些曲线没有共同电位区间。")
    start, end, count = (inputs.get(k) for k in ("start", "end", "count"))
    if start is None or end is None or not np.isfinite([start, end]).all():
        raise DataError("请填写有限的分析起点和终点。")
    if start > end or start < low - 1e-9 or end > high + 1e-9:
        raise DataError("分析区间应位于全部选中文件的共同覆盖范围内，且起点不能大于终点。")
    if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) != count or not 1 <= count <= 500:
        raise DataError("分析点数应为 1–500 的整数。")
    if count > 1 and start == end:
        raise DataError("分析单个电位请把点数设为 1。")
    preset = inputs.get("scheme") == "koh_25C"
    if preset and any(o["config"].get("temperature_C") is None or
                     abs(float(o["config"]["temperature_C"]) - 25.) > 1e-8 for o in chosen.values()):
        raise DataError("所选文献方案仅限 25 °C，请修正实验温度或选择自定义物性参数。")
    potentials = np.linspace(start, end, int(count)) if count > 1 else np.array([start])
    result, points = kl_calculate(list(chosen.values()), potentials, *(inputs.get(k) for k in ("C", "D", "nu")))
    used = deepcopy(settings.get("kl", {}))
    used.update({k: v for k, v in inputs.items() if k != "confirmed"})
    used.update(axis=settings.get("axis", "RHE"),
        units={"C":"mol/cm³", "D":"cm²/s", "nu":"cm²/s", "current_density":"A/cm²",
               "rotation_input":"rpm", "rotation_fit":"rad/s"},
        condition=KOH_PRESET["electrolyte"] if preset else "用户自定义")
    workspace.apply_pending_settings()
    workspace.state.settings["kl"] = deepcopy(used)
    saved = dict(data=result, points=points, selected=selected, params=used, outputs=chosen,
                 revision=workspace.state.revision, input_signature=json_bytes(inputs))
    workspace.state.results["kl"] = saved
    workspace.store_table("kl_results.csv", result)
    workspace.store_table("kl_fit_points.csv", points)
    return saved
