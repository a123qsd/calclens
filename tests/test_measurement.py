"""User-selected atom-pair measurements and their rendered geometry."""

from itertools import product
from pathlib import Path

import numpy as np
import pytest

from slab_preflight.core import analyze_cif, measure_atom_pair
from slab_preflight.plotting import structure_figure


ROOT = Path(__file__).resolve().parents[1]


def graphene_report():
    return analyze_cif((ROOT / "examples" / "graphene.cif").read_text(encoding="utf-8"))


def test_measurement_distinguishes_displayed_images_from_minimum_image():
    report = graphene_report()
    first_shift = [1, -1, 0]
    second_shift = [-1, 1, 0]
    measurement = measure_atom_pair(
        report, 0, 1, first_shift=first_shift, second_shift=second_shift
    )
    positions = np.asarray(report["positions"])
    cell = np.asarray(report["cell"])

    displayed = measurement["displayed"]
    expected_displayed = (
        positions[1] + np.asarray(second_shift) @ cell
        - positions[0] - np.asarray(first_shift) @ cell
    )
    assert displayed["start_shift"] == first_shift
    assert displayed["end_shift"] == second_shift
    assert displayed["shift"] == [-2, 2, 0]
    assert displayed["displacement_cartesian"] == pytest.approx(expected_displayed)
    assert displayed["distance_angstrom"] == pytest.approx(np.linalg.norm(expected_displayed))

    minimum = measurement["minimum_image"]
    reconstructed = (
        positions[1] - positions[0] + np.asarray(minimum["shift"]) @ cell
    )
    shifts = np.asarray(list(product(range(-2, 3), repeat=3)))
    brute = np.linalg.norm(positions[1] - positions[0] + shifts @ cell, axis=1).min()
    assert minimum["start_shift"] == first_shift
    assert minimum["end_shift"] == (
        np.asarray(first_shift) + np.asarray(minimum["shift"])
    ).tolist()
    assert minimum["displacement_cartesian"] == pytest.approx(reconstructed)
    assert minimum["distance_angstrom"] == pytest.approx(brute, abs=1e-10)
    assert minimum["distance_angstrom"] < displayed["distance_angstrom"]


@pytest.mark.parametrize(
    "i,j,first,second,message",
    [
        (-1, 1, (0, 0, 0), (0, 0, 0), "index"),
        (0, 2, (0, 0, 0), (0, 0, 0), "index"),
        (0, 0, (0, 0, 0), (1, 0, 0), "distinct"),
        (0, 1, (0.5, 0, 0), (0, 0, 0), "integer"),
        (0, 1, (0, 0), (0, 0, 0), "three"),
    ],
)
def test_measurement_rejects_ambiguous_site_or_image_selections(i, j, first, second, message):
    with pytest.raises(ValueError, match=message):
        measure_atom_pair(graphene_report(), i, j, first_shift=first, second_shift=second)


def test_structure_figure_renders_both_selected_display_images():
    report = graphene_report()
    selected = measure_atom_pair(
        report, 0, 1, first_shift=(1, 0, 0), second_shift=(0, 1, 0)
    )["displayed"]
    figure = structure_figure(report, repeats=1, selected_contact=selected)
    line = next(trace for trace in figure.data if trace.meta.get("role") == "contact_line")
    partner = next(trace for trace in figure.data if trace.meta.get("role") == "contact_image")
    cell = np.asarray(report["cell"])
    positions = np.asarray(report["positions"])
    expected_start = positions[0] + np.asarray(selected["start_shift"]) @ cell
    expected_end = positions[1] + np.asarray(selected["end_shift"]) @ cell

    np.testing.assert_allclose([line.x[0], line.y[0], line.z[0]], expected_start)
    np.testing.assert_allclose([line.x[1], line.y[1], line.z[1]], expected_end)
    np.testing.assert_allclose([partner.x[0], partner.y[0], partner.z[0]], expected_end)
    assert line.meta["start_shift"] == [1, 0, 0]
    assert line.meta["end_shift"] == [0, 1, 0]
