"""Single-port HTTP relay with Host-header rewrite. Stdlib only.

Used on macOS to expose the host's Ollama to the enclave network as `model`.
Ollama rejects requests whose Host header isn't localhost-like, so a plain TCP
relay (socat) gets 403s; this forwards HTTP and sets Host to the upstream.

Usage: python3 model-relay.py <listen_port> <upstream_host> <upstream_port>
"""

import http.client
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN_PORT, UP_HOST, UP_PORT = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "host", "content-length"}


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        headers["Host"] = f"{UP_HOST}:{UP_PORT}"
        if body is not None:
            headers["Content-Length"] = str(len(body))
        up = http.client.HTTPConnection(UP_HOST, UP_PORT, timeout=600)
        try:
            up.request(self.command, self.path, body=body, headers=headers)
            resp = up.getresponse()
            self.send_response(resp.status, resp.reason)
            for k, v in resp.getheaders():
                if k.lower() not in HOP_BY_HOP:
                    self.send_header(k, v)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while chunk := resp.read(65536):  # streams SSE/chunked upstreams too
                self.wfile.write(f"{len(chunk):x}\r\n".encode() + chunk + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
        except OSError as exc:
            self.send_error(502, f"upstream error: {exc}")
        finally:
            up.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_OPTIONS = do_HEAD = _forward

    def log_message(self, fmt, *args):  # keep container logs quiet
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", LISTEN_PORT), Relay).serve_forever()
