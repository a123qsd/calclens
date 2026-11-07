"""Quantitative paper plots preserve source/result identity and reject stale data."""

from copy import deepcopy
from hashlib import sha256
import json

import numpy as np
import pytest
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog, QFileDialog

from slab_preflight.density import parse_cube, planar_average
from slab_preflight.density_records import binding_digest, dataset_identity
from slab_preflight.density_verification import verify_planar_record, with_reproducibility
from slab_preflight.profile_figure import export_profile_figure
from slab_preflight.publication import FigureDialog
from test_density_records import cube
from test_density_verification import planar_record
import test_research_integrity as shared

app = shared.app
window = shared.window


def constant_record(value):
    record, item, entry = planar_record()
    item["kind"] = "difference_density"
    item["rawText"] = cube([(0, 0, 5), (.74, 0, 5)], value)
    grid = parse_cube(item["rawText"], kind=item["kind"], units=item["units"], source_name=item["filename"])
    profile = planar_average(grid, normal=[0, 0, 10])
    record.update({"dataset": dataset_identity(item, entry["sha256"], grid),
                   "profile": profile, "execution": profile["execution"], "grid": grid.metadata()})
    record = with_reproducibility(record)
    verification = verify_planar_record(record, item, entry)
    binding = {"operation": record["operation"], "dataset": dataset_identity(item, entry["sha256"]),
               "structure_sha256": entry["sha256"], "grid_plane_axis": 2}
    return profile, record, binding, verification


@pytest.mark.parametrize("quantity,units", [("average", "e/angstrom^3"), ("cumulative", "e")])
def test_gui_exports_selected_quantity_with_verified_identity_and_physical_print_size(window, tmp_path, quantity, units):
    win, errors = window
    panel = shared.water(win)
    panel.average()
    before = deepcopy(panel._profile_record)
    panel.profile_quantity.setCurrentIndex(panel.profile_quantity.findData(quantity))
    path = tmp_path / f"{quantity}.png"
    assert panel.profile_figure.isEnabled()
    assert panel.export_profile_figure(path=path, transparent=True)
    image = QImage(str(path))
    note = json.loads(image.text("CalcLens provenance"))
    assert image.width() == round(85 * 300 / 25.4)
    assert image.height() == round(63.75 * 300 / 25.4)
    assert image.dotsPerMeterX() == round(300 / .0254)
    assert image.pixelColor(0, 0).alpha() == 0
    assert note["plot"]["quantity"] == quantity and note["plot"]["y_units"] == units
    assert note["plot"]["x_units"] == "angstrom" and note["plot"]["zero_reference"]
    assert note["density_record"] == before == panel._profile_record
    assert note["density_profile_sha256"] == binding_digest(panel._profile)
    assert note["source"]["source_sha256"] == sha256(panel._source("volume", panel.volume.currentData())["rawText"].encode()).hexdigest()
    assert note["verification"]["status"] == "passed"
    assert note["verification"]["record_manifest_sha256"] == note["density_record_manifest_sha256"]
    assert note["result_binding_sha256"] == binding_digest(note["result_binding"])
    assert note["result_binding"]["dataset"] == before["dataset"]
    assert note["plot"]["sample_count"] == len(panel._profile["positions_angstrom"]) + (quantity == "cumulative")
    assert not errors


def test_pdf_profile_contains_vector_chart_and_embedded_result_in_one_page(window, tmp_path):
    win, errors = window
    panel = shared.h2(win)
    panel.difference()
    panel.profile_quantity.setCurrentIndex(panel.profile_quantity.findData("cumulative"))
    path = tmp_path / "difference-profile.pdf"
    assert panel.export_profile_figure(path=path, width_mm=180, dpi=600)
    data = path.read_bytes()
    assert data.startswith(b"%PDF-") and b"/EmbeddedFiles" in data
    assert b"/Subtype /Image" not in data  # Axes, text and the curve are painted directly.
    assert data.count(b"/Type /Page\n") == 1
    assert not errors


@pytest.mark.parametrize("value", [0., 2., -2., 1e-300, 1e300])
def test_constant_zero_signed_tiny_and_large_lines_have_finite_plot_scales(app, tmp_path, value):
    profile, record, binding, verified = constant_record(value)
    for quantity in ("average", "cumulative"):
        path = tmp_path / f"constant-{quantity}.png"
        note = export_profile_figure(profile, record, path, binding=binding, verification=verified,
                                     quantity=quantity)
        for axis in note["plot"]["axes"].values():
            assert np.isfinite(axis["limits"]).all()
            assert axis["limits"][1] > axis["limits"][0]
        assert not QImage(str(path)).isNull()


@pytest.mark.parametrize("change", ["profile", "source", "verification"])
def test_mismatched_profile_binding_or_verification_preserves_destination(app, tmp_path, change):
    profile, record, binding, verified = constant_record(.2)
    path = tmp_path / "existing.png"
    path.write_bytes(b"existing figure")
    if change == "profile":
        profile = deepcopy(profile)
        profile["average_e_per_angstrom3"][0] += 1
    elif change == "source":
        binding["dataset"]["dataset_id"] = "other"
    else:
        verified["record_manifest_sha256"] = "a" * 64
    with pytest.raises(ValueError, match="exact current"):
        export_profile_figure(profile, record, path, binding=binding, verification=verified)
    assert path.read_bytes() == b"existing figure"


def test_normal_button_path_and_modal_stale_result_guard(window, monkeypatch, tmp_path):
    win, errors = window
    panel = shared.water(win)
    panel.average()
    monkeypatch.setattr(FigureDialog, "exec", lambda _self: QDialog.DialogCode.Accepted)
    target = tmp_path / "from-button.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), "PNG"))
    panel.profile_figure.click()
    assert target.is_file() and "Profile figure saved" in win.status_label.text()
    original = target.read_bytes()

    def changed_while_choosing(*_args, **_kwargs):
        panel.axis.setCurrentIndex(0)
        return str(target), "PNG"

    monkeypatch.setattr(QFileDialog, "getSaveFileName", changed_while_choosing)
    assert panel.export_profile_figure() is False
    assert target.read_bytes() == original
    assert not panel.profile_figure.isEnabled()
    assert not errors
