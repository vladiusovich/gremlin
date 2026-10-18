"""Validation of a single rule: parse_rule() in addons/mock_errors.py."""
import pytest

from mock_errors import Rule, parse_rule

URL = "https://api.example.com/v1/orders"
MOCK = {"status": 500}


def ok(raw, number=1) -> tuple[Rule, list[str]]:
    rule, errors, warnings = parse_rule(number, raw)
    assert errors == []
    assert rule is not None
    return rule, warnings


def bad(raw) -> list[str]:
    rule, errors, _ = parse_rule(1, raw)
    assert rule is None
    assert errors
    return errors


# --- picking requests and common fields ---------------------------------------

def test_minimal_mock_rule_gets_defaults():
    rule, warnings = ok({"url": URL, "mock": {"status": 500}})
    assert warnings == []
    assert rule.url == URL
    assert rule.method == "*"
    assert rule.query == {}
    assert rule.name is None
    assert rule.request is None and rule.response is None
    m = rule.mock
    assert m.status == 500
    assert m.body is None
    assert m.content_type == "application/json"
    assert m.headers == {}
    assert m.delay == 0.0
    assert m.cors is True


def test_all_fields():
    rule, warnings = ok({
        "name": "n", "method": "post", "url": URL, "query": {"a": 1, "b": True},
        "mock": {"status": 429, "body": {"x": 1}, "content_type": "text/plain",
                 "headers": {"Retry-After": 10}, "delay": 1.5, "cors": False},
        "enabled": True, "comment": ["anything"],
    }, number=7)
    assert warnings == []
    assert rule.number == 7
    assert rule.label == 'rule #7 "n"'
    assert rule.method == "POST"
    assert rule.query == {"a": "1", "b": "true"}
    assert rule.mock.headers == {"Retry-After": "10"}
    assert rule.mock.content_type == "text/plain"
    assert rule.mock.delay == 1.5
    assert rule.mock.cors is False


def test_label_without_name():
    rule, _ = ok({"url": URL, "mock": MOCK}, number=3)
    assert rule.label == "rule #3"


def test_url_is_required():
    errors = bad({"mock": MOCK})
    assert any("field 'url' (required) is missing" in e for e in errors)


@pytest.mark.parametrize("raw", [
    {"url": URL},
    {"url": URL, "name": "forgot the action"},
])
def test_rule_without_an_action_is_invalid(raw):
    assert bad(raw) == [
        "nothing to do: add 'mock' to answer instead of the server, "
        "or 'request' / 'response' to change the real request / response"
    ]


@pytest.mark.parametrize("url", ["", "   ", 5, None])
def test_invalid_url(url):
    errors = bad({"url": url, "mock": MOCK})
    assert any("field 'url' (required): expected a non-empty string" in e for e in errors)


def test_url_without_scheme_warns():
    _, warnings = ok({"url": "api.example.com/*", "mock": MOCK})
    assert any("has no scheme and will never match" in w for w in warnings)


def test_url_starting_with_wildcard_does_not_warn():
    _, warnings = ok({"url": "*/v1/orders", "mock": MOCK})
    assert warnings == []


def test_not_an_object():
    rule, errors, warnings = parse_rule(1, ["url"])
    assert rule is None
    assert errors == ["must be a JSON object, got array"]
    assert warnings == []


def test_all_problems_are_reported_at_once():
    errors = bad({"url": 1, "mock": {"status": "x", "delay": -1, "cors": "yes"}, "method": 5})
    for f in ("'url'", "'mock.status'", "'mock.delay'", "'mock.cors'", "'method'"):
        assert any(f in e for e in errors), (f, errors)


def test_unknown_field_suggests_closest():
    _, warnings = ok({"url": URL, "mock": MOCK, "metod": "GET"})
    assert warnings == ["unknown field 'metod' is ignored, did you mean 'method'?"]


def test_unknown_field_suggests_mock():
    _, warnings = ok({"url": URL, "mock": MOCK, "mok": {}})
    assert warnings == ["unknown field 'mok' is ignored, did you mean 'mock'?"]


def test_unknown_field_without_suggestion():
    _, warnings = ok({"url": URL, "mock": MOCK, "zzzzzz": 1})
    assert warnings == ["unknown field 'zzzzzz' is ignored"]


def test_unusual_method_warns():
    rule, warnings = ok({"url": URL, "mock": MOCK, "method": " gett "})
    assert rule.method == "GETT"
    assert any('unusual method "GETT"' in w for w in warnings)


@pytest.mark.parametrize("method", ["", "  ", 1, None])
def test_invalid_method(method):
    errors = bad({"url": URL, "mock": MOCK, "method": method})
    assert any("field 'method' (optional)" in e for e in errors)


@pytest.mark.parametrize("query, expected", [
    ([1], "field 'query' (optional): expected an object"),
    ({"a": {"b": 1}}, "value of 'a' must be a string or number, got object"),
    ({"a": None}, "value of 'a' must be a string or number, got null"),
])
def test_invalid_query(query, expected):
    errors = bad({"url": URL, "mock": MOCK, "query": query})
    assert any(expected in e for e in errors), errors


def test_query_with_question_mark_in_url_warns():
    _, warnings = ok({"url": URL + "?a=1", "mock": MOCK, "query": {"a": "1"}})
    assert any("move the parameters to 'query'" in w for w in warnings)


def test_invalid_name():
    errors = bad({"url": URL, "mock": MOCK, "name": 5})
    assert any("field 'name' (optional): expected a string, got number 5" in e for e in errors)


# --- "mock" -----------------------------------------------------------------

@pytest.mark.parametrize("status", [100, 404, 599, "timeout", "kill"])
def test_valid_mock_status(status):
    rule, _ = ok({"url": URL, "mock": {"status": status}})
    assert rule.mock.status == status


def test_timeout_default_delay_is_30():
    rule, _ = ok({"url": URL, "mock": {"status": "timeout"}})
    assert rule.mock.delay == 30.0


def test_timeout_custom_delay():
    rule, _ = ok({"url": URL, "mock": {"status": "timeout", "delay": 2}})
    assert rule.mock.delay == 2.0


@pytest.mark.parametrize("value", [[], "x", None, 500])
def test_mock_must_be_an_object(value):
    errors = bad({"url": URL, "mock": value})
    assert any("field 'mock' (optional): expected an object like {\"status\": 500" in e for e in errors), errors


def test_mock_status_is_required():
    errors = bad({"url": URL, "mock": {"body": {"a": 1}}})
    assert errors == ["field 'mock.status' (required) is missing: HTTP status 100-599, "
                      "\"timeout\" (hang, then drop the connection) or \"kill\" (drop it at once)"]


@pytest.mark.parametrize("status, expected", [
    (99, "field 'mock.status' (required): HTTP status must be 100-599, got 99"),
    (600, "field 'mock.status' (required): HTTP status must be 100-599, got 600"),
    ("500", "field 'mock.status' (required): write the status as a number without quotes: 500"),
    (" 404 ", "without quotes: 404"),
    ("boom", 'field \'mock.status\' (required): expected an HTTP status 100-599, "timeout" or "kill"'),
    (True, 'an HTTP status 100-599, "timeout" or "kill"'),
    (None, 'an HTTP status 100-599, "timeout" or "kill"'),
    (500.5, 'an HTTP status 100-599, "timeout" or "kill"'),
])
def test_invalid_mock_status(status, expected):
    errors = bad({"url": URL, "mock": {"status": status}})
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("headers, expected", [
    ("X: 1", "field 'mock.headers' (optional): expected an object"),
    ({" ": "1"}, "header ' ' must have a non-empty name"),
    ({"X": [1]}, "header 'X' must have a non-empty name and a string or number value"),
])
def test_invalid_mock_headers(headers, expected):
    errors = bad({"url": URL, "mock": {"status": 500, "headers": headers}})
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("delay", [-1, "2", True, None])
def test_invalid_mock_delay(delay):
    errors = bad({"url": URL, "mock": {"status": 500, "delay": delay}})
    assert any("field 'mock.delay' (optional): expected a number of seconds >= 0" in e for e in errors)


@pytest.mark.parametrize("content_type", ["", 1])
def test_invalid_mock_content_type(content_type):
    errors = bad({"url": URL, "mock": {"status": 500, "content_type": content_type}})
    assert any("field 'mock.content_type' (optional)" in e for e in errors)


def test_invalid_mock_cors():
    errors = bad({"url": URL, "mock": {"status": 500, "cors": "false"}})
    assert any("field 'mock.cors' (optional): expected true or false, got string" in e for e in errors)


def test_kill_ignores_response_fields_and_delay():
    _, warnings = ok({"url": URL, "mock": {"status": "kill", "body": "x", "headers": {}, "delay": 1}})
    assert warnings == ['with "mock.status": "kill" no response is sent, so mock.body, mock.headers, mock.delay has no effect']


def test_timeout_ignores_response_fields_but_not_delay():
    _, warnings = ok({"url": URL, "mock": {"status": "timeout", "cors": False, "delay": 1}})
    assert warnings == ['with "mock.status": "timeout" no response is sent, so mock.cors has no effect']


def test_mock_body_is_kept_as_is():
    for body in ({"a": 1}, [1, 2], "text", 0, False):
        rule, _ = ok({"url": URL, "mock": {"status": 500, "body": body}})
        assert rule.mock.body == body


@pytest.mark.parametrize("op, expected", [
    ("json", "field 'mock.json' is ignored: 'json' only works in 'request' or 'response'"),
    ("replace", "field 'mock.replace' is ignored: 'replace' only works in 'request' or 'response'"),
    ("query", "field 'mock.query' is ignored: 'query' only works in 'request'"),
    ("staus", "unknown field 'mock.staus' is ignored, did you mean 'mock.status'?"),
])
def test_unknown_key_in_mock_warns(op, expected):
    _, warnings = ok({"url": URL, "mock": {"status": 500, op: {}}})
    assert warnings == [expected]


# --- "request" / "response" ---------------------------------------------------

def test_request_or_response_alone_is_a_rule():
    for raw in ({"url": URL, "request": {"headers": {"X": "1"}}},
                {"url": URL, "response": {"status": 500}},
                {"url": URL, "request": {"query": {"a": 1}}, "response": {"json": {"b": 2}}}):
        rule, warnings = ok(raw)
        assert warnings == []
        assert rule.mock is None


def test_all_request_ops():
    rule, warnings = ok({"url": URL, "request": {
        "method": " put ", "url": "https://other.test/v2", "query": {"a": 1, "b": None, "c": True},
        "body": {"x": 1}, "json": {"y": None}, "form": {"f": "1", "g": None},
        "replace": {"from": "a", "to": "b"}, "headers": {"X-A": 1, "Authorization": None}, "delay": 0.5,
    }})
    assert warnings == ["'request.json' is applied on top of 'request.body'"]
    ops = rule.request
    assert ops.method == "PUT"
    assert ops.url == "https://other.test/v2"
    assert ops.query == {"a": "1", "b": None, "c": "true"}
    assert ops.body == {"x": 1}
    assert ops.json == {"y": None}
    assert ops.form == {"f": "1", "g": None}
    assert [(r.source, r.to, r.regex) for r in ops.replace] == [("a", "b", False)]
    assert ops.headers == {"X-A": "1", "Authorization": None}
    assert ops.delay == 0.5
    assert rule.response is None


def test_all_response_ops():
    rule, warnings = ok({"url": URL, "response": {
        "status": 401, "body": "text",
        "replace": [{"from": "a", "to": ""}, {"from": "(\\d+)", "to": "-\\1", "regex": True}],
        "headers": {"Cache-Control": None}, "delay": 2,
    }})
    assert warnings == []
    ops = rule.response
    assert ops.status == 401
    assert ops.body == "text"
    assert [(r.source, r.to, r.regex) for r in ops.replace] == [("a", "", False), ("(\\d+)", "-\\1", True)]
    assert ops.headers == {"Cache-Control": None}
    assert ops.delay == 2.0


@pytest.mark.parametrize("section", ["request", "response"])
@pytest.mark.parametrize("value", [[], "x", None, 1])
def test_section_must_be_an_object(section, value):
    errors = bad({"url": URL, section: value})
    assert any(f"field '{section}' (optional): expected an object of changes" in e for e in errors), errors


@pytest.mark.parametrize("section", ["request", "response"])
def test_empty_section_warns(section):
    _, warnings = ok({"url": URL, section: {}})
    assert warnings == [f"field '{section}' (optional) is empty and changes nothing"]


@pytest.mark.parametrize("section, op, owners", [
    ("response", "query", "'request'"),
    ("response", "form", "'request'"),
    ("response", "method", "'request'"),
    ("response", "url", "'request'"),
    ("request", "status", "'mock' or 'response'"),
    ("response", "cors", "'mock'"),
    ("response", "content_type", "'mock'"),
])
def test_op_of_another_section_is_ignored(section, op, owners):
    _, warnings = ok({"url": URL, section: {op: "x", "delay": 0}})
    assert warnings == [f"field '{section}.{op}' is ignored: '{op}' only works in {owners}"]


def test_unknown_op_suggests_closest():
    _, warnings = ok({"url": URL, "request": {"jsn": {"a": 1}}})
    assert warnings == ["unknown field 'request.jsn' is ignored, did you mean 'request.json'?"]


@pytest.mark.parametrize("ops, expected", [
    ({"method": ""}, "field 'request.method' (optional): expected an HTTP method"),
    ({"method": "*"}, "field 'request.method' (optional): expected an HTTP method"),
    ({"method": 1}, "field 'request.method' (optional): expected an HTTP method"),
    ({"url": "/v2/orders"}, "field 'request.url' (optional): expected a full URL"),
    ({"url": None}, "field 'request.url' (optional): expected a full URL"),
    ({"query": [1]}, "field 'request.query' (optional): expected an object"),
    ({"query": {"a": [1]}}, "field 'request.query' (optional): 'a' must have a non-empty name and a string, number or null value"),
    ({"headers": {" ": "1"}}, "field 'request.headers' (optional): ' ' must have a non-empty name"),
    ({"headers": {"X": {"a": 1}}}, "field 'request.headers' (optional): 'X' must have"),
    ({"form": "a=1"}, "field 'request.form' (optional): expected an object"),
    ({"json": [1]}, "field 'request.json' (optional): expected an object like {\"amount\": -1} "
                    "(to replace the whole body use 'request.body')"),
    ({"json": "x"}, "field 'request.json' (optional): expected an object"),
    ({"body": None}, "field 'request.body' (optional): expected an object, array, string or number"),
    ({"delay": -1}, "field 'request.delay' (optional): expected a number of seconds >= 0"),
    ({"delay": "1"}, "field 'request.delay' (optional): expected a number of seconds >= 0"),
    ({"replace": []}, "field 'request.replace' (optional): expected a non-empty list"),
    ({"replace": "a"}, "field 'request.replace' (optional): expected an object like {\"from\": \"old\", \"to\": \"new\"}"),
    ({"replace": [{"from": "", "to": "x"}]}, "field 'request.replace[0].from' (optional): expected a non-empty string"),
    ({"replace": {"from": "a"}}, "field 'request.replace.to' (optional): expected a string"),
    ({"replace": {"from": "a", "to": "b", "regex": "yes"}}, "field 'request.replace.regex' (optional): expected true or false"),
    ({"replace": {"from": "(", "to": "b", "regex": True}}, "field 'request.replace.from' (optional): invalid regular expression"),
])
def test_invalid_request_ops(ops, expected):
    errors = bad({"url": URL, "request": ops})
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("status, expected", [
    (99, "expected an HTTP status 100-599"),
    (600, "expected an HTTP status 100-599"),
    (True, "expected an HTTP status 100-599"),
    ("401", "write the status as a number without quotes: 401"),
    ("timeout", "\"timeout\" means no response at all, which only 'mock' can do: \"mock\": {\"status\": \"timeout\"}"),
    ("kill", "\"kill\" means no response at all, which only 'mock' can do: \"mock\": {\"status\": \"kill\"}"),
])
def test_invalid_response_status(status, expected):
    errors = bad({"url": URL, "response": {"status": status}})
    assert any(f"field 'response.status' (optional): {expected}" in e for e in errors), errors


def test_replace_to_accepts_numbers():
    rule, _ = ok({"url": URL, "request": {"replace": {"from": "1", "to": 2, "regex": False}}})
    assert rule.request.replace[0].to == "2"


def test_replace_unknown_key_warns():
    _, warnings = ok({"url": URL, "request": {"replace": {"from": "a", "to": "b", "regx": True}}})
    assert warnings == ["field 'request.replace': unknown key 'regx' is ignored, did you mean 'regex'?"]


def test_unusual_method_in_request_warns():
    rule, warnings = ok({"url": URL, "request": {"method": "gett"}})
    assert rule.request.method == "GETT"
    assert warnings == ["field 'request.method' (optional): unusual method \"GETT\", check for a typo"]


def test_errors_in_both_sections_are_reported_at_once():
    errors = bad({"url": URL, "request": {"delay": -1, "json": 1}, "response": {"status": 0}})
    for key in ("'request.delay'", "'request.json'", "'response.status'"):
        assert any(key in e for e in errors), (key, errors)


# --- incompatible: "mock" vs "request" / "response" -----------------------------

def incompatible(errors) -> str:
    found = [e for e in errors if e.startswith("incompatible:")]
    assert len(found) == 1, errors
    return found[0]


def test_mock_with_request_is_an_error():
    msg = incompatible(bad({"url": URL, "mock": MOCK, "request": {"headers": {"X": "1"}}}))
    assert msg == (
        "incompatible: 'mock' cannot be used together with 'request' in one rule. "
        "'mock' answers instead of the server, so the request is never sent, "
        "while 'request' changes the request that goes to the server. Keep either 'mock' or 'request'"
    )


def test_mock_with_response_is_an_error():
    msg = incompatible(bad({"url": URL, "mock": MOCK, "response": {"status": 401}}))
    assert msg == (
        "incompatible: 'mock' cannot be used together with 'response' in one rule. "
        "'mock' answers instead of the server, so the request is never sent, "
        "while 'response' changes the answer that comes back from the server. Keep either 'mock' or 'response'"
    )


def test_mock_with_request_and_response_is_one_error():
    msg = incompatible(bad({"url": URL, "mock": MOCK, "request": {}, "response": {}}))
    assert msg.startswith("incompatible: 'mock' cannot be used together with 'request', 'response' in one rule.")
    assert "while 'request' changes the request that goes to the server and " \
           "'response' changes the answer that comes back from the server" in msg
    assert msg.endswith("Keep either 'mock' or 'request' / 'response'")


def test_incompatible_is_reported_even_if_the_sections_are_invalid():
    errors = bad({"url": URL, "mock": {"status": "x"}, "response": {"status": "y"}})
    incompatible(errors)
    assert any("'mock.status'" in e for e in errors)
    assert any("'response.status'" in e for e in errors)


# --- mock fields at the top level of a rule ----------------------------------------

def test_error_at_the_top_level_is_not_a_mock():
    errors = bad({"url": URL, "error": 500})
    assert any(e.startswith("nothing to do:") for e in errors), errors


def test_mock_fields_next_to_mock_are_ignored_with_a_warning():
    rule, warnings = ok({"url": URL, "mock": MOCK, "body": "x"})
    assert rule.mock.body is None
    assert warnings == [
        "'body' at the top level is ignored: put it inside 'mock' (a fake response) "
        "or 'response' (changes to the real response)"
    ]


def test_mock_fields_at_the_top_level_are_ignored_with_a_warning():
    _, warnings = ok({"url": URL, "response": {"status": 500}, "body": {"a": 1}, "delay": 1})
    assert warnings == [
        "'body', 'delay' at the top level is ignored: put it inside 'mock' (a fake response) "
        "or 'response' (changes to the real response)"
    ]
