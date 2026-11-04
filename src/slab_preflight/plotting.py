"""Local views of nuclei, true periodic-image contacts and geometric gaps."""
from __future__ import annotations

from itertools import product

import numpy as np
import plotly.graph_objects as go

COLORS = {"C": "#3B5267", "B": "#D9876A", "N": "#587AC8", "Mo": "#8E76B7", "S": "#D9B442", "H": "#9DAFBF", "O": "#C96C77"}


def _normal(report: dict) -> tuple[int, str, float]:
    index = report.get("normal_axis_index", 2)
    axis = report.get("normal_axis", "c")
    height = report["metrics"].get("normal_height_angstrom", report["metrics"]["c_height_angstrom"])
    return index, axis, height


def gap_intervals(report: dict) -> list[tuple[float, float]]:
    """Return wrapped fractional intervals; equal ends mean one full period."""
    metrics = report["metrics"]
    start, end = metrics["gap_start_fraction"], metrics["gap_end_fraction"]
    ranges = [(start, end)] if end > start else [(start, 1.0), (0.0, end)]
    return [(lo, hi) for lo, hi in ranges if hi > lo]


def structure_figure(
    report: dict, repeats: int = 2, show_cell: bool = True, korean: bool = True,
    highlighted_atoms: list[int] | None = None, selected_contact: dict | None = None,
    highlight_gap: bool = False,
) -> go.Figure:
    """Render true Cartesian geometry; repeats affect only the selected plane."""
    cell = np.asarray(report["cell"], dtype=float)
    positions = np.asarray(report["positions"], dtype=float)
    elements = report["elements"]
    normal_index, normal_axis, _ = _normal(report)
    plane = [i for i in range(3) if i != normal_index]
    fig = go.Figure()
    for symbol in dict.fromkeys(elements):
        points, labels = [], []
        for u, v in product(range(repeats), repeat=2):
            shift = np.zeros(3, dtype=int)
            shift[plane] = [u, v]
            for index, element in enumerate(elements):
                if element == symbol:
                    points.append(positions[index] + shift @ cell)
                    labels.append([index + 1, *shift.tolist()])
        xyz = np.asarray(points)
        fig.add_trace(go.Scatter3d(
            x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2], name=symbol, mode="markers",
            marker=dict(size=9, color=COLORS.get(symbol, "#169F95"), opacity=0.95, line=dict(color="#FFFFFF", width=0.7)),
            customdata=labels, meta={"role": "sites", "element": symbol},
            hovertemplate=(f"<b>{symbol}</b> · " + ("원자" if korean else "site") + " %{customdata[0]}<br>"
                           "x %{x:.3f} Å · y %{y:.3f} Å · z %{z:.3f} Å<br>"
                           + ("표시 이동" if korean else "display shift") + " [%{customdata[1]}, %{customdata[2]}, %{customdata[3]}]<extra></extra>"),
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
        fig.add_trace(go.Scatter3d(x=x, y=y, z=z, mode="lines", line=dict(color="#8295A6", width=3), name="입력 셀" if korean else "Input cell", hoverinfo="skip", meta={"role": "cell"}))
    selected = sorted(set(highlighted_atoms or []))
    if selected:
        xyz = positions[selected]
        fig.add_trace(go.Scatter3d(
            x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2], mode="markers", name="선택 원자" if korean else "Selected sites",
            marker=dict(size=14, color="#D45B61", symbol="circle-open", line=dict(color="#D45B61", width=4)),
            customdata=[i + 1 for i in selected], meta={"role": "selected_atoms", "atom_indices": selected},
            hovertemplate=("선택 원자" if korean else "Selected site") + " %{customdata}<extra></extra>",
        ))
    if selected_contact is not None:
        i, j = selected_contact["i"], selected_contact["j"]
        shift = np.asarray(selected_contact["shift"], dtype=int)
        start = positions[i]
        end = positions[j] + shift @ cell
        fig.add_trace(go.Scatter3d(
            x=[start[0], end[0]], y=[start[1], end[1]], z=[start[2], end[2]], mode="lines",
            line=dict(color="#D45B61", width=7), name="선택 거리" if korean else "Selected distance",
            meta={"role": "contact_line", "i": i, "j": j, "shift": shift.tolist()},
            hovertemplate=f"{elements[i]}{i+1} → {elements[j]}{j+1} {shift.tolist()}<br>{selected_contact['distance_angstrom']:.6f} Å<extra></extra>",
        ))
        fig.add_trace(go.Scatter3d(
            x=[end[0]], y=[end[1]], z=[end[2]], mode="markers", name="거리 측정 상대상" if korean else "Distance partner image",
            marker=dict(size=13, color="#D45B61", symbol="diamond-open", line=dict(color="#D45B61", width=3)),
            meta={"role": "contact_image", "atom_index": j, "shift": shift.tolist()},
            hovertemplate=f"{elements[j]}{j+1} + {shift.tolist()}<br>x %{{x:.4f}} Å · y %{{y:.4f}} Å · z %{{z:.4f}} Å<extra></extra>",
        ))
        midpoint = (start + end) / 2
        fig.add_trace(go.Scatter3d(
            x=[midpoint[0]], y=[midpoint[1]], z=[midpoint[2]], mode="text",
            text=[f"{selected_contact['distance_angstrom']:.4f} Å"],
            textposition="top center", textfont=dict(color="#B43D48", size=13),
            hoverinfo="skip", showlegend=False, meta={"role": "contact_distance_label"},
        ))
    if highlight_gap:
        color = "#D6A14B" if report.get("gap_review_required", False) else "#239D93"
        # Each box is built in fractional coordinates, then transformed to the
        # full input lattice. This also works when the selected normal is a/b.
        triangles = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1), (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
        for lo, hi in gap_intervals(report):
            corners = np.asarray(list(product((0.0, 1.0), repeat=3)))
            corners[:, normal_index] = lo + corners[:, normal_index] * (hi - lo)
            xyz = corners @ cell
            fig.add_trace(go.Mesh3d(
                x=xyz[:, 0], y=xyz[:, 1], z=xyz[:, 2],
                i=[p[0] for p in triangles], j=[p[1] for p in triangles], k=[p[2] for p in triangles],
                color=color, opacity=0.13, flatshading=True, name="선택 핵 간격" if korean else "Selected nuclear gap", showlegend=False,
                meta={"role": "gap", "normal_axis": normal_axis, "fraction_range": [lo, hi]},
                hovertemplate=("핵이 없는 기하 간격" if korean else "Geometric interval without nuclei") + f"<br>{normal_axis}: {lo:.4f}–{hi:.4f}<extra></extra>",
            ))
    axis_style = dict(showbackground=True, backgroundcolor="#FBFCFD", gridcolor="#E8EDF1", zerolinecolor="#CBD5DD", color="#778696")
    scene = dict(
        xaxis=dict(title="x / Å", **axis_style), yaxis=dict(title="y / Å", **axis_style), zaxis=dict(title="z / Å", **axis_style),
        aspectmode="data", camera=dict(eye=dict(x=1.6, y=1.6, z=1.1)),
    )
    fig.update_layout(height=440, margin=dict(l=0, r=0, t=0, b=0), scene=scene, paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", x=0, y=1.02, font=dict(size=11)), font=dict(color="#334155"), uirevision=f"{report['formula']}-{normal_axis}-{repeats}-{show_cell}")
    return fig


def profile_figure(report: dict, korean: bool = True, highlight_gap: bool = True) -> go.Figure:
    """Show selected-normal nuclei and the same cyclic gap as the 3D view."""
    normal_index, normal_axis, height = _normal(report)
    positions = np.asarray(report["scaled_positions"])[:, normal_index] % 1 * height
    fig = go.Figure()
    for symbol in dict.fromkeys(report["elements"]):
        indexes = [i for i, element in enumerate(report["elements"]) if element == symbol]
        fig.add_trace(go.Scatter(x=positions[indexes], y=[symbol] * len(indexes), mode="markers", name=symbol, marker=dict(size=11, color=COLORS.get(symbol, "#169F95")), customdata=[i + 1 for i in indexes], hovertemplate=("원자" if korean else "Site") + " %{customdata}<br>%{x:.3f} Å<extra>%{y}</extra>"))
    color = "#D6A14B" if report.get("gap_review_required", False) else "#239D93"
    for lo, hi in gap_intervals(report):
        fig.add_vrect(x0=lo * height, x1=hi * height, fillcolor=color if highlight_gap else "#8C9CAA", opacity=0.19 if highlight_gap else 0.08, line_width=1 if highlight_gap else 0, line_color=color, layer="below")
    fig.update_layout(height=180, margin=dict(l=5, r=10, t=0, b=35), showlegend=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#FBFCFD", font=dict(color="#657585", size=11), xaxis=dict(title=f"{normal_axis} " + ("수직 방향 / Å" if korean else "normal direction / Å"), range=[0, height], gridcolor="#E4EBEF"), yaxis=dict(title="", type="category"))
    return fig
