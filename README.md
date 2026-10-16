# Gremlin

*Feed it rules, watch your API break.*

A local tool for testing how the frontend handles API failures, **without touching the backend**: chosen requests get a fake error response (any status and body, a delay, a timeout or a dropped connection), everything else goes to the real server. Built on [mitmproxy](https://mitmproxy.org/), works with `localhost` and with real domains over HTTPS. Details: [How it works](#how-it-works).

- [1. Install](#1-install)
- [2. Create a profile](#2-create-a-profile)
- [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile)
- [4. Run](#4-run)
- [Several profiles and rule sets](#several-profiles-and-rule-sets)
- Reference: [Settings profiles](#settings-profiles) · [Command-line options](#command-line-options) · [Rules](#rules) · [Troubleshooting](#troubleshooting)
- Background: [How it works](#how-it-works) · [Project structure](#project-structure) · [Extending](#extending) · [Tests](#tests) · [Uninstall](#uninstall)

## 1. Install

Requirements: Windows 10/11, Google Chrome or Microsoft Edge.

Double-click `install.bat` in the project folder. It installs mitmproxy and adds its certificate to the trusted ones, so the browser accepts HTTPS through the proxy. When Windows asks whether to install the certificate, answer **Yes**. No admin rights are needed. You only do this once; running it again does no harm.

> ⚠️ The certificate's private key in `%USERPROFILE%\.mitmproxy\` allows decrypting your HTTPS traffic. Do not share it. See [Uninstall](#uninstall) to remove it.

## 2. Create a profile

A **profile** is a small text file in the `env` folder that says:

- which site to open (`MITM_URL`);
- **which rules file to use** (`MITM_RULES`): the rules decide which requests get broken and how;
- optionally the browser and the proxy port.

The file name is the profile name: `env\staging.env` is the profile `staging`.

1. Open the `env` folder.
2. Copy `example.env` (`Ctrl+C`, `Ctrl+V`) and rename the copy to the profile name, e.g. `staging.env`. Use Latin letters, digits, `-` and `_`, no spaces.
3. Open it in Notepad (*right click → Open with → Notepad*) and set the two main lines:

   ```ini
   # Site to open in the browser
   MITM_URL=https://staging.example.com/

   # Rules file for this profile: rules\staging.json
   MITM_RULES=rules/staging.json
   ```

   Everything else in the file can stay as it is. Lines starting with `#` are comments.

4. Save the file.

> The profile named `default` (`env\default.env`) is special: it is used when no profile is specified. Use it for the setup you run most often.

## 3. Create the rules file for the profile

The profile and the rules file are linked **by the exact file name** in `MITM_RULES`: `MITM_RULES=rules/staging.json` means the file `rules\staging.json`. If the name does not match (a typo, a different extension, `.json.txt`), the script stops with `Файл правил не найден: …` and shows the path it looked for.

1. Open the `rules` folder.
2. Create the file named exactly as in `MITM_RULES`, e.g. `staging.json`: *right click → New → Text Document*, then rename it including the extension.
3. Open it in Notepad and describe the requests to break. A file with one rule:

   ```json
   [
     {
       "name": "Order creation fails",
       "method": "POST",
       "url": "https://api.staging.example.com/v1/orders",
       "error": 500
     }
   ]
   ```

   - `name`: any label, it is shown in the proxy log;
   - `method`: the request method, as in DevTools (`GET`, `POST`, …); remove the line to match any method;
   - `url`: the request address, copied from DevTools → *Network* (right click on the request → *Copy → Copy URL*). `*` matches anything, e.g. `https://api.staging.example.com/v1/orders/*`;
   - `error`: the HTTP status to return, or `"timeout"` / `"kill"` to simulate a hang or a network failure.

   Several rules are separated by commas: `[ { … }, { … } ]`. Ready-made rules for every case (custom error text, delays, timeouts, query parameters, …) are in [`rules/examples.json`](rules/examples.json): copy the ones you need. All fields: [Rules](#rules).

4. Save the file.

You can edit and save the rules file while everything is running: changes apply to the next request, no restart needed. If the file has a mistake (a missing comma, a typo in a field name), the proxy window says which rule and which field is wrong, and the previous version of the rules stays active.

> If a profile has no `MITM_RULES` line, it uses `rules\rules.json`, which is created empty automatically.

## 4. Run

Open a console in the project folder: click the Explorer address bar, type `cmd` and press `Enter`. Then run the profile by its name, without `.env`:

```bat
run_browser.bat -e staging
```

For the `default` profile it is just `run_browser.bat` (you can also double-click it).

Two windows open:

- **`mitmproxy :8080`**, the proxy window with the log. Check its first lines: `Loaded 1 rule(s) from …\rules\staging.json` confirms that the right rules file is used. Every broken request appears here as `MOCK 500 POST https://…  [rule #1 "Order creation fails"]`.
- **A separate browser window** with the site from `MITM_URL`. Only this window goes through the proxy; your regular browser works as usual. Test in this window.

Now do the action in the app (e.g. create an order) and check how the UI handles the error.

**To stop**: close the browser window, then press `Ctrl+C` in the proxy window (or just close it).

**To switch to another profile**: stop first (close **both** windows), then run the other profile. If the proxy window of the previous profile is still open on the same port, the new run reuses that proxy, and with it the **previous profile's rules** (the console says `Прокси уже слушает порт …`).

## Several profiles and rule sets

Create as many profiles and rule files as you need: one per stand, per feature or per test scenario. Each profile points to its rules file by name:

```text
env\                              rules\
  default.env   ── MITM_RULES ──▶   rules.json          everyday local testing
  staging.env   ── MITM_RULES ──▶   staging.json        staging stand
  trade.env     ── MITM_RULES ──▶   trade-errors.json   trading error scenarios
  auth.env      ── MITM_RULES ──▶   auth-errors.json    login / session errors
```

```bat
run_browser.bat -e trade
run_browser.bat -e auth
```

- Several profiles may point to the same rules file, e.g. the same scenarios on two stands.
- To run two profiles **at the same time**, give them different ports (`MITM_PORT=8080` and `MITM_PORT=8081`); each gets its own proxy window and browser window.
- Profiles and rule files are personal and are not committed to git; only `env\example.env` and `rules\examples.json` are shared. To share a scenario, send the rules file or add it to `rules\examples.json`.

For a one-off change you do not need to edit the profile: command-line options override it, e.g. `run_browser.bat -e staging -w` additionally opens a web UI with all traffic. See [Command-line options](#command-line-options).

---

## Settings profiles

A profile is an `env/<name>.env` file. `env/default.env` is loaded when no `-e` is given; `-e <name>` loads `env/<name>.env`. Profiles are optional, and **every key in a profile is optional**: an omitted key falls back to its default.

| Key | Required | Default | Allowed values |
| --- | --- | --- | --- |
| `MITM_URL` | optional | `http://localhost:3001/` | Start page, must start with `http://` or `https://` |
| `MITM_BROWSER` | optional | `chrome` | `chrome`, `edge` or a full path to a Chromium-based browser exe |
| `MITM_PORT` | optional | `8080` | Proxy port, `1`-`65535` |
| `MITM_RULES` | optional | `rules/rules.json` | Rules file; a relative path is resolved against the project root. The default file is created if missing, any other file must exist |
| `MITM_WEB` | optional | `0` | `1` = run mitmweb (traffic UI at <http://127.0.0.1:8081>) instead of mitmdump |
| `MITM_INSECURE` | optional | `0` | `1` = ignore certificate errors in the browser (if `install.bat` was not run) |

Booleans accept `1`/`0`, `true`/`false`, `yes`/`no`, `on`/`off`.

- **Priority: command-line options > profile > built-in defaults.**
- Format: `KEY=VALUE`, no spaces around `=`, `#` starts a comment line (trailing comments are not supported).
- Validation: an unknown key (a typo like `MITM_PROT`) is skipped with a `[warn]` listing the allowed keys, so a profile cannot override system variables such as `PATH` either. An invalid value (`MITM_PORT=abc`, `MITM_WEB=maybe`, a URL without scheme, a browser that does not exist) stops the script with an `[!!]` error that names the setting.
- `env/example.env` is the shared template with all keys; your own profiles are ignored by git.

## Command-line options

All arguments are optional. Options override the values from the profile and are validated the same way.

### `run_browser.bat`: proxy + browser

```text
run_browser.bat [URL] [options]
```

| Option | Profile key | Default | Description |
| --- | --- | --- | --- |
| `URL` | `MITM_URL` | `http://localhost:3001/` | Start page |
| `-e`, `--env` | | `env/default.env`, if present | Profile `env/<name>.env` |
| `-b`, `--browser` | `MITM_BROWSER` | `chrome` | `chrome`, `edge` or a full path to a Chromium-based browser exe |
| `-p`, `--port` | `MITM_PORT` | `8080` | Proxy port |
| `-r`, `--rules` | `MITM_RULES` | `rules\rules.json` | Rules file (a relative path is resolved against the current folder) |
| `-w`, `--web` | `MITM_WEB` | off | Start the proxy as **mitmweb**: a web UI with all traffic at <http://127.0.0.1:8081> |
| `-k`, `--insecure` | `MITM_INSECURE` | off | Ignore certificate errors |
| `--no-proxy-start` | | | Do not start the proxy, only the browser |
| `--dry-run` | | | Print the commands without running anything |

Examples:

```bat
:: deployed app on a real domain, without a profile
run_browser.bat https://app.example.com/

:: profile, but Edge on another port with a separate rule set
run_browser.bat -e staging -b edge -p 8081 -r rules\trade-errors.json

:: see all requests and responses in a web UI
run_browser.bat -w
```

### `start_proxy.bat`: proxy only

Runs the proxy in the current console, for clients other than the browser.

```text
start_proxy.bat [-e profile] [-p PORT] [-r rules.json] [-w] [--dry-run]
```

It uses the `MITM_PORT`, `MITM_RULES` and `MITM_WEB` keys of the profile; the options mean the same as in `run_browser.bat`.

```bat
curl -x http://127.0.0.1:8080 https://app.example.com/api/v2/trade
```

For Postman, set the proxy to `127.0.0.1:8080` in *Settings → Proxy*. Any client that uses the Windows certificate store trusts the proxy after `install.bat`. For other clients, point them to `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem`.

### `install.bat`

No options. Steps:

1. Finds mitmproxy, or installs it via `winget` (falls back to `pip install --user mitmproxy`).
2. Generates the mitmproxy root certificate (`%USERPROFILE%\.mitmproxy\`) if it does not exist yet.
3. Adds this certificate to the current user's *Trusted Root Certification Authorities*, unless it is already trusted.

## Rules

A rules file is a JSON array. For each request the rules are checked top to bottom, and the **first match wins**. Only `url` and `error` are required; everything else is optional.

| Field | Required | Type | Default | Description |
| --- | --- | --- | --- | --- |
| `url` | **required** | string | | URL pattern: scheme, host, **port**, path. `*` matches any characters, `?` matches any single character. Without `query` it is matched against the full URL, including the query string |
| `error` | **required** | number or string | | HTTP status `100`-`599` as a number (`500`, not `"500"`), `"timeout"` (hang for `delay` seconds, then drop the connection) or `"kill"` (drop the connection immediately) |
| `method` | optional | string | `"*"` | `GET`, `POST`, `PUT`, `DELETE`, … (case-insensitive) or `*` for any |
| `query` | optional | object | not checked | Query parameters that must be present, e.g. `{"Type": "Cancel"}`. Values are strings or numbers and support `*`. With `query` set, `url` is matched **without** the query string, and parameter order does not matter |
| `body` | optional | any | generated JSON | Object or array: sent as JSON. String: sent as is (wrap it in `\"…\"` if the client expects a JSON string). Omitted or `null`: a JSON body describing the mock |
| `content_type` | optional | string | `"application/json"` | `Content-Type` of the response |
| `headers` | optional | object | none | Extra response headers, e.g. `{"Retry-After": "10"}`; values are strings or numbers |
| `delay` | optional | number | `0` (`30` for `"timeout"`) | Seconds (`>= 0`, fractions allowed) to wait before responding |
| `cors` | optional | boolean | `true` | Add `Access-Control-Allow-*` headers for the request's `Origin` (see [Why CORS headers](#why-cors-headers)). Set to `false` to reproduce a CORS failure |
| `enabled` | optional | boolean | `true` | `false` keeps the rule in the file but skips it (without validating it) |
| `name` | optional | string | | Label shown in the proxy log: `rule #3 "Trade session closed"` |
| `comment` | optional | any | | Free text, ignored |

With `"error": "kill"` or `"timeout"` no response is sent, so `body`, `content_type`, `headers` and `cors` have no effect (and `delay` neither for `kill`).

Rule files in `rules/` are **personal** and ignored by git. The only shared file is [`rules/examples.json`](rules/examples.json), a reference with a working example of every feature.

### Tips

- Write the URL the way the browser actually sends it, including a non-default port (`https://host:8443/...`). The exact URL can be copied from the proxy log or from DevTools.
- `?` in a pattern is a wildcard. To match a query string reliably, use the `query` field instead of putting `?a=b` in `url`.
- Keep scenarios in separate files (`rules/trade-errors.json`, `rules/auth-errors.json`, …) and switch between them with `MITM_RULES` in a profile or `-r`.
- To turn a rule off temporarily, set `"enabled": false` instead of deleting it.

### Validation and log messages

The rules file is validated every time it is (re)loaded, and the result is printed in the proxy window. Rules are numbered from 1 in file order.

| Problem | What happens | Example log line |
| --- | --- | --- |
| Invalid JSON | The whole file is rejected, **the previous rules stay active** | `rules.json:4:17: invalid JSON: Expecting ',' delimiter. Keeping the previous 3 rule(s).` |
| The root is not an array | Same as invalid JSON | `rules.json: the root must be a JSON array [ ... ] of rules, got object. …` |
| A rule is invalid (missing required field, wrong type, out of range) | **Only that rule is skipped**, the others are loaded. All problems of the rule are listed, each naming the field and whether it is required or optional | `rules.json: rule #2 "typo": field 'error' (required) is missing: HTTP status 100-599, "timeout" or "kill"` |
| Unknown field (typo) | Warning with a suggestion, the field is ignored, the rule is loaded | `rules.json: rule #2: unknown field 'metod' is ignored, did you mean 'method'?` |
| A rule that can never match or has fields without effect | Warning, the rule is loaded | `rules.json: rule #7 "dup": same method/url/query as rule #1 "ok", it will never match (first match wins)` |
| The file is missing | Error once, nothing is mocked until the file appears | `Rules file not found: …` |
| A failure while mocking a request | Error with a traceback; the request is passed through to the real server | `rule #3: failed to mock GET https://…, passing the request through` |

Every load ends with a summary such as `Loaded 5 rule(s) from …, 1 disabled, 2 invalid skipped (see errors above)`.

Problems found while the proxy is starting are printed as warnings rather than errors: mitmdump exits if anything is logged as an error during startup, and one bad rule should not take the proxy down.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `NET::ERR_CERT_AUTHORITY_INVALID` | The certificate is not trusted: run `install.bat` and restart the browser, or set `MITM_INSECURE=1` / use `-k` |
| Requests do not appear in the proxy log | The page is open in your regular browser instead of the one started by `run_browser.bat`, or the proxy is on another port |
| Nothing is mocked at all | `rules/rules.json` is empty (`[]`) after the first run: add rules, see [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile). Also check the proxy log for which rules file is loaded |
| Rule does not match | Compare the `url` pattern with the URL in the proxy log: scheme, port and trailing slash matter. Check `method` and `enabled` |
| Mocked response visible in the proxy log, but the app gets `TypeError: Failed to fetch` | CORS: make sure `cors` is not `false` |
| Rules file changes are ignored | The JSON is invalid; the proxy log shows `invalid JSON` with the line and column, and the previous rules stay active. See [Validation and log messages](#validation-and-log-messages) |
| A rule is missing from `Loaded N rule(s)` | It is invalid and was skipped; the reason is logged just above the summary |
| `mitmdump не найден` | Run `install.bat` |
| `Профиль не найден: env\<name>.env` | The `-e` name must match a file in `env/` (without `.env`) |
| `[warn] … неизвестный ключ "…" пропущен` | A typo in a profile key, or spaces around `=`. The message lists the allowed keys |
| `[!!] Неверный порт / Неверное значение / Неверный URL / Браузер … не найден` | An invalid value in the profile or in an option; the message names the setting and the allowed values |
| Proxy window shows `address already in use` | The port is taken; set another `MITM_PORT` or use `-p` |
| mitmweb UI does not open / port conflict | mitmweb uses port `8081` for its UI; do not run the proxy itself on `8081` together with `MITM_WEB=1` / `-w` |

---

## How it works

Typical uses:

- check that the UI shows the right message for a specific backend error (`402 Trade session is closed`, `489 Close-only mode`, …);
- reproduce rare or hard-to-trigger errors on demand;
- test loading states, retries and timeouts (`delay`, `timeout`);
- test behaviour on network failures (`kill`).

```text
 Browser (dedicated profile)
        │  all traffic, including localhost
        ▼
 mitmproxy 127.0.0.1:8080 ── addons/mock_errors.py ── rules/rules.json
        │                          │
        │ no rule matched          │ rule matched
        ▼                          ▼
   real server               mocked error response
```

1. `run_browser.bat` reads the profile, starts `start_proxy.bat` in a separate window if nothing listens on the port yet, and waits for the proxy to come up.
2. `start_proxy.bat` runs mitmdump (or mitmweb) with every addon from `addons/` and the rules file.
3. The browser is started with a **separate profile** in `%TEMP%\mitm-profile-<browser>-<port>` and the flags:
   - `--proxy-server=127.0.0.1:<port>`: all HTTP/HTTPS traffic goes through the proxy;
   - `--proxy-bypass-list="<-loopback>"`: by default Chrome never proxies `localhost`; this removes that exception, so a local dev server is intercepted too;
   - `--disable-quic`: HTTP/3 runs over UDP and could bypass the proxy, so it is turned off.

   The separate profile is required: if the regular browser is already open, a new launch only opens a tab in it and ignores the flags. It also keeps your main profile clean. Cookies and logins in the dedicated profile survive between runs; each browser and port pair has its own profile, so several setups can run side by side.
4. For HTTPS, mitmproxy decrypts the traffic with its own certificate, which is why `install.bat` makes Windows trust it.
5. For every request `mock_errors.py` checks the rules top to bottom; the first match produces a fake response (or a delay/timeout/dropped connection) and the request never reaches the server. Requests without a match pass through unchanged.

### Why CORS headers

When the app and its API are on different origins, the real server adds `Access-Control-Allow-*` headers. A mocked response is built by the proxy and would lack them, so the browser would hide its body: `fetch` fails with `TypeError` and DevTools shows "Failed to load response data". That is why the addon adds these headers for the request's `Origin` by default (`"cors": true`).

## Project structure

```text
gremlin/
├── README.md
├── .gitignore           # keeps personal env profiles and rule sets out of git
├── .gitattributes       # keeps CRLF line endings in *.bat
├── install.bat          # install mitmproxy and trust its certificate
├── start_proxy.bat      # run the proxy with all addons (current console)
├── run_browser.bat      # start the proxy if needed + open a browser through it
├── run_tests.bat        # run the tests in .venv (see Tests)
├── requirements-dev.txt # test dependencies
├── pytest.ini
├── tests/               # pytest suite
├── addons/              # mitmproxy addons, all *.py are loaded automatically
│   └── mock_errors.py   # rule-based error mocking
├── rules/               # rule sets for mock_errors.py
│   ├── examples.json    # reference of all rule features (shared)
│   └── rules.json       # default rules (personal, created empty on first run)
├── env/                 # settings profiles
│   ├── example.env      # template with all keys (shared)
│   └── <name>.env       # your profiles (personal)
└── lib/                 # internal helpers, not meant to be run directly
    ├── find-mitmdump.bat
    ├── load-env.bat     # reads env/<name>.env
    └── validate.bat     # checks port and boolean values
```

Only `README.md`, `.gitignore`, the scripts, `addons/`, `lib/`, `tests/`, `rules/examples.json` and `env/example.env` are in git.

## Extending

- **New error scenario**: add a rule to `rules/rules.json`, or create a new file in `rules/` and point `MITM_RULES` (or `-r`) to it.
- **Sharing a scenario with the team**: add it to `rules/examples.json` (with a `name`, and pointing to `api.example.com` or another placeholder host) or paste it in the task/PR. Personal rule files are not committed.
- **New target app**: create `env/<name>.env` from `env/example.env`.
- **New setting**: add the key to `ENV_KEYS` in `lib/load-env.bat` and to `env/example.env`, read it in the script after the `load-env.bat` call following the `command line > profile > default` pattern used there, and validate it (see `lib/validate.bat`).
- **New rule field**: add it to `REQUIRED_FIELDS` or `OPTIONAL_FIELDS` and validate it in `parse_rule()` in `addons/mock_errors.py`, then document it in [Rules](#rules).
- **New interception logic** (rewriting responses, logging, injecting headers, …): drop a new [mitmproxy addon](https://docs.mitmproxy.org/stable/addons-overview/) into `addons/`. It is picked up on the next proxy start. Prefix shared helper modules with `_` so they are not loaded as addons. If the addon needs its own options, register them in `load()` (like `rules_file` in `mock_errors.py`) and pass values through `--set` in `start_proxy.bat`.
- **Another browser**: set `MITM_BROWSER` (or `-b`) to the full path of its exe (Chromium-based browsers only, because the flags are Chromium flags).

## Tests

Requires Python 3.10+. The first run creates `.venv` in the project folder and installs mitmproxy, pytest and pytest-asyncio into it (the proxy itself keeps using the mitmproxy from `install.bat`).

Run it from a console in the project folder (in PowerShell, e.g. the VS Code terminal, prefix it with `.\`: `.\run_tests.bat`):

```bat
run_tests.bat                          :: everything, ~30 s
run_tests.bat -m "not e2e"             :: without starting a real mitmdump, ~20 s
run_tests.bat -k cors -v               :: only tests with "cors" in the name
run_tests.bat tests\test_mocking.py    :: one file
run_tests.bat -x                       :: stop at the first failure
```

Any arguments are passed to pytest as is. Once `.venv` exists, `.venv\Scripts\python -m pytest` works too.

The run ends with a summary such as `163 passed in 33.10s`. On a failure pytest prints the test name and the values that did not match, and `run_tests.bat` exits with a non-zero code.

| File | What it checks |
| --- | --- |
| `tests/test_parse_rule.py` | Validation of a single rule: required fields, types, ranges, defaults, warnings for typos and fields without effect |
| `tests/test_rules_file.py` | Loading the rules file: invalid JSON / root keeps the previous rules, invalid rules are skipped, `enabled`, duplicates, hot reload, missing file, BOM, warnings instead of errors during startup |
| `tests/test_mocking.py` | Matching (`url` wildcards, `method`, `query`, first match wins) and the mocked response (status, body, `content_type`, `headers`, CORS, `delay`, `timeout`, `kill`, passing through on a failure) |
| `tests/test_e2e.py` | A real mitmdump with the addon between an HTTP client and a local server: passthrough, mock without reaching the server, kill, timeout, delay, hot reload, broken rules do not stop the proxy |
| `tests/test_scripts.py` | `start_proxy.bat` and `run_browser.bat` via `--dry-run` in a temp copy of the project: profiles, priority of options, validation of ports/booleans/URL, unknown keys, addon discovery |

When adding a rule field or a profile key, add a test next to the existing ones for that layer.

## Uninstall

```bat
:: remove the trusted certificate
certutil -user -delstore Root mitmproxy
:: remove mitmproxy
winget uninstall mitmproxy.mitmproxy
:: remove the certificate files and browser profiles
rmdir /s /q "%USERPROFILE%\.mitmproxy"
for /d %d in ("%TEMP%\mitm-profile-*") do rmdir /s /q "%d"
```
