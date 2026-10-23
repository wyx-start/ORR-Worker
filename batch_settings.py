"""Pure batch scan/background intents. Each file keeps its own data and channels."""
from copy import deepcopy

from background_pairing import apply_background_binding
from orr_core import DataError, scan_segments, select_segment

KEEP = "keep"


def build_batch_updates(traces, records, targets, *, direction=None, mode=None,
                        background_action="keep", disk=KEEP, ring=KEEP):
    if direction not in (None, "递减", "递增") or mode not in (None, "A", "B"):
        raise DataError("请选择有效的扫描方向或自动规则。")
    if background_action not in ("keep", "disk", "paired", "independent", "none"):
        raise DataError("请选择有效的背景操作。")
    targets = list(dict.fromkeys(targets))
    if not targets:
        raise DataError("请先选择要修改的文件。")
    patches, preview, failures = {}, [], []
    for ident in targets:
        if ident not in records or ident not in traces:
            failures.append(f"文件 {ident} 已不存在。")
            continue
        trace, cfg = traces[ident], deepcopy(records[ident])
        patch = {}
        try:
            if direction is not None:
                patch["direction"] = direction
            if mode is not None:
                patch.update(mode=mode, manual_segment=None)
            elif direction is not None and cfg.get("manual_segment") is not None:
                segment = next((s for s in scan_segments(trace) if s["segment"] == cfg["manual_segment"]), None)
                if segment is None or segment["direction"] != direction:
                    raise DataError("人工段与新方向不相容；请选择自动规则或逐文件修正。")
            if background_action != "keep":
                if cfg.get("role") == "背景":
                    raise DataError("背景文件只能批量修改扫描，不能绑定另一份背景。")
                old_disk, old_ring = cfg.get("background_disk"), cfg.get("background_ring")
                new_disk = old_disk if disk == KEEP else disk
                new_ring = old_ring if ring == KEEP else ring
                if background_action in ("disk", "paired") and disk == KEEP:
                    raise DataError("请明确选择盘背景或“不扣除”。")
                if background_action == "none":
                    new_disk = new_ring = None
                elif background_action == "disk":
                    new_ring = old_ring
                apply_background_binding(ident, cfg, traces, records,
                    "paired" if background_action == "paired" else "independent", new_disk, new_ring)
                for channel, bgid in (("disk", cfg["background_disk"]), ("ring", cfg["background_ring"])):
                    if bgid is not None:
                        count = len(traces[bgid].columns)-1
                        bgchannel = records[bgid].get(channel+"_channel")
                        ownchannel = cfg.get(channel+"_channel")
                        if (not isinstance(ownchannel, int) or isinstance(ownchannel, bool)
                                or not 0 <= ownchannel < len(trace.columns)-1
                                or not isinstance(bgchannel, int) or isinstance(bgchannel, bool)
                                or not 0 <= bgchannel < count):
                            raise DataError(f"{channel} 背景或目标缺少有效对应通道，请逐文件核对映射。")
                patch.update({f:cfg[f] for f in ("background_mode", "background_disk", "background_ring", "background_reviewed")})
            proposed = dict(cfg, **patch)
            note = "保持扫描"
            if direction is not None or mode is not None:
                try:
                    segment = select_segment(trace, proposed)
                    note = f"第 {segment['segment']} 段 · {segment['direction']}"
                except DataError as exc:
                    note = f"需人工选段：{exc}"
            descriptions = []
            if direction is not None:
                descriptions.append(direction)
            if mode is not None:
                descriptions.append(f"规则 {mode}")
            if background_action != "keep":
                descriptions.append({"disk":"盘背景", "paired":"盘环配对",
                                     "independent":"分别指定背景", "none":"不扣背景"}[background_action])
            row = {"文件":trace.name, "修改内容":" · ".join(descriptions) or "保持原设置",
                   "清除人工段":mode is not None and records[ident].get("manual_segment") is not None,
                   "扫描预检查":note}
            for channel, label in (("disk", "盘"), ("ring", "环")):
                for prefix, config in (("原", records[ident]), ("新", proposed)):
                    bgid = config.get("background_"+channel)
                    row[prefix+label+"背景"] = traces[bgid].name if bgid in traces else "不扣除"
            preview.append(row)
            if patch:
                patches[ident] = patch
        except (DataError, ValueError, TypeError, IndexError) as exc:
            failures.append(f"{trace.name}：{exc}")
    if failures:
        raise DataError("批量设置未暂存：" + "；".join(failures))
    if patches:
        from settings_draft import candidate, new_draft, stage_config
        draft = new_draft(0)
        for ident, patch in patches.items():
            stage_config(draft, "batch_scan_background", ident, patch)
        candidate(draft, traces, records, {"axis":"原始"}, 0)
    return patches, preview
