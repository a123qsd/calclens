"""Portable reports containing observations, criteria, and interpretation limits."""

import csv
from copy import deepcopy
import io
import re


FIELDS = [
    "record_type", "code", "severity", "value", "unit", "site_i", "element_i",
    "site_j", "element_j", "image_shift_a", "image_shift_b", "image_shift_c",
    "related_sites", "normal_axis", "short_distance_threshold_angstrom", "note",
]

KOREAN_FIELDS = dict(zip(FIELDS, [
    "기록 종류", "코드", "심각도", "값", "단위", "원자 i 번호", "원소 i",
    "원자 j 번호", "원소 j", "주기 이동 a", "주기 이동 b", "주기 이동 c",
    "관련 원자 번호", "선택한 수직축", "짧은 거리 기준(Å)", "설명",
]))

_ASSUMPTIONS_KO = {
    "Exactly one explicitly expanded P1 structure with full occupancy and fractional coordinates.":
        "모든 원자 자리가 명시된 하나의 P1 구조이며, 완전 점유와 분율 좌표를 전제로 합니다.",
    "All three cell directions are periodic for distance screening.":
        "거리 점검에서는 셀의 세 방향 모두에 주기 경계 조건을 적용합니다.",
    "CIF cell lengths are in angstrom and angles in degrees; reported uncertainties are not propagated.":
        "CIF 셀 길이의 단위는 Å, 각도의 단위는 도입니다. 입력값의 불확도는 결과에 전파하지 않습니다.",
}

_LIMITATIONS_KO = {
    "No energy, electronic structure, bonds, forces, stability, or convergence calculation is performed.":
        "에너지·전자 구조·결합·힘·안정성·수렴 여부는 계산하지 않습니다.",
    "The thickness is a nuclei-center span; an ideal planar monolayer has zero nuclei-span thickness.":
        "두께는 원자핵 중심 위치의 범위입니다. 이상적인 단일 원자 평면의 핵 위치 기준 두께는 0 Å입니다.",
    "The largest cyclic nuclei gap may be an interlayer gap or empty space in a molecule or bulk cell. Physical slab assignment is not verified.":
        "가장 큰 주기적 핵 간격은 층 사이 간격이거나 분자·벌크 셀의 빈 공간일 수 있습니다. 실제 슬래브 구조인지 검증하지 않습니다.",
    "Ambiguity and short-distance thresholds are screening heuristics; absence of warnings is not validation.":
        "구조 해석의 모호함과 짧은 거리 기준은 예비 점검용 경험적 기준입니다. 경고가 없어도 구조가 검증된 것은 아닙니다.",
    "Contacts retain only one nearest image per unordered site pair and one shortest self-image per site, at most 200 records.":
        "접촉 목록에는 순서를 구분하지 않은 원자 쌍마다 가장 가까운 주기 이미지 하나와 각 원자의 가장 가까운 자체 이미지 하나만 남기며, 최대 200개 기록을 표시합니다.",
    "Screening counts one nearest image per unordered site pair and one shortest self-image per site. The contact list retains at most 200 records, prioritizing overlaps then shorter distances and preserving minimum-distance and self-image evidence when below the threshold.":
        "점검에서는 순서를 구분하지 않은 원자 쌍마다 가장 가까운 이미지 하나와 각 원자의 가장 짧은 자체 이미지 하나를 셉니다. 접촉 목록에는 중복과 더 짧은 거리를 우선하여 최대 200개 기록을 남기며, 기준보다 짧은 최소 거리와 자체 이미지의 근거를 보존합니다.",
}

_ERRORS_KO = {
    "Repeated CIF tags are ambiguous and unsupported.": "중복된 CIF 태그는 해석이 모호하여 지원하지 않습니다.",
    "Modulated, superspace, and composite-structure CIF metadata are unsupported; average site coordinates are not an explicit ordinary periodic structure.": "변조·초공간·복합 구조의 CIF 메타데이터는 지원하지 않습니다. 평균 원자 좌표만으로는 일반적인 주기 구조 전체를 명시할 수 없습니다.",
    "Only explicitly expanded P1 (space group 1) CIFs are supported.": "모든 원자 자리가 명시된 P1(공간군 1) CIF만 지원합니다.",
    "Only P1 symmetry is supported; export all sites as P1 first.": "P1 대칭만 지원합니다. 모든 원자 자리를 포함한 P1 구조로 먼저 내보내세요.",
    "Explicit P1 space-group name or number is required; symmetry is not guessed.": "P1 공간군 이름 또는 번호를 명시해야 합니다. 대칭을 추측하지 않습니다.",
    "Only the identity symmetry operation 'x,y,z' is supported.": "항등 대칭 연산 'x,y,z'만 지원합니다.",
    "Nonstandard space-group settings are unsupported.": "비표준 공간군 설정은 지원하지 않습니다.",
    "Magnetic symmetry CIFs are unsupported.": "자기 대칭을 포함한 CIF는 지원하지 않습니다.",
    "Provide CIF text or bytes, not a filename or another object.": "파일 이름이나 다른 객체가 아닌 CIF 텍스트 또는 바이트를 입력하세요.",
    "CIF exceeds the 2 MiB input limit.": "CIF 파일이 입력 크기 제한인 2 MiB를 초과했습니다.",
    "Input is empty or contains binary/null data.": "입력이 비어 있거나 바이너리·널 문자를 포함합니다.",
    "CIF 2.0 is unsupported; export a simple CIF 1.1 P1 structure.": "CIF 2.0은 지원하지 않습니다. 단순한 CIF 1.1 P1 구조로 내보내세요.",
    "ASE could not parse this as an unambiguous CIF 1.1 file.": "ASE가 이 파일을 모호함 없이 해석 가능한 CIF 1.1 형식으로 읽지 못했습니다.",
    "Exactly one CIF data block is required.": "CIF 데이터 블록은 정확히 하나여야 합니다.",
    "All six cell lengths/angles are required (angstrom and degrees).": "셀의 길이 3개와 각도 3개를 모두 입력해야 합니다. 단위는 각각 Å와 도입니다.",
    "Cell lengths must lie between 0.001 and 10000 angstrom.": "셀 길이는 0.001 Å 이상, 10000 Å 이하여야 합니다.",
    "All cell angles must be strictly between 0 and 180 degrees.": "모든 셀 각도는 0도보다 크고 180도보다 작아야 합니다.",
    "Cell lengths and angles cannot form a valid three-dimensional cell.": "셀 길이와 각도로 유효한 3차원 셀을 구성할 수 없습니다.",
    "Degenerate or ill-conditioned cells are unsupported (condition number > 10000).": "퇴화하거나 수치적으로 불안정한 셀은 지원하지 않습니다(조건수 > 10000).",
    "An explicit site loop with element symbols and fractional x, y, z is required.": "원소 기호와 분율 좌표 x, y, z를 포함한 명시적 원자 자리 루프가 필요합니다.",
    "The supported size is 1 to 400 explicit atomic sites.": "명시적 원자 자리 1개부터 400개까지 지원합니다.",
    "Site-loop columns must have equal lengths.": "원자 자리 루프의 모든 열은 길이가 같아야 합니다.",
    "Use canonical element symbols (for example C, B, Mo); mixed species, charges and isotope labels are unsupported.": "C, B, Mo 같은 표준 원소 기호를 사용하세요. 혼합 원소·전하·동위원소 표기는 지원하지 않습니다.",
    "Fractional coordinates above 1000000 in magnitude are unsupported.": "절댓값이 1000000을 넘는 분율 좌표는 지원하지 않습니다.",
    "CIFs containing Cartesian site coordinates are unsupported; provide fractional coordinates only.": "직교 좌표를 포함한 CIF는 지원하지 않습니다. 분율 좌표만 입력하세요.",
    "Only fully occupied sites (occupancy 1) are supported.": "완전히 점유된 원자 자리(점유율 1)만 지원합니다. 부분 점유 구조는 해석하지 않습니다.",
    "Disordered or ambiguous site groups are unsupported.": "무질서하거나 해석이 모호한 원자 자리 그룹은 지원하지 않습니다.",
    "Site multiplicity must be 1 in an explicitly expanded P1 structure.": "모든 원자 자리가 명시된 P1 구조에서는 자리 다중도가 1이어야 합니다.",
    "Short-distance threshold must be between 0.1 and 3.0 angstrom.": "짧은 거리 기준은 0.1 Å 이상, 3.0 Å 이하여야 합니다.",
    "Select the candidate slab-normal lattice axis explicitly as a, b, or c.": "슬래브 수직 방향의 후보 격자축을 a, b, c 중 하나로 직접 선택하세요.",
    "Periodic geometry could not be resolved reliably for this cell.": "이 셀의 주기적 기하를 신뢰할 수 있게 계산하지 못했습니다.",
}

_NUMERIC_LABELS_KO = {
    "Space-group number": "공간군 번호", "Space-group setting": "공간군 설정",
    "Cell parameter": "셀 매개변수", "Fractional coordinate": "분율 좌표",
    "Occupancy": "점유율", "Site multiplicity": "자리 다중도",
    "Short-distance threshold": "짧은 거리 기준",
}

_METRIC_NOTES = {
    "minimum_distance_angstrom": ("Shortest periodic nuclear distance, including self-images.", "자체 이미지를 포함한 가장 짧은 주기적 원자핵 간 거리입니다."),
    "minimum_pair": ("One pair/image realizing the shortest distance; site indexes start at 0.", "가장 짧은 거리를 이루는 원자 쌍 또는 이미지 하나입니다. 원자 인덱스는 0부터 시작합니다."),
    "c_height_angstrom": ("Projection of c onto the normal of the a-b plane, regardless of the selected axis.", "선택한 수직축과 관계없이 a-b 평면의 수직 방향으로 투영한 c축 높이입니다."),
    "normal_height_angstrom": ("Cell repeat height along the selected candidate normal.", "선택한 수직 방향 후보축을 따라 측정한 셀 반복 높이입니다."),
    "nuclei_thickness_angstrom": ("Nuclear-position span after removing the largest cyclic gap; physical slab assignment is unverified.", "가장 큰 주기적 간격을 제외한 원자핵 위치 범위입니다. 실제 슬래브라는 해석은 검증하지 않습니다."),
    "nuclei_gap_angstrom": ("Largest cyclic nuclear gap along the selected axis; not an electron-density vacuum width.", "선택한 축을 따른 가장 큰 주기적 핵 간격입니다. 전자밀도 경계로 정한 진공 폭이 아닙니다."),
    "gap_fraction": ("Largest gap divided by the selected normal repeat height.", "가장 큰 간격을 선택한 축의 반복 높이로 나눈 비율입니다."),
    "gap_start_fraction": ("Fractional start of the chosen gap along the selected axis.", "선택한 축에서 해당 간격이 시작하는 분율 좌표입니다."),
    "gap_end_fraction": ("Fractional end of the chosen gap; end <= start wraps through the periodic boundary.", "선택한 축에서 해당 간격이 끝나는 분율 좌표입니다. 끝값이 시작값 이하면 주기 경계를 통과합니다."),
    "second_largest_gap_angstrom": ("Second-largest cyclic nuclear gap along the selected axis.", "선택한 축을 따른 두 번째로 큰 주기적 핵 간격입니다."),
}

_PROVENANCE_NOTES = {
    "original_filename": ("Original input filename supplied by the file reader.", "파일을 읽을 때 전달된 원본 입력 파일 이름입니다."),
    "sha256": ("SHA-256 of the exact original file bytes, before decoding or newline conversion.", "디코딩하거나 줄바꿈을 변환하기 전의 원본 파일 바이트에 대한 SHA-256입니다."),
    "calclens_version": ("Version of the CalcLens package producing this report.", "이 보고서를 생성한 CalcLens 패키지 버전입니다."),
    "ase_version": ("Version of ASE used to parse and measure the structure.", "구조를 읽고 측정하는 데 사용한 ASE 버전입니다."),
}

_CRITERION_NOTES = {
    "short_distance_threshold_angstrom": ("Element-independent geometric short-contact threshold.", "원소를 구분하지 않는 기하학적 짧은 접촉 기준입니다."),
    "short_distance_comparison": ("Operator comparing a nearest-image distance with the short-contact threshold.", "가장 가까운 이미지 거리와 짧은 접촉 기준을 비교하는 연산자입니다."),
    "overlap_tolerance_angstrom": ("Distinct sites within this tolerance, including periodic images, are reported as overlaps.", "주기 이미지를 포함하여 서로 다른 자리가 이 허용 거리 이내에 있으면 중복으로 보고합니다."),
    "overlap_comparison": ("Operator comparing a distinct-site distance with the overlap tolerance.", "서로 다른 자리 사이의 거리와 중복 허용 거리를 비교하는 연산자입니다."),
    "perpendicular_angle_tolerance_degree": ("Allowed deviation from 90 degrees for the selected normal axis.", "선택한 수직축과 다른 축 사이의 각도에 허용되는 90도 기준 편차입니다."),
    "ambiguous_gap_min_angstrom": ("Gap below this length triggers interpretation review; this is not a convergence criterion.", "간격이 이 길이 미만이면 해석 검토가 필요합니다. 수렴 기준이 아닙니다."),
    "ambiguous_gap_max_fraction": ("Gap at or below this fraction of normal height triggers interpretation review.", "간격이 수직 반복 높이의 이 비율 이하면 해석 검토가 필요합니다."),
    "competing_gap_min_angstrom": ("Second gap must meet this length and the competing-gap ratio to trigger ambiguity.", "두 번째 간격이 이 길이 이상이며 경쟁 간격 비율도 충족하면 모호함을 알립니다."),
    "competing_gap_ratio": ("Required ratio of second-largest to largest gap for the competing-gap warning.", "큰 간격이 여러 개라는 경고에 사용하는 두 번째 간격 대 최대 간격의 비율 기준입니다."),
}


def _language(language: str) -> str:
    if not isinstance(language, str) or language.lower() not in ("en", "ko"):
        raise ValueError("Report language must be 'en' or 'ko'.")
    return language.lower()


def localized_error_message(message: str, language: str = "en") -> str:
    """Translate known input failures without dropping unknown original detail."""
    if _language(language) == "en":
        return message
    if message in _ERRORS_KO:
        return _ERRORS_KO[message]
    finite = re.fullmatch(r"(.+) must be a finite number\.", message)
    if finite:
        label = _NUMERIC_LABELS_KO.get(finite[1], finite[1])
        return f"{label} 값은 유한한 숫자여야 합니다."
    tilted = re.fullmatch(
        r"The selected ([abc]) axis must be perpendicular to ([abc]) and ([abc]) "
        r"\((.+) = 90 degrees\)\. Tilted slab normals are unsupported\.", message,
    )
    if tilted:
        return (f"선택한 {tilted[1]}축은 {tilted[2]}축과 {tilted[3]}축에 수직이어야 합니다"
                f"({tilted[4]} = 90도). 기울어진 슬래브 수직 방향은 지원하지 않습니다.")
    return f"처리할 수 없는 입력 또는 파일 오류입니다. 원문: {message}"


def localized_issue_message(issue: dict, report: dict, language: str = "en") -> str:
    """Translate diagnoses faithfully, retaining counts even when contacts are truncated."""
    original = issue.get("message_en", issue["message"])
    if _language(language) == "en":
        return original
    code = issue["code"]
    number = r"([0-9.eE+\-]+)"
    if code == "OVERLAPPING_SITES":
        match = re.match(r"(\d+) distinct site pair\(s\) overlap within " + number + r" angstrom", original)
        if match:
            return (f"서로 다른 원자 자리 {match[1]}쌍이 주기 이미지를 포함하여 {match[2]} Å 이내에서 겹칩니다. "
                    "입력된 원자 자리는 삭제하거나 합치지 않고 모두 보존했습니다.")
    elif code == "SHORT_DISTANCE":
        match = re.match(r"(\d+) distinct site pair\(s\) have a nearest image below the " + number + r" angstrom", original)
        if match:
            return (f"서로 다른 원자 자리 {match[1]}쌍의 가장 가까운 주기 이미지 거리가 {match[2]} Å 기준보다 작습니다. "
                    "이는 원소를 구분하지 않는 경험적 점검 기준이며, 결합이나 안정성을 판정하지 않습니다.")
    elif code == "SELF_IMAGE_CONTACT":
        match = re.search(r"periodic image only " + number + r" angstrom away", original)
        if match:
            return (f"모든 원자 자리({report['atom_count']}개)는 자신의 주기 이미지와 {match[1]} Å만큼 떨어져 있습니다. "
                    "셀 크기와 단위를 확인하세요.")
    elif code == "ASSUMED_FULL_OCCUPANCY":
        return (f"점유율 항목이 생략되어 명시된 원자 자리 {report['atom_count']}개를 모두 완전 점유(점유율 1)로 가정했습니다.")
    elif code == "AMBIGUOUS_SLAB":
        metrics, criteria = report["metrics"], report["criteria"]
        return (f"선택한 {report.get('normal_axis', 'c')}축의 가장 큰 핵 간격은 {metrics['nuclei_gap_angstrom']:.6g} Å"
                f"(반복 높이의 {metrics['gap_fraction'] * 100:.6g}%)입니다. "
                f"간격이 {criteria['ambiguous_gap_min_angstrom']:g} Å 미만이거나 반복 높이의 "
                f"{criteria['ambiguous_gap_max_fraction'] * 100:g}% 이하이므로, 이 기하 점검만으로 고립된 단일 슬래브라고 해석할 수 없습니다.")
    elif code == "MULTIPLE_LARGE_GAPS":
        metrics, criteria = report["metrics"], report["criteria"]
        return (f"선택한 {report.get('normal_axis', 'c')}축에서 큰 핵 간격이 여러 개 발견되었습니다. "
                f"가장 큰 간격은 {metrics['nuclei_gap_angstrom']:.6g} Å, 두 번째 간격은 {metrics['second_largest_gap_angstrom']:.6g} Å입니다. "
                f"두 번째 간격이 {criteria['competing_gap_min_angstrom']:g} Å 이상이며 최대 간격의 "
                f"{criteria['competing_gap_ratio'] * 100:g}% 이상인 경우에 표시하는 경고입니다. "
                "다층·여러 슬래브·다른 배향일 수 있으므로 선택된 간격을 유일한 실제 진공 영역으로 볼 수 없습니다.")
    elif code == "GEOMETRY_ONLY":
        return "입력된 원자핵과 셀의 기하만 측정합니다. 물질의 안정성·결합·실제 차원성·계산 정확성을 검증하지 않습니다."
    elif code == "VACUUM_CONVERGENCE":
        return "가장 큰 핵 간격은 전자밀도 경계로 정한 진공 폭이 아닙니다. 진공 간격이 충분한지는 수행할 계산에 대한 수렴 검증이 필요합니다."
    # Unknown/future wording is retained rather than replaced by a vague or
    # potentially incorrect translation. Canonical English is also kept in JSON.
    return f"추가 진단(원문): {original}"


def _localized_note(note: str, kind: str, report: dict) -> str:
    translations = _ASSUMPTIONS_KO if kind == "assumptions" else _LIMITATIONS_KO
    if note in translations:
        return translations[note]
    axis = report.get("normal_axis", "c")
    plane = "-".join(report.get("in_plane_axes", [item for item in "abc" if item != axis]))
    if note == f"{axis} is perpendicular to the {plane} plane; {axis} is the user-supplied candidate slab-normal direction.":
        return f"{axis}축은 {plane} 평면에 수직이며, 사용자가 선택한 슬래브 수직 방향의 후보입니다."
    return f"추가 설명(원문): {note}"


def localized_report(report: dict, language: str = "en") -> dict:
    """Copy a report with localized prose; geometry and canonical identifiers stay intact.

    Korean JSON retains exact English prose in message_en, assumptions_en and
    limitations_en. Passing that report back with language='en' restores it.
    """
    language = _language(language)
    result = deepcopy(report)
    result["report_language"] = language
    result["language_note"] = (
        "설명은 한국어입니다. 키·코드·심각도·단위 식별자와 수치·원자 인덱스는 바꾸지 않았습니다. "
        "JSON의 원자 인덱스는 0부터 시작하며, *_en 항목에는 영문 원문을 보존합니다."
        if language == "ko" else
        "Descriptions are in English. Keys, codes, severity, unit identifiers, numbers and site indexes are unchanged. JSON site indexes start at 0."
    )
    text_index = 1 if language == "ko" else 0
    result["field_descriptions"] = {
        "metrics": {key: notes[text_index] for key, notes in _METRIC_NOTES.items()},
        "criteria": {key: notes[text_index] for key, notes in _CRITERION_NOTES.items()},
        "provenance": {key: notes[text_index] for key, notes in _PROVENANCE_NOTES.items()},
        "review_required": ("하나 이상의 경고 또는 오류가 있음을 나타냅니다." if language == "ko" else
                            "True when at least one warning or error exists."),
        "gap_review_required": ("핵 간격을 실제 슬래브 간격으로 해석하는 데 모호함이 있음을 나타냅니다." if language == "ko" else
                                "True when the nuclear gap has an ambiguous slab interpretation."),
    }
    for issue in result["issues"]:
        original = issue.get("message_en", issue["message"])
        issue["message"] = localized_issue_message(issue, result, language)
        if language == "ko":
            issue["message_en"] = original
        else:
            issue.pop("message_en", None)
    for kind in ("assumptions", "limitations"):
        original = result.get(f"{kind}_en", result[kind])
        result[kind] = [_localized_note(note, kind, result) for note in original] if language == "ko" else list(original)
        if language == "ko":
            result[f"{kind}_en"] = list(original)
        else:
            result.pop(f"{kind}_en", None)
    return result


def _spreadsheet_text(value):
    # Text fields can eventually contain user-supplied descriptions. Keep CSV
    # formulas inert; numeric measurements retain their numeric representation.
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def report_csv(report: dict, language: str = "en") -> str:
    """Export localized CSV without a BOM; sites are one-based, JSON indexes zero-based."""
    language = _language(language)
    report = localized_report(report, language)
    ko = language == "ko"
    output = io.StringIO(newline="")
    headers = KOREAN_FIELDS if ko else {key: key for key in FIELDS}
    writer = csv.DictWriter(output, fieldnames=[headers[key] for key in FIELDS], lineterminator="\n")
    writer.writeheader()
    shared = {
        "normal_axis": report.get("normal_axis", "c"),
        "short_distance_threshold_angstrom": report["short_distance_threshold_angstrom"],
    }

    def write(**row):
        writer.writerow({headers[key]: _spreadsheet_text(value) for key, value in (shared | row).items()})

    def write_contact(contact, record_type, code, *, note="", severity=""):
        i, j = contact["i"], contact["j"]
        write(record_type=record_type, code=code, severity=severity,
              value=contact["distance_angstrom"], unit="angstrom", site_i=i + 1,
              element_i=report["elements"][i], site_j=j + 1, element_j=report["elements"][j],
              image_shift_a=contact["shift"][0], image_shift_b=contact["shift"][1],
              image_shift_c=contact["shift"][2], note=note)

    write(record_type="metadata", code="report_language", value=language,
          note="열 이름과 설명은 한국어이며, 기록 종류·코드·심각도·단위 식별자와 수치는 원래 값을 유지합니다." if ko else
               "Headers and descriptions are in English; record types, codes, severity, unit identifiers and numbers retain their canonical values.")
    for name, value in report.get("provenance", {}).items():
        write(record_type="provenance", code=name, value=value,
              note=report["field_descriptions"]["provenance"].get(name, ""))
    write(record_type="structure", code="formula", value=report["formula"])
    write(record_type="structure", code="atom_count", value=report["atom_count"], unit="sites")
    write(record_type="structure", code="schema_version", value=report["schema_version"])
    for name, value in report["metrics"].items():
        if isinstance(value, (int, float)):
            write(record_type="metric", code=name, value=value,
                  unit="angstrom" if name.endswith("_angstrom") else "fraction",
                  note=report["field_descriptions"]["metrics"].get(name, ""))
    minimum = report["metrics"].get("minimum_pair")
    if minimum is not None:
        write_contact(minimum, "metric", "minimum_pair",
                      note=("가장 짧은 거리를 이루는 원자 쌍 또는 이미지 하나입니다. 짧은 거리 기준과 관계없이 보존합니다." if ko else
                            "One pair/image realizing the shortest distance, retained independently of the short-contact threshold."))
    for name, value in report.get("criteria", {
        "short_distance_threshold_angstrom": report["short_distance_threshold_angstrom"],
    }).items():
        write(record_type="criterion", code=name, value=value,
              unit=("angstrom" if name.endswith("_angstrom") else
                    "degree" if name.endswith("_degree") else "dimensionless"),
              note=report["field_descriptions"]["criteria"].get(name, ""))
    for issue in report["issues"]:
        count = issue.get("contact_count")
        write(record_type="issue", code=issue["code"], severity=issue["severity"],
              value=count if count is not None else "",
              unit=("sites" if issue["code"] == "SELF_IMAGE_CONTACT" else "pairs") if count is not None else "",
              related_sites=";".join(str(i + 1) for i in issue.get("atom_indices", [])),
              note=issue["message"])
        representative = issue.get("representative_contact")
        if representative is not None:
            write_contact(representative, "issue_contact", issue["code"], severity=issue["severity"],
                          note=("이 진단을 뒷받침하는 가장 짧은 원자 쌍·이미지의 대표 기록입니다. 전체 접촉 표의 생략 여부와 관계없이 보존합니다." if ko else
                                "Shortest representative pair/image supporting this issue, retained independently of contact-table truncation."))
    for contact in report["short_contacts"]:
        write_contact(contact, "contact", "self_image" if contact["is_self_image"] else "pair")
    write(record_type="contact_summary", code="total_count", value=report["short_contact_count"])
    write(record_type="contact_summary", code="details_truncated",
          value=str(report["short_contacts_truncated"]).lower(),
          note="가장 가까운 원자 쌍·자체 주기 이미지 기록을 최대 200개 표시합니다. 진단별 정확한 개수와 대표 기록, 최소 거리 기록은 별도로 보존합니다. 배위수 분석 목록이 아닙니다." if ko else
               "At most 200 nearest-pair/self-image records; exact issue counts, issue representatives and the minimum pair are preserved separately. This is not a coordination list.")
    for kind in ("assumptions", "limitations"):
        for note in report[kind]:
            write(record_type=kind[:-1], note=note)
    write(record_type="convention", code="site_numbering", value="one-based",
          note="CSV 원자 번호는 1부터 시작합니다. JSON i/j/atom_indices는 0부터 시작합니다." if ko else
               "CSV sites start at 1. JSON i/j/atom_indices start at 0.")
    return output.getvalue()
