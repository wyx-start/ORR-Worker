"""Pure numerical and file-processing functions. Currents are always stored in A."""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import re
import zipfile

from background_ph import default_ph_link, ph_link_error, resolved_configs

import numpy as np
import pandas as pd

VERSION = "1.4.0"
FARADAY = 96485.33212
GAS_CONSTANT = 8.314462618
SOURCES = {
    "rrde": "https://www.nature.com/articles/s41467-022-30411-7",
    "kl_limits": "https://pubs.acs.org/doi/10.1021/acscatal.6b01581",
    "koh_25C": "https://www.nature.com/articles/s41467-024-50377-y",
    "reference": "https://www.gamry.com/resources-2/electrochemical-calculators-tools/convert-potentials-to-another-reference-electrode/",
    "rhe_calibration": "https://www.nature.com/articles/s41467-026-76426-2",
    "plot_smoothing": "https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.savgol_filter.html",
}
KOH_PRESET = {"electrolyte": "O2 饱和 0.1 M KOH，25 °C（文献近似值）", "C": 1.2e-6, "D": 1.9e-5, "nu": 0.01, "source": SOURCES["koh_25C"]}


class DataError(ValueError):
    pass


@dataclass
class Trace:
    name: str
    raw: bytes
    header: dict
    columns: list[str]
    values: np.ndarray
    encoding: str
    warnings: list[str]

    @property
    def id(self):
        return hashlib.sha256(self.name.encode("utf-8") + b"\0" + self.raw).hexdigest()[:16]

    @property
    def sha256(self):
        return hashlib.sha256(self.raw).hexdigest()


def parse_chi(name: str, raw: bytes) -> Trace:
    if len(raw) > 50_000_000:
        raise DataError("文件超过 50 MB，请分批处理。")
    text = None
    encoding = ""
    for encoding in ("utf-8-sig", "gb18030", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            pass
    if text is None or "\x00" in text:
        raise DataError("无法读取为文本。请在辰华软件中导出 TXT，勿直接上传二进制文件。")
    lines = text.splitlines()
    column_row = None
    for k, line in enumerate(lines):
        parts = [v.strip() for v in re.split(r"[,\t]", line)]
        if len(parts) >= 2 and re.match(r"^Potential\s*/", parts[0], re.I):
            column_row = k
            columns = parts
            break
    if column_row is None:
        raise DataError("找不到 Potential/V 数据列；请上传带完整表头的辰华 CV/LSV 文本。")
    factors = []
    for k, col in enumerate(columns):
        unit = col.rsplit("/", 1)[-1].strip().replace("μ", "u").replace("µ", "u")
        allowed = {"V": 1., "mV": .001} if k == 0 else {"A": 1., "mA": .001, "uA": 1e-6, "nA": 1e-9}
        if unit not in allowed:
            raise DataError(f"不支持或不明确的列单位：{col}")
        factors.append(allowed[unit])
    rows = []
    for k, line in enumerate(lines[column_row + 1:], column_row + 2):
        if not line.strip():
            continue
        cells = re.split(r"[,\t]", line.strip())
        if len(cells) != len(columns):
            raise DataError(f"第 {k} 行列数不一致；未静默丢弃数据。")
        try:
            row = [float(v) for v in cells]
        except ValueError as exc:
            raise DataError(f"第 {k} 行含非数字数据。") from exc
        if not all(math.isfinite(v) for v in row):
            raise DataError(f"第 {k} 行含缺失或非有限数值。")
        rows.append(row)
    if len(rows) < 3:
        raise DataError("有效数据点不足。")
    header = {}
    for line in lines[:column_row]:
        if "=" in line:
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            try:
                header[key] = float(value)
            except ValueError:
                header[key] = value
    header["raw_text"] = "\n".join(lines[:column_row])
    header["technique"] = next((s.strip() for s in lines[:column_row] if "voltammetry" in s.lower()), "unknown")
    warnings = []
    if "Cyclic" not in header["technique"] and "Linear" not in header["technique"]:
        warnings.append("测试技术未确认；请检查原始表头。")
    if "Comp R (ohm)" in header:
        warnings.append(f"表头含 Comp R={header['Comp R (ohm)']:g} Ω、UC R={header.get('UC R (ohm)', '未知')} Ω；未自动追加 iR 校正。")
    return Trace(name, raw, header, columns, np.asarray(rows, dtype=float) * factors, encoding, warnings)


def scan_segments(trace: Trace, tolerance_steps=1.01) -> list[dict]:
    e = trace.values[:, 0]
    diff = np.diff(e)
    moving = np.abs(diff) > 1e-10
    if not np.any(moving):
        raise DataError("电位没有变化，无法识别扫描段。")
    observed_step = float(np.median(np.abs(diff[moving])))
    step = float(trace.header.get("Sample Interval (V)", observed_step))
    if not np.isfinite(step) or step <= 0:
        step = observed_step
    signs = np.sign(diff)
    signs[np.abs(diff) < min(step, observed_step) * .01] = 0
    # Holds at a reversal belong to the preceding leg; retain every original row.
    first = next((v for v in signs if v != 0), None)
    if first is None:
        raise DataError("未检测到有效扫描。")
    last = first
    for i in range(len(signs)):
        if signs[i] == 0:
            signs[i] = last
        last = signs[i]
    turns = (np.where(signs[1:] != signs[:-1])[0] + 1).tolist()
    bounds = [0] + turns + [len(e) - 1]
    declared = "Low E (V)" in trace.header and "High E (V)" in trace.header
    low = float(trace.header.get("Low E (V)", e.min()))
    high = float(trace.header.get("High E (V)", e.max()))
    if low >= high:
        raise DataError("扫描上、下限无效。")
    tolerance = step * tolerance_steps + 1e-9
    segments = []
    for index, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]), 1):
        direction = "递增" if e[b] > e[a] else "递减"
        start, end = (low, high) if direction == "递增" else (high, low)
        gap = max(abs(e[a] - start), abs(e[b] - end))
        monotone = np.all(np.diff(e[a:b+1]) >= -1e-10) if direction == "递增" else np.all(np.diff(e[a:b+1]) <= 1e-10)
        complete = bool(gap <= tolerance and monotone and b - a >= 2)
        segments.append(dict(segment=index, start=a, end=b, direction=direction,
                             start_V=float(e[a]), end_V=float(e[b]), points=b-a+1,
                             complete=complete, cycle=None, endpoint_gap_mV=gap*1000,
                             endpoints_from="表头" if declared else "数据极值（无法证明边界完整）"))
    cycle = 0
    i = 0
    while i < len(segments) - 1:
        a, b = segments[i], segments[i+1]
        if a["complete"] and b["complete"] and a["direction"] != b["direction"]:
            cycle += 1
            a["cycle"] = b["cycle"] = cycle
            i += 2
        else:
            i += 1
    return segments


def select_segment(trace: Trace, cfg: dict) -> dict:
    segments = scan_segments(trace)
    manual = cfg.get("manual_segment")
    if manual is not None:
        chosen = next((s for s in segments if s["segment"] == int(manual)), None)
        if chosen is None:
            raise DataError("手选扫描段不存在，请重新选择。")
        return chosen
    # Without programmed endpoints, do not certify the final observed extrema as complete.
    if "Low E (V)" not in trace.header or "High E (V)" not in trace.header:
        raise DataError("缺少程序电位上下限，无法可靠判定完整性；请预览后手选扫描段。")
    direction = cfg.get("direction", "递减")
    if cfg.get("mode", "A") == "A":
        cycles = [s["cycle"] for s in segments if s["cycle"] is not None]
        if not cycles:
            raise DataError("没有识别到完整循环；可切换 B 或手选扫描段。")
        candidates = [s for s in segments if s["cycle"] == max(cycles) and s["direction"] == direction]
    else:
        candidates = [s for s in segments if s["complete"] and s["direction"] == direction]
    if not candidates:
        raise DataError(f"没有完整的电位{direction}扫描段；请手选并检查数据。")
    return candidates[-1]


RPM_FIELDS = ("rpm", "rpm_source", "rpm_status", "rpm_matches", "rpm_candidates", "rpm_note")
RPM_SOURCE_LABELS = {
    "filename_explicit": "文件名明确标记", "filename_legacy": "末尾数字推测",
    "manual": "人工填写", "saved_project": "项目保存值（来源未记录）", "none": "未识别",
}


def rpm_source_label(config):
    status_labels = {"ambiguous":"冲突（待填写）", "invalid":"无效标记（待填写）", "unsupported":"不支持单位（待填写）"}
    return status_labels.get(config.get("rpm_status"),RPM_SOURCE_LABELS.get(config.get("rpm_source"),"未记录"))


def _filename_stem(name):
    # Windows and POSIX path components are not evidence of rotation speed.
    return Path(str(name).replace("\\", "/")).stem


def _group_without_matches(stem, matches):
    spans = []
    for item in sorted(matches, key=lambda m: (m["start"], m["end"])):
        a, b = item["start"], item["end"]
        if spans and a <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], b)
        else:
            spans.append([a, b])
    group, previous = [], 0
    for a, b in spans:
        group.append(stem[previous:a])
        previous = b
    group.append(stem[previous:])
    text = "".join(group)
    text = re.sub(r"\(\s*\)|（\s*）|\[\s*\]|【\s*】", "", text)
    text = re.sub(r"[-_\s]{2,}", lambda m: "_" if "_" in m[0] else ("-" if "-" in m[0] else " "), text)
    return text.strip("-_ \t") or "未命名样品"


def infer_rpm_from_name(name):
    """Infer rpm only from a basename. Explicit evidence wins; conflicts stay empty."""
    stem = _filename_stem(name)
    result = dict(rpm=None, rpm_source="none", rpm_status="unrecognized", rpm_matches=[],
                  rpm_candidates=[], rpm_note="文件名中未识别到转速，请手动填写。", group=stem)
    number = r"(?:\d+(?:\.\d+)?|\.\d+)"
    unit = r"(?:rpm(?![a-z])|转(?:\s*每\s*分钟)?(?![化换移速]))"
    suffix = re.compile(r"(?<![\d.])(?P<number>"+number+r")\s*"+unit, re.I)
    prefix = re.compile(r"(?:rpm|转速)\s*[=：:]?\s*(?P<number>[+-]?"+number+r")(?![\d.])(?:\s*"+unit+r")?", re.I)
    matches = []
    for kind, pattern in (("suffix", suffix), ("prefix", prefix)):
        for match in pattern.finditer(stem):
            start, end = match.span()
            token = match.group("number")
            # A hyphen next to a sample name is a separator (CoPc-1600rpm).
            # An isolated/assigned minus sign is an invalid negative value.
            number_start = match.start("number")
            if kind=="suffix" and number_start>0 and stem[number_start-1]=="-":
                before_minus = number_start-2
                if before_minus<0 or stem[before_minus] in "_ \t=：:([（【":
                    start = number_start-1
                    token = "-"+token
            matches.append(dict(text=stem[start:end], number=token, start=start, end=end, kind=kind))
    matches.sort(key=lambda m:(m["start"],m["end"],m["kind"]))
    if matches:
        values, invalid = set(), False
        for item in matches:
            if not re.fullmatch(r"\+?\d+", item["number"]):
                invalid = True
                continue
            try:
                value = int(item["number"])
                if not math.isfinite(float(value)):
                    invalid = True
                else:
                    values.add(value)
            except (ValueError, OverflowError):
                invalid = True
        result.update(rpm_matches=matches, rpm_candidates=sorted(values))
        if invalid:
            result.update(rpm_status="invalid", rpm_note="转速标记含小数、负数或过大数值；仅预填非负整数，请核对后手动填写。")
        elif len(values)>1:
            result.update(rpm_status="ambiguous", rpm_note="转速冲突，请手动填写。候选："+" / ".join(map(str,sorted(values)))+" rpm。")
        else:
            value = next(iter(values))
            result.update(rpm=float(value), rpm_source="filename_explicit", rpm_status="recognized",
                          rpm_note="由文件名明确转速标记预填，仍需核对。", group=_group_without_matches(stem,matches))
        return result
    if re.search(r"(?<![\d.])"+number+r"\s*rps(?![a-z])",stem,re.I):
        result.update(rpm_status="unsupported",rpm_note="发现 rps 单位，未自动换算为 rpm；请手动填写。")
        return result
    legacy = re.search(r"(?:^|[-_\s])(?P<number>\d{2,5})$",stem)
    if legacy:
        value = int(legacy.group("number"))
        evidence = dict(text=legacy.group("number"),number=legacy.group("number"),
                        start=legacy.start("number"),end=legacy.end("number"),kind="legacy")
        result.update(rpm=float(value),rpm_source="filename_legacy",rpm_status="inferred",
                      rpm_matches=[evidence],rpm_candidates=[value],
                      rpm_note="由末尾裸数字推测，可能是编号或短日期，请核对。",
                      group=_group_without_matches(stem,[evidence]))
    return result


def rpm_is_empty(value):
    return value is None or (isinstance(value,(float,np.floating)) and math.isnan(value))


def set_manual_rpm(config, value):
    """Record an actual edit without erasing automatic provenance on simple confirmation."""
    if rpm_is_empty(value):
        value = None
    else:
        if isinstance(value,bool):
            raise DataError("转速必须是非负数或空白。")
        value = require_number(value,"转速 rpm")
        if value<0:
            raise DataError("转速不能为负；静止测试可填写 0。")
    old = config.get("rpm")
    if (value is None and rpm_is_empty(old)) or old==value:
        return False
    config.update(rpm=value,rpm_source="manual",rpm_status="manual",
                  rpm_note="用户手动清空转速。" if value is None else "用户手动填写的转速，优先于文件名识别。")
    return True


def fill_missing_rpms(traces, configs):
    filled, unresolved = 0, []
    for ident,trace in traces.items():
        config = configs[ident]
        if not rpm_is_empty(config.get("rpm")):
            continue
        guess = infer_rpm_from_name(trace.name)
        for key in RPM_FIELDS:
            config[key] = guess[key]
        if guess["rpm"] is not None:
            filled += 1
        else:
            unresolved.append({"文件":trace.name,"原因":guess["rpm_note"]})
    return filled, unresolved


def default_config(trace: Trace) -> dict:
    stem = _filename_stem(trace.name)
    guess = infer_rpm_from_name(trace.name)
    role = "背景" if re.search(r"(?:^|[-_\s])(Ar|N2)(?:[-_\s]|$)|背景|beijing", stem, re.I) else ("RRDE" if len(trace.columns) >= 3 else "样品")
    return dict(name=stem, group=guess["group"], role=role, **{k:guess[k] for k in RPM_FIELDS},
                direction="递减", mode="A", manual_segment=None, disk_channel=0,
                ring_channel=1 if len(trace.columns) >= 3 else None,
                disk_sign=-1, ring_sign=1, **default_ph_link(), area_cm2=math.pi * (5. / 20.)**2,
                disk_diameter_mm=5., area_mode="diameter", collection_efficiency=None,
                parameter_sources={"area_cm2":"软件默认：5 mm RDE（用户指定）",
                                   "disk_diameter_mm":"软件默认：5 mm RDE（用户指定）",
                                   "temperature_C":"软件默认：25 °C",
                                   "potential_method":"软件默认：理论换算"},
                reference="未设置", filling="", potential_method="理论换算", ref_V_SHE=None,
                reference_source="用户输入", reference_preset_C=None,
                pH=None, temperature_C=25., rhe_offset_V=None, electrolyte="",
                background_disk=None, background_ring=None, background_reviewed=False,
                ir_enabled=False, ir_ohm=0., ir_confirmed=False,
                ring_potential_V=trace.header.get("2nd E (V)"), ring_material="",
                ring_detection_confirmed=False)


def require_number(value, label, positive=False):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise DataError(f"请填写{label}。") from exc
    if not math.isfinite(value) or (positive and value <= 0):
        raise DataError(f"{label}必须是{'大于零的' if positive else ''}有限数值。")
    return value


def rhe_shift(cfg):
    method = cfg.get("potential_method", "理论换算")
    if method == "已是 RHE":
        return 0.
    if method == "实测 RHE 总偏移":
        return require_number(cfg.get("rhe_offset_V"), "实测 RHE 总偏移（V）")
    ph = require_number(cfg.get("pH"), "pH")
    temp = require_number(cfg.get("temperature_C"), "温度（°C）")
    if temp <= -273.15:
        raise DataError("温度必须高于绝对零度。")
    if cfg.get("reference_preset_C") is not None and abs(temp-float(cfg["reference_preset_C"]))>1e-8:
        raise DataError("所选参比预设不适用于该温度，请输入对应温度的值或实测 RHE 总偏移。")
    ref = require_number(cfg.get("ref_V_SHE"), "该温度下参比相对 SHE 电位（V）")
    return ref + 2.302585093 * GAS_CONSTANT * (temp + 273.15) / FARADAY * ph


def potential_signature(cfg, axis):
    if axis == "RHE":
        return ("RHE",)
    if cfg.get("potential_method") == "已是 RHE":
        return ("RHE",)
    return ("原始", cfg.get("reference"), cfg.get("filling"), cfg.get("temperature_C"), cfg.get("ref_V_SHE"))


def base_curve(trace, cfg, axis="RHE", direction=None):
    selection_cfg = dict(cfg)
    if direction is not None:
        selection_cfg["direction"] = direction
    segment = select_segment(trace, selection_cfg)
    if direction is not None and segment["direction"] != direction:
        raise DataError("背景手选段与样品方向不同，请重新选段。")
    rows = trace.values[segment["start"]:segment["end"]+1]
    disk_channel = int(cfg.get("disk_channel", 0))
    if not 0 <= disk_channel < rows.shape[1] - 1:
        raise DataError("盘电流通道无效。")
    raw_disk = rows[:, disk_channel + 1]
    e = rows[:, 0].copy()
    if cfg.get("ir_enabled"):
        if not cfg.get("ir_confirmed"):
            raise DataError("启用 iR 前，请确认输入的是尚未补偿的电阻，且导出电位未做同一补偿。")
        resistance = require_number(cfg.get("ir_ohm"), "未补偿电阻（Ω）")
        if resistance < 0:
            raise DataError("未补偿电阻不能为负。")
        anodic_positive_current = raw_disk * (-int(cfg.get("disk_sign", -1)))
        e -= anodic_positive_current * resistance
    if axis == "RHE":
        e += rhe_shift(cfg)
    return rows, e, raw_disk, segment


def interpolate(x, y, target):
    x, y = np.asarray(x), np.asarray(y)
    dx = np.diff(x)
    if not (np.all(dx >= -1e-10) or np.all(dx <= 1e-10)):
        raise DataError("校正后电位非单调，不能可靠插值；请检查 iR 参数或手选扫描段。")
    frame = pd.DataFrame({"x": x, "y": y}).groupby("x", sort=True)["y"].mean()
    if len(frame) < 2:
        raise DataError("插值需要至少两个不同电位点。")
    return np.interp(target, frame.index.to_numpy(), frame.to_numpy(), left=np.nan, right=np.nan)


def process_trace(trace, cfg, traces, configs, axis="RHE"):
    configs = resolved_configs({**configs, trace.id:cfg}, {k:t.name for k,t in traces.items()})
    cfg = configs[trace.id]
    rows, e, disk, segment = base_curve(trace, cfg, axis)
    notes = list(trace.warnings)
    if cfg.get("manual_segment"):
        notes.append("采用人工指定扫描段；完整性由用户核对。")
    if segment["endpoint_gap_mV"] > 1e-5:
        notes.append(f"端点最大差 {segment['endpoint_gap_mV']:.4g} mV；完整性容许一个采样步，不补造端点。")
    if axis == "原始" and cfg.get("reference") == "未设置" and cfg.get("potential_method") != "已是 RHE":
        notes.append("原始参比身份未设置，当前横坐标仅为文件原始电位。")
    result = pd.DataFrame({"row_1based": np.arange(segment["start"]+1, segment["end"]+2),
                           "E_original_V": rows[:, 0], "E_V": e, "I_disk_raw_A": disk})
    ring_channel = cfg.get("ring_channel")
    ring = None
    if ring_channel is not None:
        ring_channel = int(ring_channel)
        if ring_channel == int(cfg.get("disk_channel", 0)) or not 0 <= ring_channel < rows.shape[1]-1:
            raise DataError("盘、环必须对应不同且有效的通道。")
        ring = rows[:, ring_channel+1]
        result["I_ring_raw_A"] = ring
    for label, current in (("disk", disk), ("ring", ring)):
        if current is None:
            continue
        bgid = cfg.get(f"background_{label}")
        if not bgid:
            result[f"I_{label}_background_A"] = 0.
            result[f"I_{label}_A"] = current
            notes.append(f"{'盘' if label == 'disk' else '环'}电流未扣背景。")
            continue
        if bgid not in traces or bgid == trace.id:
            raise DataError("背景文件不存在或错误地选择了自身。")
        bg, bgcfg = traces[bgid], configs[bgid]
        link_error = ph_link_error(bgcfg)
        if link_error:
            raise DataError(f"背景“{bg.name}”：{link_error}")
        if bgcfg.get("background_ph_detail"):
            notes.append(f"背景 {bg.name}：{bgcfg['background_ph_detail']}")
        if potential_signature(cfg, axis) != potential_signature(bgcfg, axis):
            raise DataError("样品与背景原始参比不一致；请统一换算到 RHE 后再扣除。")
        try:
            b_rows, b_e, _, b_seg = base_curve(bg, bgcfg, axis, direction=segment["direction"])
        except (DataError, ValueError, TypeError, IndexError) as exc:
            background_label = "盘背景" if label == "disk" else "环背景"
            raise DataError(f"{background_label}“{bg.name}”：{exc} 请检查该背景文件的已应用实验条件与扫描设置。") from exc
        channel = bgcfg.get(f"{label}_channel")
        if channel is None and b_rows.shape[1] == 2:
            channel = 0
        if channel is None:
            raise DataError("背景没有指定对应电流通道。")
        # Convert the background to the sample's current-sign convention before subtraction.
        source_sign = bgcfg.get(f"{label}_sign", 1 if label == "ring" else -1)
        if label == "ring" and b_rows.shape[1] == 2:
            source_sign = bgcfg.get("ring_sign", 1)
        target_sign = cfg.get(f"{label}_sign", 1 if label == "ring" else -1)
        b_i = b_rows[:, int(channel)+1] * source_sign / target_sign
        background = interpolate(b_e, b_i, e)
        result[f"I_{label}_background_A"] = background
        result[f"I_{label}_A"] = current - background
        missing = int(np.isnan(background).sum())
        if missing:
            notes.append(f"{'盘' if label == 'disk' else '环'}背景未覆盖 {missing} 个点，这些点不外推、不参与计算。")
        for key in ("Low E (V)", "High E (V)", "Scan Rate (V/s)", "Comp R (ohm)", "UC R (ohm)"):
            if bg.header.get(key) != trace.header.get(key):
                notes.append(f"背景 {bg.name} 的 {key} 与样品不同，已保留差异记录。")
        for key in ("pH", "temperature_C", "electrolyte"):
            if cfg.get(key) != bgcfg.get(key):
                notes.append(f"背景的 {key} 与样品不同，请核对实验条件。")
    area = cfg.get("area_cm2")
    if area is not None:
        try:
            area = require_number(area, "盘面积（cm²）", positive=True)
            result["j_disk_mA_cm2"] = result["I_disk_A"] * 1000 / area
        except DataError as exc:
            # Area is irrelevant to current plots and RRDE ratios. Density and
            # K–L still require a valid area at their own calculation boundary.
            notes.append(f"{exc} 当前仍可使用电流；电流密度和 K–L 需要修正面积。")
    result["I_disk_mA"] = result["I_disk_A"] * 1000
    return {"data": result, "segment": segment, "notes": list(dict.fromkeys(notes)), "axis": axis,
            "config": dict(cfg), "name": trace.name, "sha256": trace.sha256}


def rrde_calculate(processed, cfg, floor_A=1e-9):
    df = processed["data"].copy()
    if "I_ring_A" not in df:
        raise DataError("没有环电流，请核对通道对应。")
    n_collect = require_number(cfg.get("collection_efficiency"), "收集效率 N（0–1）", positive=True)
    if n_collect > 1:
        raise DataError("收集效率 N 应输入 0–1，例如 0.37；不能直接输入 37。")
    floor_A = require_number(floor_A, "最小盘电流幅值（A）", positive=True)
    disk = df["I_disk_A"].to_numpy() * int(cfg.get("disk_sign", -1))
    ring = df["I_ring_A"].to_numpy() * int(cfg.get("ring_sign", 1))
    q = ring / n_collect
    denominator = disk + q
    finite = np.isfinite(disk) & np.isfinite(ring)
    valid = finite & (disk > floor_A) & (ring >= 0) & (denominator > floor_A)
    peroxide, n = np.full(len(df), np.nan), np.full(len(df), np.nan)
    peroxide[valid] = 200 * q[valid] / denominator[valid]
    n[valid] = 4 * disk[valid] / denominator[valid]
    physical = valid & (peroxide <= 100 + 1e-8) & (n >= 2 - 1e-8)
    status = np.full(len(df), "可用", dtype=object)
    status[~finite] = "背景未覆盖/非有限电流"
    status[finite & (disk <= floor_A)] = "盘电流方向异常或过小"
    status[finite & (disk > floor_A) & (ring < 0)] = "环电流方向异常"
    status[valid & ~physical] = "超出两产物模型范围；数值未裁剪"
    df["peroxide_pct"] = peroxide
    df["n_RRDE"] = n
    df["four_e_pct_model"] = 100 - peroxide
    df["valid_two_product_model"] = physical
    df["status"] = status
    return df


def kl_calculate(curves, potentials, C, D, nu):
    """cgs units: C mol/cm³, D and nu cm²/s; j A/cm², omega rad/s."""
    C = require_number(C, "氧浓度 C（mol/cm³）", True)
    D = require_number(D, "扩散系数 D（cm²/s）", True)
    nu = require_number(nu, "运动黏度 ν（cm²/s）", True)
    if len(curves) < 2:
        raise DataError("K–L 至少需要两个不同转速，建议三个以上。")
    rpms, currents = [], []
    signatures = set()
    conditions = set()
    for curve in curves:
        cfg, frame = curve["config"], curve["data"]
        rpms.append(require_number(cfg.get("rpm"), "转速 rpm", True))
        area = require_number(cfg.get("area_cm2"), "盘面积 cm²", True)
        signatures.add(potential_signature(cfg, curve["axis"]))
        conditions.add((cfg.get("pH"), cfg.get("temperature_C"), cfg.get("electrolyte"), curve["segment"]["direction"], area))
        currents.append(interpolate(frame.E_V.to_numpy(), frame.I_disk_A.to_numpy() * int(cfg.get("disk_sign", -1)) / area, potentials))
    if len(signatures) != 1 or len(conditions) != 1:
        raise DataError("K–L 所选文件的参比坐标、pH、温度、电解液、面积或扫描方向不一致。")
    if len(set(rpms)) != len(rpms):
        raise DataError("同一拟合中存在重复转速；请每个转速选择一条曲线。")
    omega = 2 * np.pi * np.asarray(rpms) / 60
    x = omega ** -.5
    current_matrix = np.asarray(currents)
    constant = .62 * FARADAY * D**(2/3) * nu**(-1/6) * C
    rows, point_rows = [], []
    for k, potential in enumerate(potentials):
        j = current_matrix[:, k]
        row = dict(E_V=float(potential), n_KL=np.nan, two_e_pct_model=np.nan, four_e_pct_model=np.nan,
                   slope=np.nan, intercept=np.nan, R_squared=np.nan, slope_standard_error=np.nan,
                   n_standard_error=np.nan, speeds=len(x), valid_two_path_model=False, status="")
        if not np.all(np.isfinite(j)) or np.any(j <= 1e-9):
            row["status"] = "电位未共同覆盖/阴极电流方向异常或过小"
            rows.append(row)
            continue
        y = 1 / j
        slope, intercept = np.polyfit(x, y, 1)
        predicted = slope*x + intercept
        residual = np.sum((y-predicted)**2)
        total = np.sum((y-y.mean())**2)
        r2 = (1-residual/total) if len(x)>2 and total>0 else np.nan
        slope_se = math.sqrt(residual/(len(x)-2)/np.sum((x-x.mean())**2)) if len(x)>2 else np.nan
        n = 1/(slope*constant) if slope>0 else np.nan
        valid = bool(slope>0 and intercept>=0 and 2 <= n <= 4)
        status = []
        if len(x)==2:
            status.append("仅两转速，无法有效评估线性")
        if slope<=0:
            status.append("斜率非正")
        if intercept<0:
            status.append("截距为负")
        if np.isfinite(n) and not 2 <= n <= 4:
            status.append("超出两路径模型范围；未裁剪")
        row.update(n_KL=n, two_e_pct_model=50*(4-n), four_e_pct_model=50*(n-2), slope=slope,
                   intercept=intercept, R_squared=r2, slope_standard_error=slope_se,
                   n_standard_error=n*slope_se/slope if slope>0 else np.nan,
                   valid_two_path_model=valid, status="；".join(status) or "可用（模型估算）")
        rows.append(row)
        for rpm, xx, yy, fit in zip(rpms, x, y, predicted):
            point_rows.append(dict(E_V=float(potential), rpm=rpm, omega_inv_sqrt=xx,
                                   inverse_j_cm2_A=yy, fit_inverse_j_cm2_A=fit))
    return pd.DataFrame(rows), pd.DataFrame(point_rows)


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, np.generic):
        return clean_json(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def json_bytes(value):
    return json.dumps(clean_json(value), ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def pack_project(traces, configs, settings):
    configs = resolved_configs(configs, {k:t.name for k,t in traces.items()})
    manifest = dict(schema=1, app_version=VERSION, settings=settings, files=[])
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for ident, trace in traces.items():
            path = f"raw/{ident}.txt"
            archive.writestr(path, trace.raw)
            manifest["files"].append(dict(id=ident, name=trace.name, path=path, sha256=trace.sha256, config=configs[ident]))
        archive.writestr("project.json", json_bytes(manifest))
    return output.getvalue()


def unpack_project(raw):
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            if len(archive.infolist())>250 or sum(i.file_size for i in archive.infolist())>100_000_000:
                raise DataError("项目过大，请分批保存和载入。")
            manifest = json.loads(archive.read("project.json"))
            if manifest.get("schema") != 1 or not isinstance(manifest.get("settings"), dict):
                raise DataError("项目版本或结构不支持。")
            traces, configs = {}, {}
            for entry in manifest["files"]:
                trace = parse_chi(entry["name"], archive.read(entry["path"]))
                if trace.sha256 != entry["sha256"] or trace.id != entry["id"]:
                    raise DataError("项目原始数据校验失败。")
                defaults = default_config(trace)
                if not isinstance(entry["config"], dict):
                    raise DataError("项目参数结构不正确。")
                defaults.update({k:v for k,v in entry["config"].items() if k in defaults})
                if "background_ph_mode" not in entry["config"]:
                    # Existing values and empty records remain independent until
                    # a user explicitly enables following or confirms a binding.
                    defaults.update(background_ph_mode="manual", background_ph_legacy=True)
                if "parameter_sources" not in entry["config"]:
                    defaults["parameter_sources"] = {k:"项目保存值，来源未记录" for k in
                        ("area_cm2", "temperature_C", "potential_method", "pH", "ref_V_SHE", "collection_efficiency")
                        if entry["config"].get(k) is not None}
                if "disk_diameter_mm" not in entry["config"]:
                    # Never reinterpret a legacy area (including an empty one)
                    # as the new default electrode geometry.
                    defaults.update(disk_diameter_mm=None, area_mode="area",
                                    area_cm2=entry["config"].get("area_cm2"))
                if not all(k in entry["config"] for k in RPM_FIELDS):
                    # A legacy saved value can be manual. Do not relabel or overwrite it
                    # with a new filename guess, even when the saved value is empty.
                    defaults.update(rpm=entry["config"].get("rpm"),rpm_source="saved_project",
                                    rpm_status="saved",rpm_matches=[],rpm_candidates=[],
                                    rpm_note="项目保存值，来源未记录；未重新识别覆盖。")
                traces[trace.id] = trace
                configs[trace.id] = defaults
            return traces, resolved_configs(configs, {k:t.name for k,t in traces.items()}), manifest["settings"]
    except DataError:
        raise
    except (ValueError, KeyError, TypeError, zipfile.BadZipFile, OSError) as exc:
        raise DataError(f"无法载入项目：{exc}") from exc


def parameter_record(traces, configs, settings, processed=None):
    configs = resolved_configs(configs, {k:t.name for k,t in traces.items()})
    return dict(app_version=VERSION, sources=SOURCES, settings=settings,
                formulas={"RHE": "E_vs_ref + E_ref_vs_SHE(T) + 2.303RT/F*pH; calibrated total offset is used alone",
                          "RRDE": "H2O2%=200*(R/N)/(D+R/N); n=4*D/(D+R/N); D,R are signed-background-corrected positive reaction magnitudes",
                          "KL": "1/j = 1/jk + 1/(0.62*n*F*D^(2/3)*nu^(-1/6)*C) * omega^(-1/2); omega=2*pi*rpm/60",
                          "ir": "E_corr=E_raw-I_anodic_positive_raw*R_remaining; before background subtraction"},
                files=[dict(id=k, filename=t.name, sha256=t.sha256, columns=t.columns, encoding=t.encoding,
                            header=t.header, config=configs[k],
                            selected_segment=(processed or {}).get(k, {}).get("segment"),
                            notes=(processed or {}).get(k, {}).get("notes", [])) for k,t in traces.items()])
