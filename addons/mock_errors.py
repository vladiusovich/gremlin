"""
Gremlin's mitmproxy addon: picks requests by method + URL and either answers instead of the
server ("mock"), or changes the real request and/or the real server response ("request",
"response"). Rules live in a JSON file.

Run:
  gremlin proxy run
  (or manually: mitmdump -s addons/mock_errors.py --set rules_file=rules/default.json)

The rules file is reloaded automatically when it changes (no need to restart mitmproxy).
Format: see rules/README.md and the schema below, examples: rules/examples.json.

Validation on load:
  - invalid JSON or a non-array root: the whole file is rejected, previous rules stay active;
  - an invalid rule (including "mock" together with "request" / "response"): only that rule
    is skipped, the others are loaded;
  - unknown fields, fields that have no effect, the old top-level "error" format: warning,
    the rule is still loaded.
"""
import asyncio
import difflib
import fnmatch
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

from mitmproxy import ctx, http  # type: ignore
from mitmproxy.net.http import status_codes  # type: ignore

log = logging.getLogger(__name__)

# Rule schema. Keep in sync with rules/README.md and the "Rules" section of README.md.
REQUIRED_FIELDS = {
    "url": 'URL pattern with scheme, e.g. "https://host:8443/api/*"',
}
OPTIONAL_FIELDS = {
    "method": 'HTTP method or "*" (default "*")',
    "query": "object of query params that must be present (default: not checked)",
    "mock": 'answer instead of the server, the request is never sent: {"status": 500, "body": {...}}',
    "request": "object of changes to the request before it is sent to the server",
    "response": "object of changes to the real server response",
    "enabled": "false skips the rule without validating it (default true)",
    "name": "label shown in logs",
    "comment": "free text, ignored; an entry with only a comment is a note, not a rule",
}
ALL_FIELDS = {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}
SPECIAL_ERRORS = ("timeout", "kill")
KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}

# The fake response of "mock"
MOCK_OPS = {
    "status": 'HTTP status 100-599, "timeout" (hang, then drop the connection) or "kill" (drop it at once)',
    "body": "object/array is sent as JSON, string as is (default: generated JSON)",
    "content_type": 'Content-Type of the response (default "application/json")',
    "headers": "object of response headers (default: none)",
    "delay": 'seconds to wait before responding, >= 0 (default 0, 30 for "timeout")',
    "cors": "add CORS headers for the request's Origin (default true)",
}
# Fields that only make sense when a response is sent (not for "timeout" / "kill")
MOCK_RESPONSE_OPS = ("body", "content_type", "headers", "cors")
# The format before "mock": these fields at the top level of a rule -> the "mock" field they became
LEGACY_MOCK_FIELDS = {"error": "status", "body": "body", "content_type": "content_type",
                      "headers": "headers", "delay": "delay", "cors": "cors"}

# Changes allowed in the "request" and "response" sections, applied in this order.
REQUEST_OPS = {
    "method": 'new HTTP method, e.g. "PUT"',
    "url": 'new URL, e.g. "https://other-host/api/v2/orders"',
    "query": "object of query params to set, null removes a param",
    "body": "new body: object/array is sent as JSON, string as is",
    "json": "object merged into the JSON body (JSON Merge Patch), null removes a field",
    "form": "object of form fields (x-www-form-urlencoded) to set, null removes a field",
    "replace": 'find/replace in the body: {"from": "...", "to": "...", "regex": false} or a list of them',
    "headers": "object of headers to set, null removes a header",
    "delay": "seconds to wait, >= 0",
}
RESPONSE_OPS = {
    "status": "new HTTP status 100-599",
    "body": REQUEST_OPS["body"],
    "json": REQUEST_OPS["json"],
    "replace": REQUEST_OPS["replace"],
    "headers": REQUEST_OPS["headers"],
    "delay": REQUEST_OPS["delay"],
}
SECTION_OPS = {"mock": MOCK_OPS, "request": REQUEST_OPS, "response": RESPONSE_OPS}
REPLACE_KEYS = ("from", "to", "regex")


@dataclass
class Mock:
    """The fake response sent instead of asking the server."""
    status: int | str
    body: Any = None
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    cors: bool = True


@dataclass
class Replacement:
    source: str  # the "from" value as written in the rule, for logs
    pattern: re.Pattern
    to: str
    regex: bool

    def apply(self, text: str) -> tuple[str, int]:
        # plain strings: "to" is literal, regex: "to" may use \1 / \g<name>
        repl = self.to if self.regex else (lambda _m: self.to)
        return self.pattern.subn(repl, text)


@dataclass
class Ops:
    """Changes to a request or a response. None / empty means "do not touch"."""
    method: str | None = None
    url: str | None = None
    status: int | None = None
    query: dict[str, str | None] = field(default_factory=dict)
    body: Any = None
    json: dict | None = None
    form: dict[str, str | None] = field(default_factory=dict)
    replace: list[Replacement] = field(default_factory=list)
    headers: dict[str, str | None] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class Rule:
    number: int  # 1-based position in the file, as shown in logs
    url: str
    name: str | None = None
    method: str = "*"
    query: dict[str, str] = field(default_factory=dict)
    mock: Mock | None = None
    request: Ops | None = None
    response: Ops | None = None

    @property
    def label(self) -> str:
        return f'rule #{self.number}' + (f' "{self.name}"' if self.name else "")


def _kind(key: str) -> str:
    return "required" if key in REQUIRED_FIELDS else "optional"


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    return "object"


def _bad(key: str, expected: str, value: Any, kind: str | None = None) -> str:
    return f"field '{key}' ({kind or _kind(key)}): expected {expected}, got {_json_type(value)} {json.dumps(value)}"


def _scalar_to_str(value: Any) -> str | None:
    """JSON scalar -> string as it appears in a URL/header; None for objects/arrays/null."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def _is_status(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 599


def _quote_list(names) -> str:
    return ", ".join(f"'{n}'" for n in names)


def _unknown_op(section: str, op: str, warnings: list[str]):
    """Warning for a key that is not allowed in a "mock" / "request" / "response" section."""
    key = f"{section}.{op}"
    owners = [s for s, ops in SECTION_OPS.items() if s != section and op in ops]
    if owners:
        warnings.append(f"field '{key}' is ignored: '{op}' only works in {' or '.join(repr(s) for s in owners)}")
    else:
        hint = difflib.get_close_matches(op, SECTION_OPS[section], n=1)
        warnings.append(f"unknown field '{key}' is ignored" + (f", did you mean '{section}.{hint[0]}'?" if hint else ""))


def _parse_changes(key: str, value: Any, example: str, errors: list[str]) -> dict[str, str | None]:
    """{"name": scalar | null} -> {"name": str | None}; None means "remove"."""
    if not isinstance(value, dict):
        errors.append(_bad(key, f"an object like {example}", value))
        return {}
    changes: dict[str, str | None] = {}
    for k, v in value.items():
        s = _scalar_to_str(v)
        if not k.strip() or (s is None and v is not None):
            errors.append(f"field '{key}' (optional): '{k}' must have a non-empty name and a string, number or null value")
        else:
            changes[k] = s
    return changes


def _parse_replace(key: str, value: Any, errors: list[str], warnings: list[str]) -> list[Replacement]:
    items = value if isinstance(value, list) else [value]
    if not items:
        errors.append(_bad(key, 'a non-empty list of {"from": "...", "to": "..."}', value))
        return []
    result: list[Replacement] = []
    for i, item in enumerate(items):
        where = f"{key}[{i}]" if isinstance(value, list) else key
        if not isinstance(item, dict):
            errors.append(_bad(where, 'an object like {"from": "old", "to": "new"}', item))
            continue
        for k in item:
            if k not in REPLACE_KEYS:
                hint = difflib.get_close_matches(k, REPLACE_KEYS, n=1)
                warnings.append(f"field '{where}': unknown key '{k}' is ignored" + (f", did you mean '{hint[0]}'?" if hint else ""))
        source, to, regex = item.get("from"), item.get("to"), item.get("regex", False)
        ok = True
        if not isinstance(source, str) or not source:
            errors.append(_bad(f"{where}.from", "a non-empty string", source))
            ok = False
        if _scalar_to_str(to) is None:
            errors.append(_bad(f"{where}.to", 'a string ("" to delete the match)', to))
            ok = False
        if not isinstance(regex, bool):
            errors.append(_bad(f"{where}.regex", "true or false", regex))
            ok = False
        if not ok:
            continue
        try:
            pattern = re.compile(source if regex else re.escape(source))
        except re.error as e:
            errors.append(f"field '{where}.from' (optional): invalid regular expression: {e}")
            continue
        result.append(Replacement(source, pattern, _scalar_to_str(to), regex))
    return result


def _parse_mock(raw: Any, errors: list[str], warnings: list[str], legacy: bool = False) -> Mock | None:
    """Validates the "mock" section, or (legacy=True) the old top-level fields converted to it.
    Returns None if it has errors."""
    def name(op: str) -> str:
        # messages name the fields the way they are written in the file
        if legacy:
            return "error" if op == "status" else op
        return f"mock.{op}"

    if not isinstance(raw, dict):
        errors.append(_bad("mock", 'an object like {"status": 500, "body": {"code": "DOWN"}}', raw))
        return None
    if not legacy:
        for op in raw:
            if op not in MOCK_OPS:
                _unknown_op("mock", op, warnings)
    n_errors = len(errors)

    status = raw.get("status")
    if "status" not in raw:
        errors.append(f"field 'mock.status' (required) is missing: {MOCK_OPS['status']}")
    elif _is_status(status) or status in SPECIAL_ERRORS:
        pass
    elif isinstance(status, int) and not isinstance(status, bool):
        errors.append(f"field '{name('status')}' (required): HTTP status must be 100-599, got {status}")
    elif isinstance(status, str) and status.strip().isdigit():
        errors.append(f"field '{name('status')}' (required): write the status as a number without quotes: {status.strip()}")
    else:
        errors.append(_bad(name("status"), 'an HTTP status 100-599, "timeout" or "kill"', status, "required"))

    content_type = raw.get("content_type", "application/json")
    if not isinstance(content_type, str) or not content_type.strip():
        errors.append(_bad(name("content_type"), 'a string like "application/json"', content_type))

    headers: dict[str, str] = {}
    raw_headers = raw.get("headers")
    if raw_headers is not None:
        if not isinstance(raw_headers, dict):
            errors.append(_bad(name("headers"), 'an object like {"Retry-After": "10"}', raw_headers))
        else:
            for k, v in raw_headers.items():
                s = _scalar_to_str(v)
                if not k.strip() or s is None:
                    errors.append(f"field '{name('headers')}' (optional): header '{k}' must have a non-empty name "
                                  "and a string or number value")
                else:
                    headers[k] = s

    default_delay = 30.0 if status == "timeout" else 0.0
    delay = raw.get("delay", default_delay)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
        errors.append(_bad(name("delay"), "a number of seconds >= 0", delay))
        delay = default_delay

    cors = raw.get("cors", True)
    if not isinstance(cors, bool):
        errors.append(_bad(name("cors"), "true or false", cors))

    if status in SPECIAL_ERRORS:
        ignored = [name(k) for k in MOCK_RESPONSE_OPS if k in raw]
        if status == "kill" and "delay" in raw:
            ignored.append(name("delay"))
        if ignored:
            warnings.append(f"with \"{name('status')}\": \"{status}\" no response is sent, "
                            f"so {', '.join(ignored)} has no effect")

    if len(errors) > n_errors:
        return None
    return Mock(status=status, body=raw.get("body"), content_type=content_type,
                headers=headers, delay=float(delay), cors=cors)


def _parse_ops(section: str, raw: Any, errors: list[str], warnings: list[str]) -> Ops | None:
    """Validates a "request" / "response" section. Returns None if it has errors."""
    allowed = SECTION_OPS[section]
    if not isinstance(raw, dict):
        errors.append(_bad(section, 'an object of changes, e.g. {"headers": {"X-Debug": "1"}}', raw))
        return None
    if not raw:
        warnings.append(f"field '{section}' (optional) is empty and changes nothing")
    n_errors = len(errors)
    ops = Ops()
    for op, value in raw.items():
        key = f"{section}.{op}"
        if op not in allowed:
            _unknown_op(section, op, warnings)
            continue

        if op == "method":
            if not isinstance(value, str) or not value.strip() or value.strip() == "*":
                errors.append(_bad(key, 'an HTTP method like "PUT"', value))
            else:
                ops.method = value.strip().upper()
                if ops.method not in KNOWN_METHODS:
                    warnings.append(f"field '{key}' (optional): unusual method \"{ops.method}\", check for a typo")
        elif op == "url":
            if not isinstance(value, str) or not value.startswith(("http://", "https://")):
                errors.append(_bad(key, 'a full URL like "https://host/path"', value))
            else:
                ops.url = value
        elif op == "status":
            if isinstance(value, str) and value.strip().isdigit():
                errors.append(f"field '{key}' (optional): write the status as a number without quotes: {value.strip()}")
            elif value in SPECIAL_ERRORS:
                errors.append(f"field '{key}' (optional): \"{value}\" means no response at all, "
                              f"which only 'mock' can do: \"mock\": {{\"status\": \"{value}\"}}")
            elif not _is_status(value):
                errors.append(_bad(key, "an HTTP status 100-599", value))
            else:
                ops.status = value
        elif op == "query":
            ops.query = _parse_changes(key, value, '{"lang": "en", "debug": null}', errors)
        elif op == "form":
            ops.form = _parse_changes(key, value, '{"amount": "-1", "comment": null}', errors)
        elif op == "headers":
            ops.headers = _parse_changes(key, value, '{"X-Debug": "1", "Authorization": null}', errors)
        elif op == "json":
            if not isinstance(value, dict):
                errors.append(_bad(key, f"an object like {{\"amount\": -1}} (to replace the whole body use '{section}.body')", value))
            else:
                ops.json = value
        elif op == "body":
            if value is None:
                errors.append(_bad(key, 'an object, array, string or number ("" for an empty body)', value))
            else:
                ops.body = value
        elif op == "replace":
            ops.replace = _parse_replace(key, value, errors, warnings)
        elif op == "delay":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                errors.append(_bad(key, "a number of seconds >= 0", value))
            else:
                ops.delay = float(value)

    if ops.body is not None and ops.json is not None:
        warnings.append(f"'{section}.json' is applied on top of '{section}.body'")
    return None if len(errors) > n_errors else ops


def parse_rule(number: int, raw: Any) -> tuple[Rule | None, list[str], list[str]]:
    """Validates one rule. Returns (rule or None if invalid, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"must be a JSON object, got {_json_type(raw)}"], []

    legacy = [k for k in LEGACY_MOCK_FIELDS if k in raw]
    for key in raw:
        if key not in ALL_FIELDS and key not in LEGACY_MOCK_FIELDS:
            hint = difflib.get_close_matches(key, ALL_FIELDS, n=1)
            warnings.append(f"unknown field '{key}' is ignored" + (f", did you mean '{hint[0]}'?" if hint else ""))
    for key, description in REQUIRED_FIELDS.items():
        if key not in raw:
            errors.append(f"field '{key}' (required) is missing: {description}")

    # What the rule does: answer instead of the server ("mock", or the old top-level "error"),
    # or change the real traffic ("request" / "response"). The two cannot be mixed.
    mock_key = "mock" if "mock" in raw else "error" if "error" in raw else None
    real = [s for s in ("request", "response") if s in raw]
    if mock_key is None and not real:
        errors.append(
            "nothing to do: add 'mock' to answer instead of the server, "
            "or 'request' / 'response' to change the real request / response"
        )
    if mock_key and real:
        changes = " and ".join(
            {"request": "'request' changes the request that goes to the server",
             "response": "'response' changes the answer that comes back from the server"}[s] for s in real)
        errors.append(
            f"incompatible: '{mock_key}' cannot be used together with {_quote_list(real)} in one rule. "
            f"'{mock_key}' answers instead of the server, so the request is never sent, while {changes}. "
            f"Keep either '{mock_key}' or {' / '.join(repr(s) for s in real)}"
        )

    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        errors.append(_bad("name", "a string", name))
        name = None

    url = raw.get("url")
    if "url" in raw:
        if not isinstance(url, str) or not url.strip():
            errors.append(_bad("url", "a non-empty string", url))
        elif not url.startswith(("http://", "https://", "*")):
            warnings.append(
                f"field 'url' (required): \"{url}\" has no scheme and will never match, "
                "URLs are matched in full, e.g. \"https://host/api/*\""
            )

    method = raw.get("method", "*")
    if not isinstance(method, str) or not method.strip():
        errors.append(_bad("method", 'a string like "GET" or "*"', method))
        method = "*"
    method = method.strip().upper()
    if method != "*" and method not in KNOWN_METHODS:
        warnings.append(f"field 'method' (optional): unusual method \"{method}\", check for a typo")

    query: dict[str, str] = {}
    raw_query = raw.get("query")
    if raw_query is not None:
        if not isinstance(raw_query, dict):
            errors.append(_bad("query", 'an object like {"Type": "Cancel"}', raw_query))
        else:
            for k, v in raw_query.items():
                s = _scalar_to_str(v)
                if s is None:
                    errors.append(f"field 'query' (optional): value of '{k}' must be a string or number, got {_json_type(v)}")
                else:
                    query[k] = s
            if isinstance(url, str) and "?" in url:
                warnings.append(
                    "field 'url' (required): contains '?', but with 'query' set the URL is matched "
                    "without the query string; move the parameters to 'query'"
                )

    mock = None
    if "mock" in raw:
        mock = _parse_mock(raw["mock"], errors, warnings)
        if legacy:
            errors.append(
                f"{_quote_list(legacy)} at the top level is the old format of 'mock' and cannot be used "
                f"together with 'mock': move it inside 'mock'"
            )
    elif "error" in raw:
        converted = {LEGACY_MOCK_FIELDS[k]: raw[k] for k in legacy}
        mock = _parse_mock(converted, errors, warnings, legacy=True)
        warnings.append(
            f"old format: {_quote_list(legacy)} at the top level still works, but write it as "
            f"\"mock\": {json.dumps(converted, ensure_ascii=False)}"
        )
    elif legacy:
        warnings.append(
            f"{_quote_list(legacy)} at the top level is ignored: put it inside 'mock' (a fake response) "
            "or 'response' (changes to the real response)"
        )

    request_ops = _parse_ops("request", raw["request"], errors, warnings) if "request" in raw else None
    response_ops = _parse_ops("response", raw["response"], errors, warnings) if "response" in raw else None

    if errors:
        return None, errors, warnings
    return Rule(
        number=number,
        url=url,
        name=name,
        method=method,
        query=query,
        mock=mock,
        request=request_ops,
        response=response_ops,
    ), errors, warnings


# --- applying changes to a request / response -----------------------------------

def merge_patch(target: Any, patch: Any) -> Any:
    """JSON Merge Patch (RFC 7396): objects are merged recursively, null removes a key,
    anything else (including arrays) replaces the value."""
    if not isinstance(patch, dict):
        return patch
    result = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            result.pop(k, None)
        else:
            result[k] = merge_patch(result.get(k), v)
    return result


def _set_changes(target, changes: dict[str, str | None]):
    """Applies {"name": value | None} to a mitmproxy multidict (headers, query, form)."""
    for k, v in changes.items():
        if v is None:
            if k in target:
                del target[k]
        else:
            target[k] = v


def _set_json_content(msg: http.Message, value: Any):
    msg.content = json.dumps(value).encode()
    if "content-type" not in msg.headers:
        msg.headers["Content-Type"] = "application/json"


def apply_ops(ops: Ops, msg: http.Message, warn) -> list[str]:
    """Applies the changes to a request or a response. Returns the names of the applied
    changes (for the log); problems that skip a change are reported through warn(text)."""
    done: list[str] = []

    if isinstance(msg, http.Request):
        if ops.method:
            msg.method = ops.method
            done.append("method")
        if ops.url:
            msg.url = ops.url
            done.append("url")
        if ops.query:
            _set_changes(msg.query, ops.query)
            done.append("query")
    elif ops.status is not None:
        msg.status_code = ops.status
        msg.reason = status_codes.RESPONSES.get(ops.status, "")
        done.append("status")

    if ops.body is not None:
        if isinstance(ops.body, (dict, list)):
            _set_json_content(msg, ops.body)
        else:
            msg.content = (ops.body if isinstance(ops.body, str) else json.dumps(ops.body)).encode()
        done.append("body")

    if ops.json is not None:
        content = msg.get_content(strict=False) or b""
        try:
            current = json.loads(content) if content.strip() else {}
        except ValueError:
            warn("'json' skipped: the body is not JSON (use 'replace' or 'body' instead)")
        else:
            if isinstance(current, dict):
                _set_json_content(msg, merge_patch(current, ops.json))
                done.append("json")
            else:
                warn(f"'json' skipped: the body is a JSON {_json_type(current)}, not an object (use 'body' instead)")

    if ops.form and isinstance(msg, http.Request):
        content_type = msg.headers.get("content-type", "")
        if msg.raw_content and "application/x-www-form-urlencoded" not in content_type.lower():
            warn(f"'form' skipped: the body is not a form (Content-Type: {content_type or 'none'})")
        else:
            _set_changes(msg.urlencoded_form, ops.form)
            done.append("form")

    if ops.replace:
        text = msg.get_text(strict=False)
        if text is None:
            warn("'replace' skipped: the body cannot be decoded as text")
        else:
            total = 0
            for r in ops.replace:
                text, n = r.apply(text)
                total += n
                if not n:
                    warn(f"'replace': {json.dumps(r.source)} not found in the body")
            if total:
                msg.text = text
                done.append(f"replace x{total}")

    if ops.headers:
        _set_changes(msg.headers, ops.headers)
        done.append("headers")

    if ops.delay:
        done.append(f"delay {ops.delay:g}s")
    return done


class MockErrors:
    def __init__(self):
        self.rules: list[Rule] = []
        self.path: str | None = None
        self.mtime: float | None = None
        self.missing_reported = False
        self.started = False
        # flow.id -> rule whose "response" changes wait for the server response
        self.pending: dict[str, Rule] = {}

    def _error(self, msg: str):
        # mitmdump exits if anything is logged as an error during startup, and a bad rule
        # must not take the whole proxy down: report startup problems as warnings
        if self.started:
            log.error(msg)
        else:
            log.warning(msg)

    def load(self, loader):
        loader.add_option(
            name="rules_file",
            typespec=str,
            default="rules.json",
            help="Path to the JSON rules file",
        )

    def configure(self, updated):
        if "rules_file" in updated:
            self.path = os.path.abspath(ctx.options.rules_file)
            self.mtime = None
            self.missing_reported = False
            self._reload()

    def running(self):
        self.started = True

    def _reload(self):
        try:
            mtime = os.path.getmtime(self.path)
        except OSError:
            # report once, not on every request
            if not self.missing_reported:
                self._error(f"Rules file not found: {self.path}. No requests are mocked until it appears.")
                self.missing_reported = True
            self.mtime = None
            self.rules = []
            return
        self.missing_reported = False
        if mtime == self.mtime:
            return
        # remember mtime even on failure, so a broken file is reported once per change
        self.mtime = mtime
        fname = os.path.basename(self.path)
        keep = f"Keeping the previous {len(self.rules)} rule(s)."

        try:
            # utf-8-sig: tolerate a BOM added by some editors
            with open(self.path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            self._error(f"{fname}:{e.lineno}:{e.colno}: invalid JSON: {e.msg}. {keep}")
            return
        except (OSError, UnicodeDecodeError) as e:
            self._error(f"Cannot read {self.path}: {e}. {keep}")
            return

        if not isinstance(data, list):
            self._error(f"{fname}: the root must be a JSON array [ ... ] of rules, got {_json_type(data)}. {keep}")
            return

        rules: list[Rule] = []
        invalid = disabled = 0
        seen: dict[tuple, Rule] = {}
        for number, raw in enumerate(data, start=1):
            if isinstance(raw, dict) and raw and raw.keys() == {"comment"}:
                # a note between rules, e.g. {"comment": "=== Trading errors ==="}
                continue
            enabled = raw.get("enabled", True) if isinstance(raw, dict) else True
            if not isinstance(enabled, bool):
                self._error(f"{fname}: rule #{number}: {_bad('enabled', 'true or false', enabled)}; rule skipped")
                invalid += 1
                continue
            if not enabled:
                disabled += 1
                continue
            rule, errors, warnings = parse_rule(number, raw)
            label = rule.label if rule else f"rule #{number}" + (
                f' "{raw["name"]}"' if isinstance(raw, dict) and isinstance(raw.get("name"), str) else "")
            for w in warnings:
                log.warning(f"{fname}: {label}: {w}")
            if rule is None:
                for e in errors:
                    self._error(f"{fname}: {label}: {e}")
                self._error(f"{fname}: {label}: rule skipped")
                invalid += 1
                continue
            key = (rule.method, rule.url, tuple(sorted(rule.query.items())))
            if key in seen:
                log.warning(f"{fname}: {label}: same method/url/query as {seen[key].label}, it will never match (first match wins)")
            else:
                seen[key] = rule
            rules.append(rule)

        self.rules = rules
        summary = f"Loaded {len(rules)} rule(s) from {self.path}"
        if disabled:
            summary += f", {disabled} disabled"
        if invalid:
            summary += f", {invalid} invalid skipped (see errors above)"
            log.warning(summary)
        else:
            log.info(summary)
        if not data:
            log.info(f"{fname} is empty: no requests are mocked. Examples: rules/examples.json")

    def _match(self, rule: Rule, req: http.Request) -> bool:
        if rule.method != "*" and rule.method != req.method:
            return False
        if rule.query:
            # url is matched without the query string, params are checked separately (order doesn't matter)
            if not fnmatch.fnmatchcase(req.pretty_url.split("?", 1)[0], rule.url):
                return False
            return all(k in req.query and fnmatch.fnmatchcase(req.query[k], v) for k, v in rule.query.items())
        return fnmatch.fnmatchcase(req.pretty_url, rule.url)

    async def request(self, flow: http.HTTPFlow):
        self._reload()
        req = flow.request
        for rule in self.rules:
            if not self._match(rule, req):
                continue
            if rule.mock is not None:
                try:
                    await self._apply(rule, flow)
                except Exception:
                    # let the request through instead of failing it with an addon error
                    log.exception(f"{rule.label}: failed to mock {req.method} {req.pretty_url}, passing the request through")
                return
            if rule.response:
                self.pending[flow.id] = rule
            if rule.request:
                where = f"{req.method} {req.pretty_url}  [{rule.label}]"
                try:
                    await self._modify(rule, rule.request, req, f"MODIFY REQ {where}")
                except Exception:
                    log.exception(f"{rule.label}: failed to modify the request {where}, sending it with the changes made so far")
            return

    async def response(self, flow: http.HTTPFlow):
        rule = self.pending.pop(flow.id, None)
        if rule is None or flow.response is None:
            return
        resp = flow.response
        was = resp.status_code
        where = f"{flow.request.method} {flow.request.pretty_url}  [{rule.label}]"
        status = f"{was} -> {rule.response.status}" if rule.response.status not in (None, was) else str(was)
        try:
            await self._modify(rule, rule.response, resp, f"MODIFY RESP {status} {where}")
        except Exception:
            log.exception(f"{rule.label}: failed to modify the response {where}, returning it with the changes made so far")

    def error(self, flow: http.HTTPFlow):
        # the server never answered: nothing to modify
        self.pending.pop(flow.id, None)

    async def _modify(self, rule: Rule, ops: Ops, msg: http.Message, title: str):
        part = "request" if isinstance(msg, http.Request) else "response"

        def warn(text: str):
            log.warning(f"{rule.label}: {part}: {text}")

        if ops.delay:
            await asyncio.sleep(ops.delay)
        done = apply_ops(ops, msg, warn)
        log.info(f"{title}: {', '.join(done) if done else 'nothing changed'}")

    async def _apply(self, rule: Rule, flow: http.HTTPFlow):
        req = flow.request
        mock = rule.mock
        where = f"{req.method} {req.pretty_url}  [{rule.label}]"

        if mock.status == "kill":
            log.info(f"KILL {where}")
            flow.kill()
            return

        if mock.status == "timeout":
            log.info(f"TIMEOUT {mock.delay:g}s {where}")
            await asyncio.sleep(mock.delay)
            flow.kill()
            return

        status = mock.status
        body = mock.body
        headers = dict(mock.headers)
        if body is None:
            body = {
                "error": "mocked_by_mitmproxy",
                "status": status,
                "method": req.method,
                "url": req.pretty_url,
            }
        if isinstance(body, (dict, list)):
            content = json.dumps(body).encode()
        else:
            # a string is sent as is, without JSON encoding
            content = str(body).encode()
        # Content-Type defaults to application/json, even for raw strings
        headers.setdefault("Content-Type", mock.content_type)

        # CORS: the real server would add these headers itself, but the mocked
        # response lacks them, so the browser hides the body (fetch fails with
        # TypeError, DevTools shows "Failed to load response data").
        origin = req.headers.get("Origin")
        if origin and mock.cors:
            headers.setdefault("Access-Control-Allow-Origin", origin)
            headers.setdefault("Access-Control-Allow-Credentials", "true")
            headers.setdefault("Vary", "Origin")
            custom = [k for k in headers if not k.lower().startswith("access-control-")
                      and k.lower() not in ("content-type", "vary")]
            if custom:
                headers.setdefault("Access-Control-Expose-Headers", ", ".join(custom))

        if mock.delay:
            await asyncio.sleep(mock.delay)

        flow.response = http.Response.make(status, content, headers)
        log.info(f"MOCK {status} {where}")


addons = [MockErrors()]
