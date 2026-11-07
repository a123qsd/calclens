# Frozen H₂ density difference / 동결 H₂ 전자 밀도 차분

This is an illustrative H₂ geometry with **three actual local PySCF 2.12.0
UHF/STO-3G calculations**. H₂ has a fixed 0.74 Å separation. AB is a neutral
singlet; A and B are neutral H doublets at their unchanged dimer positions.
Both fragment calculations retain the full dimer basis through a ghost-H center.
The basis, grid, origin and voxel vectors are common to all three calculations.

| State | Electrons / spin | SCF energy (hartree) | SCF converged |
| --- | --- | --- | --- |
| AB | 2 / singlet | -1.116759307395 | True |
| A | 1 / doublet | -0.470989456352 | True |
| B | 1 / doublet | -0.470989456352 | True |

Open `h2.cif`, then use `ab.cube`, `a.cube` and `b.cube` as **total density**
in `e/bohr^3`. Fragment indices in AB are A `[1]` and B `[2]` (one-based).
Select the z grid axis for the supplied reference profile. Copy the exact common
method and reference conditions from `case.json` when recomputing AB−A−B.

`ab.log`, `a.log` and `b.log` contain the actual SCF iterations. `inputs.json`
records all real/ghost centers and settings. `case.json` records source hashes,
spin diagnostics, overlap electron counts, stationary Fock/density checks and an
independent reconstruction of the UHF energy. `reference-profile.csv` comes from
an independent ASE Cube readback and direct CPU arithmetic.

The 49³ finite grid integrates to AB
2.0000000637 e, A
1.0000000457 e and B
1.0000000457 e. The integrated difference is
-2.76652e-08 e. These are finite-grid
rectangle sums, without renormalization or a convergence claim. The quantum
density matrices separately have exactly 2, 1 and 1 electrons within the recorded
overlap-trace tolerance.

Positive difference density denotes electron accumulation relative to the two
frozen atom references. It is not an assigned atomic charge or a quantitatively
converged charge-transfer measurement. STO-3G is deliberately small. These SCF
energies do not establish correlated accuracy or basis/grid convergence.
The 12 Å P1 CIF is a display container: the electronic jobs are isolated,
nonperiodic and unrelaxed.

실제 로컬 UHF 계산 세 번으로 만든 예제입니다. 원자 간격 0.74 Å를 고정하고,
AB는 중성 단일항, A·B는 각각 중성 H 이중항으로 계산했습니다. 조각에서도
고스트 중심으로 전체 H₂ 기저를 유지했습니다. 세 Cube는 같은 격자를 사용합니다.
차분의 양수는 두 원자 기준에 비해 전자가 늘어난 영역이며 원자별 전하를 뜻하지
않습니다. 작은 기저·유한 격자의 설명용 예제이므로 정량적 전하 이동이나 수렴을
주장하지 않습니다. CIF의 P1 셀은 표시용이고 전자 계산에는 주기 경계가 없습니다.

Regenerate using an isolated environment with PySCF 2.12.0, NumPy and ASE:

```sh
python scripts/prepare_density_case.py --output-dir examples/research_cases/h2_density
```

Check the bundled data with the normal CalcLens environment, without PySCF:

```sh
python scripts/prepare_density_case.py --check --output-dir examples/research_cases/h2_density
```

References: [PySCF ghost/basis input](https://pyscf.org/user/gto.html),
[PySCF unrestricted Hartree–Fock](https://pyscf.org/user/scf.html),
[Cube format](https://www.ks.uiuc.edu/Research/vmd/plugins/molfile/cubeplugin.html).
