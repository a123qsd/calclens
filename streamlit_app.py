"""CalcLens: a local, bilingual geometry inspection interface."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from slab_preflight.core import UnsupportedStructure, analyze_cif
from slab_preflight.plotting import profile_figure, structure_figure

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 2 * 1024 * 1024
st.set_page_config(page_title="CalcLens", page_icon="🔬", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp {background: #faf8f5; color: #172331;}
.block-container {max-width: 1550px; padding: 2.3rem 1.6rem 2rem;}
[data-testid="stHeader"] {background: rgba(250,248,245,0.96);}
h1 {letter-spacing: -0.04em; font-size: 2.4rem !important; font-weight: 750 !important; color: #14202d;}
h2,h3 {letter-spacing: -0.025em; color: #192635;}
[data-testid="stCaptionContainer"] {color: #6d7885;}
[data-testid="stMetric"] {background: white; border: 1px solid #d6dce0; border-radius: 10px; padding: 12px 18px;}
[data-testid="stMetricLabel"] {color: #697784;}
[data-testid="stMetricValue"] {font-size: 1.75rem; color: #172331; font-weight: 650;}
[data-testid="stSidebar"] {background: linear-gradient(160deg,#0c1c2c,#102438); min-width:250px; max-width:280px;}
[data-testid="stSidebar"] h3, [data-testid="stSidebar"] p, [data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"], [data-testid="stSidebar"] summary {color: #d6e0ec !important;}
[data-testid="stSidebar"] [data-baseweb="select"] > div, [data-testid="stSidebar"] [data-baseweb="input"] {background: #1a3046; color: #f3f7fc; border-color: #334b61;}
[data-testid="stSidebar"] input {color: #f3f7fc;}
[data-testid="stSidebar"] hr {border-color: #32475c;}
[data-testid="stSidebar"] a {color: #c8d6e6; text-decoration: none;}
.calclens-brand {display:flex; align-items:center; gap:12px; color:#fff; font-size:27px; font-weight:650; letter-spacing:-.04em; margin:0 0 24px;}
.calclens-mark {color:#ddb866; font-size:37px; line-height:1;}
.calclens-nav a {display:block; padding:12px 14px; border-radius:8px; margin:3px 0; font-size:14px;}
.calclens-nav a:first-child {background:#263c51; color:white !important;}
.calclens-demo {background:#fff2d9; color:#715124; border:1px solid #ead6b3; border-radius:8px; padding:13px 16px; margin:16px 0 20px; font-size:14px;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius:10px;}
</style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown('<div class="calclens-brand"><span class="calclens-mark">◎</span>CalcLens</div>', unsafe_allow_html=True)
    language = st.selectbox("Language / 언어", ["한국어", "English"], key="language")
ko = language == "한국어"
def t(korean: str, english: str) -> str:
    return korean if ko else english

with st.sidebar:
    st.caption(t("2차원 물질 · 계산 전 구조 확인", "2D materials · geometry before calculation"))
    st.divider()
    source = st.radio(t("1. 구조 선택", "1. Choose a structure"), ["examples", "upload"], format_func=lambda value: t("예제로 시작", "Try an example") if value == "examples" else t("CIF 파일 열기", "Open a CIF file"), key="source")
    names = {
        "graphene.cif": t("그래핀 · 단일 원자층", "Graphene · single atomic plane"),
        "hbn.cif": t("h-BN · 단일 원자층", "h-BN · single atomic plane"),
        "mos2.cif": t("MoS₂ · 세 원자 평면", "MoS₂ · three atomic planes"),
        "graphene_duplicate.cif": t("이상 예제 · 원자 중복", "Deliberate defect · duplicate site"),
        "mos2_wrapped.cif": t("MoS₂ · 셀 경계를 넘는 층", "MoS₂ · layer across cell boundary"),
        "partial_occupancy.cif": t("미지원 예제 · 부분 점유", "Unsupported example · partial occupancy"),
    }
    data = None
    filename = "structure.cif"
    if source == "examples":
        filename = st.selectbox(t("예제 구조", "Example structure"), list(names), format_func=names.get, key="example")
        data = (ROOT / "examples" / filename).read_bytes()
        st.caption(t("직접 생성한 이상화된 기하 예제입니다. 실험 구조나 최적화 결과가 아닙니다.", "These are generated idealized geometries, not experimental structures or relaxed results."))
    else:
        uploaded = st.file_uploader(t("CIF 파일 · 최대 2 MiB", "CIF file · maximum 2 MiB"), type=["cif"], max_upload_size=2, key="cif_upload")
        if uploaded is not None:
            data = uploaded.getvalue()
            filename = uploaded.name
        st.caption(t("이 앱을 내 컴퓨터에서 실행하면 파일은 해당 컴퓨터에서 처리됩니다. 서버에 배포된 앱에서는 파일이 그 서버로 전송됩니다.", "When you run this app locally, files are processed on your computer. On a hosted deployment, uploads are sent to that server."))
    st.divider()
    threshold = st.number_input(t("2. 짧은 거리 표시 기준 / Å", "2. Short-distance flag / Å"), min_value=0.1, max_value=3.0, value=1.0, step=0.1, key="threshold")
    st.caption(t("모든 원소에 같은 기준을 적용합니다. 결합 길이의 적절성이나 안정성을 판정하지 않습니다.", "One cutoff applies to all elements. It does not judge bond lengths or stability."))
    with st.expander(t("지원 범위", "Supported scope")):
        st.write(t("단일 CIF 블록, P1 명시적 원자 좌표, 완전 점유, 400개 이하 원자. c축은 a·b 평면에 수직이어야 합니다. 대칭 확장과 무질서는 지원하지 않습니다.", "One CIF block, explicit P1 sites, full occupancy, up to 400 sites. The c axis must be normal to the a/b plane. Symmetry expansion and disorder are unsupported."))

st.caption(t("계산화학을 위한 작은 구조 점검 도구", "A small structure inspection tool for computational chemistry"))
st.title("CalcLens")
st.markdown(t("**계산을 시작하기 전, 원자 위치와 층 사이 공간을 살펴보세요.**", "**Inspect atomic positions and the space between layers before you calculate.**"))
st.caption(t("기하학적 점검입니다. 물질의 안정성, 계산의 정확성, 진공 간격의 충분성을 보장하지 않습니다.", "Geometry inspection only. This does not establish material stability, calculation accuracy, or sufficient vacuum."))

if data is None:
    st.info(t("왼쪽에서 CIF 파일을 열거나 공개 예제를 선택하세요.", "Open a CIF file or choose a public example in the sidebar."))
    st.stop()
if len(data) > MAX_BYTES:
    st.error(t("파일이 2 MiB를 초과합니다. 더 작은 CIF를 사용하세요.", "File exceeds 2 MiB. Please use a smaller CIF."))
    st.stop()
try:
    report = analyze_cif(data, short_distance=float(threshold))
except (UnsupportedStructure, ValueError) as exc:
    st.error(t("이 구조는 현재 지원 범위에서 해석할 수 없습니다.", "This structure cannot be interpreted within the supported scope."))
    st.write(str(exc))
    st.info(t("완전 점유의 P1 원자 목록인지, c축이 층에 수직인지 확인하세요. 다른 구조는 ASE나 pymatgen 등에서 검토 후 준비해 주세요.", "Check for explicit fully occupied P1 sites and a c axis normal to the layer. Prepare other structures after reviewing them with tools such as ASE or pymatgen."))
    st.stop()

metrics = report["metrics"]
st.divider()
st.subheader(f"{report['formula']} · {report['atom_count']} " + t("개 원자", "sites"))
st.caption(filename)
cols = st.columns(4)
values = [
    (t("가장 짧은 주기적 거리", "Shortest periodic distance"), metrics["minimum_distance_angstrom"]),
    (t("원자핵 위치 기준 층 두께", "Nuclear-span thickness"), metrics["nuclei_thickness_angstrom"]),
    (t("원자핵 사이 최대 빈 간격", "Largest nuclear gap"), metrics["nuclei_gap_angstrom"]),
    (t("셀의 수직 높이", "Cell normal height"), metrics["c_height_angstrom"]),
]
for col, (label, value) in zip(cols, values):
    col.metric(label, "—" if value is None else f"{value:.3f} Å")
st.caption(t("간격은 원자핵 좌표 사이의 거리이며 전자밀도 경계의 진공 폭이 아닙니다. 단일 원자 평면의 두께는 이 정의에서 0 Å입니다.", "The gap is measured between nuclear coordinates, not electron-density boundaries. A single atomic plane has zero thickness under this definition."))

issues = report.get("issues", [])
severe = [item for item in issues if item["severity"] in ("error", "warning")]
if severe:
    st.warning(t(f"확인할 항목 {len(severe)}개가 있습니다. 아래 점검 내용을 읽어 주세요.", f"{len(severe)} item(s) need review. Read the inspection notes below."))
else:
    st.info(t("선택한 거리 기준에서 큰 경고가 검출되지 않았습니다. 계산 조건의 검증은 별도로 필요합니다.", "No major flags were detected at the selected distance cutoff. Calculation settings still require independent validation."))

left, right = st.columns([1.55, 1], gap="large")
with left:
    st.markdown("### " + t("원자 구조", "Atomic structure"))
    controls = st.columns(2)
    repeats = controls[0].selectbox(t("평면 내 표시 반복", "In-plane display repeats"), [1, 2, 3], index=1, format_func=lambda value: f"{value} × {value}", key="repeats")
    show_cell = controls[1].checkbox(t("입력 셀 전체 보기", "Show full input cell"), value=False, key="show_cell")
    st.plotly_chart(structure_figure(report, repeats, show_cell, ko), use_container_width=True, key="structure_plot", config={"displaylogo": False})
    st.caption(t("드래그로 회전하고 스크롤로 확대합니다. 원자 크기는 표시용이며 결합선은 추정하지 않습니다. 반복은 시각화에만 적용됩니다.", "Drag to rotate and scroll to zoom. Marker sizes are visual only; no bonds are inferred. Repetition affects the display only."))
with right:
    st.markdown("### " + t("층과 빈 공간", "Layer and empty space"))
    st.plotly_chart(profile_figure(report, ko), use_container_width=True, key="profile_plot", config={"displayModeBar": False})
    st.caption(t("연한 초록 영역: c 방향에서 원자핵이 없는 가장 큰 순환 간격. 셀 경계를 가로지르면 두 부분으로 표시됩니다.", "Pale green: the largest cyclic interval without nuclei along c. A gap crossing the cell boundary appears in two pieces."))
    st.info(t("진공 간격을 늘리며 에너지·힘·관심 물성이 수렴하는지 확인해야 합니다. 이 숫자만으로 진공이 충분하다고 판단할 수 없습니다.", "Increase vacuum and check convergence of energy, forces, and target properties. This number alone cannot establish sufficient vacuum."))
    st.caption(t("층을 자르는 위치는 가장 큰 빈 간격으로 정합니다. 다층 구조와 벌크는 이 방법만으로 신뢰성 있게 구분할 수 없습니다.", "The largest empty gap defines where the layer is unwrapped. This method cannot reliably distinguish multilayers from bulk."))

notes, contacts, details = st.tabs([t("점검 내용", "Inspection notes"), t("짧은 거리", "Short contacts"), t("좌표 · 보고서", "Coordinates · report")])
with notes:
    issue_ko = {
        "OVERLAPPING_SITES": "같은 위치 또는 주기적으로 같은 위치에 있는 원자가 있습니다. 입력 원자 목록을 확인하세요.",
        "SHORT_DISTANCE": "설정한 기준보다 가까운 원자 쌍이 있습니다. 좌표와 단위를 확인하세요. 원소별 결합 판정은 아닙니다.",
        "SELF_IMAGE_CONTACT": "원자가 자신의 주기적 복사본과 너무 가깝습니다. 셀 크기와 단위를 확인하세요.",
        "AMBIGUOUS_SLAB": "빈 간격이 작거나 셀 높이의 절반 이하입니다. 고립된 단일 층이라고 해석하기 어렵습니다.",
        "MULTIPLE_LARGE_GAPS": "큰 빈 간격이 여러 개 있습니다. 다층 구조나 여러 슬래브가 포함됐는지 확인하세요.",
        "GEOMETRY_ONLY": "원자핵 좌표와 셀의 기하만 측정합니다. 결합, 안정성, 실제 차원성 또는 계산 정확성을 검증하지 않습니다.",
        "VACUUM_CONVERGENCE": "원자핵 사이 간격은 전자밀도가 없는 진공 폭과 다릅니다. 진공의 충분성은 계산별 수렴 검증이 필요합니다.",
        "ASSUMED_FULL_OCCUPANCY": "점유율이 생략되어 모든 원자가 완전 점유라고 가정했습니다.",
    }
    for item in issues:
        explanation = issue_ko.get(item["code"], item["message"]) if ko else item["message"]
        message = f"**{item['code']}** — {explanation}"
        if item["severity"] == "error":
            st.error(message)
        elif item["severity"] == "warning":
            st.warning(message)
        else:
            st.info(message)
    if not issues:
        st.write(t("보고된 추가 항목이 없습니다.", "No additional issues were reported."))
    st.caption(t("진단 코드는 JSON 보고서와 동일합니다. 원문 상세 메시지는 보고서에서 확인할 수 있습니다.", "Diagnostic codes match the JSON report, which contains the full original messages."))
    with st.expander(t("해석의 전제와 한계", "Assumptions and limitations")):
        for text in report.get("assumptions", []) + report.get("limitations", []):
            st.write("• " + text)
with contacts:
    if report.get("short_contacts_truncated"):
        st.warning(t(f"총 {report['short_contact_count']}개 중 처음 {len(report['short_contacts'])}개만 표시합니다. JSON도 같은 수의 상세 항목을 담습니다.", f"Showing the first {len(report['short_contacts'])} of {report['short_contact_count']} contacts. JSON contains the same limited detail list."))
    rows = [{t("원자 1", "Site 1"): item["i"] + 1, t("원자 2", "Site 2"): item["j"] + 1, t("거리 / Å", "Distance / Å"): round(item["distance_angstrom"], 6), t("주기 이동 [a,b,c]", "Image shift [a,b,c]"): str(item["shift"]), t("자기 주기상", "Self image"): item["is_self_image"]} for item in report.get("short_contacts", [])]
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.write(t("설정한 기준보다 짧은 거리가 없습니다.", "No distances fall below the selected cutoff."))
    st.caption(t("번호는 입력 원자 목록의 1번부터 표시합니다. JSON의 원자 인덱스는 0부터 시작합니다.", "Displayed site numbers start at 1. Atom indexes in JSON start at 0."))
with details:
    positions = [{t("원자", "Site"): i + 1, t("원소", "Element"): element, "x / Å": p[0], "y / Å": p[1], "z / Å": p[2]} for i, (element, p) in enumerate(zip(report["elements"], report["positions"]))]
    st.dataframe(positions, hide_index=True, use_container_width=True)
    st.download_button(t("JSON 보고서 내려받기", "Download JSON report"), data=json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), file_name=f"{Path(filename).stem}_preflight.json", mime="application/json", key="download_report")
st.divider()
st.caption(t("CalcLens · 무료 개인·학교·사업체 내부 이용 · 프로그램 판매와 유료 서비스 제공은 사전 허락 필요", "CalcLens · Free personal, academic and internal business use · Selling the software or paid services requires prior permission"))
