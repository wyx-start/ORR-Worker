"""Explicit historical/missing-condition fixtures, independent of import defaults."""
from orr_core import default_config


def clear_potential_conditions(config):
    config.update(pH=None, reference="未设置", filling="", ref_V_SHE=None,
                  reference_source="用户输入", reference_preset_C=None)
    for field in ("pH", "reference", "filling", "ref_V_SHE", "reference_source", "reference_preset_C"):
        config.get("parameter_sources", {}).pop(field, None)
    return config


def unconfigured_config(trace):
    return clear_potential_conditions(default_config(trace))
