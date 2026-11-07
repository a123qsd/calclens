import platform
from itertools import product

import numpy as np
import pytest

from slab_preflight.compute_devices import (ComputeError, compute_arrays, compute_norms,
                                            minimum_image_pair_distances, probe_devices)


def test_cpu_difference_and_planar_reduction_are_verified_for_every_axis():
    a = np.arange(120, dtype=np.float64).reshape((4, 5, 6))
    b = np.full_like(a, .25)
    c = np.full_like(a, .5)
    for axis in (0, 1, 2):
        values, planes, execution = compute_arrays([a, b, c], axis=axis)
        np.testing.assert_array_equal(values, a - .75)
        np.testing.assert_allclose(planes, (a - .75).mean(axis=tuple(i for i in range(3) if i != axis)))
        assert execution["effective_device"] == "cpu"
        assert execution["parity"]["passed"] is True
        assert execution["includes_cpu_parity_check"] is True


@pytest.mark.parametrize("arrays, axis", [
    ([np.ones((2, 2))], 2), ([np.ones((1, 2, 2))], 2),
    ([np.ones((2, 2, 2))] * 2, 2), ([np.full((2, 2, 2), np.nan)], 2),
    ([np.ones((2, 2, 2))], True), ([np.ones((2, 2, 2))], 3),
    ([np.ones((101, 101, 101))], 2),
])
def test_bounded_device_workloads_reject_invalid_sources(arrays, axis):
    with pytest.raises(ComputeError):
        compute_arrays(arrays, axis=axis)


def test_explicit_unavailable_request_never_silently_falls_back():
    if platform.system() == "Darwin":
        with pytest.raises(ComputeError, match="CUDA"):
            compute_arrays([np.ones((2, 2, 2))], device="cuda")
    elif platform.system() != "Darwin":
        with pytest.raises(ComputeError, match="Metal"):
            compute_arrays([np.ones((2, 2, 2))], device="metal")
    with pytest.raises(ComputeError, match="explicitly supplied"):
        compute_arrays([np.ones((2, 2, 2))], device="remote")


def test_actual_host_device_probe_reports_workload_results():
    devices = probe_devices()
    assert [item["id"] for item in devices] == ["cpu", "metal", "cuda"]
    assert devices[0]["available"] is True
    for item in devices:
        assert item["available"] == item["workload_verified"]
        if not item["available"]:
            assert item["reason"]


@pytest.mark.skipif(platform.system() != "Darwin", reason="Actual Metal hardware test requires macOS")
def test_actual_metal_difference_and_planar_workloads_match_cpu_on_all_axes():
    if not next(item for item in probe_devices() if item["id"] == "metal")["available"]:
        pytest.skip("No usable Metal helper/device on this host")
    a = np.arange(120, dtype=np.float64).reshape((4, 5, 6)) / 16
    for axis in (0, 1, 2):
        values, averages, execution = compute_arrays([a, a * .25, a * .5], axis=axis, device="metal")
        np.testing.assert_allclose(values, a * .25, atol=1e-6)
        np.testing.assert_allclose(averages, (a * .25).mean(axis=tuple(i for i in range(3) if i != axis)), atol=1e-6)
        assert execution["effective_device"] == "metal"
        assert execution["precision"] == "float32"
        assert execution["parity"]["passed"] is True


@pytest.mark.skipif(platform.system() != "Darwin", reason="Actual Metal precision test requires macOS")
def test_metal_cancellation_failure_is_visible_and_auto_can_return_cpu_truth():
    if not next(item for item in probe_devices() if item["id"] == "metal")["available"]:
        pytest.skip("No usable Metal helper/device on this host")
    a = np.full((2, 2, 2), 1 + 1e-8)
    b = np.ones_like(a)
    c = np.zeros_like(a)
    with pytest.raises(ComputeError, match="parity"):
        compute_arrays([a, b, c], device="metal")
    values, _, execution = compute_arrays([a, b, c], device="auto")
    np.testing.assert_array_equal(values, a - b)
    assert execution["effective_device"] == "cpu"
    assert any("parity" in reason for reason in execution["fallback_reasons"])


def test_periodic_pair_distances_match_independent_skew_cell_enumeration_and_preserve_shifts():
    cell = np.array([[4., 0., 0.], [3.5, 1., 0.], [0., 0., 10.]])
    positions = np.array([[0., 0., 0.], [.49, .49, .1], [.9, .1, .8]]) @ cell
    result = minimum_image_pair_distances(positions, cell)
    assert result["pair_count"] == 3
    translations = np.array(list(product(range(-3, 4), repeat=3))) @ cell
    for record in result["pairs"]:
        vector = positions[record["j"]] - positions[record["i"]]
        expected = np.linalg.norm(vector + translations, axis=1).min()
        assert record["distance_angstrom"] == pytest.approx(expected, abs=1e-12)
        np.testing.assert_allclose(record["displacement_angstrom"], vector + np.array(record["shift"]) @ cell, atol=1e-12)
        assert record["site_i"] == record["i"] + 1
        assert record["device_distance_angstrom"] == pytest.approx(expected)
    assert set(result["timing"]) == {"minimum_image_selection_seconds", "distance_evaluation_seconds", "total_seconds"}


def test_pair_requests_are_bounded_and_reject_self_or_duplicate_pairs():
    positions = [[0, 0, 0], [1, 0, 0]]
    for pairs in ([], [(0, 0)], [(0, 2)], [(0, 1), (1, 0)], [(True, 1)]):
        with pytest.raises(ComputeError):
            minimum_image_pair_distances(positions, np.eye(3) * 5, pairs=pairs)
    for vectors in ([], [[1, 2]], [[float("nan"), 0, 0]], [[1e7, 0, 0]]):
        with pytest.raises(ComputeError):
            compute_norms(vectors)


def test_auto_uses_measured_completed_cost_and_reuses_selection_without_remote_contact():
    data = np.arange(72, dtype=float).reshape((3, 4, 6))
    _, _, first = compute_arrays([data], device="auto", remote=object())
    selection = first["auto_selection"]
    available = [item for item in selection["measurements"] if item["available"]]
    fastest = min(available, key=lambda item: item["completed_seconds"])["device"]
    assert first["effective_device"] == fastest
    assert selection["selected_device"] == fastest
    _, _, second = compute_arrays([data], device="auto", remote=object())
    assert second["auto_selection"]["calibration_reused"] is True
    assert second["effective_device"] == fastest


@pytest.mark.skipif(platform.system() != "Darwin", reason="Actual Metal pair norms require macOS")
def test_actual_metal_norms_and_cpu_periodic_pair_truth_are_both_recorded():
    if not next(item for item in probe_devices() if item["id"] == "metal")["available"]:
        pytest.skip("No usable Metal helper/device on this host")
    values, execution = compute_norms([[3, 4, 0], [1e-9, 0, 0], [0, 0, 0]], device="metal")
    np.testing.assert_allclose(values, [5, 1e-9, 0], atol=1e-12)
    assert execution["effective_device"] == "metal"
    result = minimum_image_pair_distances([[0, 0, 0], [4.9, 0, 0]], np.eye(3) * 5, device="metal")
    assert result["pairs"][0]["distance_angstrom"] == pytest.approx(.1)
    assert result["pairs"][0]["device_distance_angstrom"] == pytest.approx(.1, abs=1e-8)
    assert result["pairs"][0]["shift"] == [-1, 0, 0]
