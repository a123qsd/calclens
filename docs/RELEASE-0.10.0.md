# CalcLens 0.10.0

## 구조를 돌리고 측정하기

회전할 때 배율과 중심을 유지합니다. **표시** 메뉴에서 셀 전체, 원자, 측정 대상 중 하나에 맞출 수 있습니다. 측정 대상 맞춤에는 이웃 셀로 옮긴 거리선의 양 끝점이 들어갑니다. 공간 채움 표시에서는 구의 반지름까지 반영합니다. 언어를 여러 번 바꾼 뒤 작업이 끝날 때 삭제된 취소 버튼을 호출하던 오류도 수정했습니다.

손을 조금 움직여도 클릭은 클릭으로 처리합니다. 드래그를 시작하면 출발점으로 돌아와도 원자가 선택되지 않습니다. 거리와 축 주석은 구조 앞에 표시하고, 마우스 강조와 원자 선택은 기존 화면을 다시 사용합니다. 거리 모드나 이미지 이동량을 바꾸면 이전 측정값을 지웁니다.

## 계산 결과와 구조 비교

연구 도구에서 Gaussian 분자 로그와 VASP OUTCAR를 열면 원본 파일, SHA-256, 작업 단계와 근거 행을 확인할 수 있습니다. 구조 비교 창에서는 계산 출력의 마지막 완전한 좌표와 CIF를 선택할 수 있습니다. 같은 번호가 같은 원자인지 확인한 뒤 입력 좌표의 변위, 분자의 강체 정렬 RMSD, 같은 주기 셀의 최소 이미지 변위를 구합니다. 에너지 차이를 표시하려면 두 출력의 에너지 정의와 기록된 조건이 맞고, 사용자가 전체 입력 조건을 확인해야 합니다.

내장 Ni OUTCAR에는 전자 반복 63회와 이온 단계 1개가 있습니다. 구조 비교 창은 원자 400개까지 그리며, 그보다 큰 출력의 원본과 계산 요약도 보관합니다. 비교 대상을 바꾸면 원자 번호와 계산 조건을 다시 확인합니다. [Ni 기준 자료](../examples/research_cases/vasp_reference/sources.json)

## 전자밀도와 재현성

CHGCAR 가져오기는 원소명이 명시된 VASP 5/6 구조와 첫 총밀도 블록을 지원합니다. 선택한 CIF와 격자 및 원자 순서를 대조하고 원본 바이트를 보관합니다. 격자는 최대 100만 점, 파일은 최대 32 MiB입니다. 음수 표본이 있는 총밀도 입력은 거부합니다. 뒤따르는 PAW 점유 및 자화 블록은 원본에 남고 분석에는 첫 블록만 사용합니다. [VASP CHGCAR 형식](https://vasp.at/wiki/CHGCAR)

Cube 또는 CHGCAR에서 평면 평균과 누적 전자수, 분할 평면 양쪽의 전자수를 확인할 수 있습니다. Δρ의 양·음 적분은 원래 3차원 격자에서 따로 구합니다. 평면마다 표본을 중심에 둔 구간을 사용하며, 이 수치만으로 특정 원자에 전하를 배정할 수는 없습니다.

현재 밀도 프로파일과 보관한 Δρ는 원본과 당시 조건을 이용해 CPU에서 다시 계산할 수 있습니다. 검증 JSON에는 원본과 결과의 해시, 계산 축·법선, 실행 환경, 수치 오차와 허용오차가 들어갑니다. 이전 프로젝트에 기록되지 않은 조건은 보고서에서 확인할 수 있습니다. 재검증 범위는 가져온 전자구조 계산의 후처리입니다.

## Publication figures

**File → Export publication figure** writes a 4:3 figure at 85 or 180 mm, at 300 or 600 dpi. Choose PNG for lossless raster output with optional transparency, or PDF for a print-sized page containing the rasterized structure and a vector scale bar. The bar is calibrated in ångströms from the actual orthographic projection. The original file hash, camera, selected fields, isovalues and print dimensions travel with the figure. Find them in the PNG text metadata or the PDF attachment `calclens-figure.json`.

Use **Export profile figure** in the density panel to save the displayed planar mean or cumulative electron count. The PDF keeps its axes, labels and curve as vectors. The figure includes the selected dataset identity, numerical profile and CPU verification record.

Gaussian and VASP import reads completed or partial text outputs and labels their execution and convergence status. The OUTCAR reader keeps TOTEN, energy without entropy and the sigma-to-zero value distinct. Up to eight original outputs can be retained, within a 64 MiB combined source limit and the project's overall storage limit. The comparison uses the declared atom indices and supports equal-weight proper rigid fitting for molecules or minimum images in the same lattice. Formats in this release include Gaussian text logs, OUTCAR, Cube and the first CHGCAR total-density block. [Desktop guide](DESKTOP.md) · [VASP OUTCAR](https://vasp.at/wiki/OUTCAR)
