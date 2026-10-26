from copy import deepcopy
from pathlib import Path
import pandas as pd
import streamlit as st
from background_pairing import apply_background_binding
from ui_shared import (ROOT, add_files, file_formatter, invalidate, label,
                       per_file_form, require_files, show_errors, get_draft_configs, stage_config_updates,
                       apply_settings_button, has_draft, reset_draft, get_edit_configs)
from condition_ui import common_parameter_form
from orr_core import (DataError, rpm_source_label, fill_missing_rpms, set_manual_rpm,
                      unpack_project)

st.title("导入与设置")
st.write("拖入辰华 TXT，核对分组和实验参数，再生成曲线与选择性结果。")
with st.container(border=True):
    files = st.file_uploader("批量导入 CV / RRDE / 背景", type=["txt", "csv", "dat"], accept_multiple_files=True, key=f"upload_{st.session_state.get('upload_epoch',0)}")
    with st.container(horizontal=True):
        if st.button("导入所选文件", type="primary", disabled=not files):
            try:
                count = add_files([(f.name, f.getvalue()) for f in files])
                st.session_state.import_notice = f"新增 {count} 个文件；重复内容与文件名不会重复导入。"
                st.rerun()
            except DataError as exc:
                st.error(str(exc))
        if st.button("载入四份示例"):
            examples = sorted((ROOT / "examples").glob("*.txt"))
            if not examples:
                st.error("示例文件尚未准备。")
            else:
                try:
                    count = add_files([(p.name, p.read_bytes()) for p in examples])
                    st.session_state.import_notice = f"新增 {count} 个示例。演示数据不能作为实验结论；参比、pH、N 仍需核对。"
                    st.rerun()
                except DataError as exc:
                    st.error(str(exc))
show_errors(st.session_state.import_errors)
if st.session_state.get("import_notice"):
    st.success(st.session_state.pop("import_notice"))
with st.expander("继续上次的分析项目"):
    project = st.file_uploader("载入 .orrproj 项目", type=["orrproj"], key="restore_project")
    if st.button("载入项目（替换当前工作区）", disabled=project is None):
        try:
            from application.workspace import Workspace
            Workspace(st.session_state).restore_project(project.getvalue(), discard=True)
            st.session_state.project_restore_notice = True
            st.rerun()
        except DataError as exc:
            st.error(str(exc))
if st.session_state.pop("project_restore_notice", False):
    st.success("已载入项目，原始数据和参数已恢复。")
require_files()
st.subheader("核对识别结果")
st.caption("文件名支持 1600转、1600rpm、RPM1600、转速=1600 等写法。末尾裸数字仅为推测；人工值优先。请核对转速、分组与背景后确认。")
st.caption("转速未识别或有冲突时，可直接点击“转速/rpm”单元格填写；已识别值也可修改。修改后统一应用设置。")
configs = get_edit_configs("metadata")
if st.button("根据文件名补全空白转速",help="只处理当前空白值，保留所有非空转速和现有分组；冲突值仍留空。"):
    updated = deepcopy(configs)
    count, unresolved = fill_missing_rpms(st.session_state.traces,updated)
    stage_config_updates("metadata",{i:{k:v for k,v in c.items() if k.startswith("rpm")} for i,c in updated.items()
                                     if any(c.get(k) != configs[i].get(k) for k in c if k.startswith("rpm"))})
    st.session_state.rpm_fill_notice = dict(count=count,unresolved=unresolved)
    configs = get_edit_configs("metadata")
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
    rows.append({"id":ident,"文件":trace.name,"样品/图例":cfg["name"],"分组":cfg["group"],"用途":cfg["role"],
        "转速/rpm":cfg.get("rpm"),"转速来源":rpm_source_label(cfg),
        "背景文件":label(bg) if bg in st.session_state.traces else "不扣除",
        "背景方式":"盘环配对" if cfg.get("background_mode")=="paired" else "分别指定","数据点":len(trace.values)})
st.caption("配对背景在应用时自动盘扣盘、环扣环；独立环背景和通道映射可在“扫描与背景”修改。")
editor_key = f"metadata_{st.session_state.revision}_{st.session_state.draft_epoch}"
metadata_frame = pd.DataFrame(rows)
metadata_frame["转速/rpm"] = pd.to_numeric(metadata_frame["转速/rpm"], errors="coerce").astype("float64")
edited = st.data_editor(metadata_frame,hide_index=True,
    disabled=["id","文件","数据点","转速来源","背景方式"],
    column_config={"id":None,"用途":st.column_config.SelectboxColumn(options=["样品","RRDE","背景"],required=True),
        "转速/rpm":st.column_config.NumberColumn(min_value=0.,step=1.,help="未识别可手动填写，人工值优先；留空表示未知，0 表示静止测试。"),
        "背景文件":st.column_config.SelectboxColumn(options=["不扣除"]+[label(i) for i in backgrounds],required=True)},
    key=editor_key)
from settings_editor import _changed
records = [{k:None if pd.isna(v) else v for k,v in row.items()} for row in edited.to_dict("records")]
if _changed(editor_key,records):
    lookup = {label(i):i for i in backgrounds}
    patches, rpm_errors = {}, []
    for row in records:
        ident = row["id"]
        cfg = deepcopy(configs[ident])
        if row["转速/rpm"] != cfg.get("rpm"):
            try:
                set_manual_rpm(cfg,row["转速/rpm"])
            except DataError as exc:
                rpm_errors.append(f"{row['文件']}：{exc}")
                continue
        cfg.update(name=str(row["样品/图例"] or row["文件"]),group=str(row["分组"] or "未分组"),role=row["用途"])
        cfg["background_disk"] = lookup.get(row["背景文件"])
        if cfg.get("background_mode")=="paired" and cfg.get("role")!="背景":
            cfg["background_ring"] = cfg["background_disk"]
        own_fields = ["name","group","role","background_disk","background_ring"]+[k for k in cfg if k.startswith("rpm")]
        patches[ident] = {k:cfg.get(k) for k in own_fields}
    if rpm_errors:
        from ui_shared import reject_config_updates
        reject_config_updates("metadata", None, "；".join(rpm_errors))
        st.error("；".join(rpm_errors))
    else:
        stage_config_updates("metadata",patches)
with st.expander("移除本次分析中的文件"):
    removed = st.multiselect("选择移除（原始文件不会删除）", list(st.session_state.traces), format_func=file_formatter())
    if st.button("从本次分析移除", disabled=not removed or has_draft()):
        configs = deepcopy(st.session_state.configs)
        for ident in removed:
            st.session_state.traces.pop(ident, None)
            configs.pop(ident, None)
        for cfg in configs.values():
            for field in ("background_disk", "background_ring"):
                if cfg.get(field) in removed:
                    cfg[field] = None
        st.session_state.configs = configs
        invalidate()
        st.session_state.upload_epoch = st.session_state.get("upload_epoch", 0)+1
        st.rerun()
section = st.segmented_control("参数设置", ["实验条件", "扫描与背景"], default="实验条件", key="import_section", persist_state="session")
if section=="扫描与背景":
    from settings_editor import batch_scan_background_form
    batch_scan_background_form()
    with st.expander("逐文件检查与人工选段", expanded=True):
        per_file_form()
else:
    common_parameter_form()

apply_settings_button("import_apply")
