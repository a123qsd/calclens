"""Pixel-level depth, transparency, display preferences and real PNG exports."""
import json
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
from PySide6.QtCore import QPointF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from slab_preflight.desktop_raster import Primitive, rasterize
from slab_preflight.desktop_view import StructureView


@pytest.fixture(scope="module")
def application():
    return QApplication.instance() or QApplication([])


def plane(z, color=(0, 0, 1, 1)):
    vertices = np.array([[10, 10, z], [90, 10, z], [90, 90, z], [10, 90, z]], float)
    return [Primitive("triangle", vertices[list(face)], color) for face in ((0, 1, 2), (0, 2, 3))]


def test_opaque_plane_in_front_and_behind_atom_and_guide():
    atom = Primitive("sphere", np.array([[50, 50, 0]], float), (1, 0, 0, 1), 12, atom=3)
    guide = Primitive("line", np.array([[20, 65, 0], [80, 65, 0]], float), (0, 1, 0, 1), 2)
    pixels, picks = rasterize(100, 100, [atom, guide, *plane(20)], world_per_pixel=0.1)
    assert pixels[50, 50].tolist() == [0, 0, 255, 255]
    assert picks[50, 50] == -1
    assert pixels[65, 50].tolist() == [0, 0, 255, 255]
    pixels, picks = rasterize(100, 100, [*plane(-20), atom, guide], world_per_pixel=0.1)
    assert pixels[50, 50].tolist() == [255, 0, 0, 255]
    assert picks[50, 50] == 3
    assert pixels[65, 50].tolist() == [0, 255, 0, 255]


def test_surface_intersects_actual_sphere_depth_instead_of_atom_center():
    sphere = Primitive("sphere", np.array([[50, 50, 0]], float), (1, 0, 0, 1), 20, atom=0)
    image, picks = rasterize(100, 100, [sphere, *plane(1.2)], world_per_pixel=0.1)
    assert image[50, 50, 0] == 255 and picks[50, 50] == 0
    assert image[50, 68, 2] == 255 and picks[50, 68] == -1


def test_intersecting_triangles_are_sorted_per_pixel_not_average_depth():
    red = plane(0, (1, 0, 0, 1))
    for primitive in red:
        primitive.points[:, 2] = (primitive.points[:, 0] - 50) / 10
    green = plane(0, (0, 1, 0, 1))
    image, _ = rasterize(100, 100, [*red, *green])
    assert image[50, 25].tolist() == [0, 255, 0, 255]
    assert image[50, 75].tolist() == [255, 0, 0, 255]


def test_crossing_transparent_surfaces_are_exactly_composited_and_have_no_diagonal_seam():
    red = plane(0, (1, 0, 0, 0.5))
    for primitive in red:
        primitive.points[:, 2] = (primitive.points[:, 0] - 50) / 10
    blue = plane(0, (0, 0, 1, 0.5))
    image, _ = rasterize(100, 100, [*red, *blue])
    np.testing.assert_allclose(image[50, 25], [85, 0, 170, 191], atol=1)
    np.testing.assert_allclose(image[50, 75], [170, 0, 85, 191], atol=1)
    single, _ = rasterize(100, 100, plane(0, (0, 0, 1, 0.5)))
    assert single[30, 30, 3] == single[30, 31, 3] == 128


def test_transparent_front_surface_colors_atom_but_does_not_block_visible_picking():
    sphere = Primitive("sphere", np.array([[50, 50, 0]], float), (1, 0, 0, 1), 10, atom=4)
    image, picks = rasterize(100, 100, [sphere, *plane(20, (0, 0, 1, 0.5))], world_per_pixel=0.1)
    np.testing.assert_allclose(image[50, 50], [128, 0, 128, 255], atol=1)
    assert picks[50, 50] == 4
    hidden, _ = rasterize(100, 100, [*plane(20), *plane(0, (1, 0, 0, 0.5))])
    assert hidden[50, 50].tolist() == [0, 0, 255, 255]


def test_dense_transparent_layers_subdivide_without_omitting_depth_layers():
    layers = [primitive for z in range(240) for primitive in plane(z, (0, 0, 1, 0.01))]
    image, _ = rasterize(100, 100, layers)
    assert image[50, 50, 3] == round((1 - 0.99 ** 240) * 255)
    assert image[50, 50, :3].tolist() == [0, 0, 255]


def view_with_plane(application, opacity=1):
    view = StructureView(language="en")
    view.resize(800, 600)
    view.set_structure({"positions": [[0, 0, 0]], "elements": ["O"], "cell": np.eye(3).tolist(),
                        "normal_axis": "c", "metrics": {}}, {"filename": "oxygen.cif", "sha256": "a" * 64})
    view.yaw = view.pitch = 0
    view.show_cell = view.show_bonds = False
    view.set_surfaces([{"vertices": [[-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]],
                        "faces": [[0, 1, 2], [0, 2, 3]], "color": "#0000ff", "opacity": opacity,
                        "label": "+0.05 e/angstrom^3"}],
                      {"dataset_id": "density-1", "name": "Total density", "filename": "density.cube",
                       "kind": "density", "isovalue": 0.05, "units": "e/angstrom^3", "source_sha256": "b" * 64})
    return view


def test_real_widget_does_not_pick_atom_behind_opaque_surface(application):
    view = view_with_plane(application)
    view.show()
    application.processEvents()
    _, x, y, _ = view._projected_atoms[0]
    assert view._picked(QPointF(x, y)) == -1
    view.surfaces[0]["opacity"] = 0.4
    view.repaint()
    assert view._picked(QPointF(x, y)) == 0
    view.close()


def test_graphics_presets_change_samples_and_keep_source_data_and_manual_choice(application):
    view = view_with_plane(application)
    positions = view.positions.copy()
    vertices = view.surfaces[0]["vertices"].copy()
    faces = view.surfaces[0]["faces"].copy()
    view.show()
    application.processEvents()
    sizes = []
    for quality in ("light", "balanced", "high"):
        view.set_graphics_quality(quality)
        view.repaint()
        sizes.append(view._last_render_stats["raster_size"])
        assert view._last_render_stats["surface_faces"] == 2
    assert sizes[0][0] < sizes[1][0] < sizes[2][0]
    assert "graphics_quality" not in view.view_state()
    view.restore_view_state({"quality": "light", "yaw": 0.2})
    assert view.graphics_quality == "high"
    np.testing.assert_array_equal(view.positions, positions)
    np.testing.assert_array_equal(view.surfaces[0]["vertices"], vertices)
    np.testing.assert_array_equal(view.surfaces[0]["faces"], faces)
    assert view.surface_metadata["isovalue"] == 0.05
    view.set_graphics_quality("auto")
    view._frame_times.extend([100] * 12)
    assert view.effective_graphics_quality() == "light"
    view.set_graphics_quality("high")
    assert view.effective_graphics_quality() == "high"
    view.close()


def test_label_density_and_rotation_detail_have_real_independent_limits(application):
    view = StructureView(language="en")
    positions = [[3 * (index % 15), 3 * (index // 15), 0] for index in range(150)]
    view.set_structure({"positions": positions, "elements": ["C"] * 150, "cell": np.diag([45, 30, 10]).tolist(),
                        "normal_axis": "c", "metrics": {}})
    view.resize(800, 600)
    view.show_cell = False
    view.show()
    application.processEvents()
    counts = []
    for quality in ("light", "balanced", "high"):
        view.set_graphics_quality(quality)
        view.repaint()
        counts.append(view._last_render_stats["labels"])
    assert counts == [40, 120, 150]
    still = view._last_render_stats["raster_size"]
    view._interacting = True
    view.repaint()
    assert view._last_render_stats["raster_size"][0] < still[0]
    assert len(view.positions) == 150
    view.close()


def test_png_resolution_background_and_provenance_do_not_use_screen_quality(application, tmp_path):
    view = view_with_plane(application, opacity=0.4)
    view.set_graphics_quality("light")
    view.set_representation("spacefill")
    view.set_background("dark")
    view.surface_metadata["source"] = "Full immutable source text " * 100
    view.set_charges([None], {"dataset_id": "charge-1", "filename": "charge.json", "source_sha256": "c" * 64,
                              "kind": "partial_charge", "units": "e"})
    path = tmp_path / "annotated.png"
    view.export_png(path, width=800, quality="high", background="transparent")
    image = QImage(str(path))
    assert image.width() == 800 and image.height() > 600
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(0, image.height() - 1).getRgb() == (255, 255, 255, 255)
    provenance = json.loads(image.text("CalcLens provenance"))
    assert provenance["surface"] == view.surface_metadata
    assert provenance["charge"] == view.charge_metadata
    assert provenance["rendering"]["quality"] == "high"
    assert provenance["rendering"]["scene_width"] == 800
    assert provenance["camera"]["representation"] == "spacefill"
    annotations = image.text("CalcLens annotations")
    assert "density-1" in annotations and "density.cube" in annotations and "b" * 64 in annotations
    assert "e/angstrom^3" in annotations
    assert view.graphics_quality == "light" and view.background == "dark"
    view.set_graphics_quality("high")
    same = tmp_path / "same-export-quality.png"
    view.export_png(same, width=800, quality="high", background="transparent")
    assert path.read_bytes() == same.read_bytes()
    white = tmp_path / "white.png"
    view.export_png(white, width=1600, quality="balanced", background="white")
    assert QImage(str(white)).width() == 1600
    assert QImage(str(white)).pixelColor(0, 0).alpha() == 255


def test_invalid_graphics_options_and_dimensions_fail_before_export(application, tmp_path):
    view = view_with_plane(application)
    for method, bad in ((view.set_graphics_quality, "cuda"), (view.set_representation, "x"), (view.set_background, "x")):
        with pytest.raises(ValueError):
            method(bad)
    for dimensions in ({"width": 1000000}, {"width": float("nan")}, {"height": 1000000}):
        with pytest.raises(ValueError):
            view.export_png(tmp_path / "invalid.png", **dimensions)
    assert not (tmp_path / "invalid.png").exists()


def test_comparison_controls_and_export_stay_reachable_in_small_logical_workspace(application, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialogButtonBox, QFileDialog
    from slab_preflight.desktop import MainWindow
    from slab_preflight.desktop_compare import ComparisonDialog

    monkeypatch.setenv("CALCLENS_SETTINGS_FILE", str(tmp_path / "preferences.ini"))
    window = MainWindow(language="en", root=Path(__file__).resolve().parents[1], recovery=False, research_factory=False)
    window.view.set_graphics_quality("high")
    dialog = ComparisonDialog(window)
    try:
        dialog.resize(683, 384)
        dialog.show()
        application.processEvents()
        assert dialog.height() == 384
        assert dialog.scroll.verticalScrollBar().maximum() > 0
        button = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Close)
        assert button.mapTo(dialog, button.rect().bottomRight()).y() < dialog.height()
        pane = dialog.panes[0]
        assert pane["view"].graphics_quality == "high"
        pane["representation"].setCurrentIndex(pane["representation"].findData("spacefill"))
        assert pane["view"].representation == "spacefill"
        pane["display_toggles"]["cell"].setChecked(False)
        assert pane["view"].show_cell is False
        window.preferences.set("export_width", "2400")
        window.preferences.set("export_background", "transparent")
        saved = []
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_: (str(tmp_path / "pane.png"), "PNG"))
        monkeypatch.setattr(pane["view"], "export_png", lambda path, **kwargs: saved.append((path, kwargs)))
        dialog._export_view(pane["view"])
        assert saved[0][1] == {"width": 2400, "background": "transparent"}
    finally:
        dialog.close()
        window.dirty = False
        window.close()
        application.processEvents()
