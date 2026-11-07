from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import socket
import threading
import time
import pytest

from slab_preflight.compute_server import (
    ComputeError, RemoteCancellation, RemoteComputeConfig, make_server, remote_capabilities,
)


@contextmanager
def serving(server):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
    thread.start()
    try:
        yield server.server_port
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_authenticated_connection_reports_real_probes_and_worker_policy_without_project_data(monkeypatch):
    calls = []
    def test_devices():
        calls.append("small arrays")
        return [{"id": name, "available": True} for name in ("cpu", "metal", "cuda")]
    monkeypatch.setattr("slab_preflight.compute_server.probe_devices", test_devices)
    token = secrets.token_urlsafe(36)
    with serving(make_server(token=token, device="cpu")) as port:
        config = RemoteComputeConfig(f"http://127.0.0.1:{port}", token)
        result = remote_capabilities(config)
        assert calls == ["small arrays"]
        assert result["policy"] == "cpu"
        assert [(d["id"], d["available"]) for d in result["devices"]] == [
            ("cpu", True), ("metal", False), ("cuda", False)]
        assert config.token not in repr(config)
        with pytest.raises(ComputeError, match="401"):
            remote_capabilities(RemoteComputeConfig(config.url, "x" * 40))
        assert calls == ["small arrays"]


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("phase", ["headers", "body"])
@pytest.mark.parametrize("shutdown_wakes_read", [False, True])
def test_timeout_and_cancel_interrupt_a_worker_that_never_answers(
    manual, phase, shutdown_wakes_read, monkeypatch
):
    if not shutdown_wakes_read:
        # Winsock shutdown does not reliably wake an already waiting select().
        # Cancellation must work independently of this best-effort interrupt.
        monkeypatch.setattr(socket.socket, "shutdown", lambda *_: None)
    arrived, release = threading.Event(), threading.Event()
    class Stalled(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            if phase == "body":
                self.send_response(200)
                self.send_header("Content-Length", "32")
                self.end_headers()
                self.wfile.flush()
            arrived.set()
            release.wait(6)
        def log_message(self, *_):
            pass
    with serving(HTTPServer(("127.0.0.1", 0), Stalled)) as port:
        cancel = RemoteCancellation()
        errors = []
        config = RemoteComputeConfig(f"http://127.0.0.1:{port}", "c" * 40,
                                     timeout_seconds=10 if manual else 1, cancellation=cancel)
        def check():
            try:
                remote_capabilities(config)
            except Exception as error:
                errors.append(str(error))
        thread = threading.Thread(target=check)
        thread.start()
        try:
            assert arrived.wait(2)
            start = time.monotonic()
            if manual:
                cancel.cancel()
            thread.join(timeout=3)
            assert not thread.is_alive()
            assert time.monotonic() - start < 3
            assert len(errors) == 1 and ("cancelled" if manual else "deadline") in errors[0]
        finally:
            release.set()
            thread.join(timeout=3)
