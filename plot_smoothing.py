"""Display-only smoothing; never replace the currents used by electrochemical models."""
from __future__ import annotations

import numpy as np
import pandas as pd
import scipy
from scipy.signal import savgol_filter

from orr_core import DataError

PRESET_WINDOWS = {"弱": 11, "中": 21, "强": 51}
SMOOTH_A = "I_disk_smoothed_plot_only_A"
SMOOTH_MA = "I_disk_smoothed_plot_only_mA"
SMOOTH_DENSITY = "j_disk_smoothed_plot_only_mA_cm2"
SPACING_RTOL = .01
SPACING_ATOL_V = 1e-9


def smoothing_defaults(settings=None):
    result = dict(enabled=False, preset="弱", window_points=11, custom_window=11,
                  show_unsmoothed=True, algorithm="Savitzky–Golay", polyorder=2,
                  mode="interp", scope="polarization_plot_only")
    if settings:
        result.update(settings)
    return result


def smooth_for_plot(frame: pd.DataFrame, settings: dict):
    """Return a copy and an auditable report, leaving every existing column unchanged.

    No interpolation, gap filling, current clipping or electrochemical recalculation.
    SG is applied only within finite, sufficiently long, uniformly spaced runs.
    """
    cfg = smoothing_defaults(settings)
    output = frame.copy(deep=True)
    report = dict(enabled=bool(cfg["enabled"]), scope="polarization_plot_only",
                  algorithm="Savitzky–Golay", polyorder=2, mode="interp",
                  scipy_version=scipy.__version__, window_points=cfg["window_points"],
                  spacing_rtol=SPACING_RTOL, spacing_atol_V=SPACING_ATOL_V,
                  applied_points=0, preserved_points=0, gap_points=0,
                  segments=[], notes=[], status="disabled")
    if not cfg["enabled"]:
        return output, report
    window = cfg["window_points"]
    if isinstance(window, bool) or not isinstance(window, (int, np.integer)) or not 5 <= window <= 1001 or window % 2 != 1:
        raise DataError("平滑窗口应为 5–1001 的奇数点数；不会自动更改你的参数。")
    window = int(window)
    if "E_V" not in frame or "I_disk_A" not in frame:
        raise DataError("绘图平滑需要已处理的电位与盘电流列。")
    x = frame.E_V.to_numpy(dtype=float)
    y = frame.I_disk_A.to_numpy(dtype=float)
    finite = np.isfinite(x) & np.isfinite(y)
    smoothed = y.copy()
    smoothed[~finite] = np.nan
    statuses = np.full(len(y), "缺口：电位或电流无效", dtype=object)
    starts = np.flatnonzero(np.diff(np.r_[False, finite, False].astype(int)) == 1)
    ends = np.flatnonzero(np.diff(np.r_[False, finite, False].astype(int)) == -1)
    report["gap_points"] = int((~finite).sum())
    for start, end in zip(starts, ends):
        count = int(end-start)
        dx = np.diff(x[start:end])
        spacing = float(np.median(np.abs(dx))) if len(dx) else None
        monotone = bool(len(dx) and (np.all(dx > 0) or np.all(dx < 0)))
        uniform = bool(monotone and spacing is not None and spacing > 0 and
                       np.allclose(np.abs(dx), spacing, rtol=SPACING_RTOL, atol=SPACING_ATOL_V))
        segment = dict(start_index=int(start), end_index_exclusive=int(end), points=count,
                       spacing_mV=spacing*1000 if spacing is not None else None,
                       requested_window_span_mV=spacing*(window-1)*1000 if spacing is not None else None,
                       applied=False)
        if count < window:
            reason = f"未平滑：连续段只有 {count} 点，小于 {window} 点窗口"
        elif not uniform:
            reason = "未平滑：电位不等间距、重复或非单调；未重采样"
        else:
            smoothed[start:end] = savgol_filter(y[start:end], window_length=window,
                                               polyorder=2, deriv=0, mode="interp")
            reason = "已平滑：仅绘图"
            segment["applied"] = True
            report["applied_points"] += count
        statuses[start:end] = reason
        segment["status"] = reason
        report["segments"].append(segment)
        if not segment["applied"]:
            report["notes"].append(reason)
            report["preserved_points"] += count
    if report["gap_points"]:
        report["notes"].append(f"保留 {report['gap_points']} 个缺口点，未跨缺口平滑。")
    if report["applied_points"] == 0:
        report["status"] = "skipped"
    elif report["preserved_points"] or report["gap_points"]:
        report["status"] = "partial"
    else:
        report["status"] = "applied"
    report["notes"] = list(dict.fromkeys(report["notes"]))
    output[SMOOTH_A] = smoothed
    output[SMOOTH_MA] = smoothed*1000
    if "j_disk_mA_cm2" in frame:
        # Retain the exact same normalization factor as the processed source column.
        j = frame.j_disk_mA_cm2.to_numpy(dtype=float)
        factors = np.divide(j, y, out=np.full(len(y), np.nan), where=finite & (y != 0))
        available = factors[np.isfinite(factors)]
        if len(available):
            output[SMOOTH_DENSITY] = smoothed * float(np.median(available))
        else:
            output[SMOOTH_DENSITY] = j.copy()  # all-zero current remains exactly zero
        output.loc[~finite, SMOOTH_DENSITY] = np.nan
    output["smoothing_plot_status"] = statuses
    return output, report
