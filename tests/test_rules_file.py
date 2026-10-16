"""Loading and hot-reloading the rules file."""
import logging

R1 = {"name": "one", "url": "https://a.test/1", "error": 500}
R2 = {"name": "two", "url": "https://a.test/2", "error": 404}


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
    rules = gremlin.load([{"enabled": False, "error": "nonsense"}, R2])
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
    assert any('rule #2 "typo": field \'error\' (required) is missing' in m for m in log)
    assert any('rule #2 "typo": rule skipped' in m for m in log)
    assert any("Loaded 2 rule(s)" in m and "1 invalid skipped" in m for m in log)


def test_invalid_json_keeps_previous_rules(gremlin, caplog):
    gremlin.load([R1, R2])
    gremlin.write('[{"url": "x" "error": 1}]', raw=True)
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
    rules = gremlin.load([R1, {**R1, "name": "dup", "error": 400}])
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
    other.write_text('[{"url": "https://b.test", "error": 418}, {"url": "https://c.test", "error": 418}]')
    gremlin.tctx.configure(gremlin.addon, rules_file=str(other))
    assert len(gremlin.addon.rules) == 2
    assert gremlin.addon.path == str(other)
