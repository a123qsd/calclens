# CalcLens 0.9.1

## 한국어

Windows 배포본은 ZIP 전체를 한 번 푼 뒤 사용하는 폴더형 앱입니다.
`runtime` 폴더 옆의 `CalcLens.exe`를 실행하고, 앱을 옮길 때도 폴더 전체를
함께 옮기세요. 새 버전은 기존 폴더에 덮어 풀지 말고 새 폴더에 풉니다.
Apple Silicon Mac에서는 DMG의 CalcLens를 응용 프로그램 폴더로 옮겨 실행합니다.

- 저장한 H₂ 밀도 차이에 원본 AB/A/B, 1부터 시작하는 조각 원자 번호, 격자·단위와 계산 축·법선을 보관합니다. 현재 검사 축을 바꿔도 계산 당시의 조건을 유지합니다.
- 연구 자료나 조건을 바꾸면 현재 선택과 맞지 않는 그래프를 지우고 해당 결과의 내보내기를 막습니다.
- **설정**에서 계산 장치, 테마, 화면 그래픽 품질과 PNG 출력을 선택합니다. 사용 가능한 계산 장치는 컴퓨터와 작업에 따라 달라집니다.
- 원본 CIF와 SHA-256을 확인·복사하고 원래 CIF 바이트를 저장할 수 있습니다. 편집 중에는 세션별 복구본을 기록합니다.

기하 보고서의 판정에는 배정밀도 CPU 결과를 사용합니다. 밀도 차이와 평면 평균은
제공된 격자에서 계산하며 전자구조를 새로 계산하지 않습니다. 원자핵 기준 간격만으로
진공의 충분함을 판단할 수 없으며, 의도한 계산 조건에서 별도의 수렴 검증이 필요합니다.

## English

The Windows distribution is a folder ZIP. Extract the complete archive once,
then open `CalcLens.exe` beside `runtime`. Keep the whole folder together when
moving the app, and extract upgrades into a new folder. On Apple Silicon Mac,
drag CalcLens from the DMG into Applications.

- Saved H₂ density differences retain their AB/A/B sources, 1-based fragment atom numbers, grid and units, and calculation axis and normal, even when the current inspection axis changes.
- Changing research data or conditions clears plots and prevents exports that no longer match the active selection.
- **Settings** provides compute device, theme, interactive graphics and PNG options. Device availability depends on the computer and task.
- Original CIF bytes and their SHA-256 can be inspected, copied and exported. Each editing session also writes a recovery copy.

Geometry decisions use double-precision CPU results. Density differences and
planar averages operate on supplied grids without solving for an electronic
structure. A nuclear-position gap does not establish sufficient vacuum;
convergence tests are needed for the intended calculation.

## Downloads / 다운로드

| Platform / 운영체제 | File / 파일 |
| --- | --- |
| Windows x64 | [CalcLens-0.9.1-Windows-x64-folder.zip](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-Windows-x64-folder.zip) |
| Apple Silicon Mac | [CalcLens-0.9.1-macOS-Apple-Silicon.dmg](https://github.com/a123qsd/calclens/releases/download/v0.9.1/CalcLens-0.9.1-macOS-Apple-Silicon.dmg) |
| SHA-256 | [SHA256SUMS.txt](https://github.com/a123qsd/calclens/releases/download/v0.9.1/SHA256SUMS.txt) |

[Installation / 설치 안내](DOWNLOADS.md) · [Desktop guide / 사용 안내](DESKTOP.md) ·
[Source / 소스](https://github.com/a123qsd/calclens/archive/refs/tags/v0.9.1.zip) ·
[Earlier review record / 출시 전 검토 기록](NATIVE_REVIEW.md)
