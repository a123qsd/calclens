# CalcLens

**CalcLens Desktop 0.9.1** opens a native Qt desktop application. CIF inspection, 3D rotation, comparison, project recovery and research tools run inside the application. The desktop can compute density differences and planar averages locally or with an explicitly selected worker. [Desktop guide / 데스크톱 사용 안내](docs/DESKTOP.md)

**CalcLens 데스크톱 0.9.1**은 앱 안에서 구조를 열고 검사하는 네이티브 프로그램입니다. 실제 H₂ 밀도 차이와 h-BN 진공 수렴 예제가 포함되어 있습니다. 두 운영체제 모두 앱 안에서 한국어와 영어를 선택할 수 있습니다.

Windows용 ZIP은 한 폴더에 모두 푼 뒤 `runtime` 옆의 `CalcLens.exe`를 실행하세요. 폴더 전체를 함께 보관해야 합니다. H₂ 밀도 차이는 계산 당시의 축·법선·원본으로 다시 열립니다. 상단 **설정**에서 계산 장치, 테마, 화면 그래픽 품질과 PNG 출력을 바꿀 수 있습니다.

Extract the whole Windows ZIP once and start `CalcLens.exe` beside its `runtime` folder. Keep the extracted folder together. Saved density calculations retain their original axis when the structure axis changes, and exports check the active dataset identity. [Native desktop guide](docs/DESKTOP.md) · [Desktop and web graphics](docs/native-graphics.md) · [Pre-release review record / 출시 전 검토 기록](docs/NATIVE_REVIEW.md)

[Windows x64 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip) · [Apple Silicon Mac DMG](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-macOS-Apple-Silicon.dmg) · [전체 배포 파일](https://github.com/a123qsd/calclens/releases/tag/v0.9.1)

Created, led and maintained by [a123qsd](https://github.com/a123qsd).
[Project origin and responsibilities](AUTHORS.md) · [Citation](CITATION.cff)

창안·기획·개발 총괄 및 유지관리: [a123qsd](https://github.com/a123qsd).
[프로젝트 출처와 역할](AUTHORS.md) · [인용 정보](CITATION.cff)

Externally supplied charge JSON and density/orbital Cube files can be displayed
for a matching CIF. CalcLens does not calculate those quantities. Imported viewer
data, per-file drafts and viewer settings are included in portable ZIP projects.
Multiple datasets and shared charge scales support comparisons on the same CIF.
See [Imported viewer data](docs/VIEWER_DATA.md) for formats and limits.

CIF와 일치하는 전하 JSON 및 전자밀도·오비탈 Cube 자료를 불러와 표시할 수 있습니다.
CalcLens가 이 값을 계산하지는 않습니다. 보조 자료, 파일별 초안과 뷰어 설정은 작업 ZIP에 함께 저장합니다.
같은 CIF에 여러 자료를 연결하고 공통 전하 색상 범위로 비교할 수 있습니다. 형식과 제한은
[보조 자료 안내](docs/VIEWER_DATA.md)를 참고하세요.

[0.9.1 release notes / 변경 사항](docs/RELEASE-0.9.1.md) ·
[Workspace guide / 작업 안내](docs/WORKSPACE_SAVE.md) · [Real electronic-data case / 실제 계산 사례](docs/ELECTRONIC_CASE.md)

**Inspect a 2D material CIF before setting up a calculation.**

CalcLens is a local tool for visualizing atomic structures, finding short periodic
contacts and duplicate sites, and measuring the span of nuclear positions and
the largest empty interval along a selected axis. It includes English and Korean
interfaces, guides, and report explanations, plus analytical examples and
JSON/CSV exports and comparisons of up to 20 CIF files with settings for each file.

**2차원 물질 계산을 시작하기 전, CIF 구조의 기하 정보를 확인하는 도구입니다.**
원자 구조를 그려 보고 주기 경계를 넘는 짧은 거리, 중복 원자, 원자핵 기준 두께와
빈 간격을 확인합니다. 화면·사용 안내·결과 설명을 한국어와 영어로 제공하며,
예제와 JSON·CSV 내보내기, 파일마다 조건을 정하는 최대 20개 CIF 비교를 지원합니다.

![CalcLens molecular workspace / 입체 구조 작업공간](docs/assets/calclens-native-review-ko.png)

[Earlier Streamlit demo / 이전 Streamlit 화면 영상](docs/assets/calclens-demo.webm) ·
[Public graphite case / 공개 흑연 사례](docs/CASE_STUDY.md)

## Download / 다운로드

On Windows, extract the complete ZIP into a new folder and open `CalcLens.exe` beside its `runtime` folder. On Apple Silicon, open the DMG and drag CalcLens into Applications. Both packages include Python and Qt.

Windows ZIP은 전체를 새 폴더에 풀어야 합니다. Apple Silicon Mac에서는 DMG를 열고 CalcLens를 응용 프로그램 폴더로 옮기세요. 로컬 작업은 인터넷 연결 없이 실행할 수 있습니다.

[Windows x64 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip) · [Apple Silicon Mac DMG](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-macOS-Apple-Silicon.dmg) · [전체 배포 파일](https://github.com/a123qsd/calclens/releases/tag/v0.9.1)

[Source ZIP / 소스 ZIP](https://github.com/a123qsd/calclens/archive/refs/tags/v0.9.1.zip) · [SHA-256 checksums / 파일 검증](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt) · [Installation guide / 설치 안내](docs/DOWNLOADS.md)

## Save and continue work / 작업 저장하고 이어가기

Use **Save project** to write a `.calclens.zip` containing the original CIFs,
per-file settings, notes, review history, pair selections, drafts, electronic files
and viewer state. Older `.calclens.json` projects remain readable. Use
**Open project** to continue later; measurements are recalculated from the originals.
The native desktop writes a per-session recovery copy while you edit.
See the [English guide](README.en.md#pair-measurements-and-saved-work) for details.

**작업 저장**으로 원본 CIF, 파일별 조건, 메모, 검토 이력과 원자쌍 선택을
전자 자료·초안·뷰어 설정과 함께 `.calclens.zip`에 저장합니다.
**작업 열기**에서는 이전 `.calclens.json`도 읽을 수 있습니다.
측정값은 원본에서 다시 계산합니다. 편집 중에는 자동 복구본도 기록합니다.
자세한 내용은 [한국어 안내](README.ko.md#원자-거리와-작업-저장)를 확인하세요.

## What it checks / 검사 범위

- Interactive atoms and cell, with selected contacts and periodic images highlighted
- Minimum periodic distances, overlapping sites, and configurable short-contact screening
- A nearest-pair view that works even when no distance warning is present
- Nuclei-span thickness and largest cyclic gap along a, b, or c
- Up to 20 independent CIF checks, per-file axis/cutoff settings, and a comparison CSV
- JSON/CSV reports with the original filename, SHA-256, CalcLens and ASE versions

원자·셀 시각화, 주기 거리와 겹침 검사, a·b·c 중 선택한 방향의 원자핵 기준
두께·간격 측정을 지원합니다. 경고가 없어도 가장 가까운 원자쌍을 열어 볼 수 있습니다.
비교 표의 행을 선택하면 해당 파일의 상세 결과를 확인하고 JSON·CSV로 내보낼 수 있습니다.

Direct analysis requires one explicit, fully occupied P1 CIF structure, up to 400 sites
and 2 MiB. Comparing files does not combine their structures. The chosen normal
axis must be perpendicular to the other two cell vectors. Gaussian output review
is available in the research tools; ORCA log analysis and running Gaussian/ORCA
calculations are outside this release. Density differences and planar averages
operate on supplied grids, without solving for an electronic structure.
The separate [P1 preparation step](docs/WORKSPACE_SAVE.md#p1-preparation) can expand
supported fully occupied, ordered non-P1 sources after a preview.

직접 분석에는 원자 위치가 명시된 완전 점유 P1 CIF 구조 1개가 필요하며, 파일당 최대 400개
원자·2 MiB까지 지원합니다. 비교할 파일들은 각각 검사합니다.
선택한 수직 방향은 나머지 두 셀 벡터에 수직이어야 합니다.
연구 도구에서 Gaussian 출력을 검토할 수 있습니다. ORCA 로그 분석과 Gaussian·ORCA
계산 실행은 지원하지 않습니다. 밀도 차이와 평면 평균은 제공된 격자에서 계산하며,
전자구조를 새로 계산하지 않습니다.
지원 가능한 완전 점유·무질서 없는 비P1 원본은 별도의 **P1 구조 준비**에서
대칭 전개 결과를 확인한 뒤 적용할 수 있습니다.

> Geometry checks do not establish material stability or calculation accuracy.
> The reported gap uses nuclear positions; vacuum sufficiency requires separate
> convergence tests for the intended calculation.
>
> 기하 검사만으로 물질의 안정성이나 계산 정확성을 보장하지 않습니다.
> 간격은 원자핵 위치로 측정하며, 진공이 충분한지는 실제 계산에서 수렴 검증해야 합니다.

## Details / 자세한 내용

[Methods and limits](docs/METHODS.md) · [Example provenance](docs/PROVENANCE.md) ·
[Public graphite case](docs/CASE_STUDY.md) ·
[Validation record](docs/VALIDATION.md) · [Development](docs/DEVELOPMENT.md) ·
[Dependency notices](THIRD_PARTY_NOTICES.md)

Personal, educational, academic, and internal business use is free. Selling the
software or charging for its use, access, or hosted functionality requires prior
written permission. This is **source-available**, not OSI-approved open source.
The English [LICENSE](LICENSE) governs; dependencies retain their own licenses.

개인·교육·학술 연구·사업체 내부 이용은 무료입니다. 프로그램 판매, 사용·접근 요금,
기능을 제공하는 유료 서비스는 사전 서면 허락이 필요합니다. **소스 공개 소프트웨어**이며
OSI 기준의 오픈소스가 아닙니다. 영문 [LICENSE](LICENSE)가 적용되며, 외부 라이브러리는
각각의 라이선스를 따릅니다.
