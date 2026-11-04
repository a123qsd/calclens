"""CalcLens: a local bilingual CIF geometry inspection workspace."""
from __future__ import annotations

import hashlib
import html
import json
import os
from dataclasses import replace
from pathlib import Path

import ase
import streamlit as st

from slab_preflight import __version__
from slab_preflight.batch import MAX_BATCH_FILES, BatchInput, batch_csv, batch_rows
from slab_preflight.core import UnsupportedStructure, analyze_cif
from slab_preflight.plotting import profile_figure, structure_figure
from slab_preflight.project import Project, ProjectError, dumps_project, loads_project
from slab_preflight.provenance import with_provenance
from slab_preflight.review import cached_batch, reconcile_uploads
from slab_preflight.reporting import (
    localized_error_message,
    localized_issue_message,
    localized_report,
    report_csv,
)

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
    if value == "examples":
        set_sample_axis()


def set_sample_axis() -> None:
    sample = st.session_state.get("example", "graphene.cif")
    st.session_state["normal_axis"] = "a" if "_a_normal" in sample else "b" if "_b_normal" in sample else "c"


def show_minimum_pair() -> None:
    st.session_state["review_focus"] = "minimum"


header = st.columns([5.4, 1.25, 1.25, 1.35], vertical_alignment="center")
if "language" not in st.session_state:
    # Launchers choose a default only for a new session. Interactive changes
    # remain authoritative for all later reruns in that session.
    default_language = os.environ.get("CALCLENS_LANGUAGE", "ko").strip().lower()
    st.session_state["language"] = "English" if default_language == "en" else "한국어"
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


def sync_selectbox(widget_key: str, logical_key: str, callback=None) -> None:
    selected = st.session_state[widget_key]
    if selected is None:
        # Ignore a stale clear event from a previously mounted frontend.
        st.session_state[widget_key] = st.session_state[logical_key]
        return
    st.session_state[logical_key] = selected
    if callback is not None:
        callback()


def localized_selectbox(label: str, options: list[str], *, key: str, on_change=None, **kwargs) -> str:
    """Remount translated dropdown labels while keeping the logical choice."""
    logical_value = st.session_state.get(key, options[0])
    if logical_value not in options:
        logical_value = options[0]
    st.session_state[key] = logical_value
    widget_key = f"{key}_{'ko' if ko else 'en'}"
    st.session_state[widget_key] = logical_value
    return st.selectbox(label, options, index=0, key=widget_key,
                        on_change=sync_selectbox, args=(widget_key, key, on_change), **kwargs)


def sync_entry(widget_key: str, entry_source: str, entry_id: str, field: str) -> None:
    """Commit widget edits to durable review state before any source switches."""
    value = st.session_state[widget_key]

    def update(entry):
        if entry.id != entry_id:
            return entry
        changes = {field: value}
        if field in ("normal_axis", "short_distance") and getattr(entry, field) != value:
            changes["reviewed"] = False
        return replace(entry, **changes)

    if entry_source == "batch":
        st.session_state["upload_records"] = [
            (upload, update(entry)) for upload, entry in st.session_state["upload_records"]
        ]
    else:
        st.session_state["project_entries"] = [
            update(entry) for entry in st.session_state["project_entries"]
        ]


header[0].title(t("구조 개요", "Structure overview"), anchor="overview")
header[1].button(t("CIF 열기", "Open CIF"), on_click=set_source, args=("upload",), key="open_cif", width="stretch")
header[2].button(t("예제 보기", "Try sample"), on_click=set_source, args=("examples",), key="try_sample", width="stretch")
st.caption(t("CalcLens  /  2차원 물질의 계산 전 구조 확인", "CalcLens  /  Pre-calculation geometry review for 2D materials"))

with st.sidebar:
    st.markdown('<div class="calclens-brand"><span class="calclens-mark">◎</span>CalcLens</div>', unsafe_allow_html=True)
    st.markdown('<div class="calclens-nav">' + f'<a href="#overview">▦ &nbsp; {t("구조 개요", "Overview")}</a><a href="#review-checks">☷ &nbsp; {t("점검 항목", "Review checks")}</a><a href="#method-notes">◇ &nbsp; {t("방법과 한계", "Method notes")}</a></div>', unsafe_allow_html=True)
    st.divider()
    source_labels = {"examples": t("공개 예제", "Public examples"), "upload": t("내 CIF 파일", "My CIF file"), "batch": t("여러 CIF 비교", "Compare CIF files"), "project": t("저장한 작업 열기", "Open saved work")}
    source = localized_radio(t("구조 불러오기", "Load structure"), list(source_labels), format_func=source_labels.get, key="source")
    # File uploaders cannot be repopulated from Session State. Keep this widget
    # mounted while another source is shown, so a source round trip retains the
    # actual browser upload IDs as well as our independent measurement settings.
    if source != "batch":
        st.markdown("<style>.st-key-batch_upload_holder {display:none;}</style>", unsafe_allow_html=True)
    with st.container(key="batch_upload_holder"):
        uploads = st.file_uploader(t("CIF 여러 개 · 파일당 2 MiB", "Multiple CIFs · 2 MiB per file"), type=["cif"], accept_multiple_files=True, max_upload_size=2, key="batch_upload")
        st.caption(t(f"한 번에 최대 {MAX_BATCH_FILES}개 파일을 비교합니다.", f"Compare up to {MAX_BATCH_FILES} files at a time."))
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
        filename = localized_selectbox(t("예제 구조", "Example structure"), list(names), format_func=names.get, key="example", on_change=set_sample_axis)
        if st.session_state.get("previous_source") != "examples":
            set_sample_axis()
        data = (ROOT / "examples" / filename).read_bytes()
    elif source == "upload":
        uploaded = st.file_uploader(t("CIF · 최대 2 MiB", "CIF · maximum 2 MiB"), type=["cif"], max_upload_size=2, key="cif_upload")
        if uploaded is not None:
            data = uploaded.getvalue()
            filename = uploaded.name
    elif source == "project":
        project_upload = st.file_uploader(t("저장한 작업 · .calclens.json", "Saved work · .calclens.json"), type=["json"], max_upload_size=55, key="project_upload")
        if st.button(t("작업 불러오기", "Open project"), key="load_project", disabled=project_upload is None):
            try:
                project = loads_project(project_upload.getvalue())
            except ProjectError as exc:
                st.error(t("작업 파일을 열 수 없습니다: ", "Cannot open project: ") + str(exc))
            else:
                st.session_state["project_entries"] = project.entries
                st.session_state["project_selected_id"] = project.selected_id
                st.session_state["batch_filter"] = project.filter_mode
                st.session_state["review_focus"] = project.review_focus
                st.session_state["project_versions"] = (project.calclens_version, project.ase_version)
                st.session_state["project_generation"] = st.session_state.get("project_generation", 0) + 1
                for entry in project.entries:
                    for prefix, value in (("batch_axis", entry.normal_axis), ("batch_cutoff", entry.short_distance), ("review_note", entry.note), ("review_done", entry.reviewed)):
                        st.session_state[f"{prefix}_project_{entry.id}"] = value
                st.success(t("저장한 작업을 불러왔습니다.", "Saved work opened."))
        st.caption(t("원본 CIF와 측정 조건·메모를 복원합니다. 결과는 현재 버전으로 계산합니다.", "Restores original CIFs, conditions and notes. Results use the current analysis version."))
    if source != "examples":
        st.caption(t("로컬 실행 시 내 컴퓨터에서 처리합니다. 호스팅된 앱에서는 파일이 해당 서버로 전송됩니다.", "Local runs process files on your computer. Hosted apps send uploads to their server."))
    st.session_state["previous_source"] = source
    st.divider()
    st.caption(t("측정 조건", "MEASUREMENT SETTINGS"))
    normal_axis = st.selectbox(t("층의 수직 방향", "Candidate layer normal"), ["c", "a", "b"], key="normal_axis", disabled=source in ("batch", "project"))
    st.caption(t("선택 축은 나머지 두 축에 수직이어야 합니다. 실제 층 방향은 사용자가 확인합니다.", "The selected axis must be perpendicular to the other two. You must verify the physical layer direction."))
    threshold = st.number_input(t("짧은 거리 기준 / Å", "Short-distance cutoff / Å"), min_value=0.1, max_value=3.0, value=1.0, step=0.1, key="threshold", disabled=source in ("batch", "project"))
    if source in ("batch", "project"):
        st.caption(t("비교 화면의 ‘파일별 측정 조건’에서 각 파일의 축과 기준을 지정하세요.", "Set each file's axis and cutoff under Measurement settings by file."))
    st.caption(t("원소와 무관한 표시 기준입니다. 결합이나 안정성의 판정 기준이 아닙니다.", "An element-independent flag, not a bond or stability criterion."))
    st.divider()
    st.caption(t("프로젝트 · CIF 구조 점검", "PROJECT · CIF GEOMETRY"))
    guide_language = "ko" if ko else "en"
    st.markdown(f"[{t('사용 안내', 'User guide')} ↗](https://github.com/a123qsd/calclens/blob/main/README.{guide_language}.md)")
    st.markdown(f"[{t('다운로드 파일', 'Download files')} ↗](https://github.com/a123qsd/calclens/releases)")
    st.markdown("[GitHub ↗](https://github.com/a123qsd/calclens)")

if source == "examples":
    banner = t("예제 모드 · 직접 생성한 이상화된 기하 구조입니다. 실험 자료나 최적화 결과가 아닙니다.", "Sample mode · Generated idealized geometry, not experimental data or a relaxed result.")
    st.markdown(f'<div class="calclens-demo">◈ &nbsp; {html.escape(banner)}</div>', unsafe_allow_html=True)
else:
    st.caption(t("입력 파일의 좌표를 분석하며 원자를 삭제하거나 구조를 자동 보정하지 않습니다.", "Input coordinates are inspected without deleting sites or automatically repairing the structure."))

report = None
if source in ("batch", "project"):
    st.subheader(t("여러 CIF 비교", "Compare CIF files"))
    if source == "batch":
        if len(uploads) > MAX_BATCH_FILES:
            st.error(t(f"파일을 {MAX_BATCH_FILES}개 이하로 줄여 주세요.", f"Choose no more than {MAX_BATCH_FILES} files."))
            st.stop()
        previous_records = st.session_state.get("upload_records", [])
        records = reconcile_uploads(uploads, previous_records)
        previous_data = {entry.id: entry.data for _, entry in previous_records}
        for _, entry in records:
            if entry.id in previous_data and previous_data[entry.id] != entry.data:
                st.session_state[f"review_done_batch_{entry.id}"] = False
        st.session_state["upload_records"] = records
        entries = [entry for _, entry in records]
    else:
        entries = st.session_state.get("project_entries", [])
        versions = st.session_state.get("project_versions")
        if versions and versions != (__version__, ase.__version__):
            st.warning(t(
                f"저장 당시 버전은 CalcLens {versions[0]} · ASE {versions[1]}입니다. 현재 CalcLens {__version__} · ASE {ase.__version__}로 다시 분석합니다.",
                f"Saved with CalcLens {versions[0]} · ASE {versions[1]}. Reanalyzing with current CalcLens {__version__} · ASE {ase.__version__}.",
            ))
    if not entries:
        st.info(t("왼쪽에서 CIF 파일이나 저장한 작업을 선택하세요.", "Choose CIF files or open saved work in the sidebar."))
        st.stop()
    inputs = []
    updated_entries = []
    with st.expander(t("파일별 측정 조건", "Measurement settings by file"), expanded=True):
        st.caption(t("모든 파일의 기본값은 c축·1.0 Å입니다. 실제 층 방향을 확인하고 파일마다 조정하세요.", "Every file starts at c and 1.0 Å. Verify the physical layer direction and adjust each file."))
        for index, entry in enumerate(entries):
            settings_key = f"{source}_{entry.id}"
            axis_key = f"batch_axis_{settings_key}"
            cutoff_key = f"batch_cutoff_{settings_key}"
            st.session_state[axis_key] = entry.normal_axis
            st.session_state[cutoff_key] = entry.short_distance
            label, axis_col, cutoff_col = st.columns([3, 1, 1.5])
            label.write(f"{index + 1}. {entry.filename}")
            axis = axis_col.selectbox(t("축", "Axis"), ["c", "a", "b"], key=axis_key,
                                      on_change=sync_entry, args=(axis_key, source, entry.id, "normal_axis"))
            cutoff = cutoff_col.number_input(t("기준 / Å", "Cutoff / Å"), min_value=0.1, max_value=3.0, step=0.1, key=cutoff_key,
                                              on_change=sync_entry, args=(cutoff_key, source, entry.id, "short_distance"))
            changed = (axis, float(cutoff)) != (entry.normal_axis, entry.short_distance)
            updated_entries.append(replace(entry, normal_axis=axis, short_distance=float(cutoff),
                                           reviewed=False if changed else entry.reviewed))
            if changed:
                st.session_state[f"review_done_{settings_key}"] = False
            inputs.append(BatchInput(entry.filename, entry.data, axis, float(cutoff)))
    entries = updated_entries

    def keep_entries():
        if source == "batch":
            st.session_state["upload_records"] = [(upload, entry) for (upload, _), entry in zip(records, entries)]
        else:
            st.session_state["project_entries"] = entries

    keep_entries()
    results = cached_batch(inputs, st.session_state.setdefault("analysis_cache", {}))
    batch_language = "ko" if ko else "en"
    filters = {"all": t("전체", "All"), "needs_review": t("검토 필요", "Needs review"), "unsupported": t("입력 오류", "Input errors")}
    filter_mode = localized_radio(t("표시할 파일", "Files to show"), list(filters), key="batch_filter", format_func=filters.get, horizontal=True)
    all_rows = batch_rows(results, "en")
    visible_indices = [i for i, row in enumerate(all_rows)
                       if filter_mode == "all"
                       or (filter_mode == "needs_review" and row["status"] == "review_required")
                       or (filter_mode == "unsupported" and row["status"] == "unsupported")]
    visible_results = [results[i] for i in visible_indices]
    rows = batch_rows(visible_results, batch_language)
    detail_fields = {"formula", "atom_count", "sha256", "calclens_version", "ase_version", "error"} if not ko else {"조성", "원자 수", "SHA-256", "CalcLens 버전", "ASE 버전", "입력 오류"}
    rows = [{key: value for key, value in row.items() if key not in detail_fields} for row in rows]
    # A remounted table discards positional events. The logical selection lives
    # separately as an entry ID, so changed settings/order do not change files.
    fingerprint = hashlib.sha256(json.dumps([
        source, filter_mode, st.session_state.get("project_generation", 0),
        [(entries[i].id, results[i]["sha256"], inputs[i].normal_axis, inputs[i].short_distance)
         for i in visible_indices],
    ]).encode()).hexdigest()[:16]
    selected_key = f"{source}_selected_id"
    ids = [entry.id for entry in entries]
    if st.session_state.get(selected_key) not in ids:
        st.session_state[selected_key] = ids[0]
    table = None
    if rows:
        table = st.dataframe(rows, hide_index=True, width="stretch", on_select="rerun",
                             selection_mode="single-row", key=f"batch_table_{fingerprint}")
        if table.selection.rows:
            selected_row = table.selection.rows[0]
            if 0 <= selected_row < len(visible_indices):
                st.session_state[selected_key] = entries[visible_indices[selected_row]].id
        if st.session_state[selected_key] not in [entries[i].id for i in visible_indices]:
            st.session_state[selected_key] = entries[visible_indices[0]].id
    export_col, save_col = st.columns(2)
    export_col.download_button(t("전체 비교 요약 CSV 내보내기", "Export all comparison CSV"),
                       data=batch_csv(results, batch_language).encode("utf-8-sig" if ko else "utf-8"),
                       file_name=f"calclens_comparison_{batch_language}.csv", mime="text/csv; charset=utf-8", key="download_batch")
    st.caption(t("표의 행을 선택하면 상세 결과를 표시합니다. 조건을 바꿔도 선택한 파일을 유지합니다. no_flags는 경고가 없다는 뜻이며 구조의 타당성을 보장하지 않습니다.", "Select a row for details. Changing conditions keeps the selected file. no_flags means no screening flags, not validated geometry."))
    selected_index = ids.index(st.session_state[selected_key])
    entry = entries[selected_index]
    if visible_indices:
        with st.expander(t("검토 메모와 진행 상황", "Review notes and progress"), expanded=True):
            note_key = f"review_note_{source}_{entry.id}"
            done_key = f"review_done_{source}_{entry.id}"
            st.session_state[note_key] = entry.note
            st.session_state[done_key] = entry.reviewed
            note = st.text_area(t("메모", "Notes"), key=note_key, max_chars=10000,
                                on_change=sync_entry, args=(note_key, source, entry.id, "note"))
            reviewed = st.checkbox(t("검토 완료", "Review complete"), key=done_key,
                                    on_change=sync_entry, args=(done_key, source, entry.id, "reviewed"))
            entries[selected_index] = replace(entry, note=note, reviewed=reviewed)
            keep_entries()
            st.caption(t(f"{sum(item.reviewed for item in entries)}/{len(entries)}개 검토 완료 · 입력이나 측정 조건을 바꾸면 완료 표시가 해제됩니다.", f"{sum(item.reviewed for item in entries)}/{len(entries)} reviewed · Input or measurement changes clear the completion mark."))
    try:
        project_data = dumps_project(Project(entries, selected_id=st.session_state[selected_key],
                                             review_focus=st.session_state.get("review_focus", "overview"),
                                             filter_mode=filter_mode))
    except ProjectError as exc:
        save_col.warning(t("작업을 저장할 수 없습니다: ", "Cannot save project: ") + str(exc))
    else:
        save_col.download_button(t("작업 저장", "Save project"), data=project_data,
                                 file_name="calclens_work.calclens.json", mime="application/json",
                                 key="download_project")
    if not visible_indices:
        st.info(t("이 필터에 해당하는 파일이 없습니다.", "No files match this filter."))
        st.stop()
    selected = results[selected_index]
    filename = selected["filename"]
    data = inputs[selected_index].data
    normal_axis = selected["normal_axis"]
    threshold = selected["short_distance_threshold_angstrom"]
    report = selected["report"]
    st.caption(t("현재 파일: ", "Current file: ") + f"{selected_index + 1}. {filename}")
    with st.expander(t("파일 식별 정보와 분석 조건", "File identity and analysis conditions")):
        st.code(f"SHA-256: {selected['sha256']}", language=None)
        st.write(f"CalcLens {__version__} · ASE {ase.__version__}")
        st.write(t(f"선택 축: {normal_axis} · 짧은 거리 기준: {threshold:g} Å", f"Normal axis: {normal_axis} · Short-distance cutoff: {threshold:g} Å"))
        if report:
            st.json(report.get("criteria", {}), expanded=False)
    if report is None:
        st.error(f"{filename}: {localized_error_message(selected['error'], batch_language)}")
        st.stop()
    st.divider()

if data is None:
    st.info(t("왼쪽에서 CIF를 열거나 위의 예제 보기 버튼으로 시작하세요.", "Open a CIF in the sidebar, or use Try sample above."))
    st.stop()
if len(data) > MAX_BYTES:
    st.error(t("파일이 2 MiB를 초과합니다. 더 작은 CIF를 사용하세요.", "File exceeds 2 MiB. Please use a smaller CIF."))
    st.stop()
try:
    if report is None:
        report = with_provenance(analyze_cif(data, short_distance=float(threshold), normal_axis=normal_axis), data, filename)
except (UnsupportedStructure, ValueError) as exc:
    st.error(t("이 입력은 현재 지원 범위에서 해석할 수 없습니다.", "This input cannot be interpreted within the supported scope."))
    original_reason = str(exc)
    reason = localized_error_message(original_reason, language="ko" if ko else "en")
    st.write(reason)
    if ko and reason != original_reason:
        with st.expander("원문 진단 / Original diagnostic"):
            st.code(original_reason, language=None)
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
cols[0].button(t("원자쌍 보기", "View nearest pair"), key="show_minimum_pair", on_click=show_minimum_pair)
st.caption(t("두께·간격은 원자핵 위치 기준입니다. 단일 원자 평면의 두께는 0 Å이며, 핵 간격은 전자밀도 경계의 진공 폭이 아닙니다.", "Thickness and gap refer to nuclear positions. A single atomic plane has zero nuclear-span thickness; this gap is not an electron-density vacuum width."))

def explanation(item: dict) -> str:
    return localized_issue_message(item, report, language="ko" if ko else "en")


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
        "minimum": t("가장 가까운 원자쌍", "Nearest atom pair"),
        "overlap": t("● 원자 겹침 · 확인 필요" if overlapping else "○ 원자 겹침 · 검출 없음", "● Overlap · needs review" if overlapping else "○ Overlap · none detected"),
        "short": t("● 짧은 거리 · 확인 필요" if close else "○ 짧은 거리 · 검출 없음", "● Short distance · needs review" if close else "○ Short distance · none detected"),
        "gap": t("● 층·핵 간격 · 해석 검토 필요" if gap_review else "◐ 층·핵 간격 · 수렴 검증 필요", "● Layer/gap · interpretation needed" if gap_review else "◐ Layer/gap · convergence needed"),
        "metadata": t("● 입력 정보 · 점유율 생략" if assumed else "○ 필수 입력 정보 · 읽음", "● Input data · occupancy omitted" if assumed else "○ Required input fields · read"),
    }
    with st.container(key="review_focus"):
        focus = localized_radio(t("강조할 점검 항목", "Check to highlight"), list(choices), format_func=choices.get, key="review_focus", label_visibility="collapsed")
    related_codes = {
        "overview": [], "minimum": [], "overlap": ["OVERLAPPING_SITES"], "short": ["SHORT_DISTANCE", "SELF_IMAGE_CONTACT"],
        "gap": ["AMBIGUOUS_SLAB", "MULTIPLE_LARGE_GAPS", "VACUUM_CONVERGENCE"], "metadata": ["ASSUMED_FULL_OCCUPANCY"],
    }[focus]
    related_issues = [issue_by_code[code] for code in related_codes if code in issue_by_code]
    highlighted_atoms = sorted({i for item in related_issues for i in item.get("atom_indices", [])})
    selected_contact = None
    if focus == "minimum":
        selected_contact = metrics["minimum_pair"]
        highlighted_atoms = sorted({selected_contact["i"], selected_contact["j"]})
        st.caption(t("경고 기준과 관계없이 가장 짧은 주기적 거리를 보여줍니다. 같은 최솟값이 여럿이면 한 쌍을 표시합니다.", "Shows the shortest periodic distance regardless of the warning cutoff. One pair is shown when several share the minimum."))
    if focus in ("overlap", "short"):
        contacts = list(report["short_contacts"])
        for issue in related_issues:
            evidence = issue.get("representative_contact")
            if evidence is not None and evidence not in contacts:
                contacts.append(evidence)
        if focus == "overlap":
            contacts = [item for item in contacts if not item["is_self_image"] and item["distance_angstrom"] <= overlap_tolerance]
        if contacts:
            def contact_label(index: int) -> str:
                item = contacts[index]
                return f"{report['elements'][item['i']]}{item['i']+1}–{report['elements'][item['j']]}{item['j']+1} · {item['distance_angstrom']:.4f} Å"
            contact_index = st.selectbox(t("강조할 원자 쌍", "Contact to highlight"), list(range(len(contacts))), format_func=contact_label, key=f"contact_{focus}")
            selected_contact = contacts[contact_index]
            highlighted_atoms = sorted({selected_contact["i"], selected_contact["j"]})
        else:
            st.caption(t("이 항목에 해당하는 거리 기록이 없습니다.", "No contact records match this check."))
        if report["short_contacts_truncated"]:
            st.warning(t(f"전체 {report['short_contact_count']}개 중 중요한 원자쌍을 우선 보관한 일부 기록입니다. 경고 건수는 전체 구조에서 계산합니다.", f"This is a prioritized subset of {report['short_contact_count']} contacts. Warning counts cover the full structure."))
    if selected_contact is not None:
        st.write(f"**{selected_contact['element_i']}{selected_contact['i']+1}–{selected_contact['element_j']}{selected_contact['j']+1} · {selected_contact['distance_angstrom']:.6f} Å**")
        st.caption(t(f"상대 원자의 주기 이동 [a,b,c]: {selected_contact['shift']}", f"Partner image shift [a,b,c]: {selected_contact['shift']}"))
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
    title, export_language_column, csv_button, json_button = st.columns([2.5, 1.4, 1, 1], vertical_alignment="center")
    title.subheader(t("점검 결과와 원자 좌표", "Review results and site data"))
    export_labels = {"interface": t("화면과 같음", "Same as interface"), "en": "English", "ko": "한국어"}
    with export_language_column:
        export_choice = localized_selectbox(t("보고서 언어", "Report language"), list(export_labels), format_func=export_labels.get, key="report_language")
    output_language = ("ko" if ko else "en") if export_choice == "interface" else export_choice
    output_report = localized_report(report, language=output_language)
    csv_text = report_csv(report, language=output_language)
    csv_data = csv_text.encode("utf-8-sig" if output_language == "ko" else "utf-8")
    export_stem = f"{Path(filename).stem}_calclens_{output_language}"
    csv_button.download_button(t("CSV 내보내기", "Export CSV"), data=csv_data, file_name=f"{export_stem}.csv", mime="text/csv; charset=utf-8", key="download_csv", width="stretch")
    json_button.download_button(t("JSON 내보내기", "Export JSON"), data=json.dumps(output_report, ensure_ascii=False, indent=2, allow_nan=False), file_name=f"{export_stem}.json", mime="application/json", key="download_report", width="stretch")
    contact_tab, coordinate_tab, issue_tab = st.tabs([t("짧은 거리", "Short contacts"), t("원자 좌표", "Site coordinates"), t("모든 진단", "All diagnostics")])
    with contact_tab:
        if report.get("short_contacts_truncated"):
            st.warning(t(f"총 {report['short_contact_count']}개 중 겹침·최소 거리·자기 주기상 근거를 우선하여 {len(report['short_contacts'])}개를 표시합니다. 내보내기에 전체 건수와 대표 근거도 남깁니다.", f"Showing {len(report['short_contacts'])} of {report['short_contact_count']} contacts, prioritizing overlaps, the minimum and self-image evidence. Exports also retain total counts and representative evidence."))
        rows = [{t("원자 쌍", "Element pair"): f"{report['elements'][item['i']]}{item['i']+1}–{report['elements'][item['j']]}{item['j']+1}", t("거리 / Å", "Distance / Å"): round(item["distance_angstrom"], 6), t("기준 / Å", "Cutoff / Å"): float(threshold), t("주기 이동 [a,b,c]", "Image shift [a,b,c]"): str(item["shift"]), t("자기 주기상", "Self image"): item["is_self_image"]} for item in report.get("short_contacts", [])]
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        else:
            st.write(t(f"{threshold:.2f} Å 미만의 거리 기록이 없습니다. 이 결과가 구조의 타당성을 보장하지는 않습니다.", f"No contact records below {threshold:.2f} Å. This does not establish structural validity."))
        st.caption(t("화면의 원자 번호는 1부터, JSON 인덱스는 0부터 시작합니다. CSV/JSON에는 선택 축·기준·보고서 언어가 포함됩니다. JSON 키·진단 코드는 두 언어에서 같습니다.", "Displayed site numbers start at 1; JSON indexes start at 0. CSV/JSON include the axis, criteria and report language. JSON keys and diagnostic codes remain the same in both languages."))
    with coordinate_tab:
        positions = [{t("원자", "Site"): i + 1, t("원소", "Element"): element, "x / Å": p[0], "y / Å": p[1], "z / Å": p[2]} for i, (element, p) in enumerate(zip(report["elements"], report["positions"]))]
        st.dataframe(positions, hide_index=True, width="stretch")
    with issue_tab:
        st.caption(t("보고서에는 원본 파일명·SHA-256·CalcLens 및 ASE 버전이 포함됩니다.", "Reports include the original filename, SHA-256, CalcLens version and ASE version."))
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
