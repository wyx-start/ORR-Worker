import streamlit as st
from orr_core import DataError, json_bytes, pack_project, parameter_record
from download_ui import send_download
from ui_shared import (merged_data, require_files, set_export, show_errors, csv_bytes,
                       zip_exports, apply_settings_button, has_draft,
                       apply_pending_settings, pending_candidate, process_selected)

st.title("导出与项目")
st.write("绘图 CSV 优先用于 Origin；完整数据和参数供核查，分析项目用于下次继续。")
require_files()
apply_settings_button("export_apply")
st.subheader("已生成的绘图 CSV")
exports = st.session_state.exports
plots = [name for name in exports if name.endswith("_plot.csv")]
if has_draft():
    st.warning("有未应用科学修改。请回到相应分析页使用“应用并导出”，或先应用后重新计算；旧分析文件暂不可下载。")
elif not plots:
    st.caption("前往极化曲线、K–L 或 RRDE 生成当前结果。")
else:
    for name in plots:
        st.download_button(name,exports[name]["bytes"],name,"text/csv",on_click="ignore",key="csv_"+name,type="primary")

st.subheader("完整处理数据")
if st.button("应用并导出完整数据 CSV" if has_draft() else "下载全部完整数据 CSV",key="all_data"):
    try:
        configs,settings = pending_candidate()
        outputs,errors = process_selected(list(st.session_state.traces),configs,settings)
        show_errors(errors)
        if not outputs:
            raise DataError("没有可处理的数据。请补全实际需要的条件。")
        payload = csv_bytes(merged_data(outputs))
        params = json_bytes(parameter_record(st.session_state.traces,configs,settings,outputs))
        apply_pending_settings()
        set_export("all_curves.csv",payload,"text/csv")
        set_export("parameters.json",params,"application/json")
        send_download(payload,"all_curves.csv","text/csv")
    except (DataError,ValueError,TypeError) as exc:
        st.error(str(exc))

with st.expander("更多导出：图片、完整结果、参数与结果包"):
    for name,info in list(st.session_state.exports.items()):
        if not name.endswith("_plot.csv"):
            st.download_button(name,info["bytes"],name,info["mime"],key="asset_"+name,
                               disabled=has_draft(),on_click="ignore")
    st.download_button("当前全部结果 ZIP",zip_exports(st.session_state.exports),"orr_results.zip",
        "application/zip",disabled=has_draft(),on_click="ignore")

st.subheader("保存可继续编辑的项目")
if st.button("应用并保存项目" if has_draft() else "保存分析项目",key="save_project"):
    try:
        apply_pending_settings()
        project = pack_project(st.session_state.traces,st.session_state.configs,st.session_state.settings)
        send_download(project,"ORR_Worker_analysis.orrproj","application/zip")
        st.success("项目已生成，包含原始数据和已应用设置。缺项／冲突记录可保存，恢复后仍需解决才能分析。")
    except (DataError,ValueError,TypeError) as exc:
        st.error(str(exc))
st.caption("结果 ZIP 保存已生成的分析产物；.orrproj 保存原始数据和设置。关闭浏览器前请下载项目。")
