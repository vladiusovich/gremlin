# Rules

A rules file tells Gremlin which requests to intercept and what to do with them. This page describes every option with examples. For setup and running see the [main README](../README.md); a file with a working example of every feature is [`examples.json`](examples.json).

- [Two kinds of rules](#two-kinds-of-rules): **read this first**
- [Picking requests](#picking-requests): `url`, `method`, `query`
- [Mocking the response](#mocking-the-response-mock): `mock`
- [Changing the request](#changing-the-request-request): `request`
- [Changing the response](#changing-the-response-response): `response`
- [Request and response together](#request-and-response-together)
- [Recipes](#recipes): ready rules for typical test cases
- [Reference](#reference): all fields, order of changes, log lines, validation messages
- [The old format (`error`)](#the-old-format-error)
- [Limitations](#limitations)
- [Organizing rule files](#organizing-rule-files)

## Two kinds of rules

A rules file is a JSON array of rules: `[ { … }, { … } ]`. Each rule says **which requests** (`url`, `method`, `query`) and **what to do** with them. There are two kinds of "what to do", and the difference is **whether the request reaches the server**:

| Kind | Fields | Does the request reach the server? | What the app gets |
| --- | --- | --- | --- |
| **Fake answer** | `mock` | ❌ **No.** The proxy answers by itself | The fake response from `mock` |
| **Real call, changed** | `request` and/or `response` | ✅ **Yes** | The server's real answer, changed by `response` if set |

```text
 mock:                 app ──► proxy ─┐                                       (server is not called)
                                      └──► fake response ──► app

 request / response:   app ──► proxy ──► [request: change] ──► server
                       app ◄── proxy ◄── [response: change] ◄── server's real answer
```

> ⚠️ **`mock` cannot be combined with `request` or `response` in one rule.**
> With `mock` the request is never sent, so there is no request to change and no real answer to change.
> Such a rule is **invalid and skipped**, and the proxy window says why:
>
> ```text
> rules.json: rule #3: incompatible: 'mock' cannot be used together with 'response' in one rule.
> 'mock' answers instead of the server, so the request is never sent, while 'response' changes the
> answer that comes back from the server. Keep either 'mock' or 'response'
> rules.json: rule #3: rule skipped
> ```

`request` and `response` **can** be used together: they are the two ends of one real call to the server (change what is sent, change what comes back).

Why the difference matters, with `POST /orders` as an example:

| Rule | Order created on the server? | What the app shows |
| --- | --- | --- |
| `"mock": {"status": 500}` | **No** | An error |
| `"response": {"status": 500}` | **Yes** | An error, although the order exists: "the server failed after saving" |

Both are useful test cases, but they are different cases. For a request that has side effects (creates, pays, sends), choose consciously.

Which kind to use:

| I want to… | Use |
| --- | --- |
| Show a backend error, a timeout, a dropped connection | `mock` |
| Test an endpoint that does not exist yet or a server that is down | `mock` |
| Avoid side effects on the server (no real order, payment, e-mail) | `mock` |
| Send values the UI does not allow (negative amount, missing field, broken token) | `request` |
| Show real data with one field changed (zero balance, feature flag off) | `response` |
| Real data with an error status, a slow real server | `response` |

For every request the rules are checked **top to bottom**, and the **first matching rule wins**: one request is handled by one rule. Requests that match no rule pass through untouched.

The file is reloaded on save, no restart needed. A mistake in a rule is reported in the proxy window with the rule number and field; the rest of the rules keep working.

## Picking requests

| Field | Default | Description |
| --- | --- | --- |
| `url` | required | URL pattern: scheme, host, **port**, path. `*` matches any characters, `?` any single character. Without `query` it is matched against the full URL, including the query string |
| `method` | `"*"` | `GET`, `POST`, `PUT`, `DELETE`, … (case-insensitive) or `*` for any |
| `query` | not checked | Query parameters that must be present, e.g. `{"Type": "Cancel"}`. Values support `*`. With `query` set, `url` is matched **without** the query string and parameter order does not matter |

Copy the exact URL from DevTools → *Network* (right click → *Copy → Copy URL*) or from the proxy log, then replace the variable parts with `*`.

| Pattern | Matches | Does not match |
| --- | --- | --- |
| `https://api.example.com/v1/orders` | `…/v1/orders` | `…/v1/orders?id=1`, `…/v1/orders/1` |
| `https://api.example.com/v1/orders*` | `…/v1/orders`, `…/v1/orders?id=1`, `…/v1/orders/1` | `…/v2/orders` |
| `https://api.example.com/v1/orders/*` | `…/v1/orders/1`, `…/v1/orders/1/cancel` | `…/v1/orders` |
| `*/v1/orders` | `/v1/orders` on any host | |
| `https://host:8443/api/*` | `https://host:8443/api/x` | `https://host/api/x` (no port) |

Match by query parameters, in any order and with other parameters around:

```json
{
  "name": "Only the cancel request",
  "method": "DELETE",
  "url": "https://api.example.com/v1/trade",
  "query": { "Type": "Cancel", "ClientApp": "*" },
  "mock": { "status": 400 }
}
```

> `query` at the top level of a rule **picks** requests. `request.query` (see below) **changes** the query of the request. They are independent and can be used together.

## Mocking the response (`mock`)

> ❌ The request **never reaches the server**. Cannot be combined with `request` / `response`.

The proxy answers by itself with the response described in `mock`:

| Field | Default | Description |
| --- | --- | --- |
| `status` | **required** | HTTP status `100`-`599` as a number (`500`, not `"500"`), `"timeout"` or `"kill"` |
| `body` | generated JSON | Object or array: sent as JSON. String: sent as is (wrap it in `\"…\"` if the client expects a JSON string). Omitted or `null`: a JSON body describing the mock |
| `content_type` | `"application/json"` | `Content-Type` of the response |
| `headers` | none | Response headers, e.g. `{"Retry-After": "10"}` |
| `delay` | `0` (`30` for `"timeout"`) | Seconds (fractions allowed) to wait before responding |
| `cors` | `true` | Add `Access-Control-Allow-*` headers for the request's `Origin`, so the browser lets the app read the fake response. `false` reproduces a CORS failure |

The names `status`, `body`, `headers` and `delay` are the same as in `response`, but the meaning differs: in `mock` they describe a fake answer, in `response` they change the real one.

### A backend error with a JSON body

```json
{
  "name": "User not found",
  "method": "GET",
  "url": "https://api.example.com/v1/users/*",
  "mock": {
    "status": 404,
    "body": { "code": "NOT_FOUND", "message": "User not found" }
  }
}
```

### Plain text or HTML

```json
{
  "method": "POST",
  "url": "https://api.example.com/v1/orders",
  "mock": {
    "status": 502,
    "content_type": "text/html",
    "body": "<html><body><h1>502 Bad Gateway</h1></body></html>"
  }
}
```

### A JSON string

The backend returns `"Trade session is restricted"` with the quotes. The quotes are part of the body, so they are escaped:

```json
{
  "url": "https://api.example.com/v1/trade",
  "mock": { "status": 400, "body": "\"Trade session is restricted\"" }
}
```

### Without a body

`status` alone returns a JSON body describing the mock: `{"error": "mocked_by_mitmproxy", "status": 503, "method": "GET", "url": "…"}`. For a really empty body use `"body": ""`.

```json
{ "url": "https://api.example.com/v1/health", "mock": { "status": 503 } }
```

### Headers and a slow answer

```json
{
  "name": "Rate limit",
  "method": "GET",
  "url": "https://api.example.com/v1/quotes*",
  "mock": {
    "status": 429,
    "delay": 2,
    "headers": { "Retry-After": "10" },
    "body": { "message": "Too many requests" }
  }
}
```

Custom headers are added to `Access-Control-Expose-Headers` automatically, so `fetch` can read them in the browser.

### Timeout and network failure

`"timeout"` hangs for `delay` seconds (30 by default) and then drops the connection: the app sees its own timeout or a network error. `"kill"` drops the connection immediately. No response is sent, so `body`, `content_type`, `headers` and `cors` have no effect here (and `delay` neither for `"kill"`).

```json
[
  { "url": "https://api.example.com/v1/slow", "mock": { "status": "timeout", "delay": 15 } },
  { "url": "https://api.example.com/v1/unstable/*", "mock": { "status": "kill" } }
]
```

`"timeout"` and `"kill"` exist only in `mock`: they mean "no answer at all", which cannot be a change of a real answer.

### CORS failure

```json
{ "url": "https://api.example.com/v1/cors-test", "mock": { "status": 401, "cors": false } }
```

## Changing the request (`request`)

> ✅ The request **reaches the server**, changed. Can be combined with `response`, not with `mock`.

Use it for what is hard to do through the UI: values the form does not allow, missing fields, broken tokens, unusual parameters. The server's real answer comes back to the app.

`request` is an object with any of these changes:

| Change | What it does |
| --- | --- |
| `json` | Merges an object into the JSON body: listed fields are set, `null` removes a field, other fields stay |
| `body` | Replaces the whole body: object or array is sent as JSON, string as is |
| `query` | Sets query parameters, `null` removes one |
| `headers` | Sets headers, `null` removes one |
| `form` | Sets fields of a form body (`application/x-www-form-urlencoded`), `null` removes one |
| `replace` | Finds and replaces text in the body, in any format |
| `method` | Changes the HTTP method |
| `url` | Sends the request to another URL |
| `delay` | Holds the request for N seconds before sending it |

**`null` means "remove"** everywhere: in `json`, `query`, `headers` and `form`. Removing something that is not there is not an error.

### `json`: change fields of a JSON body

The body is merged with the given object ([JSON Merge Patch](https://www.rfc-editor.org/rfc/rfc7396)):

- a field with a value is set (added or replaced);
- a field with `null` is removed;
- nested objects are merged the same way, field by field;
- arrays and other values are replaced as a whole.

```json
{
  "name": "Order with a negative amount and an unknown symbol",
  "method": "POST",
  "url": "https://api.example.com/v1/orders",
  "request": {
    "json": { "amount": -100, "symbol": "XXXYYY", "meta": { "source": null } }
  }
}
```

```jsonc
// the app sends:
{ "amount": 10, "symbol": "EURUSD", "side": "buy", "meta": { "source": "web", "v": 2 } }
// the server gets:
{ "amount": -100, "symbol": "XXXYYY", "side": "buy", "meta": { "v": 2 } }
```

Common cases:

| Test case | `json` |
| --- | --- |
| A required field is missing | `{"symbol": null}` |
| Wrong type | `{"amount": "ten"}` |
| Out of range | `{"amount": 999999999}`, `{"leverage": 0}` |
| Empty value | `{"comment": ""}`, `{"items": []}` |
| An extra field the UI never sends | `{"isAdmin": true}` |
| Another user's data | `{"accountId": 12345}` |

If the body is empty (e.g. a `GET`), `json` creates it, and `Content-Type: application/json` is added if there was none. If the body is not JSON or is a JSON array, `json` is skipped with a warning in the log; use `body` or `replace` then.

To change one element of an array, replace the whole array, or use `replace`:

```json
{
  "url": "https://api.example.com/v1/cart",
  "request": {
    "json": { "items": [ { "id": 1, "qty": -1 } ] }
  }
}
```

### `body`: replace the whole body

```json
{
  "method": "PUT",
  "url": "https://api.example.com/v1/profile",
  "request": {
    "body": { "email": "not-an-email", "phone": "" }
  }
}
```

A string is sent as is: `"body": "garbage{"` for a broken JSON, `"body": ""` for an empty one. `Content-Type` is left as the app sent it; to change it add `"headers": {"Content-Type": "…"}`. `body` and `json` can be combined: `json` is applied to the new body.

### `query`: query parameters

```json
{
  "method": "GET",
  "url": "https://api.example.com/v1/history*",
  "request": {
    "query": { "pageSize": 100000, "from": "2099-01-01", "debug": null }
  }
}
```

`https://…/v1/history?debug=1&pageSize=20` becomes `https://…/v1/history?pageSize=100000&from=2099-01-01`. Other parameters stay.

### `headers`: request headers

```json
{
  "url": "https://api.example.com/v1/me*",
  "request": {
    "headers": { "Authorization": null, "X-Client-Version": "0.0.1", "Accept-Language": "xx" }
  }
}
```

Header names are case-insensitive. A set header replaces all existing values of that header. Useful cases: remove or break `Authorization` (`"Bearer expired"`), an old app version (`X-Client-Version`), an unknown language, another `User-Agent`, a missing `X-CSRF-Token`.

### `form`: form fields

For bodies of type `application/x-www-form-urlencoded` (classic HTML forms, OAuth token requests):

```json
{
  "method": "POST",
  "url": "https://auth.example.com/login",
  "request": {
    "form": { "username": "' OR 1=1 --", "remember": null }
  }
}
```

If the body is of another type (JSON, multipart), `form` is skipped with a warning. With an empty body the form is created.

### `replace`: find and replace in the body

Works on the body as text, in any format: JSON, XML, GraphQL, plain text. One replacement is an object, several are an array; they are applied in order.

| Key | Default | Description |
| --- | --- | --- |
| `from` | required | Text to find. Every occurrence is replaced |
| `to` | required | Replacement text, `""` deletes the match |
| `regex` | `false` | `true`: `from` is a [regular expression](https://docs.python.org/3/library/re.html#regular-expression-syntax), and `to` may use groups `\1`, `\g<name>` |

Plain text, no special characters to escape:

```json
{
  "method": "POST",
  "url": "https://api.example.com/graphql",
  "request": {
    "replace": { "from": "first: 20", "to": "first: 0" }
  }
}
```

A regular expression with a group: every `"qty": 5` becomes `"qty": -5`, at any nesting level. In JSON a backslash is written twice (`\\d`, `\\1`):

```json
{
  "method": "POST",
  "url": "https://api.example.com/v1/cart",
  "request": {
    "replace": [
      { "from": "\"qty\":\\s*(\\d+)", "to": "\"qty\": -\\1", "regex": true },
      { "from": "USD", "to": "XXX" }
    ]
  }
}
```

A `from` that is not found is reported in the log as a warning.

### `method` and `url`

```json
[
  {
    "method": "POST",
    "url": "https://api.example.com/v1/orders/*/cancel",
    "request": { "method": "DELETE" }
  },
  {
    "url": "https://api.example.com/v1/charts/*",
    "request": { "url": "http://localhost:5000/v2/charts" }
  }
]
```

`url` is the full new address: scheme, host, port, path and query. Use it to send a single endpoint to another stand, another API version or a backend running locally. The `Host` header follows the new address. `query` is applied after `url`.

### `delay`: hold the request

```json
{
  "method": "POST",
  "url": "https://api.example.com/v1/payments",
  "request": { "delay": 5 }
}
```

The request is held for 5 seconds and then sent. Good for double-click and double-submit tests: the UI has time to send the second request while the first is still on its way.

## Changing the response (`response`)

> ✅ The request **reaches the server**; its real answer is changed. Can be combined with `request`, not with `mock`.

The request goes to the server unchanged (unless `request` is set too), and the real answer is changed before it reaches the app. Use it when the real data is needed and only a part should differ.

| Change | What it does |
| --- | --- |
| `status` | Sets the HTTP status (`100`-`599`), the body stays real |
| `json` | Merges an object into the JSON body (same as `request.json`) |
| `body` | Replaces the whole body |
| `replace` | Finds and replaces text in the body |
| `headers` | Sets headers, `null` removes one |
| `delay` | Holds the response for N seconds before returning it |

### `json`: change fields of the real JSON

```json
{
  "name": "Zero balance, trading disabled",
  "method": "GET",
  "url": "https://api.example.com/v1/account",
  "response": {
    "json": { "balance": 0, "flags": { "tradingAllowed": false, "beta": null } }
  }
}
```

```jsonc
// the server answers:
{ "id": 7, "balance": 1520.4, "currency": "USD", "flags": { "tradingAllowed": true, "beta": true } }
// the app gets:
{ "id": 7, "balance": 0, "currency": "USD", "flags": { "tradingAllowed": false } }
```

### `status`: real body, another status

```json
{
  "method": "GET",
  "url": "https://api.example.com/v1/positions",
  "response": { "status": 500 }
}
```

Remember: the server has really processed the request. For `POST`, `PUT`, `DELETE` this is "the server did it, but the app thinks it failed". If the server must not process the request, use `mock`.

### `body`: an empty list, a broken answer

```json
[
  { "method": "GET", "url": "https://api.example.com/v1/news", "response": { "body": [] } },
  { "method": "GET", "url": "https://api.example.com/v1/settings", "response": { "body": "{\"broken\": " } }
]
```

The real headers (including `Content-Type` and CORS) are kept.

### `replace`: the same field in many places

```json
{
  "method": "GET",
  "url": "https://api.example.com/v1/instruments",
  "response": {
    "replace": [
      { "from": "\"status\":\"Open\"", "to": "\"status\":\"Closed\"" },
      { "from": "\"price\":\\s*[0-9.]+", "to": "\"price\": 0", "regex": true }
    ]
  }
}
```

Every instrument in the list becomes closed and gets a zero price. `json` cannot do this, because it would replace the whole array.

### `headers`

```json
{
  "method": "GET",
  "url": "https://cdn.example.com/config.json",
  "response": {
    "headers": { "Cache-Control": "no-store", "ETag": null, "Retry-After": "30" }
  }
}
```

### `delay`: a slow server

```json
{
  "method": "GET",
  "url": "https://api.example.com/v1/reports/*",
  "response": { "delay": 8 }
}
```

The server answers at its normal speed, the app gets the answer 8 seconds later: loaders, skeletons, cancel buttons, request races. Unlike `mock` with `delay`, the data is real.

## Request and response together

`request` and `response` can be used in one rule, each is optional. It is still **one real call** to the server: the request is changed on the way there, the answer on the way back.

```json
{
  "name": "Expired session",
  "method": "*",
  "url": "https://api.example.com/v1/trade*",
  "request": {
    "headers": { "Authorization": "Bearer expired" }
  },
  "response": {
    "status": 401,
    "json": { "code": "SESSION_EXPIRED" }
  }
}
```

```json
{
  "name": "Order with a huge amount, slow answer",
  "method": "POST",
  "url": "https://api.example.com/v1/orders",
  "query": { "type": "market" },
  "request": { "json": { "amount": 999999999 }, "delay": 1 },
  "response": { "delay": 3 }
}
```

What does **not** work, and what to write instead:

| Written | Problem | Write instead |
| --- | --- | --- |
| `"mock": {…}, "request": {…}` | With `mock` the request is never sent, so changing it does nothing | Only `request` (the server gets the changed request), or only `mock` (the server gets nothing) |
| `"mock": {…}, "response": {…}` | With `mock` there is no real answer to change | Put everything into `mock` (`status`, `body`, `headers`, `delay`), or drop `mock` to change the real answer |
| `"response": {"status": "timeout"}` | `"timeout"` / `"kill"` mean "no answer", which only `mock` can do | `"mock": {"status": "timeout"}` |
| `"response": {…}, "body": {…}` | `body` at the top level of a rule does nothing | `"response": {"body": {…}}` or `"mock": {"status": …, "body": {…}}` |

## Recipes

| Test case | Rule |
| --- | --- |
| Backend error | `"mock": {"status": 500, "body": {…}}` |
| Timeout, network failure | `"mock": {"status": "timeout"}`, `"mock": {"status": "kill"}` |
| Endpoint not implemented yet | `"mock": {"status": 200, "body": {…}}` |
| Server validation of a field the UI checks itself | `"request": {"json": {"amount": -1}}` |
| A required field is missing | `"request": {"json": {"symbol": null}}` |
| The token expired in the middle of a session | `"request": {"headers": {"Authorization": "Bearer expired"}}` |
| Request without authorization | `"request": {"headers": {"Authorization": null, "Cookie": null}}` |
| Old app version, forced update | `"request": {"headers": {"X-Client-Version": "0.0.1"}}` |
| Huge page size, pagination limits | `"request": {"query": {"pageSize": 100000}}` |
| Double submit | `"request": {"delay": 5}` |
| Empty list state | `"response": {"body": []}` or `"response": {"json": {"items": []}}` |
| Feature flag off | `"response": {"json": {"features": {"newChart": false}}}` |
| Zero balance, account blocked | `"response": {"json": {"balance": 0, "status": "Blocked"}}` |
| A long text that breaks the layout | `"response": {"json": {"name": "Very long name …"}}` |
| Unknown enum value from the backend | `"response": {"json": {"orderType": "SomethingNew"}}` |
| The server did it, but the app got an error | `"response": {"status": 500}` |
| Slow real server | `"response": {"delay": 8}` |

## Reference

### All fields

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | string | **required** | URL pattern, see [Picking requests](#picking-requests) |
| `method` | string | `"*"` | HTTP method or `*` |
| `query` | object | not checked | Query parameters that must be present |
| `mock` | object | | Fake answer, the server is not called: `status` (required), `body`, `content_type`, `headers`, `delay`, `cors` |
| `request` | object | | Changes to the request: `json`, `body`, `query`, `headers`, `form`, `replace`, `method`, `url`, `delay` |
| `response` | object | | Changes to the real response: `status`, `json`, `body`, `replace`, `headers`, `delay` |
| `enabled` | boolean | `true` | `false` keeps the rule in the file but skips it (without validating it) |
| `name` | string | | Label shown in the proxy log |
| `comment` | any | | Free text, ignored |

A rule needs `url` and **either** `mock` **or** at least one of `request` / `response`.

### What can be combined

| | `mock` | `request` | `response` |
| --- | --- | --- | --- |
| `mock` | | ❌ error, rule skipped | ❌ error, rule skipped |
| `request` | ❌ | | ✅ one real call, both ends changed |
| `response` | ❌ | ✅ | |

### Which change is allowed where

| Change | `mock` | `request` | `response` |
| --- | --- | --- | --- |
| `status` | ✅ required, also `"timeout"` / `"kill"` | | ✅ |
| `body` | ✅ | ✅ | ✅ |
| `headers` | ✅ | ✅ (`null` removes) | ✅ (`null` removes) |
| `delay` | ✅ | ✅ | ✅ |
| `content_type`, `cors` | ✅ | | |
| `json`, `replace` | | ✅ | ✅ |
| `query`, `form`, `method`, `url` | | ✅ | |

A change in the wrong section is ignored with a warning that names the right one: `field 'response.query' is ignored: 'query' only works in 'request'`.

### Order of changes

Changes of one `request` / `response` section are applied in a fixed order, whatever the order in the file:

1. `delay`;
2. `method`, `url`, `query` (request) or `status` (response);
3. `body`;
4. `json`;
5. `form`;
6. `replace`;
7. `headers`.

So `json` is applied on top of a new `body`, `replace` sees the result of `json`, and a `Content-Type` set in `headers` wins over the one added by `json` or `form`.

### Body encoding

Compressed bodies (`gzip`, `br`, `deflate`, `zstd`) are decompressed before the change and compressed back after it. `Content-Length` is updated. `json` writes the body back as compact JSON: the key order is kept, but whitespace changes and non-ASCII characters become `\uXXXX` escapes. This is still the same JSON for any parser. When the exact bytes matter, use `replace`.

### Log lines

```text
MOCK 500 POST https://…/v1/orders  [rule #1 "Order fails"]
TIMEOUT 15s GET https://…/v1/slow  [rule #2]
KILL GET https://…/v1/unstable/1  [rule #3]
MODIFY REQ POST https://…/v1/orders  [rule #4 "Negative amount"]: json, headers
MODIFY RESP 200 -> 401 GET https://…/v1/trade  [rule #5]: status, json
MODIFY RESP 200 GET https://…/v1/account  [rule #6]: json
```

`MOCK` / `TIMEOUT` / `KILL`: the server was not called. `MODIFY`: the server was called; after the colon are the changes that were applied. A change that could not be applied is reported as a warning, and the other changes are still applied:

```text
rule #4: request: 'json' skipped: the body is not JSON (use 'replace' or 'body' instead)
rule #4: request: 'form' skipped: the body is not a form (Content-Type: application/json)
rule #7: response: 'replace': "Open" not found in the body
```

`nothing changed` in a `MODIFY` line means the rule matched, but none of its changes applied: check the warnings above it.

### Validation messages

When the file is saved, every rule is checked. A rule with an **error** is skipped and the others are loaded; a **warning** does not skip the rule.

Errors (the rule is skipped):

```text
rules.json: rule #2: nothing to do: add 'mock' to answer instead of the server, or 'request' / 'response' to change the real request / response
rules.json: rule #3: incompatible: 'mock' cannot be used together with 'request' in one rule. 'mock' answers instead of the server, so the request is never sent, while 'request' changes the request that goes to the server. Keep either 'mock' or 'request'
rules.json: rule #4: field 'mock.status' (required) is missing: HTTP status 100-599, "timeout" (hang, then drop the connection) or "kill" (drop it at once)
rules.json: rule #5: field 'response.status' (optional): "timeout" means no response at all, which only 'mock' can do: "mock": {"status": "timeout"}
rules.json: rule #6: field 'request.json' (optional): expected an object like {"amount": -1} (to replace the whole body use 'request.body'), got array [1]
rules.json: rule #7: field 'request.replace.from' (optional): invalid regular expression: missing ), unterminated subpattern at position 0
```

Warnings (the rule works, but something in it does nothing):

```text
rules.json: rule #8: field 'response.query' is ignored: 'query' only works in 'request'
rules.json: rule #9: unknown field 'request.jsn' is ignored, did you mean 'request.json'?
rules.json: rule #10: 'body' at the top level is ignored: put it inside 'mock' (a fake response) or 'response' (changes to the real response)
rules.json: rule #11: old format: 'error', 'body' at the top level still works, but write it as "mock": {"status": 404, "body": {"code": "NOT_FOUND"}}
```

## The old format (`error`)

Before `mock` existed, a fake answer was written with fields at the top level of a rule. Such rules **still work**, but the proxy window prints a warning with the exact replacement:

```text
rules.json: rule #1: old format: 'error', 'body' at the top level still works, but write it as "mock": {"status": 404, "body": {"code": "NOT_FOUND"}}
```

| Old (top level) | New (inside `mock`) |
| --- | --- |
| `"error": 500` | `"mock": {"status": 500}` |
| `"body"` | `"mock": {"body": …}` |
| `"content_type"` | `"mock": {"content_type": …}` |
| `"headers"` | `"mock": {"headers": …}` |
| `"delay"` | `"mock": {"delay": …}` |
| `"cors"` | `"mock": {"cors": …}` |

```jsonc
// old
{ "url": "https://api.example.com/v1/orders", "error": 500, "body": { "code": "DOWN" }, "delay": 2 }
// new
{ "url": "https://api.example.com/v1/orders", "mock": { "status": 500, "body": { "code": "DOWN" }, "delay": 2 } }
```

The old format follows the same rules as `mock`: `error` together with `request` / `response` is an error. Mixing the two formats in one rule (`mock` plus a top-level `error` or `body`) is an error too.

## Limitations

- **One rule per request**: the first match wins. To change the request and the response of one endpoint, put both into one rule.
- **WebSocket** messages and **streamed** responses (Server-Sent Events) are not changed.
- **`form`** works with `application/x-www-form-urlencoded` only. For `multipart/form-data` (file uploads) use `replace`.
- **Binary bodies** (images, protobuf) cannot be changed with `json` and `replace`; `body` replaces them as text.
- `response` changes only answers that came from the server. If the server is unreachable, the app gets the network error as is; use `mock` to test without the server.
- **HTTP/2 and HTTP/3** have no reason phrase, so with `response.status` only the code changes there.

## Organizing rule files

- Each profile uses `rules/<profile>.json` by default. For scenarios shared between profiles use one file per scenario (`rules/trade-errors.json`, `rules/validation.json`, …), selected by short name with `MITM_RULES` in a profile or `-r`: `-r trade-errors`. Subfolders group scenarios by feature: `-r trade/errors` is `rules/trade/errors.json`.
- To turn a rule off temporarily, set `"enabled": false` instead of deleting it.
- An entry with only `comment` is a note, not a rule. Use it to split a file into groups; it does not shift the numbering of the other rules (rule numbers are positions in the file):

```json
[
  { "comment": "=== Orders ===" },
  { "name": "Order fails", "method": "POST", "url": "https://api.example.com/v1/orders", "mock": { "status": 500 } },
  { "comment": "=== Account ===" },
  { "name": "Zero balance", "url": "https://api.example.com/v1/account", "response": { "json": { "balance": 0 } } }
]
```

- Rule files in `rules/` are personal and ignored by git; only `examples.json` and this page are shared.
