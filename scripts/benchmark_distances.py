"""Reproducible local benchmark for CalcLens periodic-distance screening."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path

from ase.build import graphene

from slab_preflight.core import _distances


ROOT = Path(__file__).resolve().parents[1]


def graphene_shape(atom_count: int) -> tuple[int, int, int]:
    if atom_count < 2 or atom_count % 2:
        raise ValueError("Atom count must be an even integer of at least 2.")
    cells = atom_count // 2
    first = int(cells**0.5)
    while cells % first:
        first -= 1
    return first, cells // first, 1


def load_from_ref(ref: str):
    source = subprocess.check_output(
        ["git", "show", f"{ref}:src/slab_preflight/core.py"], cwd=ROOT, text=True
    )
    namespace = {"__name__": f"calclens_core_{ref.replace('/', '_')}"}
    exec(compile(source, f"<{ref}:core.py>", "exec"), namespace)
    return namespace["_distances"]


def measure(function, atoms, repeats: int) -> dict:
    function(atoms, 1.0)
    samples = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = function(atoms, 1.0)
        samples.append(time.perf_counter() - start)
    return {
        "seconds": samples,
        "best_seconds": min(samples),
        "median_seconds": statistics.median(samples),
        "minimum_distance_angstrom": result[0]["distance_angstrom"],
        "short_contact_count": result[2],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--atoms", type=int, default=400)
    parser.add_argument("--repeats", type=int, default=7)
    parser.add_argument(
        "--compare-ref",
        default="v0.3.0",
        help="Git ref to benchmark against; pass an empty value to skip comparison.",
    )
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    try:
        size = graphene_shape(args.atoms)
    except ValueError as exc:
        parser.error(str(exc))
    atoms = graphene(size=size, vacuum=10)
    output = {
        "atom_count": len(atoms),
        "unordered_pair_count": len(atoms) * (len(atoms) - 1) // 2,
        "current": measure(_distances, atoms, args.repeats),
    }
    if args.compare_ref:
        output["comparison_ref"] = args.compare_ref
        output["comparison"] = measure(load_from_ref(args.compare_ref), atoms, args.repeats)
        output["median_speedup"] = (
            output["comparison"]["median_seconds"]
            / output["current"]["median_seconds"]
        )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
