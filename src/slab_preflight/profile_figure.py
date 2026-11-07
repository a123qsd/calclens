"""Print-sized, vector-capable density profiles bound to a verified live result."""

from __future__ import annotations

from copy import deepcopy
import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen

from . import __version__
from .density_records import binding_digest
from .density_verification import with_reproducibility


def _power_text(exponent):
    return "×10" + str(exponent).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))


def _axis(values, *, include_zero=False, offset=False):
    """Scale coordinates before padding, so tiny/large constant fields stay finite."""
    low, high = float(values.min()), float(values.max())
    span = high - low
    origin = low if offset and span > 0 and abs(low) / span > 1000 else 0.0
    shifted = values - origin
    largest = float(np.max(np.abs(shifted)))
    exponent = math.floor(math.log10(largest)) if largest else 0
    exponent = max(-323, min(308, exponent)) if exponent < -2 or exponent > 3 else 0
    scale = 10.0 ** exponent
    normalized = shifted / scale
    low, high = float(normalized.min()), float(normalized.max())
    if include_zero:
        low, high = min(0.0, low), max(0.0, high)
        padding = (high - low) * .07 if high != low else 1.0
        low, high = low - padding, high + padding
    if not math.isfinite(low) or not math.isfinite(high) or high <= low:
        raise ValueError("The density plot needs a finite, resolvable coordinate range.")
    target = (high - low) / 4
    power = 10.0 ** math.floor(math.log10(target))
    step = next(candidate * power for candidate in (1, 2, 2.5, 5, 10)
                if candidate * power >= target * (1 - 1e-12))
    ticks = np.arange(math.ceil(low / step), math.floor(high / step) + 1) * step
    return {"values": normalized, "limits": (low, high), "ticks": ticks,
            "power10": exponent, "offset": origin}


def _plot_data(profile, quantity):
    if (profile.get("field_kind") not in ("density", "difference_density", "spin_density")
            or profile.get("units") != "e/angstrom^3"):
        raise ValueError("Publication density profiles require physical electron-density units.")
    if quantity == "average":
        x, y = profile.get("positions_angstrom"), profile.get("average_e_per_angstrom3")
        units, ylabel = "e/angstrom^3", "⟨Δρ⟩ (e/Å³)" if profile["field_kind"] == "difference_density" else "⟨ρ⟩ (e/Å³)"
        title = {"density": "Planar mean electron density",
                 "difference_density": "Planar mean density difference",
                 "spin_density": "Planar mean spin density"}[profile["field_kind"]]
    elif quantity == "cumulative":
        integration = profile.get("integration", {})
        x, y = integration.get("boundary_positions_angstrom"), integration.get("cumulative_e")
        units, ylabel = "e", "ΔN(z) (e)" if profile["field_kind"] == "difference_density" else "N(z) (e)"
        title = {"density": "Cumulative electron count",
                 "difference_density": "Cumulative density-difference count",
                 "spin_density": "Cumulative spin-density count"}[profile["field_kind"]]
    else:
        raise ValueError("Choose a planar mean or cumulative density figure.")
    try:
        x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    except (TypeError, ValueError) as error:
        raise ValueError("Missing or invalid density profile coordinates.") from error
    if (x.ndim != 1 or y.shape != x.shape or len(x) < 2
            or not np.isfinite(x).all() or not np.isfinite(y).all() or np.any(np.diff(x) <= 0)):
        raise ValueError("Density figures require matching finite values and increasing plane coordinates.")
    return x, y, units, ylabel, title


def _font(painter, dpi, points=8, *, bold=False):
    font = QFont("Arial")
    font.setPixelSize(max(1, round(points * dpi / 72)))
    font.setBold(bold)
    painter.setFont(font)


def _paint_profile(painter, width, height, dpi, data, source, axis_index):
    xaxis, yaxis, ylabel, title = data
    mm = dpi / 25.4
    rect = QRectF(15 * mm, 12.5 * mm, width - 20 * mm, height - 31.5 * mm)
    ink, grid = QColor("#111827"), QColor("#d6dce2")
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setPen(ink)
        _font(painter, dpi, 9, bold=True)
        painter.drawText(QRectF(5 * mm, 2.5 * mm, width - 10 * mm, 5 * mm),
                         Qt.AlignmentFlag.AlignCenter, title)
        _font(painter, dpi)
        xlow, xhigh = xaxis["limits"]
        ylow, yhigh = yaxis["limits"]

        def point(xx, yy):
            return QPointF(rect.left() + (xx - xlow) / (xhigh - xlow) * rect.width(),
                           rect.bottom() - (yy - ylow) / (yhigh - ylow) * rect.height())

        painter.setPen(QPen(grid, .13 * mm))
        for tick in xaxis["ticks"]:
            painter.drawLine(point(tick, ylow), point(tick, yhigh))
        for tick in yaxis["ticks"]:
            painter.drawLine(point(xlow, tick), point(xhigh, tick))
        painter.setPen(QPen(QColor("#64748b"), .22 * mm, Qt.PenStyle.DashLine))
        painter.drawLine(point(xlow, 0), point(xhigh, 0))
        painter.setPen(QPen(ink, .23 * mm))
        painter.drawRect(rect)
        for tick in xaxis["ticks"]:
            location = point(tick, ylow)
            painter.drawLine(location, location + QPointF(0, mm))
            painter.drawText(QRectF(location.x() - 7 * mm, rect.bottom() + mm, 14 * mm, 4 * mm),
                             Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, f"{tick:.5g}")
        for tick in yaxis["ticks"]:
            location = point(xlow, tick)
            painter.drawLine(location, location - QPointF(mm, 0))
            painter.drawText(QRectF(3 * mm, location.y() - 2 * mm, 10.5 * mm, 4 * mm),
                             Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{tick:.5g}")
        xlabel = "Projected coordinate z"
        if xaxis["offset"]:
            xlabel = f"z − ({xaxis['offset']:.17g} Å)"
        xlabel += f" ({_power_text(xaxis['power10'])} Å)" if xaxis["power10"] else " (Å)"
        painter.drawText(QRectF(rect.left() - 2 * mm, rect.bottom() + 5 * mm,
                               rect.width() + 4 * mm, 4 * mm), Qt.AlignmentFlag.AlignCenter, xlabel)
        painter.save()
        painter.translate(4 * mm, rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-rect.height() / 2, -2 * mm, rect.height(), 4 * mm),
                         Qt.AlignmentFlag.AlignCenter, ylabel)
        painter.restore()
        if yaxis["power10"]:
            painter.drawText(QRectF(rect.left(), rect.top() - 4 * mm, rect.width(), 4 * mm),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignBottom,
                             _power_text(yaxis["power10"]))
        painter.save()
        painter.setClipRect(rect.adjusted(-.2 * mm, -.2 * mm, .2 * mm, .2 * mm))
        painter.setPen(QPen(QColor("#075985"), .4 * mm,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path = QPainterPath(point(xaxis["values"][0], yaxis["values"][0]))
        for xx, yy in zip(xaxis["values"][1:], yaxis["values"][1:], strict=True):
            path.lineTo(point(xx, yy))
        painter.drawPath(path)
        painter.restore()
        painter.setPen(ink)
        for yy, text in ((height - 9 * mm, "Source: " + source["filename"]),
                         (height - 5 * mm, f"SHA-256: {source['source_sha256'][:16]}… · plane {'abc'[axis_index]}")):
            display = painter.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle,
                                                       round(width - 10 * mm))
            painter.drawText(QRectF(5 * mm, yy, width - 10 * mm, 4 * mm),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, display)
    finally:
        painter.restore()


def export_profile_figure(profile, record, path, *, binding, verification,
                          quantity="average", width_mm=85, dpi=300, transparent=False):
    """Export all retained samples; PDF text, axes and curve remain vector paths."""
    from .publication import write_print_figure

    expected = with_reproducibility(record)["reproducibility"]
    retained = record.get("reproducibility", {})
    if (profile != record.get("profile") or retained.get("manifest") != expected["manifest"]
            or retained.get("manifest_sha256") != expected["manifest_sha256"]
            or not isinstance(verification, dict) or verification.get("status") != "passed"
            or verification.get("record_manifest_sha256") != expected["manifest_sha256"]
            or binding.get("operation") != record.get("operation")
            or any(binding.get("dataset", {}).get(key) != record.get("dataset", {}).get(key)
                   for key in ("dataset_id", "source_sha256"))
            or binding.get("structure_sha256") != record.get("dataset", {}).get("structure_sha256")
            or binding.get("grid_plane_axis") != record.get("calculation", {}).get("grid_plane_axis")):
        raise ValueError("The figure needs the exact current profile, dataset binding and matching CPU verification.")
    axis = profile.get("axis")
    if type(axis) is not int or axis not in (0, 1, 2):
        raise ValueError("The retained density figure has no valid grid plane axis.")
    x, y, units, ylabel, title = _plot_data(profile, quantity)
    xaxis, yaxis = _axis(x, offset=True), _axis(y, include_zero=True)
    figure_binding = {
        "operation": record["operation"], "dataset": deepcopy(record["dataset"]),
        "calculation": deepcopy(record["calculation"]), "density_profile_sha256": binding_digest(profile),
        "record_manifest_sha256": expected["manifest_sha256"],
    }
    provenance = {
        "schema_version": 1, "kind": "density_profile_figure", "calclens_version": __version__,
        "source": deepcopy(record["dataset"]), "calculation": deepcopy(record["calculation"]),
        "density_record": deepcopy(record), "density_profile_sha256": binding_digest(profile),
        "density_record_manifest_sha256": expected["manifest_sha256"],
        "result_binding": figure_binding, "result_binding_sha256": binding_digest(figure_binding),
        "verification": deepcopy(verification),
        "figure": {"kind": "density_profile", "chart_rendering": "vector paths and text on PDF",
                   "font_size_points": {"labels": 8, "title": 9}},
        "plot": {"quantity": quantity, "field_kind": profile["field_kind"],
                 "x_units": "angstrom", "y_units": units, "sample_count": len(x),
                 "title": title, "x_label": "Projected normal coordinate", "y_label": ylabel,
                 "zero_reference": True, "line_rendering": "all retained samples; no resampling or smoothing",
                 "axes": {name: {key: value.tolist() if isinstance(value, np.ndarray) else value
                                 for key, value in axis_data.items() if key != "values"}
                          for name, axis_data in (("x", xaxis), ("y", yaxis))},
                 "cumulative_convention": profile.get("integration", {}).get("convention")
                 if quantity == "cumulative" else None},
    }

    def paint(painter, width, height):
        _paint_profile(painter, width, height, dpi, (xaxis, yaxis, ylabel, title),
                       record["dataset"], axis)

    return write_print_figure(path, width_mm=width_mm, dpi=dpi, transparent=transparent,
                              record=provenance, paint=paint)
