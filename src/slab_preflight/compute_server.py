"""Explicit authenticated compute worker and a bounded TLS/loopback client.

Nothing listens or connects at import. The worker accepts only numerical
difference/planar requests, never paths, Python code, project archives or commands.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import hmac
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
from pathlib import Path
import ssl
import time
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, ProxyHandler, Request, build_opener

import numpy as np

from .compute_devices import (ComputeError, MAX_GRID_POINTS, MAX_PAIR_VECTORS,
                              _validate_arrays, _validate_vectors, compute_arrays, compute_norms)

MAX_REQUEST_BYTES = 34 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class RemoteComputeConfig:
    url: str
    token: str
    device: str = "auto"
    timeout_seconds: float = 45.0
    ca_file: str | None = None


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


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request: Request, *args: Any, **kwargs: Any) -> None:
        raise ComputeError("Compute worker redirects are refused; configure the final trusted endpoint explicitly.")


def _exchange(request_data: dict[str, Any], config: RemoteComputeConfig
              ) -> tuple[dict[str, Any], dict[str, Any]]:
    endpoint = _endpoint(config)
    body = json.dumps(request_data, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_REQUEST_BYTES:
        raise ComputeError("Compute request exceeds the 34 MiB transfer limit.")
    context = ssl.create_default_context(cafile=config.ca_file)
    opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))
    request = Request(endpoint, data=body, method="POST", headers={
        "Authorization": "Bearer " + config.token, "Content-Type": "application/json",
        "Accept": "application/json"})
    deadline = time.monotonic() + config.timeout_seconds
    try:
        with opener.open(request, timeout=config.timeout_seconds) as response:
            if response.status != 200:
                raise ComputeError(f"Compute worker returned HTTP {response.status}.")
            chunks: list[bytes] = []
            received = 0
            while received <= MAX_RESPONSE_BYTES:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Compute response deadline exceeded.")
                chunk = response.read1(min(65536, MAX_RESPONSE_BYTES + 1 - received))
                if not chunk:
                    break
                chunks.append(chunk)
                received += len(chunk)
            content = b"".join(chunks)
    except HTTPError as error:
        detail = ""
        try:
            explanation = json.loads(error.read(4096))
            if isinstance(explanation, dict) and isinstance(explanation.get("error"), str):
                detail = " " + explanation["error"][:2000].replace(config.token, "[redacted]")
        except (ValueError, UnicodeDecodeError, RecursionError):
            pass
        raise ComputeError(f"Compute worker refused the request (HTTP {error.code}).{detail}") from error
    except (URLError, TimeoutError, OSError) as error:
        raise ComputeError(f"Compute worker connection failed: {error.reason if isinstance(error, URLError) else error}") from error
    if len(content) > MAX_RESPONSE_BYTES:
        raise ComputeError("Compute worker response exceeds the 16 MiB transfer limit.")
    try:
        result = json.loads(content)
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        raise ComputeError("Compute worker returned invalid JSON.") from error
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
        "worker_effective_device": execution["effective_device"], "worker_execution": execution,
        "worker_device_attestation": "reported by the authenticated worker; client independently checks numerical parity",
        "endpoint": endpoint, "request_bytes": len(body), "response_bytes": len(content),
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
        if self.path != "/v1/compute" or self.headers.get("Origin") is not None:
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
            data = self._read_body(length)
            if len(data) != length:
                raise ComputeError("Compute body is incomplete.")
            request = json.loads(data)
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
