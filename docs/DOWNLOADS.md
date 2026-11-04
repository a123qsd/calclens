# Downloads and installation / 다운로드·설치

[Project home](../README.md) · [Full English guide](../README.en.md) · [한국어 전체 안내](../README.ko.md)

The asset links below download published **v0.1.1**. The current source tree is
**0.2.0** and adds multiple-file comparison, report source identity, and improved
contact evidence. To use those changes, install the current source folder with
the same commands below; no v0.2.0 release asset is linked here.

아래 배포 링크는 공개된 **v0.1.1** 파일입니다. 현재 소스 버전 **0.2.0**에는
여러 파일 비교, 보고서의 원본 식별 정보, 접촉 근거 보강이 포함됩니다.
새 기능을 사용하려면 현재 소스 폴더에서 아래와 같은 설치 명령을 실행하세요.

## English

Download a language-specific source package from
[CalcLens v0.1.1](https://github.com/a123qsd/calclens/releases/tag/v0.1.1):

| Asset | Initial interface and main guide |
| --- | --- |
| [calclens-0.1.1-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-en.zip) | English |
| [calclens-0.1.1-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-ko.zip) | Korean |

You can also download the guides separately as Markdown files:
[English guide](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.en.md) ·
[Korean guide](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.ko.md).
These text files explain the app; they do not contain the program.

Both packages contain the same geometry engine, examples, and English/Korean
interface switch. The main `README.md` in each ZIP is the corresponding full
language guide; `README.en.md` and `README.ko.md` are both included.

These are **source ZIPs, not standalone executables**. Install Python 3.12 first.
You need an internet connection for the initial dependency installation. Running
the local geometry checks does not require an API key or paid computation service.

### Install on macOS or Linux

Extract the ZIP and open a terminal in the folder containing `run_app.py` and
`requirements.lock`. Run:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Install on Windows

Extract the ZIP and open PowerShell in the folder containing `run_app.py` and
`requirements.lock`. Run:

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

### Compare files in the 0.2.0 source version

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

## 한국어

[CalcLens v0.1.1 배포 페이지](https://github.com/a123qsd/calclens/releases/tag/v0.1.1)에서
원하는 언어의 소스 ZIP을 받으세요.

| 파일 | 처음 열리는 화면과 기본 안내 |
| --- | --- |
| [calclens-0.1.1-ko.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-ko.zip) | 한국어 |
| [calclens-0.1.1-en.zip](https://github.com/a123qsd/calclens/releases/download/v0.1.1/calclens-0.1.1-en.zip) | 영어 |

안내 문서만 필요하면 Markdown 파일로 따로 받을 수 있습니다.
[한국어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.ko.md) ·
[영어 안내 파일](https://github.com/a123qsd/calclens/releases/download/v0.1.1/CalcLens-Guide.en.md).
안내 파일에는 프로그램이 들어 있지 않습니다.

두 파일의 검사 엔진과 예제는 같습니다. 둘 다 한국어·영어 화면을 제공하며, ZIP 안의
`README.md`만 선택한 언어의 전체 안내로 시작합니다. `README.en.md`와 `README.ko.md`도
함께 들어 있습니다.

**독립 실행 프로그램이 아니라 소스 ZIP입니다.** Python 3.12를 먼저 설치하고
아래 명령으로 필요한 패키지를 설치해야 합니다. 처음 설치할 때는 인터넷 연결이
필요합니다. 로컬 기하 검사에는 API 키나 유료 계산 서비스가 필요하지 않습니다.

### macOS·Linux에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 폴더에서 터미널을 열고 실행하세요.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation .
.venv/bin/python run_app.py
```

### Windows에서 설치

ZIP을 푼 뒤 `run_app.py`와 `requirements.lock`이 있는 폴더에서 PowerShell을 열고 실행하세요.

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

### 0.2.0 소스 버전에서 여러 파일 비교

**여러 CIF 비교**를 고르고 최대 20개 CIF를 올린 뒤 파일별 축과 기준을 정합니다.
파일당 2 MiB·400개 원자 제한은 같습니다. 요약 표의 행을 선택하면 해당 구조와
개별 보고서가 열리고, **비교 요약 CSV 내보내기**로 전체 요약을 저장할 수 있습니다.
지원하지 않는 파일은 이유를 표시하며 다른 파일의 검사는 계속합니다.
요약은 화면 언어를 따르고, 개별 보고서의 언어는 별도로 선택합니다.

앱과 명령행의 보고서에는 원본 파일명, 원본 바이트의 SHA-256, CalcLens·ASE 버전이
들어갑니다. 짧은 접촉이 없어도 **원자쌍 보기**로 최소 거리의 근거를 확인할 수 있습니다.
사용 예는 [한국어 안내](../README.ko.md)와 [공개 흑연 사례](CASE_STUDY.md)를 확인하세요.

오류를 제보할 때는 공개해도 되는 구조만 사용하세요. 동봉한 예제는 기하 계산을 확인하기 위한
모델이며 실험 구조나 최적화된 구조가 아닙니다. 입력 제한, 결과 해석, 명령행 사용법과
이용 조건은 [한국어 전체 안내](../README.ko.md)에 있습니다.
