# CalcLens

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

This source tree is **v0.2.0**. The published ZIP links below are for **v0.1.1**;
the new comparison, report-provenance, and contact-evidence features require
the current source. No v0.2.0 release asset is linked here.

현재 소스 버전은 **v0.2.0**이며, 아래에 연결된 공개 ZIP은 **v0.1.1**입니다.
여러 파일 비교, 보고서의 원본 식별 정보, 접촉 근거 보강은 현재 소스에 포함된 기능입니다.

![CalcLens local structure inspection / 로컬 구조 검사 화면](docs/assets/calclens-overview.png)

[Short demo / 짧은 사용 영상](docs/assets/calclens-demo.webm) ·
[Public graphite case / 공개 흑연 사례](docs/CASE_STUDY.md)

## Download / 다운로드

[Latest release / 최신 배포](https://github.com/a123qsd/calclens/releases/latest)

| Language | Source ZIP for v0.1.1 | Read guide | Download guide |
| --- | --- | --- | --- |
| English | [calclens-0.1.1-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-en.zip) | [English](README.en.md) | [English .md](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.en.md) |
| 한국어 | [calclens-0.1.1-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-ko.zip) | [한국어](README.ko.md) | [한국어 .md](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.ko.md) |

Both ZIPs contain the same analysis engine and both interface languages. Each
opens in its selected language by default. **Python 3.12 and dependency installation
are required; these are source packages, not standalone executables.**
Report language follows the interface by default and can be chosen separately.
JSON keys and technical identifiers stay in standard English for compatibility;
human explanations and CSV headings are localized.
See [download and installation instructions](docs/DOWNLOADS.md).

두 ZIP의 검사 기능은 같으며, 처음 열리는 언어와 기본 안내 문서만 다릅니다.
실행 후에도 언어를 전환할 수 있습니다. **Python 3.12와 의존성 설치가 필요한 소스
패키지이며, 독립 실행 프로그램이 아닙니다.** 보고서 언어는 기본적으로 화면 언어를
따르며 별도로 선택할 수도 있습니다. 설명과 CSV 열 제목은 번역하고, JSON 키와 기술
식별자는 호환성을 위해 표준 영문을 유지합니다. [설치 안내](docs/DOWNLOADS.md#한국어)를 확인하세요.

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
