"""Explicit paired-background binding; no candidate or rendering side effects."""
from orr_core import DataError


def validate_pair(trace, cfg):
    count = len(trace.columns)-1
    disk, ring = cfg.get("disk_channel"), cfg.get("ring_channel")
    if (isinstance(disk, bool) or isinstance(ring, bool) or
            not isinstance(disk, int) or not isinstance(ring, int) or
            not 0 <= disk < count or not 0 <= ring < count or disk == ring):
        raise DataError(f"“{trace.name}”需要不同且有效的盘、环通道；单通道背景请改用分别指定。")


def apply_background_binding(ident, cfg, traces, configs, mode, disk=None, ring=None):
    if mode not in ("paired", "independent"):
        raise DataError("无效的背景模式。")
    if mode == "paired":
        validate_pair(traces[ident], cfg)
        if disk is not None:
            if disk == ident or disk not in traces or configs[disk].get("role") != "背景":
                raise DataError("请选择有效的背景文件，不能选择自身。")
            validate_pair(traces[disk], configs[disk])
        ring = disk
    for bgid in (disk, ring):
        if bgid is not None and (bgid == ident or bgid not in traces or configs[bgid].get("role") != "背景"):
            raise DataError("背景文件不存在、用途不是背景或错误地选择了自身。")
    cfg.update(background_mode=mode, background_disk=disk, background_ring=ring,
               background_reviewed=True)
