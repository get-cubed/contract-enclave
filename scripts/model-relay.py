"""Inference-only HTTP relay with a localhost Host-header rewrite.

The workspace needs exactly two Ollama endpoints: model discovery and OpenAI-
compatible chat completions. Ollama's management API can pull/push models and
must not be reachable across the enclave boundary, so every other path and
method is rejected before an upstream connection is opened.

Usage: python3 model-relay.py <listen_port> <upstream_host> <upstream_port>
"""

from __future__ import annotations

import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

ALLOWED_REQUESTS = {
    ("GET", "/v1/models"),
    ("POST", "/v1/chat/completions"),
}
BASE_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}
MAX_REQUEST_BYTES = 64 * 1024 * 1024


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, server_address, handler, upstream_host: str, upstream_port: int):
        super().__init__(server_address, handler)
        self.upstream_host = upstream_host
        self.upstream_port = upstream_port


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def relay_server(self) -> RelayServer:
        return self.server  # type: ignore[return-value]

    def _forward(self):
        path = urlsplit(self.path).path
        if (self.command, path) not in ALLOWED_REQUESTS:
            self.send_error(403, "endpoint not allowed by enclave relay")
            return

        # BaseHTTPRequestHandler does not decode chunked request bodies. Fail
        # closed instead of forwarding an empty request while unread chunks
        # remain on the client connection.
        if self.headers.get("Transfer-Encoding"):
            self.close_connection = True
            self.send_error(400, "Transfer-Encoding is not supported")
            return

        raw_length = self.headers.get("Content-Length")
        try:
            length = int(raw_length or 0)
        except ValueError:
            self.send_error(400, "invalid Content-Length")
            return
        if length < 0 or length > MAX_REQUEST_BYTES:
            self.send_error(413, "request body too large")
            return

        body = self.rfile.read(length) if length else None
        connection_tokens = {
            token.strip().lower()
            for token in self.headers.get("Connection", "").split(",")
            if token.strip()
        }
        blocked_headers = BASE_HOP_BY_HOP | connection_tokens
        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in blocked_headers
        }
        # Connect to host.docker.internal (or another supplied address), but
        # identify the request as localhost so Ollama accepts it consistently.
        headers["Host"] = f"localhost:{self.relay_server.upstream_port}"
        if body is not None:
            headers["Content-Length"] = str(len(body))

        upstream = http.client.HTTPConnection(
            self.relay_server.upstream_host,
            self.relay_server.upstream_port,
            timeout=600,
        )
        try:
            upstream.request(self.command, self.path, body=body, headers=headers)
            response = upstream.getresponse()
            self.send_response(response.status, response.reason)
            response_connection_tokens = {
                token.strip().lower()
                for token in (response.getheader("Connection") or "").split(",")
                if token.strip()
            }
            blocked_response_headers = BASE_HOP_BY_HOP | response_connection_tokens
            for key, value in response.getheaders():
                if key.lower() not in blocked_response_headers:
                    self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while chunk := response.read(65536):
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except OSError as exc:
            self.send_error(502, f"upstream error: {exc}")
        finally:
            upstream.close()

    do_GET = do_POST = _forward

    def _reject_method(self):
        self.send_error(405, "method not allowed by enclave relay")

    do_PUT = do_DELETE = do_OPTIONS = do_PATCH = do_HEAD = _reject_method

    def log_message(self, fmt, *args):
        pass


def serve(listen_port: int, upstream_host: str, upstream_port: int) -> None:
    RelayServer(("0.0.0.0", listen_port), Relay, upstream_host, upstream_port).serve_forever()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        print("Usage: model-relay.py <listen_port> <upstream_host> <upstream_port>", file=sys.stderr)
        return 2
    try:
        listen_port, upstream_port = int(args[0]), int(args[2])
    except ValueError:
        print("listen_port and upstream_port must be integers", file=sys.stderr)
        return 2
    if not 1 <= listen_port <= 65535 or not 1 <= upstream_port <= 65535:
        print("ports must be between 1 and 65535", file=sys.stderr)
        return 2
    serve(listen_port, args[1], upstream_port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
