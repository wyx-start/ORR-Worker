"""Initial native curve preparation; preserves the scientific processing snapshot."""
from application.data import axis_label, merged_data
from application.figures import new_figure, figure_bytes
from orr_core import DataError, json_bytes
from origin_export import curve_plot_table, csv_bytes


def calculate_curves(workspace, selected):
    workspace.clear_polarization_exports()
    configs, settings = workspace.pending_candidate()
    outputs, errors = workspace.process_selected(selected, configs, settings, channels="disk")
    if not outputs:
        raise DataError("没有可处理的曲线。" + "；".join(e["原因"] for e in errors))
    fig = new_figure();ax = fig.subplots()
    plotted = {}
    for ident, output in outputs.items():
        frame = output["data"].copy()
        frame["plotted_current_value"] = frame["I_disk_mA"]
        frame["plotted_current_unit"] = "mA"
        plotted[ident] = dict(output, data=frame, plot_channel="disk", plot_smoothing_enabled=False)
        ax.plot(frame.E_V, frame.I_disk_mA, label=output["config"]["name"])
    ax.set(xlabel=axis_label(outputs), ylabel="I / mA", title="ORR polarization curves")
    ax.legend(frameon=False)
    png, svg = figure_bytes(fig)
    wide = curve_plot_table(plotted)
    params = workspace.parameters(outputs)
    workspace.apply_pending_settings()
    for name, payload, mime in (("polarization_plot.csv", csv_bytes(wide), "text/csv"),
            ("polarization_data.csv", csv_bytes(merged_data(outputs)), "text/csv"),
            ("polarization.png", png, "image/png"), ("polarization.svg", svg, "image/svg+xml"),
            ("parameters.json", json_bytes(params), "application/json")):
        workspace.set_export(name, payload, mime)
    result = dict(figure=fig, outputs=outputs, errors=errors, plot=wide, revision=workspace.state.revision)
    # The service does not store a UI canvas or figure in workspace state.
    workspace.state.results["curves"] = {k:v for k,v in result.items() if k!="figure"}
    return result
