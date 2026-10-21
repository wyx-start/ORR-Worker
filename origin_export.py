"""Numeric CSV tables for Origin, without aligning or resampling sample grids.

These helpers only copy already-produced plotting/calculation values.  They do
not process currents, interpolate, smooth, clip, or change scientific results.
"""
from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd


def csv_bytes(frame: pd.DataFrame) -> bytes:
    """Write a numeric table with one header row, full float precision and BOM."""
    return frame.to_csv(index=False, na_rep="", float_format="%.17g",
                        lineterminator="\n").encode("utf-8-sig")


def _clean_label(value: object) -> str:
    return " ".join(str(value).replace("\x00", "").split()) or "sample"


def _short_ids(idents: list[object]) -> dict[object, str]:
    """Extend colliding ID prefixes deterministically, independent of order."""
    full = {ident: _clean_label(ident) for ident in idents}
    short = {}
    for ident, value in full.items():
        length = min(8, len(value))
        while length < len(value) and any(
                other != ident and full[other][:length] == value[:length]
                for other in full):
            length += 1
        short[ident] = value[:length]
    return short


def _column_name(base: str, used: set[str]) -> str:
    candidate = base
    count = 2
    while candidate in used:
        candidate = f"{base}__{count}"
        count += 1
    used.add(candidate)
    return candidate


def _sample_prefix(ident: object, output: Mapping, short_ids: Mapping) -> str:
    config = output.get("config", {})
    name = config.get("name") or output.get("name") or "sample"
    return f"{_clean_label(name)}__{short_ids[ident]}"


def _axis_variable(axis: object) -> str:
    if axis is None or not str(axis).strip():
        raise ValueError("绘图 CSV 缺少电位坐标记录。")
    if axis == "RHE":
        return "E_RHE_V"
    if axis == "原始":
        # This can include applied iR correction, so do not call it the file's
        # original potential (E_original_V in the complete processing table).
        return "E_original_reference_V"
    return f"E_{_clean_label(axis)}_V"


def effective_axis(output: Mapping) -> str:
    """The requested original view can already be an RHE identity coordinate."""
    return "RHE" if output.get("axis")=="RHE" or output.get("config",{}).get("potential_method")=="已是 RHE" else output.get("axis")


def _numeric(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        raise ValueError(f"绘图 CSV 缺少数据列：{column}。")
    try:
        values = pd.to_numeric(frame[column], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"绘图 CSV 的 {column} 列不是数值。") from exc
    # Source indexes may describe original acquisition rows, and can overlap
    # between samples.  Only positional alignment is meaningful for a wide CSV.
    return values.reset_index(drop=True).copy(deep=True)


def _metadata(output: Mapping, frame: pd.DataFrame, name: str,
              default: object = None) -> object:
    present = name in output and output[name] is not None
    value = output[name] if present else default
    if name in frame:
        recorded = frame[name].dropna()
        if not recorded.empty:
            first = recorded.iloc[0]
            if not bool(recorded.eq(first).all()):
                raise ValueError(f"绘图 CSV 的 {name} 记录不一致。")
            if present and value != first:
                raise ValueError(f"绘图 CSV 的 {name} 与当前图记录不一致。")
            value = first
    return value


def _curve_y_variable(output: Mapping, frame: pd.DataFrame) -> str:
    channel = _metadata(output, frame, "plot_channel")
    if channel not in ("disk", "ring"):
        raise ValueError("绘图 CSV 需要明确当前盘／环通道。")
    unit = _metadata(output, frame, "plotted_current_unit")
    unit_aliases = {"A": "A", "mA": "mA", "uA": "uA", "μA": "uA",
                    "µA": "uA", "mA/cm2": "mA_cm2", "mA/cm²": "mA_cm2",
                    "mA_cm2": "mA_cm2"}
    if unit not in unit_aliases:
        raise ValueError("绘图 CSV 的当前电流单位无效或未记录。")
    suffix = unit_aliases[unit]
    if suffix == "mA_cm2" and channel != "disk":
        raise ValueError("环电流绘图 CSV 不支持盘面积归一化单位。")
    smooth = _metadata(output, frame, "plot_smoothing_enabled", False)
    if not isinstance(smooth, (bool, np.bool_)):
        raise ValueError("绘图 CSV 的平滑开关记录必须为布尔值。")
    variable = "j_disk" if suffix == "mA_cm2" else f"I_{channel}"
    if smooth:
        variable += "_smoothed_plot_only"
    return f"{variable}_{suffix}"


def _assemble(columns: list[pd.Series]) -> pd.DataFrame:
    return pd.concat(columns, axis=1) if columns else pd.DataFrame()


def curve_plot_table(outputs: Mapping) -> pd.DataFrame:
    """Return independent E/current pairs in the selected sample order.

    Each output must contain ``data`` with ``E_V``,
    ``plotted_current_value`` and a constant ``plotted_current_unit`` column.
    ``plot_channel`` (disk/ring), ``plot_smoothing_enabled`` (bool) and ``axis``
    are output metadata; the first two may alternatively be constant data columns.
    The exact plotted values are exported, including display-only smoothing and
    gaps.  The complete-data CSV remains the place for all processing columns.
    """
    columns, used = [], set()
    short_ids = _short_ids(list(outputs))
    for ident, output in outputs.items():
        frame = output["data"]
        prefix = _sample_prefix(ident, output, short_ids)
        for source, variable in (("E_V", _axis_variable(effective_axis(output))),
                                 ("plotted_current_value", _curve_y_variable(output, frame))):
            series = _numeric(frame, source)
            series.name = _column_name(f"{prefix}__{variable}", used)
            columns.append(series)
    return _assemble(columns)


def rrde_plot_table(results: Mapping, outputs: Mapping) -> pd.DataFrame:
    """Return per-sample E, peroxide %, n and model 4e % without changing values."""
    columns, used = [], set()
    short_ids = _short_ids(list(results))
    for ident, frame in results.items():
        if ident not in outputs:
            raise ValueError("RRDE 绘图 CSV 缺少样品的处理记录。")
        output = outputs[ident]
        prefix = _sample_prefix(ident, output, short_ids)
        variables = (("E_V", _axis_variable(effective_axis(output))),
                     ("peroxide_pct", "peroxide_pct"),
                     ("n_RRDE", "n_RRDE"),
                     ("four_e_pct_model", "four_e_pct_model"))
        for source, variable in variables:
            series = _numeric(frame, source)
            series.name = _column_name(f"{prefix}__{variable}", used)
            columns.append(series)
    return _assemble(columns)


def kl_fit_plot_table(points: pd.DataFrame, axis: str) -> pd.DataFrame:
    """Return one independent X/Y/Yfit column group per existing K–L potential.

    This consumes calculation fit points verbatim; it never derives new fit
    points from currents, changes point order, or interpolates potential grids.
    """
    axis_variable = _axis_variable(axis)
    if points.empty:
        return pd.DataFrame()
    potentials = _numeric(points, "E_V")
    if not bool(np.isfinite(potentials.to_numpy(dtype=float)).all()):
        raise ValueError("K–L 拟合点缺少有效的分析电位。")
    columns, used = [], set()
    for potential in pd.unique(potentials):
        selected = points.loc[points["E_V"].eq(potential)]
        prefix = f"{axis_variable}={repr(float(potential))}"
        for source in ("omega_inv_sqrt", "inverse_j_cm2_A", "fit_inverse_j_cm2_A"):
            series = _numeric(selected, source)
            variable = "omega_inv_sqrt_rad_s" if source == "omega_inv_sqrt" else source
            series.name = _column_name(f"{prefix}__{variable}", used)
            columns.append(series)
    return _assemble(columns)
