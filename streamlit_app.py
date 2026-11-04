"""CalcLens: a local bilingual CIF geometry inspection workspace."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

import streamlit as st

from slab_preflight.core import UnsupportedStructure, analyze_cif
from slab_preflight.plotting import profile_figure, structure_figure
from slab_preflight.reporting import report_csv

ROOT = Path(__file__).resolve().parent
MAX_BYTES = 2 * 1024 * 1024
st.set_page_config(page_title="CalcLens", page_icon="🔬", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
.stApp {background:#faf8f5; color:#172331;}
.block-container {max-width:1600px; padding:2.1rem 1.6rem 2rem;}
[data-testid="stHeader"] {background:rgba(250,248,245,.96);}
h1 {letter-spacing:-.045em; font-size:2.35rem !important; font-weight:750 !important; color:#15222f; padding-top:0 !important;}
h2,h3 {letter-spacing:-.025em; color:#192635;}
h3 {font-size:1.12rem !important;}
[data-testid="stCaptionContainer"] {color:#6d7885;}
[data-testid="stMetric"] {background:white; border:1px solid #d2d9dd; border-radius:10px; padding:12px 18px;}
[data-testid="stMetricLabel"] {color:#697784; font-size:13px;}
[data-testid="stMetricValue"] {font-size:1.7rem; color:#172331; font-weight:650;}
[data-testid="stSidebar"] {background:linear-gradient(160deg,#0b1929,#102438); min-width:250px; max-width:280px;}
[data-testid="stSidebar"] h3,[data-testid="stSidebar"] p,[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],[data-testid="stSidebar"] summary {color:#d6e0ec !important;}
[data-testid="stSidebar"] [data-baseweb="select"] > div,[data-testid="stSidebar"] [data-baseweb="input"] {background:#1a3046; color:#f3f7fc; border-color:#334b61;}
[data-testid="stSidebar"] input {color:#172331 !important;}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {color:#172331 !important;}
#overview, #review-checks, #method-notes {scroll-margin-top:5rem;}
[data-testid="stSidebar"] hr {border-color:#32475c;}
[data-testid="stSidebar"] a {color:#c8d6e6; text-decoration:none;}
[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {background:#f3f6fa;}
.calclens-brand {display:flex; align-items:center; gap:12px; color:white; font-size:27px; font-weight:650; letter-spacing:-.04em; margin:0 0 20px;}
.calclens-mark {color:#d9b36d; font-size:37px; line-height:1;}
.calclens-nav a {display:block; padding:11px 14px; border-radius:8px; margin:3px 0; font-size:14px;}
.calclens-nav a:first-child {background:#263c51; color:white !important;}
.calclens-demo {background:#fff2d9; color:#735325; border:1px solid #ead6b3; border-radius:8px; padding:11px 15px; margin:5px 0 18px; font-size:13px;}
.st-key-viewer_card,.st-key-review_card,.st-key-details_card {background:white; border-radius:10px;}
[data-testid="stVerticalBlockBorderWrapper"] > div {border-radius:10px;}
.st-key-review_focus label {padding:8px 9px; border:1px solid #e0e5e8; border-radius:7px; margin-bottom:4px; width:100%;}
.st-key-review_focus [data-testid="stMarkdownContainer"] p {font-size:13px;}
.st-key-review_focus [data-testid="stRadio"] > div {gap:0;}
.stButton button,.stDownloadButton button {border-radius:7px;}
</style>""", unsafe_allow_html=True)


def set_source(value: str) -> None:
    st.session_state["source"] = value


def set_sample_axis() -> None:
    sample = st.session_state["example"]
    st.session_state["normal_axis"] = "a" if "_a_normal" in sample else "b" if "_b_normal" in sample else "c"


header = st.columns([5.4, 1.25, 1.25, 1.35], vertical_alignment="center")
language = header[3].selectbox("Language / 언어", ["한국어", "English"], key="language", label_visibility="collapsed")
ko = language == "한국어"


def t(korean: str, english: str) -> str:
    return korean if ko else english


def sync_radio(widget_key: str, logical_key: str) -> None:
    st.session_state[logical_key] = st.session_state[widget_key]


def localized_radio(label: str, options: list[str], *, key: str, **kwargs) -> str:
    """Keep logical choices while remounting translated frontend option labels.

    Streamlit radios serialize their formatted labels. Reusing a frontend ID
    after translating those labels can leave no option visibly checked, even
    though Python still holds the correct choice. Separate language widget IDs
    avoid that mismatch; logical state also survives conditional widget removal.
    """
    logical_value = st.session_state.get(key, options[0])
    if logical_value not in options:
        logical_value = options[0]
    st.session_state[key] = logical_value
    widget_key = f"{key}_{'ko' if ko else 'en'}"
    if key == "review_focus":
        # Review-status labels also change with the sample and cutoff.
        labels = [kwargs.get("format_func", str)(option) for option in options]
        fingerprint = hashlib.sha256("\0".join(labels).encode()).hexdigest()[:10]
        widget_key += f"_{fingerprint}"
    st.session_state[widget_key] = logical_value
    return st.radio(label, options, index=None, key=widget_key,
                    on_change=sync_radio, args=(widget_key, key), **kwargs)


header[0].title(t("구조 개요", "Structure overview"), anchor="overview")
header[1].button(t("CIF 열기", "Open CIF"), on_click=set_source, args=("upload",), key="open_cif", width="stretch")
header[2].button(t("예제 보기", "Try sample"), on_click=set_source, args=("examples",), key="try_sample", width="stretch")
st.caption(t("CalcLens  /  2차원 물질의 계산 전 구조 확인", "CalcLens  /  Pre-calculation geometry review for 2D materials"))

with st.sidebar:
    st.markdown('<div class="calclens-brand"><span class="calclens-mark">◎</span>CalcLens</div>', unsafe_allow_html=True)
    st.markdown('<div class="calclens-nav">' + f'<a href="#overview">▦ &nbsp; {t("구조 개요", "Overview")}</a><a href="#review-checks">☷ &nbsp; {t("점검 항목", "Review checks")}</a><a href="#method-notes">◇ &nbsp; {t("방법과 한계", "Method notes")}</a></div>', unsafe_allow_html=True)
    st.divider()
    source = localized_radio(t("구조 불러오기", "Load structure"), ["examples", "upload"], format_func=lambda value: t("공개 예제", "Public examples") if value == "examples" else t("내 CIF 파일", "My CIF file"), key="source")
    names = {
        "graphene.cif": t("그래핀 · 단일 원자층", "Graphene · single plane"),
        "hbn.cif": t("h-BN · 단일 원자층", "h-BN · single plane"),
        "mos2.cif": t("MoS₂ · 세 원자 평면", "MoS₂ · three atomic planes"),
        "mos2_a_normal.cif": t("MoS₂ · a축 수직 방향", "MoS₂ · a-axis normal"),
        "mos2_b_normal.cif": t("MoS₂ · b축 수직 방향", "MoS₂ · b-axis normal"),
        "graphene_duplicate.cif": t("이상 예제 · 원자 중복", "Defect · duplicate site"),
        "graphene_short_contact.cif": t("이상 예제 · 짧은 거리", "Defect · short contact"),
        "graphene_boundary_duplicate.cif": t("이상 예제 · 경계 중복", "Defect · boundary duplicate"),
        "tiny_self_image.cif": t("이상 예제 · 자기 주기상", "Defect · close self image"),
        "mos2_wrapped.cif": t("MoS₂ · 경계를 넘는 층", "MoS₂ · wrapped layer"),
        "bilayer_graphene.cif": t("검토 예제 · 두 원자층", "Review · two atomic planes"),
        "partial_occupancy.cif": t("미지원 · 부분 점유", "Unsupported · partial occupancy"),
    }
    data = None
    filename = "structure.cif"
    if source == "examples":
        filename = st.selectbox(t("예제 구조", "Example structure"), list(names), format_func=names.get, key="example", on_change=set_sample_axis)
        data = (ROOT / "examples" / filename).read_bytes()
    else:
        uploaded = st.file_uploader(t("CIF · 최대 2 MiB", "CIF · maximum 2 MiB"), type=["cif"], max_upload_size=2, key="cif_upload")
        if uploaded is not None:
            data = uploaded.getvalue()
            filename = uploaded.name
        st.caption(t("로컬 실행 시 내 컴퓨터에서 처리합니다. 호스팅된 앱에서는 파일이 해당 서버로 전송됩니다.", "Local runs process files on your computer. Hosted apps send uploads to their server."))
    st.divider()
    st.caption(t("측정 조건", "MEASUREMENT SETTINGS"))
    normal_axis = st.selectbox(t("층의 수직 방향", "Candidate layer normal"), ["c", "a", "b"], key="normal_axis")
    st.caption(t("선택 축은 나머지 두 축에 수직이어야 합니다. 실제 층 방향은 사용자가 확인합니다.", "The selected axis must be perpendicular to the other two. You must verify the physical layer direction."))
    threshold = st.number_input(t("짧은 거리 기준 / Å", "Short-distance cutoff / Å"), min_value=0.1, max_value=3.0, value=1.0, step=0.1, key="threshold")
    st.caption(t("원소와 무관한 표시 기준입니다. 결합이나 안정성의 판정 기준이 아닙니다.", "An element-independent flag, not a bond or stability criterion."))
    st.divider()
    st.caption(t("프로젝트 · CIF 구조 점검", "PROJECT · CIF GEOMETRY"))
    st.markdown("[GitHub ↗](https://github.com/a123qsd/calclens)")

if source == "examples":
    banner = t("예제 모드 · 직접 생성한 이상화된 기하 구조입니다. 실험 자료나 최적화 결과가 아닙니다.", "Sample mode · Generated idealized geometry, not experimental data or a relaxed result.")
    st.markdown(f'<div class="calclens-demo">◈ &nbsp; {html.escape(banner)}</div>', unsafe_allow_html=True)
else:
    st.caption(t("입력 파일의 좌표를 분석하며 원자를 삭제하거나 구조를 자동 보정하지 않습니다.", "Input coordinates are inspected without deleting sites or automatically repairing the structure."))

if data is None:
    st.info(t("왼쪽에서 CIF를 열거나 위의 예제 보기 버튼으로 시작하세요.", "Open a CIF in the sidebar, or use Try sample above."))
    st.stop()
if len(data) > MAX_BYTES:
    st.error(t("파일이 2 MiB를 초과합니다. 더 작은 CIF를 사용하세요.", "File exceeds 2 MiB. Please use a smaller CIF."))
    st.stop()
try:
    report = analyze_cif(data, short_distance=float(threshold), normal_axis=normal_axis)
except (UnsupportedStructure, ValueError) as exc:
    st.error(t("이 입력은 현재 지원 범위에서 해석할 수 없습니다.", "This input cannot be interpreted within the supported scope."))
    st.write(str(exc))
    st.info(t("단일 CIF 1.1 블록, 명시적 P1 원자 목록, 완전 점유, 원소와 분율 좌표, 셀 정보가 필요합니다. 선택한 수직 축도 확인하세요. 누락 정보를 추측하거나 원자를 삭제하지 않습니다.", "A single CIF 1.1 block, explicit P1 sites, full occupancy, elements, fractional coordinates and cell data are required. Check the selected normal axis too. Missing information is not guessed and sites are not deleted."))
    st.caption(t("다른 형식은 ASE 또는 pymatgen 등에서 사람이 검토하고 준비해 주세요. 부분 점유를 임의로 1로 바꾸지 마세요.", "Prepare other structures after human review in tools such as ASE or pymatgen. Do not arbitrarily replace partial occupancies with 1."))
    st.stop()

metrics = report["metrics"]
issues = report.get("issues", [])
issue_by_code = {item["code"]: item for item in issues}
criteria = report.get("criteria", {})
overlap_tolerance = criteria.get("overlap_tolerance_angstrom", 1e-5)
gap_review = report.get("gap_review_required", "AMBIGUOUS_SLAB" in issue_by_code or "MULTIPLE_LARGE_GAPS" in issue_by_code)
summary, cell_summary = st.columns([2, 1])
summary.subheader(f"{report['formula']}  ·  {report['atom_count']} " + t("개 원자", "sites"))
cell_summary.caption(t(f"수직 방향 {normal_axis} · 셀 높이 {metrics['normal_height_angstrom']:.3f} Å", f"Normal {normal_axis} · cell height {metrics['normal_height_angstrom']:.3f} Å"))
st.caption(filename)
cols = st.columns(3)
values = [
    (t("가장 짧은 주기적 거리", "Shortest periodic distance"), metrics["minimum_distance_angstrom"]),
    (t("원자핵 위치 기준 층 두께", "Nuclear-span thickness"), metrics["nuclei_thickness_angstrom"]),
    (t("슬래브 핵 간격 · 해석 검토 필요" if gap_review else "슬래브 핵 간격 후보", "Nuclear gap · review needed" if gap_review else "Candidate nuclear gap"), metrics["nuclei_gap_angstrom"]),
]
for col, (label, value) in zip(cols, values):
    col.metric(label, "—" if value is None else f"{value:.3f} Å")
st.caption(t("두께·간격은 원자핵 위치 기준입니다. 단일 원자 평면의 두께는 0 Å이며, 핵 간격은 전자밀도 경계의 진공 폭이 아닙니다.", "Thickness and gap refer to nuclear positions. A single atomic plane has zero nuclear-span thickness; this gap is not an electron-density vacuum width."))

issue_ko = {
    "OVERLAPPING_SITES": "같은 위치 또는 주기적으로 같은 위치에 있는 원자가 있습니다. 입력 원자 목록을 확인하세요.",
    "SHORT_DISTANCE": "기준보다 가까운 원자 쌍이 있습니다. 좌표와 단위를 확인하세요. 원소별 결합 판정은 아닙니다.",
    "SELF_IMAGE_CONTACT": "원자가 자신의 주기적 복사본과 가깝습니다. 셀 크기와 단위를 확인하세요.",
    "AMBIGUOUS_SLAB": "빈 간격이 작거나 셀 높이의 절반 이하입니다. 고립된 단일 층이라는 해석을 검토해야 합니다.",
    "MULTIPLE_LARGE_GAPS": "큰 빈 간격이 여러 개 있습니다. 다층 구조나 여러 슬래브가 포함됐는지 확인하세요.",
    "GEOMETRY_ONLY": "원자핵과 셀의 기하만 측정합니다. 결합, 안정성, 실제 차원성 또는 계산 정확성을 검증하지 않습니다.",
    "VACUUM_CONVERGENCE": "핵 간격은 전자밀도가 없는 진공 폭과 다릅니다. 진공의 충분성은 계산별 수렴 검증이 필요합니다.",
    "ASSUMED_FULL_OCCUPANCY": "점유율이 생략되어 모든 명시적 원자가 완전 점유라고 가정했습니다. 원본을 확인하세요.",
}

def explanation(item: dict) -> str:
    return issue_ko.get(item["code"], item["message"]) if ko else item["message"]


# Render the review controls first, so their current selection determines the
# figure in the left column during this same run.
viewer, review = st.columns([1.9, 1], gap="medium")
with review, st.container(border=True, key="review_card"):
    st.subheader(t("점검 항목", "Review checks"), anchor="review-checks")
    st.caption(t("항목을 선택하면 관련 원자나 간격이 강조됩니다.", "Select a check to highlight its sites or gap."))
    overlapping = "OVERLAPPING_SITES" in issue_by_code
    close = "SHORT_DISTANCE" in issue_by_code or "SELF_IMAGE_CONTACT" in issue_by_code
    assumed = "ASSUMED_FULL_OCCUPANCY" in issue_by_code
    choices = {
        "overview": t("전체 구조 보기", "Show full structure"),
        "overlap": t("● 원자 겹침 · 확인 필요" if overlapping else "○ 원자 겹침 · 검출 없음", "● Overlap · needs review" if overlapping else "○ Overlap · none detected"),
        "short": t("● 짧은 거리 · 확인 필요" if close else "○ 짧은 거리 · 검출 없음", "● Short distance · needs review" if close else "○ Short distance · none detected"),
        "gap": t("● 층·핵 간격 · 해석 검토 필요" if gap_review else "◐ 층·핵 간격 · 수렴 검증 필요", "● Layer/gap · interpretation needed" if gap_review else "◐ Layer/gap · convergence needed"),
        "metadata": t("● 입력 정보 · 점유율 생략" if assumed else "○ 필수 입력 정보 · 읽음", "● Input data · occupancy omitted" if assumed else "○ Required input fields · read"),
    }
    with st.container(key="review_focus"):
        focus = localized_radio(t("강조할 점검 항목", "Check to highlight"), list(choices), format_func=choices.get, key="review_focus", label_visibility="collapsed")
    related_codes = {
        "overview": [], "overlap": ["OVERLAPPING_SITES"], "short": ["SHORT_DISTANCE", "SELF_IMAGE_CONTACT"],
        "gap": ["AMBIGUOUS_SLAB", "MULTIPLE_LARGE_GAPS", "VACUUM_CONVERGENCE"], "metadata": ["ASSUMED_FULL_OCCUPANCY"],
    }[focus]
    related_issues = [issue_by_code[code] for code in related_codes if code in issue_by_code]
    highlighted_atoms = sorted({i for item in related_issues for i in item.get("atom_indices", [])})
    selected_contact = None
    if focus in ("overlap", "short"):
        contacts = report["short_contacts"]
        if focus == "overlap":
            contacts = [item for item in contacts if not item["is_self_image"] and item["distance_angstrom"] <= overlap_tolerance]
        if contacts:
            def contact_label(index: int) -> str:
                item = contacts[index]
                return f"{report['elements'][item['i']]}{item['i']+1}–{report['elements'][item['j']]}{item['j']+1} · {item['distance_angstrom']:.4f} Å"
            contact_index = st.selectbox(t("강조할 원자 쌍", "Contact to highlight"), list(range(len(contacts))), format_func=contact_label, key=f"contact_{focus}")
            selected_contact = contacts[contact_index]
            highlighted_atoms = sorted({selected_contact["i"], selected_contact["j"]})
            st.caption(t(f"상대 원자의 주기 이동 [a,b,c]: {selected_contact['shift']}", f"Partner image shift [a,b,c]: {selected_contact['shift']}"))
        else:
            st.caption(t("이 항목에 해당하는 거리 기록이 없습니다.", "No contact records match this check."))
    for item in related_issues:
        if item["severity"] == "error":
            st.error(explanation(item))
        elif item["severity"] == "warning":
            st.warning(explanation(item))
        else:
            st.caption(explanation(item))
    if focus == "metadata" and not assumed:
        st.caption(t("셀·원소·분율 좌표·점유율이 지원 범위에서 읽혔습니다. 화학적 타당성을 검증했다는 뜻은 아닙니다.", "Cell, elements, fractional coordinates and occupancies were read within scope. This does not verify chemical validity."))
    if focus == "overview":
        flag_count = sum(item["severity"] in ("error", "warning") for item in issues)
        st.caption(t(f"검토 경고 {flag_count}개 · 겹침 기준 {overlap_tolerance:g} Å", f"{flag_count} review flags · overlap tolerance {overlap_tolerance:g} Å"))
    st.markdown("**" + t(f"{normal_axis} 방향 원자 분포", f"Nuclei along {normal_axis}") + "**")
    st.plotly_chart(profile_figure(report, ko, highlight_gap=focus == "gap"), width="stretch", key="profile_plot", config={"displayModeBar": False})
    st.caption(t("색 영역은 최대 순환 핵 간격입니다. 선택 축과 실제 층 방향이 맞는지 확인하세요.", "Shading marks the largest cyclic nuclear gap. Check that the selected axis matches the physical layer normal."))

with viewer, st.container(border=True, key="viewer_card"):
    st.subheader(t("원자 구조와 단위 셀", "Atomic structure and unit cell"))
    controls = st.columns([1.2, 1.2, 1.4], vertical_alignment="center")
    repeats = controls[0].selectbox(t("평면 내 표시 반복", "In-plane display repeats"), [1, 2, 3], index=1, format_func=lambda value: f"{value} × {value}", key="repeats")
    show_cell = controls[1].checkbox(t("입력 셀 표시", "Show input cell"), value=True, key="show_cell")
    controls[2].caption(t("드래그: 회전  /  스크롤: 확대", "Drag: rotate  /  Scroll: zoom"))
    st.plotly_chart(structure_figure(report, repeats, show_cell, ko, highlighted_atoms=highlighted_atoms, selected_contact=selected_contact, highlight_gap=focus == "gap"), width="stretch", key="structure_plot", config={"displaylogo": False})
    st.caption(t("실제 Å 좌표 비율입니다. 원자 크기는 표시용이며 결합을 추정하지 않습니다. 반복은 표시만 바꾸며, 강조는 원본 셀과 정확한 주기상 좌표에 적용됩니다.", "Axes retain the actual Å proportions. Marker sizes are visual; bonds are not inferred. Repeats affect display only; highlights use original-cell sites and exact periodic images."))

with st.container(border=True, key="details_card"):
    title, csv_button, json_button = st.columns([3, 1, 1], vertical_alignment="center")
    title.subheader(t("점검 결과와 원자 좌표", "Review results and site data"))
    csv_button.download_button(t("CSV 내보내기", "Export CSV"), data=report_csv(report), file_name=f"{Path(filename).stem}_calclens.csv", mime="text/csv", key="download_csv", width="stretch")
    json_button.download_button(t("JSON 내보내기", "Export JSON"), data=json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), file_name=f"{Path(filename).stem}_calclens.json", mime="application/json", key="download_report", width="stretch")
    contact_tab, coordinate_tab, issue_tab = st.tabs([t("짧은 거리", "Short contacts"), t("원자 좌표", "Site coordinates"), t("모든 진단", "All diagnostics")])
    with contact_tab:
        if report.get("short_contacts_truncated"):
            st.warning(t(f"총 {report['short_contact_count']}개 중 처음 {len(report['short_contacts'])}개만 표시합니다. 내보내기도 같은 상세 항목 수를 담습니다.", f"Showing the first {len(report['short_contacts'])} of {report['short_contact_count']} contacts. Exports contain the same limited detail list."))
        rows = [{t("원자 쌍", "Element pair"): f"{report['elements'][item['i']]}{item['i']+1}–{report['elements'][item['j']]}{item['j']+1}", t("거리 / Å", "Distance / Å"): round(item["distance_angstrom"], 6), t("기준 / Å", "Cutoff / Å"): float(threshold), t("주기 이동 [a,b,c]", "Image shift [a,b,c]"): str(item["shift"]), t("자기 주기상", "Self image"): item["is_self_image"]} for item in report.get("short_contacts", [])]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.write(t(f"{threshold:.2f} Å 미만의 거리 기록이 없습니다. 이 결과가 구조의 타당성을 보장하지는 않습니다.", f"No contact records below {threshold:.2f} Å. This does not establish structural validity."))
        st.caption(t("화면의 원자 번호는 1부터, JSON 인덱스는 0부터 시작합니다. CSV/JSON에는 선택 축과 점검 기준도 포함됩니다.", "Displayed site numbers start at 1; JSON indexes start at 0. CSV/JSON include the selected axis and screening criteria."))
    with coordinate_tab:
        positions = [{t("원자", "Site"): i + 1, t("원소", "Element"): element, "x / Å": p[0], "y / Å": p[1], "z / Å": p[2]} for i, (element, p) in enumerate(zip(report["elements"], report["positions"]))]
        st.dataframe(positions, hide_index=True, width="stretch")
    with issue_tab:
        for item in issues:
            message = f"**{item['code']}** — {explanation(item)}"
            if item["severity"] == "error":
                st.error(message)
            elif item["severity"] == "warning":
                st.warning(message)
            else:
                st.caption(message)

st.markdown('<div id="method-notes"></div>', unsafe_allow_html=True)
with st.expander(t("방법과 한계 · 계산 전에 읽어 주세요", "Method notes · read before calculating")):
    st.markdown(t("**지원 범위:** 단일 CIF 1.1 블록, 명시적 P1 원자 좌표, 완전 점유, 1–400개 원자, 최대 2 MiB. 선택 축은 나머지 두 축에 수직이어야 합니다. 대칭 확장, 부분 점유와 무질서는 지원하지 않습니다.", "**Scope:** one CIF 1.1 block, explicit P1 sites, full occupancy, 1–400 sites, at most 2 MiB. The selected axis must be normal to the other two. Symmetry expansion, partial occupancy and disorder are unsupported."))
    st.write(t("주기적 최소 거리는 a·b·c 전체 경계에서 계산합니다. 핵 간격은 선택 축의 가장 큰 순환 빈 간격이고 두께는 셀 높이에서 그 간격을 뺀 값입니다. 다층·벌크·분자 구조에서는 물리적 해석을 별도로 검토해야 합니다.", "Periodic minimum distances use all three cell directions. The nuclear gap is the largest cyclic empty interval along the selected axis; thickness is cell height minus that gap. Multilayers, bulk and molecules need separate physical interpretation."))
    st.write(t("진공을 늘리며 에너지·힘·관심 물성이 수렴하는지 검증해야 합니다. 안정성, 결합, 에너지, 힘, 전자구조 또는 계산 정확성은 이 도구로 판정하지 않습니다. 경고가 없다는 것은 검증 통과가 아닙니다.", "Increase vacuum and check convergence of energy, forces and target properties. This tool does not establish stability, bonding, energy, forces, electronic structure or calculation accuracy. An absence of flags is not validation."))
    st.json(report.get("criteria", {}), expanded=False)
st.caption(t("CalcLens · 무료 개인·학교·사업체 내부 이용 · 프로그램 판매와 유료 서비스 제공은 사전 허락 필요", "CalcLens · Free personal, academic and internal business use · Selling the software or paid services requires prior permission"))
