"""Download only bytes prepared after a native Streamlit action succeeds.

Native download buttons start downloading concurrently with callbacks. The small
v2 component below only hands already validated immutable bytes to the browser.
It contains no application state or scientific logic.
"""
import base64
import uuid
import streamlit as st

_DOWNLOAD = st.components.v2.component(
    "orr_validated_download",
    html="<span id='status' role='status'></span>",
    js="""
export default function ({data, parentElement, setTriggerValue}) {
  const status = parentElement.querySelector('#status');
  if (!data?.token || !status || status.dataset.sent === data.token) return;
  status.dataset.sent = data.token;
  const raw = atob(data.base64);
  const bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: data.mime}));
  const link = document.createElement('a');
  link.href = url;
  link.download = data.filename;
  parentElement.appendChild(link);
  link.click();
  link.remove();
  status.textContent = '文件已生成，正在下载。';
  setTimeout(() => URL.revokeObjectURL(url), 15000);
  // Rebuild the page from the committed snapshot after handing off the file;
  // this restores the complete export controls without a second user click.
  setTriggerValue('sent', data.token);
}
""",
)


def send_download(payload, filename, mime):
    """Call only in the successful native button handler; never cache a draft."""
    token = uuid.uuid4().hex
    _DOWNLOAD(data={"base64":base64.b64encode(payload).decode("ascii"),
                    "filename":filename, "mime":mime, "token":token},
              key="download_"+token, height=24, on_sent_change=lambda: None)


def result_downloads(plot_csv, plot_name, *, figures=(), extras=(), key="result", prepare=None):
    """One visible CSV/PNG row; every download goes through current validation.

    prepare is a UI-thread action returning (bytes, filename, mime). For dirty
    settings it performs preflight and commit before any bytes reach the client.
    """
    from ui_shared import has_draft, set_export, zip_exports
    st.subheader("导出当前结果")
    figures = list(figures)
    extras = list(extras)
    if plot_csv is not None and not has_draft():
        set_export(plot_name, plot_csv, "text/csv")
    with st.container(horizontal=True):
        text = "应用并导出绘图 CSV" if has_draft() else "下载绘图 CSV"
        if st.button(text, type="primary", key=key+"_csv"):
            try:
                if prepare is not None:
                    payload, filename, mime = prepare()
                elif has_draft():
                    raise ValueError("请先应用设置并重新计算本页结果，再导出。")
                else:
                    payload, filename, mime = plot_csv, plot_name, "text/csv"
                set_export(filename,payload,mime)
                send_download(payload, filename, mime)
                # prepare may commit a new revision; variables below were built
                # before that commit and must not repopulate the export store.
                return
            except (ValueError, TypeError, IndexError) as exc:
                st.error(str(exc))
        if figures:
            name = figures[0]
            info = st.session_state.exports.get(name+".png")
            if info:
                st.download_button("PNG", info["bytes"], name+".png", "image/png",
                    key=key+"_png", on_click="ignore", disabled=has_draft())
    with st.expander("更多导出"):
        if len(figures)>1:
            selection = st.selectbox("选择图片", figures, key=key+"_figure")
        else:
            selection = figures[0] if figures else None
        if selection:
            for ext, mime in (("png","image/png"),("svg","image/svg+xml")):
                info = st.session_state.exports.get(selection+"."+ext)
                if info:
                    st.download_button("下载 "+selection+" · "+ext.upper(),info["bytes"],selection+"."+ext,mime,
                        key=key+"_more_"+ext,disabled=has_draft(),on_click="ignore")
        for title, name, payload, mime in extras:
            if not has_draft():
                set_export(name,payload,mime)
            st.download_button(title,payload,name,mime,key=key+"_"+name,
                               disabled=has_draft(),on_click="ignore")
        st.download_button("当前结果包 ZIP", zip_exports(st.session_state.exports),
            "orr_results.zip","application/zip",key=key+"_zip",disabled=has_draft(),on_click="ignore")
