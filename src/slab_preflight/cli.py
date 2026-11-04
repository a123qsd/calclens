"""Local command-line entry point; input files are never uploaded."""

import argparse
import json
from pathlib import Path
import sys

from .core import UnsupportedStructure, analyze_cif
from .reporting import report_csv


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect explicit P1 slab CIF geometry; this is not a stability test."
    )
    parser.add_argument("cif", type=Path, help="CIF file (up to 2 MiB)")
    parser.add_argument("--short-distance", type=float, default=1.0, metavar="ANGSTROM",
                        help="Geometric short-contact threshold in Å (default: 1.0)")
    parser.add_argument("--normal-axis", choices=["a", "b", "c"], default="c",
                        help="Candidate slab normal; must be perpendicular to the other axes")
    outputs = parser.add_mutually_exclusive_group()
    outputs.add_argument("--json", type=Path, dest="output", metavar="PATH",
                        help="Save the report to a new JSON file; existing files are not overwritten")
    outputs.add_argument("--csv", type=Path, dest="csv_output", metavar="PATH",
                         help="Save observations, criteria and limits to a new CSV file")
    args = parser.parse_args(argv)
    try:
        with args.cif.open("rb") as source:
            data = source.read(2 * 1024 * 1024 + 1)
        report = analyze_cif(data, short_distance=args.short_distance, normal_axis=args.normal_axis)
        result = (report_csv(report) if args.csv_output else
                  json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        output = args.csv_output or args.output
        if output:
            with output.open("x", encoding="utf-8", newline="") as target:
                target.write(result)
        else:
            sys.stdout.write(result)
    except (OSError, UnsupportedStructure, ValueError) as exc:
        print(f"calclens: {exc}", file=sys.stderr)
        return 2
    return 1 if any(issue["severity"] == "error" for issue in report["issues"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
