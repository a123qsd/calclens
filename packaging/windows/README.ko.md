# Windows용 CalcLens

Windows 10/11 x64용 CalcLens 0.7.0에는 Python, 필요한 패키지와 화면 파일이
들어 있습니다. Python이나 Node.js를 따로 설치할 필요가 없습니다.

1. [CalcLens v0.7.0 배포 페이지](https://github.com/a123qsd/calclens/releases/tag/v0.7.0)를 엽니다.
2. [한국어 EXE](https://github.com/a123qsd/calclens/releases/download/v0.7.0/CalcLens-0.7.0-windows-x64-ko.exe)
   또는 [영어 EXE](https://github.com/a123qsd/calclens/releases/download/v0.7.0/CalcLens-0.7.0-windows-x64-en.exe)를 받습니다.
3. 받은 파일을 두 번 클릭합니다. 실행 상태를 보여 주는 작은 관리 창과 기본
   브라우저의 CalcLens 화면이 열립니다. 단일 실행 파일은 시작할 때 포함된 파일을
   풀기 때문에 몇 초가 걸릴 수 있습니다. 반복 실행 시간을 줄이려면
   [한국어 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.7.0/CalcLens-0.7.0-windows-x64-ko-folder.zip)
   또는 [영어 폴더 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.7.0/CalcLens-0.7.0-windows-x64-en-folder.zip)을
   모두 풀고 안에 있는 실행 파일을 사용하세요. 함께 들어 있는 파일은 같은 폴더에 보관해야 합니다.
4. 관리 창의 `CalcLens 열기`로 화면을 다시 열고, `진단 기록`으로 시작 기록을
   확인할 수 있습니다. `종료`나 관리 창 닫기를 사용하면 서버도 함께 종료됩니다.
   브라우저 탭만 닫으면 앱은 계속 실행됩니다. 저장하지 않은 작업은 메모리에만
   있으므로 종료하기 전에 작업을 저장하세요.

앱은 `127.0.0.1`에서만 연결을 받습니다. CIF 파일은 내 컴퓨터에서 처리하며,
다른 컴퓨터에 접속을 제공하는 서비스로 실행하지 않습니다. 안내 문서나 GitHub 링크를
선택하면 해당 웹사이트가 열립니다. 앱 안에서 화면 언어를 바꿀 수 있습니다.

CalcLens는 CIF의 기하 정보를 점검합니다. 화학적 안정성, 전자구조, 진공 수렴을
판정하지 않습니다. 보고서를 해석하기 전에 앱의 방법 설명과
[한국어 안내](https://github.com/a123qsd/calclens/blob/main/README.ko.md)를 확인하세요.

## 파일 확인과 Windows 경고

이 실행 파일은 서명하지 않았으며 게시자 인증서가 없습니다. Windows에서
게시자를 확인할 수 없다는 메시지나 Microsoft Defender SmartScreen 경고가
나올 수 있습니다. 실행 여부를 결정하기 전에 배포 계정, 소스와 파일 체크섬을
확인하세요. CalcLens를 사용하려고 Windows 보호 기능을 끄지 마세요.
체크섬이 같다는 것은 배포 페이지의 체크섬과 파일이 일치한다는 뜻입니다.
게시자 인증이나 프로그램에 대한 안전 보증을 대신하지 않습니다.

같은 배포 페이지에서 [WINDOWS-SHA256SUMS.txt](https://github.com/a123qsd/calclens/releases/download/v0.7.0/WINDOWS-SHA256SUMS.txt)를 받으세요. PowerShell에서
다음 명령을 실행한 뒤, 표시된 값을 받은 파일에 해당하는 항목과 비교합니다.

```powershell
Get-FileHash .\CalcLens-0.7.0-windows-x64-ko.exe -Algorithm SHA256
```

## 라이선스, 소스와 다시 빌드하기

[한국어 소스 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.7.0/calclens-0.7.0-ko.zip)과
[영어 소스 ZIP](https://github.com/a123qsd/calclens/releases/download/v0.7.0/calclens-0.7.0-en.zip)은
Python 3.12 또는 3.13과 의존성 설치가 필요합니다. 화면 파일은 포함되어 있어 실행에
Node.js는 필요하지 않습니다. Python을 설치하지 않고 사용하려면 위의 EXE나 폴더 ZIP을 받으세요.
[CalcLens-0.7.0-windows-support.zip](https://github.com/a123qsd/calclens/releases/download/v0.7.0/CalcLens-0.7.0-windows-support.zip)에는
타사 라이선스 고지, 빌드에 사용한 정확한
ASE 소스 압축 파일, 의존성 정보와 CalcLens 소스가 들어 있습니다.
실행 파일을 재배포할 때 지원 ZIP도 함께 보관하고 전달하세요.
지원 ZIP의 체크섬도 `WINDOWS-SHA256SUMS.txt`에 있습니다.

CalcLens 자체 라이선스는 이 프로젝트가 작성한 코드와 문서에 적용됩니다.
포함된 타사 구성 요소에는 각각의 라이선스가 적용됩니다. ASE는
LGPL-2.1-or-later에 따라 수정하거나 교체한 뒤 CalcLens를 다시 빌드할 수 있습니다.
CalcLens 라이선스도 그 수정 사항을 디버깅하는 데 필요한 권리를 보존합니다.
수집한 라이선스 목록은 원래 라이선스 조항이나 모든 법적 의무에 대한 검토를
대신하지 않습니다.

다시 빌드하려면 Windows x64에서 CPython 3.13를 설치하고 Windows 지원 ZIP을
푸세요. 그 폴더에서 PowerShell을 연 뒤 다음 명령을 실행합니다. 기록된 소스
커밋을 읽고 CalcLens 소스를 푼 다음 빌드 환경을 만듭니다. 빌드 환경의 Python을
직접 실행하므로 PowerShell 활성화 명령은 필요하지 않습니다.

```powershell
$sourceCommit = (Get-Content .\DEPENDENCIES.json -Raw | ConvertFrom-Json).source_commit
Expand-Archive .\CalcLens-windows-source.zip .
Set-Location .\calclens-source
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --require-hashes -r packaging/windows/build-requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation .
.\.venv\Scripts\python.exe scripts/build_windows.py --language ko --mode onefile --output dist/windows --source-commit $sourceCommit
.\.venv\Scripts\python.exe scripts/build_windows.py --language en --mode onefile --output dist/windows --source-commit $sourceCommit
```

ASE를 수정하려면 지원 ZIP의 `sources/ase-3.29.0.tar.gz`를 풀어 편집하세요.
위의 고정된 의존성을 설치한 다음
`.\.venv\Scripts\python.exe -m pip install --no-deps PATH_TO_MODIFIED_ASE`로 수정한 ASE를 설치하고,
두 빌드 명령을 다시 실행합니다. 수정 내용을 기록하고 라이선스 고지를 유지하세요.
제공된 실행 파일을 사용하는 데는 Python이 필요하지 않으며, 다시 빌드할 때 필요합니다.
의존성 버전과 소스 커밋은 `DEPENDENCIES.json`에 기록됩니다.
구성 요소를 바꾸면 빌드 결과도 달라집니다. 실행 파일과 동반 폴더를 만드는 빌드는
`--mode onefile` 대신 `--mode onedir`를 사용합니다.

## 새 화면과 이전 화면

기본 화면은 React/TypeScript와 3Dmol.js를 사용합니다. 화면 스크립트와 라이선스는
실행 파일에 포함되므로 Node.js나 CDN 연결이 필요하지 않습니다. 공개된 0.6.0
배포판에는 이전 Streamlit 화면도 들어 있어 `--legacy-ui`로 실행할 수 있습니다.

0.7.0 소스부터 기본 Windows 빌드는 Streamlit과 Plotly를 제외합니다. 이전 화면도
포함하려면 `requirements.lock` 대신 `requirements-legacy.lock`을 설치하고,
`build_windows.py`에 `--include-legacy-ui`를 추가하세요. 이 배포판은 파일명에
`-legacy`가 붙으며 실행할 때 `--legacy-ui`를 사용할 수 있습니다. 빌드 정보에는
`includes_legacy_ui: true`가 기록됩니다. 기본 배포판에서 이전 화면을 요청하면
포함되지 않았다는 안내가 나옵니다. 두 배포판의 지원 ZIP과 라이선스 목록도 별도로
만듭니다. 이전 화면 포함 지원 ZIP의 소스 파일명은
`CalcLens-windows-source-legacy.zip`이므로 위 `Expand-Archive` 명령에도
이 파일명을 사용하세요. 실제 파일 크기와 시작 시간 차이는 Windows에서 빌드한 뒤 측정해야 합니다.

소스의 화면을 수정해
다시 빌드할 때는 Node 26.7.0에서 `cd frontend`, `npm ci --ignore-scripts`,
`npm run build`를 실행하고 루트로 돌아와 위의 패키지 설치·빌드 명령을 실행합니다.
