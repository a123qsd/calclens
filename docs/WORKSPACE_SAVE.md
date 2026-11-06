# Continue a research workspace / 연구 작업 이어가기

This guide describes the default browser workspace in CalcLens 0.8.0.

## Find the current structure

The selected filename is the main heading. Use the file strip to switch CIFs and
the header actions to open files or save the project. Horizontal navigation opens
Overview, Compare, Review and Methods. **Try sample** remains available as a
smaller action. In Overview, the large viewer sits beside compact measurements
and review controls.

선택한 파일명이 화면 제목에 표시됩니다. 파일 선택 줄에서 CIF를 바꾸고, 상단의
파일 열기·작업 저장 버튼으로 작업을 다룹니다. 가로 메뉴에서 개요·비교·검토·방법
화면으로 이동할 수 있습니다. **예제 불러오기**는 작은 보조 버튼으로 제공합니다.
개요 화면에서는 넓은 뷰어 옆에서 수치와 검토 항목을 확인합니다.

## Drafts and saved work

Notes and analysis conditions have a draft for each file. Switching files or
opening Compare, Review or Methods preserves the draft. **Apply changes** updates
the analysis conditions; editing a draft alone does not change a report or mark
a structure as reviewed. A server refresh updates untouched fields and preserves
locally edited fields. A conflicting edit requires review before retrying.

**Save project** downloads a `.calclens.zip` containing original CIF bytes,
applied conditions, notes, review stamps, pair selections, unapplied drafts,
electronic source files, viewer settings and comparison choices. The ZIP contains
one `project.json`; no external file paths are needed. **Open project** also reads
older schema-1 and schema-2 `.calclens.json` files. Older CalcLens versions cannot
read new schema-3 projects.

The browser validates the saved electronic files against the recalculated CIF
reports before replacing the active workspace. Imported charge JSON is checked
against the original CIF hash, atom indices and elements. Cube files are checked
against the atom order, coordinates, field kind and units. Stored render meshes
and numeric geometry reports are never treated as authoritative results.

Drafts and viewer changes are local to a browser tab until saved. There is no
automatic disk backup. Save before closing the tab or server. Browser reload
warnings help prevent accidental loss but do not themselves store the work.

메모와 검사 조건의 초안은 파일마다 따로 유지됩니다. 비교·검토·방법 화면으로
이동하거나 다른 CIF를 선택해도 초안이 남습니다. **변경 적용**을 눌러야 분석에
반영되며, 초안을 작성하는 것만으로 결과나 검토 완료 상태가 바뀌지는 않습니다.

**작업 저장**은 원본 CIF, 적용한 조건, 검토 이력, 원자쌍 선택, 적용 전 초안,
전하 JSON·Cube 원본, 뷰어 설정과 비교 선택을 `.calclens.zip`에 담습니다.
**작업 열기**는 이전 `.calclens.json`도 읽습니다. 새 작업 파일은 이전 버전에서
열 수 없습니다. 파일을 열 때 원본으로 다시 계산하고 전자 자료의 연결을 확인합니다.
저장하기 전의 초안과 화면 설정은 브라우저 탭에만 있으므로 종료 전에 저장하세요.

## Electronic datasets and comparable colors

One CIF can have several named charge and volume datasets. An import adds a
dataset instead of replacing one of the same kind. Every dataset has a distinct
identifier. Choose a charge dataset after selecting its quantity in the viewer;
choose a volume dataset in **Electronic surface**. The overview and each side of
Compare retain independent selections, so the same CIF can appear on both sides
with different calculations.

Comparison offers automatic scales per dataset, a shared symmetric range, and a
manual negative minimum/positive maximum. A common range applies only when both
viewers display the same quantity. Missing values stay gray. Oxidation states are
dimensionless and are never silently compared with charges in e. Matching scales
do not make different partitioning methods equivalent; inspect each dataset's
method and source.

Representation, colors, repetition, projection, camera rotation/zoom, selected
datasets, applied isovalue and opacity are saved. Transient fullscreen and image
export settings are not stored. A volume occupies its supplied grid and is not
replicated with repeated atom images.

하나의 CIF에 여러 전하·전자 표면 자료를 연결하고 각 뷰어에서 따로 고를 수 있습니다.
같은 구조를 비교 화면 양쪽에 두고 서로 다른 계산 결과를 선택해 보세요.
전하 색상은 자료별 자동 범위, 공통 범위, 직접 지정 중에서 고릅니다. 공통 범위는
양쪽이 같은 물리량을 표시할 때 적용됩니다. 값이 없는 원자는 회색으로 남습니다.

## P1 preparation

Open **Prepare a P1 structure** and preview the conversion. CalcLens checks the
space-group declarations, symmetry operations, occupancy, cell and disorder
metadata before expansion. The preview shows asymmetric/expanded site counts,
the original and prepared cells, and the operations performed. **Apply prepared
P1 structure** replaces the working CIF and retains the original bytes, hashes
and preparation history in the project.

Preparation supports fully occupied, ordered structures in the validated
standard setting. Ambiguous or conflicting symmetry declarations, partial or
unknown occupancy, disorder, unsupported geometry and structures exceeding 400
expanded sites are rejected. It does not choose a layer, add vacuum, relax atoms
or establish stability. The core analysis still accepts only explicit P1 CIFs.

**P1 구조 준비**에서 원본의 공간군·점유율·무질서 여부를 확인하고 대칭 전개 결과를
미리 볼 수 있습니다. 원자 수와 셀을 확인한 뒤 **준비된 P1 구조 적용**을 누르면
원본과 변환 이력을 보관한 채 준비된 구조를 분석합니다. 층 선택·진공 추가·구조
최적화는 수행하지 않습니다. 부분 점유와 무질서 구조는 지원하지 않습니다.

## File limits and installation

The existing 20 CIFs, 2 MiB per CIF and 400-site analysis limits are unchanged.
Each charge JSON is at most 1 MiB; each Cube is at most 32 MiB and 1,000,000
points. A CIF can have at most 16 electronic datasets, totaling at most 64 MiB
of raw text. The project workspace extension is capped at 96 MiB; the full JSON
and compressed archive are each capped at 128 MiB. A compressed file's small
size does not bypass the uncompressed limit.

The default installation needs the geometry engine and browser workspace.
Streamlit and Plotly are optional: install `calclens[legacy-ui]` (or, from this
checkout, `python -m pip install '.[legacy-ui]'`) before using `--legacy-ui`.
`requirements.lock` pins the default environment plus development tools;
`requirements-legacy.lock` additionally pins the legacy interface.
Windows builds default to the workspace; `--include-legacy-ui` produces a
separately named legacy variant. The 0.8.0 Windows release supplies the default
bundles; previously published legacy builds remain on the
[v0.7.0 resources page](https://github.com/a123qsd/calclens/releases/tag/v0.7.0-resources).
Binary size and startup time require a native
build measurement; removing dependencies alone does not establish those results.

For a real calculation with reproducible inputs, see the
[H₂O electronic-data case](ELECTRONIC_CASE.md).
