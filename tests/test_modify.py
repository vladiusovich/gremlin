"""Changing the real request and response: the "request" / "response" sections of a rule."""
import gzip
import json
import logging

import pytest
from mitmproxy import http
from mitmproxy.test import tflow

import mock_errors
from mock_errors import merge_patch

URL = "https://api.example.com/v1/orders"
JSON = {"Content-Type": "application/json"}
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def make_flow(method="POST", url=URL, body=b"", headers=None) -> http.HTTPFlow:
    f = tflow.tflow()
    content = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    f.request = http.Request.make(method, url, content, headers or {})
    f.response = None
    return f


def server_reply(flow, status=200, body=b"", headers=None) -> http.Response:
    """What the real server would answer."""
    content = json.dumps(body).encode() if isinstance(body, (dict, list)) else body
    flow.response = http.Response.make(status, content, headers or {})
    return flow.response


@pytest.fixture
def sleeps(monkeypatch):
    calls = []

    async def fake_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(mock_errors.asyncio, "sleep", fake_sleep)
    return calls


async def send(gremlin, flow, status=200, body=b"", headers=None):
    """Runs the request hook, lets the "server" answer, runs the response hook."""
    await gremlin.addon.request(flow)
    assert flow.response is None, "the request must reach the server"
    server_reply(flow, status, body, headers)
    await gremlin.addon.response(flow)
    return flow


def messages(caplog, level=None):
    return [r.getMessage() for r in caplog.records if level is None or r.levelno == level]


# --- JSON Merge Patch ---------------------------------------------------------

@pytest.mark.parametrize("target, patch, expected", [
    ({"a": 1}, {"a": 2}, {"a": 2}),
    ({"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
    ({"a": 1, "b": 2}, {"a": None}, {"b": 2}),
    ({"a": 1}, {"missing": None}, {"a": 1}),
    ({"a": {"x": 1, "y": 2}}, {"a": {"y": None, "z": 3}}, {"a": {"x": 1, "z": 3}}),
    ({"a": [1, 2, 3]}, {"a": [9]}, {"a": [9]}),  # arrays are replaced, not merged
    ({"a": "text"}, {"a": {"b": 1}}, {"a": {"b": 1}}),
    ({"a": {"b": 1}}, {"a": 5}, {"a": 5}),
    ({}, {"a": {"b": None}}, {"a": {}}),
])
def test_merge_patch(target, patch, expected):
    assert merge_patch(target, patch) == expected


def test_merge_patch_does_not_mutate_target():
    target = {"a": {"b": 1}}
    merge_patch(target, {"a": {"b": 2}})
    assert target == {"a": {"b": 1}}


# --- request ----------------------------------------------------------------

async def test_request_reaches_the_server_unmocked(gremlin):
    gremlin.load([{"url": URL, "request": {"headers": {"X-Test": "1"}}}])
    f = make_flow()
    await gremlin.addon.request(f)
    assert f.response is None
    assert f.error is None
    assert f.request.headers["X-Test"] == "1"


async def test_request_headers_set_and_remove(gremlin):
    gremlin.load([{"url": URL, "request": {"headers": {
        "X-Client-Version": "0.0.1", "authorization": None, "Missing": None, "Accept": "text/plain"}}}])
    f = await send(gremlin, make_flow(headers={"Authorization": "Bearer t", "Accept": "*/*"}))
    h = f.request.headers
    assert h["X-Client-Version"] == "0.0.1"
    assert "Authorization" not in h
    assert h.get_all("Accept") == ["text/plain"]


async def test_request_query_set_and_remove(gremlin):
    gremlin.load([{"url": URL + "*", "request": {"query": {"lang": "xx", "debug": None, "page": 0}}}])
    f = await send(gremlin, make_flow(url=URL + "?debug=1&lang=en&keep=yes"))
    assert dict(f.request.query) == {"lang": "xx", "keep": "yes", "page": "0"}


async def test_request_query_added_to_url_without_query(gremlin):
    gremlin.load([{"url": URL, "request": {"query": {"a": "1"}}}])
    f = await send(gremlin, make_flow())
    assert f.request.pretty_url == URL + "?a=1"


async def test_request_method_and_url(gremlin):
    gremlin.load([{"url": URL, "request": {"method": "put", "url": "https://other.test:8443/v2/orders?x=1"}}])
    f = await send(gremlin, make_flow(headers={"Host": "api.example.com"}))
    assert f.request.method == "PUT"
    assert f.request.pretty_url == "https://other.test:8443/v2/orders?x=1"
    assert f.request.headers["Host"] == "other.test:8443"


async def test_request_url_then_query(gremlin):
    gremlin.load([{"url": URL, "request": {"url": "https://other.test/v2?a=1", "query": {"b": "2"}}}])
    f = await send(gremlin, make_flow())
    assert f.request.pretty_url == "https://other.test/v2?a=1&b=2"


async def test_request_json_merge(gremlin):
    gremlin.load([{"url": URL, "request": {"json": {"amount": -100, "meta": {"source": None, "test": True}}}}])
    body = {"amount": 10, "symbol": "EURUSD", "meta": {"source": "web", "v": 2}}
    f = await send(gremlin, make_flow(body=body, headers=JSON))
    assert json.loads(f.request.content) == {
        "amount": -100, "symbol": "EURUSD", "meta": {"v": 2, "test": True}}
    assert f.request.headers["Content-Type"] == "application/json"


async def test_request_json_into_empty_body(gremlin):
    gremlin.load([{"url": URL, "request": {"json": {"a": 1}}}])
    f = await send(gremlin, make_flow())
    assert json.loads(f.request.content) == {"a": 1}
    assert f.request.headers["Content-Type"] == "application/json"


async def test_request_json_keeps_custom_content_type(gremlin):
    gremlin.load([{"url": URL, "request": {"json": {"a": 1}}}])
    f = await send(gremlin, make_flow(body={"b": 2}, headers={"Content-Type": "application/vnd.api+json"}))
    assert f.request.headers["Content-Type"] == "application/vnd.api+json"


async def test_request_json_updates_content_length(gremlin):
    gremlin.load([{"url": URL, "request": {"json": {"long_field_name": "long value"}}}])
    f = await send(gremlin, make_flow(body={}, headers={**JSON, "Content-Length": "2"}))
    assert f.request.headers["Content-Length"] == str(len(f.request.content))


async def test_request_json_skipped_for_non_json_body(gremlin, caplog):
    gremlin.load([{"url": URL, "request": {"json": {"a": 1}, "headers": {"X": "1"}}}])
    f = await send(gremlin, make_flow(body=b"not json", headers={"Content-Type": "text/plain"}))
    assert f.request.content == b"not json"
    assert f.request.headers["X"] == "1"  # other changes are still applied
    assert "rule #1: request: 'json' skipped: the body is not JSON (use 'replace' or 'body' instead)" \
        in messages(caplog, logging.WARNING)


async def test_request_json_skipped_for_json_array(gremlin, caplog):
    gremlin.load([{"url": URL, "request": {"json": {"a": 1}}}])
    f = await send(gremlin, make_flow(body=[1, 2], headers=JSON))
    assert json.loads(f.request.content) == [1, 2]
    assert any("'json' skipped: the body is a JSON array, not an object" in m for m in messages(caplog))


@pytest.mark.parametrize("body, content", [
    ({"replaced": True}, b'{"replaced": true}'),
    ([1, 2], b"[1, 2]"),
    ("raw=text", b"raw=text"),
    ("", b""),
    (42, b"42"),
    (False, b"false"),
])
async def test_request_body(gremlin, body, content):
    gremlin.load([{"url": URL, "request": {"body": body}}])
    f = await send(gremlin, make_flow(body={"original": 1}, headers=JSON))
    assert f.request.content == content


async def test_request_body_object_sets_json_content_type_only_if_missing(gremlin):
    gremlin.load([{"url": URL, "request": {"body": {"a": 1}}}])
    f = await send(gremlin, make_flow())
    assert f.request.headers["Content-Type"] == "application/json"
    f = await send(gremlin, make_flow(headers={"Content-Type": "text/plain"}))
    assert f.request.headers["Content-Type"] == "text/plain"


async def test_request_body_then_json(gremlin):
    gremlin.load([{"url": URL, "request": {"body": {"a": 1, "b": 2}, "json": {"b": None, "c": 3}}}])
    f = await send(gremlin, make_flow(body=b"whatever"))
    assert json.loads(f.request.content) == {"a": 1, "c": 3}


async def test_request_form(gremlin):
    gremlin.load([{"url": URL, "request": {"form": {"amount": -1, "comment": None, "new": "x y"}}}])
    f = await send(gremlin, make_flow(body=b"amount=10&comment=hi&keep=1", headers=FORM))
    assert dict(f.request.urlencoded_form) == {"amount": "-1", "keep": "1", "new": "x y"}


async def test_request_form_into_empty_body(gremlin):
    gremlin.load([{"url": URL, "request": {"form": {"a": "1"}}}])
    f = await send(gremlin, make_flow())
    assert f.request.content == b"a=1"
    assert f.request.headers["Content-Type"] == "application/x-www-form-urlencoded"


async def test_request_form_skipped_for_json_body(gremlin, caplog):
    gremlin.load([{"url": URL, "request": {"form": {"a": "1"}}}])
    f = await send(gremlin, make_flow(body={"a": 0}, headers=JSON))
    assert json.loads(f.request.content) == {"a": 0}
    assert any("'form' skipped: the body is not a form (Content-Type: application/json)" in m for m in messages(caplog))


async def test_request_replace_plain_text(gremlin):
    gremlin.load([{"url": URL, "request": {"replace": [
        {"from": "EURUSD", "to": "XXXYYY"}, {"from": "a.b", "to": "\\1"}]}}])
    f = await send(gremlin, make_flow(body=b"<s>EURUSD</s><s>EURUSD</s> a.b axb"))
    # plain strings: no regex meaning in "from", no group references in "to"
    assert f.request.content == b"<s>XXXYYY</s><s>XXXYYY</s> \\1 axb"


async def test_request_replace_regex(gremlin):
    gremlin.load([{"url": URL, "request": {"replace": {"from": "\"qty\":\\s*(\\d+)", "to": "\"qty\": -\\1", "regex": True}}}])
    f = await send(gremlin, make_flow(body=b'{"qty": 5, "items": [{"qty":7}]}'))
    assert f.request.content == b'{"qty": -5, "items": [{"qty": -7}]}'


async def test_request_replace_not_found_warns(gremlin, caplog):
    gremlin.load([{"url": URL, "request": {"replace": {"from": "nope", "to": "x"}}}])
    f = await send(gremlin, make_flow(body=b"body"))
    assert f.request.content == b"body"
    assert 'rule #1: request: \'replace\': "nope" not found in the body' in messages(caplog, logging.WARNING)


async def test_request_replace_unicode(gremlin):
    gremlin.load([{"url": URL, "request": {"replace": {"from": "Größe", "to": "Размер"}}}])
    f = await send(gremlin, make_flow(body="Größe: 1".encode(), headers={"Content-Type": "text/plain; charset=utf-8"}))
    assert f.request.content.decode("utf-8") == "Размер: 1"


async def test_request_headers_are_applied_after_body(gremlin):
    gremlin.load([{"url": URL, "request": {"form": {"a": "1"}, "headers": {"Content-Type": "text/plain"}}}])
    f = await send(gremlin, make_flow())
    assert f.request.headers["Content-Type"] == "text/plain"


async def test_request_delay(gremlin, sleeps):
    gremlin.load([{"url": URL, "request": {"delay": 1.5}}])
    await send(gremlin, make_flow())
    assert sleeps == [1.5]


async def test_request_is_logged(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"name": "neg", "url": URL, "request": {"headers": {"X": "1"}, "json": {"a": -1}, "delay": 0}}])
    await send(gremlin, make_flow(body={"a": 1}, headers=JSON))
    assert f'MODIFY REQ POST {URL}  [rule #1 "neg"]: json, headers' in messages(caplog, logging.INFO)


async def test_nothing_changed_is_logged(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "request": {"json": {"a": 1}}}])
    await send(gremlin, make_flow(body=b"text"))
    assert f"MODIFY REQ POST {URL}  [rule #1]: nothing changed" in messages(caplog, logging.INFO)


async def test_request_only_rule_does_not_touch_the_response(gremlin):
    gremlin.load([{"url": URL, "request": {"headers": {"X": "1"}}}])
    f = await send(gremlin, make_flow(), status=201, body={"real": True}, headers=JSON)
    assert f.response.status_code == 201
    assert json.loads(f.response.content) == {"real": True}


# --- response ---------------------------------------------------------------

async def test_response_status_keeps_the_real_body(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 401}}])
    f = await send(gremlin, make_flow(), body={"real": True}, headers=JSON)
    assert f.response.status_code == 401
    assert f.response.reason == "Unauthorized"
    assert json.loads(f.response.content) == {"real": True}


async def test_response_json_merge(gremlin):
    gremlin.load([{"url": URL, "response": {"json": {"balance": 0, "flags": {"trading": False, "beta": None}}}}])
    f = await send(gremlin, make_flow(), body={"balance": 1000, "currency": "USD", "flags": {"trading": True, "beta": True}},
                   headers=JSON)
    assert json.loads(f.response.content) == {"balance": 0, "currency": "USD", "flags": {"trading": False}}


async def test_response_json_with_gzip(gremlin):
    gremlin.load([{"url": URL, "response": {"json": {"a": 2}}}])
    f = make_flow()
    await gremlin.addon.request(f)
    # make() encodes the content according to Content-Encoding, as a real server would
    f.response = http.Response.make(200, b'{"a": 1, "b": 1}', {**JSON, "Content-Encoding": "gzip"})
    assert f.response.raw_content.startswith(b"\x1f\x8b")
    await gremlin.addon.response(f)
    assert f.response.headers["Content-Encoding"] == "gzip"
    assert json.loads(gzip.decompress(f.response.raw_content)) == {"a": 2, "b": 1}
    assert f.response.headers["Content-Length"] == str(len(f.response.raw_content))


async def test_response_body(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 500, "body": "Internal error"}}])
    f = await send(gremlin, make_flow(), body={"real": True}, headers=JSON)
    assert f.response.status_code == 500
    assert f.response.content == b"Internal error"
    assert f.response.headers["Content-Type"] == "application/json"  # the real header is kept


async def test_response_replace_and_headers(gremlin):
    gremlin.load([{"url": URL, "response": {
        "replace": {"from": "Welcome", "to": "Willkommen"},
        "headers": {"Cache-Control": None, "X-Debug": "1"}}}])
    f = await send(gremlin, make_flow(), body=b"<h1>Welcome</h1>",
                   headers={"Content-Type": "text/html", "Cache-Control": "max-age=60"})
    assert f.response.content == b"<h1>Willkommen</h1>"
    assert "Cache-Control" not in f.response.headers
    assert f.response.headers["X-Debug"] == "1"


async def test_response_keeps_real_cors_headers(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 403}}])
    f = await send(gremlin, make_flow(headers={"Origin": "http://localhost:3001"}),
                   headers={"Access-Control-Allow-Origin": "http://localhost:3001"})
    assert f.response.headers["Access-Control-Allow-Origin"] == "http://localhost:3001"


async def test_response_delay(gremlin, sleeps):
    gremlin.load([{"url": URL, "request": {"delay": 1}, "response": {"delay": 2}}])
    await send(gremlin, make_flow())
    assert sleeps == [1.0, 2.0]


async def test_response_is_logged(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "response": {"status": 401, "json": {"a": 1}}}])
    await send(gremlin, make_flow("GET"), body={}, headers=JSON)
    assert f"MODIFY RESP 200 -> 401 GET {URL}  [rule #1]: status, json" in messages(caplog, logging.INFO)


async def test_response_same_status_is_logged_once(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "response": {"status": 200, "headers": {"X": "1"}}}])
    await send(gremlin, make_flow("GET"))
    assert f"MODIFY RESP 200 GET {URL}  [rule #1]: status, headers" in messages(caplog, logging.INFO)


async def test_response_only_rule_does_not_touch_the_request(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 500}}])
    f = await send(gremlin, make_flow(body=b"original", headers={"X": "1"}))
    assert f.request.content == b"original"
    assert f.request.headers["X"] == "1"


async def test_request_and_response_together(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([{"url": URL, "request": {"headers": {"X-Session": "expired"}},
                   "response": {"status": 401, "body": {"code": "SESSION_EXPIRED"}}}])
    f = await send(gremlin, make_flow(), body={"ok": True}, headers=JSON)
    assert f.request.headers["X-Session"] == "expired"
    assert f.response.status_code == 401
    assert json.loads(f.response.content) == {"code": "SESSION_EXPIRED"}
    log = messages(caplog, logging.INFO)
    assert f"MODIFY REQ POST {URL}  [rule #1]: headers" in log
    assert f"MODIFY RESP 200 -> 401 POST {URL}  [rule #1]: status, body" in log


async def test_unmatched_response_is_untouched(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 500}}])
    f = await send(gremlin, make_flow(url=URL + "/other"))
    assert f.response.status_code == 200
    assert gremlin.addon.pending == {}


async def test_response_uses_the_rule_matched_at_request_time(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 418}}])
    f = make_flow()
    await gremlin.addon.request(f)
    gremlin.write([{"url": URL, "response": {"status": 500}}])  # rules change while the server is answering
    server_reply(f)
    await gremlin.addon.response(f)
    assert f.response.status_code == 418


async def test_server_error_clears_pending(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 500}}])
    f = make_flow()
    await gremlin.addon.request(f)
    assert f.id in gremlin.addon.pending
    gremlin.addon.error(f)
    assert gremlin.addon.pending == {}


async def test_pending_is_cleared_after_response(gremlin):
    gremlin.load([{"url": URL, "response": {"status": 500}}])
    await send(gremlin, make_flow())
    assert gremlin.addon.pending == {}


async def test_first_match_wins_across_rule_kinds(gremlin):
    gremlin.load([
        {"url": URL, "method": "POST", "request": {"headers": {"X": "1"}}},
        {"url": URL, "mock": {"status": 500}},
    ])
    f = await send(gremlin, make_flow("POST"))
    assert f.request.headers["X"] == "1"
    f = make_flow("GET")
    await gremlin.addon.request(f)
    assert f.response.status_code == 500


async def test_failure_while_modifying_request_sends_it(gremlin, monkeypatch, caplog):
    gremlin.load([{"url": URL, "request": {"headers": {"X": "1"}}}])

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mock_errors, "apply_ops", boom)
    f = make_flow()
    await gremlin.addon.request(f)
    assert f.response is None
    assert f.error is None
    assert any(f"rule #1: failed to modify the request POST {URL}" in m
               for m in messages(caplog, logging.ERROR))


async def test_failure_while_modifying_response_returns_it(gremlin, monkeypatch, caplog):
    gremlin.load([{"url": URL, "response": {"status": 500}}])
    f = make_flow()
    await gremlin.addon.request(f)

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(mock_errors, "apply_ops", boom)
    server_reply(f, 200, b"real")
    await gremlin.addon.response(f)
    assert f.response.status_code == 200
    assert f.response.content == b"real"
    assert any(f"rule #1: failed to modify the response POST {URL}" in m
               for m in messages(caplog, logging.ERROR))
