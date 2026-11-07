"""Measure actual imported-Cube plane workloads, including CPU parity and transfer costs."""
from pathlib import Path
import argparse
import json
import platform
import statistics
import time

from slab_preflight.compute_devices import ComputeError, probe_devices
from slab_preflight.density import parse_cube, planar_average

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--cube", type=Path, required=True)
parser.add_argument("--units", choices=("e/bohr^3", "e/angstrom^3"), required=True)
parser.add_argument("--kind", choices=("density", "difference_density", "spin_density"), default="density")
parser.add_argument("--axis", type=int, choices=(0, 1, 2), default=2)
parser.add_argument("--repeats", type=int, default=3)
parser.add_argument("--output", type=Path)
arguments = parser.parse_args()
if not 1 <= arguments.repeats <= 20:
    parser.error("--repeats must be between 1 and 20")
field = parse_cube(arguments.cube.read_bytes(), kind=arguments.kind, units=arguments.units,
                   source_name=arguments.cube.name)
report = {"host": {"system": platform.system(), "machine": platform.machine(),
                    "release": platform.release()}, "source": field.metadata(),
          "operation": "planar_average", "timing_scope": "end-to-end completed result including CPU parity, host/device transfers and helper process launch; compilation/probe excluded from warm samples",
          "devices": probe_devices(), "measurements": []}
for device in ("cpu", "metal", "cuda"):
    try:
        samples = []
        last = None
        for _ in range(arguments.repeats):
            started = time.perf_counter()
            last = planar_average(field, axis=arguments.axis, device=device)
            samples.append(time.perf_counter() - started)
        report["measurements"].append({"requested_device": device,
            "effective_device": last["execution"]["effective_device"],
            "seconds": samples, "median_seconds": statistics.median(samples),
            "execution": last["execution"], "integral_e": last["integral_e"]})
    except ComputeError as error:
        report["measurements"].append({"requested_device": device, "available": False,
                                         "reason": str(error)})
payload = json.dumps(report, indent=2, allow_nan=False)
if arguments.output:
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(payload + "\n")
    for result in report["measurements"]:
        if "median_seconds" in result:
            print(f"{result['requested_device']}: effective={result['effective_device']}; median={result['median_seconds']:.6f}s")
        else:
            print(f"{result['requested_device']}: unavailable: {result['reason']}")
    print(arguments.output)
else:
    print(payload)
