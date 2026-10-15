import streamlit as st
from ui_shared import initialize, invalidate

st.set_page_config(page_title="ORR Worker", page_icon=":material/science:", layout="wide")
initialize()
with st.sidebar:
    st.title("ORR Worker")
    st.caption("辰华 CV · K–L · RRDE")
    current_axis = st.session_state.settings.get("axis", "RHE")
    axis = st.selectbox("分析与导出的电位坐标", ["RHE", "原始"], index=0 if current_axis=="RHE" else 1,
                        help="RHE 需要先设置实验参数。原始模式可直接预览数据。", key=f"axis_{st.session_state.revision}")
    if axis != current_axis:
        st.session_state.settings["axis"] = axis
        invalidate()
        st.rerun()
    st.caption(f"已载入 {len(st.session_state.traces)} 个文件 · 本机处理")
    if len(st.session_state.traces)>10:
        st.info("本版按每批 10 个文件验证；可在导入页移除不需要的文件。")
nav = st.navigation([
    st.Page("app_pages/import_data.py", title="导入与设置", icon=":material/upload_file:"),
    st.Page("app_pages/curves.py", title="极化曲线", icon=":material/show_chart:"),
    st.Page("app_pages/kl.py", title="多转速 K–L", icon=":material/scatter_plot:"),
    st.Page("app_pages/rrde.py", title="RRDE 选择性", icon=":material/track_changes:"),
    st.Page("app_pages/export.py", title="导出与项目", icon=":material/download:"),
])
nav.run()
