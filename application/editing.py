"""Pure editing intents extracted from the established browser editors."""
import copy
from copy import deepcopy
import math
import re
from background_conditions import INHERITED_FIELDS, NUMERIC, controlled_fields
from experiment_conditions import apply_conditions
from orr_core import DataError

def _missing(value):
    return value is None or isinstance(value, str) and value.strip() in ("", "未设置", "未记录")

def _same_condition_value(field, left, right):
    if _missing(left) and _missing(right):
        return True
    if _missing(left) or _missing(right):
        return False
    if field in NUMERIC:
        try:
            return math.isclose(float(left), float(right), rel_tol=0., abs_tol=1e-9)
        except (TypeError, ValueError):
            return False
    clean = lambda text: re.sub(r"\s+", " ", str(text).strip()).casefold()
    return clean(left) == clean(right)

def condition_updates(view, targets, values, *, names=None, source="人工输入", overwrite=True,
                      background_ph_edit=False):
    """Build one atomic patch set from the shared view; nothing is committed.

    For records still following linked samples, intents that merely restate the
    current effective value are removed together with their parameter_sources
    leaf.  The elimination only runs on a valid applied/candidate view; under an
    applied fallback every field is checked by the business layer instead.
    """
    records, configs = view["records"], view["configs"]
    eliminate = view["view_basis"] in ("applied", "candidate")
    updates = {}
    for ident in targets:
        record = records[ident]
        intended = copy.deepcopy(values)
        blocked = controlled_fields(record) if record.get("role") == "背景" else set()
        if eliminate and blocked:
            effective = configs[ident]
            sources = intended.get("parameter_sources")
            for field in list(intended):
                if field != "parameter_sources" and \
                        _same_condition_value(field, intended[field], effective.get(field)):
                    intended.pop(field)
                    if isinstance(sources, dict):
                        sources.pop(field, None)
            if isinstance(sources, dict) and not sources:
                intended.pop("parameter_sources", None)
        after = copy.deepcopy(record)
        try:
            apply_conditions(after, intended, source=source, overwrite=overwrite,
                             background_ph_edit=background_ph_edit)
        except (DataError, ValueError, TypeError) as exc:
            label = (names or {}).get(ident) or record.get("name") or ident
            raise DataError(f"{label}：{exc}") from exc
        patch = {field: copy.deepcopy(value) for field, value in after.items()
                 if field not in record or record[field] != value}
        if patch:
            updates[ident] = patch
    return updates

def effective_independent_values(info):
    """Only the currently active, known effective fields; None never clears caches."""
    values = {}
    for field in INHERITED_FIELDS:
        state = info.get("field_states", {}).get(field, {})
        value = info.get("effective", {}).get(field)
        if state.get("active") and value is not None:
            values[field] = deepcopy(value)
    return values

def stage_background_mode(workspace, ident, mode, *, domain=None, values=None, source_label="用户复制：当前有效条件"):
    """Replace condition-strategy intent atomically, preserving unrelated edits."""
    patch = {"background_conditions_mode": mode}
    if values:
        patch.update(deepcopy(values))
        patch["parameter_sources"] = {field: source_label for field in values}
    domain = domain or f"background_conditions:{ident}"
    keys = ("settings_draft", "rejected_config_edits", "draft_errors", "draft_error", "draft_retryable_domains")
    before = {key: deepcopy(workspace.state[key]) for key in keys if key in workspace.state}
    related = set(INHERITED_FIELDS) | {"background_conditions_mode", "background_ph_mode", "background_ph_legacy"}
    peers = {domain, f"background_conditions:{ident}", f"conditions:{ident}", f"background_ph:{ident}"}
    # Work on detached structures; only condition leaves for this background
    # are superseded by the explicit mode action. Area and other files survive.
    draft = deepcopy(workspace.state.settings_draft)
    rejected = deepcopy(workspace.state.get("rejected_config_edits", {}))
    errors = deepcopy(workspace.state.get("draft_errors", {}))
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
    workspace.state.settings_draft = draft
    workspace.state.rejected_config_edits = rejected
    workspace.state.draft_errors = errors
    if workspace.stage_config_updates(domain, {ident: patch}):
        return True
    failed = workspace.state.get("draft_error", "背景条件模式未能加入草稿。")
    for key in keys:
        if key in before:
            workspace.state[key] = before[key]
        else:
            workspace.state.pop(key, None)
    return workspace.reject_config_updates(domain, {ident:patch}, failed)
