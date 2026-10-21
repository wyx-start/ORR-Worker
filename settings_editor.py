"""Scientific editors only stage changes; the shared action applies them."""
from copy import deepcopy
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from background_ph import finite_ph
from orr_core import DataError, scan_segments, select_segment


def _changed(context, values):
    snapshots = st.session_state.setdefault("editor_snapshots", {})
    before = snapshots.get(context)
    snapshots[context] = deepcopy(values)
    return before is not None and before != values


def background_ph_panel(background_ids, prefix="shared"):
    from ui_shared import get_draft_configs, stage_config_updates
    configs = get_draft_configs()
    for ident in dict.fromkeys(background_ids):
        if ident not in configs:
            continue
        cfg = configs[ident]
        with st.expander("背景 pH · "+st.session_state.traces[ident].name):
            st.caption(cfg.get("background_ph_detail", "应用后核对关联样品 pH。"))
            st.caption("影响此背景的全部关联样品；只有 pH 联动，其他实验条件独立保存。")
            key = f"bgph_{ident}_{st.session_state.revision}_{st.session_state.draft_epoch}"
            mode = st.selectbox("背景 pH 模式", ["跟随关联样品", "独立填写"],
                index=int(cfg.get("background_ph_mode")=="manual"),key=key+"mode",persist_state="session")
            updates = {"background_ph_mode":"manual" if mode=="独立填写" else "follow", "background_ph_legacy":False}
            if mode=="独立填写":
                updates["pH"] = st.number_input("背景独立 pH（允许 0）",value=finite_ph(cfg.get("pH")),
                    step=.1,format="%.3f",key=key+"ph",persist_state="session")
                updates["parameter_sources"] = {"pH":"人工独立填写背景 pH"}
            if _changed(key,updates):
                stage_config_updates("background_ph:"+ident,{ident:updates})


def per_file_form():
    from ui_shared import (get_draft_configs, stage_config_updates, file_formatter,
                           figure_style, figure_bytes)
    ids = list(st.session_state.traces)
    ident = st.selectbox("要检查的文件",ids,format_func=file_formatter(),key="detail_file",persist_state="session")
    trace, cfg = st.session_state.traces[ident], get_draft_configs()[ident]
    key = f"scan_{ident}_{st.session_state.revision}_{st.session_state.draft_epoch}_"
    try:
        segments = scan_segments(trace)
    except DataError as exc:
        st.error(str(exc))
        return
    try:
        selected = select_segment(trace,cfg)
        st.caption(f"当前选择：第 {selected['segment']} 段 · {selected['points']} 点 · 电位{selected['direction']}")
    except DataError as exc:
        selected = None
        st.warning(str(exc)+"；可在高级设置中人工选段。")
    updates = {}
    updates["direction"] = st.segmented_control("扫描方向",["递减","递增"],default=cfg.get("direction","递减"),
        key=key+"direction",persist_state="session") or cfg.get("direction","递减")
    configs = get_draft_configs()
    backgrounds = [""]+[i for i in ids if i!=ident and configs[i].get("role")=="背景"]
    multi = len(trace.columns)>=3
    mode = cfg.get("background_mode","independent")
    with st.expander("高级扫描、通道与背景"):
        updates["mode"] = st.selectbox("自动选择规则",["A","B"],index=int(cfg.get("mode")=="B"),
            format_func=lambda v:"A · 最后完整循环的支线" if v=="A" else "B · 最后完整单向支线",key=key+"mode",persist_state="session")
        manual = st.toggle("人工选择扫描段",value=cfg.get("manual_segment") is not None,key=key+"manual_on",persist_state="session")
        updates["manual_segment"] = None
        if manual:
            choices = [s["segment"] for s in segments]
            updates["manual_segment"] = st.selectbox("人工指定扫描段",choices,
                index=choices.index(cfg["manual_segment"]) if cfg.get("manual_segment") in choices else len(choices)-1,
                key=key+"manual",persist_state="session")
            st.dataframe(pd.DataFrame(segments),hide_index=True)
        if multi and cfg.get("role")!="背景":
            selected_mode = st.selectbox("背景模式",["盘环配对背景","分别指定背景"],index=int(mode!="paired"),
                key=key+"bgmode",persist_state="session")
            mode = "paired" if selected_mode=="盘环配对背景" else "independent"
        else:
            mode = "independent"
        channels = list(range(len(trace.columns)-1))
        updates["disk_channel"] = st.selectbox("盘 / 主电流通道",channels,
            index=channels.index(cfg.get("disk_channel")) if cfg.get("disk_channel") in channels else 0,
            format_func=lambda v:trace.columns[v+1],key=key+"disk",persist_state="session")
        if multi:
            choices = [-1]+channels
            ring = st.selectbox("环电流通道",choices,index=choices.index(cfg["ring_channel"]) if cfg.get("ring_channel") in choices else 0,
                format_func=lambda v:"无" if v==-1 else trace.columns[v+1],key=key+"ring",persist_state="session")
            updates["ring_channel"] = None if ring==-1 else ring
            updates["ring_sign"] = st.selectbox("环氧化电流符号",[1,-1],index=int(cfg.get("ring_sign",1)==-1),key=key+"ringsign",persist_state="session")
            updates["ring_material"] = st.text_input("环材质（选填）",value=cfg.get("ring_material",""),key=key+"material",persist_state="session")
            updates["ring_potential_V"] = st.number_input("环固定电位 / V（原参比，选填）",value=cfg.get("ring_potential_V"),format="%.4f",key=key+"ringv",persist_state="session")
            updates["ring_detection_confirmed"] = st.checkbox("已确认环电位适合定量检测过氧化物",value=cfg.get("ring_detection_confirmed",False),key=key+"ringok",persist_state="session")
        updates["disk_sign"] = st.selectbox("盘还原电流符号",[-1,1],index=int(cfg.get("disk_sign",-1)==1),key=key+"disksign",persist_state="session")
        updates["ir_enabled"] = st.toggle("追加 iR 校正",value=cfg.get("ir_enabled",False),key=key+"ir",persist_state="session")
        if updates["ir_enabled"]:
            updates["ir_ohm"] = st.number_input("尚未补偿电阻 / Ω *",min_value=0.,value=float(cfg.get("ir_ohm",0.)),key=key+"ohm",persist_state="session")
            updates["ir_confirmed"] = st.checkbox("确认这里仅追加剩余未补偿部分",value=cfg.get("ir_confirmed",False),key=key+"irok",persist_state="session")
        group_scan = st.checkbox("统一当前组扫描规则（清除其他文件人工选段）",key=key+"group",persist_state="session")
        targets = [i for i,c in configs.items() if i!=ident and c.get("group")==cfg.get("group")]
        if group_scan:
            st.warning(f"将影响同组其他 {len(targets)} 个文件，人工选段将清除。")
            st.write([st.session_state.traces[i].name for i in targets])
    updates["background_mode"] = mode
    updates["background_disk"] = st.selectbox("背景文件（盘扣盘、环扣环）" if mode=="paired" else "盘背景文件",backgrounds,
        index=backgrounds.index(cfg.get("background_disk")) if cfg.get("background_disk") in backgrounds else 0,
        format_func=file_formatter(),key=key+"bgdisk",persist_state="session") or None
    if mode=="paired":
        updates["background_ring"] = updates["background_disk"]
    elif multi:
        with st.expander("独立环背景"):
            updates["background_ring"] = st.selectbox("环背景文件",backgrounds,
                index=backgrounds.index(cfg.get("background_ring")) if cfg.get("background_ring") in backgrounds else 0,
                format_func=file_formatter(),key=key+"bgring",persist_state="session") or None
    watched = dict(updates, group_scan=group_scan)
    if _changed(key,watched):
        patches = {ident:updates}
        for target in targets:
            if group_scan:
                patches[target] = {"mode":updates["mode"],"direction":updates["direction"],"manual_segment":None}
            elif target in st.session_state.settings_draft.get("configs",{}).get("scan:"+ident,{}):
                patches[target] = {f:st.session_state.configs[target].get(f) for f in ("mode","direction","manual_segment")}
        stage_config_updates("scan:"+ident,patches)
    background_ph_panel([i for i in (updates.get("background_disk"),updates.get("background_ring")) if i])
    if manual:
        try:
            selection = select_segment(trace,dict(cfg,**updates))
            figure_style()
            fig, ax = plt.subplots(figsize=(8,3.5),layout="constrained")
            col = int(updates["disk_channel"])+1
            ax.plot(trace.values[:,0],trace.values[:,col]*1000,color="#CDD4D8")
            piece = trace.values[selection["start"]:selection["end"]+1]
            ax.plot(piece[:,0],piece[:,col]*1000,color="#167D8D")
            ax.set(xlabel="E / V (original)",ylabel="I / mA",title="CV scan selection")
            png,_ = figure_bytes(fig)
            st.image(png,width="stretch")
        except (DataError,IndexError) as exc:
            st.error(str(exc))
    with st.expander("原始表头与解析信息"):
        st.code(trace.header["raw_text"],language=None)
        st.caption(f"编码：{trace.encoding} · {len(trace.values)} 点 · SHA-256：{trace.sha256}")
