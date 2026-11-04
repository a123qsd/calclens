# Downloads and installation / 다운로드·설치

[Project home](../README.md) · [Full English guide](../README.en.md) · [한국어 전체 안내](../README.ko.md)

**CalcLens v0.3.0** includes portable review projects, per-file comparison settings
and filters, session caching, source identity in reports, and contact evidence
preserved outside detail tables. Choose a language-specific source ZIP and install
it with the commands below.

**CalcLens v0.3.0**에는 작업 저장·불러오기, 파일별 비교 조건과 필터, 세션 캐시,
보고서의 원본 식별 정보와 상세 표에서 생략되어도 보존되는 접촉 근거가 포함됩니다.
원하는 언어의 소스 ZIP을 받은 뒤 아래 명령으로 설치하세요.

## English

Download a language-specific source package from
[CalcLens v0.3.0](https://github.com/a123qsd/calclens/releases/tag/v0.3.0):

| Asset | Initial interface and main guide |
| --- | --- |
| [calclens-0.3.0-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-en.zip) | English |
| [calclens-0.3.0-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-ko.zip) | Korean |

You can also download the guides separately as Markdown files:
[English guide](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.en.md) ·
[Korean guide](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.ko.md).
These text files explain the app; they do not contain the program.

Both packages contain the same geometry engine, examples, and English/Korean
interface switch. The main `README.md` in each ZIP is the corresponding full
language guide; `README.en.md` and `README.ko.md` are both included.

These are **source ZIPs, not standalone executables**. Install Python 3.12 or 3.13 first.
You need an internet connection for the initial dependency installation. Running
the local geometry checks does not require an API key or paid computation service.
The installation command examples below use Python 3.12.

### Install on macOS or Linux

Extract the ZIP and open a terminal in `calclens-0.3.0-en` (or `calclens-0.3.0-ko`
for the Korean package), the folder containing `run_app.py` and `requirements.lock`. Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Install on Windows

Extract the ZIP and open PowerShell in `calclens-0.3.0-en` (or `calclens-0.3.0-ko`
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

The report-language selector defaults to the interface language. You can select
English or Korean separately for JSON/CSV downloads; filenames end in
`_calclens_en.json`, `_calclens_ko.json`, or the corresponding `.csv` suffix.
For the CLI, pass `--language en` or `--language ko`; its default is English.

Issue explanations, assumptions, and limitations are localized. CSV headings
are localized too. JSON keys, technical codes, severity values, units, indices,
and numerical results stay consistent for comparison and automated processing.
Korean JSON retains the English source explanations alongside its Korean text.
App and CLI Korean CSV files use UTF-8 with a BOM; JSON uses UTF-8 without a BOM.

### Compare CIF files

Choose **Compare CIF files**, upload up to 20 CIFs, and set each file's axis and
cutoff. Each file keeps the 2 MiB and 400-site limits. Select a summary row for
the individual structure view and reports, or export the comparison CSV. An
unsupported file keeps its reason without stopping the other checks.
The summary follows the interface language; detailed report language is separate.

App and CLI reports include the original filename, exact-byte SHA-256, and
CalcLens/ASE versions. Use **View nearest pair** to inspect the minimum even
when the short-contact list is empty. See the [English guide](../README.en.md)
and [public graphite case](CASE_STUDY.md) for examples.

Use only public or shareable structures when reporting an issue. The bundled
examples are analytical test models, not experimental or relaxed structures.
See the [English guide](../README.en.md) for the input limits, result definitions,
CLI commands, and license conditions.

### Save and reopen work

CalcLens v0.3.0 keeps per-file settings and selection during comparison edits,
caches checks by file content, axis, and cutoff for the session, and offers
**All**, **Needs review**, and **Input errors** filters. Exports still include
all files and provenance.

**Save project** downloads a `.calclens.json` with original CIF bytes, unique
entry IDs, conditions, selection, review focus/filter, notes, and reviewed state.
Choose **Open saved work** in the sidebar, upload it, and click **Open project**
to continue without the original CIF files. Invalid or missing CIF payloads and
hash mismatches are rejected; engine-version differences warn and trigger a
recalculation. Projects restore work separately from JSON/CSV reports.
See the [project guide](../README.en.md#save-and-continue-a-comparison) for details.

## 한국어

[CalcLens v0.3.0 배포 페이지](https://github.com/a123qsd/calclens/releases/tag/v0.3.0)에서
원하는 언어의 소스 ZIP을 받으세요.

| 파일 | 처음 열리는 화면과 기본 안내 |
| --- | --- |
| [calclens-0.3.0-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-ko.zip) | 한국어 |
| [calclens-0.3.0-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.3.0/calclens-0.3.0-en.zip) | 영어 |

안내 문서만 필요하면 Markdown 파일로 따로 받을 수 있습니다.
[한국어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.ko.md) ·
[영어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.3.0/CalcLens-Guide.en.md).
안내 파일에는 프로그램이 들어 있지 않습니다.

두 파일의 검사 엔진과 예제는 같습니다. 둘 다 한국어·영어 화면을 제공하며, ZIP 안의
`README.md`만 선택한 언어의 전체 안내로 시작합니다. `README.en.md`와 `README.ko.md`도
함께 들어 있습니다.

**독립 실행 프로그램이 아니라 소스 ZIP입니다.** Python 3.12 또는 3.13을 먼저 설치하고
아래 명령으로 필요한 패키지를 설치해야 합니다. 처음 설치할 때는 인터넷 연결이
필요합니다. 로컬 기하 검사에는 API 키나 유료 계산 서비스가 필요하지 않습니다.
아래 설치 명령 예시는 Python 3.12를 사용합니다.

### macOS·Linux에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 `calclens-0.3.0-ko` 폴더에서
터미널을 열고 실행하세요. 영어 패키지를 받았다면 폴더 이름은 `calclens-0.3.0-en`입니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Windows에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 `calclens-0.3.0-ko` 폴더에서
PowerShell을 열고 실행하세요. 영어 패키지를 받았다면 폴더 이름은 `calclens-0.3.0-en`입니다.

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

보고서 언어는 기본적으로 화면 언어를 따릅니다. JSON·CSV 다운로드에 사용할 언어를
한국어·영어 중 별도로 선택할 수도 있습니다. 파일명 끝에는 `_calclens_ko.json`,
`_calclens_en.json` 또는 같은 형식의 `.csv`가 붙습니다. 명령행에서는
`--language ko` 또는 `--language en`을 지정하세요. 명령행의 기본값은 영어입니다.

점검 설명·가정·한계와 CSV 열 제목은 번역합니다. JSON 키와 기술 코드, 심각도 값,
단위, 인덱스와 수치는 비교·자동 처리를 위해 유지합니다. 한국어 JSON에는 영문 원문도
함께 남깁니다. 앱과 명령행의 한국어 CSV는 BOM이 있는 UTF-8을 사용하며,
JSON은 BOM 없는 UTF-8로 저장합니다.

### 여러 CIF 비교

**여러 CIF 비교**를 고르고 최대 20개 CIF를 올린 뒤 파일별 축과 기준을 정합니다.
파일당 2 MiB·400개 원자 제한은 같습니다. 요약 표의 행을 선택하면 해당 구조와
개별 보고서가 열리고, **전체 비교 요약 CSV 내보내기**로 전체 요약을 저장할 수 있습니다.
지원하지 않는 파일은 이유를 표시하며 다른 파일의 검사는 계속합니다.
요약은 화면 언어를 따르고, 개별 보고서의 언어는 별도로 선택합니다.

앱과 명령행의 보고서에는 원본 파일명, 원본 바이트의 SHA-256, CalcLens·ASE 버전이
들어갑니다. 짧은 접촉이 없어도 **원자쌍 보기**로 최소 거리의 근거를 확인할 수 있습니다.
사용 예는 [한국어 안내](../README.ko.md)와 [공개 흑연 사례](CASE_STUDY.md)를 확인하세요.

오류를 제보할 때는 공개해도 되는 구조만 사용하세요. 동봉한 예제는 기하 계산을 확인하기 위한
모델이며 실험 구조나 최적화된 구조가 아닙니다. 입력 제한, 결과 해석, 명령행 사용법과
이용 조건은 [한국어 전체 안내](../README.ko.md)에 있습니다.

### 작업 저장하고 다시 열기

CalcLens v0.3.0은 비교 목록을 편집해도 파일별 조건과 선택을 유지하며, 파일 내용·축·기준별로
세션 안에서 검사를 캐시합니다. **전체**, **검토 필요**, **입력 오류** 필터로 비교 표를
좁혀도 내보내기에는 모든 파일과 원본 식별 정보가 들어갑니다.

**작업 저장**으로 원본 CIF 바이트, 고유 항목 ID, 조건, 선택한 파일, 검토 초점·필터,
메모와 검토 완료 상태를 담은 `.calclens.json`을 내려받습니다. 사이드바의
**저장한 작업 열기**에서 파일을 올리고 **작업 불러오기**를 누르면 원본 CIF 없이
이어갈 수 있습니다. CIF 데이터의 손상·누락이나 해시 불일치는 거부하며, 엔진 버전이
다르면 경고 후 현재 엔진으로 다시 계산합니다. 작업 파일은 JSON·CSV 결과 보고서와
별도로 검토 상태를 복원합니다. 자세한 내용은
[작업 저장 안내](../README.ko.md#비교-작업-저장하고-이어가기)를 확인하세요.
