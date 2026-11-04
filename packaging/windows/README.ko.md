# Windows용 CalcLens

CalcLens 0.3.0은 Windows 10 또는 11의 x64 환경에서 실행합니다.
Windows 실행 파일에 Python과 필요한 패키지가 들어 있어 Python을 따로 설치할 필요가 없습니다.

1. [CalcLens 배포 페이지](https://github.com/a123qsd/calclens/releases/tag/v0.3.0)를 엽니다.
2. 한국어로 시작하려면 `CalcLens-0.3.0-windows-x64-ko.exe`,
   영어로 시작하려면 `CalcLens-0.3.0-windows-x64-en.exe`를 받습니다.
3. 받은 파일을 두 번 클릭합니다. 콘솔 창이 열리고 기본 브라우저에서 앱이 실행됩니다.
   시작할 때 포함된 파일을 풀기 때문에 몇 초가 걸릴 수 있습니다.
   브라우저가 열리지 않으면 콘솔에 표시된 로컬 주소를 여세요.
4. 앱을 사용하는 동안 콘솔 창을 열어 두세요. 콘솔 창을 닫거나 그 창에서
   `Ctrl+C`를 누르면 앱이 종료됩니다. 브라우저 탭만 닫으면 앱은 계속 실행됩니다.

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

같은 배포 페이지에서 `WINDOWS-SHA256SUMS.txt`를 받으세요. PowerShell에서
다음 명령을 실행한 뒤, 표시된 값을 받은 파일에 해당하는 항목과 비교합니다.

```powershell
Get-FileHash .\CalcLens-0.3.0-windows-x64-ko.exe -Algorithm SHA256
```

## 라이선스, 소스와 다시 빌드하기

배포 페이지의 소스 ZIP은 Python을 별도로 설치해야 실행할 수 있습니다.
Python을 설치하지 않고 사용하려면 위의 `.exe` 파일을 받으세요.
`CalcLens-0.3.0-windows-support.zip`에는 타사 라이선스 고지, 빌드에 사용한 정확한
ASE 소스 압축 파일, 의존성 정보와 CalcLens 소스가 들어 있습니다.
실행 파일을 재배포할 때 지원 ZIP도 함께 보관하고 전달하세요.
지원 ZIP의 체크섬도 `WINDOWS-SHA256SUMS.txt`에 있습니다.

CalcLens 자체 라이선스는 이 프로젝트가 작성한 코드와 문서에 적용됩니다.
포함된 타사 구성 요소에는 각각의 라이선스가 적용됩니다. ASE는
LGPL-2.1-or-later에 따라 수정하거나 교체한 뒤 CalcLens를 다시 빌드할 수 있습니다.
CalcLens 라이선스도 그 수정 사항을 디버깅하는 데 필요한 권리를 보존합니다.
수집한 라이선스 목록은 원래 라이선스 조항이나 모든 법적 의무에 대한 검토를
대신하지 않습니다.

다시 빌드하려면 Windows x64에서 CPython 3.12를 설치하고 Windows 지원 ZIP을
푸세요. 그 폴더에서 PowerShell을 연 뒤 다음 명령을 실행합니다. 기록된 소스
커밋을 읽고 CalcLens 소스를 푼 다음 빌드 환경을 만듭니다. 빌드 환경의 Python을
직접 실행하므로 PowerShell 활성화 명령은 필요하지 않습니다.

```powershell
$sourceCommit = (Get-Content .\DEPENDENCIES.json -Raw | ConvertFrom-Json).source_commit
Expand-Archive .\CalcLens-windows-source.zip .
Set-Location .\calclens-source
py -3.12 -m venv .venv
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
구성 요소를 바꾸면 빌드 결과도 달라집니다.
