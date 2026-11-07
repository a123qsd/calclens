# Scientific post-processing and compute devices

CalcLens post-processes externally calculated Cube fields. It does not obtain an
electron density from a CIF or run a DFT, Gaussian, ORCA, relaxation or SCF job.
Source SHA-256 hashes, declared field types, physical units and calculation
conditions accompany the result.

CalcLens는 외부 계산으로 얻은 Cube 자료를 후처리합니다. CIF만으로 전자 밀도를
계산하거나 전자구조 계산을 실행하지 않습니다. CPU·GPU·서버 선택은 아래 수치
작업의 실행 위치를 정하며, 원본 계산의 정확성을 보증하지 않습니다.

## Fields and frozen-geometry density difference

`parse_cube(data, kind=..., units=..., source_name=...)` returns a `CubeGrid`.
It accepts one scalar field, 1,000,000 grid points, 400 atom records and 32 MiB
per Cube. Values, origin, voxel vectors and atom coordinates must be finite.
Spatial coordinates use the existing CalcLens convention: all positive voxel
counts mean Bohr and all negative counts mean Å. Mixed signs are rejected.
Verify this convention against the Cube producer; it is not universal.

| Declared kind | Scalar units accepted | Computation |
| --- | --- | --- |
| `density` | `e/bohr^3`, `e/angstrom^3` | Nonnegative total electron density |
| `difference_density` | `e/bohr^3`, `e/angstrom^3` | Explicitly signed electron-density difference |
| `spin_density` | `e/bohr^3`, `e/angstrom^3` | Explicitly signed spin electron density |
| `orbital` | `bohr^-3/2`, `angstrom^-3/2`, `arbitrary` | Surface input only; excluded from physical density averages/differences |

Density values are converted to `e/angstrom^3` independently of spatial units.
Orbital amplitudes with physical units are converted to `angstrom^-3/2`; arbitrary
amplitudes stay arbitrary. Comments and filenames never determine field kind.
Negative values cannot silently enter the total-density path.
Cube atom-record charges are retained on export, including effective core-charge
values. They are never imported as partial atomic charges or replaced by atomic numbers.

`density_difference(ab, a, b, a_indices=..., b_indices=..., method=...,
reference_conditions=..., frozen_geometry=True, axis=2, normal=None,
device="cpu", remote=None)` computes `rho_AB - rho_A - rho_B` only when:

- All three sources are total electron densities on the same grid. Counts must
  agree exactly; origins and voxel bases agree within `1e-8 Å`, with no relative
  tolerance, interpolation, translation, rotation or periodic registration.
- One-based `a_indices` and `b_indices` disjointly partition every AB atom.
  Each fragment's Cube order and elements match its explicitly selected AB atoms.
  Nuclear positions agree within `1e-6 Å` Euclidean distance. Separately relaxed
  fragments are rejected.
- The caller explicitly confirms frozen geometry and declares a common method
  and reference conditions. These should identify basis/pseudopotentials,
  spin/charge/electron reference states, potential reference and numerical settings
  relevant to comparability. CalcLens records the declaration; it cannot prove
  that the external calculations actually used those settings.

The `DensityComputation` contains `.grid`, `.profile`, `.execution` and
`.provenance`. `to_dict(include_values=False)` produces an inspectable report;
`cube_bytes(result.grid)` exports the normalized signed field. The derived hash
identifies the recorded source hashes, declarations and resulting float64 array.
It is distinguished from the exact-byte hashes of the three imported sources.

Positive difference density means electron accumulation relative to the declared
fragments. Electric-charge sign is opposite. A density difference alone does not
assign atomic charges or establish a unique transferred-electron count.

AB−A−B는 같은 격자와 동결된 원자 위치에서 계산한 세 전자 밀도만 사용합니다.
A·B의 원자 번호는 AB 기준 1부터 시작하며 전체 원자를 중복 없이 나눠야 합니다.
각 조각을 따로 최적화했거나 격자 원점·기저가 다르면 계산을 거부합니다.
공통 계산법과 기준 조건은 사용자가 명시하고, 세 원본의 해시와 함께 기록합니다.
궤도·스핀 밀도·기존 차분 밀도를 전체 전자 밀도로 바꿔 쓰지 않습니다.

## Planar averages and integration

`planar_average(grid, axis=2, normal=None, device="cpu", remote=None)` accepts the
three density kinds. The selected axis identifies the grid direction between
planes. The other two voxel vectors must lie in the supplied slab plane. If
`normal` is supplied, it must be perpendicular to those two vectors; an
incompatible grid is rejected rather than resampled. Without a supplied normal,
CalcLens uses their cross product, oriented toward the selected voxel vector.

For voxel row vectors `b_u`, `b_v`, `b_w`, counts `N_u`, `N_v`, `N_w`, unit normal
`n` and origin `o`, the reported quantities are:

```text
plane average(k) = sum of rho on plane k / (N_u * N_v)       [e/Å³]
plane area      = N_u * N_v * |b_u × b_v|                    [Å²]
plane position  = o · n + k * (b_w · n)                     [Å]
line density    = plane average * plane area                [e/Å]
integral        = sum(rho) * |det(voxel basis)|              [e]
```

The spacing uses the projection `b_w · n`, including when that voxel vector is
tilted. Skewed in-plane vectors are supported. Positions and corresponding
averages are sorted together when the supplied normal reverses direction.
The quadrature is an equal-volume voxel rectangle rule: the domain spans `N`
voxel steps, not `N-1`. No endpoint/trapezoid correction, missing-density estimate
or physical electron-number convergence claim is inferred. A finite coarse Cube
can integrate to a value different from the system's expected electron count.

면 평균은 실제 슬랩 법선에 평행한 격자면에서 구합니다. 원점의 법선 투영, 기울어진
복셀의 수직 간격, 면적을 함께 반영합니다. 적분은 복셀 부피를 곱한 수치 합이며,
원자별 전하 분할이나 전자 수 수렴 검증을 대신하지 않습니다.

## Devices and numerical checks

`probe_devices()` / `detect_compute_devices()` runs small real difference,
plane-reduction and vector-norm workloads. An operating-system name or installed
driver alone does not establish availability.

| Selection | Implementation and behavior |
| --- | --- |
| `cpu` | NumPy float64; authoritative numerical reference |
| `metal` | Native Swift host and Metal float32 kernels on a usable macOS device |
| `cuda` | Bundled float64 PTX JIT-compiled by the installed NVIDIA driver on Windows/Linux; `sm_50` or newer |
| `auto` | Measures completed local CPU/GPU calls and selects the fastest validated result for that workload |
| `remote` | Contacts only the explicitly configured authenticated worker for this request |

Explicit `metal`, `cuda` and `remote` requests fail visibly when unavailable or
outside numerical tolerance. They do not silently return a different local
device. `auto` includes CPU parity, copies and helper/context overhead in its
measurement; it does not use GPU kernel time alone. It caches up to 64 decisions
per process by operation, shape and plane axis. The first call includes calibration
cost; later calls reuse the measured choice. A failed cached device returns a
reported CPU fallback. `auto` never selects or contacts a remote endpoint. Worker-side `auto`
may fall back locally; both the remote selection and the worker's effective
device are reported.

Each non-CPU result is compared with CPU float64 results. Density/value and
planar tolerances are calculated separately: relative tolerance `5e-6` for
Metal float32 and `1e-12` for CUDA float64; absolute tolerances scale with the
corresponding output, with floors `1e-12` and `1e-14`. Recorded errors and
tolerances accompany the result. Severe float32 cancellation can therefore
reject a Metal difference and cause a reported CPU fallback in `auto` mode.
Numerical parity does not establish physical convergence or correctness of an
external calculation.

The packaged macOS application should include
`slab_preflight/kernels/calclens-metal-arm64`, built with:

```sh
python scripts/build_compute_metal.py --output src/slab_preflight/kernels/calclens-metal-arm64
```

The helper targets macOS 13 or newer. Include `compute_metal.swift` and
`density_cuda.ptx` as package resources too. Source checkouts can build the helper
using local Xcode command-line tools; no compiler, driver or network download is
installed automatically. Windows CUDA execution needs the NVIDIA driver and the
bundled PTX, not CuPy or a CUDA toolkit. CUDA hardware verification remains a
separate requirement before claiming that a particular GPU works.

CPU 기준값과 실제 장치 결과를 비교한 뒤 선택 장치·실행 장치·오차·실패 사유를
표시합니다. `auto`만 CPU 대체 실행을 허용합니다. GPU가 있다는 이유로 계산이
빨라졌다고 판단하지 않으며, 업로드·프로세스 실행·검증 비용도 측정에 포함합니다.

## Periodic pair distances

`minimum_image_pair_distances(positions, cell, pairs=None, device="cpu",
remote=None)` is in `compute_devices.py`. It supports 2–400 atoms and up to
80,000 displacement vectors. `pairs` uses zero-based indices; omitted pairs mean
all unordered distinct atom pairs. CPU ASE chooses the minimum-image vectors
for the original row-vector cell. The selected device actually evaluates their
norms. It does not replace ASE's periodic-image search or the core scientific
report.

CSV-ready records contain zero-based `i`/`j`, one-based `site_i`/`site_j`, original
cell `shift_a`/`shift_b`/`shift_c`, `distance_angstrom` (CPU scientific truth), and
`device_distance_angstrom` (the checked device result). Shifts reconstruct
`r_j + shift @ cell - r_i`. The report separates CPU image-selection time,
device-evaluation time and total time. Metal norm parity uses `rtol=2e-6` and
`atol=1e-8 Å`; CUDA uses `rtol=1e-12` and `atol=1e-12 Å`.

Only one closest image per unordered pair is recorded. Ties and nonzero
self-images are not enumerated here; the core report retains its existing
self-image checks. A remote pair request transmits anonymous displacement
vectors, not CIF bytes, atom identities or the project.

## Explicit remote worker

Importing these modules and launching the normal desktop workspace neither opens
a compute server nor contacts a remote host. A user must start a worker and
initiate a request. For a source installation:

```sh
python -m slab_preflight.compute_server --host 127.0.0.1 --port 8768 --token-file /private/path/worker-token --device cuda
```

The native executable can route `--worker` to the same worker entry point. The
token file must contain a random 32–512 character printable token with no
spaces. Keep it private and provide the same value to the initiating client.

`RemoteComputeConfig(url, token, device="auto", timeout_seconds=45, ca_file=None)`
accepts cleartext HTTP only for literal loopback IP addresses. Other endpoints
require certificate-verified HTTPS; `ca_file` explicitly supplies a private CA
when needed. Redirects and inherited HTTP proxies are refused. A non-loopback
worker bind requires an explicitly supplied TLS certificate and private key:

```sh
python -m slab_preflight.compute_server --host 0.0.0.0 --port 8768 --token-file /private/path/worker-token --device cuda --certificate /private/path/cert.pem --private-key /private/path/key.pem
```

The worker supports only density difference, plane reduction and vector norms.
It accepts bounded float64 arrays and shape/device metadata, not file paths,
project archives or executable code. It allows one active job, a 34 MiB request
body and a 16 MiB response. Requests require bearer authentication; browser-origin
requests are refused. Request data is not written to payload files or access logs.
TLS, authentication and bounds do not make an operator trustworthy: send data
only to a worker you intend to use.

일반 데스크톱 실행에서는 서버를 열거나 외부에 접속하지 않습니다. 사용자가 직접
작업자를 시작하고 서버 계산을 실행할 때만 해당 요청의 수치 배열을 전송합니다.
원격 접속에는 인증 토큰과 인증서를 검증하는 HTTPS가 필요하며, 평문 HTTP는 IP로
지정한 로컬 루프백에만 허용합니다. 프로젝트 전체나 임의 명령은 전송하지 않습니다.

## Host verification and benchmark

The tests cover malformed Cube input, signed-field separation, exact source
hashes, scalar/spatial unit conversion, frozen atom subsets, grid mismatches,
skew/left-handed grids, reversed normals, volume conservation, real Metal
workloads and actual authenticated loopback requests. CUDA hardware execution
cannot be established on an Apple-only test host.
CUDA entry parameter widths and the actual Python↔C allocation, transfer and
launch-argument ABI are checked with a compiled native C fixture. That fixture
runs on the CPU. It does not validate PTX instruction JIT or NVIDIA hardware.

Run a reproducible benchmark against an actual imported field:

```sh
python scripts/benchmark_compute_density.py --cube examples/electronic_case/density.cube --units e/bohr^3 --repeats 3 --output work/compute-benchmark.json
```

This measures completed end-to-end results, including transfers, helper launch
and CPU parity. Compilation/probing is outside the warm samples. It reports
measured durations, device identity and errors without assuming that GPU
execution is faster for a small Cube.

The boundary benchmark exercises exactly 1,000,000 voxels and 400 sites (79,800
unordered pairs), including all copies and CPU checks:

```sh
python scripts/benchmark_compute_bounds.py --repeats 3 --output work/compute-bounds-benchmark.json
```

Those boundary inputs are explicitly labeled deterministic numerical fixtures,
not electronic-structure calculations or physical materials. Record the
resulting device identity and completed durations before making a performance claim.

Primary API/format references:

- [Apple: Performing calculations on a GPU](https://developer.apple.com/documentation/metal/performing-calculations-on-a-gpu)
- [NVIDIA CUDA Driver API](https://docs.nvidia.com/cuda/cuda-driver-api/index.html)
- [NVIDIA PTX ISA](https://docs.nvidia.com/cuda/parallel-thread-execution/index.html)
- [VMD Cube format](https://www.ks.uiuc.edu/Research/vmd/plugins/molfile/cubeplugin.html)
