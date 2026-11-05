# Downloads and installation / 다운로드·설치

This page describes the published **v0.6.0 downloads**. The **v0.7.0 source** adds
draft/viewer persistence, electronic ZIP projects and P1 preparation; see the
[current workspace guide](WORKSPACE_SAVE.md).
이 문서의 다운로드는 공개된 **v0.6.0**입니다. **v0.7.0 소스**의 개선 사항은
[새 작업 안내](WORKSPACE_SAVE.md)를 참고하세요.

[Project home](../README.md) · [Full English guide](../README.en.md) · [한국어 전체 안내](../README.ko.md)

## Windows EXE — Python included / Python 포함

For Windows 10/11 x64, download an EXE and double-click it. A launch manager opens
CalcLens in your browser. Python and the browser workspace are included; neither
Python nor Node.js needs to be installed separately. Both languages use the same
engine, and you can switch languages in the interface.

Windows 10/11 x64에서는 EXE를 받은 뒤 더블클릭하세요. Python을 따로 설치할 필요가
없습니다. 화면 파일도 포함되어 있어 Node.js는 필요하지 않습니다.
실행 관리 창과 브라우저에서 앱이 열립니다.
두 파일은 처음 열리는 언어만 다르고, 화면에서 언어를 바꿀 수 있습니다.

| Language / 언어 | Standalone EXE / 단일 EXE | Folder ZIP / 폴더 ZIP | Guide / 안내 |
| --- | --- | --- | --- |
| 한국어 | [한국어 EXE](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-0.6.0-windows-x64-ko.exe) | [한국어 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-0.6.0-windows-x64-ko-folder.zip) | [한국어 Windows 안내](../packaging/windows/README.ko.md) |
| English | [English EXE](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-0.6.0-windows-x64-en.exe) | [English folder ZIP](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-0.6.0-windows-x64-en-folder.zip) | [English Windows guide](../packaging/windows/README.en.md) |

The standalone EXE unpacks its files at startup, which can take several seconds.
For faster repeat launches, extract the entire folder ZIP and run the EXE inside
it. Keep its accompanying files together. Use the manager's **Open CalcLens**,
**Diagnostics** and **Quit** controls. Closing the manager stops the server;
closing only the browser tab leaves it running. Save your project before quitting.

단일 EXE는 시작할 때 포함된 파일을 풀기 때문에 몇 초가 걸릴 수 있습니다.
반복 실행 시간을 줄이려면 폴더 ZIP을 모두 풀고 안에 있는 EXE를 실행하세요.
함께 들어 있는 파일은 같은 폴더에 보관해야 합니다. 관리 창의 **CalcLens 열기**,
**진단 기록**, **종료**를 사용하세요. 관리 창을 닫으면 서버도 종료되며,
브라우저 탭만 닫으면 계속 실행됩니다. 종료하기 전에 작업을 저장하세요.

[Windows checksums](https://github.com/a123qsd/calclens/releases/download/v0.6.0/WINDOWS-SHA256SUMS.txt) ·
[Windows licenses and build source](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-0.6.0-windows-support.zip)

The EXEs are unsigned. Windows may show an unknown-publisher or SmartScreen
warning. Check the release owner, source and checksum before deciding whether to
run them. The [Windows guide](../packaging/windows/README.en.md) explains file checks
and the bundled license and source materials.

EXE에는 코드 서명이 없어 Windows에서 게시자를 알 수 없다는 경고가 표시될 수 있습니다.
실행 여부를 결정하기 전에 배포 계정, 소스와 체크섬을 확인하세요.
파일 확인과 동봉한 라이선스·소스 자료는 [Windows 안내](../packaging/windows/README.ko.md)에 있습니다.

## Source packages / 소스 패키지

**CalcLens v0.6.0** includes the molecular workspace, project editing, review
history, pair measurements and side-by-side structure comparison. The viewer
adds representation and graphics controls, linked comparison cameras, PNG export
and imported charge/density/orbital displays. Choose a language-specific source
ZIP and install it with the commands below.

**CalcLens v0.6.0**에는 입체 구조 작업공간, 프로젝트 편집, 검토 이력, 원자쌍 측정과
두 구조의 나란히 비교가 포함됩니다. 뷰어에 표현·그래픽 설정, 비교 시점 동기화,
PNG 저장과 외부 전하·전자밀도·오비탈 자료 표시가 추가되었습니다.
원하는 언어의 소스 ZIP을 받은 뒤 아래 명령으로 설치하세요.

Imported viewer data is kept only in the current browser session and is not
included in saved projects. CalcLens does not calculate electronic data.
보조 자료는 현재 브라우저 세션에만 보관하며 작업 저장 파일에 포함하지 않습니다.
CalcLens가 전하나 전자밀도를 계산하지는 않습니다.
See [Imported viewer data / 보조 자료 안내](VIEWER_DATA.md).

## English

Download a language-specific source package from
[CalcLens v0.6.0](https://github.com/a123qsd/calclens/releases/tag/v0.6.0):

| Asset | Initial interface and main guide |
| --- | --- |
| [calclens-0.6.0-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.6.0/calclens-0.6.0-en.zip) | English |
| [calclens-0.6.0-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.6.0/calclens-0.6.0-ko.zip) | Korean |

You can also download the guides separately as Markdown files:
[English guide](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-Guide.en.md) ·
[Korean guide](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-Guide.ko.md).
These text files explain the app; they do not contain the program.

Both packages contain the same geometry engine, examples, and English/Korean
interface switch. The main `README.md` in each ZIP is the corresponding full
language guide; `README.en.md` and `README.ko.md` are both included.

These are **source ZIPs, not standalone executables**. Install Python 3.12 or 3.13 first.
The browser assets are included, so Node.js is not required to run the app.
You need an internet connection for the initial dependency installation. Running
the local geometry checks does not require an API key or paid computation service.
The installation command examples below use Python 3.12.

### Install on macOS or Linux

Extract the ZIP and open a terminal in `calclens-0.6.0-en` (or `calclens-0.6.0-ko`
for the Korean package), the folder containing `run_app.py` and `requirements.lock`. Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Install on Windows

Extract the ZIP and open PowerShell in `calclens-0.6.0-en` (or `calclens-0.6.0-ko`
for the Korean package), the folder containing `run_app.py` and `requirements.lock`. Run:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
.venv\Scripts\python.exe run_app.py
```

These commands call the environment's Python directly; activating the environment
is optional. Open the local address printed in the terminal if the browser does
not open automatically. Stop the app with `Ctrl+C` in that terminal.

### Choose the language

The launcher reads `DEFAULT_LANGUAGE.txt` in the package. To override the default,
append `--language en` or `--language ko` to the launch command, for example:

```bash
.venv/bin/python run_app.py --language en
```

On Windows, use `.venv\Scripts\python.exe run_app.py --language en`.
You can also switch language in the running interface. Changing language does
not change the geometry calculation or its acceptance criteria.

### Choose the report language

Under **Method notes**, the report-language selector defaults to the interface language. You can select
English or Korean separately for JSON/CSV downloads; filenames end in
`_calclens_en.json`, `_calclens_ko.json`, or the corresponding `.csv` suffix.
For the CLI, pass `--language en` or `--language ko`; its default is English.

Issue explanations, assumptions, and limitations are localized. CSV headings
are localized too. JSON keys, technical codes, severity values, units, indices,
and numerical results stay consistent for comparison and automated processing.
Korean JSON retains the English source explanations alongside its Korean text.
App and CLI Korean CSV files use UTF-8 with a BOM; JSON uses UTF-8 without a BOM.

### Compare CIF files

Use **Open files** for a new workspace of up to 20 CIFs. To extend the current
workspace, choose **Add CIFs** in **Edit selected structure**. Set each file's axis
and cutoff and save the edits. Each file keeps the 2 MiB and 400-site limits.
Select a record for its structure and reports. Unsupported files retain their
explanation and blank measurements while the other checks continue.

**Compare structures** shows two selected entries side by side. Differences mean
comparison minus reference; no atom correspondence or RMSD is calculated.
**Export all CSV** includes every file regardless of the visible filters. The
comparison CSV follows the interface language; detailed report language is separate.

App and CLI reports include the original filename, exact-byte SHA-256, and
CalcLens/ASE versions. Select **Minimum periodic distance** in **Review checks**
to inspect the nearest pair even when the short-contact list is empty. See the [English guide](../README.en.md)
and [public graphite case](CASE_STUDY.md) for examples.

Use only public or shareable structures when reporting an issue. The bundled
examples are analytical test models, not experimental or relaxed structures.
See the [English guide](../README.en.md) for the input limits, result definitions,
CLI commands, and license conditions.

### Save and reopen work

**Save project** downloads a `.calclens.json` with original CIF bytes, entry IDs,
per-file settings, notes, review stamps, pair selections and view filters.
Use **Open project** to restore it without the separate original CIF files.
Reports and saved distances are recalculated from those originals. Missing or
corrupt CIF payloads and hash mismatches are rejected. JSON/CSV reports cannot be
imported as projects.

**Reviewed** records a human review; geometry warnings remain visible. A review
stamp is tied to the source hash, axis, cutoff, analysis revision and ASE version.
Changed analysis conditions require rechecking. Tabs of one running server share
the workspace, and unsaved work stays in memory. Save before stopping the server.
See the [project guide](../README.en.md#pair-measurements-and-saved-work) for details.

## 한국어

[CalcLens v0.6.0 배포 페이지](https://github.com/a123qsd/calclens/releases/tag/v0.6.0)에서
원하는 언어의 소스 ZIP을 받으세요.

| 파일 | 처음 열리는 화면과 기본 안내 |
| --- | --- |
| [calclens-0.6.0-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.6.0/calclens-0.6.0-ko.zip) | 한국어 |
| [calclens-0.6.0-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.6.0/calclens-0.6.0-en.zip) | 영어 |

안내 문서만 필요하면 Markdown 파일로 따로 받을 수 있습니다.
[한국어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-Guide.ko.md) ·
[영어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.6.0/CalcLens-Guide.en.md).
안내 파일에는 프로그램이 들어 있지 않습니다.

두 파일의 검사 엔진과 예제는 같습니다. 둘 다 한국어·영어 화면을 제공하며, ZIP 안의
`README.md`만 선택한 언어의 전체 안내로 시작합니다. `README.en.md`와 `README.ko.md`도
함께 들어 있습니다.

**독립 실행 프로그램이 아니라 소스 ZIP입니다.** Python 3.12 또는 3.13을 먼저 설치하고
아래 명령으로 필요한 패키지를 설치해야 합니다. 화면 파일은 포함되어 있어 실행에
Node.js는 필요하지 않습니다. 처음 설치할 때는 인터넷 연결이
필요합니다. 로컬 기하 검사에는 API 키나 유료 계산 서비스가 필요하지 않습니다.
아래 설치 명령 예시는 Python 3.12를 사용합니다.

### macOS·Linux에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 `calclens-0.6.0-ko` 폴더에서
터미널을 열고 실행하세요. 영어 패키지를 받았다면 폴더 이름은 `calclens-0.6.0-en`입니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Windows에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 `calclens-0.6.0-ko` 폴더에서
PowerShell을 열고 실행하세요. 영어 패키지를 받았다면 폴더 이름은 `calclens-0.6.0-en`입니다.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
.venv\Scripts\python.exe run_app.py
```

가상환경의 Python을 직접 호출하므로 가상환경 활성화 명령은 생략해도 됩니다.
브라우저가 자동으로 열리지 않으면 터미널에 표시된 로컬 주소를 여세요.
앱을 종료하려면 실행한 터미널에서 `Ctrl+C`를 누릅니다.

### 언어 선택

실행기는 ZIP 안의 `DEFAULT_LANGUAGE.txt`를 읽어 기본 언어를 정합니다.
다른 언어로 시작하려면 실행 명령 뒤에 `--language ko` 또는 `--language en`을 붙이세요.

```bash
.venv/bin/python run_app.py --language ko
```

Windows에서는 `.venv\Scripts\python.exe run_app.py --language ko`를 사용합니다.
실행한 화면에서도 언어를 바꿀 수 있습니다. 언어를 바꿔도 계산 방법과 입력 허용 기준은 같습니다.

### 결과 언어 선택

**방법과 한계**의 보고서 언어는 기본적으로 화면 언어를 따릅니다. JSON·CSV 다운로드에 사용할 언어를
한국어·영어 중 별도로 선택할 수도 있습니다. 파일명 끝에는 `_calclens_ko.json`,
`_calclens_en.json` 또는 같은 형식의 `.csv`가 붙습니다. 명령행에서는
`--language ko` 또는 `--language en`을 지정하세요. 명령행의 기본값은 영어입니다.

점검 설명·가정·한계와 CSV 열 제목은 번역합니다. JSON 키와 기술 코드, 심각도 값,
단위, 인덱스와 수치는 비교·자동 처리를 위해 유지합니다. 한국어 JSON에는 영문 원문도
함께 남깁니다. 앱과 명령행의 한국어 CSV는 BOM이 있는 UTF-8을 사용하며,
JSON은 BOM 없는 UTF-8로 저장합니다.

### 여러 CIF 비교

**파일 열기**로 최대 20개 CIF의 새 작업을 엽니다. 기존 작업에 더하려면
**선택 구조 편집**의 **CIF 추가**를 사용하세요. 파일별 축과 기준을 정한 뒤 편집 내용을
저장합니다. 파일당 2 MiB·400개 원자 제한은 같습니다. 기록 표의 행을 선택하면 해당
구조와 보고서를 확인할 수 있습니다. 지원하지 않는 파일도 빈 측정값과 이유를 남기며
다른 파일의 검사는 계속합니다.

**구조 비교**에서는 두 항목을 나란히 봅니다. 변화량은 ‘비교 − 기준’이며 원자별 대응이나
RMSD는 계산하지 않습니다. **전체 CSV**에는 화면 필터와 관계없이 모든 파일이 들어갑니다.
비교 CSV는 화면 언어를 따르고, 개별 보고서의 언어는 별도로 선택합니다.

앱과 명령행의 보고서에는 원본 파일명, 원본 바이트의 SHA-256, CalcLens·ASE 버전이
들어갑니다. 짧은 접촉이 없어도 **검토 항목**의 **최소 주기 거리**를 선택하면
가장 가까운 원자쌍을 확인할 수 있습니다.
사용 예는 [한국어 안내](../README.ko.md)와 [공개 흑연 사례](CASE_STUDY.md)를 확인하세요.

오류를 제보할 때는 공개해도 되는 구조만 사용하세요. 동봉한 예제는 기하 계산을 확인하기 위한
모델이며 실험 구조나 최적화된 구조가 아닙니다. 입력 제한, 결과 해석, 명령행 사용법과
이용 조건은 [한국어 전체 안내](../README.ko.md)에 있습니다.

### 작업 저장하고 다시 열기

**작업 저장**으로 원본 CIF 바이트, 항목 ID, 파일별 조건, 메모, 검토 이력,
원자쌍 선택과 화면 필터를 담은 `.calclens.json`을 내려받습니다.
**작업 열기**로 불러오면 별도의 원본 CIF 없이 이어갈 수 있습니다. 보고서와 저장한
거리는 포함된 원본으로 다시 계산합니다. CIF 데이터가 없거나 손상되었거나 해시가
다르면 불러오기를 거부합니다. JSON·CSV 보고서는 작업 파일로 불러올 수 없습니다.

**검토 완료**는 사람이 확인했다는 기록이며, 구조 경고는 계속 표시됩니다.
원본 해시·축·거리 기준·계산 방식·ASE 버전에 연결된 검토 기록을 남기고,
관련 조건이 바뀌면 재검토가 필요합니다. 같은 서버의 탭들은 하나의 작업을 공유하며,
저장하지 않은 작업은 메모리에만 있으므로 서버를 종료하기 전에 저장하세요.
자세한 내용은 [작업 저장 안내](../README.ko.md#원자-거리와-작업-저장)를 확인하세요.
