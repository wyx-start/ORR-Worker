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

from application.workspace import Workspace
from application.data import csv_bytes, merged_data, axis_label, zip_exports
from background_conditions import canonical_configs, resolved_configs
from background_pairing import apply_background_binding

from orr_core import (DataError, VERSION, default_config, json_bytes, parameter_record,
                      parse_chi, process_trace, scan_segments, select_segment, migrate_background_config)

ROOT = Path(__file__).resolve().parent
from application.references import REFERENCE_PRESETS


def initialize():
    return Workspace(st.session_state).initialize()






def get_draft_view():
    return Workspace(st.session_state).get_draft_view()


def get_draft_configs():
    return Workspace(st.session_state).get_draft_configs()


def get_draft_settings():
    return Workspace(st.session_state).get_draft_settings()


def get_edit_configs(domain=None):
    return Workspace(st.session_state).get_edit_configs(domain)


def get_edit_settings():
    return Workspace(st.session_state).get_edit_settings()


def has_draft():
    return Workspace(st.session_state).has_draft()


def _draft_error_summary():
    return Workspace(st.session_state)._draft_error_summary()


def reject_config_updates(domain, updates_by_id, message, *, _retryable=False):
    return Workspace(st.session_state).reject_config_updates(domain, updates_by_id, message, _retryable=_retryable)


def stage_config_updates(domain, updates_by_id, _retry=True, *, replace=False, replace_domain=False, retain_intent=False):
    return Workspace(st.session_state).stage_config_updates(domain, updates_by_id, _retry, replace=replace, replace_domain=replace_domain, retain_intent=retain_intent)


def stage_settings_updates(domain, updates):
    return Workspace(st.session_state).stage_settings_updates(domain, updates)


def pending_candidate():
    return Workspace(st.session_state).pending_candidate()


def apply_pending_settings(preflight=None):
    return Workspace(st.session_state).apply_pending_settings(preflight)


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
    return Workspace(st.session_state).reset_draft()


def process_selected(ids, configs=None, settings=None, channels="all", subtract_background=True):
    return Workspace(st.session_state).process_selected(ids, configs, settings, channels, subtract_background)


def invalidate():
    return Workspace(st.session_state).invalidate()


def clear_polarization_exports(channel="disk"):
    return Workspace(st.session_state).clear_polarization_exports(channel)


@st.cache_data(max_entries=40, show_spinner=False)
def cached_parse(name, raw):
    return parse_chi(name, raw)


def add_files(files):
    return Workspace(st.session_state).add_files(files)


def label(ident):
    return Workspace(st.session_state).label(ident)


def file_formatter(empty_label="不扣除"):
    return Workspace(st.session_state).file_formatter(empty_label)


def require_files():
    if not st.session_state.traces:
        st.info("先在「导入与设置」上传 TXT，或载入四份示例。")
        st.stop()


def process_all(axis=None, channels="all", subtract_background=True):
    return Workspace(st.session_state).process_all(axis, channels, subtract_background)


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






def parameters(outputs=None):
    return Workspace(st.session_state).parameters(outputs)


def set_export(name, content, mime):
    return Workspace(st.session_state).set_export(name, content, mime)


def store_table(name, frame):
    return Workspace(st.session_state).store_table(name, frame)


def figure_style():
    from application.figures import figure_style as configure
    return configure()


def figure_bytes(fig):
    from application.figures import figure_bytes as render
    payloads = render(fig)
    plt.close(fig)
    return payloads


def offer_figure(fig, name):
    png, svg = figure_bytes(fig)
    st.image(png, width="stretch")
    set_export(f"{name}.png", png, "image/png")
    set_export(f"{name}.svg", svg, "image/svg+xml")




def background_conditions_panel(background_ids, prefix="shared"):
    import settings_editor
    render = getattr(settings_editor, "background_conditions_panel", settings_editor.background_ph_panel)
    return render(background_ids, prefix)


def background_ph_panel(background_ids, prefix="shared"):
    return background_conditions_panel(background_ids, prefix)


def per_file_form():
    from settings_editor import per_file_form as render
    return render()


