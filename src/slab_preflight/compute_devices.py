"""Bounded real CPU, Metal and CUDA-driver workloads with numerical parity checks.

Importing this module opens no server and contacts no network. Explicit GPU
requests fail visibly; only ``auto`` permits a reported CPU fallback.
"""
from __future__ import annotations

import atexit
import ctypes
from functools import lru_cache
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import struct
import subprocess
import tempfile
import time
from typing import Any, Sequence

import numpy as np

MAX_GRID_POINTS = 1_000_000
MAX_PAIR_VECTORS = 80_000
_KERNELS = Path(__file__).with_name("kernels")
_TEMPORARIES: list[tempfile.TemporaryDirectory] = []
_AUTO_TIMINGS: dict[tuple[Any, ...], dict[str, Any]] = {}


class ComputeError(ValueError):
    """A requested compute operation is unavailable, unsafe or numerically invalid."""


def _automatic(key: tuple[Any, ...], evaluate) -> tuple[Any, ...]:
    """Choose from measured completed local workloads; retain timings, not data."""
    started = time.perf_counter()
    selection = _AUTO_TIMINGS.get(key)
    reused = selection is not None
    result = None
    failures: list[str] = []
    if selection is None:
        measurements: list[dict[str, Any]] = []
        best_seconds = float("inf")
        chosen = "cpu"
        candidates = ("cpu", "metal", "cuda") if platform.system() == "Darwin" else ("cpu", "cuda")
        for candidate in candidates:
            sample_started = time.perf_counter()
            try:
                sample = evaluate(candidate)
                seconds = time.perf_counter() - sample_started
                measurements.append({"device": candidate, "available": True,
                                     "completed_seconds": seconds})
                if seconds < best_seconds:
                    best_seconds, chosen, result = seconds, candidate, sample
            except (ComputeError, OSError) as error:
                reason = f"{candidate}: {error}"
                failures.append(reason)
                measurements.append({"device": candidate, "available": False, "reason": str(error)})
        if result is None:
            raise ComputeError("No local device completed automatic calibration: " + "; ".join(failures))
        selection = {"selected_device": chosen, "measurements": measurements,
                     "method": "lowest measured completed local call, including CPU parity, copies and helper/context overhead",
                     "workload_key": repr(key), "calibration_failures": failures}
        if len(_AUTO_TIMINGS) >= 64:
            _AUTO_TIMINGS.pop(next(iter(_AUTO_TIMINGS)))
        _AUTO_TIMINGS[key] = selection
    if result is None:
        try:
            result = evaluate(selection["selected_device"])
        except (ComputeError, OSError) as error:
            failures.append(f"{selection['selected_device']}: {error}")
            result = evaluate("cpu")
            selection = {**selection, "selected_device": "cpu",
                         "fallback_after_calibration": str(error)}
            _AUTO_TIMINGS[key] = selection
    execution = {**result[-1], "requested_device": "auto",
                 "auto_selection": {**selection, "calibration_reused": reused},
                 "elapsed_seconds": time.perf_counter() - started,
                 "fallback_reasons": list(dict.fromkeys(list(selection.get("calibration_failures", [])) + failures))}
    return (*result[:-1], execution)


def build_metal_helper(output: str | Path | None = None) -> Path:
    """Compile the bundled Swift/Metal host; distributable builds should bundle it."""
    if platform.system() != "Darwin":
        raise ComputeError("Metal compute requires macOS.")
    compiler = shutil.which("xcrun")
    if compiler is None:
        raise ComputeError("No bundled Metal helper or local Xcode command-line compiler is available.")
    if output is None:
        directory = tempfile.TemporaryDirectory(prefix="calclens-metal-")
        _TEMPORARIES.append(directory)
        atexit.register(directory.cleanup)
        target = Path(directory.name) / "calclens-metal"
    else:
        target = Path(output).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
    process = subprocess.run([compiler, "swiftc", "-O", "-target", f"{platform.machine()}-apple-macosx13.0",
                              "-framework", "Metal", "-framework",
                              "Foundation", str(_KERNELS / "compute_metal.swift"), "-o", str(target)],
                             capture_output=True, timeout=90, check=False)
    if process.returncode != 0:
        raise ComputeError("Metal helper build failed: " + process.stderr.decode(errors="replace")[-4000:])
    return target


@lru_cache(maxsize=1)
def _metal_helper() -> Path:
    if platform.system() != "Darwin":
        raise ComputeError("Metal compute requires macOS; this host is " + platform.system() + ".")
    bundled = _KERNELS / ("calclens-metal-" + platform.machine())
    if bundled.is_file() and os.access(bundled, os.X_OK):
        return bundled
    return build_metal_helper()


def _metal_arrays(arrays: Sequence[np.ndarray], axis: int) -> tuple[np.ndarray, np.ndarray, dict]:
    converted = [np.asarray(array, dtype="<f4") for array in arrays]
    if any(not np.isfinite(array).all() or np.any((source != 0) & (array == 0))
           for source, array in zip(arrays, converted, strict=True)):
        raise ComputeError("Metal float32 cannot represent these scalar values; choose CPU or CUDA float64.")
    header = json.dumps({"operation": "difference_planar" if len(arrays) == 3 else "planar",
                         "shape": list(arrays[0].shape), "axis": axis}, separators=(",", ":")).encode()
    payload = struct.pack("<I", len(header)) + header + b"".join(array.tobytes() for array in converted)
    process = subprocess.run([str(_metal_helper())], input=payload, capture_output=True,
                             timeout=45, check=False)
    if process.returncode != 0:
        raise ComputeError("Metal compute failed: " + process.stderr.decode(errors="replace")[-2000:])
    if len(process.stdout) < 4:
        raise ComputeError("Metal helper returned an incomplete response.")
    length = struct.unpack("<I", process.stdout[:4])[0]
    if length > 4096 or len(process.stdout) < 4 + length:
        raise ComputeError("Metal helper returned an invalid response header.")
    metadata = json.loads(process.stdout[4:4 + length])
    count = arrays[0].size if len(arrays) == 3 else 0
    planes = arrays[0].shape[axis]
    if len(process.stdout) != 4 + length + (count + planes) * 4:
        raise ComputeError("Metal helper returned an invalid array length.")
    values = np.frombuffer(process.stdout, dtype="<f4", offset=4 + length).astype(np.float64)
    output = values[:count].reshape(arrays[0].shape) if count else arrays[0].copy()
    return output, values[count:], metadata


class _CudaDriver:
    """Small CUDA Driver API binding; PTX is JIT-compiled by the installed driver."""

    def __init__(self) -> None:
        if platform.system() == "Windows":
            self.library = ctypes.WinDLL("nvcuda.dll")
        elif platform.system() == "Linux":
            self.library = ctypes.CDLL("libcuda.so.1")
        else:
            raise ComputeError("CUDA driver compute is supported on NVIDIA Windows/Linux hosts.")
        self.context = ctypes.c_void_p()
        self.module = ctypes.c_void_p()
        self.buffers: list[ctypes.c_uint64] = []
        self._bind()
        self.check(self.library.cuInit(0), "initialize driver")
        count = ctypes.c_int()
        self.check(self.library.cuDeviceGetCount(ctypes.byref(count)), "count devices")
        if count.value < 1:
            raise ComputeError("The NVIDIA driver reports no CUDA devices.")
        device = ctypes.c_int()
        self.check(self.library.cuDeviceGet(ctypes.byref(device), 0), "select device")
        name = ctypes.create_string_buffer(256)
        self.check(self.library.cuDeviceGetName(name, 256, device), "read device name")
        self.name = name.value.decode(errors="replace")
        self.check(self.library.cuCtxCreate_v2(ctypes.byref(self.context), 0, device), "create context")
        try:
            self.ptx = ctypes.create_string_buffer((_KERNELS / "density_cuda.ptx").read_bytes() + b"\0")
            self.check(self.library.cuModuleLoadData(ctypes.byref(self.module), self.ptx), "JIT bundled PTX (requires sm_50+)")
        except Exception:
            self.close()
            raise

    def _bind(self) -> None:
        pointer = ctypes.c_void_p
        integer = ctypes.c_int
        uint = ctypes.c_uint
        size = ctypes.c_size_t
        address = ctypes.c_uint64
        specifications = {
            "cuInit": [uint], "cuDeviceGetCount": [ctypes.POINTER(integer)],
            "cuDeviceGet": [ctypes.POINTER(integer), integer],
            "cuDeviceGetName": [pointer, integer, integer],
            "cuCtxCreate_v2": [ctypes.POINTER(pointer), uint, integer],
            "cuCtxDestroy_v2": [pointer], "cuCtxSynchronize": [],
            "cuModuleLoadData": [ctypes.POINTER(pointer), pointer], "cuModuleUnload": [pointer],
            "cuModuleGetFunction": [ctypes.POINTER(pointer), pointer, ctypes.c_char_p],
            "cuMemAlloc_v2": [ctypes.POINTER(address), size], "cuMemFree_v2": [address],
            "cuMemcpyHtoD_v2": [address, pointer, size], "cuMemcpyDtoH_v2": [pointer, address, size],
            "cuLaunchKernel": [pointer, uint, uint, uint, uint, uint, uint, uint,
                               pointer, ctypes.POINTER(pointer), ctypes.POINTER(pointer)],
            "cuGetErrorName": [integer, ctypes.POINTER(ctypes.c_char_p)],
        }
        for name, arguments in specifications.items():
            function = getattr(self.library, name)
            function.argtypes = arguments
            function.restype = integer

    def check(self, code: int, action: str) -> None:
        if code:
            name = ctypes.c_char_p()
            self.library.cuGetErrorName(code, ctypes.byref(name))
            reason = name.value.decode() if name.value else str(code)
            raise ComputeError(f"CUDA could not {action}: {reason}.")

    def allocate(self, array: np.ndarray | None, count: int = 0) -> ctypes.c_uint64:
        pointer = ctypes.c_uint64()
        length = array.nbytes if array is not None else count * 8
        self.check(self.library.cuMemAlloc_v2(ctypes.byref(pointer), length), "allocate memory")
        self.buffers.append(pointer)
        if array is not None:
            self.check(self.library.cuMemcpyHtoD_v2(pointer, array.ctypes.data, length), "upload scalars")
        return pointer

    def launch(self, name: bytes, arguments: list[Any], threads: int) -> None:
        function = ctypes.c_void_p()
        self.check(self.library.cuModuleGetFunction(ctypes.byref(function), self.module, name), "load kernel")
        parameters = (ctypes.c_void_p * len(arguments))(*(ctypes.addressof(value) for value in arguments))
        self.check(self.library.cuLaunchKernel(function, (threads + 127) // 128, 1, 1,
                                              128, 1, 1, 0, None, parameters, None), "launch kernel")

    def download(self, pointer: ctypes.c_uint64, shape: tuple[int, ...]) -> np.ndarray:
        result = np.empty(shape, dtype=np.float64)
        self.check(self.library.cuMemcpyDtoH_v2(result.ctypes.data, pointer, result.nbytes), "download result")
        return result

    def close(self) -> None:
        for pointer in self.buffers:
            self.library.cuMemFree_v2(pointer)
        self.buffers.clear()
        if self.module:
            self.library.cuModuleUnload(self.module)
            self.module = ctypes.c_void_p()
        if self.context:
            self.library.cuCtxDestroy_v2(self.context)
            self.context = ctypes.c_void_p()


def _cuda_arrays(arrays: Sequence[np.ndarray], axis: int) -> tuple[np.ndarray, np.ndarray, dict]:
    driver = _CudaDriver()
    try:
        sources = [driver.allocate(np.ascontiguousarray(array, dtype=np.float64)) for array in arrays]
        count = arrays[0].size
        if len(arrays) == 3:
            output = driver.allocate(None, count)
            driver.launch(b"density_difference", sources + [output, ctypes.c_uint(count)], count)
        else:
            output = sources[0]
        average = driver.allocate(None, arrays[0].shape[axis])
        driver.launch(b"density_planar", [output, average,
                      *(ctypes.c_uint(value) for value in arrays[0].shape), ctypes.c_uint(axis)],
                      arrays[0].shape[axis])
        driver.check(driver.library.cuCtxSynchronize(), "synchronize result")
        values = driver.download(output, arrays[0].shape)
        planes = driver.download(average, (arrays[0].shape[axis],))
        return values, planes, {"device_name": driver.name, "precision": "float64",
                                "implementation": "bundled PTX via installed NVIDIA CUDA driver"}
    finally:
        driver.close()


def _validate_arrays(arrays: Sequence[np.ndarray], axis: int) -> list[np.ndarray]:
    if len(arrays) not in (1, 3) or isinstance(axis, bool) or axis not in (0, 1, 2):
        raise ComputeError("Supported workloads take one field or three difference fields and axis 0, 1 or 2.")
    converted = [np.asarray(array, dtype=np.float64) for array in arrays]
    shape = converted[0].shape
    if len(shape) != 3 or min(shape) < 2 or converted[0].size > MAX_GRID_POINTS:
        raise ComputeError("Compute grids need three dimensions, at least two points per axis and at most 1,000,000 points.")
    if any(array.shape != shape or not np.isfinite(array).all() for array in converted):
        raise ComputeError("Compute arrays must have identical shapes and only finite scalar values.")
    return converted


def _parity(values: np.ndarray, planes: np.ndarray, truth: np.ndarray,
            truth_planes: np.ndarray, precision: str) -> dict[str, Any]:
    relative = 5e-6 if precision == "float32" else 1e-12
    floor = 1e-12 if precision == "float32" else 1e-14
    absolute = max(floor, relative * float(np.max(np.abs(truth))))
    plane_absolute = max(floor, relative * float(np.max(np.abs(truth_planes))))
    if values.shape != truth.shape or planes.shape != truth_planes.shape:
        raise ComputeError("Device result shape failed CPU parity.")
    value_error = float(np.max(np.abs(values - truth)))
    plane_error = float(np.max(np.abs(planes - truth_planes)))
    max_error = max(value_error, plane_error)
    if not (
            np.isfinite(values).all() and np.isfinite(planes).all()
            and np.allclose(values, truth, rtol=relative, atol=absolute)
            and np.allclose(planes, truth_planes, rtol=relative, atol=plane_absolute)):
        raise ComputeError(f"Device result failed CPU float64 parity (max absolute error {max_error:.6g}, value atol {absolute:.6g}, plane atol {plane_absolute:.6g}, rtol {relative:g}); cancellation may exceed device precision.")
    return {"reference": "CPU NumPy float64", "passed": True, "max_absolute_error": max_error,
            "absolute_tolerance": absolute, "relative_tolerance": relative,
            "planar_absolute_tolerance": plane_absolute,
            "value_max_absolute_error": value_error, "planar_max_absolute_error": plane_error,
            "note": "Numerical tolerance is not an electronic-structure convergence criterion."}


def compute_arrays(arrays: Sequence[np.ndarray], *, axis: int = 2, device: str = "cpu",
                   remote: Any = None) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Real difference/plane workloads; every non-CPU result is checked against CPU."""
    arrays = _validate_arrays(arrays, axis)
    if device not in {"cpu", "auto", "metal", "cuda", "remote"}:
        raise ComputeError("Select cpu, auto, metal, cuda or remote.")
    if device == "auto":
        return _automatic(("difference_planar" if len(arrays) == 3 else "planar", arrays[0].shape, axis),
                          lambda selected: compute_arrays(arrays, axis=axis, device=selected))
    started = time.perf_counter()
    with np.errstate(over="ignore", invalid="ignore"):
        truth = arrays[0].copy() if len(arrays) == 1 else arrays[0] - arrays[1] - arrays[2]
    if not np.isfinite(truth).all():
        raise ComputeError("The difference exceeds CPU float64 numerical range.")
    with np.errstate(over="ignore", invalid="ignore"):
        truth_planes = np.mean(truth, axis=tuple(value for value in range(3) if value != axis), dtype=np.float64)
    if not np.isfinite(truth_planes).all():
        raise ComputeError("Plane reduction exceeds CPU float64 numerical range.")
    failures: list[str] = []
    candidates = (["metal", "cuda", "cpu"] if device == "auto" and platform.system() == "Darwin"
                  else ["cuda", "cpu"] if device == "auto" else [device])
    for candidate in candidates:
        try:
            metadata: dict[str, Any] = {"device_name": platform.processor() or platform.machine(),
                                       "precision": "float64", "implementation": "NumPy CPU"}
            if candidate == "cpu":
                values, planes = truth, truth_planes
            elif candidate == "remote":
                if remote is None:
                    raise ComputeError("Remote compute requires an explicitly supplied endpoint and authentication token.")
                from .compute_server import remote_arrays
                values, planes, metadata = remote_arrays(arrays, axis=axis, config=remote)
            else:
                values, planes, metadata = (_metal_arrays if candidate == "metal" else _cuda_arrays)(arrays, axis)
            parity = _parity(values, planes, truth, truth_planes, metadata.get("precision", "float64"))
            return values, planes, {"requested_device": device, "effective_device": candidate,
                **metadata, "elapsed_seconds": time.perf_counter() - started,
                "includes_cpu_parity_check": True, "parity": parity,
                "fallback_reasons": failures, "operation": "density_difference_and_planar" if len(arrays) == 3 else "planar_average"}
        except (ComputeError, OSError, subprocess.SubprocessError, ValueError, AttributeError) as error:
            if device != "auto":
                if isinstance(error, ComputeError):
                    raise
                raise ComputeError(f"Explicit {candidate} compute failed: {error}") from error
            failures.append(f"{candidate}: {error}")
    raise ComputeError("No compute device completed the requested workload.")


def probe_devices() -> list[dict[str, Any]]:
    """Probe actual small arithmetic/reduction workloads; never contact a remote host."""
    sample = np.arange(24, dtype=np.float64).reshape((2, 3, 4)) / 10
    result: list[dict[str, Any]] = []
    for device in ("cpu", "metal", "cuda"):
        try:
            _, _, execution = compute_arrays([sample, sample * .25, sample * .5], device=device)
            compute_norms([[3., 4., 0.], [0., 0., 2.]], device=device)
            result.append({"id": device, "available": True, "workload_verified": True,
                           "device_name": execution["device_name"], "precision": execution["precision"],
                           "workloads": ["density_difference", "planar_average", "periodic_pair_norms"], "reason": None})
        except (ComputeError, OSError) as error:
            result.append({"id": device, "available": False, "workload_verified": False,
                           "workloads": ["density_difference", "planar_average", "periodic_pair_norms"], "reason": str(error)})
    return result


detect_compute_devices = probe_devices


def _validate_vectors(vectors: Any) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float64)
    if (array.ndim != 2 or array.shape[1] != 3 or not 1 <= len(array) <= MAX_PAIR_VECTORS
            or not np.isfinite(array).all() or np.max(np.abs(array)) > 1e6):
        raise ComputeError("Vector norms require 1–80,000 finite three-vectors within ±1,000,000 Å.")
    return array


def _metal_norms(vectors: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    converted = np.asarray(vectors, dtype="<f4")
    header = json.dumps({"operation": "norms", "shape": list(vectors.shape), "axis": 0},
                        separators=(",", ":")).encode()
    payload = struct.pack("<I", len(header)) + header + converted.tobytes()
    process = subprocess.run([str(_metal_helper())], input=payload, capture_output=True,
                             timeout=45, check=False)
    if process.returncode or len(process.stdout) < 4:
        raise ComputeError("Metal vector norms failed: " + process.stderr.decode(errors="replace")[-2000:])
    length = struct.unpack("<I", process.stdout[:4])[0]
    if length > 4096 or len(process.stdout) != 4 + length + len(vectors) * 4:
        raise ComputeError("Metal vector-norm response has an invalid size.")
    metadata = json.loads(process.stdout[4:4 + length])
    return np.frombuffer(process.stdout, dtype="<f4", offset=4 + length).astype(np.float64), metadata


def _cuda_norms(vectors: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    driver = _CudaDriver()
    try:
        source = driver.allocate(np.ascontiguousarray(vectors, dtype=np.float64))
        output = driver.allocate(None, len(vectors))
        driver.launch(b"vector_norms", [source, output, ctypes.c_uint(len(vectors))], len(vectors))
        driver.check(driver.library.cuCtxSynchronize(), "synchronize vector norms")
        return driver.download(output, (len(vectors),)), {
            "device_name": driver.name, "precision": "float64",
            "implementation": "bundled vector-norm PTX via installed NVIDIA CUDA driver"}
    finally:
        driver.close()


def compute_norms(vectors: Any, *, device: str = "cpu", remote: Any = None
                  ) -> tuple[np.ndarray, dict[str, Any]]:
    """Evaluate norms of already selected image displacements, with strict parity."""
    array = _validate_vectors(vectors)
    if device not in {"cpu", "auto", "metal", "cuda", "remote"}:
        raise ComputeError("Select cpu, auto, metal, cuda or remote.")
    if device == "auto":
        return _automatic(("vector_norms", array.shape),
                          lambda selected: compute_norms(array, device=selected))
    started = time.perf_counter()
    truth = np.linalg.norm(array, axis=1)
    failures: list[str] = []
    candidates = (["metal", "cuda", "cpu"] if device == "auto" and platform.system() == "Darwin"
                  else ["cuda", "cpu"] if device == "auto" else [device])
    for candidate in candidates:
        try:
            metadata: dict[str, Any] = {"device_name": platform.processor() or platform.machine(),
                                       "precision": "float64", "implementation": "NumPy CPU norms"}
            if candidate == "cpu":
                values = truth.copy()
            elif candidate == "remote":
                if remote is None:
                    raise ComputeError("Remote vector norms require an explicit endpoint and authentication token.")
                from .compute_server import remote_norms
                values, metadata = remote_norms(array, config=remote)
            else:
                values, metadata = (_metal_norms if candidate == "metal" else _cuda_norms)(array)
            relative = 2e-6 if metadata.get("precision") == "float32" else 1e-12
            absolute = 1e-8 if metadata.get("precision") == "float32" else 1e-12
            if values.shape != truth.shape or not np.isfinite(values).all() or not np.allclose(
                    values, truth, rtol=relative, atol=absolute):
                raise ComputeError("Device vector norms failed CPU float64 parity; scientific distances were not replaced.")
            return values, {"requested_device": device, "effective_device": candidate,
                **metadata, "elapsed_seconds": time.perf_counter() - started,
                "includes_cpu_parity_check": True, "fallback_reasons": failures,
                "operation": "norms_of_CPU_selected_periodic_displacements", "parity": {
                    "reference": "CPU NumPy float64", "passed": True,
                    "max_absolute_error_angstrom": float(np.max(np.abs(values - truth))),
                    "relative_tolerance": relative, "absolute_tolerance_angstrom": absolute}}
        except (ComputeError, OSError, subprocess.SubprocessError, ValueError, AttributeError) as error:
            if device != "auto":
                if isinstance(error, ComputeError):
                    raise
                raise ComputeError(f"Explicit {candidate} vector norms failed: {error}") from error
            failures.append(f"{candidate}: {error}")
    raise ComputeError("No device completed the vector-norm workload.")


def minimum_image_pair_distances(positions: Any, cell: Any, *,
                                 pairs: Sequence[Sequence[int]] | None = None,
                                 device: str = "cpu", remote: Any = None) -> dict[str, Any]:
    """CPU ASE selects periodic images; the chosen device evaluates vector norms.

    Pair indices are zero-based. CSV-friendly records also include one-based site
    numbers. ``distance_angstrom`` always retains CPU scientific truth; the real
    device evaluation is separately visible as ``device_distance_angstrom``.
    """
    from ase.geometry import find_mic
    started = time.perf_counter()
    positions = np.asarray(positions, dtype=np.float64)
    basis = np.asarray(cell, dtype=np.float64)
    if (positions.ndim != 2 or positions.shape[1] != 3 or not 2 <= len(positions) <= 400
            or not np.isfinite(positions).all() or np.max(np.abs(positions)) > 1e6
            or basis.shape != (3, 3) or not np.isfinite(basis).all()
            or np.max(np.abs(basis)) > 10000 or np.linalg.cond(basis) > 10000
            or np.min(np.linalg.norm(basis, axis=1)) < .001
            or np.max(np.linalg.norm(basis, axis=1)) > 10000):
        raise ComputeError("Periodic pairs require 2–400 finite positions and a well-conditioned 3×3 cell.")
    selected = ([(i, j) for i in range(len(positions)) for j in range(i + 1, len(positions))]
                if pairs is None else [tuple(pair) for pair in pairs])
    if not 1 <= len(selected) <= MAX_PAIR_VECTORS:
        raise ComputeError("Select between 1 and 80,000 distinct non-self pairs.")
    seen: set[tuple[int, int]] = set()
    for pair in selected:
        if (len(pair) != 2 or any(isinstance(value, bool) or not isinstance(value, (int, np.integer))
                                  or not 0 <= value < len(positions) for value in pair)
                or pair[0] == pair[1]):
            raise ComputeError("Pair indices must be distinct zero-based atom indices in range.")
        key = tuple(sorted(pair))
        if key in seen:
            raise ComputeError("Repeated unordered atom pairs are not accepted.")
        seen.add(key)
    displacements = np.array([positions[j] - positions[i] for i, j in selected])
    image_started = time.perf_counter()
    minimum_vectors, cpu_lengths = find_mic(displacements, basis, pbc=True)
    shifts = np.rint((minimum_vectors - displacements) @ np.linalg.inv(basis)).astype(np.int64)
    if not np.allclose(minimum_vectors, displacements + shifts @ basis, rtol=1e-10, atol=1e-8):
        raise ComputeError("CPU minimum-image vectors could not be represented by stable original-cell shifts.")
    image_seconds = time.perf_counter() - image_started
    values, execution = compute_norms(minimum_vectors, device=device, remote=remote)
    records = [{"i": int(i), "j": int(j), "site_i": int(i + 1), "site_j": int(j + 1),
                "shift": shift.tolist(), "shift_a": int(shift[0]), "shift_b": int(shift[1]),
                "shift_c": int(shift[2]), "displacement_angstrom": vector.tolist(),
                "distance_angstrom": float(truth), "device_distance_angstrom": float(value)}
               for (i, j), shift, vector, truth, value in zip(
                   selected, shifts, minimum_vectors, cpu_lengths, values, strict=True)]
    return {"pairs": records, "pair_count": len(records), "execution": execution,
            "geometry_sha256": sha256(np.asarray(positions, dtype="<f8").tobytes()
                                      + np.asarray(basis, dtype="<f8").tobytes()).hexdigest(),
            "geometry_hash_scope": "Cartesian float64 positions followed by row cell vectors; not original CIF bytes",
            "timing": {"minimum_image_selection_seconds": image_seconds,
                       "distance_evaluation_seconds": execution["elapsed_seconds"],
                       "total_seconds": time.perf_counter() - started},
            "scientific_authority": "CPU ASE minimum-image distances; GPU norms are independently checked and recorded",
            "limitations": ["Distinct atom pairs only; shortest nonzero self-images are handled by the core report.",
                            "One closest periodic image per unordered pair; ties are not exhaustively enumerated.",
                            "GPU timing covers vector norms after CPU image selection, not the entire geometry analysis."]}
