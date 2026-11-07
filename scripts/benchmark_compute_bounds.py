"""Measure bounded 1,000,000-voxel and 400-site numerical workloads on this host.

These deterministic fixtures exercise implementation limits, not electronic
calculations or experimentally validated materials. No speedup is assumed.
"""
import argparse
import json
from pathlib import Path
import platform
import statistics
import time

import numpy as np

from slab_preflight.compute_devices import (
    ComputeError, compute_arrays, minimum_image_pair_distances, probe_devices,
)

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--repeats", type=int, default=3)
arguments = parser.parse_args()
if not 1 <= arguments.repeats <= 10:
    parser.error("--repeats must be 1–10")

field = np.arange(1_000_000, dtype=np.float64).reshape((100, 100, 100)) / 1_000_000 + .25
fragments = [field, field * .25, field * .5]
cell = np.array([[10., 0., 0.], [2., 10., 0.], [0., 0., 20.]])
positions = np.random.default_rng(20261107).random((400, 3)) @ cell
report = {"host": {"system": platform.system(), "machine": platform.machine(), "release": platform.release()},
          "fixture_status": "deterministic numerical boundary fixtures, not physical electron-density calculations",
          "timing_scope": "completed calls including CPU parity, transfers, context/helper overhead; probing/compilation excluded",
          "devices": probe_devices(), "measurements": []}

for workload in ("planar_1e6", "difference_planar_1e6", "periodic_pairs_400_sites"):
    for device in ("cpu", "metal", "cuda", "auto"):
        samples = []
        stages = []
        try:
            for _ in range(arguments.repeats):
                started = time.perf_counter()
                if workload == "periodic_pairs_400_sites":
                    result = minimum_image_pair_distances(positions, cell, device=device)
                    execution = result["execution"]
                    stages.append(result["timing"])
                    count = result["pair_count"]
                    del result
                else:
                    _, _, execution = compute_arrays(fragments if workload.startswith("difference") else [field], device=device)
                    count = field.size
                samples.append(time.perf_counter() - started)
            report["measurements"].append({"workload": workload, "count": count,
                "requested_device": device, "effective_device": execution["effective_device"],
                "seconds": samples, "median_seconds": statistics.median(samples),
                "stages": stages, "execution": execution})
        except ComputeError as error:
            report["measurements"].append({"workload": workload, "requested_device": device,
                                            "available": False, "reason": str(error)})

arguments.output.parent.mkdir(parents=True, exist_ok=True)
arguments.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
for result in report["measurements"]:
    if "median_seconds" in result:
        print(f"{result['workload']}: requested={result['requested_device']}; effective={result['effective_device']}; median={result['median_seconds']:.6f}s")
    else:
        print(f"{result['workload']}: {result['requested_device']} unavailable: {result['reason']}")
print(arguments.output)
