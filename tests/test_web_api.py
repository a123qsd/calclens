"""HTTP contract and security boundaries for the offline workspace API."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
from pathlib import Path
import threading

import ase
import pytest

from slab_preflight import __version__
from slab_preflight.project import ANALYSIS_REVISION
from slab_preflight.project import loads_project
from slab_preflight import web_api
from slab_preflight.web_api import create_server


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def api_server():
    server = create_server(ROOT, 0, "ko")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def request(server, method, path, body=None, *, authorized=False, headers=None):
    payload = body
    if isinstance(body, (dict, list)):
        payload = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    all_headers = {"Host": server.expected_host}
    if payload is not None:
        all_headers["Content-Type"] = "application/json"
    if authorized:
        all_headers.update({
            "Origin": f"http://{server.expected_host}",
            "X-CalcLens-Token": server.token,
        })
    if headers:
        all_headers.update(headers)
    connection.request(method, path, body=payload, headers=all_headers)
    response = connection.getresponse()
    data = response.read()
    result = (response.status, dict(response.getheaders()), data)
    connection.close()
    return result


def decoded(response):
    return json.loads(response[2])


def action(server, revision, value, **kwargs):
    return request(
        server, "POST", "/api/v1/actions",
        {"expected_revision": revision, "action": value},
        authorized=True, **kwargs,
    )


def file_payload(name):
    return {
        "filename": name,
        "data_base64": base64.b64encode((ROOT / "examples" / name).read_bytes()).decode(),
    }


def test_bootstrap_health_and_real_graphene_snapshot_have_no_original_bytes(api_server):
    health = request(api_server, "GET", "/_calclens/health")
    assert health[0] == 200
    assert health[2] == b"ok"
    assert "Access-Control-Allow-Origin" not in health[1]
    assert health[1]["Content-Security-Policy"] == (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )

    response = request(api_server, "GET", "/api/v1/bootstrap")
    snapshot = decoded(response)
    assert response[0] == 200
    assert snapshot["api_version"] == 1
    assert snapshot["revision"] == 0
    assert snapshot["language"] == "ko"
    assert snapshot["token"] == api_server.token
    assert snapshot["runtime"] == {
        "calclens_version": __version__,
        "ase_version": ase.__version__,
        "analysis_revision": ANALYSIS_REVISION,
    }
    assert snapshot["project"]["selected_id"] == snapshot["entries"][0]["id"]
    assert snapshot["entries"][0]["filename"] == "graphene.cif"
    assert snapshot["entries"][0]["analysis"]["report"]["formula"] == "C2"
    assert snapshot["entries"][0]["analysis"]["error"] is None
    assert snapshot["entries"][0]["analysis"]["assumptions_ko"]
    assert snapshot["entries"][0]["analysis"]["limitations_ko"]
    assert len(snapshot["examples"]) == 16
    assert {item["name"] for item in snapshot["examples"]} == {
        path.name for path in (ROOT / "examples").glob("*.cif")
    }
    assert b"cif_base64" not in response[2]


@pytest.mark.parametrize(
    ("name", "axis"),
    [("mos2_a_normal.cif", "a"), ("mos2_b_normal.cif", "b")],
)
def test_oriented_examples_load_with_their_named_normal_axis(api_server, name, axis):
    response = action(api_server, 0, {"type": "load_example", "name": name})
    snapshot = decoded(response)
    assert response[0] == 200
    assert snapshot["entries"][0]["normal_axis"] == axis
    assert snapshot["entries"][0]["analysis"]["error"] is None


@pytest.mark.parametrize(
    ("authorized", "headers", "code"),
    [
        (False, {}, "invalid_origin"),
        (True, {"Origin": "http://evil.invalid"}, "invalid_origin"),
        (True, {"X-CalcLens-Token": "wrong"}, "invalid_token"),
        (True, {"Host": "localhost:1"}, "invalid_host"),
    ],
)
def test_mutations_require_exact_host_origin_and_token(
    api_server, authorized, headers, code,
):
    response = request(
        api_server, "POST", "/api/v1/actions",
        {"expected_revision": 0, "action": {"type": "patch_workspace", "language": "en"}},
        authorized=authorized, headers=headers,
    )
    assert response[0] == 403
    assert decoded(response)["error"]["code"] == code
    assert api_server.workspace.revision == 0
    assert api_server.workspace.language == "ko"


def test_actions_are_atomic_and_revision_conflicts_return_current_revision(api_server):
    initial = decoded(request(api_server, "GET", "/api/v1/workspace"))
    first_id = initial["entries"][0]["id"]

    response = action(api_server, 0, {
        "type": "import_cifs", "mode": "append",
        "files": [file_payload("hbn.cif"), file_payload("mos2.cif")],
    })
    snapshot = decoded(response)
    assert response[0] == 200
    assert snapshot["revision"] == 1
    assert [entry["filename"] for entry in snapshot["entries"]] == [
        "graphene.cif", "hbn.cif", "mos2.cif",
    ]

    response = action(api_server, 1, {
        "type": "patch_workspace", "language": "en", "review_focus": "invalid",
    })
    assert response[0] == 422
    assert api_server.workspace.revision == 1
    assert api_server.workspace.language == "ko"

    response = action(api_server, 1, {
        "type": "patch_entry", "id": first_id, "normal_axis": "c",
        "short_distance": 1.2, "note": "keep this note",
    })
    snapshot = decoded(response)
    assert response[0] == 200
    assert snapshot["revision"] == 2
    assert snapshot["entries"][0]["note"] == "keep this note"

    response = action(api_server, 2, {
        "type": "save_measurement", "id": first_id,
        "selection": {
            "i": 0, "j": 1, "first_shift": [0, 0, 0],
            "second_shift": [1, 0, 0], "mode": "displayed",
        },
    })
    snapshot = decoded(response)
    assert response[0] == 200
    assert len(snapshot["entries"][0]["measurements"]) == 1

    response = action(api_server, 3, {"type": "set_reviewed", "id": first_id, "value": True})
    reviewed = decoded(response)["entries"][0]
    assert reviewed["reviewed"] is True
    assert reviewed["review_current"] is True
    stamp = reviewed["review_stamp"]

    response = action(api_server, 4, {
        "type": "replace_source", "id": first_id, **file_payload("hbn.cif"),
    })
    changed = decoded(response)["entries"][0]
    assert response[0] == 200
    assert changed["id"] == first_id
    assert changed["note"] == "keep this note"
    assert changed["reviewed"] is False
    assert changed["review_stamp"] == stamp
    assert changed["measurements"] == []

    conflict = action(api_server, 4, {"type": "patch_workspace", "language": "en"})
    assert conflict[0] == 409
    assert decoded(conflict)["revision"] == 5
    assert api_server.workspace.language == "ko"

    invalid = action(api_server, 5, {
        "type": "import_cifs", "mode": "append",
        "files": [file_payload("graphene.cif"), {"filename": "bad.cif", "data_base64": "!"}],
    })
    assert invalid[0] in (400, 413)
    assert api_server.workspace.revision == 5
    assert len(api_server.workspace.project.entries) == 3

    remove = action(api_server, 5, {"type": "remove_entry", "id": first_id})
    snapshot = decoded(remove)
    assert remove[0] == 200
    assert len(snapshot["entries"]) == 2
    assert snapshot["project"]["selected_id"] in {entry["id"] for entry in snapshot["entries"]}


def test_read_only_measurement_and_report_downloads_do_not_change_revision(api_server):
    snapshot = decoded(request(api_server, "GET", "/api/v1/workspace"))
    entry_id = snapshot["entries"][0]["id"]
    measurement = request(
        api_server, "POST", "/api/v1/measure",
        {
            "expected_revision": 0, "entry_id": entry_id, "i": 0, "j": 1,
            "first_shift": [0, 0, 0], "second_shift": [1, 0, 0],
        },
        authorized=True,
    )
    result = decoded(measurement)
    assert measurement[0] == 200
    assert {"displayed", "minimum_image"} <= set(result)
    assert result["displayed"]["distance_angstrom"] != result["minimum_image"]["distance_angstrom"]
    assert api_server.workspace.revision == 0

    report_json = request(
        api_server, "GET", f"/api/v1/entries/{entry_id}/report.json?lang=ko"
    )
    assert report_json[0] == 200
    assert decoded(report_json)["report_language"] == "ko"
    assert "attachment" in report_json[1]["Content-Disposition"]

    report_csv = request(
        api_server, "GET", f"/api/v1/entries/{entry_id}/report.csv?lang=en"
    )
    assert report_csv[0] == 200
    assert report_csv[2].startswith(b"record_type,code,severity")
    comparison = request(api_server, "GET", "/api/v1/comparison.csv?lang=en")
    assert comparison[0] == 200
    assert comparison[2].startswith(b"filename,status")

    korean_report = request(
        api_server, "GET", f"/api/v1/entries/{entry_id}/report.csv?lang=ko"
    )
    korean_comparison = request(api_server, "GET", "/api/v1/comparison.csv?lang=ko")
    assert korean_report[2].startswith(b"\xef\xbb\xbf")
    assert korean_comparison[2].startswith(b"\xef\xbb\xbf")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("first_shift", [10, 0, 0]),
        ("second_shift", [-10, 0, 0]),
        ("first_shift", [0.5, 0, 0]),
        ("second_shift", [True, 0, 0]),
        ("first_shift", [0, 0]),
    ],
)
def test_measurement_rejects_unbounded_or_noninteger_image_shifts(api_server, field, value):
    snapshot = decoded(request(api_server, "GET", "/api/v1/workspace"))
    measurement = {
        "expected_revision": snapshot["revision"],
        "entry_id": snapshot["entries"][0]["id"], "i": 0, "j": 1,
        "first_shift": [0, 0, 0], "second_shift": [0, 0, 0],
    }
    measurement[field] = value

    response = request(
        api_server, "POST", "/api/v1/measure", measurement, authorized=True,
    )

    assert response[0] == 400
    assert decoded(response)["error"]["code"] == "invalid_measurement"
    assert api_server.workspace.revision == 0


def test_measurement_rejects_stale_revision_before_using_replaced_entry(api_server):
    original = decoded(request(api_server, "GET", "/api/v1/workspace"))
    entry_id = original["entries"][0]["id"]
    replacement = action(api_server, 0, {
        "type": "replace_source", "id": entry_id, **file_payload("hbn.cif"),
    })
    assert replacement[0] == 200

    body = {
        "expected_revision": 0, "entry_id": entry_id, "i": 0, "j": 1,
        "first_shift": [0, 0, 0], "second_shift": [0, 0, 0],
    }
    stale = request(api_server, "POST", "/api/v1/measure", body, authorized=True)
    assert stale[0] == 409
    assert decoded(stale) == {
        "error": {"code": "revision_conflict", "message": "Workspace revision is stale."},
        "revision": 1,
    }

    body["expected_revision"] = 1
    current = request(api_server, "POST", "/api/v1/measure", body, authorized=True)
    result = decoded(current)
    assert current[0] == 200
    assert result["element_i"] == "B"
    assert result["element_j"] == "N"
    assert api_server.workspace.revision == 1


def test_measurement_contract_requires_expected_revision(api_server):
    snapshot = decoded(request(api_server, "GET", "/api/v1/workspace"))
    response = request(
        api_server, "POST", "/api/v1/measure",
        {
            "entry_id": snapshot["entries"][0]["id"], "i": 0, "j": 1,
            "first_shift": [0, 0, 0], "second_shift": [0, 0, 0],
        },
        authorized=True,
    )
    assert response[0] == 400
    assert decoded(response)["error"]["code"] == "invalid_request"


def test_project_export_and_raw_import_use_current_metadata_and_revision(api_server):
    snapshot = decoded(action(api_server, 0, {
        "type": "patch_workspace", "review_focus": "gap", "filter_mode": "needs_review",
        "progress_filter": "unreviewed", "language": "en",
    }))
    exported = request(api_server, "GET", "/api/v1/project/export")
    assert exported[0] == 200
    project = loads_project(exported[2])
    assert project.review_focus == "gap"
    assert project.filter_mode == "needs_review"
    assert project.progress_filter == "unreviewed"
    assert project.calclens_version != ""
    assert "attachment" in exported[1]["Content-Disposition"]

    wrong = request(
        api_server, "POST", "/api/v1/project/import", exported[2], authorized=True,
        headers={"Content-Type": "application/json", "X-CalcLens-Revision": "0"},
    )
    assert wrong[0] == 409
    assert decoded(wrong)["revision"] == snapshot["revision"]

    historical_document = json.loads(exported[2])
    historical_document["tools"] = {
        "calclens_version": "0.1.0",
        "ase_version": "3.0.0",
        "analysis_revision": "geometry-old",
    }
    historical = json.dumps(historical_document, separators=(",", ":")).encode()

    imported = request(
        api_server, "POST", "/api/v1/project/import", historical, authorized=True,
        headers={"Content-Type": "application/json", "X-CalcLens-Revision": "1"},
    )
    imported_snapshot = decoded(imported)
    assert imported[0] == 200
    assert imported_snapshot["revision"] == 2
    assert imported_snapshot["project"]["review_focus"] == "gap"
    assert imported_snapshot["project"]["calclens_version"] == "0.1.0"
    assert imported_snapshot["project"]["analysis_revision"] == "geometry-old"
    assert imported_snapshot["runtime"] == {
        "calclens_version": __version__,
        "ase_version": ase.__version__,
        "analysis_revision": ANALYSIS_REVISION,
    }


def test_no_cors_chunked_bodies_or_static_path_escape(api_server):
    options = request(api_server, "OPTIONS", "/api/v1/actions")
    assert options[0] == 405
    assert "Access-Control-Allow-Origin" not in options[1]

    escaped = request(api_server, "GET", "/../pyproject.toml")
    assert escaped[0] == 404
    encoded = request(api_server, "GET", "/%2e%2e/pyproject.toml")
    assert encoded[0] == 404

    connection = http.client.HTTPConnection("127.0.0.1", api_server.server_port, timeout=5)
    connection.request(
        "POST", "/api/v1/actions", body=b"{}",
        headers={
            "Host": api_server.expected_host,
            "Origin": f"http://{api_server.expected_host}",
            "X-CalcLens-Token": api_server.token,
            "Transfer-Encoding": "chunked",
            "Content-Type": "application/json",
        },
    )
    response = connection.getresponse()
    body = response.read()
    connection.close()
    assert response.status == 400
    assert json.loads(body)["error"]["code"] == "chunked_not_allowed"


def test_json_content_type_and_single_security_headers_are_enforced(api_server):
    wrong_type = request(
        api_server, "POST", "/api/v1/actions",
        {"expected_revision": 0, "action": {"type": "patch_workspace", "language": "en"}},
        authorized=True, headers={"Content-Type": "text/plain"},
    )
    assert wrong_type[0] == 415
    assert decoded(wrong_type)["error"]["code"] == "unsupported_media_type"

    connection = http.client.HTTPConnection("127.0.0.1", api_server.server_port, timeout=5)
    body = b'{"expected_revision":0,"action":{"type":"patch_workspace","language":"en"}}'
    connection.putrequest("POST", "/api/v1/actions", skip_host=True)
    connection.putheader("Host", api_server.expected_host)
    connection.putheader("Origin", f"http://{api_server.expected_host}")
    connection.putheader("X-CalcLens-Token", api_server.token)
    connection.putheader("X-CalcLens-Token", api_server.token)
    connection.putheader("Content-Type", "application/json")
    connection.putheader("Content-Length", str(len(body)))
    connection.endheaders(body)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    assert response.status == 400
    assert json.loads(data)["error"]["code"] == "invalid_header"
    assert api_server.workspace.revision == 0


def test_only_one_concurrent_request_can_commit_the_same_revision(api_server):
    barrier = threading.Barrier(2)

    def submit(language):
        barrier.wait(timeout=5)
        return action(api_server, 0, {
            "type": "patch_workspace", "language": language,
        })

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(submit, ("en", "ko")))

    assert sorted(response[0] for response in responses) == [200, 409]
    conflict = next(response for response in responses if response[0] == 409)
    assert decoded(conflict)["revision"] == 1
    assert api_server.workspace.revision == 1


def test_run_server_announces_bound_server_and_always_closes(monkeypatch):
    events = []

    class FakeServer:
        expected_host = "127.0.0.1:43123"

        def serve_forever(self):
            events.append("serve")
            raise KeyboardInterrupt

        def server_close(self):
            events.append("close")

    server = FakeServer()
    monkeypatch.setattr(web_api, "create_server", lambda *args: server)

    with pytest.raises(KeyboardInterrupt):
        web_api.run_server(
            ROOT, 0, "ko", lambda url, ready_server: events.append((url, ready_server))
        )

    assert events == [("http://127.0.0.1:43123/", server), "serve", "close"]


def test_cli_prints_ready_url_even_without_browser(monkeypatch, capsys):
    def run(_root, _port, _language, on_ready):
        on_ready("http://127.0.0.1:43124/", object())

    monkeypatch.setattr(web_api, "run_server", run)
    monkeypatch.setattr(web_api.webbrowser, "open", lambda _url: pytest.fail("opened browser"))

    assert web_api.main(["--root", str(ROOT), "--port", "0", "--no-browser"]) == 0
    assert capsys.readouterr().out == "http://127.0.0.1:43124/\n"
