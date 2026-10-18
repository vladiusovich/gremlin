"""Loading and hot-reloading the rules file, and the rules shipped in rules/ and the docs."""
import json
import logging
import re

import pytest

from conftest import ROOT
from mock_errors import Mock, Ops, parse_rule

R1 = {"name": "one", "url": "https://a.test/1", "mock": {"status": 500}}
R2 = {"name": "two", "url": "https://a.test/2", "mock": {"status": 404}}


def messages(caplog, level=None):
    return [r.getMessage() for r in caplog.records if level is None or r.levelno == level]


def test_loads_valid_rules(gremlin, caplog):
    caplog.set_level(logging.INFO)
    rules = gremlin.load([R1, R2])
    assert [r.name for r in rules] == ["one", "two"]
    assert [r.number for r in rules] == [1, 2]
    assert f"Loaded 2 rule(s) from {gremlin.path}" in messages(caplog, logging.INFO)


def test_empty_file_hint(gremlin, caplog):
    caplog.set_level(logging.INFO)
    assert gremlin.load([]) == []
    assert "rules.json is empty: no requests are mocked. Examples: rules/examples.json" in messages(caplog)


def test_utf8_bom_is_accepted(gremlin):
    rules = gremlin.load([R1], encoding="utf-8-sig")
    assert len(rules) == 1


def test_disabled_rules_are_skipped_but_keep_numbering(gremlin, caplog):
    caplog.set_level(logging.INFO)
    # a disabled rule is not validated, even if broken
    rules = gremlin.load([{"enabled": False, "mock": "nonsense"}, R2])
    assert [(r.number, r.name) for r in rules] == [(2, "two")]
    assert any("1 rule(s)" in m and "1 disabled" in m for m in messages(caplog))


def test_non_bool_enabled_is_an_invalid_rule(gremlin, caplog):
    rules = gremlin.load([{**R1, "enabled": "false"}, R2])
    assert [r.name for r in rules] == ["two"]
    assert any("rule #1: field 'enabled' (optional): expected true or false" in m for m in messages(caplog))


def test_invalid_rule_is_skipped_others_loaded(gremlin, caplog):
    rules = gremlin.load([R1, {"name": "typo", "url": "https://a.test/x"}, R2])
    assert [r.name for r in rules] == ["one", "two"]
    log = messages(caplog)
    assert any('rule #2 "typo": nothing to do' in m for m in log)
    assert any('rule #2 "typo": rule skipped' in m for m in log)
    assert any("Loaded 2 rule(s)" in m and "1 invalid skipped" in m for m in log)


def test_invalid_json_keeps_previous_rules(gremlin, caplog):
    gremlin.load([R1, R2])
    gremlin.write('[{"url": "x" "mock": 1}]', raw=True)
    gremlin.addon._reload()
    assert [r.name for r in gremlin.addon.rules] == ["one", "two"]
    assert any("rules.json:1:" in m and "invalid JSON" in m and "Keeping the previous 2 rule(s)" in m
               for m in messages(caplog))


def test_non_array_root_keeps_previous_rules(gremlin, caplog):
    gremlin.load([R1])
    gremlin.write({"rules": []})
    gremlin.addon._reload()
    assert len(gremlin.addon.rules) == 1
    assert any("the root must be a JSON array [ ... ] of rules, got object" in m for m in messages(caplog))


def test_broken_file_is_reported_once_per_change(gremlin, caplog):
    gremlin.load([R1])
    gremlin.write("not json", raw=True)
    for _ in range(3):
        gremlin.addon._reload()
    assert sum("invalid JSON" in m for m in messages(caplog)) == 1


def test_hot_reload_on_change(gremlin):
    gremlin.load([R1])
    gremlin.write([R1, R2])
    gremlin.addon._reload()
    assert len(gremlin.addon.rules) == 2


def test_no_reload_without_change(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.load([R1])
    caplog.clear()
    gremlin.addon._reload()
    assert messages(caplog) == []


def test_missing_file_clears_rules_and_is_reported_once(gremlin, caplog):
    gremlin.load([R1])
    gremlin.path.unlink()
    for _ in range(3):
        gremlin.addon._reload()
    assert gremlin.addon.rules == []
    assert sum("Rules file not found" in m for m in messages(caplog)) == 1


def test_file_appearing_later_is_loaded(gremlin):
    gremlin.configure()  # no file yet
    assert gremlin.addon.rules == []
    gremlin.write([R1])
    gremlin.addon._reload()
    assert len(gremlin.addon.rules) == 1


def test_duplicate_rule_warns(gremlin, caplog):
    rules = gremlin.load([R1, {**R1, "name": "dup", "mock": {"status": 400}}])
    assert len(rules) == 2
    assert any('rule #2 "dup": same method/url/query as rule #1 "one", it will never match' in m
               for m in messages(caplog, logging.WARNING))


def test_same_url_different_query_is_not_a_duplicate(gremlin, caplog):
    gremlin.load([{**R1, "query": {"a": "1"}}, {**R1, "query": {"a": "2"}}])
    assert not any("never match" in m for m in messages(caplog))


def test_warnings_do_not_skip_the_rule(gremlin, caplog):
    rules = gremlin.load([{**R1, "metod": "GET"}])
    assert len(rules) == 1
    assert any("did you mean 'method'" in m for m in messages(caplog, logging.WARNING))


def test_errors_are_warnings_during_startup(gremlin, caplog):
    # mitmdump exits on an error logged during startup, so a bad rule must not be logged as error
    gremlin.load([{"url": "https://a.test"}])
    assert messages(caplog, logging.ERROR) == []
    assert any("rule skipped" in m for m in messages(caplog, logging.WARNING))


def test_errors_are_errors_after_startup(gremlin, caplog):
    gremlin.load([R1])
    gremlin.addon.running()
    gremlin.write([{"url": "https://a.test"}])
    gremlin.addon._reload()
    assert any("rule skipped" in m for m in messages(caplog, logging.ERROR))


def test_changing_rules_file_option_switches_file(gremlin, tmp_path):
    gremlin.load([R1])
    other = tmp_path / "other.json"
    other.write_text('[{"url": "https://b.test", "mock": {"status": 418}}, '
                     '{"url": "https://c.test", "mock": {"status": 418}}]')
    gremlin.tctx.configure(gremlin.addon, rules_file=str(other))
    assert len(gremlin.addon.rules) == 2
    assert gremlin.addon.path == str(other)


def test_comment_only_entries_are_notes(gremlin, caplog):
    caplog.set_level(logging.INFO)
    rules = gremlin.load([{"comment": "=== group ==="}, R1, {"comment": ["any", "text"]}, R2])
    assert [(r.number, r.name) for r in rules] == [(2, "one"), (4, "two")]
    assert messages(caplog, logging.WARNING) == []
    assert f"Loaded 2 rule(s) from {gremlin.path}" in messages(caplog, logging.INFO)


def test_empty_object_is_still_an_invalid_rule(gremlin, caplog):
    rules = gremlin.load([{}, R1])
    assert [r.name for r in rules] == ["one"]
    assert any("rule #1: field 'url' (required) is missing" in m for m in messages(caplog))


def test_incompatible_rule_is_skipped_with_the_reason(gremlin, caplog):
    rules = gremlin.load([
        {"name": "mixed", "url": "https://a.test/1", "mock": {"status": 500}, "response": {"status": 401}},
        R2,
    ])
    assert [r.name for r in rules] == ["two"]
    log = messages(caplog)
    assert any("rules.json: rule #1 \"mixed\": incompatible: 'mock' cannot be used together with 'response'" in m
               for m in log)
    assert 'rules.json: rule #1 "mixed": rule skipped' in log
    assert any("1 invalid skipped" in m for m in log)


# --- rules shipped with the project -------------------------------------------

def test_examples_file_loads_without_warnings(gremlin, caplog):
    caplog.set_level(logging.INFO)
    gremlin.path = ROOT / "rules" / "examples.json"
    gremlin.configure()
    rules = gremlin.addon.rules
    assert messages(caplog, logging.WARNING) == []
    assert messages(caplog, logging.ERROR) == []
    # every kind of rule is covered
    mocks = [r.mock for r in rules if r.mock]
    assert {"timeout", "kill"} <= {m.status for m in mocks}
    mock_fields = {k for m in mocks if isinstance(m.status, int) for k, v in vars(m).items()
                   if v != getattr(Mock(status=500), k)}
    assert mock_fields == {"status", "body", "content_type", "headers", "delay", "cors"}
    defaults = vars(Ops())
    request_ops = {op for r in rules if r.request for op, v in vars(r.request).items() if v != defaults[op]}
    response_ops = {op for r in rules if r.response for op, v in vars(r.response).items() if v != defaults[op]}
    assert request_ops == {"method", "url", "query", "body", "json", "form", "replace", "headers", "delay"}
    assert response_ops == {"status", "body", "json", "replace", "headers", "delay"}
    assert any(r.request and r.response for r in rules)


def doc_rules() -> list:
    """Every ```json block in the docs that is a rule or a list of rules."""
    params = []
    for doc in ("README.md", "rules/README.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"```json\r?\n(.*?)```", text, re.S)):
            data = json.loads(block)  # a ```json block must be valid JSON
            for j, raw in enumerate(data if isinstance(data, list) else [data]):
                if raw.keys() != {"comment"}:
                    params.append(pytest.param(raw, id=f"{doc}#{i}.{j}"))
    return params


@pytest.mark.parametrize("raw", doc_rules())
def test_doc_examples_are_valid_rules(raw):
    rule, errors, warnings = parse_rule(1, raw)
    assert errors == []
    assert warnings == []
