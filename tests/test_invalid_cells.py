"""Malformed cells fail locally without losing valid files in a batch."""

from pathlib import Path

import pytest

from slab_preflight import UnsupportedStructure, analyze_cif
from slab_preflight.batch import BatchInput, analyze_batch, batch_rows
from slab_preflight.core import Cell
from slab_preflight.reporting import localized_error_message


GRAPHENE = Path(__file__).resolve().parents[1] / "examples" / "graphene.cif"


def impossible_cell() -> bytes:
    # Each angle passes the individual bounds and slab-normal tolerance, but
    # these nearly parallel a/b vectors cannot share the requested c angles.
    return GRAPHENE.read_bytes().replace(
        b"_cell_angle_alpha 90", b"_cell_angle_alpha 90.000001"
    ).replace(b"_cell_angle_gamma 120", b"_cell_angle_gamma 0.00000001")


def test_impossible_cell_has_a_clear_localized_input_error():
    with pytest.raises(UnsupportedStructure, match="valid three-dimensional cell") as exc:
        analyze_cif(impossible_cell())
    message = str(exc.value)
    assert localized_error_message(message) == message
    assert localized_error_message(message, "ko") == (
        "셀 길이와 각도로 유효한 3차원 셀을 구성할 수 없습니다."
    )


@pytest.mark.parametrize("bad_first", [True, False])
def test_impossible_cell_does_not_abort_other_batch_files(bad_first):
    invalid = BatchInput("invalid.cif", impossible_cell())
    valid = BatchInput("graphene.cif", GRAPHENE.read_bytes())
    inputs = [invalid, valid] if bad_first else [valid, invalid]

    results = analyze_batch(inputs)

    assert [entry["filename"] for entry in results] == [item.filename for item in inputs]
    by_filename = {entry["filename"]: entry for entry in results}
    failed = by_filename["invalid.cif"]
    assert failed["report"] is None
    assert "valid three-dimensional cell" in failed["error"]
    passed = by_filename["graphene.cif"]
    assert passed["error"] is None
    assert passed["report"]["atom_count"] == 2
    assert passed["report"]["metrics"]["minimum_distance_angstrom"] == pytest.approx(
        2.46 / 3**0.5
    )
    rows = {row["파일명"]: row for row in batch_rows(results, "ko")}
    assert rows["invalid.cif"]["상태"] == "unsupported"
    assert rows["invalid.cif"]["입력 오류"] == localized_error_message(failed["error"], "ko")
    assert rows["graphene.cif"]["상태"] == "no_flags"


def test_unexpected_cell_construction_errors_remain_visible(monkeypatch):
    def broken_constructor(*args, **kwargs):
        raise TypeError("unexpected constructor defect")

    monkeypatch.setattr(Cell, "fromcellpar", broken_constructor)
    with pytest.raises(TypeError, match="unexpected constructor defect"):
        analyze_cif(GRAPHENE.read_bytes())
