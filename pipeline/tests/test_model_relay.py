"""Security-boundary tests for the inference-only Ollama relay."""

import http.client
import importlib.util
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _load_relay_module():
    path = Path(__file__).parents[2] / "scripts" / "model-relay.py"
    spec = importlib.util.spec_from_file_location("model_relay", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


relay = _load_relay_module()


class _Upstream(BaseHTTPRequestHandler):
    requests = []

    def _respond(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        self.requests.append((self.command, self.path, dict(self.headers), body))
        payload = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    do_GET = do_POST = _respond

    def log_message(self, fmt, *args):
        pass


@contextmanager
def _servers():
    _Upstream.requests = []
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), _Upstream)
    proxy = relay.RelayServer(
        ("127.0.0.1", 0), relay.Relay, "127.0.0.1", upstream.server_port
    )
    threads = [
        threading.Thread(target=upstream.serve_forever, daemon=True),
        threading.Thread(target=proxy.serve_forever, daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        yield proxy.server_port
    finally:
        proxy.shutdown()
        upstream.shutdown()
        proxy.server_close()
        upstream.server_close()
        for thread in threads:
            thread.join(timeout=2)


def test_relay_forwards_only_required_openai_endpoints_and_rewrites_host():
    with _servers() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request("GET", "/v1/models", headers={"Connection": "x-remove", "X-Remove": "secret"})
        response = client.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"ok": True}

        body = b'{"model":"local"}'
        client.request("POST", "/v1/chat/completions", body=body,
                       headers={"Content-Type": "application/json"})
        response = client.getresponse()
        assert response.status == 200
        response.read()
        client.close()

    assert [request[:2] for request in _Upstream.requests] == [
        ("GET", "/v1/models"),
        ("POST", "/v1/chat/completions"),
    ]
    assert _Upstream.requests[0][2]["Host"].startswith("localhost:")
    assert "X-Remove" not in _Upstream.requests[0][2]
    assert _Upstream.requests[1][3] == body


def test_relay_blocks_ollama_management_api_without_touching_upstream():
    with _servers() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request("POST", "/api/pull", body=b'{"model":"anything"}')
        response = client.getresponse()
        assert response.status == 403
        response.read()
        client.close()
    assert _Upstream.requests == []


def test_relay_rejects_unneeded_methods_and_oversized_requests():
    with _servers() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.request("DELETE", "/v1/models")
        response = client.getresponse()
        assert response.status == 405
        response.read()

        client.putrequest("POST", "/v1/chat/completions")
        client.putheader("Content-Length", str(relay.MAX_REQUEST_BYTES + 1))
        client.endheaders()
        response = client.getresponse()
        assert response.status == 413
        response.read()
        client.close()
    assert _Upstream.requests == []


def test_relay_rejects_chunked_requests_before_contacting_upstream():
    with _servers() as port:
        client = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        client.putrequest("POST", "/v1/chat/completions")
        client.putheader("Transfer-Encoding", "chunked")
        client.endheaders()
        response = client.getresponse()
        assert response.status == 400
        response.read()
        client.close()
    assert _Upstream.requests == []


def test_relay_cli_rejects_bad_arguments():
    assert relay.main([]) == 2
    assert relay.main(["not-a-port", "localhost", "11434"]) == 2
    assert relay.main(["0", "localhost", "11434"]) == 2
