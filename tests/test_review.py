"""Stable upload identity and bounded, isolated reuse of analysis results."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from slab_preflight import batch, review
from slab_preflight.batch import BatchInput


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class Upload:
    def __init__(self, file_id=None):
        self.name = "same.cif"
        self.data = b"identical uploaded bytes"
        if file_id is not None:
            self.file_id = file_id

    def getvalue(self):
        return self.data


@pytest.mark.parametrize("remaining_ids", [("second", "third"), ("third", "second", "first")])
def test_recreated_upload_wrappers_preserve_duplicate_file_settings(remaining_ids):
    originals = [Upload(file_id) for file_id in ("first", "second", "third")]
    records = review.reconcile_uploads(originals, [])
    records = [(upload, replace(entry, normal_axis="abc"[index],
                                short_distance=1.0 + index * 0.5,
                                note=f"File {index} was reviewed", reviewed=True))
               for index, (upload, entry) in enumerate(records)]
    expected = {upload.file_id: entry for upload, entry in records}
    assert len({entry.id for _, entry in records}) == 3
    recreated = [Upload(file_id) for file_id in remaining_ids]

    reconciled = review.reconcile_uploads(recreated, records)

    assert [entry for _, entry in reconciled] == [expected[key] for key in remaining_ids]
    assert all(upload is recreated[index]
               for index, (upload, _) in enumerate(reconciled))
    assert all(new is not old for new in recreated for old in originals)


def test_upload_adapters_without_file_ids_keep_distinct_object_identities():
    first, second = Upload(), Upload()
    records = review.reconcile_uploads([first, second], [])
    first_entry, second_entry = [entry for _, entry in records]
    assert first_entry.id != second_entry.id
    records[1] = (second, replace(second_entry, short_distance=2.5, note="Keep this file"))

    reordered = review.reconcile_uploads([second, first], records)
    survivor = review.reconcile_uploads([second], reordered)

    assert [entry.id for _, entry in reordered] == [second_entry.id, first_entry.id]
    assert survivor[0][1] == records[1][1]
    new_record = review.reconcile_uploads([Upload()], survivor)[0][1]
    assert new_record.id not in (first_entry.id, second_entry.id)


def test_cached_reports_have_current_filenames_and_independent_mutable_data(monkeypatch):
    data = (EXAMPLES / "graphene.cif").read_bytes()
    original_analyze = batch.analyze_cif
    calls = []

    def analyze(*args, **kwargs):
        calls.append(args[0])
        return original_analyze(*args, **kwargs)

    monkeypatch.setattr(batch, "analyze_cif", analyze)
    inputs = [BatchInput("first.cif", data), BatchInput("second.cif", data)]
    cache = {}
    results = review.cached_batch(inputs, cache)
    expected = deepcopy(results)
    assert len(calls) == 1
    assert [entry["report"]["provenance"]["original_filename"] for entry in results] == [
        "first.cif", "second.cif",
    ]

    results[0]["report"]["positions"][0][0] = 999
    results[0]["report"]["issues"][0]["message"] = "mutated by caller"
    results[0]["report"]["provenance"]["original_filename"] = "wrong.cif"
    assert results[1] == expected[1]
    assert review.cached_batch(inputs, cache) == expected
    assert len(calls) == 1


def test_unsupported_inputs_are_cached_with_the_current_filename(monkeypatch):
    data = (EXAMPLES / "partial_occupancy.cif").read_bytes()
    original_analyze = batch.analyze_cif
    calls = []

    def analyze(*args, **kwargs):
        calls.append(args[0])
        return original_analyze(*args, **kwargs)

    monkeypatch.setattr(batch, "analyze_cif", analyze)
    cache = {}

    first = review.cached_batch([BatchInput("first.cif", data)], cache)[0]
    second = review.cached_batch([BatchInput("renamed.cif", data)], cache)[0]

    assert len(calls) == 1
    assert first["report"] is second["report"] is None
    assert "fully occupied" in first["error"]
    assert second["error"] == first["error"]
    assert (first["filename"], second["filename"]) == ("first.cif", "renamed.cif")
    assert first["sha256"] == second["sha256"]


def test_cache_is_bounded_and_recent_hits_survive_eviction(monkeypatch):
    calls = []

    def cheap_batch(inputs):
        calls.extend(item.data for item in inputs)
        return [{"filename": item.filename, "report": None, "error": "fixture input"}
                for item in inputs]

    monkeypatch.setattr(review, "analyze_batch", cheap_batch)
    cache = {}
    items = [BatchInput(f"{index}.cif", str(index).encode()) for index in range(41)]
    for item in items[:40]:
        review.cached_batch([item], cache)
        assert len(cache) <= 40
    assert len(cache) == 40
    assert len(calls) == 40

    # Refresh file 0, so adding file 40 evicts file 1 rather than file 0.
    review.cached_batch([items[0]], cache)
    review.cached_batch([items[40]], cache)
    review.cached_batch([items[0]], cache)
    assert len(calls) == 41
    assert len(cache) == 40
    review.cached_batch([items[1]], cache)
    assert len(calls) == 42
    assert calls[-1] == items[1].data
    assert len(cache) == 40
