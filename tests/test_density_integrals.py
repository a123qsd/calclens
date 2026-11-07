"""Analytic volume counts and cut planes use one explicit voxel convention."""

import numpy as np
import pytest

from slab_preflight.density import (
    DensityError, integrate_profile_interval, parse_cube, planar_average,
)
from test_density import cube


def signed(values, **kwargs):
    return parse_cube(cube(values, **kwargs), kind="difference_density", units="e/angstrom^3")


def test_cumulative_signed_count_and_partial_slab_cut_on_a_skew_cell():
    field = signed(np.broadcast_to([-1., -1., 1., 1.], (2, 3, 4)), origin=(0, 0, 1),
                   vectors=((1, 0, 0), (.5, 2, 0), (.2, .3, 3)))
    profile = planar_average(field, normal=[0, 0, 1])
    integral = profile["integration"]
    assert integral["boundary_positions_angstrom"] == pytest.approx([-.5, 2.5, 5.5, 8.5, 11.5])
    assert integral["plane_integral_e"] == pytest.approx([-36, -36, 36, 36])
    assert integral["cumulative_e"] == pytest.approx([0, -36, -72, -36, 0])
    assert integral["positive_voxel_integral_e"] == pytest.approx(72)
    assert integral["negative_voxel_integral_e"] == pytest.approx(-72)
    assert integral["absolute_voxel_integral_e"] == pytest.approx(144)
    assert integral["voxel_volume_angstrom3"] == pytest.approx(6)
    # A cut halfway through the third centered slab retains half its +36 e.
    assert integrate_profile_interval(profile, -.5, 7) == pytest.approx(-54)
    assert integrate_profile_interval(profile, 7, 11.5) == pytest.approx(54)
    assert integrate_profile_interval(profile, 7, 7) == 0


def test_reversing_the_normal_reverses_boundaries_and_complements_cumulative_counts():
    field = signed(np.broadcast_to([-1., 0., 1., 2.], (2, 3, 4)), origin=(0, 0, 1))
    forward = planar_average(field, normal=[0, 0, 1])
    reverse = planar_average(field, normal=[0, 0, -1])
    assert reverse["integral_e"] == forward["integral_e"] == pytest.approx(12)
    np.testing.assert_allclose(reverse["integration"]["boundary_positions_angstrom"],
                               -np.array(forward["integration"]["boundary_positions_angstrom"])[::-1])
    np.testing.assert_allclose(reverse["integration"]["cumulative_e"],
                               forward["integral_e"] - np.array(forward["integration"]["cumulative_e"])[::-1])


def test_positive_and_negative_counts_use_voxels_before_planar_cancellation():
    values = np.broadcast_to(np.array([-1., 1.])[:, None, None], (2, 3, 4))
    profile = planar_average(signed(values))
    assert profile["average_e_per_angstrom3"] == [0] * 4
    assert profile["integration"]["cumulative_e"] == [0] * 5
    assert profile["integration"]["positive_voxel_integral_e"] == pytest.approx(12)
    assert profile["integration"]["negative_voxel_integral_e"] == pytest.approx(-12)


def test_counts_preserve_bohr_scalar_and_volume_conversion():
    field = parse_cube(cube(np.ones((2, 3, 4)), bohr=True),
                       kind="density", units="e/bohr^3")
    for axis in (0, 1, 2):
        profile = planar_average(field, axis=axis)
        assert profile["integration"]["cumulative_e"][-1] == pytest.approx(24)
        assert profile["integration"]["positive_voxel_integral_e"] == pytest.approx(24)
        assert profile["integration"]["negative_voxel_integral_e"] == 0
        edges = profile["integration"]["boundary_positions_angstrom"]
        assert integrate_profile_interval(profile, edges[0], edges[-1]) == pytest.approx(24)


@pytest.mark.parametrize("interval", [(-1, 0), (0, 3), (1, 0), (float("nan"), 1)])
def test_interval_rejects_extrapolation_reversed_or_nonfinite_bounds(interval):
    profile = planar_average(signed(np.ones((2, 2, 2))))
    with pytest.raises(DensityError, match="interval"):
        integrate_profile_interval(profile, *interval)


def test_unrepresentable_integral_is_rejected_instead_of_exporting_infinity():
    field = signed(np.full((2, 2, 2), 1e307),
                   vectors=((10, 0, 0), (0, 10, 0), (0, 0, 10)))
    with pytest.raises(DensityError, match="integration exceeds"):
        planar_average(field)
