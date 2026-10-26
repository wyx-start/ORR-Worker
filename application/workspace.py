"""Frontend-independent workspace. Stored records and effective views stay separate."""
from copy import deepcopy
from background_conditions import canonical_configs, resolved_configs
from orr_core import DataError, default_config, parameter_record, parse_chi, process_trace, migrate_background_config
from application.data import csv_bytes

class State(dict):
    def __getattr__(self, key):
        try: return self[key]
        except KeyError as exc: raise AttributeError(key) from exc
    def __setattr__(self, key, value): self[key] = value

def _overlay(base, patch):
    result = deepcopy(base)
    for key, value in patch.items():
        result[key] = _overlay(result.get(key, {}), value) if isinstance(value, dict) else deepcopy(value)
    return result

def _difference(value, base):
    result = {}
    for key, item in value.items():
        if isinstance(item, dict):
            nested = _difference(item, base.get(key, {}) if isinstance(base.get(key), dict) else {})
            if nested:
                result[key] = nested
        elif item != base.get(key):
            result[key] = deepcopy(item)
    return result

class Workspace:
    def __init__(self, state=None):
        self.state = state if state is not None else State()
        self.initialize()

    def snapshot(self):
        """Detached workspace for non-UI processing; never shares mutable records."""
        return Workspace(State(deepcopy(dict(self.state))))

    def project_bytes(self):
        from orr_core import pack_project
        self.apply_pending_settings()
        return pack_project(self.state.traces, self.state.configs, self.state.settings)

    def restore_project(self, raw, *, discard=False):
        from orr_core import unpack_project
        if self.has_draft() and not discard:
            raise DataError("请先应用或放弃草稿，再替换项目。")
        traces, configs, settings = unpack_project(raw)
        # Decode and validate before changing any part of the current workspace.
        self.state.traces, self.state.configs, self.state.settings = traces, configs, settings
        self.state.common_defaults = {}
        self.state.import_errors = []
        self.state.workspace_epoch += 1
        self.invalidate()

    def calculate_rrde(self, selected):
        from application.analysis import calculate_rrde
        return calculate_rrde(self, selected)

    def calculate_kl(self, inputs):
        from application.analysis import calculate_kl
        return calculate_kl(self, inputs)

    def remove_files(self, identifiers):
        if self.has_draft():raise DataError("请先应用或放弃草稿，再移除文件。")
        identifiers=set(identifiers)
        for ident in identifiers:
            self.state.traces.pop(ident,None);self.state.configs.pop(ident,None)
        for config in self.state.configs.values():
            for field in ('background_disk','background_ring'):
                if config.get(field) in identifiers:config[field]=None
        self.invalidate()

    def initialize(self):
        defaults = {"traces": {}, "configs": {}, "revision": 0, "results": {}, "exports": {},
                    "import_errors": [], "settings": {"axis": "RHE", "kl": {}, "plot": {}, "presets": {}},
                    "common_defaults": {}}
        for key, value in defaults.items():
            self.state.setdefault(key, value)
        from settings_draft import new_draft
        self.state.setdefault("settings_draft", new_draft(self.state.revision))
        self.state.setdefault("draft_epoch", 0)
        self.state.setdefault("workspace_epoch", 0)
        if any("background_conditions_mode" not in cfg for cfg in self.state.configs.values()):
            self.state.configs = {
                ident: migrate_background_config(cfg, schema=1)
                if "background_conditions_mode" not in cfg else cfg
                for ident, cfg in self.state.configs.items()}
            # Migration preserves scientific values and pending edit domains, but
            # previously generated exports do not carry the new audit structure.
            self.state.results = {}
            self.state.exports = {}
            self.state.settings_notice = "旧会话已按兼容规则恢复，独立记录及草稿保留；分析结果请重新生成。"

    def get_draft_view(self):
        """One detached source for records, effective conditions and provenance.

        Failure displays the actual applied snapshot. Accepted and rejected edit
        domains remain separately accessible; this view is never an apply fallback.
        """
        from settings_draft import candidate
        errors = [{"domain": domain, "message": str(message)}
                  for domain, message in self.state.get("draft_errors", {}).items()]
        summary = self.state.get("draft_error")
        if summary and not errors:
            errors.append({"domain": None, "message": str(summary)})
        rejected = deepcopy(self.state.get("rejected_config_edits", {}))
        rejected_domains = list(dict.fromkeys([item["domain"] for item in errors if item["domain"] is not None]
                                              + list(rejected)))
        draft = self.state.settings_draft
        records = canonical_configs(self.state.configs)
        settings = deepcopy(self.state.settings)
        try:
            pending = self.has_draft()
        except (DataError, ValueError, TypeError) as exc:
            pending = True
            errors.append({"domain": None, "message": str(exc)})
        if isinstance(draft, dict) and draft.get("base_revision") != self.state.revision:
            pending = True
            errors.append({"domain": None, "message": "草稿基于旧修订，请核对或放弃草稿后重新编辑。"})
        basis = "applied_fallback" if errors or rejected else "applied"
        if pending and not errors and not rejected:
            try:
                records, settings = candidate(draft, self.state.traces, records,
                                              settings, self.state.revision)
                basis = "candidate"
            except (DataError, ValueError, TypeError, IndexError) as exc:
                errors.append({"domain": None, "message": str(exc)})
                basis = "applied_fallback"
        configs = resolved_configs(records, {ident: trace.name for ident, trace in self.state.traces.items()})
        return {"view_basis": basis, "revision": self.state.revision,
                "has_pending": pending or bool(errors or rejected), "records": records,
                "configs": configs, "settings": settings, "errors": errors,
                "rejected_domains": rejected_domains,
                "staged_edits": deepcopy(draft.get("configs", {})) if isinstance(draft, dict) else {},
                "staged_setting_edits": deepcopy(draft.get("settings", {})) if isinstance(draft, dict) else {},
                "rejected_edits": rejected}

    def get_draft_configs(self):
        return self.get_draft_view()["configs"]

    def get_draft_settings(self):
        return self.get_draft_view()["settings"]

    def get_edit_configs(self, domain=None):
        """Unresolved records for controls only, including one rejected domain."""
        result = canonical_configs(self.state.configs)
        stages = list(self.state.settings_draft.get("configs", {}).values())
        if domain is not None:
            stages.append(self.state.get("rejected_config_edits", {}).get(domain, {}))
        for files in stages:
            for ident, patch in files.items():
                if ident in result:
                    result[ident] = _overlay(result[ident], patch)
        return result

    def get_edit_settings(self):
        """Raw settings for repairing controls only; never use for processing."""
        result = deepcopy(self.state.settings)
        for patch in self.state.settings_draft.get("settings", {}).values():
            result = _overlay(result, patch)
        return result

    def has_draft(self):
        from settings_draft import has_changes
        return has_changes(self.state.settings_draft) or bool(
            self.state.get("draft_error") or self.state.get("draft_errors")
            or self.state.get("rejected_config_edits"))

    def _draft_error_summary(self):
        errors = self.state.get("draft_errors", {})
        if errors:
            self.state.draft_error = "；".join(errors.values())
        else:
            self.state.pop("draft_error", None)

    def reject_config_updates(self, domain, updates_by_id, message, *, _retryable=False):
        """Keep a failed editor operation visible without accepting any target."""
        self.state.setdefault("draft_errors", {})[domain] = str(message)
        if updates_by_id is not None:
            self.state.setdefault("rejected_config_edits", {})[domain] = deepcopy(updates_by_id)
        self.state.setdefault("draft_retryable_domains", {})[domain] = _retryable
        self._draft_error_summary()
        return False

    def stage_config_updates(self, domain, updates_by_id, _retry=True, *, replace=False, replace_domain=False, retain_intent=False):
        from settings_draft import candidate, DraftConflictError, stage_config, validate_config_patch
        draft = deepcopy(self.state.settings_draft)
        try:
            if replace_domain:
                draft.get("configs", {}).pop(domain, None)
            if not isinstance(updates_by_id, dict):
                raise DataError("文件修改必须是按文件标识组织的字典。")
            stored = canonical_configs(self.state.configs)
            for ident, updates in updates_by_id.items():
                if ident not in stored:
                    raise DataError("修改引用的文件已不存在。")
                if not isinstance(updates, dict):
                    raise DataError("文件修改内容必须是字典。")
                old = draft.get("configs", {}).get(domain, {}).pop(ident, {})
                combined = deepcopy(updates) if replace else _overlay(old, updates)
                validate_config_patch(self.state.traces[ident], stored[ident], combined)
                patch = combined if retain_intent else _difference(combined, stored[ident])
                if patch:
                    stage_config(draft, domain, ident, patch)
            if not _retry:
                # Only re-accept a previously conflicting operation when the whole
                # proposed record is now valid. An unrelated edit must not clear a
                # local validation error just because staging accepts raw numbers.
                candidate(draft, self.state.traces, stored,
                          self.state.settings, self.state.revision)
            self.state.settings_draft = draft
            self.state.setdefault("draft_errors", {}).pop(domain, None)
            self.state.setdefault("rejected_config_edits", {}).pop(domain, None)
            self.state.setdefault("draft_retryable_domains", {}).pop(domain, None)
            self._draft_error_summary()
            if _retry:
                for rejected_domain, values in list(self.state.get("rejected_config_edits", {}).items()):
                    if self.state.get("draft_retryable_domains", {}).get(rejected_domain):
                        self.stage_config_updates(rejected_domain, values, _retry=False)
            return True
        except (DataError, ValueError, TypeError) as exc:
            return self.reject_config_updates(domain, updates_by_id, exc,
                                         _retryable=isinstance(exc, DraftConflictError) and not replace and not retain_intent)

    def stage_settings_updates(self, domain, updates):
        from settings_draft import stage_settings
        draft = deepcopy(self.state.settings_draft)
        try:
            old = draft.get("settings", {}).pop(domain, {})
            patch = _difference(_overlay(old, updates), self.state.settings)
            if patch:
                stage_settings(draft, domain, patch)
            self.state.settings_draft = draft
            self.state.setdefault("draft_errors", {}).pop(domain, None)
            self._draft_error_summary()
        except (DataError, ValueError, TypeError) as exc:
            self.state.setdefault("draft_errors", {})[domain] = str(exc)
            self._draft_error_summary()

    def pending_candidate(self):
        from settings_draft import candidate
        if (self.state.get("draft_error") or self.state.get("draft_errors")
                or self.state.get("rejected_config_edits")):
            raise DataError(self.state.get("draft_error") or "仍有未修正的编辑域，请核对错误与拒绝输入。")
        if self.state.settings_draft.get("base_revision") != self.state.revision:
            raise DataError("草稿基于旧修订，请核对或放弃草稿后重新编辑。")
        if not self.has_draft():
            return canonical_configs(self.state.configs), deepcopy(self.state.settings)
        return candidate(self.state.settings_draft, self.state.traces,
                         self.state.configs, self.state.settings, self.state.revision)

    def apply_pending_settings(self, preflight=None):
        """Validate one immutable candidate, then commit both configs and settings."""
        dirty = self.has_draft()
        configs, settings = self.pending_candidate()
        if preflight is not None:
            preflight(configs, settings)
        if not dirty:
            return True
        self.state.configs = configs
        self.state.settings = settings
        self.invalidate()
        self.state.settings_notice = "设置已应用；受影响的分析结果需重新计算。"
        return True

    def reset_draft(self):
        from settings_draft import new_draft
        self.state.settings_draft = new_draft(self.state.revision)
        self.state.draft_epoch = self.state.get("draft_epoch", 0)+1
        self.state.pop("draft_error", None)
        self.state.pop("draft_errors", None)
        self.state.pop("rejected_config_edits", None)
        self.state.pop("draft_retryable_domains", None)

    def process_selected(self, ids, configs=None, settings=None, channels="all", subtract_background=True):
        configs = configs if configs is not None else self.state.configs
        settings = settings if settings is not None else self.state.settings
        outputs, errors = {}, []
        for ident in ids:
            if ident not in configs or configs[ident].get("role") == "背景":
                continue
            try:
                outputs[ident] = process_trace(self.state.traces[ident], configs[ident],
                    self.state.traces, configs, settings.get("axis", "RHE"),
                    channels=channels, subtract_background=subtract_background)
            except (DataError, ValueError, TypeError, IndexError) as exc:
                errors.append({"文件":self.state.traces[ident].name, "原因":str(exc)})
        return outputs, errors

    def invalidate(self):
        self.state.revision += 1
        self.state.results = {}
        self.state.exports = {}
        self.state.settings.get("plot", {}).pop("smoothing_report", None)
        self.reset_draft()

    def clear_polarization_exports(self, channel="disk"):
        # Display changes must not invalidate K–L or RRDE calculations.
        names = (("polarization.png", "polarization.svg", "polarization_data.csv", "polarization_plot.csv", "parameters.json") if channel == "disk"
                 else ("ring_current.png", "ring_current.svg", "ring_current_data.csv", "ring_current_plot.csv", "ring_current_parameters.json"))
        for name in names:
            self.state.exports.pop(name, None)
        self.state.exports.pop("parameters.json", None)
        self.state.settings.get("plot" if channel == "disk" else "ring_plot", {}).pop("smoothing_report", None)
        if channel == "ring":
            self.state.settings.get("ring_plot", {}).pop("comparison_audit", None)

    def cached_parse(self, name, raw):
        return parse_chi(name, raw)

    def add_files(self, files):
        if self.has_draft() or self.state.get("draft_error"):
            raise DataError("有未应用修改。请先应用或放弃草稿，再导入新文件；现有草稿已保留。")
        errors = []
        added = 0
        for name, raw in files:
            try:
                trace = self.cached_parse(name, raw)
                if trace.id not in self.state.traces:
                    self.state.traces[trace.id] = trace
                    cfg = default_config(trace)
                    self.state.configs[trace.id] = cfg
                    added += 1
            except (DataError, ValueError, TypeError) as exc:
                errors.append({"文件": name, "原因": str(exc)})
        self.state.import_errors = errors
        if added:
            self.invalidate()
        return added

    def label(self, ident):
        return self.state.traces[ident].name + " · " + ident[:4]

    def file_formatter(self, empty_label="不扣除"):
        # A stable snapshot also works when Streamlit deserializes widget options off-thread.
        labels = {ident:trace.name + " · " + ident[:4] for ident, trace in self.state.traces.items()}
        return lambda ident: empty_label if ident in (None, "") else labels.get(ident, str(ident))

    def process_all(self, axis=None, channels="all", subtract_background=True):
        axis = axis or self.state.settings.get("axis", "RHE")
        outputs, errors = {}, []
        for ident, trace in self.state.traces.items():
            cfg = self.state.configs[ident]
            if cfg.get("role") == "背景":
                continue
            try:
                outputs[ident] = process_trace(trace, cfg, self.state.traces, self.state.configs, axis,
                                               channels=channels, subtract_background=subtract_background)
            except (DataError, ValueError, TypeError, IndexError) as exc:
                errors.append({"文件": trace.name, "原因": str(exc)})
        return outputs, errors

    def parameters(self, outputs=None):
        return parameter_record(self.state.traces, self.state.configs,
                                self.state.settings, outputs)

    def set_export(self, name, content, mime):
        self.state.exports[name] = {"bytes": content, "mime": mime}

    def store_table(self, name, frame):
        payload = csv_bytes(frame)
        self.set_export(name, payload, "text/csv")
        return payload
