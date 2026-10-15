"""
Gremlin's mitmproxy addon: replaces responses with errors by method + URL, rules live in a JSON file.

Run:
  start_proxy.bat
  (or manually: mitmdump -s addons/mock_errors.py --set rules_file=rules/rules.json)

The rules file is reloaded automatically when it changes (no need to restart mitmproxy).
Format: see README.md and the schema below, examples: rules/examples.json.

Validation on load:
  - invalid JSON or a non-array root: the whole file is rejected, previous rules stay active;
  - an invalid rule: only that rule is skipped, the others are loaded;
  - unknown fields and fields that have no effect: warning, the rule is still loaded.
"""
import asyncio
import difflib
import fnmatch
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any

from mitmproxy import ctx, http  # type: ignore

log = logging.getLogger(__name__)

# Rule schema. Keep in sync with the "Rules" section of README.md.
REQUIRED_FIELDS = {
    "url": 'URL pattern with scheme, e.g. "https://host:8443/api/*"',
    "error": 'HTTP status 100-599, "timeout" or "kill"',
}
OPTIONAL_FIELDS = {
    "method": 'HTTP method or "*" (default "*")',
    "query": "object of query params that must be present (default: not checked)",
    "body": "object/array is sent as JSON, string as is (default: generated JSON)",
    "content_type": 'Content-Type of the response (default "application/json")',
    "headers": "object of extra response headers (default: none)",
    "delay": 'seconds to wait before responding, >= 0 (default 0, 30 for "timeout")',
    "cors": "add CORS headers for the request's Origin (default true)",
    "enabled": "false skips the rule without validating it (default true)",
    "name": "label shown in logs",
    "comment": "free text, ignored",
}
ALL_FIELDS = {**REQUIRED_FIELDS, **OPTIONAL_FIELDS}
SPECIAL_ERRORS = ("timeout", "kill")
# Fields that only make sense for a mocked HTTP response
RESPONSE_FIELDS = ("body", "content_type", "headers", "cors")
KNOWN_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}


@dataclass
class Rule:
    number: int  # 1-based position in the file, as shown in logs
    url: str
    error: int | str
    name: str | None = None
    method: str = "*"
    query: dict[str, str] = field(default_factory=dict)
    body: Any = None
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0
    cors: bool = True

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


def _bad(key: str, expected: str, value: Any) -> str:
    return f"field '{key}' ({_kind(key)}): expected {expected}, got {_json_type(value)} {json.dumps(value)}"


def _scalar_to_str(value: Any) -> str | None:
    """JSON scalar -> string as it appears in a URL/header; None for objects/arrays/null."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    return None


def parse_rule(number: int, raw: Any) -> tuple[Rule | None, list[str], list[str]]:
    """Validates one rule. Returns (rule or None if invalid, errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(raw, dict):
        return None, [f"must be a JSON object, got {_json_type(raw)}"], []

    for key in raw:
        if key not in ALL_FIELDS:
            hint = difflib.get_close_matches(key, ALL_FIELDS, n=1)
            warnings.append(f"unknown field '{key}' is ignored" + (f", did you mean '{hint[0]}'?" if hint else ""))
    for key, description in REQUIRED_FIELDS.items():
        if key not in raw:
            errors.append(f"field '{key}' (required) is missing: {description}")

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

    error = raw.get("error")
    if "error" in raw:
        if isinstance(error, int) and not isinstance(error, bool):
            if not 100 <= error <= 599:
                errors.append(f"field 'error' (required): HTTP status must be 100-599, got {error}")
        elif isinstance(error, str) and error.strip().isdigit():
            errors.append(f"field 'error' (required): write the status as a number without quotes: {error.strip()}")
        elif error not in SPECIAL_ERRORS:
            errors.append(_bad("error", 'an HTTP status 100-599, "timeout" or "kill"', error))

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

    content_type = raw.get("content_type", "application/json")
    if not isinstance(content_type, str) or not content_type.strip():
        errors.append(_bad("content_type", 'a string like "application/json"', content_type))

    headers: dict[str, str] = {}
    raw_headers = raw.get("headers")
    if raw_headers is not None:
        if not isinstance(raw_headers, dict):
            errors.append(_bad("headers", 'an object like {"Retry-After": "10"}', raw_headers))
        else:
            for k, v in raw_headers.items():
                s = _scalar_to_str(v)
                if not k.strip() or s is None:
                    errors.append(f"field 'headers' (optional): header '{k}' must have a non-empty name and a string or number value")
                else:
                    headers[k] = s

    default_delay = 30.0 if error == "timeout" else 0.0
    delay = raw.get("delay", default_delay)
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or delay < 0:
        errors.append(_bad("delay", "a number of seconds >= 0", delay))
        delay = default_delay

    cors = raw.get("cors", True)
    if not isinstance(cors, bool):
        errors.append(_bad("cors", "true or false", cors))

    if error in SPECIAL_ERRORS:
        ignored = [k for k in RESPONSE_FIELDS if k in raw]
        if error == "kill" and "delay" in raw:
            ignored.append("delay")
        if ignored:
            warnings.append(f"with \"error\": \"{error}\" no response is sent, so {', '.join(ignored)} has no effect")

    if errors:
        return None, errors, warnings
    return Rule(
        number=number,
        url=url,
        error=error,
        name=name,
        method=method,
        query=query,
        body=raw.get("body"),
        content_type=content_type,
        headers=headers,
        delay=float(delay),
        cors=cors,
    ), errors, warnings


class MockErrors:
    def __init__(self):
        self.rules: list[Rule] = []
        self.path: str | None = None
        self.mtime: float | None = None
        self.missing_reported = False
        self.started = False

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
            try:
                await self._apply(rule, flow)
            except Exception:
                # let the request through instead of failing it with an addon error
                log.exception(f"{rule.label}: failed to mock {req.method} {req.pretty_url}, passing the request through")
            return

    async def _apply(self, rule: Rule, flow: http.HTTPFlow):
        req = flow.request
        where = f"{req.method} {req.pretty_url}  [{rule.label}]"

        if rule.error == "kill":
            log.info(f"KILL {where}")
            flow.kill()
            return

        if rule.error == "timeout":
            log.info(f"TIMEOUT {rule.delay:g}s {where}")
            await asyncio.sleep(rule.delay)
            flow.kill()
            return

        status = rule.error
        body = rule.body
        headers = dict(rule.headers)
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
        headers.setdefault("Content-Type", rule.content_type)

        # CORS: the real server would add these headers itself, but the mocked
        # response lacks them, so the browser hides the body (fetch fails with
        # TypeError, DevTools shows "Failed to load response data").
        origin = req.headers.get("Origin")
        if origin and rule.cors:
            headers.setdefault("Access-Control-Allow-Origin", origin)
            headers.setdefault("Access-Control-Allow-Credentials", "true")
            headers.setdefault("Vary", "Origin")
            custom = [k for k in headers if not k.lower().startswith("access-control-")
                      and k.lower() not in ("content-type", "vary")]
            if custom:
                headers.setdefault("Access-Control-Expose-Headers", ", ".join(custom))

        if rule.delay:
            await asyncio.sleep(rule.delay)

        flow.response = http.Response.make(status, content, headers)
        log.info(f"MOCK {status} {where}")


addons = [MockErrors()]
