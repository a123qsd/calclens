# Third-party software and data

The repository contains the CalcLens application, its original model
fixtures, and the public graphite case described below. Dependencies are installed separately from their upstream packages;
the repository does not vendor or modify ASE, Streamlit, Plotly, or NumPy.
The project's [license](LICENSE) applies only to its original material.
It does not change any dependency's license or permission to sell that dependency.

| Component | Role | Upstream license and source |
| --- | --- | --- |
| ASE | CIF token parsing, cells, periodic geometry | [LGPL-2.1-or-later](https://gitlab.com/ase/ase/-/blob/master/LICENSE), [source](https://gitlab.com/ase/ase) |
| NumPy | Array operations and linear algebra | [BSD-3-Clause](https://numpy.org/doc/stable/license.html), [source](https://github.com/numpy/numpy) |
| Streamlit | Local web interface | [Apache-2.0](https://github.com/streamlit/streamlit/blob/develop/LICENSE), [source](https://github.com/streamlit/streamlit) |
| Plotly.py | Interactive structure plot | [MIT](https://github.com/plotly/plotly.py/blob/main/LICENSE.txt), [source](https://github.com/plotly/plotly.py) |
| pytest | Test runner; development only | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE), [source](https://github.com/pytest-dev/pytest) |

The initial verification environment uses ASE 3.29.0, NumPy 2.5.4,
Streamlit 1.66.1, Plotly 6.9.0, and pytest 9.2.0 on Python 3.12.16.
The exact installed versions and transitive dependencies are recorded in
`requirements.lock`. Their own distributions contain their license notices.
This table describes direct dependencies, not every transitive package or
license included in a Python wheel. If you redistribute an installed environment,
a container, a bundled executable, or dependency source, retain all applicable
notices and meet that distribution's source and license obligations.

## Windows executable distribution

The Windows executables bundle CPython and the runtime libraries. Each executable
contains their license and notice files under `third_party/` in its extracted
runtime directory. The accompanying `CalcLens-0.3.0-windows-support.zip` provides
the same notices, a dependency/version manifest, the exact unmodified ASE source
archive with its upstream SHA-256, and the CalcLens source used for the Windows
build. Build-tool notices are identified separately from runtime dependencies.
NumPy/SciPy wheel notices also cover native libraries shipped in those wheels.

The support archive's source includes locked build requirements, the PyInstaller
specification, and English/Korean rebuild instructions. Those instructions allow
rebuilding the application with a modified ASE installation. The application
license permits modifications and debugging needed to exercise ASE's LGPL rights.
The Windows packaging commit is recorded by `--build-info` and in the support
archive manifest; it may be newer than the original v0.3.0 source-ZIP tag.

## ASE

ASE remains available under LGPL-2.1-or-later. CalcLens imports it as a
separately installed Python library and does not copy ASE implementation code
into its own modules. You can inspect, replace, and modify the ASE installation.
The custom application license preserves the rights required for modifying an
LGPL dependency and debugging those modifications.

ASE's [license guidance](https://docs.ase-lib.org/development/licenseinfo.html)
discusses use with separately licensed Python modules. The upstream source and
license remain available from the links above. The LGPL terms govern ASE;
this explanation is not a substitute for them.

## Comparison with pymatgen

[pymatgen](https://pymatgen.org/) is a broader materials-analysis toolkit and is
[MIT licensed](https://github.com/materialsproject/pymatgen/blob/master/LICENSE).
It is a comparison point, not a dependency of this project. CalcLens uses
ASE for the narrow CIF and periodic-geometry task and keeps its validation rules
visible in a small core module. Neither project's developers endorse CalcLens.

## Example data

The top-level CIF examples are analytical models created for this project and released
with the repository under [LICENSE](LICENSE). Parameters, construction rules, and artificial defects are
recorded in [docs/PROVENANCE.md](docs/PROVENANCE.md). Material names identify the
intended model; they do not establish experimental provenance or validation.

`examples/public_case/` also includes [COD 9011577](https://www.crystallography.net/cod/9011577.html),
revision 291877, and two documented derivatives. The source is Trucano and Chen,
“Structure of graphite by neutron diffraction,” *Nature* 258 (1975), 136–137,
DOI [10.1038/258136a0](https://doi.org/10.1038/258136a0).
[COD distributes its data under CC0](https://www.crystallography.net/cod/).
That data retains its CC0 status; the CalcLens application license does not
restrict it. The source hash, preparation, occupancy assumption, and independent
comparison are recorded in [the case study](docs/CASE_STUDY.md). The constructed
isolated sheet is a geometric derivative, not an experimentally measured or relaxed slab.
