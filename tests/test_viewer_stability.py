"""Camera, logical overlays and pointer regressions from the 0.9.1 audit."""
import math
import os
import json
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from slab_preflight.core import analyze_cif
from slab_preflight.desktop_raster import Primitive, rasterize
from slab_preflight.desktop_view import GRAPHICS_PRESETS, StructureView


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def view(application):
    widget = StructureView(language="en")
    widget.resize(800, 560)
    widget.set_graphics_quality("balanced")
    widget.set_structure(analyze_cif((ROOT / "examples/graphene.cif").read_bytes()))
    yield widget
    widget.close()


def test_rotation_preserves_scale_pivot_and_physical_geometry(view):
    rect = QRectF(0, 0, 800, 480)
    positions, cell = view.positions.copy(), view.cell.copy()
    scales, pivots = [], []
    for yaw, pitch, roll in ((0, 0, 0), (0.55, -0.35, 0), (2.1, -math.pi / 2, 0.7)):
        view.yaw, view.pitch, view.roll = yaw, pitch, roll
        project, scale, _ = view._projection(rect)
        scales.append(scale)
        pivots.append(project([view.view_state()["camera_center"]])[0][0])
    np.testing.assert_allclose(scales, scales[0], rtol=1e-12)
    np.testing.assert_allclose(pivots, np.tile([400, 240], (3, 1)), atol=1e-10)
    np.testing.assert_array_equal(view.positions, positions)
    np.testing.assert_array_equal(view.cell, cell)
    assert np.linalg.norm(positions[1] - positions[0]) == pytest.approx(1.42028, abs=1e-4)
    assert math.degrees(math.acos(np.dot(cell[0], cell[1]) / np.prod(np.linalg.norm(cell[:2], axis=1)))) == pytest.approx(120)


def test_atom_fit_accounts_for_spacefill_radius_at_every_rotation(view):
    view.show_cell = False
    view.set_representation("spacefill")
    view.fit_atoms()
    rect = QRectF(0, 0, 800, 480)
    for yaw, pitch in ((0, 0), (0.8, -0.65), (2.1, -math.pi / 2)):
        view.yaw, view.pitch = yaw, pitch
        project, scale, corners = view._projection(rect)
        primitives, _, _ = view._scene_primitives(project, scale, corners, GRAPHICS_PRESETS["balanced"], 1, False)
        for primitive in primitives:
            if primitive.kind == "sphere":
                x, y = primitive.points[0, :2]
                assert primitive.radius <= x <= rect.width() - primitive.radius
                assert primitive.radius <= y <= rect.height() - primitive.radius


def test_measurement_fit_includes_both_periodic_image_shifts_and_retains_camera_until_requested(view):
    state = view.view_state()
    contact = {"i": 0, "j": 1, "start_shift": [-3, 2, 0], "end_shift": [4, -2, 1], "distance_angstrom": 20}
    view.set_contact(contact)
    assert view.view_state() == state
    assert view.fit_measurement()
    endpoints = np.array([view.positions[0] + np.array(contact["start_shift"]) @ view.cell,
                          view.positions[1] + np.array(contact["end_shift"]) @ view.cell])
    for yaw, pitch in ((0, 0), (1.2, -0.4), (-1, -1.5)):
        view.yaw, view.pitch = yaw, pitch
        project, _, _ = view._projection(QRectF(0, 0, 800, 480))
        xy, _ = project(endpoints)
        assert np.all(xy >= 12)
        assert np.all(xy <= [788, 468])


def test_camera_and_large_pan_roundtrip(view, application):
    view.fit_atoms()
    view.pan = np.array([4567.25, -8910.5])
    view.yaw, view.pitch, view.roll, view.zoom = 0.8, 0.4, 0.2, 1.5
    state = view.view_state()
    other = StructureView(language="en")
    try:
        other.resize(view.size())
        other.set_structure(view.report)
        other.restore_view_state(state)
        assert other.view_state() == state
        rect = QRectF(0, 0, 800, 480)
        np.testing.assert_allclose(other._projection(rect)[0](other.positions)[0],
                                   view._projection(rect)[0](view.positions)[0])
    finally:
        other.close()


def test_extreme_camera_in_an_archive_keeps_a_finite_projection(view):
    fitted = view.view_state()
    view.restore_view_state({"camera_center": [0, 0, 0], "camera_radius": 1e-320, "pan": [1e308, -1e308]})
    project, scale, _ = view._projection(QRectF(0, 0, 800, 480), pan_scale=2)
    assert view.view_state()["camera_radius"] == fitted["camera_radius"]
    assert math.isfinite(scale) and np.isfinite(project(view.positions)[0]).all()


def test_subthreshold_pointer_jitter_never_rotates_and_drag_latches(view, application):
    view.fit_atoms()
    view.show()
    application.processEvents()
    _, x, y, _ = view._projected_atoms[-1]
    point = QPoint(round(x), round(y))
    original = view.yaw, view.pitch
    picked = QSignalSpy(view.atomPicked)
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(view, point + QPoint(2, 1))
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point + QPoint(2, 1))
    assert (view.yaw, view.pitch) == original
    assert picked.count() == 1
    QTest.mousePress(view, Qt.MouseButton.LeftButton, pos=point)
    QTest.mouseMove(view, point + QPoint(40, 20))
    QTest.mouseMove(view, point)
    QTest.mouseRelease(view, Qt.MouseButton.LeftButton, pos=point)
    assert picked.count() == 1


def test_hover_and_selection_reuse_raster_but_camera_pick_is_fresh(view, application, monkeypatch):
    import slab_preflight.desktop_view as module
    view.fit_atoms()
    view.show()
    application.processEvents()
    calls = []
    original = module.rasterize

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "rasterize", counted)
    _, x, y, _ = view._projected_atoms[-1]
    QTest.mouseMove(view, QPoint(round(x), round(y)))
    view.set_selection([0])
    view.repaint()
    assert calls == []
    view.pan += [100, 0]
    assert view._picked(QPointF(x + 100, y)) >= 0
    assert calls == [1]


def test_end_on_line_depth_is_independent_of_endpoint_order():
    line = np.array([[20, 20, -3], [20, 20, 5]], float)
    front = Primitive("sphere", np.array([[20, 20, 0]], float), (0, 0, 1, 1), 4, atom=0)
    first, pick_first = rasterize(40, 40, [front, Primitive("line", line, (1, 0, 0, 1), 2)], world_per_pixel=0.1)
    second, pick_second = rasterize(40, 40, [front, Primitive("line", line[::-1], (1, 0, 0, 1), 2)], world_per_pixel=0.1)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(pick_first, pick_second)
    assert first[20, 20].tolist() == [255, 0, 0, 255]


def test_optional_molecular_cell_has_no_crystal_axis_or_gap_assumptions(view):
    view.set_structure({"positions": [[0, 0, 0], [1, 0, 0]], "elements": ["H", "H"], "cell": None,
                        "periodic_axes": [False, False, False], "metrics": {}})
    assert not view.has_cell
    assert view.fit_cell()
    image = view.render_scene_image(600, 400)
    assert not image.isNull()
    assert "Cartesian molecular geometry" in view._export_annotations()


def test_auto_quality_ignores_interaction_and_overlay_frame_costs(view, application):
    view.set_graphics_quality("auto")
    view.show()
    application.processEvents()
    view._frame_times.clear()
    view._interacting = True
    view.yaw += 0.2
    view.repaint()
    assert not view._frame_times
    view._interacting = False
    view.repaint()
    count = len(view._frame_times)
    view.set_selection([0])
    view.repaint()
    assert len(view._frame_times) == count


def test_line_and_dash_sizes_are_logical_units_at_all_sampling_scales(view):
    view.show_gap = True
    project, scale, corners = view._projection(QRectF(0, 0, 800, 480))
    reference = None
    for sampling in (0.5, 0.7, 1.0, 1.5, 2.0):
        def sampled(points):
            xy, z = project(points)
            return xy * sampling, z

        primitives, _, _ = view._scene_primitives(sampled, scale * sampling, corners,
                                                  GRAPHICS_PRESETS["balanced"], sampling, False)
        sizes = [(primitive.radius / sampling, primitive.dash_length / sampling,
                  primitive.dash_gap / sampling) for primitive in primitives if primitive.kind == "line"]
        if reference is None:
            reference = sizes
        np.testing.assert_allclose(sizes, reference, rtol=1e-12)
        assert not any(primitive.kind == "sprite" for primitive in primitives)


def contrast_ratio(first, second):
    def luminance(value):
        rgb = np.array([int(value[index:index + 2], 16) / 255 for index in (1, 3, 5)])
        linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
        return linear @ [0.2126, 0.7152, 0.0722]
    low, high = sorted((luminance(first), luminance(second)))
    return (high + 0.05) / (low + 0.05)


def test_annotations_are_legible_screen_overlays_and_do_not_jump_on_drag(view, application):
    view.set_contact({"i": 0, "j": 1, "distance_angstrom": 1.420})
    view.fit_measurement()
    view.set_background("dark")
    view.show()
    application.processEvents()
    reference = view._last_annotation_boxes
    assert any(box["text"] == "1.420 Å" for box in reference)
    assert all(contrast_ratio(box["foreground"], box["background"]) >= 4.5 for box in reference)
    view._interacting = True
    view.repaint()
    for first, second in zip(reference, view._last_annotation_boxes):
        assert first["text"] == second["text"]
        np.testing.assert_allclose(first["rect"], second["rect"], atol=1e-9)


@pytest.mark.parametrize("dpr", [1.0, 1.25, 1.5, 2.0])
def test_high_dpi_changes_raster_density_but_not_annotation_or_picking_coordinates(view, application, monkeypatch, dpr):
    monkeypatch.setattr(StructureView, "devicePixelRatioF", lambda self: dpr)
    view.fit_atoms()
    view.show()
    application.processEvents()
    width, height = view._last_render_stats["raster_size"]
    assert width == round(view._pick_rect.width() * dpr)
    assert height == round(view._pick_rect.height() * dpr)
    _, x, y, _ = view._projected_atoms[-1]
    assert view._picked(QPointF(x, y)) >= 0
    assert view._last_render_stats["device_pixel_ratio"] == dpr


def test_scene_publication_canvas_scales_physical_fonts_and_scientific_scale_together(view):
    view.fit_atoms()
    view.set_contact({"i": 0, "j": 1, "distance_angstrom": 1.420})
    state = view.view_state()
    first = view.render_scene_image(600, 400)
    first_boxes = view._last_annotation_boxes
    second = view.render_scene_image(1200, 800)
    assert view.view_state() == state
    assert view._last_annotation_boxes == first_boxes
    low = json.loads(first.text("CalcLens scene"))
    high = json.loads(second.text("CalcLens scene"))
    assert high["pixels_per_angstrom"] == pytest.approx(low["pixels_per_angstrom"] * 2)
    assert (first.width(), first.height()) == (600, 400)
    assert (second.width(), second.height()) == (1200, 800)


def test_resize_before_queued_paint_rebuilds_pick_map_at_current_scene(view, application):
    view.fit_atoms()
    view.show()
    application.processEvents()
    original_size = view._pick_map.shape
    view.resize(960, 720)
    view._picked(QPointF(0, 0))
    assert view._pick_map.shape != original_size
    _, x, y, _ = view._projected_atoms[-1]
    assert view._picked(QPointF(x, y)) >= 0


def test_scene_and_annotated_exports_ignore_transient_hover(view, tmp_path):
    view.fit_atoms()
    view.set_selection([0])
    state = view.view_state()
    first = view.render_scene_image(600, 400)
    first_path = view.export_png(tmp_path / "before-hover.png", width=600, height=400)
    view._hover = 1
    second = view.render_scene_image(600, 400)
    second_path = view.export_png(tmp_path / "after-hover.png", width=600, height=400)
    assert bytes(first.constBits()) == bytes(second.constBits())
    assert first_path.read_bytes() == second_path.read_bytes()
    assert view.view_state() == state
    assert view.selected_atoms == [0]


def test_annotation_text_stays_in_front_of_opaque_mesh_but_hidden_atoms_have_no_highlight(view, application):
    view.set_structure({"positions": [[0, 0, 0]], "elements": ["C"], "cell": None, "metrics": {}})
    view.yaw = view.pitch = view.roll = 0
    view.set_surfaces([{"vertices": [[-10, -10, 3], [10, -10, 3], [10, 10, 3], [-10, 10, 3]],
                        "faces": [[0, 1, 2], [0, 2, 3]], "opacity": 1, "color": "#0000ff"}])
    view.set_contact({"i": 0, "j": 0, "distance_angstrom": 0})
    image = view.render_scene_image(800, 600)
    assert image.pixelColor(20, 20).getRgb() == (0, 0, 255, 255)
    box = view._last_annotation_boxes[0]["rect"]
    assert image.pixelColor(round(box[0] + 3), round(box[1] + box[3] / 2)).getRgb() == (255, 255, 255, 255)
    view.set_selection([0])
    view.show()
    application.processEvents()
    assert not (view._pick_map == 0).any()
    assert view._scene_cache["highlights"] == []


def test_selected_atom_outside_label_budget_gains_a_cached_visible_glyph(view, application):
    view.set_structure({"positions": [[index * 2, 0, 0] for index in range(41)],
                        "elements": ["C"] * 41, "cell": None, "metrics": {}})
    view.set_graphics_quality("light")
    view.fit_atoms()
    view.show()
    application.processEvents()
    frame = view._scene_cache
    view.set_selection([40])
    view.repaint()
    assert view._scene_cache is frame
    assert frame["labels"] == 40
    assert frame["highlights"]
    overlay = frame["highlights"][0][1]
    pixels = np.frombuffer(overlay.constBits(), np.uint8).reshape(overlay.height(), overlay.bytesPerLine())
    pixels = pixels[:, :overlay.width() * 4].reshape(overlay.height(), overlay.width(), 4)
    assert np.any((pixels[:, :, :3] == [255, 255, 255]).all(axis=2) & (pixels[:, :, 3] > 0))
