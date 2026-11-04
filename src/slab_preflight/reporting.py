"""Portable reports containing observations, criteria, and interpretation limits."""

import csv
import io


FIELDS = [
    "record_type", "code", "severity", "value", "unit", "site_i", "element_i",
    "site_j", "element_j", "image_shift_a", "image_shift_b", "image_shift_c",
    "related_sites", "normal_axis", "short_distance_threshold_angstrom", "note",
]


def _spreadsheet_text(value):
    # Text fields can eventually contain user-supplied descriptions. Keep CSV
    # formulas inert; numeric measurements retain their numeric representation.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def report_csv(report: dict) -> str:
    """Export a long-form CSV. Site numbers are one-based; JSON indexes are zero-based."""
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    shared = {
        "normal_axis": report.get("normal_axis", "c"),
        "short_distance_threshold_angstrom": report["short_distance_threshold_angstrom"],
    }

    def write(**row):
        writer.writerow({key: _spreadsheet_text(value) for key, value in (shared | row).items()})

    write(record_type="structure", code="formula", value=report["formula"])
    write(record_type="structure", code="atom_count", value=report["atom_count"], unit="sites")
    write(record_type="structure", code="schema_version", value=report["schema_version"])
    for name, value in report["metrics"].items():
        if isinstance(value, (int, float)):
            write(record_type="metric", code=name, value=value,
                  unit="angstrom" if name.endswith("_angstrom") else "fraction")
    for name, value in report.get("criteria", {
        "short_distance_threshold_angstrom": report["short_distance_threshold_angstrom"],
    }).items():
        write(record_type="criterion", code=name, value=value,
              unit=("angstrom" if name.endswith("_angstrom") else
                    "degree" if name.endswith("_degree") else "dimensionless"))
    for issue in report["issues"]:
        write(record_type="issue", code=issue["code"], severity=issue["severity"],
              related_sites=";".join(str(i + 1) for i in issue.get("atom_indices", [])),
              note=issue["message"])
    for contact in report["short_contacts"]:
        i, j = contact["i"], contact["j"]
        write(record_type="contact", code="self_image" if contact["is_self_image"] else "pair",
              value=contact["distance_angstrom"], unit="angstrom", site_i=i + 1,
              element_i=report["elements"][i], site_j=j + 1, element_j=report["elements"][j],
              image_shift_a=contact["shift"][0], image_shift_b=contact["shift"][1],
              image_shift_c=contact["shift"][2])
    write(record_type="contact_summary", code="total_count", value=report["short_contact_count"])
    write(record_type="contact_summary", code="details_truncated",
          value=str(report["short_contacts_truncated"]).lower(),
          note="At most 200 nearest-pair/self-image records; this is not a coordination list.")
    for kind in ("assumptions", "limitations"):
        for note in report[kind]:
            write(record_type=kind[:-1], note=note)
    write(record_type="convention", code="site_numbering", value="one-based",
          note="CSV sites start at 1. JSON i/j/atom_indices start at 0.")
    return output.getvalue()
