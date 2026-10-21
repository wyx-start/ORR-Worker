from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile
from copy import deepcopy

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from background_ph import (activate_ph_links, finite_ph, synchronize_ph_links)
from background_pairing import apply_background_binding

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
    from settings_draft import new_draft
    st.session_state.setdefault("settings_draft", new_draft(st.session_state.revision))
    st.session_state.setdefault("draft_epoch", 0)
    st.session_state.setdefault("workspace_epoch", 0)


def _overlay(base, patch):
    result = deepcopy(base)
    for key, value in patch.items():
        result[key] = _overlay(result.get(key, {}), value) if isinstance(value, dict) else deepcopy(value)
    return result


def _difference(value, base):
    result = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = _difference(item, base.get(key, {}) if isinstance(base.get(key), dict) else {})
            if nested:
                result[key] = nested
        elif item != base.get(key):
            result[key] = deepcopy(item)
    return result


def get_draft_configs():
    from settings_draft import candidate
    try:
        configs, _ = candidate(st.session_state.settings_draft, st.session_state.traces,
            st.session_state.configs, st.session_state.settings, st.session_state.revision)
        return configs
    except (DataError, ValueError, TypeError, IndexError):
        # Invalid edits must remain visible and repairable; processing still uses
        # pending_candidate(), which refuses them instead of this UI fallback.
        pass
    result = deepcopy(st.session_state.configs)
    for records in st.session_state.settings_draft.get("configs", {}).values():
        for ident, patch in records.items():
            if ident in result:
                result[ident] = _overlay(result[ident], patch)
    return result


def get_draft_settings():
    result = deepcopy(st.session_state.settings)
    for patch in st.session_state.settings_draft.get("settings", {}).values():
        result = _overlay(result, patch)
    return result


def has_draft():
    from settings_draft import has_changes
    return has_changes(st.session_state.settings_draft) or bool(st.session_state.get("draft_error"))


def _draft_error_summary():
    errors = st.session_state.get("draft_errors", {})
    if errors:
        st.session_state.draft_error = "；".join(errors.values())
    else:
        st.session_state.pop("draft_error", None)


def stage_config_updates(domain, updates_by_id, _retry=True):
    from settings_draft import stage_config
    draft = deepcopy(st.session_state.settings_draft)
    try:
        for ident, updates in updates_by_id.items():
            old = draft.get("configs", {}).get(domain, {}).pop(ident, {})
            patch = _difference(_overlay(old, updates), st.session_state.configs[ident])
            if patch:
                stage_config(draft, domain, ident, patch)
        st.session_state.settings_draft = draft
        st.session_state.setdefault("draft_errors", {}).pop(domain, None)
        st.session_state.setdefault("rejected_config_edits", {}).pop(domain, None)
        _draft_error_summary()
        if _retry:
            for rejected_domain, values in list(st.session_state.get("rejected_config_edits", {}).items()):
                stage_config_updates(rejected_domain, values, _retry=False)
        return True
    except (DataError, ValueError, TypeError) as exc:
        st.session_state.setdefault("draft_errors", {})[domain] = str(exc)
        st.session_state.setdefault("rejected_config_edits", {})[domain] = deepcopy(updates_by_id)
        _draft_error_summary()
        return False


def stage_settings_updates(domain, updates):
    from settings_draft import stage_settings
    draft = deepcopy(st.session_state.settings_draft)
    try:
        old = draft.get("settings", {}).pop(domain, {})
        patch = _difference(_overlay(old, updates), st.session_state.settings)
        if patch:
            stage_settings(draft, domain, patch)
        st.session_state.settings_draft = draft
        st.session_state.setdefault("draft_errors", {}).pop(domain, None)
        _draft_error_summary()
    except (DataError, ValueError, TypeError) as exc:
        st.session_state.setdefault("draft_errors", {})[domain] = str(exc)
        _draft_error_summary()


def pending_candidate():
    from settings_draft import candidate
    if st.session_state.get("draft_error"):
        raise DataError(st.session_state.draft_error)
    if not has_draft():
        return deepcopy(st.session_state.configs), deepcopy(st.session_state.settings)
    return candidate(st.session_state.settings_draft, st.session_state.traces,
                     st.session_state.configs, st.session_state.settings, st.session_state.revision)


def apply_pending_settings(preflight=None):
    """Validate one immutable candidate, then commit both configs and settings."""
    if not has_draft() and not st.session_state.get("draft_error"):
        return True
    configs, settings = pending_candidate()
    if preflight is not None:
        preflight(configs, settings)
    st.session_state.configs = configs
    st.session_state.settings = settings
    invalidate()
    st.session_state.settings_notice = "设置已应用；受影响的分析结果需重新计算。"
    return True


def apply_settings_button(key="shared_apply"):
    if st.session_state.get("settings_notice"):
        st.success(st.session_state.pop("settings_notice"))
    if st.session_state.get("draft_error"):
        st.error(st.session_state.draft_error)
    dirty = has_draft() or bool(st.session_state.get("draft_error"))
    if dirty:
        st.info("有未应用修改：应用范围见下方。计算、导出或保存项目时也可合并应用。")
        with st.expander("查看本次修改与目标文件"):
            draft = st.session_state.settings_draft
            rows = [{"来源":domain, "文件":label(ident), "修改字段":"、".join(patch)}
                    for domain, records in draft.get("configs", {}).items()
                    for ident, patch in records.items() if patch]
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True)
            if draft.get("settings"):
                st.write("全局设置", draft["settings"])
        with st.container(horizontal=True):
            if st.button("应用设置", type="primary", key=key):
                try:
                    apply_pending_settings()
                    st.rerun()
                except (DataError, ValueError, TypeError) as exc:
                    st.error(str(exc))
            if st.button("放弃未应用修改", key=key+"_discard"):
                reset_draft()
                st.rerun()
    else:
        st.caption(f"已应用 · 配置修订 {st.session_state.revision} · {st.session_state.settings.get('axis', 'RHE')} 电位坐标")


def reset_draft():
    from settings_draft import new_draft
    st.session_state.settings_draft = new_draft(st.session_state.revision)
    st.session_state.draft_epoch = st.session_state.get("draft_epoch", 0)+1
    st.session_state.pop("draft_error", None)
    st.session_state.pop("draft_errors", None)
    st.session_state.pop("rejected_config_edits", None)


def process_selected(ids, configs=None, settings=None, channels="all", subtract_background=True):
    configs = configs if configs is not None else st.session_state.configs
    settings = settings if settings is not None else st.session_state.settings
    outputs, errors = {}, []
    for ident in ids:
        if ident not in configs or configs[ident].get("role") == "背景":
            continue
        try:
            outputs[ident] = process_trace(st.session_state.traces[ident], configs[ident],
                st.session_state.traces, configs, settings.get("axis", "RHE"),
                channels=channels, subtract_background=subtract_background)
        except (DataError, ValueError, TypeError, IndexError) as exc:
            errors.append({"文件":st.session_state.traces[ident].name, "原因":str(exc)})
    return outputs, errors


def invalidate():
    synchronize_ph_links(st.session_state.configs, {k:t.name for k,t in st.session_state.traces.items()})
    st.session_state.revision += 1
    st.session_state.results = {}
    st.session_state.exports = {}
    st.session_state.settings.get("plot", {}).pop("smoothing_report", None)
    reset_draft()


def clear_polarization_exports(channel="disk"):
    # Display changes must not invalidate K–L or RRDE calculations.
    names = (("polarization.png", "polarization.svg", "polarization_data.csv", "polarization_plot.csv", "parameters.json") if channel == "disk"
             else ("ring_current.png", "ring_current.svg", "ring_current_data.csv", "ring_current_plot.csv", "ring_current_parameters.json"))
    for name in names:
        st.session_state.exports.pop(name, None)
    st.session_state.exports.pop("parameters.json", None)
    st.session_state.settings.get("plot" if channel == "disk" else "ring_plot", {}).pop("smoothing_report", None)
    if channel == "ring":
        st.session_state.settings.get("ring_plot", {}).pop("comparison_audit", None)


@st.cache_data(max_entries=40, show_spinner=False)
def cached_parse(name, raw):
    return parse_chi(name, raw)


def add_files(files):
    if has_draft() or st.session_state.get("draft_error"):
        raise DataError("有未应用修改。请先应用或放弃草稿，再导入新文件；现有草稿已保留。")
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
    return lambda ident: empty_label if ident in (None, "") else labels.get(ident, str(ident))


def require_files():
    if not st.session_state.traces:
        st.info("先在「导入与设置」上传 TXT，或载入四份示例。")
        st.stop()


def process_all(axis=None, channels="all", subtract_background=True):
    axis = axis or st.session_state.settings.get("axis", "RHE")
    outputs, errors = {}, []
    for ident, trace in st.session_state.traces.items():
        cfg = st.session_state.configs[ident]
        if cfg.get("role") == "背景":
            continue
        try:
            outputs[ident] = process_trace(trace, cfg, st.session_state.traces, st.session_state.configs, axis,
                                           channels=channels, subtract_background=subtract_background)
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


def background_ph_panel(background_ids, prefix="shared"):
    from settings_editor import background_ph_panel as render
    return render(background_ids, prefix)


def per_file_form():
    from settings_editor import per_file_form as render
    return render()


def zip_exports(exports):
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, info in exports.items():
            archive.writestr(name, info["bytes"])
    return buf.getvalue()
