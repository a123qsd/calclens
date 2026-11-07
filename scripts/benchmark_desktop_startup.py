"""Measure actual Windows distributions; Wine results stay explicitly labelled.

Run on the target Windows machine for Windows performance claims. No cache purge,
antivirus changes, network requests or administrator privileges are performed.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import threading
import time


def windows_path(path, *, wine=False):
    path = str(Path(path).resolve())
    return "Z:" + path.replace("/", "\\") if wine else path


def measure(executable, output, *, runs=3, runner=None, legacy_smoke=False,
            timeout=120, environment=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    executable = Path(executable).resolve()
    wine = runner is not None
    if not wine and sys.platform != "win32":
        raise ValueError("Run this on Windows, or explicitly provide a Wine --runner.")
    observations = []
    for index in range(runs):
        trace = output / f"run-{index + 1}.json"
        if trace.exists():
            raise ValueError(f"Refusing to reuse an old timing result: {trace}")
        command = ([str(runner)] if runner else []) + [str(executable), "--language", "en",
                    "--native-smoke" if legacy_smoke else "--startup-benchmark",
                    windows_path(trace, wine=wine)]
        child_env = dict(os.environ if environment is None else environment)
        started = time.perf_counter_ns()
        # perf_counter origins are shared between processes on Windows. Do not
        # claim that macOS and the Wine Windows clock share a reference point.
        if not wine:
            child_env["CALCLENS_STARTUP_PARENT_NS"] = str(started)
        else:
            child_env.pop("CALCLENS_STARTUP_PARENT_NS", None)
        observed = {}
        stopped = threading.Event()

        def observe():
            try:
                current = json.loads(trace.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return
            receipt_ms = round((time.perf_counter_ns() - started) / 1e6, 3)
            for stage in current.get("milestones_ms", {}):
                observed.setdefault(stage, receipt_ms)

        def watch():
            while not stopped.wait(0.025):
                observe()

        watcher = threading.Thread(target=watch, daemon=True)
        watcher.start()
        with (output / f"run-{index + 1}.output.txt").open("w", encoding="utf-8") as log:
            try:
                completed = subprocess.run(command, env=child_env, stdout=log, stderr=log,
                                           timeout=timeout, check=False)
            finally:
                stopped.set()
                watcher.join()
                observe()
        elapsed = round((time.perf_counter_ns() - started) / 1e6, 3)
        record = json.loads(trace.read_text(encoding="utf-8")) if trace.is_file() else {}
        success = record.get("status") == "passed" if legacy_smoke else record.get("ready") is True
        observation = {"run": index + 1, "kind": "first_observed" if index == 0 else "repeat",
                       "process_wall_ms": elapsed, "exit_code": completed.returncode,
                       "passed": completed.returncode == 0 and success, "trace": record}
        if observed:
            observation["observed_launch_to_ms"] = observed
        observations.append(observation)
        print(json.dumps({key: value for key, value in observation.items() if key != "trace"}), flush=True)
        if not observation["passed"]:
            break
    repeats = [item["process_wall_ms"] for item in observations[1:] if item["passed"]]
    result = {
        "schema_version": 1,
        "status": "passed" if len(observations) == runs and all(item["passed"] for item in observations) else "failed",
        "environment": "Wine on " + platform.system() if wine else "Windows",
        "host_architecture": platform.machine(),
        "host_os": platform.platform(),
        "executable": executable.name,
        "executable_sha256": sha256(executable.read_bytes()).hexdigest(),
        "mode": "legacy smoke total (not readiness)" if legacy_smoke else "startup milestones",
        "first_is_cold_boot": False,
        "cache_policy": "OS and application caches are left unchanged; first observed run then repeats",
        "process_wall_includes": "launcher, runtime, GUI, readiness/verification and orderly shutdown",
        "observation_method": "Parent reads atomic trace updates every 25 ms; receipt times are upper bounds, subject to scheduling",
        "windows_performance_measured": not wine,
        "runs": observations,
        "repeat_wall_median_ms": statistics.median(repeats) if repeats else None,
    }
    (output / "summary.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--runner", type=Path, help="Explicit Wine executable; results are not Windows timings.")
    parser.add_argument("--legacy-smoke", action="store_true", help="For older EXEs lacking startup traces.")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    if not 2 <= args.runs <= 20:
        parser.error("--runs must be between 2 and 20")
    result = measure(args.exe, args.output, runs=args.runs, runner=args.runner,
                     legacy_smoke=args.legacy_smoke, timeout=args.timeout)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
