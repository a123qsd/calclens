import csv
import hashlib
import io
from pathlib import Path

import ase
import pytest

from slab_preflight import __version__
from slab_preflight.batch import BatchInput, analyze_batch, batch_csv, batch_rows

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def input_file(name, axis="c", cutoff=1.0):
    return BatchInput(name, (EXAMPLES / name).read_bytes(), axis, cutoff)


def test_mixed_batch_keeps_settings_order_errors_and_identity():
    inputs = [input_file("graphene.cif"), input_file("partial_occupancy.cif"),
              input_file("mos2_a_normal.cif", "a", 2.5)]
    result = analyze_batch(inputs)
    assert [entry["filename"] for entry in result] == [item.filename for item in inputs]
    assert result[1]["report"] is None
    assert "fully occupied" in result[1]["error"]
    assert result[2]["report"]["metrics"]["nuclei_gap_angstrom"] == pytest.approx(16.88)
    assert result[2]["report"]["short_distance_threshold_angstrom"] == 2.5
    for entry, item in zip(result, inputs):
        assert entry["sha256"] == hashlib.sha256(item.data).hexdigest()
    rows = batch_rows(result)
    assert rows[1]["minimum_distance_angstrom"] is None
    assert rows[1]["warning_count"] is None
    assert rows[0]["status"] == "no_flags"
    assert rows[2]["normal_axis"] == "a"
    assert rows[0]["calclens_version"]


def test_same_filename_different_content_stays_distinguishable_and_csv_safe():
    result = analyze_batch([BatchInput("=same.cif", input_file("graphene.cif").data),
                            BatchInput("=same.cif", input_file("mos2.cif").data)])
    assert result[0]["sha256"] != result[1]["sha256"]
    for language, field in (("en", "filename"), ("ko", "파일명")):
        rows = list(csv.DictReader(io.StringIO(batch_csv(result, language))))
        assert len(rows) == 2
        assert all(row[field] == "'=same.cif" for row in rows)


def test_batch_limit_and_wrong_axis_are_explicit():
    with pytest.raises(ValueError, match="between 1 and 20"):
        analyze_batch([])
    with pytest.raises(ValueError, match="between 1 and 20"):
        analyze_batch([input_file("graphene.cif")] * 21)
    results = analyze_batch([input_file("mos2_a_normal.cif"), input_file("graphene.cif")])
    assert results[0]["error"]
    assert results[1]["report"] is not None


@pytest.mark.parametrize("language", ["en", "ko"])
def test_failed_csv_rows_keep_source_and_engine_provenance(language):
    item = input_file("partial_occupancy.cif")
    result = analyze_batch([item])
    assert result[0]["report"] is None
    row = next(csv.DictReader(io.StringIO(batch_csv(result, language))))
    fields = ({"filename": "파일명", "sha256": "SHA-256",
               "calclens_version": "CalcLens 버전", "ase_version": "ASE 버전"}
              if language == "ko" else {})
    expected = {"filename": item.filename, "sha256": hashlib.sha256(item.data).hexdigest(),
                "calclens_version": __version__, "ase_version": ase.__version__}
    assert {key: row[fields.get(key, key)] for key in expected} == expected
    assert result[0]["calclens_version"] == __version__
    assert result[0]["ase_version"] == ase.__version__
