import streamlit as st
from ui_shared import initialize, get_draft_settings, stage_settings_updates, has_draft

st.set_page_config(page_title="ORR Worker", page_icon=":material/science:", layout="wide")
initialize()
with st.sidebar:
    st.title("ORR Worker")
    st.caption("辰华 CV · K–L · RRDE")
    current_axis = get_draft_settings().get("axis", "RHE")
    axis = st.selectbox("分析与导出的电位坐标", ["RHE", "原始"], index=0 if current_axis=="RHE" else 1,
                        help="科学设置：修改后与本批条件一起应用。原始模式可预览数据。", key=f"axis_{st.session_state.revision}_{st.session_state.draft_epoch}",persist_state="session")
    stage_settings_updates("potential_axis", {"axis":axis})
    if has_draft():
        st.caption("有未应用修改 · 请在当前页应用或合并下一步")
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
