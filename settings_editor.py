"""Scientific editors only stage changes; the shared action applies them."""
from copy import deepcopy
import json
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
from background_conditions import INHERITED_FIELDS, METHODS as CONDITION_METHODS
from background_ph import finite_ph
from experiment_conditions import apply_conditions
from orr_core import DataError, scan_segments, select_segment


CONDITION_FIELD_LABELS = {
    "potential_method": "换算方式", "pH": "pH", "temperature_C": "温度 / °C",
    "reference": "参比电极", "filling": "参比内充液", "ref_V_SHE": "E_ref vs SHE / V",
    "reference_source": "参比来源说明", "reference_preset_C": "参比预设温度 / °C",
    "rhe_offset_V": "实测 RHE 总偏移 / V",
}
CONDITION_MODE_LABELS = {"follow": "整组跟随关联样品", "independent": "独立设置", "legacy_ph": "旧版 pH 兼容"}
CONDITION_STATUS_LABELS = {"following": "跟随中", "independent": "独立", "waiting": "等待关联样品",
                           "conflict": "条件冲突", "invalid": "记录无效", "unbound": "尚未关联",
                           "not_required": "当前方式不需要", "manual_missing": "待填写"}


def _changed(context, values):
    snapshots = st.session_state.setdefault("editor_snapshots", {})
    before = snapshots.get(context)
    snapshots[context] = deepcopy(values)
    return before is not None and before != values


def stage_background_mode(ident, mode, *, domain=None, values=None, source_label="用户复制：当前有效条件"):
    """Replace condition-strategy intent atomically, preserving unrelated edits."""
    from ui_shared import stage_config_updates
    patch = {"background_conditions_mode": mode}
    if values:
        patch.update(deepcopy(values))
        patch["parameter_sources"] = {field: source_label for field in values}
    domain = domain or f"background_conditions:{ident}"
    keys = ("settings_draft", "rejected_config_edits", "draft_errors", "draft_error", "draft_retryable_domains")
    before = {key: deepcopy(st.session_state[key]) for key in keys if key in st.session_state}
    related = set(INHERITED_FIELDS) | {"background_conditions_mode", "background_ph_mode", "background_ph_legacy"}
    peers = {domain, f"background_conditions:{ident}", f"conditions:{ident}", f"background_ph:{ident}"}
    # Work on detached structures; only condition leaves for this background
    # are superseded by the explicit mode action. Area and other files survive.
    draft = deepcopy(st.session_state.settings_draft)
    rejected = deepcopy(st.session_state.get("rejected_config_edits", {}))
    errors = deepcopy(st.session_state.get("draft_errors", {}))
    for collection in (draft["configs"], rejected):
        for peer in peers:
            files = collection.get(peer, {})
            entry = files.get(ident)
            if entry is None:
                continue
            kept = {k: v for k, v in entry.items() if k not in related and k != "parameter_sources"}
            sources = {k:v for k,v in entry.get("parameter_sources", {}).items() if k not in related}
            if sources:
                kept["parameter_sources"] = sources
            if kept:
                files[ident] = kept
            else:
                files.pop(ident, None)
            if not files:
                collection.pop(peer, None)
                if collection is rejected:
                    errors.pop(peer, None)
    st.session_state.settings_draft = draft
    st.session_state.rejected_config_edits = rejected
    st.session_state.draft_errors = errors
    if stage_config_updates(domain, {ident: patch}):
        return True
    failed = st.session_state.get("draft_error", "背景条件模式未能加入草稿。")
    for key in keys:
        if key in before:
            st.session_state[key] = before[key]
        else:
            st.session_state.pop(key, None)
    from ui_shared import reject_config_updates
    return reject_config_updates(domain, {ident:patch}, failed)


def effective_independent_values(info):
    """Only the currently active, known effective fields; None never clears caches."""
    values = {}
    for field in INHERITED_FIELDS:
        state = info.get("field_states", {}).get(field, {})
        value = info.get("effective", {}).get(field)
        if state.get("active") and value is not None:
            values[field] = deepcopy(value)
    return values


def _mode_buttons(ident, info, view_basis, key, domain):
    mode = info.get("mode")
    if mode in ("follow", "legacy_ph"):
        if mode == "legacy_ph":
            st.caption("可升级为新版整组条件策略；升级后由整组面板接管，独立记录原样保留。")
        if st.button("切到独立设置", key=key+"_to_independent",
                     help="保留既有独立记录；之后的背景条件修改独立于关联样品。"):
            stage_background_mode(ident, "independent", domain=domain)
            st.rerun()
        if mode == "follow":
            usable = view_basis in ("applied", "candidate") and info.get("status") == "following"
            if st.button("用当前有效条件建立独立记录", key=key+"_adopt", disabled=not usable,
                         help="仅复制当前换算方式实际使用的已知有效字段；未启用方式的历史缓存保持不变。"):
                stage_background_mode(ident, "independent", domain=domain,
                                      values=effective_independent_values(info))
                st.rerun()
            if not usable:
                st.caption("等待、冲突或未绑定时没有一套完整有效条件可复制；请先补齐或统一关联样品条件。")
        if mode == "legacy_ph" and st.button("升级为整组跟随（推荐）", key=key+"_to_follow"):
            stage_background_mode(ident, "follow", domain=domain)
            st.rerun()
    elif mode == "independent":
        if st.button("改为跟随关联样品", key=key+"_to_follow",
                     help="恢复整组跟随；独立记录原样保留，未应用的独立输入不混入跟随提交。"):
            stage_background_mode(ident, "follow", domain=domain)
            st.rerun()


def _condition_detail_table(info):
    rows = []
    for field in INHERITED_FIELDS:
        state = info.get("field_states", {}).get(field, {})
        rows.append({"字段": CONDITION_FIELD_LABELS.get(field, field),
                     "有效值": info.get("effective", {}).get(field),
                     "状态": CONDITION_STATUS_LABELS.get(state.get("status"), state.get("status")),
                     "可编辑": "是" if state.get("editable") else "否",
                     "独立记录": info.get("independent", {}).get(field),
                     "有效来源": info.get("effective_sources", {}).get(field, ""),
                     "说明": state.get("detail", "")})
    st.dataframe(pd.DataFrame(rows), hide_index=True)


def _independent_editors(ident, record, key):
    """Direct independent-record editors; patches merge into this panel's domain."""
    from ui_shared import get_edit_configs, reject_config_updates, stage_config_updates
    domain = f"background_conditions:{ident}"
    edit = get_edit_configs(domain)[ident]
    st.caption("独立条件编辑；修改加入本批草稿，由统一“应用设置”生效。")
    updates = {}
    method = edit.get("potential_method")
    method = st.selectbox("背景电位换算方式", CONDITION_METHODS,
        index=CONDITION_METHODS.index(method) if method in CONDITION_METHODS else 0,
        key=key+"_method", persist_state="session")
    updates["potential_method"] = method
    if method == "理论换算":
        updates["pH"] = st.number_input("背景 pH（允许 0）", value=finite_ph(edit.get("pH")),
            step=.1, format="%.3f", key=key+"_ph", persist_state="session")
        temperature = edit.get("temperature_C")
        updates["temperature_C"] = st.number_input("背景温度 / °C",
            value=float(temperature) if isinstance(temperature, (int, float)) else None,
            min_value=-20., max_value=150., step=1., key=key+"_temp", persist_state="session")
        updates["reference"] = st.text_input("背景参比电极名称", value=edit.get("reference") or "未设置",
            key=key+"_ref", persist_state="session")
        updates["filling"] = st.text_input("背景参比内充液", value=edit.get("filling") or "",
            key=key+"_filling", persist_state="session")
        updates["ref_V_SHE"] = st.number_input("背景 E_ref vs SHE / V",
            value=finite_ph(edit.get("ref_V_SHE")), format="%.5f", step=.001,
            key=key+"_refv", persist_state="session")
        updates.update(reference_source="用户输入", reference_preset_C=None)
    elif method == "实测 RHE 总偏移":
        updates["rhe_offset_V"] = st.number_input("背景实测 RHE 总偏移 / V",
            value=finite_ph(edit.get("rhe_offset_V")), format="%.5f", step=.001,
            key=key+"_offset", persist_state="session")
    else:
        st.caption("按用户选择将原始电位视为 RHE，不再平移，不要求 pH 或参比。")
    if not _changed(key, updates):
        return
    after = deepcopy(record)
    try:
        apply_conditions(after, updates, source="人工独立设置背景条件")
    except (DataError, ValueError, TypeError) as exc:
        reject_config_updates(domain, None, str(exc))
        st.error(str(exc))
        return
    patch = {field: deepcopy(value) for field, value in after.items()
             if field not in record or record[field] != value}
    stage_config_updates(domain, {ident: patch})


def _legacy_ph_panel(ident, cfg):
    """Legacy pH-only records keep their original controls and labels."""
    from ui_shared import get_draft_view, stage_config_updates
    with st.expander("背景 pH · "+st.session_state.traces[ident].name):
        st.caption(cfg.get("background_ph_detail", "应用后核对关联样品 pH。"))
        st.caption("旧版记录：仅 pH 与关联样品联动，其他实验条件始终使用背景独立记录。")
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
        info = cfg.get("background_conditions") or {}
        if info.get("migration"):
            st.caption("迁移记录：" + json.dumps(info["migration"], ensure_ascii=False))
        _mode_buttons(ident, info, get_draft_view()["view_basis"], key, f"background_conditions:{ident}")


def background_conditions_panel(background_ids, prefix="shared"):
    """Per-background condition strategy panel over the shared draft view."""
    from ui_shared import get_draft_view
    view = get_draft_view()
    configs, records = view["configs"], view["records"]
    for ident in dict.fromkeys(background_ids):
        cfg = configs.get(ident)
        if cfg is None:
            continue
        info = cfg.get("background_conditions")
        if not isinstance(info, dict):
            continue
        if info.get("mode") == "legacy_ph":
            _legacy_ph_panel(ident, cfg)
            continue
        name = st.session_state.traces[ident].name
        with st.expander("背景实验条件 · " + name):
            st.caption(f"模式：{CONDITION_MODE_LABELS.get(info.get('mode'), info.get('mode'))} · "
                       f"状态：{CONDITION_STATUS_LABELS.get(info.get('status'), info.get('status'))}。"
                       f"{info.get('detail') or ''}")
            linked = info.get("linked_samples") or []
            st.caption("关联样品：" + ("、".join(sample["filename"] for sample in linked)
                       if linked else "尚未关联样品；不会使用独立缓存代替跟随值。"))
            for assumption in info.get("assumptions", []):
                st.caption(assumption)
            if view["view_basis"] == "applied_fallback":
                st.caption("草稿待修正；下方条件基于已应用设置。")
            key = f"bgcond_{prefix}_{ident}_{st.session_state.revision}_{st.session_state.draft_epoch}"
            _mode_buttons(ident, info, view["view_basis"], key, f"background_conditions:{ident}")
            _condition_detail_table(info)
            if info.get("migration"):
                st.caption("迁移记录：" + json.dumps(info["migration"], ensure_ascii=False))
            if info.get("mode") == "independent":
                _independent_editors(ident, records[ident], key)


def background_ph_panel(background_ids, prefix="shared"):
    return background_conditions_panel(background_ids, prefix)


def batch_scan_background_form():
    from batch_settings import KEEP, build_batch_updates
    from ui_shared import get_draft_view, get_edit_configs, file_formatter, stage_config_updates, reject_config_updates
    st.subheader("批量扫描与背景")
    records = get_edit_configs("batch_scan_background")
    samples = [i for i,c in records.items() if c.get("role") != "背景"]
    groups = list(dict.fromkeys(records[i].get("group", "未分组") for i in samples))
    key = f"batch_scan_{st.session_state.revision}_{st.session_state.draft_epoch}_"
    scope = st.segmented_control("批量应用范围", ["当前组", "全部样品", "自选"],
        default="当前组", key=key+"scope", persist_state="session")
    if scope == "自选":
        targets = st.multiselect("批量目标文件", list(records), default=[],
            format_func=file_formatter(), key=key+"targets", persist_state="session")
    elif scope == "全部样品":
        targets = samples
    elif groups:
        group = st.selectbox("批量实验组", groups, key=key+"group", persist_state="session")
        targets = [i for i in samples if records[i].get("group", "未分组") == group]
    else:
        targets = []
    st.caption(f"本次目标 {len(targets)} 个文件；只修改明确选定的项。选择范围本身不复制设置。")
    with st.expander("查看批量目标文件"):
        st.write([st.session_state.traces[i].name for i in targets])
    direction = st.selectbox("批量扫描方向", ["保持", "递减", "递增"], key=key+"direction", persist_state="session")
    mode = st.selectbox("批量自动选择规则", ["保持", "A", "B"],
        format_func=lambda v: {"保持":"保持", "A":"A · 最后完整循环的支线", "B":"B · 最后完整单向支线"}[v],
        key=key+"mode", persist_state="session")
    actions = {"keep":"保持原背景", "disk":"统一盘背景（环保持）", "paired":"盘环配对背景",
               "independent":"分别指定盘／环背景", "none":"不扣背景"}
    action = st.selectbox("批量背景操作", list(actions), format_func=actions.get,
        key=key+"action", persist_state="session")
    disk = ring = KEEP
    choices = [KEEP, None]+[i for i,c in records.items() if c.get("role") == "背景"]
    def background_label(ident):
        return "保持" if ident == KEEP else "不扣除" if ident is None else file_formatter()(ident)
    if action in ("disk", "paired", "independent"):
        disk = st.selectbox("批量盘背景", choices, format_func=background_label,
            key=key+"disk", persist_state="session")
    if action == "independent":
        ring = st.selectbox("批量环背景", choices, format_func=background_label,
            key=key+"ring", persist_state="session")
    try:
        patches, rows = build_batch_updates(st.session_state.traces, get_draft_view()["records"], targets,
            direction=None if direction == "保持" else direction,
            mode=None if mode == "保持" else mode, background_action=action, disk=disk, ring=ring)
        error = None
    except DataError as exc:
        patches, rows, error = {}, [], str(exc)
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True,
            column_config={"文件":st.column_config.TextColumn(width="medium"),
                           "修改内容":st.column_config.TextColumn(width="medium")})
        cleared = [row["文件"] for row in rows if row["清除人工段"]]
        if cleared:
            st.warning(f"应用自动规则将清除 {len(cleared)} 个文件的人工段："+"、".join(cleared))
    if error:
        st.info(error)
    previous_targets = set(st.session_state.settings_draft.get("configs", {}).get("batch_scan_background", {}))
    removed_targets = previous_targets-set(targets)
    if removed_targets:
        st.caption("再次加入将替换上一批量草稿，以下文件的上一批量修改将撤回："+
                   "、".join(st.session_state.traces[i].name for i in removed_targets))
    if st.button("加入本批草稿", disabled=not targets, key=key+"stage"):
        if error:
            reject_config_updates("batch_scan_background", None, error)
        elif not patches:
            st.info("未选择要修改的项目；已有草稿保持不变。")
        elif stage_config_updates("batch_scan_background", patches, replace_domain=True, retain_intent=True):
            st.success("批量设置已加入草稿；下方统一应用设置后生效。")
    st.caption("逐文件扫描段、通道与符号可在下方检查；批量操作不复制转速、N 或实验条件。")


def per_file_form():
    from ui_shared import (get_edit_configs, stage_config_updates, file_formatter,
                           figure_style, figure_bytes)
    ids = list(st.session_state.traces)
    ident = st.selectbox("要检查的文件",ids,format_func=file_formatter(),key="detail_file",persist_state="session")
    trace, cfg = st.session_state.traces[ident], get_edit_configs("scan:"+ident)[ident]
    import hashlib
    external = st.session_state.settings_draft.get("configs", {}).get("batch_scan_background", {}).get(ident, {})
    fingerprint = hashlib.sha256(json.dumps(external, sort_keys=True, default=str).encode()).hexdigest()[:12]
    key = f"scan_{ident}_{st.session_state.revision}_{st.session_state.draft_epoch}_{fingerprint}_"
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
    configs = get_edit_configs("scan:"+ident)
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
    if _changed(key,updates):
        stage_config_updates("scan:"+ident,{ident:updates})
    background_conditions_panel([i for i in (updates.get("background_disk"),updates.get("background_ring")) if i])
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
