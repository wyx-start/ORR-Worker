import streamlit as st
from orr_core import json_bytes, pack_project
from ui_shared import (merged_data, parameters, process_all, require_files,
                       set_export, show_errors, store_table, zip_exports)

st.title("导出与项目")
st.write("图片、数据和参数可以分别下载。保存项目可在下次恢复原始数据和全部设置。")
require_files()
outputs, errors = process_all()
show_errors(errors)
payload = json_bytes(parameters(outputs))
set_export("parameters.json",payload,"application/json")
st.download_button("导出全部参数与处理记录 JSON",payload,"parameters.json","application/json",type="primary",on_click="ignore")
if outputs:
    data = merged_data(outputs)
    st.download_button("导出全部处理后曲线 CSV",store_table("all_curves.csv",data),"all_curves.csv","text/csv",on_click="ignore")
st.subheader("已生成的图片与分析表")
exports = st.session_state.exports
if len(exports)<=2:
    st.caption("前往极化曲线、K–L 或 RRDE 页面生成图片和结果，它们会显示在这里。参数变化后旧结果会清空。")
for name, info in list(exports.items()):
    if name not in ("parameters.json","all_curves.csv"):
        st.download_button(name,info["bytes"],name,info["mime"],key="export_"+name,on_click="ignore")
st.download_button("打包下载当前全部结果 ZIP",zip_exports(exports),"orr_results.zip","application/zip",on_click="ignore")
st.subheader("保存可继续编辑的项目")
project = pack_project(st.session_state.traces,st.session_state.configs,st.session_state.settings)
st.download_button("保存分析项目 .orrproj",project,"ORR_Worker_analysis.orrproj","application/zip",on_click="ignore")
st.caption("项目包含原始 TXT 与参数；载入时重新解析和计算。浏览器页面关闭不等于已保存，请在离开前下载项目。原始实验文件不会被修改。")
