"""Validation of a single rule: parse_rule() in addons/mock_errors.py."""
import pytest

from mock_errors import Rule, parse_rule

URL = "https://api.example.com/v1/orders"


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


def test_minimal_rule_gets_defaults():
    rule, warnings = ok({"url": URL, "error": 500})
    assert warnings == []
    assert rule.url == URL
    assert rule.error == 500
    assert rule.method == "*"
    assert rule.query == {}
    assert rule.body is None
    assert rule.content_type == "application/json"
    assert rule.headers == {}
    assert rule.delay == 0.0
    assert rule.cors is True
    assert rule.name is None


def test_all_fields():
    rule, warnings = ok({
        "name": "n", "method": "post", "url": URL, "query": {"a": 1, "b": True},
        "error": 429, "body": {"x": 1}, "content_type": "text/plain",
        "headers": {"Retry-After": 10}, "delay": 1.5, "cors": False,
        "enabled": True, "comment": ["anything"],
    }, number=7)
    assert warnings == []
    assert rule.number == 7
    assert rule.label == 'rule #7 "n"'
    assert rule.method == "POST"
    assert rule.query == {"a": "1", "b": "true"}
    assert rule.headers == {"Retry-After": "10"}
    assert rule.delay == 1.5
    assert rule.cors is False


def test_label_without_name():
    rule, _ = ok({"url": URL, "error": 500}, number=3)
    assert rule.label == "rule #3"


@pytest.mark.parametrize("error", [100, 404, 599, "timeout", "kill"])
def test_valid_errors(error):
    rule, _ = ok({"url": URL, "error": error})
    assert rule.error == error


def test_timeout_default_delay_is_30():
    rule, _ = ok({"url": URL, "error": "timeout"})
    assert rule.delay == 30.0


def test_timeout_custom_delay():
    rule, _ = ok({"url": URL, "error": "timeout", "delay": 2})
    assert rule.delay == 2.0


@pytest.mark.parametrize("missing", ["url", "error"])
def test_required_field_missing(missing):
    raw = {"url": URL, "error": 500}
    del raw[missing]
    errors = bad(raw)
    assert any(f"field '{missing}' (required) is missing" in e for e in errors)


@pytest.mark.parametrize("error, expected", [
    (99, "must be 100-599"),
    (600, "must be 100-599"),
    ("500", "without quotes: 500"),
    (" 404 ", "without quotes: 404"),
    ("boom", 'an HTTP status 100-599, "timeout" or "kill"'),
    (True, 'an HTTP status 100-599, "timeout" or "kill"'),
    (None, 'an HTTP status 100-599, "timeout" or "kill"'),
    (500.5, 'an HTTP status 100-599, "timeout" or "kill"'),
])
def test_invalid_error(error, expected):
    errors = bad({"url": URL, "error": error})
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("url", ["", "   ", 5, None])
def test_invalid_url(url):
    errors = bad({"url": url, "error": 500})
    assert any("field 'url' (required): expected a non-empty string" in e for e in errors)


def test_url_without_scheme_warns():
    _, warnings = ok({"url": "api.example.com/*", "error": 500})
    assert any("has no scheme and will never match" in w for w in warnings)


def test_url_starting_with_wildcard_does_not_warn():
    _, warnings = ok({"url": "*/v1/orders", "error": 500})
    assert warnings == []


def test_not_an_object():
    rule, errors, warnings = parse_rule(1, ["url"])
    assert rule is None
    assert errors == ["must be a JSON object, got array"]
    assert warnings == []


def test_all_problems_are_reported_at_once():
    errors = bad({"url": 1, "error": "x", "delay": -1, "cors": "yes", "method": 5})
    fields = ("'url'", "'error'", "'delay'", "'cors'", "'method'")
    for f in fields:
        assert any(f in e for e in errors), (f, errors)


def test_unknown_field_suggests_closest():
    _, warnings = ok({"url": URL, "error": 500, "metod": "GET"})
    assert warnings == ["unknown field 'metod' is ignored, did you mean 'method'?"]


def test_unknown_field_without_suggestion():
    _, warnings = ok({"url": URL, "error": 500, "zzzzzz": 1})
    assert warnings == ["unknown field 'zzzzzz' is ignored"]


def test_unusual_method_warns():
    rule, warnings = ok({"url": URL, "error": 500, "method": " gett "})
    assert rule.method == "GETT"
    assert any('unusual method "GETT"' in w for w in warnings)


@pytest.mark.parametrize("method", ["", "  ", 1, None])
def test_invalid_method(method):
    errors = bad({"url": URL, "error": 500, "method": method})
    assert any("field 'method' (optional)" in e for e in errors)


@pytest.mark.parametrize("query, expected", [
    ([1], "field 'query' (optional): expected an object"),
    ({"a": {"b": 1}}, "value of 'a' must be a string or number, got object"),
    ({"a": None}, "value of 'a' must be a string or number, got null"),
])
def test_invalid_query(query, expected):
    errors = bad({"url": URL, "error": 500, "query": query})
    assert any(expected in e for e in errors), errors


def test_query_with_question_mark_in_url_warns():
    _, warnings = ok({"url": URL + "?a=1", "error": 500, "query": {"a": "1"}})
    assert any("move the parameters to 'query'" in w for w in warnings)


@pytest.mark.parametrize("headers, expected", [
    ("X: 1", "expected an object"),
    ({" ": "1"}, "header ' ' must have a non-empty name"),
    ({"X": [1]}, "header 'X' must have a non-empty name and a string or number value"),
])
def test_invalid_headers(headers, expected):
    errors = bad({"url": URL, "error": 500, "headers": headers})
    assert any(expected in e for e in errors), errors


@pytest.mark.parametrize("delay", [-1, "2", True, None])
def test_invalid_delay(delay):
    errors = bad({"url": URL, "error": 500, "delay": delay})
    assert any("field 'delay' (optional): expected a number of seconds >= 0" in e for e in errors)


@pytest.mark.parametrize("content_type", ["", 1])
def test_invalid_content_type(content_type):
    errors = bad({"url": URL, "error": 500, "content_type": content_type})
    assert any("field 'content_type' (optional)" in e for e in errors)


def test_invalid_cors():
    errors = bad({"url": URL, "error": 500, "cors": "false"})
    assert any("field 'cors' (optional): expected true or false, got string" in e for e in errors)


def test_invalid_name():
    errors = bad({"url": URL, "error": 500, "name": 5})
    assert any("field 'name' (optional): expected a string, got number 5" in e for e in errors)


def test_kill_ignores_response_fields_and_delay():
    _, warnings = ok({"url": URL, "error": "kill", "body": "x", "headers": {}, "delay": 1})
    assert warnings == ['with "error": "kill" no response is sent, so body, headers, delay has no effect']


def test_timeout_ignores_response_fields_but_not_delay():
    _, warnings = ok({"url": URL, "error": "timeout", "cors": False, "delay": 1})
    assert warnings == ['with "error": "timeout" no response is sent, so cors has no effect']


def test_body_is_kept_as_is():
    for body in ({"a": 1}, [1, 2], "text", 0, False):
        rule, _ = ok({"url": URL, "error": 500, "body": body})
        assert rule.body == body
