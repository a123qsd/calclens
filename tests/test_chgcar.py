from hashlib import sha256

import numpy as np
import pytest

from slab_preflight.chgcar import parse_chgcar
from slab_preflight.desktop_sources import evaluate_source


def source():
    # NX varies fastest in VASP. The second block is magnetization.
    return b"""Analytic two-element fixture
1
2 0 0
0 3 0
0 0 4
H He
1 1
Selective dynamics
Direct
0 0 0 T T T
0.5 0.5 0.5 F F F

2 3 2
0 1 2 3 4 5
6 7 8 9 10 11
augmentation occupancies 1 1
7
2 3 2
-8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8 -8
"""


def structure():
    return {"cell": np.diag([2., 3., 4.]), "elements": ["H", "He"],
            "positions": np.array([[0., 0., 0.], [1., 1.5, 2.]])}


def test_raw_first_grid_keeps_order_units_integral_and_original_byte_hash():
    raw = source().replace(b"\n", b"\r\n")
    grid = parse_chgcar(raw, structure(), "CHGCAR")
    assert grid.shape == (2, 3, 2)
    assert grid.values[1, 2, 0] == pytest.approx(5 / 24)
    assert grid.values[0, 0, 1] == pytest.approx(6 / 24)
    assert grid.values.sum() * np.linalg.det(grid.voxel_vectors_angstrom) == pytest.approx(5.5)
    assert grid.source_sha256 == sha256(raw).hexdigest() and grid.units == "e/angstrom^3"


def test_proper_cell_rotation_and_equivalent_atom_image_are_supported():
    ref = structure()
    rotation = np.array([[0, 1, 0], [-1, 0, 0], [0, 0, 1]])
    ref["cell"] = ref["cell"] @ rotation
    ref["positions"] = ref["positions"] @ rotation + ref["cell"][1]
    result = parse_chgcar(source(), ref, "CHGCAR")
    assert np.allclose(result.voxel_vectors_angstrom * np.array(result.shape)[:, None], ref["cell"])
    assert np.allclose(result.atom_positions_angstrom, ref["positions"])


@pytest.mark.parametrize("before,after,reason", [
    (b"H He", b"1 1", "explicit"), (b"1 1\nSelective", b"8000000 1\nSelective", "counts"),
    (b"0 3 0", b"0 3.1 0", "lattice"), (b"H He", b"He H", "order"),
    (b"0.5 0.5 0.5", b"0.5 0.5 0.51", "coordinates"), (b"2 3 2", b"2 3000000 2", "grid points"),
    (b"9 10 11", b"9 10", "incomplete"), (b"9 10 11", b"9 10 -11", "negative"),
    (b"9 10 11", b"9 10 nan", "non-finite"), (b"9 10 11", b"9 10 11 12", "Excess"),
])
def test_bad_input_fails_without_changing_the_field(before, after, reason):
    with pytest.raises(ValueError, match=reason):
        parse_chgcar(source().replace(before, after), structure(), "CHGCAR")


def test_restoring_changed_chgcar_rejects_the_source():
    item = {"rawText": source().decode().replace("10 11", "10 12"), "filename": "CHGCAR",
            "kind": "density", "units": "e/angstrom^3", "source": "VASP", "source_format": "vasp-chgcar",
            "source_sha256": sha256(source()).hexdigest()}
    with pytest.raises(ValueError, match="checksum"):
        evaluate_source(item, "volume", structure(), "f" * 64)
