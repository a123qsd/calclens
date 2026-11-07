from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest

from slab_preflight.density import (
    BOHR_ANGSTROM, DensityError, cube_bytes, density_difference, parse_cube, planar_average,
)


def cube(values, *, atoms=((1, (0, 0, 0)), (8, (1, 0, 0))),
         origin=(0, 0, 0), vectors=((1, 0, 0), (0, 1, 0), (0, 0, 1)),
         bohr=False, nval=None):
    values = np.asarray(values)
    lines = ["Explicit test field", "Synthetic numerical fixture, not an electronic calculation",
             " ".join(map(str, [len(atoms), *origin, *([] if nval is None else [nval])]))]
    lines += [" ".join(map(str, [count if bohr else -count, *vector]))
              for count, vector in zip(values.shape, vectors)]
    lines += [" ".join(map(str, [number, number, *position])) for number, position in atoms]
    lines += [" ".join(map(str, values.ravel()))]
    return ("\n".join(lines) + "\n").encode()


def grid(values, **options):
    return parse_cube(cube(values, **options), kind="density", units="e/angstrom^3")


def fragments():
    values = np.ones((2, 3, 4))
    return (grid(values), grid(values * .25, atoms=((1, (0, 0, 0)),)),
            grid(values * .5, atoms=((8, (1, 0, 0)),)))


def difference(*fields, **options):
    defaults = {"a_indices": [1], "b_indices": [2], "method": "Declared same method/basis/grid",
                "reference_conditions": "Common potential, spin, charge and electron reference declarations",
                "frozen_geometry": True}
    defaults.update(options)
    return density_difference(*fields, **defaults)


def test_scalar_units_are_independent_of_coordinate_units_and_hash_exact_bytes():
    source = cube(np.ones((2, 2, 2)), bohr=True)
    result = parse_cube(source, kind="density", units="e/bohr^3")
    np.testing.assert_allclose(result.voxel_vectors_angstrom, np.eye(3) * BOHR_ANGSTROM)
    np.testing.assert_allclose(result.values, 1 / BOHR_ANGSTROM**3)
    assert result.source_sha256 == sha256(source).hexdigest()
    assert result.units == "e/angstrom^3"
    assert planar_average(result)["integral_e"] == pytest.approx(8)
    changed = parse_cube(source.replace(b"\n", b"\r\n"), kind="density", units="e/bohr^3")
    assert changed.source_sha256 != result.source_sha256
    np.testing.assert_array_equal(changed.values, result.values)
    with pytest.raises(ValueError):
        result.values[0, 0, 0] = 5


def test_skew_plane_average_uses_projected_spacing_area_and_absolute_origin():
    values = np.broadcast_to(np.arange(1, 5), (2, 3, 4))
    field = grid(values, origin=(-.1, .2, 1), vectors=((1, 0, 0), (.5, 2, 0), (.2, .3, 3)))
    result = planar_average(field, normal=[0, 0, 1])
    assert result["positions_angstrom"] == pytest.approx([1, 4, 7, 10])
    assert result["average_e_per_angstrom3"] == pytest.approx([1, 2, 3, 4])
    assert result["plane_area_angstrom2"] == pytest.approx(12)
    assert result["plane_step_angstrom"] == pytest.approx(3)
    assert result["integral_e"] == pytest.approx(360)
    assert result["integral_e"] == pytest.approx(values.sum() * abs(np.linalg.det(field.voxel_vectors_angstrom)))
    reverse = planar_average(field, normal=[0, 0, -1])
    assert reverse["positions_angstrom"] == pytest.approx([-10, -7, -4, -1])
    assert reverse["average_e_per_angstrom3"] == pytest.approx([4, 3, 2, 1])
    assert reverse["integral_e"] == pytest.approx(360)
    with pytest.raises(DensityError, match="not parallel"):
        planar_average(field, normal=[1, 0, 0])


def test_all_axes_and_left_handed_voxel_basis_preserve_volume_integral():
    field = grid(np.arange(24).reshape((2, 3, 4)), vectors=((-1, 0, 0), (.5, 2, 0), (.2, .3, 3)))
    for axis in (0, 1, 2):
        result = planar_average(field, axis=axis)
        expected = field.values.mean(axis=tuple(value for value in range(3) if value != axis))
        assert result["average_e_per_angstrom3"] == pytest.approx(expected)
        assert result["integral_e"] == pytest.approx(field.values.sum() * 6)


def test_frozen_density_difference_preserves_sources_partition_and_export():
    fields = fragments()
    result = difference(*fields)
    np.testing.assert_allclose(result.grid.values, .25)
    assert result.grid.kind == "difference_density"
    assert result.profile["integral_e"] == pytest.approx(6)
    assert [source["source_sha256"] for source in result.provenance["sources"]] == [field.source_sha256 for field in fields]
    assert result.provenance["a_indices_one_based"] == [1]
    assert result.execution["effective_device"] == "cpu"
    assert "values" not in result.to_dict()["grid"]
    exported = parse_cube(cube_bytes(result.grid), kind="difference_density", units="e/angstrom^3")
    np.testing.assert_array_equal(exported.values, result.grid.values)
    np.testing.assert_array_equal(exported.atom_positions_angstrom, result.grid.atom_positions_angstrom)
    assert exported.atom_record_charges == fields[0].atom_record_charges


def test_cube_export_preserves_atom_record_charge_without_inventing_partial_or_nuclear_charge():
    source = cube(np.ones((2, 2, 2))).replace(b"8 8 1 0 0", b"8 6.0 1 0 0")
    field = parse_cube(source, kind="density", units="e/angstrom^3")
    exported = parse_cube(cube_bytes(field), kind="density", units="e/angstrom^3")
    assert exported.atom_record_charges == (1., 6.)
    with pytest.raises(DensityError, match="not inferred"):
        cube_bytes(replace(field, atom_record_charges=None))


@pytest.mark.parametrize("changes, message", [
    ({"frozen_geometry": False}, "frozen"), ({"method": ""}, "method"),
    ({"reference_conditions": " "}, "reference"), ({"a_indices": [0]}, "partition"),
    ({"b_indices": [1]}, "partition"), ({"a_indices": [True]}, "integers"),
    ({"a_indices": [2], "b_indices": [1]}, "elements/order"),
])
def test_difference_rejects_missing_declarations_or_ambiguous_atom_partition(changes, message):
    with pytest.raises(DensityError, match=message):
        difference(*fragments(), **changes)


def test_difference_rejects_relaxed_atoms_shifted_origin_grid_or_voxel_basis():
    ab, a, b = fragments()
    with pytest.raises(DensityError, match="frozen AB positions"):
        difference(ab, replace(a, atom_positions_angstrom=a.atom_positions_angstrom + .001), b)
    with pytest.raises(DensityError, match="origins"):
        difference(ab, replace(a, origin_angstrom=a.origin_angstrom + .01), b)
    with pytest.raises(DensityError, match="voxel basis"):
        difference(ab, replace(a, voxel_vectors_angstrom=a.voxel_vectors_angstrom * 1.01), b)
    with pytest.raises(DensityError, match="grid counts"):
        difference(ab, replace(a, values=np.ones((2, 2, 4))), b)


def test_signed_density_is_explicit_and_orbitals_never_become_total_density():
    source = cube(-np.ones((2, 2, 2)))
    with pytest.raises(DensityError, match="nonnegative"):
        parse_cube(source, kind="density", units="e/angstrom^3")
    for kind in ("spin_density", "difference_density"):
        field = parse_cube(source, kind=kind, units="e/angstrom^3")
        assert planar_average(field)["integral_e"] == pytest.approx(-8)
        with pytest.raises(DensityError, match="three total"):
            difference(field, fragments()[1], fragments()[2])
    orbital = parse_cube(source, kind="orbital", units="bohr^-3/2")
    assert orbital.units == "angstrom^-3/2"
    np.testing.assert_allclose(orbital.values, -1 / BOHR_ANGSTROM**1.5)
    with pytest.raises(DensityError, match="orbital amplitude"):
        planar_average(orbital)


@pytest.mark.parametrize("mutation", [
    lambda value: value.replace(b"-2 1 0 0", b"2 1 0 0", 1),
    lambda value: value.replace(b"-2 0 0 1", b"-2 0 0 0", 1),
    lambda value: value.replace(b"1.0 1.0", b"nan 1.0", 1),
    lambda value: value.replace(b"1.0 1.0", b"1e-999 1.0", 1),
    lambda value: value + b" 1.0",
])
def test_malformed_grid_values_and_extra_scalars_are_rejected(mutation):
    with pytest.raises(DensityError):
        parse_cube(mutation(cube(np.ones((2, 2, 2)))), kind="density", units="e/angstrom^3")


def test_multiple_values_and_invalid_normal_are_rejected():
    with pytest.raises(DensityError, match="one scalar"):
        parse_cube(cube(np.ones((2, 2, 2)), nval=2), kind="density", units="e/angstrom^3")
    for normal in ([0, 0, 0], [0, 0], [0, float("nan"), 1]):
        with pytest.raises(DensityError, match="normal"):
            planar_average(fragments()[0], normal=normal)
    with pytest.raises(DensityError, match="axis"):
        planar_average(fragments()[0], axis=True)


def test_extreme_finite_normal_magnitudes_do_not_overflow_or_erase_density_integrals():
    field = fragments()[0]
    truth = planar_average(field, normal=[0, 0, 1])
    for magnitude in (1e-300, 1e300):
        result = planar_average(field, normal=[0, 0, magnitude])
        assert result["integral_e"] == pytest.approx(truth["integral_e"])
        assert result["positions_angstrom"] == pytest.approx(truth["positions_angstrom"])
