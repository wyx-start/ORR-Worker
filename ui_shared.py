from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from orr_core import (DataError, VERSION, default_config, json_bytes, parameter_record,
                      parse_chi, process_trace, scan_segments, select_segment)

ROOT = Path(__file__).resolve().parent
REFERENCE_PRESETS = {
    "自定义 / 实测标定": None,
    "Ag/AgCl · 饱和 KCl · 25 °C": ("Ag/AgCl", "饱和 KCl", .197, "https://www.metrohm.com/content/dam/metrohm/shared/documents/white-papers/WP-002EN.pdf"),
    "Ag/AgCl · 3 M KCl · 25 °C": ("Ag/AgCl", "3 M KCl", .207, "https://www.metrohm.com/content/dam/metrohm/shared/documents/white-papers/WP-002EN.pdf"),
    "SCE · 饱和 KCl · 25 °C": ("SCE", "饱和 KCl", .241, "https://www.metrohm.com/en_be/service/product-help-center/voltammetry/voltammetry---faqs.html"),
    "Hg/HgO · 1 M KOH · Pine 25 °C 近似值": ("Hg/HgO", "1 M KOH", .110, "https://pineresearch.com/tools/reference-electrode-conversion-calculator/"),
}


def initialize():
    defaults = {"traces": {}, "configs": {}, "revision": 0, "results": {}, "exports": {},
                "import_errors": [], "settings": {"axis": "RHE", "kl": {}, "plot": {}, "presets": {}},
                "common_defaults": {}}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def invalidate():
    st.session_state.revision += 1
    st.session_state.results = {}
    st.session_state.exports = {}
    st.session_state.settings.get("plot", {}).pop("smoothing_report", None)


def clear_polarization_exports():
    # Display changes must not invalidate K–L or RRDE calculations.
    for name in ("polarization.png", "polarization.svg", "polarization_data.csv", "parameters.json"):
        st.session_state.exports.pop(name, None)
    st.session_state.settings.get("plot", {}).pop("smoothing_report", None)


@st.cache_data(max_entries=40, show_spinner=False)
def cached_parse(name, raw):
    return parse_chi(name, raw)


def add_files(files):
    errors = []
    added = 0
    for name, raw in files:
        try:
            trace = cached_parse(name, raw)
            if trace.id not in st.session_state.traces:
                st.session_state.traces[trace.id] = trace
                cfg = default_config(trace)
                st.session_state.configs[trace.id] = cfg
                added += 1
        except (DataError, ValueError, TypeError) as exc:
            errors.append({"文件": name, "原因": str(exc)})
    st.session_state.import_errors = errors
    if added:
        invalidate()
    return added


def label(ident):
    return st.session_state.traces[ident].name + " · " + ident[:4]


def file_formatter(empty_label="不扣除"):
    # A stable snapshot also works when Streamlit deserializes widget options off-thread.
    labels = {ident:trace.name + " · " + ident[:4] for ident, trace in st.session_state.traces.items()}
    return lambda ident: empty_label if ident is None else labels.get(ident, str(ident))


def require_files():
    if not st.session_state.traces:
        st.info("先在「导入与设置」上传 TXT，或载入四份示例。")
        st.stop()


def process_all(axis=None):
    axis = axis or st.session_state.settings.get("axis", "RHE")
    outputs, errors = {}, []
    for ident, trace in st.session_state.traces.items():
        cfg = st.session_state.configs[ident]
        if cfg.get("role") == "背景":
            continue
        try:
            outputs[ident] = process_trace(trace, cfg, st.session_state.traces, st.session_state.configs, axis)
        except (DataError, ValueError, TypeError, IndexError) as exc:
            errors.append({"文件": trace.name, "原因": str(exc)})
    return outputs, errors


def show_errors(errors):
    if errors:
        st.warning(f"{len(errors)} 个文件暂未处理，其余文件可继续。")
        st.dataframe(pd.DataFrame(errors), hide_index=True)


def show_notes(outputs):
    with st.expander("查看扫描选择与处理记录"):
        for ident, result in outputs.items():
            seg = result["segment"]
            st.markdown(f"**{result['name']}** · 第 {seg['cycle'] or '—'} 圈 / 第 {seg['segment']} 段 · 电位{seg['direction']} · {seg['points']} 点")
            for note in result["notes"]:
                st.caption(note)


def csv_bytes(frame):
    return frame.to_csv(index=False).encode("utf-8-sig")


def merged_data(outputs):
    frames = []
    for ident, output in outputs.items():
        frame = output["data"].copy()
        frame.insert(0, "file_id", ident)
        frame.insert(1, "filename", output["name"])
        frame.insert(2, "potential_axis", output["axis"])
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parameters(outputs=None):
    return parameter_record(st.session_state.traces, st.session_state.configs,
                            st.session_state.settings, outputs)


def set_export(name, content, mime):
    st.session_state.exports[name] = {"bytes": content, "mime": mime}


def store_table(name, frame):
    payload = csv_bytes(frame)
    set_export(name, payload, "text/csv")
    return payload


def figure_style():
    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Microsoft YaHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "font.size": 10, "svg.fonttype": "none",
                         "axes.spines.top": False, "axes.spines.right": False})


def figure_bytes(fig):
    png, svg = BytesIO(), BytesIO()
    fig.savefig(png, format="png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, format="svg", bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png.getvalue(), svg.getvalue()


def offer_figure(fig, name):
    png, svg = figure_bytes(fig)
    st.image(png, width="stretch")
    with st.container(horizontal=True):
        st.download_button("PNG · 300 dpi", png, f"{name}.png", "image/png", key=f"png_{name}")
        st.download_button("SVG · 矢量图", svg, f"{name}.svg", "image/svg+xml", key=f"svg_{name}")
    set_export(f"{name}.png", png, "image/png")
    set_export(f"{name}.svg", svg, "image/svg+xml")


def axis_label(outputs):
    if all(o["axis"] == "RHE" or o["config"].get("potential_method") == "已是 RHE" for o in outputs.values()):
        return "E / V vs. RHE"
    refs = {(o["config"].get("reference", "未设置"), o["config"].get("filling", "")) for o in outputs.values()}
    if len(refs) == 1 and next(iter(refs))[0] != "未设置":
        ref, filling = next(iter(refs))
        return f"E / V vs. {ref} ({filling})"
    return "E / V (original reference)"


def per_file_form():
    st.subheader("扫描、通道与背景")
    ids = list(st.session_state.traces)
    ident = st.selectbox("要检查的文件", ids, format_func=file_formatter(), key="detail_file")
    trace, cfg = st.session_state.traces[ident], st.session_state.configs[ident]
    prefix = f"detail_{ident}_{st.session_state.revision}_"
    multi = len(trace.columns) >= 3
    try:
        segments = scan_segments(trace)
    except DataError as exc:
        st.error(str(exc))
        return
    try:
        selected = select_segment(trace, cfg)
        st.caption(f"当前：{cfg.get('mode', 'A')} 模式 · 电位{selected['direction']} · 第 {selected['segment']} 段 · {selected['points']} 点。")
    except DataError as exc:
        selected = None
        st.warning(str(exc))
    st.caption(f"盘通道 {cfg.get('disk_channel', 0)+1}" +
               (f" / 环通道 {cfg.get('ring_channel')+1 if cfg.get('ring_channel') is not None else '未设置'}；通道为建议，请核对接线。" if multi else " · 单电流通道。"))
    with st.expander("修改扫描、通道与背景"):
        updates = {}
        updates["mode"] = st.selectbox("自动选择规则", ["A", "B"], index=0 if cfg.get("mode", "A")=="A" else 1,
            format_func=lambda m: "A · 最后完整循环内的支线" if m=="A" else "B · 最后完整单向支线",
            key=prefix+"mode", persist_state="session")
        updates["direction"] = st.selectbox("电位方向", ["递减", "递增"], index=0 if cfg.get("direction")=="递减" else 1,
            key=prefix+"direction", persist_state="session")
        manual_enabled = st.toggle("人工选择扫描段", value=cfg.get("manual_segment") is not None or selected is None,
            key=prefix+"manual_enabled", persist_state="session")
        if manual_enabled:
            choices = [s["segment"] for s in segments]
            updates["manual_segment"] = st.selectbox("人工指定扫描段", choices,
                index=choices.index(cfg.get("manual_segment")) if cfg.get("manual_segment") in choices else len(choices)-1,
                format_func=lambda v: f"第 {v} 段（可选择不完整段）", key=prefix+"manual", persist_state="session")
            st.dataframe(pd.DataFrame(segments), hide_index=True)
        else:
            updates["manual_segment"] = None
        backgrounds = [None] + [i for i in ids if i != ident and st.session_state.configs[i].get("role")=="背景"]
        updates["background_disk"] = st.selectbox("盘背景", backgrounds,
            index=backgrounds.index(cfg.get("background_disk")) if cfg.get("background_disk") in backgrounds else 0,
            format_func=file_formatter(), key=prefix+"bg_disk", persist_state="session")
        if multi:
            with st.expander("高级：盘环通道与符号"):
                channels = list(range(len(trace.columns)-1))
                disk = st.selectbox("盘 / 主电流通道", channels,
                    index=channels.index(cfg.get("disk_channel")) if cfg.get("disk_channel") in channels else 0,
                    format_func=lambda v:trace.columns[v+1], key=prefix+"disk", persist_state="session")
                options = [None] + channels
                ring = st.selectbox("环电流通道", options,
                    index=options.index(cfg.get("ring_channel")) if cfg.get("ring_channel") in options else 0,
                    format_func=lambda v:"无" if v is None else trace.columns[v+1], key=prefix+"ring", persist_state="session")
                updates.update(disk_channel=disk, ring_channel=ring)
                updates["disk_sign"] = st.selectbox("盘还原电流的符号", [-1, 1], index=0 if cfg.get("disk_sign", -1)==-1 else 1,
                    format_func=lambda v:"负" if v==-1 else "正", key=prefix+"disk_sign", persist_state="session")
                updates["ring_sign"] = st.selectbox("环氧化电流的符号", [1, -1], index=0 if cfg.get("ring_sign", 1)==1 else 1,
                    format_func=lambda v:"正" if v==1 else "负", key=prefix+"ring_sign", persist_state="session")
            updates["background_ring"] = st.selectbox("环背景（单列背景按其唯一电流列）", backgrounds,
                index=backgrounds.index(cfg.get("background_ring")) if cfg.get("background_ring") in backgrounds else 0,
                format_func=file_formatter(), key=prefix+"bg_ring", persist_state="session")
            with st.expander("环检测条件（实验核对）"):
                updates["ring_material"] = st.text_input("环材质（选填记录）", cfg.get("ring_material", ""), key=prefix+"material", persist_state="session")
                updates["ring_potential_V"] = st.number_input("环固定电位 / V（相对本文件原参比）", value=cfg.get("ring_potential_V"),
                    format="%.4f", key=prefix+"ring_v", persist_state="session")
                updates["ring_detection_confirmed"] = st.checkbox("已确认环电位适合定量检测过氧化物",
                    value=cfg.get("ring_detection_confirmed", False), key=prefix+"ring_ok", persist_state="session")
        else:
            with st.expander("高级：电流符号"):
                updates["disk_sign"] = st.selectbox("盘还原电流的符号", [-1, 1], index=0 if cfg.get("disk_sign", -1)==-1 else 1,
                    format_func=lambda v:"负" if v==-1 else "正", key=prefix+"disk_sign", persist_state="session")
        updates["ir_enabled"] = st.toggle("追加 iR 校正", value=cfg.get("ir_enabled", False), key=prefix+"ir", persist_state="session")
        if updates["ir_enabled"]:
            updates["ir_ohm"] = st.number_input("尚未补偿的电阻 / Ω *", min_value=0., value=float(cfg.get("ir_ohm", 0)),
                step=.1, key=prefix+"resistance", persist_state="session")
            updates["ir_confirmed"] = st.checkbox("确认导出电位未做这里追加的补偿，电阻是剩余未补偿部分",
                value=cfg.get("ir_confirmed", False), key=prefix+"ir_ok", persist_state="session")
        apply_group = st.checkbox("把扫描规则和方向应用到同组文件（清除同组其他文件的手选段）",
            key=prefix+"group_scan")
        if st.button("应用扫描与背景设置", type="primary"):
            if updates.get("ring_channel") is not None and updates["ring_channel"] == updates["disk_channel"]:
                st.error("盘、环不能使用同一个通道。")
            else:
                changed_records = [field for field in ("ring_material", "ring_potential_V")
                                   if field in updates and cfg.get(field) != updates[field]]
                cfg.update(updates, background_reviewed=True)
                sources = cfg.setdefault("parameter_sources", {})
                for field in changed_records:
                    sources[field] = "人工输入"
                if apply_group:
                    for key in ids:
                        if key != ident and st.session_state.configs[key].get("group") == cfg.get("group"):
                            st.session_state.configs[key].update(mode=updates["mode"], direction=updates["direction"], manual_segment=None)
                invalidate()
                st.rerun()
    if manual_enabled:
        figure_style()
        fig, ax = plt.subplots(figsize=(8, 3.5), layout="constrained")
        channel = int(cfg.get("disk_channel", 0))+1
        ax.plot(trace.values[:,0], trace.values[:,channel]*1000, color="#CDD4D8", lw=1)
        if selected:
            data = trace.values[selected["start"]:selected["end"]+1]
            ax.plot(data[:,0], data[:,channel]*1000, color="#167D8D", lw=1.6)
        ax.set(xlabel="E / V (original)", ylabel="I / mA", title="CV scan selection")
        png, _ = figure_bytes(fig)
        st.image(png, width="stretch")
    with st.expander("原始表头与解析信息"):
        st.code(trace.header["raw_text"], language=None)
        st.caption(f"编码：{trace.encoding} · {len(trace.values)} 点 · SHA-256：{trace.sha256}")


def zip_exports(exports):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, info in exports.items():
            archive.writestr(name, info["bytes"])
    return buf.getvalue()
