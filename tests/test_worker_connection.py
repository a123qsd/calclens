from contextlib import contextmanager
import http.client
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


def test_deadline_does_not_become_user_cancellation_if_a_timer_wakes_early(monkeypatch):
    class EarlyTimer:
        def __init__(self, interval, callback):
            self.callback = callback

        def start(self):
            self.callback()  # The monotonic response deadline has not elapsed.

        def cancel(self):
            pass

    monkeypatch.setattr(threading, "Timer", EarlyTimer)
    release = threading.Event()

    class Stalled(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            release.wait(6)

        def log_message(self, *_):
            pass

    with serving(HTTPServer(("127.0.0.1", 0), Stalled)) as port:
        cancel = RemoteCancellation()
        config = RemoteComputeConfig(f"http://127.0.0.1:{port}", "c" * 40,
                                     timeout_seconds=1, cancellation=cancel)
        start = time.monotonic()
        try:
            with pytest.raises(ComputeError, match="deadline"):
                remote_capabilities(config)
            assert 1 <= time.monotonic() - start < 3
            cancel.check()  # Only the user may set the user-cancellation state.
        finally:
            release.set()


def test_buffered_response_still_checks_the_total_deadline(monkeypatch):
    clock = [0.0]
    original_read = http.client.HTTPResponse.read

    def delayed_read(response, *args):
        body = original_read(response, *args)
        clock[0] = 2.0  # The buffered body is consumed after the one-second deadline.
        return body

    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(http.client.HTTPResponse, "read", delayed_read)
    monkeypatch.setattr("slab_preflight.compute_server.probe_devices", lambda: [
        {"id": name, "available": True} for name in ("cpu", "metal", "cuda")
    ])
    cancel = RemoteCancellation()
    with serving(make_server(token="c" * 40, device="cpu")) as port:
        config = RemoteComputeConfig(f"http://127.0.0.1:{port}", "c" * 40,
                                     timeout_seconds=1, cancellation=cancel)
        with pytest.raises(ComputeError, match="deadline"):
            remote_capabilities(config)
        cancel.check()
