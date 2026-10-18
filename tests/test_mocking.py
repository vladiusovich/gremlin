"""Matching requests and building mocked responses: MockErrors.request()."""
import json
import logging

import pytest
from mitmproxy import http
from mitmproxy.test import tflow

import mock_errors

URL = "https://api.example.com/v1/orders"


def make_flow(method="GET", url=URL, headers=None) -> http.HTTPFlow:
    f = tflow.tflow()
    f.request = http.Request.make(method, url, b"", headers or {})
    return f


@pytest.fixture
def sleeps(monkeypatch):
    """Records asyncio.sleep calls made by the addon instead of waiting."""
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(mock_errors.asyncio, "sleep", fake_sleep)
    return calls


async def run(gremlin, flow):
    await gremlin.addon.request(flow)
    return flow


# --- matching ---------------------------------------------------------------

async def test_no_rules_passes_through(gremlin):
    gremlin.load([])
    f = await run(gremlin, make_flow())
    assert f.response is None
    assert f.error is None


async def test_exact_url_match(gremlin):
    gremlin.load([{"url": URL, "error": 500}])
    f = await run(gremlin, make_flow())
    assert f.response.status_code == 500


async def test_non_matching_url_passes_through(gremlin):
    gremlin.load([{"url": URL, "error": 500}])
    for url in (URL + "/1", "http://api.example.com/v1/orders", "https://api.example.com:8443/v1/orders"):
        f = await run(gremlin, make_flow(url=url))
        assert f.response is None, url


@pytest.mark.parametrize("pattern, url, matches", [
    ("https://api.example.com/v1/*", "https://api.example.com/v1/orders/1?x=2", True),
    ("https://api.example.com/v1/*", "https://api.example.com/v2/orders", False),
    ("https://api.example.com/v1/order?", "https://api.example.com/v1/orders", True),
    ("*/orders", "https://any.host/v1/orders", True),
    ("https://host:8443/api/*", "https://host:8443/api/x", True),
    ("https://host:8443/api/*", "https://host/api/x", False),
    # without "query", the query string is part of the matched URL
    ("https://api.example.com/v1/orders", "https://api.example.com/v1/orders?a=1", False),
    # case-sensitive matching
    ("https://api.example.com/V1/*", "https://api.example.com/v1/orders", False),
])
async def test_url_wildcards(gremlin, pattern, url, matches):
    gremlin.load([{"url": pattern, "error": 500}])
    f = await run(gremlin, make_flow(url=url))
    assert (f.response is not None) == matches


@pytest.mark.parametrize("rule_method, req_method, matches", [
    ("*", "DELETE", True),
    ("GET", "GET", True),
    ("get", "GET", True),
    ("POST", "GET", False),
])
async def test_method(gremlin, rule_method, req_method, matches):
    gremlin.load([{"url": URL, "method": rule_method, "error": 500}])
    f = await run(gremlin, make_flow(method=req_method))
    assert (f.response is not None) == matches


@pytest.mark.parametrize("query, url, matches", [
    ({"Type": "Cancel"}, URL + "?Type=Cancel", True),
    ({"Type": "Cancel"}, URL + "?a=1&Type=Cancel&b=2", True),
    ({"Type": "Cancel", "a": "1"}, URL + "?a=1&Type=Cancel", True),  # order does not matter
    ({"Type": "Cancel"}, URL + "?Type=Open", False),
    ({"Type": "Cancel", "a": "1"}, URL + "?Type=Cancel&a=2", False),  # every param must match
    ({"Type": "Cancel", "a": "1"}, URL + "?Type=Cancel", False),
    ({"Type": "Cancel"}, URL, False),
    ({"Type": "*"}, URL + "?Type=", True),
    ({"Id": "1*"}, URL + "?Id=123", True),
    ({"Id": 5}, URL + "?Id=5", True),
    ({"Type": "Cancel"}, URL + "/x?Type=Cancel", False),
])
async def test_query(gremlin, query, url, matches):
    gremlin.load([{"url": URL, "query": query, "error": 400}])
    f = await run(gremlin, make_flow(url=url))
    assert (f.response is not None) == matches


async def test_first_match_wins(gremlin):
    gremlin.load([
        {"url": URL, "method": "POST", "error": 401},
        {"url": "https://api.example.com/*", "error": 502},
        {"url": URL, "error": 503},
    ])
    assert (await run(gremlin, make_flow("POST"))).response.status_code == 401
    assert (await run(gremlin, make_flow("GET"))).response.status_code == 502


async def test_disabled_rule_does_not_match(gremlin):
    gremlin.load([{"url": URL, "error": 500, "enabled": False}])
    assert (await run(gremlin, make_flow())).response is None


async def test_rules_file_is_reloaded_on_request(gremlin):
    gremlin.load([])
    gremlin.write([{"url": URL, "error": 504}])
    f = await run(gremlin, make_flow())
    assert f.response.status_code == 504


# --- response ---------------------------------------------------------------

async def test_default_body(gremlin):
    gremlin.load([{"url": URL, "error": 503}])
    r = (await run(gremlin, make_flow("PUT"))).response
    assert r.headers["Content-Type"] == "application/json"
    assert json.loads(r.content) == {
        "error": "mocked_by_mitmproxy", "status": 503, "method": "PUT", "url": URL,
    }


@pytest.mark.parametrize("body", [{"code": "NOT_FOUND"}, [1, "two"], {"unicode": "Fehler: Größe – ✓"}])
async def test_json_body(gremlin, body):
    gremlin.load([{"url": URL, "error": 404, "body": body}])
    r = (await run(gremlin, make_flow())).response
    assert json.loads(r.content) == body


@pytest.mark.parametrize("body, content", [
    ("Internal Server Error", b"Internal Server Error"),
    ('"Trade session is restricted"', b'"Trade session is restricted"'),
    ("", b""),
    (42, b"42"),
])
async def test_raw_body(gremlin, body, content):
    gremlin.load([{"url": URL, "error": 500, "body": body}])
    r = (await run(gremlin, make_flow())).response
    assert r.content == content
    assert r.headers["Content-Type"] == "application/json"


async def test_content_type(gremlin):
    gremlin.load([{"url": URL, "error": 500, "body": "<h1>x</h1>", "content_type": "text/html"}])
    r = (await run(gremlin, make_flow())).response
    assert r.headers["Content-Type"] == "text/html"


async def test_headers_and_content_type_header_override(gremlin):
    gremlin.load([{"url": URL, "error": 429, "headers": {"Retry-After": 10, "Content-Type": "text/plain"}}])
    r = (await run(gremlin, make_flow())).response
    assert r.headers["Retry-After"] == "10"
    assert r.headers["Content-Type"] == "text/plain"


async def test_no_cors_headers_without_origin(gremlin):
    gremlin.load([{"url": URL, "error": 500}])
    r = (await run(gremlin, make_flow())).response
    assert not any(k.lower().startswith("access-control-") for k in r.headers)


async def test_cors_headers_for_origin(gremlin):
    gremlin.load([{"url": URL, "error": 500}])
    r = (await run(gremlin, make_flow(headers={"Origin": "http://localhost:3001"}))).response
    assert r.headers["Access-Control-Allow-Origin"] == "http://localhost:3001"
    assert r.headers["Access-Control-Allow-Credentials"] == "true"
    assert r.headers["Vary"] == "Origin"
    assert "Access-Control-Expose-Headers" not in r.headers


async def test_cors_exposes_custom_headers(gremlin):
    gremlin.load([{"url": URL, "error": 429, "headers": {"Retry-After": "1", "X-Req": "2"}}])
    r = (await run(gremlin, make_flow(headers={"Origin": "http://localhost:3001"}))).response
    assert r.headers["Access-Control-Expose-Headers"] == "Retry-After, X-Req"


async def test_cors_does_not_override_rule_headers(gremlin):
    gremlin.load([{"url": URL, "error": 500, "headers": {"Access-Control-Allow-Origin": "*"}}])
    r = (await run(gremlin, make_flow(headers={"Origin": "http://localhost:3001"}))).response
    assert r.headers["Access-Control-Allow-Origin"] == "*"


async def test_cors_false(gremlin):
    gremlin.load([{"url": URL, "error": 401, "cors": False}])
    r = (await run(gremlin, make_flow(headers={"Origin": "http://localhost:3001"}))).response
    assert r.status_code == 401
    assert "Access-Control-Allow-Origin" not in r.headers


async def test_mock_is_logged(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"name": "orders", "url": URL, "error": 500}])
    await run(gremlin, make_flow("POST"))
    assert f'MOCK 500 POST {URL}  [rule #1 "orders"]' in [r.getMessage() for r in caplog.records]


# --- delay / timeout / kill -------------------------------------------------

async def test_no_delay_by_default(gremlin, sleeps):
    gremlin.load([{"url": URL, "error": 500}])
    await run(gremlin, make_flow())
    assert sleeps == []


async def test_delay_before_response(gremlin, sleeps):
    gremlin.load([{"url": URL, "error": 500, "delay": 2.5}])
    f = await run(gremlin, make_flow())
    assert sleeps == [2.5]
    assert f.response.status_code == 500


async def test_kill(gremlin, sleeps, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "error": "kill"}])
    f = await run(gremlin, make_flow())
    assert f.response is None
    assert f.error is not None and f.error.msg == f.error.KILLED_MESSAGE
    assert sleeps == []
    assert any(r.getMessage().startswith(f"KILL GET {URL}") for r in caplog.records)


async def test_timeout(gremlin, sleeps, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "error": "timeout", "delay": 15}])
    f = await run(gremlin, make_flow())
    assert sleeps == [15.0]
    assert f.response is None
    assert f.error.msg == f.error.KILLED_MESSAGE
    assert any(r.getMessage().startswith(f"TIMEOUT 15s GET {URL}") for r in caplog.records)


async def test_timeout_default_30s(gremlin, sleeps):
    gremlin.load([{"url": URL, "error": "timeout"}])
    await run(gremlin, make_flow())
    assert sleeps == [30.0]


async def test_real_delay_is_awaited(gremlin):
    # without the sleep stub: the delay really happens and does not block other requests
    import asyncio
    import time
    gremlin.load([{"url": URL, "error": 500, "delay": 0.2}])
    start = time.monotonic()
    flows = await asyncio.gather(*(run(gremlin, make_flow()) for _ in range(5)))
    elapsed = time.monotonic() - start
    assert all(f.response.status_code == 500 for f in flows)
    assert 0.2 <= elapsed < 0.9


async def test_failure_while_mocking_passes_request_through(gremlin, monkeypatch, caplog):
    gremlin.load([{"url": URL, "error": 500}, {"url": URL, "error": 502}])

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mock_errors.http.Response, "make", boom)
    f = await run(gremlin, make_flow())
    assert f.response is None
    assert f.error is None
    assert any("rule #1: failed to mock GET" in r.getMessage() and "passing the request through" in r.getMessage()
               for r in caplog.records if r.levelno == logging.ERROR)
