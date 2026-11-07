from contextlib import contextmanager
import json
import secrets
import platform
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import numpy as np
import pytest

from slab_preflight.compute_devices import (ComputeError, compute_arrays,
                                            minimum_image_pair_distances, probe_devices)
from slab_preflight.compute_server import (MAX_REQUEST_BYTES, RemoteComputeConfig,
                                           make_server, remote_arrays)


@contextmanager
def worker(device="cpu"):
    token = secrets.token_urlsafe(32)
    server = make_server(token=token, device=device)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield RemoteComputeConfig(f"http://127.0.0.1:{server.server_port}", token, device=device), server
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_actual_authenticated_loopback_roundtrip_computes_difference_and_planes():
    a = np.arange(120).reshape((4, 5, 6)).astype(float)
    with worker() as (config, _):
        values, planes, execution = compute_arrays([a, a * .25, a * .5],
                                                    axis=1, device="remote", remote=config)
        np.testing.assert_allclose(values, a * .25)
        np.testing.assert_allclose(planes, (a * .25).mean(axis=(0, 2)))
        assert execution["effective_device"] == "remote"
        assert execution["worker_effective_device"] == "cpu"
        assert execution["parity"]["passed"] is True
        assert "project" not in execution["transfer_scope"]
        _, plane_only, metadata = remote_arrays([a], axis=0, config=config)
        np.testing.assert_allclose(plane_only, a.mean(axis=(1, 2)))
        assert metadata["request_bytes"] > 0
        pairs = minimum_image_pair_distances([[0, 0, 0], [4.9, 0, 0]], np.eye(3) * 5,
                                             device="remote", remote=config)
        assert pairs["pairs"][0]["distance_angstrom"] == pytest.approx(.1)
        assert pairs["execution"]["worker_effective_device"] == "cpu"
        assert "anonymous displacement" in pairs["execution"]["transfer_scope"]


def test_worker_rejects_wrong_authentication_origin_unbounded_and_extra_request_fields():
    with worker() as (config, _):
        with pytest.raises(ComputeError, match="HTTP 401"):
            remote_arrays([np.ones((2, 2, 2))], axis=2,
                          config=RemoteComputeConfig(config.url, "x" * 40, device="cpu"))
        endpoint = config.url + "/v1/compute"
        for body, extra, status in [
            ({}, {"Origin": "https://example.com"}, 404),
            ({"execute": "untrusted"}, {}, 400),
            ({"protocol_version": 1, "operation": "planar", "shape": [1_000_000] * 3,
              "axis": 2, "device": "cpu", "arrays": [""]}, {}, 400),
        ]:
            request = Request(endpoint, data=json.dumps(body).encode(), headers={
                "Authorization": "Bearer " + config.token, "Content-Type": "application/json", **extra})
            with pytest.raises(HTTPError) as error:
                urlopen(request, timeout=5)
            assert error.value.code == status


@pytest.mark.parametrize("url", ["http://worker.example.com", "http://localhost:8888",
                                 "ftp://127.0.0.1", "https://name:secret@example.com",
                                 "https://example.com/other", "https://example.com?token=x"])
def test_remote_endpoint_validation_rejects_unsafe_urls_before_network(url):
    with pytest.raises(ComputeError):
        remote_arrays([np.ones((2, 2, 2))], axis=2,
                      config=RemoteComputeConfig(url, "x" * 40))


def test_public_plaintext_bind_and_weak_token_are_rejected():
    with pytest.raises(ComputeError, match="TLS"):
        make_server(host="0.0.0.0", token="x" * 40)
    with pytest.raises(ComputeError, match="authentication"):
        make_server(token="short")


def test_oversized_declared_request_is_refused_without_waiting_for_a_body():
    with worker() as (config, server):
        connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        connection.putrequest("POST", "/v1/compute")
        connection.putheader("Authorization", "Bearer " + config.token)
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(MAX_REQUEST_BYTES + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        response.read()
        connection.close()


def test_worker_redirect_is_rejected_before_any_destination_contact():
    class Redirect(BaseHTTPRequestHandler):
        def do_POST(self):
            # Consume the POST so Winsock can deliver the redirect before closing.
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(307)
            self.send_header("Location", "https://example.invalid/not-contacted")
            self.end_headers()

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), Redirect)
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        config = RemoteComputeConfig(f"http://127.0.0.1:{server.server_port}", "x" * 40)
        with pytest.raises(ComputeError, match="redirects are refused"):
            remote_arrays([np.ones((2, 2, 2))], axis=2, config=config)
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


@pytest.mark.skipif(platform.system() != "Darwin", reason="Actual Metal worker requires macOS")
def test_actual_authenticated_worker_executes_metal_density_and_norm_kernels():
    if not next(item for item in probe_devices() if item["id"] == "metal")["available"]:
        pytest.skip("No Metal compute device/helper")
    data = np.arange(24).reshape((2, 3, 4)).astype(float)
    with worker("metal") as (config, _):
        values, _, execution = compute_arrays([data, data * .25, data * .5],
                                               device="remote", remote=config)
        np.testing.assert_allclose(values, data * .25)
        assert execution["worker_effective_device"] == "metal"
        pairs = minimum_image_pair_distances([[0, 0, 0], [4.9, 0, 0]], np.eye(3) * 5,
                                             device="remote", remote=config)
        assert pairs["execution"]["worker_effective_device"] == "metal"
        assert pairs["pairs"][0]["distance_angstrom"] == pytest.approx(.1)
