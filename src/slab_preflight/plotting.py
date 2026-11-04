"""Local Plotly views of nuclear positions, without inferred chemical bonds."""
from __future__ import annotations

from itertools import product

import numpy as np
import plotly.graph_objects as go

COLORS = {"C": "#334155", "B": "#F0806A", "N": "#4C78E8", "Mo": "#9065C9", "S": "#E7B62C", "H": "#9DAFBF", "O": "#D95D68"}


def structure_figure(report: dict, repeats: int = 2, show_cell: bool = False, korean: bool = True) -> go.Figure:
    """Repeat only a/b for display; analyses always refer to the input cell."""
    cell = np.asarray(report["cell"], dtype=float)
    positions = np.asarray(report["positions"], dtype=float)
    elements = report["elements"]
    fig = go.Figure()
    for symbol in dict.fromkeys(elements):
        points, labels = [], []
        for u, v in product(range(repeats), repeat=2):
            for index, element in enumerate(elements):
                if element == symbol:
                    points.append(positions[index] + u * cell[0] + v * cell[1])
                    labels.append([index + 1, u, v])
        xyz = np.asarray(points)
        fig.add_trace(go.Scatter3d(
            x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2], name=symbol, mode="markers",
            marker=dict(size=9, color=COLORS.get(symbol, "#169F95"), opacity=0.95, line=dict(color="#FFFFFF", width=0.7)),
            customdata=labels,
            hovertemplate=(f"<b>{symbol}</b> · " + ("원자" if korean else "site") + " %{customdata[0]}<br>"
                           "x %{x:.3f} Å · y %{y:.3f} Å · z %{z:.3f} Å<br>"
                           + ("표시 이동" if korean else "display shift") + " [%{customdata[1]}, %{customdata[2]}, 0]<extra></extra>"),
        ))
    if show_cell:
        corners = list(product((0, 1), repeat=3))
        x, y, z = [], [], []
        for a, p in enumerate(corners):
            for q in corners[a + 1:]:
                if sum(i != j for i, j in zip(p, q)) == 1:
                    ends = np.asarray([p, q]) @ cell
                    x.extend([*ends[:, 0], None])
                    y.extend([*ends[:, 1], None])
                    z.extend([*ends[:, 2], None])
        fig.add_trace(go.Scatter3d(x=x, y=y, z=z, mode="lines", line=dict(color="#8A9DAD", width=3), name="입력 셀" if korean else "Input cell", hoverinfo="skip"))
    scene = dict(
        xaxis=dict(title="x / Å", backgroundcolor="#F6F9FC", gridcolor="#DFE7EF"),
        yaxis=dict(title="y / Å", backgroundcolor="#F6F9FC", gridcolor="#DFE7EF"),
        zaxis=dict(title="z / Å", backgroundcolor="#F6F9FC", gridcolor="#DFE7EF"),
        aspectmode="data", camera=dict(eye=dict(x=1.6, y=1.6, z=1.1)),
    )
    fig.update_layout(height=470, margin=dict(l=0, r=0, t=5, b=0), scene=scene, paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", x=0, y=1), font=dict(color="#334155"), uirevision=f"{report['formula']}-{repeats}-{show_cell}")
    return fig


def profile_figure(report: dict, korean: bool = True) -> go.Figure:
    """Show wrapped c-normal nuclear positions and the largest cyclic empty gap."""
    metrics = report["metrics"]
    height = metrics["c_height_angstrom"]
    z = np.asarray(report["scaled_positions"])[:, 2] % 1 * height
    fig = go.Figure()
    for row, symbol in enumerate(dict.fromkeys(report["elements"])):
        indexes = [i for i, element in enumerate(report["elements"]) if element == symbol]
        fig.add_trace(go.Scatter(x=z[indexes], y=[symbol] * len(indexes), mode="markers", name=symbol, marker=dict(size=14, color=COLORS.get(symbol, "#169F95")), customdata=[i + 1 for i in indexes], hovertemplate=("원자" if korean else "Site") + " %{customdata}<br>%{x:.3f} Å<extra>%{y}</extra>"))
    start = metrics["gap_start_fraction"] * height
    end = metrics["gap_end_fraction"] * height
    if end > start:
        ranges = [(start, end)]
    else:
        ranges = [(start, height), (0, end)]
    for x0, x1 in ranges:
        if x1 > x0:
            fig.add_vrect(x0=x0, x1=x1, fillcolor="#15A89A", opacity=0.13, line_width=0, layer="below")
    fig.update_layout(height=230, margin=dict(l=10, r=15, t=5, b=40), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#F6F9FC", font=dict(color="#334155"), xaxis=dict(title="c 수직 방향 위치 / Å" if korean else "Position along the c normal / Å", range=[0, height], gridcolor="#DFE7EF"), yaxis=dict(title="", type="category"))
    return fig
