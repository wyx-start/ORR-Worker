"""Figure utilities without selecting a global Matplotlib backend or importing UI."""
from io import BytesIO
import matplotlib
from matplotlib.figure import Figure


def figure_style():
    matplotlib.rcParams.update({"font.family":"sans-serif", "font.sans-serif":["Microsoft YaHei", "DejaVu Sans"],
        "axes.unicode_minus":False, "font.size":10, "svg.fonttype":"none",
        "axes.spines.top":False, "axes.spines.right":False})


def figure_bytes(fig):
    png, svg = BytesIO(), BytesIO()
    fig.savefig(png, format="png", dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(svg, format="svg", bbox_inches="tight", facecolor="white")
    return png.getvalue(), svg.getvalue()


def new_figure(width=8., height=5.):
    figure_style()
    return Figure(figsize=(width, height), layout="constrained")
