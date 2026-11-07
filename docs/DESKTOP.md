# CalcLens 데스크톱 0.9.1 / CalcLens Desktop

Windows에서는 ZIP 전체를 빈 폴더에 푼 뒤 `runtime` 옆의 `CalcLens.exe`를 실행합니다. 폴더 전체를 함께 보관하고, 새 버전은 별도 폴더에 푸세요. Apple Silicon Mac은 DMG를 열어 앱을 응용 프로그램 폴더로 옮깁니다. 첫 창에서 그래핀을 불러온 뒤 CIF 또는 저장한 프로젝트를 열 수 있습니다. [다운로드와 파일 검증](DOWNLOADS.md) · [Windows 빌드와 시작 진단](../packaging/desktop/windows-portable-build.md)

Extract the complete Windows ZIP and open `CalcLens.exe` beside its `runtime` folder. Keep these files together and extract upgrades into a new folder. On Apple Silicon, drag the app from the DMG into Applications. Open CIF files or a saved project in the native Qt window. [Windows x64 folder ZIP](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip) · [Apple Silicon Mac DMG](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-macOS-Apple-Silicon.dmg) · [SHA-256 checksums](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt)

## 화면과 환경 설정

상단 **설정**에서 시스템·라이트·다크 테마, 화면 그래픽 품질, PNG 너비와 배경을 고릅니다. 언어와 장치 선호는 이 컴퓨터에 저장합니다. 좁은 창에서는 **파일 목록**과 **검사 패널**로 구조 화면을 전환합니다. 오른쪽 **출처 상세**에서 원본 CIF와 전체 SHA-256을 확인하고 복사할 수 있습니다. **원본 CIF 저장**은 원래 바이트를 그대로 내보냅니다. [그래픽 품질과 웹 뷰어 비교](native-graphics.md)

## 작업 저장과 복구

**작업 저장**은 원본 CIF, 파일별 조건과 메모, 검토 이력, 측정, 전자 자료, 연구 원본을 휴대용 `.calclens.zip`에 보관합니다. 변경 후 자동 복구본은 사용자 계정에 저장됩니다. 다음 실행 때 이전 세션의 복구본이 있으면 시각을 확인하고 열 수 있습니다. 종료 시에는 저장·버리기·취소 중 하나를 선택합니다. 이미 열려 있는 다른 CalcLens 창의 초안은 복구 후보에서 제외합니다.

Recovery files live under `%LOCALAPPDATA%/CalcLens/Recovery` on Windows and `~/Library/Application Support/CalcLens/Recovery` on macOS. CalcLens writes each session's backup atomically and retains a previous generation. The project ZIP remains the portable way to carry work to another computer. Opening an archive validates its original data before replacing the current project.

보관한 H₂ Δρ는 원본 AB/A/B, 1부터 시작하는 조각 원자 번호, 격자·단위, 계산 축·법선, 공통 방법·조건 및 실행 기록과 함께 열립니다. 현재 검사 축이 다르면 연구 화면에서 이를 표시합니다. 당시 법선이나 실행 정보를 기록하지 않은 옛 자료는 재구성 가능한 조건과 CPU 재검산을 구분해 표시합니다. 자료나 조건을 바꾸면 그 선택에 맞지 않는 그래프와 내보내기 버튼은 비워집니다.

## 계산 장치 선택

**설정 → 계산 장치와 원격 워커**에서 실행 위치와 장치를 선택합니다. 장치 확인은 작은 격자·거리 계산으로 가용성을 검사합니다. 연결할 워커의 URL, 토큰, 제한 시간을 입력한 뒤 **워커 연결 확인**을 누르면 워커 정책에 따라 쓸 수 있는 장치가 표시됩니다. 이 선택은 전자 격자 차이, 평면 평균, 주기적 원자쌍 거리의 벡터 길이 계산에 적용됩니다. 기하 보고서의 판정에는 배정밀도 CPU 결과를 사용합니다. 자동 선택은 해당 작업의 전송·계산·검산 시간을 포함해 장치를 비교합니다. 실행 결과에는 사용한 장치와 정밀도가 표시됩니다.

원격 워커에는 사용자가 선택한 수치 배열만 보냅니다. 워커 주소와 토큰을 입력한 뒤 전송할 때 확인합니다. 토큰은 프로젝트에 저장하지 않습니다. 큰 작업에서 결과 적용을 취소하면 이후 계산 결과가 열린 프로젝트에 반영되지 않습니다. 워커에서 시작한 계산은 끝까지 실행될 수 있습니다. 워커 실행, TLS 설정과 장치별 검증 범위는 [계산 안내](COMPUTE.md)에 있습니다.

## 실제 자료 열기

- **전자 자료**에서 선택한 CIF와 일치하는 전하 JSON이나 Cube를 엽니다. 수치를 읽을 때 물리량과 파일 단위를 선택합니다. 차이·스핀 밀도와 오비탈에는 양·음 등치면이 있습니다. 그림에는 실제 표시한 자료의 출처, 단위와 등치값을 기록할 수 있습니다.
- **연산 장치·밀도 차이 → H₂ 실제 계산 예제 열기**는 같은 기하와 격자에서 계산한 H₂와 두 H 조각의 원본으로 작업을 엽니다. Δρ를 다시 계산한 뒤 평면 평균과 계산 기록을 내보낼 수 있습니다. [원본과 계산 방법](../examples/research_cases/h2_density/README.md)
- **Gaussian 로그 → 기준 예제**는 공개 Gaussian 출력에서 계산 단계, 정상·오류·중단 상태, SCF 에너지, 최적화, 진동수와 원본 행 번호를 읽습니다. 원본 파일과 해석 JSON을 따로 저장할 수 있습니다.
- **진공 간격 수렴 → h-BN 예제**는 주기적 PySCF 계산 세 건과 입력·출력 해시를 비교합니다. 사용한 방법, 고정한 조건, 허용오차와 샘플 범위를 결과 JSON에서 확인할 수 있습니다. [연구 사례와 검증](RESEARCH_CASES.md)

## Source and packaging

Use Python 3.12 or 3.13. From a checkout install `python -m pip install --require-hashes -r requirements.lock`, then `python -m pip install --no-deps --no-build-isolation .`. Launch `python run_app.py` or `calclens-desktop`. `python run_app.py --web-ui` opens the optional earlier browser interface. The command-line geometry tool remains `calclens input.cif --json report.json`.

The Windows x64 builder verifies the embedded CPython archive and selected wheels against their hashes. `scripts/build_portable_windows.py` packages the small NSIS launcher and runtime together in a folder ZIP. The Windows PyInstaller workflow also supports an interactive native build. `scripts/build_native_macos.py` builds the Apple Silicon bundle with its Qt runtime and Metal helper. Research data, validation fixtures, original software notices, and example source licenses accompany the distributions.
