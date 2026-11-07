# CalcLens 데스크톱 0.9.0 / CalcLens Desktop

Windows x64에서는 `CalcLens-0.9.0-Windows-x64.exe`를 두 번 클릭합니다. Apple Silicon Mac에서는 DMG를 열고 `CalcLens.app`을 응용 프로그램 폴더에 옮긴 다음 실행합니다. 앱을 시작하면 그래핀 구조와 기하 검사 결과가 보입니다. 파일 선택, 구조 회전, 원자 선택, 거리 측정, 대칭 전개, 비교, 그림 출력은 데스크톱 창 안에서 이루어집니다. 창은 QtWidgets로 그리며 같은 프로세스의 Python 엔진이 계산합니다.

Double-click the Windows x64 executable or open the Apple Silicon application. The initial graphene structure opens in a native Qt window. Drag one or more CIFs into it, select a file, and rotate the structure with the mouse. Use the comparison action to inspect two structures or datasets. The default desktop application works offline.

[Windows x64 EXE](https://github.com/a123qsd/calclens/releases/download/v0.9.0/CalcLens-0.9.0-Windows-x64.exe) · [Apple Silicon Mac DMG](https://github.com/a123qsd/calclens/releases/download/v0.9.0/CalcLens-0.9.0-macOS-Apple-Silicon.dmg) · [전체 배포 파일](https://github.com/a123qsd/calclens/releases/tag/v0.9.0)

## 작업 저장과 복구

**작업 저장**은 원본 CIF, 파일별 조건과 메모, 검토 이력, 측정, 전자 자료, 연구 원본을 휴대용 `.calclens.zip`에 보관합니다. 변경 후 자동 복구본은 사용자 계정에 저장됩니다. 다음 실행 때 이전 세션의 복구본이 있으면 시각을 확인하고 열 수 있습니다. 종료 시에는 저장·버리기·취소 중 하나를 선택합니다. 이미 열려 있는 다른 CalcLens 창의 초안은 복구 후보에서 제외합니다.

Recovery files live under `%LOCALAPPDATA%/CalcLens/Recovery` on Windows and `~/Library/Application Support/CalcLens/Recovery` on macOS. CalcLens writes each session's backup atomically and retains a previous generation. The project ZIP remains the portable way to carry work to another computer. Opening an archive validates its original data before replacing the current project.

## 계산 장치 선택

**연구 도구 → 연산 장치·밀도 차이**에서 장치를 확인하고 CPU, Apple Metal, NVIDIA CUDA 또는 원격 워커를 선택합니다. 이 선택은 전자 격자 차이, 평면 평균, 주기적 원자쌍 거리의 벡터 길이 계산에 적용됩니다. 기하 보고서의 판정에는 배정밀도 CPU 결과를 사용합니다. 자동 선택은 해당 작업의 전송·계산·검산 시간을 포함해 장치를 비교합니다. 실행 결과에는 사용한 장치와 정밀도가 표시됩니다.

원격 워커에는 사용자가 선택한 수치 배열만 보냅니다. 워커 주소와 토큰을 입력한 뒤 전송할 때 확인합니다. 토큰은 프로젝트에 저장하지 않습니다. 큰 작업에서 결과 적용을 취소하면 이후 계산 결과가 열린 프로젝트에 반영되지 않습니다. 워커에서 시작한 계산은 끝까지 실행될 수 있습니다. 워커 실행, TLS 설정과 장치별 검증 범위는 [계산 안내](COMPUTE.md)에 있습니다.

## 실제 자료 열기

- **전자 자료**에서 선택한 CIF와 일치하는 전하 JSON이나 Cube를 엽니다. 수치를 읽을 때 물리량과 파일 단위를 선택합니다. 차이·스핀 밀도와 오비탈에는 양·음 등치면이 있습니다. 그림에는 실제 표시한 자료의 출처, 단위와 등치값을 기록할 수 있습니다.
- **연산 장치·밀도 차이 → H₂ 실제 계산 예제 열기**는 같은 기하와 격자에서 계산한 H₂와 두 H 조각의 원본으로 작업을 엽니다. Δρ를 다시 계산한 뒤 평면 평균과 계산 기록을 내보낼 수 있습니다. [원본과 계산 방법](../examples/research_cases/h2_density/README.md)
- **Gaussian 로그 → 기준 예제**는 공개 Gaussian 출력에서 계산 단계, 정상·오류·중단 상태, SCF 에너지, 최적화, 진동수와 원본 행 번호를 읽습니다. 원본 파일과 해석 JSON을 따로 저장할 수 있습니다.
- **진공 간격 수렴 → h-BN 예제**는 주기적 PySCF 계산 세 건과 입력·출력 해시를 비교합니다. 사용한 방법, 고정한 조건, 허용오차와 샘플 범위를 결과 JSON에서 확인할 수 있습니다. [연구 사례와 검증](RESEARCH_CASES.md)

## Source and packaging

Use Python 3.12 or 3.13. From a checkout install `python -m pip install --require-hashes -r requirements.lock`, then `python -m pip install --no-deps --no-build-isolation .`. Launch `python run_app.py` or `calclens-desktop`. `python run_app.py --web-ui` opens the optional earlier browser interface. The command-line geometry tool remains `calclens input.cif --json report.json`.

The x64 Windows portable build embeds CPython and Windows wheels from the recorded hashes. `scripts/build_portable_windows.py` assembles the executable using NSIS. The Windows PyInstaller workflow also supports an interactive native build. `scripts/build_native_macos.py` builds the Apple Silicon bundle with its Qt runtime and Metal helper. Research data, validation fixtures, original software notices, and example source licenses accompany the distributions.
