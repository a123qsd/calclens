# CalcLens 0.8.0

Created, led and maintained by [a123qsd](https://github.com/a123qsd).
[Project origin and responsibilities](../AUTHORS.md)

## Workspace changes

The selected structure is the focus of the workspace:

- Compact horizontal navigation opens the overview, comparison, review and method screens.
- The selected filename is the main heading, with visible file and project-save actions.
- A file strip switches structures; the sample action takes less space.
- A larger viewer sits beside compact numerical results and review controls.
- Viewer controls stay close to the structure they affect.

CIF geometry checks, project ZIPs, file drafts, pair measurements, electronic
datasets, P1 preparation, linked comparison cameras and PNG export remain
available. Scientific API contracts, source data and the default rendering
settings are preserved.

## 작업공간 변경 사항

선택한 구조를 중심으로 화면을 정리했습니다.

- 가로 메뉴에서 개요·비교·검토·방법 화면을 엽니다.
- 선택한 파일명을 화면 제목으로 표시하고 파일 열기·작업 저장 버튼을 배치했습니다.
- 파일 선택 줄에서 구조를 바꾸며, 예제 불러오기는 공간을 덜 차지하도록 정리했습니다.
- 넓은 뷰어 옆에서 수치와 검토 항목을 확인합니다.
- 뷰어 조작 버튼을 구조 가까이에 배치했습니다.

CIF 기하 검사, 작업 ZIP, 파일별 초안, 원자쌍 측정, 전자 자료, P1 준비,
비교 시점 동기화와 PNG 저장 기능을 계속 제공합니다. 과학 계산 API의 규약,
원본 자료와 기본 렌더링 설정은 유지합니다.

## Verification / 검증

Local verification passed: 657 Python tests, 56 frontend tests, typecheck/build,
Ruff and all 34 existing browser check groups. Two PowerShell-only tests await
Windows CI. Both languages passed 390, 820, 1100 and 1584 px layout checks with
no horizontal page overflow or overlapping sample controls. Viewer updates,
project roundtrips, draft/camera restoration, electronic data, P1 preparation
and image export passed. Original CIF fixtures and independent reference
calculations are unchanged.

로컬 검증에서 Python 657개와 프런트엔드 56개 테스트, 빌드·타입 검사·정적 검사,
기존 브라우저 검사 34개 그룹이 통과했습니다. PowerShell 전용 검사 2개는
Windows CI에서 실행합니다. 두 언어의 390·820·1100·1584px 배치, 작업 재열기,
초안·카메라 복원, 전자 자료, P1 준비와 이미지 저장을 확인했습니다.

Windows packages are published only after their native build and browser checks
pass. The release resources contain the exact source commit, workflow links and
artifact hashes in VALIDATION-0.8.0.json. Previous-version results in
[the validation record](VALIDATION.md) apply to their named versions and commits.
