"""End to end: a real mitmdump with the addon between an HTTP client and a local upstream server."""
import gzip
import http.client
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import ROOT

pytestmark = pytest.mark.e2e


def find_mitmdump() -> str | None:
    scripts = Path(sys.executable).parent
    for name in ("mitmdump.exe", "mitmdump"):
        if (scripts / name).exists():
            return str(scripts / name)
    return shutil.which("mitmdump")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Upstream:
    """The "real server": answers 200 with a JSON echo (gzipped for paths with "/gzip"),
    counts the requests it got and keeps them as it saw them."""

    def __init__(self):
        self.hits: list[str] = []
        self.requests: list[dict] = []
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            def _reply(self):
                upstream.hits.append(f"{self.command} {self.path}")
                length = int(self.headers.get("Content-Length") or 0)
                upstream.requests.append({
                    "method": self.command, "path": self.path,
                    "headers": dict(self.headers), "body": self.rfile.read(length),
                })
                body = json.dumps({"real": True, "method": self.command, "path": self.path}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                if "/gzip" in self.path:
                    body = gzip.compress(body)
                    self.send_header("Content-Encoding", "gzip")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            do_GET = do_POST = do_PUT = do_DELETE = _reply

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class Proxy:
    def __init__(self, tmp_path: Path, rules, extra_args=()):
        self.rules_path = tmp_path / "rules.json"
        self._mtime = time.time()
        self.write_rules(rules)
        self.log_path = tmp_path / "mitmdump.log"
        self.port = free_port()
        exe = find_mitmdump()
        if not exe:
            pytest.skip("mitmdump not found (pip install -r requirements-dev.txt)")
        self._log = open(self.log_path, "w", encoding="utf-8", errors="replace")
        self.proc = subprocess.Popen(
            [exe, "-p", str(self.port), "--listen-host", "127.0.0.1",
             *extra_args,
             "-s", str(ROOT / "addons" / "mock_errors.py"), "--set", f"rules_file={self.rules_path}"],
            stdout=self._log, stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        self._wait_listening()

    def _wait_listening(self, timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                pytest.fail(f"mitmdump exited with {self.proc.returncode}:\n{self.log()}")
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                return
            except OSError:
                time.sleep(0.1)
        pytest.fail(f"mitmdump did not start in {timeout}s:\n{self.log()}")

    def write_rules(self, rules, raw: str | None = None):
        self.rules_path.write_text(raw if raw is not None else json.dumps(rules), encoding="utf-8")
        # make sure the change is visible even with a coarse mtime
        self._mtime += 2
        os.utime(self.rules_path, (self._mtime, self._mtime))

    def log(self) -> str:
        self._log.flush()
        return self.log_path.read_text(encoding="utf-8", errors="replace")

    def request(self, method, url, body=None, headers=None, timeout=10):
        """Sends a request through the proxy; returns (status, headers, body)."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            conn.request(method, url, body=body, headers=headers or {})
            r = conn.getresponse()
            return r.status, dict(r.getheaders()), r.read()
        finally:
            conn.close()

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._log.close()


@pytest.fixture
def upstream():
    u = Upstream()
    yield u
    u.close()


@pytest.fixture
def proxy_factory(tmp_path):
    proxies = []

    def start(rules, extra_args=()):
        p = Proxy(tmp_path, rules, extra_args)
        proxies.append(p)
        return p

    yield start
    for p in proxies:
        p.close()


def test_unmatched_request_reaches_the_server(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/mocked", "mock": {"status": 500}}])
    status, _, body = proxy.request("GET", upstream.base + "/real?x=1")
    assert status == 200
    assert json.loads(body) == {"real": True, "method": "GET", "path": "/real?x=1"}
    assert upstream.hits == ["GET /real?x=1"]


def test_mocked_request_never_reaches_the_server(upstream, proxy_factory):
    proxy = proxy_factory([{"name": "orders", "method": "POST", "url": upstream.base + "/orders", "mock": {"status": 503, "body": {"code": "DOWN"}, "headers": {"Retry-After": "5"}}}])
    status, headers, body = proxy.request("POST", upstream.base + "/orders", body=b"{}",
                                          headers={"Origin": "http://localhost:3001"})
    assert status == 503
    assert json.loads(body) == {"code": "DOWN"}
    assert headers["Retry-After"] == "5"
    assert headers["Access-Control-Allow-Origin"] == "http://localhost:3001"
    assert upstream.hits == []
    # another method on the same URL is not mocked
    assert proxy.request("GET", upstream.base + "/orders")[0] == 200
    assert upstream.hits == ["GET /orders"]
    assert f'MOCK 503 POST {upstream.base}/orders  [rule #1 "orders"]' in proxy.log()


def test_query_rule(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/trade", "query": {"Type": "Cancel"}, "mock": {"status": 400, "body": "\"Trade session is restricted\""}}])
    status, _, body = proxy.request("DELETE", upstream.base + "/trade?Id=1&Type=Cancel")
    assert (status, body) == (400, b'"Trade session is restricted"')
    assert proxy.request("DELETE", upstream.base + "/trade?Id=1&Type=Open")[0] == 200


def test_kill_drops_the_connection(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/unstable/*", "mock": {"status": "kill"}}])
    with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
        proxy.request("GET", upstream.base + "/unstable/1")
    assert upstream.hits == []


def test_timeout_hangs_then_drops(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/slow", "mock": {"status": "timeout", "delay": 1.5}}])
    start = time.monotonic()
    with pytest.raises((http.client.RemoteDisconnected, ConnectionError)):
        proxy.request("GET", upstream.base + "/slow")
    assert time.monotonic() - start >= 1.4
    assert upstream.hits == []


def test_delay(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/quotes", "mock": {"status": 429, "delay": 1}}])
    start = time.monotonic()
    assert proxy.request("GET", upstream.base + "/quotes")[0] == 429
    assert time.monotonic() - start >= 0.9


def test_hot_reload(upstream, proxy_factory):
    proxy = proxy_factory([])
    assert proxy.request("GET", upstream.base + "/x")[0] == 200
    proxy.write_rules([{"url": upstream.base + "/x", "mock": {"status": 502}}])
    assert proxy.request("GET", upstream.base + "/x")[0] == 502
    proxy.write_rules([{"url": upstream.base + "/x", "mock": {"status": 502}, "enabled": False}])
    assert proxy.request("GET", upstream.base + "/x")[0] == 200


def test_modified_request_reaches_the_server(upstream, proxy_factory):
    proxy = proxy_factory([{
        "name": "negative amount", "method": "POST", "url": upstream.base + "/orders*",
        "request": {
            "query": {"lang": "xx", "debug": None},
            "headers": {"X-Client-Version": "0.0.1", "Authorization": None},
            "json": {"amount": -100, "meta": {"source": None}},
        },
    }])
    status, _, body = proxy.request(
        "POST", upstream.base + "/orders?debug=1&keep=1",
        body=json.dumps({"amount": 10, "symbol": "EURUSD", "meta": {"source": "web"}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer t"})
    assert status == 200
    assert json.loads(body)["real"] is True
    got = upstream.requests[-1]
    assert got["path"] == "/orders?keep=1&lang=xx"
    assert got["headers"]["X-Client-Version"] == "0.0.1"
    assert "Authorization" not in got["headers"]
    assert json.loads(got["body"]) == {"amount": -100, "symbol": "EURUSD", "meta": {}}
    assert int(got["headers"]["Content-Length"]) == len(got["body"])
    assert f'MODIFY REQ POST {upstream.base}/orders?debug=1&keep=1  [rule #1 "negative amount"]: query, json, headers' \
        in proxy.log()


def test_modified_form_and_method(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/form", "request": {"method": "PUT", "form": {"a": "-1", "b": None}}}])
    proxy.request("POST", upstream.base + "/form", body=b"a=1&b=2&c=3",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    got = upstream.requests[-1]
    assert got["method"] == "PUT"
    assert got["body"] == b"a=-1&c=3"


def test_modified_response(upstream, proxy_factory):
    proxy = proxy_factory([{
        "url": upstream.base + "/account",
        "response": {"status": 403, "json": {"real": None, "balance": 0}, "headers": {"X-Debug": "1"}},
    }])
    status, headers, body = proxy.request("GET", upstream.base + "/account")
    assert upstream.hits == ["GET /account"]  # the server was asked
    assert status == 403
    assert headers["X-Debug"] == "1"
    assert json.loads(body) == {"method": "GET", "path": "/account", "balance": 0}
    assert int(headers["Content-Length"]) == len(body)
    assert f"MODIFY RESP 200 -> 403 GET {upstream.base}/account  [rule #1]: status, json, headers" in proxy.log()


def test_modified_gzipped_response(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/gzip", "response": {"json": {"balance": 0}}}])
    _, headers, body = proxy.request("GET", upstream.base + "/gzip", headers={"Accept-Encoding": "gzip"})
    assert headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(body))["balance"] == 0


def test_modified_request_and_response(upstream, proxy_factory):
    proxy = proxy_factory([{
        "url": upstream.base + "/trade",
        "request": {"headers": {"X-Session": "expired"}, "delay": 0.5},
        "response": {"status": 401, "body": {"code": "SESSION_EXPIRED"}, "delay": 0.5},
    }])
    start = time.monotonic()
    status, _, body = proxy.request("POST", upstream.base + "/trade", body=b"{}")
    assert time.monotonic() - start >= 0.9
    assert upstream.requests[-1]["headers"]["X-Session"] == "expired"
    assert (status, json.loads(body)) == (401, {"code": "SESSION_EXPIRED"})


def test_redirect_request_to_another_url(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/v1/*", "request": {"url": upstream.base + "/v2/orders"}}])
    _, _, body = proxy.request("GET", upstream.base + "/v1/orders")
    assert json.loads(body)["path"] == "/v2/orders"
    assert upstream.hits == ["GET /v2/orders"]


def test_incompatible_rule_is_skipped_and_the_request_reaches_the_server(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/orders", "mock": {"status": 500},
                            "request": {"json": {"amount": -1}}}])
    assert proxy.request("POST", upstream.base + "/orders", body=b'{"amount": 1}')[0] == 200
    assert json.loads(upstream.requests[-1]["body"]) == {"amount": 1}
    log = proxy.log()
    assert "incompatible: 'mock' cannot be used together with 'request' in one rule" in log
    assert "rule #1: rule skipped" in log


def test_old_format_still_mocks(upstream, proxy_factory):
    proxy = proxy_factory([{"url": upstream.base + "/old", "error": 418, "body": "teapot"}])
    status, _, body = proxy.request("GET", upstream.base + "/old")
    assert (status, body) == (418, b"teapot")
    assert upstream.hits == []
    assert "old format: 'error', 'body' at the top level still works" in proxy.log()


def test_wireguard_mode_keeps_the_regular_proxy(upstream, proxy_factory, tmp_path):
    # the modes "gremlin phone run" passes; confdir in tmp keeps the real ~/.mitmproxy untouched
    wg_port = free_port()
    proxy = proxy_factory([{"url": upstream.base + "/orders", "mock": {"status": 500}}],
                          ["--mode", "regular", "--mode", f"wireguard@{wg_port}",
                           "--set", f"confdir={tmp_path / 'confdir'}"])
    assert proxy.request("GET", upstream.base + "/orders")[0] == 500
    assert proxy.request("GET", upstream.base + "/real")[0] == 200
    deadline = time.monotonic() + 10
    while "WireGuard server listening" not in proxy.log() and time.monotonic() < deadline:
        time.sleep(0.1)
    log = proxy.log()
    assert f"WireGuard server listening at 127.0.0.1:{wg_port}" in log
    # the client config for the phone is printed, and its keys are kept for the next run
    assert "[Peer]" in log and f"Endpoint = 127.0.0.1:{wg_port}" in log
    assert (tmp_path / "confdir" / "wireguard.conf").exists()


def test_broken_rules_do_not_stop_the_proxy(upstream, proxy_factory):
    # one invalid rule at startup: logged as a warning, mitmdump keeps running, valid rules work
    proxy = proxy_factory([{"url": upstream.base + "/a"}, {"url": upstream.base + "/b", "mock": {"status": 418}}])
    assert proxy.request("GET", upstream.base + "/b")[0] == 418
    assert proxy.request("GET", upstream.base + "/a")[0] == 200
    # invalid JSON while running: previous rules stay active
    proxy.write_rules(None, raw="[{")
    assert proxy.request("GET", upstream.base + "/b")[0] == 418
    assert proxy.proc.poll() is None
    log = proxy.log()
    assert "nothing to do: add 'mock'" in log
    assert "invalid JSON" in log
