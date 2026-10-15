from pathlib import Path
import pandas as pd
import streamlit as st
from ui_shared import (ROOT, add_files, file_formatter, invalidate, label,
                       per_file_form, require_files, show_errors)
from condition_ui import common_parameter_form
from orr_core import (DataError, rpm_source_label, fill_missing_rpms, set_manual_rpm,
                      unpack_project)

st.title("导入与设置")
st.write("拖入辰华 TXT，核对分组和实验参数，再生成曲线与选择性结果。")
with st.container(border=True):
    files = st.file_uploader("批量导入 CV / RRDE / 背景", type=["txt", "csv", "dat"], accept_multiple_files=True, key=f"upload_{st.session_state.get('upload_epoch',0)}")
    with st.container(horizontal=True):
        if st.button("导入所选文件", type="primary", disabled=not files):
            count = add_files([(f.name, f.getvalue()) for f in files])
            st.success(f"新增 {count} 个文件；重复内容与文件名不会重复导入。")
        if st.button("载入四份示例"):
            examples = sorted((ROOT / "examples").glob("*.txt"))
            if not examples:
                st.error("示例文件尚未准备。")
            else:
                count = add_files([(p.name, p.read_bytes()) for p in examples])
                st.success(f"新增 {count} 个示例。演示数据不能作为实验结论；参比、pH、N 仍需核对。")
show_errors(st.session_state.import_errors)
with st.expander("继续上次的分析项目"):
    project = st.file_uploader("载入 .orrproj 项目", type=["orrproj"], key="restore_project")
    if st.button("载入项目（替换当前工作区）", disabled=project is None):
        try:
            traces, configs, settings = unpack_project(project.getvalue())
            st.session_state.traces = traces
            st.session_state.configs = configs
            st.session_state.settings = settings
            st.session_state.common_defaults = {}
            st.session_state.import_errors = []
            st.session_state.project_restore_notice = True
            invalidate()
            st.rerun()
        except DataError as exc:
            st.error(str(exc))
if st.session_state.pop("project_restore_notice", False):
    st.success("已载入项目，原始数据和参数已恢复。")
require_files()
st.subheader("核对识别结果")
st.caption("文件名支持 1600转、1600rpm、RPM1600、转速=1600 等写法。末尾裸数字仅为推测；人工值优先。请核对转速、分组与背景后确认。")
configs = st.session_state.configs
if st.button("根据文件名补全空白转速",help="只处理当前空白值，保留所有非空转速和现有分组；冲突值仍留空。"):
    count, unresolved = fill_missing_rpms(st.session_state.traces,configs)
    st.session_state.rpm_fill_notice = dict(count=count,unresolved=unresolved)
    if count:
        invalidate()
    else:
        # Provenance changed, but no numerical input changed.
        st.session_state.exports.pop("parameters.json",None)
    st.rerun()
notice = st.session_state.pop("rpm_fill_notice",None)
if notice:
    st.info(f"已补全 {notice['count']} 个空白转速；已有数值与分组保持不变。")
    if notice["unresolved"]:
        st.dataframe(pd.DataFrame(notice["unresolved"]),hide_index=True)
backgrounds = [i for i,c in configs.items() if c.get("role")=="背景"]
rows = []
for ident, trace in st.session_state.traces.items():
    cfg = configs[ident]
    bg = cfg.get("background_disk")
    if bg is None and not cfg.get("background_reviewed") and len(backgrounds)==1 and cfg.get("role")=="样品":
        bg = backgrounds[0]
    rows.append({"id":ident, "文件":trace.name, "样品/图例":cfg["name"], "分组":cfg["group"], "用途":cfg["role"],
                 "转速/rpm":cfg.get("rpm"), "转速来源":rpm_source_label(cfg),
                 "盘背景":label(bg) if bg in st.session_state.traces else "不扣除",
                 "数据点":len(trace.values)})
with st.form(f"metadata_{st.session_state.revision}"):
    edited = st.data_editor(pd.DataFrame(rows), hide_index=True, disabled=["id", "文件", "数据点", "转速来源"],
        column_config={"id":None, "用途":st.column_config.SelectboxColumn(options=["样品", "RRDE", "背景"], required=True),
                       "转速/rpm":st.column_config.NumberColumn(min_value=0., step=1.),
                       "盘背景":st.column_config.SelectboxColumn(options=["不扣除"]+[label(i) for i in backgrounds], required=True)},
        key=f"metadata_table_{st.session_state.revision}")
    applied = st.form_submit_button("确认并应用分组与背景", type="primary")
if applied:
    bg_lookup = {label(i):i for i in backgrounds}
    try:
        updates = {}
        for row in edited.to_dict("records"):
            ident = row["id"]
            cfg = dict(configs[ident])
            set_manual_rpm(cfg,None if pd.isna(row["转速/rpm"]) else row["转速/rpm"])
            cfg.update(name=str(row["样品/图例"] or row["文件"]),group=str(row["分组"] or "未分组"),role=row["用途"],
                       background_disk=bg_lookup.get(row["盘背景"]),background_reviewed=True)
            updates[ident] = cfg
        configs.update(updates)
        invalidate()
        st.rerun()
    except DataError as exc:
        st.error(str(exc))
with st.expander("转速识别依据与需要核对的记录"):
    details = []
    for ident,trace in st.session_state.traces.items():
        cfg = configs[ident]
        details.append({"文件":trace.name,"最终转速/rpm":cfg.get("rpm"),
                        "来源":rpm_source_label(cfg),
                        "匹配片段":" / ".join(m["text"] for m in cfg.get("rpm_matches",[])),
                        "候选/rpm":" / ".join(str(v) for v in cfg.get("rpm_candidates",[])),
                        "说明":cfg.get("rpm_note","")})
    st.dataframe(pd.DataFrame(details),hide_index=True)
with st.expander("移除本次分析中的文件"):
    removed = st.multiselect("选择移除（原始文件不会删除）", list(st.session_state.traces), format_func=file_formatter())
    if st.button("从本次分析移除", disabled=not removed):
        for ident in removed:
            st.session_state.traces.pop(ident, None)
            configs.pop(ident, None)
        for cfg in configs.values():
            for field in ("background_disk", "background_ring"):
                if cfg.get(field) in removed:
                    cfg[field] = None
        invalidate()
        st.session_state.upload_epoch = st.session_state.get("upload_epoch", 0)+1
        st.rerun()
section = st.segmented_control("参数设置", ["实验条件", "扫描与背景"], default="实验条件", key="import_section", persist_state="session")
if section=="扫描与背景":
    per_file_form()
else:
    common_parameter_form()
