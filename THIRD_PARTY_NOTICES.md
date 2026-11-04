# Third-party software and data

The repository contains the CalcLens application and its original model
fixtures. Dependencies are installed separately from their upstream packages;
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

The CIF examples are analytical models created for this project and released
with the repository under [LICENSE](LICENSE). No experimental CIF dataset is
redistributed. Parameters, construction rules, and artificial defects are
recorded in [docs/PROVENANCE.md](docs/PROVENANCE.md). Material names identify the
intended model; they do not establish experimental provenance or validation.
