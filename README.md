# CalcLens

The source tree is preparing **v0.5.0**: project file editing, review provenance,
chosen-pair measurement, side-by-side comparison, a Windows launch manager,
and a React/TypeScript workspace with an offline 3Dmol.js sphere-and-stick viewer.
Published download links below remain **v0.3.0** until the next release is built.

현재 소스는 **v0.5.0** 업데이트입니다. 프로젝트 파일 편집, 검토 이력, 원자쌍 측정,
두 구조 비교와 Windows 실행 관리 창에 더해 React/TypeScript 화면과 오프라인
3Dmol.js 구·막대 뷰어를 추가했습니다. 아래 다운로드는 새 버전이
배포되기 전까지 **v0.3.0**을 가리킵니다.

**Windows x64: no Python installation needed / Python 설치 없이 실행**

[한국어 EXE](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-0.3.0-windows-x64-ko.exe) ·
[English EXE](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-0.3.0-windows-x64-en.exe) ·
[실행 안내](packaging/windows/README.ko.md) · [Windows guide](packaging/windows/README.en.md)

Double-click the EXE to open CalcLens in your browser. Keep its console window
open while using the app. EXE를 더블클릭하면 브라우저에서 열립니다.
사용하는 동안 함께 열린 실행 창을 유지하세요.

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

**v0.3.0** includes portable review projects, preserved per-file comparison
settings and selection, session caching, and review filters. Reports retain source
identity and contact evidence even when detail tables are truncated.

**v0.3.0**에는 원본 CIF를 담는 작업 저장·불러오기, 파일별 비교 조건·선택 유지,
세션 캐시와 검토 필터가 포함됩니다. 보고서에는 원본 식별 정보와 상세 표에서
생략되어도 보존되는 접촉 근거를 남깁니다.

![CalcLens local structure inspection / 로컬 구조 검사 화면](docs/assets/calclens-overview.png)

[Short demo / 짧은 사용 영상](docs/assets/calclens-demo.webm) ·
[Public graphite case / 공개 흑연 사례](docs/CASE_STUDY.md)

## Download / 다운로드

[Latest release / 최신 배포](https://github.com/a123qsd/calclens/releases/latest)

| Language | Source ZIP for v0.3.0 | Read guide | Download guide |
| --- | --- | --- | --- |
| English | [calclens-0.3.0-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-en.zip) | [English](README.en.md) | [English .md](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.en.md) |
| 한국어 | [calclens-0.3.0-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-ko.zip) | [한국어](README.ko.md) | [한국어 .md](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.ko.md) |

Both ZIPs contain the same analysis engine and both interface languages. Each
opens in its selected language by default. **Python 3.12 or 3.13 and dependency
installation are required; these are source packages, not standalone executables.**
The installation examples in the guides use Python 3.12.
Report language follows the interface by default and can be chosen separately.
JSON keys and technical identifiers stay in standard English for compatibility;
human explanations and CSV headings are localized.
See [download and installation instructions](docs/DOWNLOADS.md).

두 ZIP의 검사 기능은 같으며, 처음 열리는 언어와 기본 안내 문서만 다릅니다.
실행 후에도 언어를 전환할 수 있습니다. **Python 3.12 또는 3.13과 의존성 설치가 필요한
소스 패키지이며, 독립 실행 프로그램이 아닙니다.** 안내 문서의 설치 명령 예시는
Python 3.12를 사용합니다. 보고서 언어는 기본적으로 화면 언어를
따르며 별도로 선택할 수도 있습니다. 설명과 CSV 열 제목은 번역하고, JSON 키와 기술
식별자는 호환성을 위해 표준 영문을 유지합니다. [설치 안내](docs/DOWNLOADS.md#한국어)를 확인하세요.

## Save and continue work / 작업 저장하고 이어가기

Both v0.3.0 packages include comparison filters, persistent per-file settings and
selection during edits, and session caching by file content, axis, and cutoff.
Use **Save project** to download a `.calclens.json` containing the original CIFs
and review state, then **Open saved work** → **Open project** to continue later.
See the [English guide](README.en.md#save-and-continue-a-comparison) for details.

두 v0.3.0 패키지에는 비교 필터, 편집 중 파일별 조건·선택 유지, 파일 내용·축·기준별
세션 캐시가 포함됩니다. **작업 저장**으로 원본 CIF와 검토 상태를 `.calclens.json`에
저장하고, **저장한 작업 열기** → **작업 불러오기**로 이어서 검토할 수 있습니다.
자세한 내용은 [한국어 안내](README.ko.md#비교-작업-저장하고-이어가기)를 확인하세요.

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

Each file must contain one explicit, fully occupied P1 CIF structure, up to 400 sites
and 2 MiB. Comparing files does not combine their structures. The chosen normal
axis must be perpendicular to the other two cell vectors. Gaussian/ORCA logs
and calculation execution are outside this release.

파일마다 원자 위치가 명시된 완전 점유 P1 CIF 구조 1개를 받으며, 파일당 최대 400개
원자·2 MiB까지 지원합니다. 비교할 파일들은 각각 검사합니다.
선택한 수직 방향은 나머지 두 셀 벡터에 수직이어야 합니다.
Gaussian·ORCA 로그 분석과 계산 실행은 지원하지 않습니다.

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
