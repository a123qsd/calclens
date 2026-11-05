# Actual H2O electronic calculation

These files come from an actual PySCF 2.12.0 molecular RHF/STO-3G calculation.
The fixed water geometry is an original illustrative model. It is not an
experimental structure, optimized geometry or periodic solid calculation.

Load `water.cif`, then `charges_mulliken.json` and `charges_lowdin.json` to compare
two charge partitions of the same converged density. The atom order is O/H/H.
The 12 Å orthogonal P1 cell serves only as a display container.

| File | Use |
| --- | --- |
| `source/water.xyz` | Original, untranslated fixed molecular input in Å |
| `water.cif` | Same atom order, translated by (+6,+6,+6) Å for display |
| `charges_mulliken.json`, `charges_lowdin.json` | Importable partial-charge datasets bound to the exact CIF hash |
| `charges_*.csv` | Readable copies of the charge results |
| `density.cube` | Total electron density; select density and `e/bohr^3` |
| `homo.cube` | Occupied MO 5; select orbital and `bohr^-3/2` |
| `scf.log`, `calculation.json` | Convergence trace, program/settings, energy and limitations |
| `wavefunction.json` | AO/MO matrices and integrals for NumPy consistency checks |
| `independent_check.json` | Energy/charge reconstruction, ASE Cube readback and separate quadrature |
| `reference_sections.png` | Independent ASE-read density/orbital section visualization |
| `manifest.json` | SHA-256 hashes of scientific artifacts and the preparation script |
| `requirements.txt` | Optional regeneration dependencies; not CalcLens runtime requirements |

For either Cube, 0.05 is an illustrative display isovalue. Orbital colors show
wavefunction signs. The 30³ density grid is too coarse for quantitative electron
integration: it gives 9.1780 electrons, while a separate atom-centered quadrature
gives 9.9999999895. Neither charge dataset represents an oxidation state.

See [the full case guide](../../docs/ELECTRONIC_CASE.md) for results, units,
independent-check scope and commands to reproduce or verify this case.
