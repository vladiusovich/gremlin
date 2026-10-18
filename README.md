# Gremlin

*Feed it rules, watch your API break.*

A local tool for testing how the frontend handles API failures, **without touching the backend**: chosen requests get a fake error response (any status and body, a delay, a timeout or a dropped connection), everything else goes to the real server. Built on [mitmproxy](https://mitmproxy.org/), works with `localhost` and with real domains over HTTPS, in a browser, in API clients (curl, Postman) and in mobile apps on a phone. Details: [How it works](#how-it-works).

- [1. Install](#1-install)
- [2. Create a profile](#2-create-a-profile)
- [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile)
- [4. Run](#4-run)
- [Several profiles and rule sets](#several-profiles-and-rule-sets)
- [Phones (Android, iOS)](#phones-android-ios): mobile and Capacitor apps through WireGuard
- [Consoles](#consoles): cmd, PowerShell, VS Code, Git Bash
- Reference: [Settings profiles](#settings-profiles) · [Command-line options](#command-line-options) · [Rules](#rules) · [Troubleshooting](#troubleshooting)
- Background: [How it works](#how-it-works) · [Project structure](#project-structure) · [Extending](#extending) · [Tests](#tests) · [Uninstall](#uninstall)

## 1. Install

Requirements: Windows 10/11, Google Chrome or Microsoft Edge. For phones also the WireGuard app on the phone, see [Phones](#phones-android-ios).

Double-click `install.bat` in the project folder (or run `gremlin install` from a console). It installs mitmproxy and adds its certificate to the trusted ones, so the browser accepts HTTPS through the proxy. When Windows asks whether to install the certificate, answer **Yes**. No admin rights are needed. You only do this once; running it again does no harm.

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

The profile and the rules file are linked **by the exact file name** in `MITM_RULES`: `MITM_RULES=rules/staging.json` means the file `rules\staging.json`. If the name does not match (a typo, a different extension, `.json.txt`), the script stops with `Rules file not found: …` and shows the path it looked for.

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
gremlin run -e staging
```

For the `default` profile it is just `gremlin run`.

> In PowerShell (e.g. the VS Code terminal) type `.\gremlin run -e staging`, in Git Bash `./gremlin.bat run -e staging`. Details: [Consoles](#consoles). `gremlin` without arguments lists all commands.

Two windows open:

- **`mitmproxy :8080`**, the proxy window with the log. Check its first lines: `Loaded 1 rule(s) from …\rules\staging.json` confirms that the right rules file is used. Every broken request appears here as `MOCK 500 POST https://…  [rule #1 "Order creation fails"]`.
- **A separate browser window** with the site from `MITM_URL`. Only this window goes through the proxy; your regular browser works as usual. Test in this window.

Now do the action in the app (e.g. create an order) and check how the UI handles the error.

**To stop**: close the browser window, then press `Ctrl+C` in the proxy window (or just close it).

**To switch to another profile**: stop first (close **both** windows), then run the other profile. If the proxy window of the previous profile is still open on the same port, the new run reuses that proxy, and with it the **previous profile's rules** (the console says `Proxy is already listening on port …`).

**To start the proxy and the browser separately** (e.g. to keep the proxy log in your own console, or to restart only the browser): run `gremlin proxy run` in one console and `gremlin browser run` in another, with the same profile or port. See [Command-line options](#command-line-options).

## Consoles

`gremlin` is a batch file (`gremlin.bat`), so it runs in any Windows console, but each one calls it a little differently. Always open the console **in the project folder** (or `cd` there first).

| Console | How to open it in the project folder | Command |
| --- | --- | --- |
| Command Prompt (`cmd`) | Explorer address bar → type `cmd` → `Enter` | `gremlin run -e staging` |
| PowerShell | Explorer address bar → type `powershell` → `Enter` | `.\gremlin run -e staging` |
| Windows Terminal | Right click in the folder → *Open in Terminal* (opens PowerShell by default) | `.\gremlin run -e staging` |
| VS Code terminal | *Terminal → New Terminal* (PowerShell by default; switch with the `+ ˅` menu → *Command Prompt*) | PowerShell: `.\gremlin run -e staging`, cmd: `gremlin run -e staging` |
| Git Bash | Right click in the folder → *Open Git Bash here* | `./gremlin.bat run -e staging` |

- **Why `.\` in PowerShell**: PowerShell never runs programs from the current folder by name alone, so `gremlin` alone gives *"The term 'gremlin' is not recognized"*. `.\gremlin` means "the one in this folder". Git Bash is the same, and also needs the `.bat` extension.
- **Double-click** works only for `install.bat`. `gremlin.bat` needs a command, so a double-click just shows the help and closes the window.
- **Paths**: `-r rules\trade.json` works in cmd and PowerShell; in Git Bash use forward slashes (`-r rules/trade.json`) or quotes, because `\` is an escape character there.
- **Stopping**: `Ctrl+C` stops `gremlin proxy run` in any console. cmd may ask `Terminate batch job (Y/N)?`: answer `Y`.

### URLs with `&`

A URL with `&` (e.g. `https://app.example.com/?a=1&b=2`) needs care, because `&` separates commands in cmd:

| Console | How to pass it |
| --- | --- |
| cmd | In double quotes: `gremlin run "https://app.example.com/?a=1&b=2"` |
| PowerShell | PowerShell drops the quotes before cmd sees them, so add a second pair: `.\gremlin run '"https://app.example.com/?a=1&b=2"'`, or stop PowerShell parsing with `--%`: `.\gremlin --% run "https://app.example.com/?a=1&b=2"` |
| Git Bash | There is no reliable way to pass it on the command line: put the URL in a profile |

The way that works everywhere: put the URL into a profile as `MITM_URL=https://app.example.com/?a=1&b=2` (no quotes) and run `gremlin run -e <profile>`. URLs without `&` (with `?`, `=`, `%20`, …) can be passed in double quotes in any console.

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
gremlin run -e trade
gremlin run -e auth
```

- Several profiles may point to the same rules file, e.g. the same scenarios on two stands.
- To run two profiles **at the same time**, give them different ports (`MITM_PORT=8080` and `MITM_PORT=8081`); each gets its own proxy window and browser window.
- Profiles and rule files are personal and are not committed to git; only `env\example.env` and `rules\examples.json` are shared. To share a scenario, send the rules file or add it to `rules\examples.json`.

For a one-off change you do not need to edit the profile: command-line options override it, e.g. `gremlin run -e staging -w` additionally opens a web UI with all traffic. See [Command-line options](#command-line-options).

## Phones (Android, iOS)

A mobile app on a real phone, e.g. a React + Capacitor app, goes through the same proxy and the same rules. The phone connects to the computer as a **VPN**: mitmproxy runs a WireGuard server, the phone runs the official WireGuard app, and while the tunnel is on all the phone's traffic goes through the proxy. Nothing has to be configured in the phone's Wi-Fi settings, and it works for apps that ignore the system proxy.

```bat
gremlin phone run -e mobile
```

This is `gremlin proxy run` plus WireGuard on UDP port `51820`, started as mitmweb, which shows the QR code for the phone. The regular proxy keeps running on `MITM_PORT` next to it, so `gremlin browser run` with the same profile works at the same time.

### One-time setup

The WireGuard keys are saved in `%USERPROFILE%\.mitmproxy\wireguard.conf` on the first start, so the phone is set up once and keeps working across restarts.

1. **Network.** The phone and the computer must be on the same Wi-Fi (or the computer on a cable in the same network). Guest and some office networks block devices from seeing each other: use another network or the phone's hotspot. In Windows the network must be *Private* (*Settings → Network & internet → Wi-Fi → the network → Private network*).
2. **Firewall.** On the first `gremlin phone run` Windows asks whether `mitmweb.exe` may use the network: tick *Private networks* and click *Allow*. If the dialog was dismissed, allow the port from an admin console:

   ```bat
   netsh advfirewall firewall add rule name="gremlin WireGuard" dir=in action=allow protocol=UDP localport=51820
   ```

3. **Tunnel.** Run `gremlin phone run`. mitmweb opens in the browser: go to the *Capture* tab, the *WireGuard* section shows a QR code. On the phone install **WireGuard** (Google Play / App Store), tap *+* → *Scan from QR code*, name the tunnel `gremlin` and allow the VPN.
4. **Certificate.** Turn the tunnel on and open **<http://mitm.it>** in the phone's browser (the page is served by the proxy, so it opens only through the tunnel).
   - **iOS:** tap the iOS certificate → *Allow*. Then *Settings → Profile Downloaded → Install*. Then **also** *Settings → General → About → Certificate Trust Settings* → turn on *mitmproxy*. Without this last step HTTPS fails.
   - **Android:** download the Android certificate. Then *Settings → Security → Encryption & credentials → Install a certificate → CA certificate* → *Install anyway* → pick the downloaded file. Menu names differ between vendors: search the settings for "CA certificate". Tapping the downloaded file does not install it on Android 11+.
5. **Android only:** the app must be allowed to trust this certificate, see [Capacitor apps](#capacitor-apps). Since Android 7 apps ignore user-installed certificates unless they opt in, so without this step the phone's browser works but the app does not.

### Every day

1. `gremlin phone run -e mobile`;
2. on the phone, turn the `gremlin` tunnel on in WireGuard;
3. test in the app: requests appear in mitmweb, mocked ones also in the console as `MOCK 500 POST https://…`;
4. when done, **turn the tunnel off** first, then stop the proxy (`Ctrl+C`). While the tunnel is on and the proxy is not running, the phone has no internet.

Rules for the phone are written the same way as for the browser: the `url` of the backend request as the app sends it. The exact URL can be copied from the flow list in mitmweb. Rules apply only to the URLs they match; other apps on the phone just go through the proxy unchanged (a few, like banking apps, refuse to work through it: that is expected, turn the tunnel off for them).

### Capacitor apps

**Android: let the debug build trust user certificates.** Create `android/app/src/main/res/xml/network_security_config.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<network-security-config>
  <debug-overrides>
    <trust-anchors>
      <certificates src="system" />
      <certificates src="user" />
    </trust-anchors>
  </debug-overrides>
</network-security-config>
```

and reference it in `android/app/src/main/AndroidManifest.xml`:

```xml
<application
    android:networkSecurityConfig="@xml/network_security_config"
    ...>
```

If the app already has a `network_security_config.xml` (e.g. to allow `http://` for live reload), add the `<debug-overrides>` block to it instead. `debug-overrides` applies only to debuggable builds (`npx cap run android`, *Run* in Android Studio); release builds are not affected. It covers both kinds of requests in a Capacitor app: `fetch`/XHR from the WebView and native requests through `CapacitorHttp`. If testers use a non-debuggable QA build, that build needs the same `<certificates src="user" />` in a `<base-config>` of its own, e.g. in a build-type or flavor source set (`android/app/src/qa/res/xml/…`), never in the release one.

**iOS:** nothing to change in the app. After step 4 of the setup the WebView (WKWebView) and `CapacitorHttp` trust the certificate.

**Certificate pinning.** If the app pins the server certificate (an SSL pinning plugin or native config), the proxy cannot decrypt its requests: turn pinning off in debug and test builds.

**CORS.** Requests from the Capacitor WebView come with the origin `https://localhost` (Android) or `capacitor://localhost` (iOS). Mocked responses get CORS headers for that origin automatically (`"cors": true` by default), the same as in the browser.

**Live reload.** With `server.url` pointing to the dev server on the computer (`npx cap run android -l --external`), the app loads through the tunnel too; nothing extra is needed.

**Seeing how the UI reacts.** Inspect the WebView like a web page: `chrome://inspect` in desktop Chrome for Android (USB debugging on), Safari → *Develop* menu for iOS (*Web Inspector* on in the phone's Safari settings, a Mac is needed).

### Emulators

- **Android emulator:** works the same way: install WireGuard in the emulator and add the tunnel from the QR code (or *Import from file* with the config that is also printed in the console). The computer is reachable from the emulator as `10.0.2.2`: if the tunnel does not connect, edit the tunnel's *Endpoint* to `10.0.2.2:51820`. A simpler alternative without WireGuard: start the emulator with `emulator -avd <name> -http-proxy 127.0.0.1:8080` next to `gremlin proxy run`. The certificate and the `network_security_config` are needed in both cases.
- **iOS simulator:** runs only on macOS, and gremlin's scripts are Windows-only. The simulator has no VPN and uses the Mac's network settings, so on a Mac run `mitmweb -s addons/mock_errors.py --set rules_file=rules/rules.json`, set the Mac's HTTP/HTTPS proxy to `127.0.0.1:8080`, and drag `~/.mitmproxy/mitmproxy-ca-cert.pem` onto the simulator, then trust it as in step 4.

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
| `MITM_INSECURE` | optional | `0` | `1` = ignore certificate errors in the browser (if `gremlin install` was not run) |
| `MITM_WIREGUARD` | optional | `0` | `1` = also run a WireGuard server for phones, see [Phones](#phones-android-ios). `gremlin phone run` turns it on regardless |
| `MITM_WG_PORT` | optional | `51820` | WireGuard UDP port, `1`-`65535`; used only with WireGuard on |

Booleans accept `1`/`0`, `true`/`false`, `yes`/`no`, `on`/`off`.

- **Priority: command-line options > profile > built-in defaults.**
- Format: `KEY=VALUE`, no spaces around `=`, `#` starts a comment line (trailing comments are not supported).
- Validation: an unknown key (a typo like `MITM_PROT`) is skipped with a `[warn]` listing the allowed keys, so a profile cannot override system variables such as `PATH` either. An invalid value (`MITM_PORT=abc`, `MITM_WEB=maybe`, a URL without scheme, a browser that does not exist) stops the script with an `[!!]` error that names the setting.
- `env/example.env` is the shared template with all keys; your own profiles are ignored by git.

## Command-line options

All arguments are optional. Options override the values from the profile and are validated the same way.

### `gremlin run`: proxy + browser

```text
gremlin run [URL] [options]
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
| `--dry-run` | | | Print the commands without running anything |

Examples:

```bat
:: deployed app on a real domain, without a profile
gremlin run https://app.example.com/

:: profile, but Edge on another port with a separate rule set
gremlin run -e staging -b edge -p 8081 -r rules\trade-errors.json

:: see all requests and responses in a web UI
gremlin run -w
```

### `gremlin browser run`: browser only

Opens only the browser, pointed at a proxy that is already running, e.g. one started with `gremlin proxy run` in another console. If nothing listens on the port, it warns and opens the browser anyway: pages will not load until the proxy is up.

```text
gremlin browser run [URL] [-e profile] [-b chrome|edge|path] [-p PORT] [-k] [--dry-run]
```

The options are the same as in `gremlin run`, except `-r` and `-w`: they configure the proxy, so they are refused here.

### `gremlin proxy run`: proxy only

Runs the proxy in the current console: for `gremlin browser run` in another console, or for clients other than the browser (curl, Postman, …). Stop it with `Ctrl+C`.

```text
gremlin proxy run [-e profile] [-p PORT] [-r rules.json] [-w] [-g] [--wg-port PORT] [--dry-run]
```

It uses the `MITM_PORT`, `MITM_RULES`, `MITM_WEB`, `MITM_WIREGUARD` and `MITM_WG_PORT` keys of the profile; `-e`, `-p`, `-r` and `-w` mean the same as in `gremlin run`.

| Option | Profile key | Default | Description |
| --- | --- | --- | --- |
| `-g`, `--wireguard` | `MITM_WIREGUARD` | off | Also run a WireGuard server for phones; the client config is printed in the console. See [Phones](#phones-android-ios) |
| `--wg-port` | `MITM_WG_PORT` | `51820` | WireGuard UDP port |

```bat
curl -x http://127.0.0.1:8080 https://app.example.com/api/v2/trade
```

For Postman, set the proxy to `127.0.0.1:8080` in *Settings → Proxy*. Any client that uses the Windows certificate store trusts the proxy after `gremlin install`. For other clients, point them to `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem`.

### `gremlin phone run`: proxy + WireGuard for phones

The same as `gremlin proxy run -g -w`: the proxy with a WireGuard server, started as mitmweb so the QR code for the phone is in the *Capture* tab. Runs in the current console, stop it with `Ctrl+C`. Setup and Capacitor specifics: [Phones](#phones-android-ios).

```text
gremlin phone run [-e profile] [-p PORT] [-r rules.json] [--wg-port PORT] [--dry-run]
```

### `gremlin install` (`install.bat`)

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
| `NET::ERR_CERT_AUTHORITY_INVALID` | The certificate is not trusted: run `gremlin install` and restart the browser, or set `MITM_INSECURE=1` / use `-k` |
| Requests do not appear in the proxy log | The page is open in your regular browser instead of the one started by `gremlin run` / `gremlin browser run`, or the proxy is on another port |
| Nothing is mocked at all | `rules/rules.json` is empty (`[]`) after the first run: add rules, see [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile). Also check the proxy log for which rules file is loaded |
| Rule does not match | Compare the `url` pattern with the URL in the proxy log: scheme, port and trailing slash matter. Check `method` and `enabled` |
| Mocked response visible in the proxy log, but the app gets `TypeError: Failed to fetch` | CORS: make sure `cors` is not `false` |
| Rules file changes are ignored | The JSON is invalid; the proxy log shows `invalid JSON` with the line and column, and the previous rules stay active. See [Validation and log messages](#validation-and-log-messages) |
| A rule is missing from `Loaded N rule(s)` | It is invalid and was skipped; the reason is logged just above the summary |
| `mitmdump not found` | Run `gremlin install` |
| `Profile not found: env\<name>.env` | The `-e` name must match a file in `env/` (without `.env`) |
| `[warn] …: unknown key "…" skipped` | A typo in a profile key, or spaces around `=`. The message lists the allowed keys |
| `[!!] Invalid port / Invalid value / Invalid URL / Browser … not found` | An invalid value in the profile or in an option; the message names the setting and the allowed values |
| `'gremlin' is not recognized …` / `The term 'gremlin' is not recognized …` | The console is not in the project folder, or it is PowerShell / Git Bash, which need `.\gremlin` / `./gremlin.bat`. See [Consoles](#consoles) |
| `Invalid URL "1"` and `'…' is not recognized as an internal or external command` | The URL contains `&` and the console did not keep it quoted. See [URLs with `&`](#urls-with-) |
| `[!!] -r is a proxy option` / `-w is a proxy option` | `gremlin browser run` does not start the proxy; pass these to `gremlin proxy run` or use `gremlin run` |
| `[warn] No proxy on port …` | `gremlin browser run` found nothing on the port: start `gremlin proxy run` (with the same `-p`) or use `gremlin run` |
| Proxy window shows `address already in use` | The port is taken; set another `MITM_PORT` or use `-p` |
| mitmweb UI does not open / port conflict | mitmweb uses port `8081` for its UI; do not run the proxy itself on `8081` together with `MITM_WEB=1` / `-w` |
| mitmweb UI answers `403` or asks for a token | Open the UI by the link with `?token=…` printed in the console when mitmweb starts (mitmweb normally opens it by itself) |
| Phone: the WireGuard tunnel is on, but there is no internet and mitmweb shows nothing | The proxy is not running, or the phone does not reach the computer: same Wi-Fi, Windows network set to *Private*, UDP `51820` allowed in the firewall (see [Phones](#phones-android-ios), steps 1-2), no guest-network isolation. If the computer has several network adapters or a VPN, the QR code may carry the wrong address: edit the tunnel's *Endpoint* on the phone to the computer's Wi-Fi IP from `ipconfig` |
| Phone: <http://mitm.it> says the traffic is not going through mitmproxy | The tunnel is off, or the phone uses another VPN at the same time |
| Phone: the browser works, but the Android app gets network / SSL errors | The app does not trust user certificates: add the `network_security_config` and run a debug build, see [Capacitor apps](#capacitor-apps). Also check that the app does not pin certificates |
| Phone: HTTPS fails on iOS | *Settings → General → About → Certificate Trust Settings*: turn on *mitmproxy* |
| Phone: everything stopped working after reinstalling mitmproxy or deleting `%USERPROFILE%\.mitmproxy` | New keys and a new certificate were generated: scan the QR code again and reinstall the certificate on the phone (remove the old one) |

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

1. `gremlin run` reads the profile, starts `gremlin proxy run` in a separate window if nothing listens on the port yet, and waits for the proxy to come up.
2. `gremlin proxy run` runs mitmdump (or mitmweb) with every addon from `addons/` and the rules file.
3. The browser is started with a **separate profile** in `%TEMP%\mitm-profile-<browser>-<port>` and the flags:
   - `--proxy-server=127.0.0.1:<port>`: all HTTP/HTTPS traffic goes through the proxy;
   - `--proxy-bypass-list="<-loopback>"`: by default Chrome never proxies `localhost`; this removes that exception, so a local dev server is intercepted too;
   - `--disable-quic`: HTTP/3 runs over UDP and could bypass the proxy, so it is turned off.

   The separate profile is required: if the regular browser is already open, a new launch only opens a tab in it and ignores the flags. It also keeps your main profile clean. Cookies and logins in the dedicated profile survive between runs; each browser and port pair has its own profile, so several setups can run side by side.
4. For HTTPS, mitmproxy decrypts the traffic with its own certificate, which is why `gremlin install` makes Windows trust it.
5. For every request `mock_errors.py` checks the rules top to bottom; the first match produces a fake response (or a delay/timeout/dropped connection) and the request never reaches the server. Requests without a match pass through unchanged.
6. For phones, `gremlin phone run` starts mitmproxy with two modes: `--mode regular` (the usual proxy on `MITM_PORT`) and `--mode wireguard@51820`. The phone's WireGuard app sends all its traffic to the computer through an encrypted UDP tunnel, mitmproxy takes it out of the tunnel and handles it like any other request. The phone needs nothing else configured, and apps that ignore the system proxy are covered too.

### Why CORS headers

When the app and its API are on different origins, the real server adds `Access-Control-Allow-*` headers. A mocked response is built by the proxy and would lack them, so the browser would hide its body: `fetch` fails with `TypeError` and DevTools shows "Failed to load response data". That is why the addon adds these headers for the request's `Origin` by default (`"cors": true`).

## Project structure

```text
gremlin/
├── README.md
├── .gitignore           # keeps personal env profiles and rule sets out of git
├── .gitattributes       # keeps CRLF line endings in *.bat
├── gremlin.bat          # entry point: gremlin run | proxy run | browser run | phone run | install | test
├── install.bat          # install mitmproxy and trust its certificate (gremlin install)
├── run_tests.bat        # run the tests in .venv (gremlin test, see Tests)
├── commands/            # the scripts behind gremlin's commands
│   ├── proxy-run.bat    # gremlin proxy run: the proxy with all addons (current console)
│   └── run.bat          # gremlin run: start the proxy if needed + open a browser through it;
│                        #   gremlin browser run: the same, browser only (--no-proxy-start)
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

Everything above is in git except the personal files: `rules/*` other than `rules/examples.json`, `env/*.env` other than `env/example.env`, and `.venv/`.

## Extending

- **New error scenario**: add a rule to `rules/rules.json`, or create a new file in `rules/` and point `MITM_RULES` (or `-r`) to it.
- **Sharing a scenario with the team**: add it to `rules/examples.json` (with a `name`, and pointing to `api.example.com` or another placeholder host) or paste it in the task/PR. Personal rule files are not committed.
- **New target app**: create `env/<name>.env` from `env/example.env`.
- **New setting**: add the key to `ENV_KEYS` in `lib/load-env.bat` and to `env/example.env`, read it in the script after the `load-env.bat` call following the `command line > profile > default` pattern used there, and validate it (see `lib/validate.bat`).
- **New rule field**: add it to `REQUIRED_FIELDS` or `OPTIONAL_FIELDS` and validate it in `parse_rule()` in `addons/mock_errors.py`, then document it in [Rules](#rules).
- **New interception logic** (rewriting responses, logging, injecting headers, …): drop a new [mitmproxy addon](https://docs.mitmproxy.org/stable/addons-overview/) into `addons/`. It is picked up on the next proxy start. Prefix shared helper modules with `_` so they are not loaded as addons. If the addon needs its own options, register them in `load()` (like `rules_file` in `mock_errors.py`) and pass values through `--set` in `commands/proxy-run.bat`.
- **Another browser**: set `MITM_BROWSER` (or `-b`) to the full path of its exe (Chromium-based browsers only, because the flags are Chromium flags).

## Tests

Requires Python 3.10+. The first run creates `.venv` in the project folder and installs mitmproxy, pytest and pytest-asyncio into it (the proxy itself keeps using the mitmproxy from `gremlin install`).

Run it from a console in the project folder (in PowerShell `.\gremlin test`, see [Consoles](#consoles)):

```bat
gremlin test                          :: everything, ~30 s
gremlin test -m "not e2e"             :: without starting a real mitmdump, ~20 s
gremlin test -k cors -v               :: only tests with "cors" in the name
gremlin test tests\test_mocking.py    :: one file
gremlin test -x                       :: stop at the first failure
```

Any arguments are passed to pytest as is. Once `.venv` exists, `.venv\Scripts\python -m pytest` works too.

The run ends with a summary such as `175 passed in 33.10s`. On a failure pytest prints the test name and the values that did not match, and `gremlin test` exits with a non-zero code.

| File | What it checks |
| --- | --- |
| `tests/test_parse_rule.py` | Validation of a single rule: required fields, types, ranges, defaults, warnings for typos and fields without effect |
| `tests/test_rules_file.py` | Loading the rules file: invalid JSON / root keeps the previous rules, invalid rules are skipped, `enabled`, duplicates, hot reload, missing file, BOM, warnings instead of errors during startup |
| `tests/test_mocking.py` | Matching (`url` wildcards, `method`, `query`, first match wins) and the mocked response (status, body, `content_type`, `headers`, CORS, `delay`, `timeout`, `kill`, passing through on a failure) |
| `tests/test_e2e.py` | A real mitmdump with the addon between an HTTP client and a local server: passthrough, mock without reaching the server, kill, timeout, delay, hot reload, broken rules do not stop the proxy, WireGuard mode next to the regular proxy |
| `tests/test_scripts.py` | `gremlin run`, `gremlin proxy run`, `gremlin browser run` and `gremlin phone run` via `--dry-run` in a temp copy of the project: profiles, priority of options, validation of ports/booleans/URL, unknown keys, addon discovery, WireGuard options, routing of `gremlin` commands |

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
:: if the firewall rule for phones was added (admin console)
netsh advfirewall firewall delete rule name="gremlin WireGuard"
```

On the phone: delete the `gremlin` tunnel in the WireGuard app and remove the mitmproxy certificate (iOS: *Settings → General → VPN & Device Management*; Android: *Encryption & credentials → User credentials*).
