"""Local command-line entry point; input files are never uploaded."""

import argparse
import json
from pathlib import Path
import sys

from .core import UnsupportedStructure, analyze_cif


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Inspect explicit P1 slab CIF geometry; this is not a stability test."
    )
    parser.add_argument("cif", type=Path, help="CIF file (up to 2 MiB)")
    parser.add_argument("--short-distance", type=float, default=1.0, metavar="ANGSTROM",
                        help="Geometric short-contact threshold in Å (default: 1.0)")
    parser.add_argument("--json", type=Path, dest="output", metavar="PATH",
                        help="Save the report to a new JSON file; existing files are not overwritten")
    args = parser.parse_args(argv)
    try:
        with args.cif.open("rb") as source:
            data = source.read(2 * 1024 * 1024 + 1)
        report = analyze_cif(data, short_distance=args.short_distance)
        result = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as target:
                target.write(result)
        else:
            sys.stdout.write(result)
    except (OSError, UnsupportedStructure, ValueError) as exc:
        print(f"slab-preflight: {exc}", file=sys.stderr)
        return 2
    return 1 if any(issue["severity"] == "error" for issue in report["issues"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
