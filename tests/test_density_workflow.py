"""Density integrals and verification are reachable through the normal GUI."""

import csv
import io
import json

import pytest

import test_research_integrity as shared

app = shared.app
window = shared.window


def test_current_profile_exposes_cumulative_chart_cut_counts_and_verification(window):
    win, errors = window
    panel = shared.water(win)
    panel.average()
    integral = panel._profile["integration"]
    assert panel.profile_cut.isEnabled() and panel.profile_quantity.isEnabled()
    assert "Total integral" in panel.profile_integral_info.text()
    panel.profile_quantity.setCurrentIndex(panel.profile_quantity.findData("cumulative"))
    assert panel.chart.quantity == "cumulative"
    panel.profile_cut.setValue(integral["boundary_positions_angstrom"][0])
    assert "Below cut 0 e" in panel.profile_integral_info.text()
    panel.verify_profile()
    assert panel._verification["status"] == "passed"
    assert "verification passed" in panel.verification_info.text()
    assert panel.verification_save.isEnabled()
    exports = []
    panel._save = lambda *args: exports.append(args)
    panel.export_verification()
    verified = json.loads(exports[-1][0])
    assert verified["cpu_replay_integral_e"] == pytest.approx(panel._profile["integral_e"])
    panel.export_profile()
    rows = list(csv.DictReader(io.StringIO(exports[-1][0].decode("utf-8-sig"))))
    assert float(rows[-1]["cumulative_after_e"]) == pytest.approx(panel._profile["integral_e"])
    assert float(rows[0]["slab_lower_angstrom"]) == pytest.approx(integral["boundary_positions_angstrom"][0])
    panel.export_profile_record()
    record = json.loads(exports[-1][0])
    assert record["reproducibility"]["manifest_sha256"] == verified["record_manifest_sha256"]
    panel.axis.setCurrentIndex(0)
    assert panel._verification is None and not panel.verification_save.isEnabled()
    assert not panel.profile_verify.isEnabled()
    assert not errors


def test_retained_difference_verification_is_independent_of_later_draft_settings(window):
    win, errors = window
    panel = shared.h2(win)
    panel.difference()
    panel.verify_profile()
    assert panel._verification["status"] == "passed"
    panel.method.setText("An unrelated later draft")
    panel._store_draft()
    assert panel._profile is None and panel._verification is None
    assert panel.archive_verify.isEnabled()
    panel.verify_archive()
    assert panel._verification["status"] == "passed"
    assert len(panel._verification["source_identity_and_checksums"]) == 3
    assert panel._verification["captured_settings"]["structure_normal_axis"] == "c"
    assert not errors
