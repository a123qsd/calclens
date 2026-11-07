# Third-party software and data

The repository contains the CalcLens application, its original model
fixtures, and the public graphite case described below. Dependencies are installed separately from their upstream packages;
the repository does not vendor or modify ASE, Streamlit, Plotly, or NumPy.
The project's [license](LICENSE) applies only to its original material.
It does not change any dependency's license or permission to sell that dependency.

| Component | Role | Upstream license and source |
| --- | --- | --- |
| PySide6 Essentials / Shiboken6 and Qt 6.12 | Native desktop widgets, rendering and file dialogs | [Qt for Python licensing and source](https://doc.qt.io/qtforpython-6/licenses.html), [PySide source](https://code.qt.io/cgit/pyside/pyside-setup.git/), [Qt source archives](https://download.qt.io/archive/qt/6.12/) · the exact wheel and included libraries carry their own notices |
| Pillow | Image handling dependency and packaging artwork | [License and source](https://github.com/python-pillow/Pillow) |
| ASE | CIF token parsing, cells, periodic geometry | [LGPL-2.1-or-later](https://gitlab.com/ase/ase/-/blob/master/LICENSE), [source](https://gitlab.com/ase/ase) |
| NumPy | Array operations and linear algebra | [BSD-3-Clause](https://numpy.org/doc/stable/license.html), [source](https://github.com/numpy/numpy) |
| Streamlit | Optional legacy web interface | [Apache-2.0](https://github.com/streamlit/streamlit/blob/develop/LICENSE), [source](https://github.com/streamlit/streamlit) |
| Plotly.py | Optional legacy structure plot | [MIT](https://github.com/plotly/plotly.py/blob/main/LICENSE.txt), [source](https://github.com/plotly/plotly.py) |
| React / ReactDOM | Workspace interface | [MIT](https://github.com/facebook/react/blob/main/LICENSE), [source](https://github.com/facebook/react) |
| 3Dmol.js | Shaded molecular viewer | [BSD-3-Clause and incorporated notices](https://github.com/3Dmol/3Dmol.js/blob/master/LICENSE), [source](https://github.com/3Dmol/3Dmol.js) |
| pytest | Test runner; development only | [MIT](https://github.com/pytest-dev/pytest/blob/main/LICENSE), [source](https://github.com/pytest-dev/pytest) |

The initial verification environment uses ASE 3.29.0, NumPy 2.5.4,
Streamlit 1.66.1, Plotly 6.9.0, and pytest 9.2.0 on Python 3.12.16.
The exact installed versions and transitive dependencies are recorded in
`requirements.lock` for the default environment and `requirements-legacy.lock`
for the optional previous interface. Their own distributions contain their license notices.
This table describes direct dependencies, not every transitive package or
license included in a Python wheel. If you redistribute an installed environment,
a container, a bundled executable, or dependency source, retain all applicable
notices and meet that distribution's source and license obligations.

The browser interface includes compiled React, ReactDOM, scheduler and 3Dmol.js
code. Its complete retained notices, including 3Dmol's incorporated libraries,
are in `frontend/public/THIRD_PARTY_LICENSES.txt` and the packaged
`slab_preflight/web_assets/THIRD_PARTY_LICENSES.txt`. The locked frontend sources
and build tooling are recorded in `frontend/package-lock.json`. Node.js is needed
only to rebuild these assets; running CalcLens does not fetch scripts from a CDN.

## Windows executable distribution

The Windows executables bundle CPython and the runtime libraries. Each executable
contains their license and notice files under `third_party/` in its extracted
runtime directory. The accompanying versioned `CalcLens-<version>-windows-support.zip` provides
the same notices, a dependency/version manifest, the exact unmodified ASE source
archive with its upstream SHA-256, and the CalcLens source used for the Windows
build. Build-tool notices are identified separately from runtime dependencies.
NumPy/SciPy wheel notices also cover native libraries shipped in those wheels.
From the 0.7.0 source, default builds exclude Streamlit and Plotly. The optional
`-legacy` executable and support ZIP carry their own dependency inventory.

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

`examples/electronic_case/` contains an original isolated-water calculation made
for this project with the optional PySCF tool. The input, numerical outputs,
reproduction requirements and checks are documented in
[the electronic case](docs/ELECTRONIC_CASE.md). PySCF is not bundled with CalcLens
and is not an application runtime dependency.

## Crystallographic reference data

The Hall-symbol lookup in `src/slab_preflight/preparation.py` was derived from
the [spglib space-group table](https://github.com/spglib/spglib/blob/2d0b73cc3b556282e35f9ae51de01268f5d88e5a/database/spg.csv).
The module records the source hash, retrieval date and matching method.
No spglib implementation or runtime dependency is included. Upstream spglib
provides its [BSD-3-Clause notice](https://github.com/spglib/spglib/blob/2d0b73cc3b556282e35f9ae51de01268f5d88e5a/COPYING).
