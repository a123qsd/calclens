"""Explicit authenticated compute worker and a bounded TLS/loopback client.

Nothing listens or connects at import. The worker accepts only numerical
difference/planar requests, never paths, Python code, project archives or commands.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
import hmac
import http.client
import io
import select
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import time
from typing import Any, Sequence
from urllib.parse import urlsplit

import numpy as np

from .compute_devices import (ComputeError, MAX_GRID_POINTS, MAX_PAIR_VECTORS,
                              _validate_arrays, _validate_vectors, compute_arrays, compute_norms, probe_devices)

MAX_REQUEST_BYTES = 34 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PROTOCOL_VERSION = 1


class RemoteCancellation:
    """Interrupt client I/O; an already submitted bounded worker kernel may finish."""
    def __init__(self):
        self._lock = threading.Lock()
        self._cancelled = False
        self._socket = None

    def attach(self, sock):
        with self._lock:
            if self._cancelled:
                raise ComputeError("Remote request cancelled.")
            self._socket = sock

    def cancel(self):
        with self._lock:
            self._cancelled = True
            if self._socket is not None:
                try:
                    self._socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def detach(self):
        with self._lock:
            self._socket = None

    def check(self):
        with self._lock:
            if self._cancelled:
                raise ComputeError("Remote request cancelled.")


class _RemoteReader(io.RawIOBase):
    def __init__(self, transport):
        super().__init__()
        self.transport = transport
        # Retain the socket's normal makefile reference: HTTPConnection may
        # close its socket before an HTTP/1.0 response body has been consumed.
        self.raw = transport.sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        return self.transport.perform(lambda: self.raw.readinto(buffer))

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _RemoteTransport:
    """Keep HTTP buffering while bounding every wait for plain or TLS I/O.

    Winsock shutdown need not wake a socket's existing timeout/select wait.
    Nonblocking operations and short readiness polls check cancellation directly;
    a timeout never escapes into a makefile buffer that cannot safely be retried.
    """
    def __init__(self, sock, cancel, deadline):
        self.sock, self.cancel, self.deadline = sock, cancel, deadline
        sock.setblocking(False)

    def perform(self, operation, *, writing=False):
        while True:
            if time.monotonic() >= self.deadline:
                raise TimeoutError("Compute worker response deadline exceeded.")
            self.cancel.check()
            try:
                value = operation()
                if value is not None:
                    return value
                wait_write = writing  # SocketIO returns None when a read would block.
            except ssl.SSLWantReadError:
                wait_write = False
            except ssl.SSLWantWriteError:
                wait_write = True
            except BlockingIOError:
                wait_write = writing
            seconds = min(0.1, max(0, self.deadline - time.monotonic()))
            select.select([] if wait_write else [self.sock], [self.sock] if wait_write else [], [], seconds)

    def sendall(self, data):
        remaining = memoryview(data)
        while remaining:
            sent = self.perform(lambda: self.sock.send(remaining), writing=True)
            if sent == 0:
                raise ConnectionError("Compute worker closed the connection during upload.")
            remaining = remaining[sent:]

    def makefile(self, mode):
        if mode != "rb":
            raise ValueError("Compute responses require binary reads.")
        return io.BufferedReader(_RemoteReader(self))

    def close(self):
        self.sock.close()


@dataclass(frozen=True)
class RemoteComputeConfig:
    url: str
    token: str = field(repr=False)
    device: str = "auto"
    timeout_seconds: float = 45.0
    ca_file: str | None = None
    cancellation: RemoteCancellation | None = field(default=None, repr=False, compare=False)


def _loopback(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _token(token: str) -> None:
    if not isinstance(token, str) or not 32 <= len(token) <= 512 or any(
            character.isspace() or ord(character) < 33 or ord(character) > 126 for character in token):
        raise ComputeError("Compute authentication requires a 32–512 character printable token without spaces.")


def _endpoint(config: RemoteComputeConfig) -> str:
    _token(config.token)
    parsed = urlsplit(config.url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {"", "/", "/v1/compute"}):
        raise ComputeError("Use a compute-worker base URL or /v1/compute endpoint without credentials, query or fragment.")
    if parsed.scheme == "http" and not _loopback(parsed.hostname):
        raise ComputeError("Unencrypted compute is restricted to an explicit loopback IP; remote workers require verified HTTPS.")
    if config.device not in {"cpu", "auto", "metal", "cuda"}:
        raise ComputeError("A worker device must be cpu, auto, metal or cuda.")
    if not 1 <= config.timeout_seconds <= 120:
        raise ComputeError("Remote compute timeout must be between 1 and 120 seconds.")
    return config.url.rstrip("/") if parsed.path == "/v1/compute" else config.url.rstrip("/") + "/v1/compute"


def _encode_array(array: np.ndarray) -> str:
    return base64.b64encode(np.asarray(array, dtype="<f8").tobytes()).decode("ascii")


def _decode_array(encoded: Any, shape: tuple[int, ...]) -> np.ndarray:
    size = int(np.prod(shape))
    if not isinstance(encoded, str) or len(encoded) != 4 * ((size * 8 + 2) // 3):
        raise ComputeError("Worker array encoding length disagrees with its bounded shape.")
    try:
        payload = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error) as error:
        raise ComputeError("Worker array is not valid base64.") from error
    if len(payload) != size * 8:
        raise ComputeError("Worker array byte count disagrees with its shape.")
    array = np.frombuffer(payload, dtype="<f8").reshape(shape)
    if not np.isfinite(array).all():
        raise ComputeError("Worker arrays must contain finite float64 values.")
    return array


def _post(request_data, config, *, capabilities=False):
    endpoint = _endpoint(config)
    target = urlsplit(endpoint)
    body = json.dumps(request_data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ComputeError("Compute request exceeds the 34 MiB transfer limit.")
    if target.scheme == "https":
        connection = http.client.HTTPSConnection(target.hostname, target.port, timeout=config.timeout_seconds,
                                                  context=ssl.create_default_context(cafile=config.ca_file))
    else:
        connection = http.client.HTTPConnection(target.hostname, target.port, timeout=config.timeout_seconds)
    cancel = config.cancellation or RemoteCancellation()
    deadline = time.monotonic() + config.timeout_seconds
    timer = threading.Timer(config.timeout_seconds, cancel.cancel)
    timer.daemon = True
    timer.start()
    try:
        cancel.check()
        connection.connect()
        cancel.attach(connection.sock)
        connection.sock = _RemoteTransport(connection.sock, cancel, deadline)
        path = "/v1/capabilities" if capabilities else target.path
        connection.request("POST", path, body, headers={"Authorization": "Bearer " + config.token,
                           "Content-Type": "application/json", "Accept": "application/json"})
        with connection.getresponse() as response:
            if 300 <= response.status < 400:
                raise ComputeError("Compute worker redirects are refused; configure the final trusted endpoint explicitly.")
            if response.status != 200:
                detail = ""
                try:
                    error = json.loads(response.read(4096))
                    if isinstance(error.get("error"), str):
                        detail = " " + error["error"][:2000].replace(config.token, "[redacted]")
                except (ValueError, UnicodeDecodeError, AttributeError, RecursionError):
                    pass
                raise ComputeError(f"Compute worker refused the request (HTTP {response.status}).{detail}")
            limit = 32 * 1024 if capabilities else MAX_RESPONSE_BYTES
            content = response.read(limit + 1)
            if len(content) > limit:
                raise ComputeError("Compute worker response exceeds the transfer limit.")
        cancel.check()
    except (OSError, http.client.HTTPException, ComputeError) as error:
        if time.monotonic() >= deadline or isinstance(error, TimeoutError):
            raise ComputeError("Compute worker response deadline exceeded.") from error
        cancel.check()
        if isinstance(error, ComputeError):
            raise
        raise ComputeError(f"Compute worker connection failed: {error}") from error
    finally:
        timer.cancel()
        cancel.detach()
        connection.close()
    try:
        # Untrusted workers must never echo a local bearer credential into an archive.
        result = json.loads(content)
        if json.dumps(config.token, ensure_ascii=False)[1:-1] in json.dumps(result, ensure_ascii=False):
            raise ComputeError("Compute worker included a credential in its reply.")
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ComputeError("Compute worker returned invalid JSON or unsafe metadata.") from error
    return result, endpoint, len(body), len(content)


def remote_capabilities(config: RemoteComputeConfig) -> dict:
    result, _, _, _ = _post({"protocol_version": PROTOCOL_VERSION}, config, capabilities=True)
    if (not isinstance(result, dict) or result.get("protocol_version") != PROTOCOL_VERSION
            or result.get("policy") not in {"auto", "cpu", "metal", "cuda"}
            or not isinstance(result.get("devices"), list) or len(result["devices"]) != 3):
        raise ComputeError("Worker returned an unsupported capabilities response.")
    seen = set()
    for item in result["devices"]:
        if (not isinstance(item, dict) or item.get("id") not in {"cpu", "metal", "cuda"}
                or item["id"] in seen or type(item.get("available")) is not bool):
            raise ComputeError("Worker returned invalid device capability details.")
        seen.add(item["id"])
    return result


def _exchange(request_data: dict[str, Any], config: RemoteComputeConfig
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    result, endpoint, request_bytes, response_bytes = _post(request_data, config)
    if not isinstance(result, dict) or set(result) != {"protocol_version", "shape", "values", "averages", "execution"}:
        raise ComputeError("Compute worker returned an unsupported response schema.")
    if result["protocol_version"] != PROTOCOL_VERSION or result["shape"] != request_data["shape"]:
        raise ComputeError("Compute worker response protocol or shape disagrees with this request.")
    execution = result["execution"]
    if (not isinstance(execution, dict) or not isinstance(execution.get("effective_device"), str)
            or execution["effective_device"] not in {"cpu", "metal", "cuda"}
            or execution.get("precision") not in {"float32", "float64"}):
        raise ComputeError("Compute worker did not identify its actual local device.")
    return result, {"device_name": str(execution.get("device_name", "worker")),
        "precision": execution.get("precision", "float64"),
        "implementation": "authenticated per-request remote worker",
        "worker_effective_device": execution["effective_device"], "requested_worker_device": config.device,
        "worker_execution": execution,
        "worker_device_attestation": "reported by the authenticated worker; client independently checks numerical parity",
        "endpoint": endpoint, "request_bytes": request_bytes, "response_bytes": response_bytes,
        "transfer_scope": "this request's float64 numerical arrays, shape, axis and requested worker device only"}


def remote_arrays(arrays: Sequence[np.ndarray], *, axis: int,
                  config: RemoteComputeConfig) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    """Contact one explicitly selected worker; transmit only this request's fields."""
    arrays = _validate_arrays(arrays, axis)
    result, metadata = _exchange({"protocol_version": PROTOCOL_VERSION,
        "operation": "difference_planar" if len(arrays) == 3 else "planar",
        "shape": list(arrays[0].shape), "axis": axis, "device": config.device,
        "arrays": [_encode_array(array) for array in arrays]}, config)
    values = _decode_array(result["values"], arrays[0].shape)
    averages = _decode_array(result["averages"], (arrays[0].shape[axis],))
    return values, averages, metadata


def remote_norms(vectors: np.ndarray, *, config: RemoteComputeConfig
                 ) -> tuple[np.ndarray, dict[str, Any]]:
    """Transmit anonymous displacements; no atom identity, CIF or project is sent."""
    vectors = _validate_vectors(vectors)
    result, metadata = _exchange({"protocol_version": PROTOCOL_VERSION,
        "operation": "norms", "shape": list(vectors.shape), "axis": 0,
        "device": config.device, "arrays": [_encode_array(vectors)]}, config)
    values = _decode_array(result["values"], (len(vectors),))
    _decode_array(result["averages"], (0,))
    metadata["transfer_scope"] = "this request's anonymous displacement vectors, shape and requested worker device only"
    return values, metadata


class ComputeHTTPServer(HTTPServer):
    """Single active job bounds concurrency and resident worker arrays."""
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, token: str, device: str,
                 tls_context: ssl.SSLContext | None = None) -> None:
        _token(token)
        if not _loopback(address[0]) and tls_context is None:
            raise ComputeError("A non-loopback worker bind requires an explicit TLS certificate/context.")
        if device not in {"cpu", "auto", "metal", "cuda"}:
            raise ComputeError("Worker device must be cpu, auto, metal or cuda.")
        self.auth_token = token
        self.compute_device = device
        self.tls_context = tls_context
        super().__init__(address, _ComputeHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(20)
        try:
            if self.tls_context is not None:
                connection = self.tls_context.wrap_socket(connection, server_side=True)
            return connection, address
        except Exception:
            connection.close()
            raise


class _ComputeHandler(BaseHTTPRequestHandler):
    server: ComputeHTTPServer
    protocol_version = "HTTP/1.0"
    server_version = "CalcLensCompute/1"

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(20)

    def log_message(self, format: str, *args: Any) -> None:
        # Neither authorization values nor scientific payloads enter access logs.
        pass

    def _send(self, status: int, value: dict) -> None:
        payload = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def _read_body(self, length: int) -> bytes:
        deadline = time.monotonic() + 20
        chunks: list[bytes] = []
        remaining = length
        while remaining:
            seconds = deadline - time.monotonic()
            if seconds <= 0:
                raise TimeoutError("Compute body deadline exceeded.")
            self.connection.settimeout(seconds)
            chunk = self.rfile.read1(min(65536, remaining))
            if not chunk:
                raise ComputeError("Compute body is incomplete.")
            chunks.append(chunk)
            remaining -= len(chunk)
        self.connection.settimeout(20)
        return b"".join(chunks)

    def do_POST(self) -> None:
        authorization = self.headers.get("Authorization", "")
        if not hmac.compare_digest(authorization.encode(), ("Bearer " + self.server.auth_token).encode()):
            self._send(401, {"error": "Authentication required."})
            return
        if self.path not in {"/v1/compute", "/v1/capabilities"} or self.headers.get("Origin") is not None:
            self._send(404, {"error": "Unsupported compute endpoint or browser-origin request."})
            return
        if self.headers.get("Transfer-Encoding") is not None or self.headers.get_content_type() != "application/json":
            self._send(415, {"error": "Use bounded JSON with an explicit Content-Length."})
            return
        try:
            length = int(self.headers.get("Content-Length", "-1"))
            if not 1 <= length <= MAX_REQUEST_BYTES:
                self._send(413, {"error": "Compute request exceeds the bounded body limit."})
                return
            if self.path == "/v1/capabilities" and length > 128:
                self._send(413, {"error": "Capabilities requests take only a protocol version."})
                return
            data = self._read_body(length)
            if len(data) != length:
                raise ComputeError("Compute body is incomplete.")
            request = json.loads(data)
            if self.path == "/v1/capabilities":
                if request != {"protocol_version": PROTOCOL_VERSION}:
                    raise ComputeError("Capabilities requests take only a protocol version.")
                devices = probe_devices()
                policy = self.server.compute_device
                for device in devices:
                    if policy not in ("auto", device["id"]):
                        device.update(available=False, reason="Disabled by this worker's device policy.")
                self._send(200, {"protocol_version": PROTOCOL_VERSION, "policy": policy, "devices": devices})
                return
            expected = {"protocol_version", "operation", "shape", "axis", "device", "arrays"}
            if not isinstance(request, dict) or set(request) != expected or request["protocol_version"] != PROTOCOL_VERSION:
                raise ComputeError("Unsupported compute request schema.")
            operation = request["operation"]
            if operation not in {"planar", "difference_planar", "norms"}:
                raise ComputeError("Worker accepts only planar, difference_planar or vector-norm workloads.")
            shape = request["shape"]
            if not isinstance(shape, list) or any(isinstance(value, bool) or not isinstance(value, int) for value in shape):
                raise ComputeError("Worker shape must be a bounded integer list.")
            if operation == "norms":
                if len(shape) != 2 or shape[1] != 3 or not 1 <= shape[0] <= MAX_PAIR_VECTORS:
                    raise ComputeError("Worker norms require 1–80,000 displacement three-vectors.")
            elif (len(shape) != 3 or any(not 2 <= value <= MAX_GRID_POINTS for value in shape)
                  or int(np.prod(shape, dtype=object)) > MAX_GRID_POINTS):
                raise ComputeError("Worker grid exceeds the supported bounded dimensions.")
            encoded = request["arrays"]
            count = 3 if operation == "difference_planar" else 1
            if not isinstance(encoded, list) or len(encoded) != count:
                raise ComputeError("Compute source-array count does not match its operation.")
            arrays = [_decode_array(value, tuple(shape)) for value in encoded]
            requested_device = request["device"]
            if requested_device not in {"cpu", "auto", "metal", "cuda"}:
                raise ComputeError("Worker device must be cpu, auto, metal or cuda.")
            if self.server.compute_device != "auto" and requested_device not in {"auto", self.server.compute_device}:
                raise ComputeError("The requested device is not enabled on this worker.")
            selected = self.server.compute_device if self.server.compute_device != "auto" else requested_device
            if operation == "norms":
                if request["axis"] != 0:
                    raise ComputeError("Vector norms use protocol axis 0.")
                values, execution = compute_norms(arrays[0], device=selected)
                averages = np.empty(0, dtype=np.float64)
            else:
                values, averages, execution = compute_arrays(arrays, axis=request["axis"], device=selected)
            response = {"protocol_version": PROTOCOL_VERSION, "shape": shape,
                        "values": _encode_array(values), "averages": _encode_array(averages),
                        "execution": execution}
            self._send(200, response)
        except (ComputeError, ValueError, TypeError, OverflowError, KeyError, RecursionError) as error:
            self._send(400, {"error": str(error)[:2000]})
        except (TimeoutError, ConnectionError):
            self.close_connection = True


def make_server(*, host: str = "127.0.0.1", port: int = 0, token: str,
                device: str = "auto", tls_context: ssl.SSLContext | None = None) -> ComputeHTTPServer:
    """Construct an inert server; the explicit caller must invoke serve_forever()."""
    return ComputeHTTPServer((host, port), token=token, device=device, tls_context=tls_context)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit CalcLens density compute worker; no files or code execution.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "auto", "metal", "cuda"), default="auto")
    parser.add_argument("--certificate", type=Path)
    parser.add_argument("--private-key", type=Path)
    arguments = parser.parse_args(argv)
    token = arguments.token_file.read_text().strip()
    context = None
    if arguments.certificate or arguments.private_key:
        if not arguments.certificate or not arguments.private_key:
            parser.error("Both --certificate and --private-key are required for TLS.")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(arguments.certificate, arguments.private_key)
    with make_server(host=arguments.host, port=arguments.port, token=token,
                     device=arguments.device, tls_context=context) as server:
        print(f"Explicit compute worker listening on {arguments.host}:{server.server_port}; device={arguments.device}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
