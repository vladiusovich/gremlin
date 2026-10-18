# Gremlin

*Feed it rules, watch your app break.*

A local tool for Windows and Linux that sits between your app and its API and breaks chosen requests on purpose: to see how the UI copes with errors and odd data, and how the server copes with requests the UI would never send. No changes to the backend or the app code: you describe what to break in a JSON rules file.

For each matching request a rule can:

- **answer instead of the server** (`mock`): any status and body, a delay, a hang or a dropped connection. The request never reaches the server;
- **change the request** before it is sent (`request`): JSON fields, query parameters, headers, form fields, the whole body, the method or the URL. Good for cases the UI does not let you produce, such as a negative amount, a missing field or an expired token;
- **change the real response** before it reaches the app (`response`): the status, JSON fields, headers, the body, a delay. A zero balance, an empty list, a feature flag off.

Everything else passes through untouched.

> ⚠️ `request` / `response` rules talk to the **real server**: a changed request is really executed there. Point them at a test stand, not production.

**Works with:** a dedicated Chrome / Edge window (your regular browser is not affected), `localhost` and real domains over HTTPS, API clients (curl, Postman) and mobile apps on a phone or an emulator through WireGuard, including Capacitor apps.

**Convenient:** rules reload on save, no restart needed; a mistake in a rule is explained in the log while the previous rules keep working; separate profiles per stand or scenario. Built on [mitmproxy](https://mitmproxy.org/), details: [How it works](#how-it-works).

Typical uses:

- check that the UI shows the right message for a specific backend error (`402 Trade session is closed`, `489 Close-only mode`, …);
- reproduce rare or hard-to-trigger errors on demand;
- test loading states, retries and timeouts (`delay`, `timeout`);
- test behaviour on network failures (`kill`);
- send values the UI does not allow (negative amounts, missing fields, broken tokens) and check how the server and the UI react (`request`);
- show the UI real data with one field changed: a zero balance, a closed market, a feature flag off, an empty list (`response`).

Contents:

- [1. Install](#1-install)
- [2. Create a profile](#2-create-a-profile)
- [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile)
- [4. Run](#4-run)
- [Consoles](#consoles): cmd, PowerShell, VS Code, Git Bash, Linux terminals
- [Several profiles and rule sets](#several-profiles-and-rule-sets)
- [Phones (Android, iOS)](#phones-android-ios): mobile and Capacitor apps through WireGuard
- Reference: [Settings profiles](#settings-profiles) · [Command-line options](#command-line-options) · [Rules](#rules) · [Troubleshooting](#troubleshooting)
- Background: [How it works](#how-it-works) · [Project structure](#project-structure) · [Extending](#extending) · [Tests](#tests) · [Uninstall](#uninstall)

## 1. Install

Requirements:

- **Windows 10/11** or **Linux** with a desktop (Ubuntu, Debian, Fedora, Arch, openSUSE, …). macOS is not supported;
- Google Chrome, Microsoft Edge or (on Linux) Chromium;
- Python 3.10+ and mitmproxy: the installer checks for them and offers to install what is missing;
- for phones also the WireGuard app on the phone, see [Phones](#phones-android-ios).

**Windows:** double-click `install.bat` in the project folder (or run `gremlin install` from a console).

**Linux:** run `./install.sh` in a terminal in the project folder (or `./gremlin install`).

The installer:

1. Checks for **Python 3.10+**. If there is none, it asks and installs it: with `winget` on Windows (for the current user, no admin rights), with the package manager on Linux (`apt-get`, `dnf`, `pacman` or `zypper`, asks for the `sudo` password; with `apt-get` it runs `apt-get update` first, a new system has an empty package list).
2. Checks for **mitmproxy**. If there is none, it asks and installs it: with `winget` on Windows, with `pipx` on Linux, otherwise into its own virtual environment (`%LOCALAPPDATA%\gremlin\mitmproxy` / `~/.local/share/gremlin/mitmproxy`).
3. Makes the browser **trust the mitmproxy certificate**, so it accepts HTTPS through the proxy:
   - Windows: adds it to the current user's trusted certificates. When Windows asks whether to install the certificate, answer **Yes**. No admin rights are needed;
   - Linux: adds it to the certificate database of Chrome / Chromium / Edge (`~/.pki/nssdb`, no `sudo`). This needs `certutil`: if it is missing, the installer offers to install it (`libnss3-tools` / `nss-tools` / `nss`). Then it asks whether to trust the certificate **system-wide** too, for curl and other command-line tools (needs `sudo`, optional).

Questions are `[Y/n]`, where `Enter` means yes (the Python question in `install.bat` is `[Y,N]`: press `Y` or `N`). `-y` (`install.bat -y`, `./install.sh -y`) answers yes to all of them. You only do this once; running it again does no harm, steps already done are skipped.

> ⚠️ The certificate's private key in `%USERPROFILE%\.mitmproxy\` (Linux: `~/.mitmproxy/`) allows decrypting your HTTPS traffic. Do not share it. See [Uninstall](#uninstall) to remove it.

## 2. Create a profile

A **profile** is a small text file in the `profiles` folder that says which site to open (`MITM_URL`) and, optionally, the browser and the proxy port.

The file name is the profile name: `profiles\staging.env` is the profile `staging`.

1. Open the `profiles` folder.
2. Copy `example.env` (`Ctrl+C`, `Ctrl+V`) and rename the copy to the profile name, e.g. `staging.env`. Use Latin letters, digits, `-` and `_`, no spaces.
3. Open it in a text editor (Windows: *right click → Open with → Notepad*) and set the site:

   ```ini
   # Site to open in the browser
   MITM_URL=https://staging.example.com/
   ```

   Everything else in the file can stay as it is. Lines starting with `#` are comments.

4. Save the file.

> The profile named `default` (`profiles\default.env`) is special: it is used when no profile is specified. Use it for the setup you run most often.

## 3. Create the rules file for the profile

The rules decide which requests get broken and how. Each profile has **its own rules file with the same name**: the profile `staging` uses `rules\staging.json`, the profile `default` uses `rules\default.json`. Nothing has to be set in the profile for that. On the first run a missing file is created empty, so you can also just run the profile once and then fill in the file.

1. Open the `rules` folder.
2. Create the file named like the profile, e.g. `staging.json` (Windows: *right click → New → Text Document*, then rename it including the extension; make sure it is not `staging.json.txt`).
3. Open it in a text editor and describe the requests to intercept. A file with one rule:

   ```json
   [
     {
       "name": "Order creation fails",
       "method": "POST",
       "url": "https://api.staging.example.com/v1/orders",
       "mock": { "status": 500 }
     }
   ]
   ```

   - `name`: any label, it is shown in the proxy log;
   - `method`: the request method, as in DevTools (`GET`, `POST`, …); remove the line to match any method;
   - `url`: the request address, copied from DevTools → *Network* (right click on the request → *Copy → Copy URL*). `*` matches anything, e.g. `https://api.staging.example.com/v1/orders/*`;
   - `mock`: answer instead of the server: `status` is the HTTP status to return, or `"timeout"` / `"kill"` to simulate a hang or a network failure. The request **never reaches the server**.

   Instead of `mock`, a rule can let the request **reach the server** and change the request and/or the real response:

   ```json
   [
     {
       "name": "Order with a negative amount: does the server reject it?",
       "method": "POST",
       "url": "https://api.staging.example.com/v1/orders",
       "request": { "json": { "amount": -100 } }
     },
     {
       "name": "Real account, but zero balance",
       "method": "GET",
       "url": "https://api.staging.example.com/v1/account",
       "response": { "json": { "balance": 0 } }
     }
   ]
   ```

   > ⚠️ `mock` and `request` / `response` cannot be in one rule: with `mock` the request is never sent, so there is nothing to change. Such a rule is skipped, and the proxy window says why. `request` and `response` together are fine.

   Several rules are separated by commas: `[ { … }, { … } ]`. Every option with examples is described in [`rules/README.md`](rules/README.md); ready-made rules for every case are in [`rules/examples.json`](rules/examples.json): copy the ones you need. Short reference: [Rules](#rules).

4. Save the file.

You can edit and save the rules file while everything is running: changes apply to the next request, no restart needed. If the file has a mistake (a missing comma, a typo in a field name), the proxy window says which rule and which field is wrong, and the previous version of the rules stays active.

> To use another rules file, e.g. one scenario shared by several profiles, set it in the profile: `MITM_RULES=trade-errors` means `rules\trade-errors.json`. See [Several profiles and rule sets](#several-profiles-and-rule-sets).

## 4. Run

Open a console in the project folder (Windows: click the Explorer address bar, type `cmd` and press `Enter`; Linux: open a terminal and `cd` to the folder). Then run the profile by its name, without `.env`:

```bat
gremlin browser run --profile staging
```

On Linux the same command is `./gremlin browser run --profile staging`. For the `default` profile it is just `gremlin browser run`.

> In PowerShell (e.g. the VS Code terminal) type `.\gremlin browser run --profile staging`, in Git Bash `./gremlin.bat browser run --profile staging`. Details: [Consoles](#consoles). `gremlin` without arguments lists all commands.

Two windows open:

- **`mitmproxy :8080`**, the proxy window with the log: a new console window on Windows, a new terminal window on Linux. Check its first lines: `Loaded 1 rule(s) from …\rules\staging.json` confirms that the right rules file is used. Every intercepted request appears here as `MOCK 500 POST https://…  [rule #1 "Order creation fails"]` (or `MODIFY REQ …` / `MODIFY RESP …` for rules that change the request or the response).
- **A separate browser window** with the site from `MITM_URL`. Only this window goes through the proxy; your regular browser works as usual. Test in this window.

Now do the action in the app (e.g. create an order) and check how the UI handles the error.

**To stop**: close the browser window, then press `Ctrl+C` in the proxy window (or just close it).

**To switch to another profile**: stop first (close **both** windows), then run the other profile. If a proxy is already running on the port, `gremlin browser run` reuses it only when it has the same rules file (the console says `Proxy is already listening on port …`). A proxy with other rules, e.g. the previous profile's, stops the run with `A proxy with other rules is already running on port …`: close that proxy window first, or give the profiles different ports.

**To start the proxy and the browser separately** (e.g. to keep the proxy log in your own console, or to restart only the browser): run `gremlin proxy run` in one console and `gremlin browser run` in another, with the same profile. `gremlin browser run` finds the running proxy and only opens the browser. See [Command-line options](#command-line-options).

## Consoles

On Windows `gremlin` is a batch file (`gremlin.bat`), so it runs in any Windows console, but each one calls it a little differently. On Linux it is a shell script (`gremlin`). Both start the same Python code in `lib/`. Always open the console **in the project folder** (or `cd` there first).

| Console | How to open it in the project folder | Command |
| --- | --- | --- |
| Command Prompt (`cmd`) | Explorer address bar → type `cmd` → `Enter` | `gremlin browser run --profile staging` |
| PowerShell | Explorer address bar → type `powershell` → `Enter` | `.\gremlin browser run --profile staging` |
| Windows Terminal | Right click in the folder → *Open in Terminal* (opens PowerShell by default) | `.\gremlin browser run --profile staging` |
| VS Code terminal | *Terminal → New Terminal* (PowerShell by default; switch with the `+ ˅` menu → *Command Prompt*) | PowerShell: `.\gremlin browser run --profile staging`, cmd: `gremlin browser run --profile staging` |
| Git Bash | Right click in the folder → *Open Git Bash here* | `./gremlin.bat browser run --profile staging` |
| Linux (bash, zsh, …) | A terminal, then `cd` to the project folder | `./gremlin browser run --profile staging` |

- **Why `.\` in PowerShell and `./` on Linux**: PowerShell and Linux shells never run programs from the current folder by name alone, so `gremlin` alone gives *"The term 'gremlin' is not recognized"* / *"command not found"*. `.\gremlin` / `./gremlin` means "the one in this folder". Git Bash is the same, and also needs the `.bat` extension.
- **Linux: the proxy window** is opened in the first terminal emulator found: `$TERMINAL` (called as `$TERMINAL -e …`), then GNOME Terminal, Ptyxis, Konsole, Xfce Terminal, GNOME Console, kitty, Alacritty, WezTerm, foot, `x-terminal-emulator`, xterm. Without a desktop session (e.g. over SSH) there is no window to open: run `./gremlin proxy run` in one terminal and `./gremlin browser run` in another.
- **Double-click** works only for `install.bat`. `gremlin.bat` needs a command, so a double-click just shows the help and closes the window.
- **Paths**: `-r rules\trade.json` works in cmd and PowerShell; in Git Bash use forward slashes (`-r rules/trade.json`) or quotes, because `\` is an escape character there.
- **Stopping**: `Ctrl+C` stops `gremlin proxy run` in any console. cmd may ask `Terminate batch job (Y/N)?`: answer `Y`.

### URLs with `&`

A URL with `&` (e.g. `https://app.example.com/?a=1&b=2`) needs care, because `&` separates commands in cmd:

| Console | How to pass it |
| --- | --- |
| cmd | In double quotes: `gremlin browser run "https://app.example.com/?a=1&b=2"` |
| PowerShell | PowerShell drops the quotes before cmd sees them, so add a second pair: `.\gremlin browser run '"https://app.example.com/?a=1&b=2"'`, or stop PowerShell parsing with `--%`: `.\gremlin --% browser run "https://app.example.com/?a=1&b=2"` |
| Git Bash | There is no reliable way to pass it on the command line: put the URL in a profile |
| Linux | In single or double quotes: `./gremlin browser run 'https://app.example.com/?a=1&b=2'` |

The way that works everywhere: put the URL into a profile as `MITM_URL=https://app.example.com/?a=1&b=2` (no quotes) and run `gremlin browser run --profile <profile>`. URLs without `&` (with `?`, `=`, `%20`, …) can be passed in double quotes in any console.

## Several profiles and rule sets

Create as many profiles and rule files as you need. A profile says **where** you test (a stand, its URL and port), a rules file says **what** you break (a scenario). By default each profile uses the rules file with its own name; `MITM_RULES` in the profile or `-r` on the command line picks another one:

```text
profiles\                         rules\
  default.env   ────────────────▶   default.json        everyday local testing
  staging.env   ────────────────▶   staging.json        staging stand
  trade.env     ── MITM_RULES ──▶   trade-errors.json   trading error scenarios
  auth.env      ── MITM_RULES ──▶   auth-errors.json    login / session errors
```

```bat
gremlin browser run --profile trade
gremlin browser run --profile auth

:: any stand with any scenario, without editing the profile
gremlin browser run --profile staging -r trade-errors
```

- A rules file is given by its **short name**, without the `rules` folder and `.json`: `MITM_RULES=trade-errors`, `-r trade-errors`. Subfolders work too, to group scenarios by feature: `-r trade/errors` is `rules\trade\errors.json`. A value ending in `.json` is a path (in the profile relative to the project folder, on the command line relative to the current folder).
- Several profiles may point to the same rules file, e.g. the same scenarios on two stands.
- To run two profiles **at the same time**, give them different ports (`MITM_PORT=8080` and `MITM_PORT=8081`); each gets its own proxy window and browser window.
- Profiles and rule files are personal and are not committed to git; only `profiles\example.env` and `rules\examples.json` are shared. To share a scenario, send the rules file or add it to `rules\examples.json`.

For a one-off change you do not need to edit the profile: command-line options override it, e.g. `gremlin browser run --profile staging -w` additionally opens a web UI with all traffic. See [Command-line options](#command-line-options).

## Phones (Android, iOS)

A mobile app on a real phone, e.g. a React + Capacitor app, goes through the same proxy and the same rules. The phone connects to the computer as a **VPN**: mitmproxy runs a WireGuard server, the phone runs the official WireGuard app, and while the tunnel is on all the phone's traffic goes through the proxy. Nothing has to be configured in the phone's Wi-Fi settings, and it works for apps that ignore the system proxy.

```bat
gremlin mobile run --profile mobile
```

This is `gremlin proxy run` plus WireGuard on UDP port `51820`, started as mitmweb, which shows the QR code for the phone. The regular proxy keeps running on `MITM_PORT` next to it, so `gremlin browser run` with the same profile works at the same time.

### One-time setup

The WireGuard keys are saved in `%USERPROFILE%\.mitmproxy\wireguard.conf` (Linux: `~/.mitmproxy/wireguard.conf`) on the first start, so the phone is set up once and keeps working across restarts.

1. **Network.** The phone and the computer must be on the same Wi-Fi (or the computer on a cable in the same network). Guest and some office networks block devices from seeing each other: use another network or the phone's hotspot. In Windows the network must be *Private* (*Settings → Network & internet → Wi-Fi → the network → Private network*). WSL does not work for this: the phone cannot reach a WSL machine behind Windows' NAT, run gremlin on Windows itself.
2. **Firewall.** On the first `gremlin mobile run` Windows asks whether `mitmweb.exe` may use the network: tick *Private networks* and click *Allow*. If the dialog was dismissed, allow the port from an admin console:

   ```bat
   netsh advfirewall firewall add rule name="gremlin WireGuard" dir=in action=allow protocol=UDP localport=51820
   ```

   On Linux nothing is needed unless a firewall is on; then allow the port: `sudo ufw allow 51820/udp` (Ubuntu) or `sudo firewall-cmd --add-port=51820/udp` (Fedora).

3. **Tunnel.** Run `gremlin mobile run`. mitmweb opens in the browser: go to the *Capture* tab, the *WireGuard* section shows a QR code. On the phone install **WireGuard** (Google Play / App Store), tap *+* → *Scan from QR code*, name the tunnel `gremlin` and allow the VPN.
4. **Certificate.** Turn the tunnel on and open **<http://mitm.it>** in the phone's browser (the page is served by the proxy, so it opens only through the tunnel).
   - **iOS:** tap the iOS certificate → *Allow*. Then *Settings → Profile Downloaded → Install*. Then **also** *Settings → General → About → Certificate Trust Settings* → turn on *mitmproxy*. Without this last step HTTPS fails.
   - **Android:** download the Android certificate. Then *Settings → Security → Encryption & credentials → Install a certificate → CA certificate* → *Install anyway* → pick the downloaded file. Menu names differ between vendors: search the settings for "CA certificate". Tapping the downloaded file does not install it on Android 11+.
5. **Android only:** the app must be allowed to trust this certificate, see [Capacitor apps](#capacitor-apps). Since Android 7 apps ignore user-installed certificates unless they opt in, so without this step the phone's browser works but the app does not.

### Every day

1. `gremlin mobile run --profile mobile`;
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
- **iOS simulator:** runs only on macOS, and gremlin supports only Windows and Linux. The simulator has no VPN and uses the Mac's network settings, so on a Mac run `mitmweb -s addons/mock_errors.py --set rules_file=rules/default.json`, set the Mac's HTTP/HTTPS proxy to `127.0.0.1:8080`, and drag `~/.mitmproxy/mitmproxy-ca-cert.pem` onto the simulator, then trust it as in step 4.

---

## Settings profiles

A profile is a `profiles/<name>.env` file. `profiles/default.env` is loaded when no `--profile` is given; `--profile <name>` loads `profiles/<name>.env`. Profiles are optional, and **every key in a profile is optional**: an omitted key falls back to its default.

| Key | Required | Default | Allowed values |
| --- | --- | --- | --- |
| `MITM_URL` | optional | `http://localhost:3001/` | Start page, must start with `http://` or `https://` |
| `MITM_BROWSER` | optional | `chrome` | `chrome`, `edge`, `chromium` (Linux) or a full path to a Chromium-based browser executable. On Linux `chrome` falls back to Chromium if Google Chrome is not installed |
| `MITM_PORT` | optional | `8080` | Proxy port, `1`-`65535` |
| `MITM_RULES` | optional | `rules/<profile>.json` | Rules file: a short name without `.json` is a file in `rules/` (`trade-errors`, `trade/errors`), a value ending in `.json` is a path, a relative one resolved against the project root. The profile's own file (`rules/<profile>.json`, `rules/default.json` without a profile) is created if missing, any other file must exist |
| `MITM_WEB` | optional | `0` | `1` = run mitmweb (traffic UI at <http://127.0.0.1:8081>) instead of mitmdump |
| `MITM_INSECURE` | optional | `0` | `1` = ignore certificate errors in the browser (if `gremlin install` was not run) |
| `MITM_WIREGUARD` | optional | `0` | `1` = also run a WireGuard server for phones, see [Phones](#phones-android-ios). `gremlin mobile run` turns it on regardless |
| `MITM_WG_PORT` | optional | `51820` | WireGuard UDP port, `1`-`65535`; used only with WireGuard on |

Booleans accept `1`/`0`, `true`/`false`, `yes`/`no`, `on`/`off`.

- **Priority: command-line options > profile > built-in defaults.**
- Format: `KEY=VALUE`, `#` starts a comment line (trailing comments are not supported). An empty value (`MITM_PORT=`) counts as not set.
- Validation: an unknown key (a typo like `MITM_PROT`) is skipped with a `[warn]` listing the allowed keys, so a profile cannot override system variables such as `PATH` either. An invalid value (`MITM_PORT=abc`, `MITM_WEB=maybe`, a URL without scheme, a browser that does not exist) stops the script with an `[!!]` error that names the setting.
- `profiles/example.env` is the shared template with all keys; your own profiles are ignored by git.

## Command-line options

All arguments are optional. Options override the values from the profile and are validated the same way.

### `gremlin browser run`: proxy + browser

Starts `gremlin proxy run` in a separate window if nothing listens on the port yet, waits for it and opens the browser through it. A proxy already running on the port is reused if it has the same rules file; if it has other rules, or the port is taken by another program, the command stops with an error instead of opening a browser through the wrong proxy.

```text
gremlin browser run [URL] [options]
```

| Option | Profile key | Default | Description |
| --- | --- | --- | --- |
| `URL` | `MITM_URL` | `http://localhost:3001/` | Start page |
| `--profile` | | `profiles/default.env`, if present | Profile `profiles/<name>.env` |
| `-b`, `--browser` | `MITM_BROWSER` | `chrome` | `chrome`, `edge`, `chromium` (Linux) or a full path to a Chromium-based browser executable |
| `-p`, `--port` | `MITM_PORT` | `8080` | Proxy port |
| `-r`, `--rules` | `MITM_RULES` | `rules\<profile>.json` | Rules file: a short name (`trade-errors` = `rules\trade-errors.json`) or a path ending in `.json` (relative to the current folder) |
| `-w`, `--web` | `MITM_WEB` | off | Start the proxy as **mitmweb**: a web UI with all traffic at <http://127.0.0.1:8081> |
| `-k`, `--insecure` | `MITM_INSECURE` | off | Ignore certificate errors |
| `--dry-run` | | | Print the commands without running anything |

Examples:

```bat
:: deployed app on a real domain, without a profile
gremlin browser run https://app.example.com/

:: profile, but Edge on another port with a separate rule set
gremlin browser run --profile staging -b edge -p 8081 -r trade-errors

:: see all requests and responses in a web UI
gremlin browser run -w
```

### `gremlin proxy run`: proxy only

Runs the proxy in the current console: for `gremlin browser run` in another console, or for clients other than the browser (curl, Postman, …). Stop it with `Ctrl+C`.

```text
gremlin proxy run [--profile NAME] [-p PORT] [-r RULES] [-w] [-g] [--wg-port PORT] [--dry-run]
```

It uses the `MITM_PORT`, `MITM_RULES`, `MITM_WEB`, `MITM_WIREGUARD` and `MITM_WG_PORT` keys of the profile; `--profile`, `-p`, `-r` and `-w` mean the same as in `gremlin browser run`.

| Option | Profile key | Default | Description |
| --- | --- | --- | --- |
| `-g`, `--wireguard` | `MITM_WIREGUARD` | off | Also run a WireGuard server for phones; the client config is printed in the console. See [Phones](#phones-android-ios) |
| `--wg-port` | `MITM_WG_PORT` | `51820` | WireGuard UDP port |

```bat
curl -x http://127.0.0.1:8080 https://app.example.com/api/v2/trade
```

For Postman, set the proxy to `127.0.0.1:8080` in *Settings → Proxy*. On Windows any client that uses the Windows certificate store trusts the proxy after `gremlin install`; on Linux curl and other tools that use the system store do so if you agreed to the system-wide step of `./gremlin install`. For other clients, point them to `%USERPROFILE%\.mitmproxy\mitmproxy-ca-cert.pem` (Linux: `~/.mitmproxy/mitmproxy-ca-cert.pem`).

### `gremlin mobile run`: proxy + WireGuard for phones

The same as `gremlin proxy run -g -w`: the proxy with a WireGuard server, started as mitmweb so the QR code for the phone is in the *Capture* tab. Runs in the current console, stop it with `Ctrl+C`. Setup and Capacitor specifics: [Phones](#phones-android-ios).

```text
gremlin mobile run [--profile NAME] [-p PORT] [-r RULES] [--wg-port PORT] [--dry-run]
```

### `gremlin install` (`install.bat`, `install.sh`)

```text
gremlin install [-y]
```

`-y`, `--yes` answers yes to every question. Without a console to answer in (e.g. input from a pipe), every question is answered no. Steps, each skipped if already done:

1. Finds Python 3.10+, or asks and installs it: `winget install Python.Python.3.12 --scope user` on Windows, the package manager on Linux (`python3` and `python3-venv` with `apt-get`, after `apt-get update`; `python3` with `dnf` / `zypper`, `python` with `pacman`). This step is in `install.bat` / `install.sh`, which need no Python; the steps below are in Python (`lib/gremlin_cli/install.py`).
2. Finds mitmproxy, or asks and installs it: `winget` on Windows, `pipx` on Linux; if that is unavailable or fails, `pip` into a virtual environment of its own (`%LOCALAPPDATA%\gremlin\mitmproxy`, `~/.local/share/gremlin/mitmproxy`).
3. Generates the mitmproxy root certificate (`%USERPROFILE%\.mitmproxy\`, `~/.mitmproxy/`) if it does not exist yet.
4. Trusts the certificate:
   - Windows: adds it to the current user's *Trusted Root Certification Authorities*;
   - Linux: adds it to the NSS database of Chromium-based browsers, `~/.pki/nssdb` (and `~/snap/chromium/current/.pki/nssdb` for Chromium from snap; if snap Chromium was never started, that folder does not exist yet and the installer asks to start it once and run again), replacing an older mitmproxy certificate there. Needs `certutil`: asks to install `libnss3-tools` / `nss-tools` / `nss` / `mozilla-nss-tools` if it is missing. Then asks whether to add it to the system store as well (`/usr/local/share/ca-certificates` + `update-ca-certificates` on Debian / Ubuntu, `/etc/pki/ca-trust/source/anchors` + `update-ca-trust` on Fedora, and the like), needs `sudo`.

## Rules

A short reference. **The full guide with an example for every option is [`rules/README.md`](rules/README.md).**

A rules file is a JSON array. For each request the rules are checked top to bottom, and the **first match wins**. A rule picks requests by `url` (required), `method` and `query`, and does **one of two things**:

| Kind | Fields | The request reaches the server? | What it does |
| --- | --- | --- | --- |
| Fake answer | `mock` | ❌ **No** | The proxy answers by itself: `status` (or `"timeout"` / `"kill"`), `body`, `content_type`, `headers`, `delay`, `cors` |
| Real call, changed | `request` and/or `response` | ✅ **Yes** | `request` changes what is sent: `json`, `body`, `query`, `headers`, `form`, `replace`, `method`, `url`, `delay`. `response` changes the real answer: `status`, `json`, `body`, `replace`, `headers`, `delay` |

> ⚠️ **`mock` cannot be combined with `request` or `response`**: with `mock` the request is never sent, so there is no request and no real answer to change. Such a rule is **an error and is skipped**, with the reason in the proxy window. `request` and `response` together are fine: they are the two ends of one real call. Details: [Two kinds of rules](rules/README.md#two-kinds-of-rules).

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `url` | string | **required** | URL pattern: scheme, host, **port**, path. `*` matches any characters, `?` matches any single character. Without `query` it is matched against the full URL, including the query string |
| `method` | string | `"*"` | `GET`, `POST`, `PUT`, `DELETE`, … (case-insensitive) or `*` for any |
| `query` | object | not checked | Query parameters that must be present, e.g. `{"Type": "Cancel"}`. Values are strings or numbers and support `*`. With `query` set, `url` is matched **without** the query string, and parameter order does not matter |
| `mock` | object | | Answer instead of the server, see the table below and [Mocking the response](rules/README.md#mocking-the-response-mock) |
| `request` | object | | Changes to the request before it is sent, see [Changing the request](rules/README.md#changing-the-request-request) |
| `response` | object | | Changes to the real response, see [Changing the response](rules/README.md#changing-the-response-response) |
| `enabled` | boolean | `true` | `false` keeps the rule in the file but skips it (without validating it) |
| `name` | string | | Label shown in the proxy log: `rule #3 "Trade session closed"` |
| `comment` | any | | Free text, ignored. An entry with only `comment` is a note between rules |

Fields of `mock`:

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `status` | number or string | **required** | HTTP status `100`-`599` as a number (`500`, not `"500"`), `"timeout"` (hang for `delay` seconds, then drop the connection) or `"kill"` (drop the connection immediately) |
| `body` | any | generated JSON | Object or array: sent as JSON. String: sent as is (wrap it in `\"…\"` if the client expects a JSON string). Omitted or `null`: a JSON body describing the mock |
| `content_type` | string | `"application/json"` | `Content-Type` of the response |
| `headers` | object | none | Response headers, e.g. `{"Retry-After": "10"}`; values are strings or numbers |
| `delay` | number | `0` (`30` for `"timeout"`) | Seconds (`>= 0`, fractions allowed) to wait before responding |
| `cors` | boolean | `true` | Add `Access-Control-Allow-*` headers for the request's `Origin` (see [Why CORS headers](#why-cors-headers)). Set to `false` to reproduce a CORS failure |

With `"status": "kill"` or `"timeout"` no response is sent, so `body`, `content_type`, `headers` and `cors` have no effect (and `delay` neither for `kill`).

Changes inside `request` and `response` (`null` removes a field, a parameter or a header everywhere):

| Change | `request` | `response` | Example |
| --- | --- | --- | --- |
| `json` | ✅ | ✅ | `{"amount": -1, "meta": {"source": null}}`: merged into the JSON body |
| `body` | ✅ | ✅ | `{"items": []}` or `"raw text"`: replaces the whole body |
| `replace` | ✅ | ✅ | `{"from": "Open", "to": "Closed"}`, or a list; `"regex": true` for regular expressions |
| `headers` | ✅ | ✅ | `{"Authorization": null, "X-Client-Version": "0.0.1"}` |
| `delay` | ✅ | ✅ | `5`: seconds before sending the request / returning the response |
| `query` | ✅ | | `{"pageSize": 100000, "debug": null}` |
| `form` | ✅ | | `{"amount": "-1"}`: fields of an `application/x-www-form-urlencoded` body |
| `method` | ✅ | | `"DELETE"` |
| `url` | ✅ | | `"http://localhost:5000/v2/quotes"`: send the request elsewhere |
| `status` | | ✅ | `401`: the body stays real (the server **has** processed the request) |

Rule files in `rules/` are **personal** and ignored by git. The shared files are [`rules/README.md`](rules/README.md), the guide, and [`rules/examples.json`](rules/examples.json), a working example of every feature.

### Tips

- Write the URL the way the browser actually sends it, including a non-default port (`https://host:8443/...`). The exact URL can be copied from the proxy log or from DevTools.
- `?` in a pattern is a wildcard. To match a query string reliably, use the `query` field instead of putting `?a=b` in `url`.
- Keep scenarios in separate files (`rules/trade-errors.json`, `rules/auth-errors.json`, …) and switch between them by short name with `MITM_RULES` in a profile or `-r`: `-r trade-errors`. Subfolders group them by feature: `-r trade/errors`.
- To turn a rule off temporarily, set `"enabled": false` instead of deleting it.
- To check what the server actually received after a `request` change, run with `-w` and open the request in mitmweb: it shows the changed request.

### Validation and log messages

The rules file is validated every time it is (re)loaded, and the result is printed in the proxy window. Rules are numbered from 1 in file order.

| Problem | What happens | Example log line |
| --- | --- | --- |
| Invalid JSON | The whole file is rejected, **the previous rules stay active** | `rules.json:4:17: invalid JSON: Expecting ',' delimiter. Keeping the previous 3 rule(s).` |
| The root is not an array | Same as invalid JSON | `rules.json: the root must be a JSON array [ ... ] of rules, got object. …` |
| A rule is invalid (missing required field, wrong type, out of range, nothing to do, `mock` together with `request` / `response`) | **Only that rule is skipped**, the others are loaded. All problems of the rule are listed, each naming the field and whether it is required or optional | `rules.json: rule #2 "typo": field 'request.json' (optional): expected an object like {"amount": -1} …` |
| `mock` together with `request` / `response` | The rule is skipped, the message explains why the two cannot be combined | `rules.json: rule #3: incompatible: 'mock' cannot be used together with 'response' in one rule. 'mock' answers instead of the server, so the request is never sent, while 'response' changes the answer that comes back from the server. Keep either 'mock' or 'response'` |
| Unknown field (typo) | Warning with a suggestion, the field is ignored, the rule is loaded | `rules.json: rule #2: unknown field 'metod' is ignored, did you mean 'method'?` |
| A rule that can never match or has fields without effect | Warning, the rule is loaded | `rules.json: rule #7 "dup": same method/url/query as rule #1 "ok", it will never match (first match wins)` |
| The file is missing | Error once, nothing is mocked until the file appears | `Rules file not found: …` |
| A change that does not fit the body (e.g. `json` on a non-JSON body) | Warning, that change is skipped, the other changes are applied | `rule #4: request: 'json' skipped: the body is not JSON (use 'replace' or 'body' instead)` |
| A failure while mocking or changing a request | Error with a traceback; the request (or response) goes on as is | `rule #3: failed to mock GET https://…, passing the request through` |

What each intercepted request looks like in the log:

```text
MOCK 500 POST https://…/v1/orders  [rule #1 "Order fails"]
MODIFY REQ POST https://…/v1/orders  [rule #2 "Negative amount"]: json, headers
MODIFY RESP 200 -> 401 GET https://…/v1/trade  [rule #3]: status, json
```

Every load ends with a summary such as `Loaded 5 rule(s) from …, 1 disabled, 2 invalid skipped (see errors above)`.

Problems found while the proxy is starting are printed as warnings rather than errors: mitmdump exits if anything is logged as an error during startup, and one bad rule should not take the proxy down.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `NET::ERR_CERT_AUTHORITY_INVALID` | The certificate is not trusted: run `gremlin install` and restart the browser, or set `MITM_INSECURE=1` / use `-k` |
| Requests do not appear in the proxy log | The page is open in your regular browser instead of the one started by `gremlin browser run`, or the proxy is on another port |
| Nothing is mocked at all | The profile's rules file (`rules/<profile>.json`) is empty (`[]`) after the first run, or you are editing another file (e.g. `staging.json.txt`): add rules, see [3. Create the rules file for the profile](#3-create-the-rules-file-for-the-profile). Also check the proxy log for which rules file is loaded |
| Rule does not match | Compare the `url` pattern with the URL in the proxy log: scheme, port and trailing slash matter. Check `method` and `enabled` |
| Mocked response visible in the proxy log, but the app gets `TypeError: Failed to fetch` | CORS: make sure `cors` is not `false` |
| Rules file changes are ignored | The JSON is invalid; the proxy log shows `invalid JSON` with the line and column, and the previous rules stay active. See [Validation and log messages](#validation-and-log-messages) |
| A rule is missing from `Loaded N rule(s)` | It is invalid and was skipped; the reason is logged just above the summary |
| `mitmdump not found` | Run `gremlin install` |
| `Profile not found: profiles\<name>.env` | The `--profile` name must match a file in `profiles/` (without `.env`) |
| `Rules file not found: …` | `MITM_RULES` or `-r` names a file that does not exist: check the name against the `rules` folder. Only the profile's own `rules/<profile>.json` is created automatically |
| `[warn] …: unknown key "…" skipped` | A typo in a profile key. The message lists the allowed keys |
| `[!!] Invalid port / Invalid value / Invalid URL / Browser … not found` | An invalid value in the profile or in an option; the message names the setting and the allowed values |
| `'gremlin' is not recognized …` / `The term 'gremlin' is not recognized …` / `gremlin: command not found` | The console is not in the project folder, or it is PowerShell / Git Bash / Linux, which need `.\gremlin` / `./gremlin.bat` / `./gremlin`. See [Consoles](#consoles) |
| `[!!] Python 3.10+ not found` | Run `install.bat` (Windows) or `./install.sh` (Linux): it installs Python |
| Linux: `Permission denied` for `./gremlin` or `./install.sh` | The files lost the executable bit (e.g. copied from a Windows share or a zip): `chmod +x gremlin install.sh`, or run them as `sh gremlin …` / `sh install.sh` |
| Linux: `[!!] No terminal emulator could open the proxy window` | Every terminal found failed to start; the message shows each one's error (e.g. zutty without the `xfonts-base` package: `No suitable files for '9x18' found`). Install the missing package or another terminal (`sudo apt-get install xterm`), or set `TERMINAL` to a working one |
| Linux: the proxy window opens, its title is `mitmproxy :8080`, but it stays empty | The terminal cannot draw (seen with zutty under WSLg, which has no GPU acceleration); the proxy itself works. Use another terminal: `TERMINAL=xterm ./gremlin browser run` |
| Linux: `[!!] No graphical session` / `No terminal emulator found` | `gremlin browser run` cannot open a window for the proxy: run `./gremlin proxy run` in one terminal and `./gremlin browser run` in another, or set `TERMINAL` to your terminal emulator. See [Consoles](#consoles) |
| Linux: the browser shows certificate errors after `./gremlin install` | `certutil` was missing and was not installed (the installer warns about it), or the browser was open during the install: restart it. Chromium from snap (Ubuntu) that was never started has no certificate database yet: start it once, close it and run `./gremlin install` again (the installer warns about it). Chromium from Flatpak keeps its own certificate database and is not covered: use `-k` |
| Linux: `Failed to create a virtual environment` | Debian / Ubuntu ship Python without `venv`: `sudo apt-get install python3-venv` (the installer offers it) |
| `Invalid URL "1"` and `'…' is not recognized as an internal or external command` | The URL contains `&` and the console did not keep it quoted. See [URLs with `&`](#urls-with-) |
| `[!!] A proxy with other rules is already running on port …` | A proxy started with another profile or `-r` is still running on this port. Stop it (`Ctrl+C` in its window) and run again, or use another `-p` / `MITM_PORT` |
| `[!!] Port … is used by …, not by the gremlin proxy` | Another program listens on the port: close it or use another `-p` / `MITM_PORT` |
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

```text
 Browser (dedicated profile)
        │  all traffic, including localhost
        ▼
 mitmproxy 127.0.0.1:8080 ── addons/mock_errors.py ── rules/<profile>.json
        │                │                         │
        │ no rule        │ "mock"                  │ "request" / "response"
        ▼                ▼                         ▼
   real server     mocked response       changed request ──► real server
                   (server not asked)    changed response ◄──┘
```

1. `gremlin.bat` (Windows) and `gremlin` (Linux) only find Python and run `lib/main.py`; the commands themselves are the same Python code on both platforms (`lib/gremlin_cli/`, standard library only).
2. `gremlin browser run` reads the profile, starts `gremlin proxy run` in a separate window if nothing listens on the port yet (a new console with `cmd /k` on Windows, a terminal emulator on Linux), and waits for the proxy to come up. To tell whether the port is taken it checks the listening sockets, not a test connection (`lib/port-owner.ps1` on Windows, `/proc/net/tcp` on Linux), and it recognizes a gremlin proxy and its rules file by the `rules_file=` in the process command line.
3. `gremlin proxy run` runs mitmdump (or mitmweb) with every addon from `addons/` and the rules file.
4. The browser is started with a **separate profile** in `%TEMP%\mitm-profile-<browser>-<port>` (Linux: `/tmp/mitm-profile-<browser>-<port>`) and the flags:
   - `--proxy-server=127.0.0.1:<port>`: all HTTP/HTTPS traffic goes through the proxy;
   - `--proxy-bypass-list="<-loopback>"`: by default Chrome never proxies `localhost`; this removes that exception, so a local dev server is intercepted too;
   - `--disable-quic`: HTTP/3 runs over UDP and could bypass the proxy, so it is turned off;
   - Linux only, `--password-store=basic`: a new profile would otherwise ask to unlock the desktop keyring.

   The separate profile is required: if the regular browser is already open, a new launch only opens a tab in it and ignores the flags. It also keeps your main profile clean. Cookies and logins in the dedicated profile survive between runs (on Linux until a reboot clears `/tmp`); each browser and port pair has its own profile, so several setups can run side by side.
5. For HTTPS, mitmproxy decrypts the traffic with its own certificate, which is why `gremlin install` makes the browser trust it: the Windows certificate store, or on Linux the NSS database that Chromium-based browsers use.
6. For every request `mock_errors.py` checks the rules top to bottom, and the first match decides. With `mock` it produces a fake response (or a delay/timeout/dropped connection), and the request never reaches the server. With `request` it changes the request and sends it on; with `response` it remembers the rule and changes the server's answer when it arrives (the `response` hook of mitmproxy). Compressed bodies are decompressed and compressed back, `Content-Length` is updated. Requests without a match pass through unchanged.
7. For phones, `gremlin mobile run` starts mitmproxy with two modes: `--mode regular` (the usual proxy on `MITM_PORT`) and `--mode wireguard@51820`. The phone's WireGuard app sends all its traffic to the computer through an encrypted UDP tunnel, mitmproxy takes it out of the tunnel and handles it like any other request. The phone needs nothing else configured, and apps that ignore the system proxy are covered too.

### Why CORS headers

When the app and its API are on different origins, the real server adds `Access-Control-Allow-*` headers. A mocked response is built by the proxy and would lack them, so the browser would hide its body: `fetch` fails with `TypeError` and DevTools shows "Failed to load response data". That is why the addon adds these headers for the request's `Origin` by default (`"cors": true`).

## Project structure

```text
gremlin/
├── README.md
├── .gitignore           # keeps personal profiles and rule sets out of git
├── .gitattributes       # CRLF line endings in *.bat, LF in shell scripts
├── gremlin.bat          # entry point on Windows: gremlin browser run | proxy run | mobile run | install | test
├── gremlin              # entry point on Linux: ./gremlin browser run | …
├── install.bat          # Windows: Python (if missing), then gremlin install
├── install.sh           # Linux: Python (if missing), then ./gremlin install
├── requirements-dev.txt # test dependencies
├── pytest.ini
├── tests/               # pytest suite
├── addons/              # mitmproxy addons, all *.py are loaded automatically
│   └── mock_errors.py   # rule-based mocking and request/response changes
├── rules/               # rule sets for mock_errors.py
│   ├── README.md        # guide to every rule option with examples (shared)
│   ├── examples.json    # reference of all rule features (shared)
│   └── <profile>.json   # rules of each profile (personal, created empty on first run)
├── profiles/            # settings profiles
│   ├── example.env      # template with all keys (shared)
│   └── <name>.env       # your profiles (personal)
└── lib/                 # the commands, run through gremlin.bat / gremlin
    ├── main.py          # entry point of the Python part
    ├── gremlin_cli/     # the commands, the same on Windows and Linux (standard library only)
    │   ├── cli.py       # routes "gremlin <command>" to the modules below
    │   ├── browser.py   # gremlin browser run: start the proxy if needed + open a browser through it
    │   ├── proxy.py     # gremlin proxy run / mobile run: the proxy with all addons (current console)
    │   ├── install.py   # gremlin install: mitmproxy and trust in its certificate
    │   ├── testing.py   # gremlin test: pytest in .venv
    │   ├── profile.py   # reads profiles/<name>.env, picks the rules file
    │   ├── ports.py     # what listens on the port: nothing, a gremlin proxy (with which rules) or another program
    │   ├── terminal.py  # a new console / terminal window for the proxy
    │   └── common.py    # output, options, validation, finding mitmdump
    ├── port-owner.ps1   # Windows part of ports.py
    ├── find-python.bat  # finds Python 3.10+ for gremlin.bat and install.bat
    └── find-python.sh   # the same for gremlin and install.sh
```

Everything above is in git except the personal files: `rules/*` other than `rules/README.md` and `rules/examples.json`, `profiles/*.env` other than `profiles/example.env`, and `.venv/`.

## Extending

- **New test scenario**: add a rule to the profile's `rules/<profile>.json`, or create a new file in `rules/` and point `MITM_RULES` (or `-r`) to it by name.
- **Sharing a scenario with the team**: add it to `rules/examples.json` (with a `name`, and pointing to `api.example.com` or another placeholder host) or paste it in the task/PR. Personal rule files are not committed.
- **New target app**: create `profiles/<name>.env` from `profiles/example.env`.
- **New setting**: add the key to `ENV_KEYS` in `lib/gremlin_cli/profile.py` and to `profiles/example.env`, read it in the command (`browser.py` / `proxy.py`) following the `option or profile or default` pattern used there, and validate it (see `validate_port()` / `validate_bool()` in `common.py`).
- **New command**: add a module to `lib/gremlin_cli/` with a `run(args) -> int` and route it in `cli.py`; `gremlin.bat` and `gremlin` pass every command on as is.
- **New rule field**: add it to `REQUIRED_FIELDS` or `OPTIONAL_FIELDS` and validate it in `parse_rule()` in `addons/mock_errors.py`, then document it in [`rules/README.md`](rules/README.md) and [Rules](#rules).
- **New change in `request` / `response`**: add it to `REQUEST_OPS` / `RESPONSE_OPS`, a field to `Ops`, validate it in `_parse_ops()` and apply it in `apply_ops()` in `addons/mock_errors.py`. Add an example to `rules/examples.json` (a test checks that every change has one) and document it in [`rules/README.md`](rules/README.md); `json` blocks there are validated by the tests too.
- **New interception logic** beyond rules (logging, recording, …): drop a new [mitmproxy addon](https://docs.mitmproxy.org/stable/addons-overview/) into `addons/`. It is picked up on the next proxy start. Prefix shared helper modules with `_` so they are not loaded as addons. If the addon needs its own options, register them in `load()` (like `rules_file` in `mock_errors.py`) and pass values through `--set` in `lib/gremlin_cli/proxy.py`.
- **Another browser**: set `MITM_BROWSER` (or `-b`) to the full path of its executable (Chromium-based browsers only, because the flags are Chromium flags).

## Tests

Requires Python 3.10+. The first run creates `.venv` in the project folder and installs mitmproxy, pytest and pytest-asyncio into it (the proxy itself keeps using the mitmproxy from `gremlin install`).

Run it from a console in the project folder (in PowerShell `.\gremlin test`, on Linux `./gremlin test`, see [Consoles](#consoles)):

```bat
gremlin test                          :: everything, ~1 min
gremlin test -m "not e2e"             :: without starting a real mitmdump, ~20 s
gremlin test -k cors -v               :: only tests with "cors" in the name
gremlin test tests\test_mocking.py    :: one file
gremlin test -x                       :: stop at the first failure
```

Any arguments are passed to pytest as is. Once `.venv` exists, `.venv\Scripts\python -m pytest` (Linux: `.venv/bin/python -m pytest`) works too. The whole suite runs on both Windows and Linux; a few tests are for one platform only and are skipped on the other.

The run ends with a summary such as `376 passed, 5 skipped in 53.00s` (Windows; on Linux nothing is skipped). On a failure pytest prints the test name and the values that did not match, and `gremlin test` exits with a non-zero code.

| File | What it checks |
| --- | --- |
| `tests/test_parse_rule.py` | Validation of a single rule: required fields, types, ranges, defaults, warnings for typos and fields without effect |
| `tests/test_parse_rule.py` (sections) | Validation of `request` / `response`: every change, `null` values, `replace` with regular expressions, changes from the wrong section, `mock` fields, `mock` fields written at the top level of a rule, `mock` combined with `request` / `response` is an error with an explanation |
| `tests/test_rules_file.py` | Loading the rules file: invalid JSON / root keeps the previous rules, invalid rules are skipped, `enabled`, comment-only notes, duplicates, hot reload, missing file, BOM, warnings instead of errors during startup; `rules/examples.json` loads without warnings and covers every change; every `json` block in `README.md` and `rules/README.md` is a valid rule |
| `tests/test_modify.py` | Changing the request and the response: JSON Merge Patch, `json`, `body`, `query`, `headers`, `form`, `replace`, `method`, `url`, `status`, `delay`, gzip bodies, order of changes, warnings when a change does not fit the body, log lines, failures |
| `tests/test_mocking.py` | Matching (`url` wildcards, `method`, `query`, first match wins) and the mocked response (status, body, `content_type`, `headers`, CORS, `delay`, `timeout`, `kill`, passing through on a failure) |
| `tests/test_e2e.py` | A real mitmdump with the addon between an HTTP client and a local server: passthrough, mock without reaching the server, changed request as the server sees it (JSON, query, headers, form, method, URL), changed response (including gzip), both together, kill, timeout, delay, hot reload, broken rules do not stop the proxy, WireGuard mode next to the regular proxy |
| `tests/test_scripts.py` | `gremlin browser run`, `gremlin proxy run` and `gremlin mobile run` via `--dry-run` in a temp copy of the project, through the platform's entry point (`gremlin.bat` / `gremlin`) with fake browsers on `PATH`: profiles, priority of options, validation of ports/booleans/URL, unknown keys, addon discovery, WireGuard options, reusing or refusing a proxy already on the port, routing of `gremlin` commands including `install`, no desktop session on Linux |
| `tests/test_install.py` | `gremlin install` on Linux: the browsers' certificate databases it writes to, including Chromium from snap, started or not |
| `tests/test_terminal.py` | Linux: the proxy window. A terminal emulator that fails to start is skipped for the next one, the error of each is shown when none works, a terminal that hands the window over and exits counts as started, a failing proxy keeps the window open. Fake terminals, no window is opened |

When adding a rule field, a change in `request` / `response` or a profile key, add a test next to the existing ones for that layer.

## Uninstall

Windows:

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
:: if mitmproxy was installed into gremlin's own virtual environment
rmdir /s /q "%LOCALAPPDATA%\gremlin"
```

Python installed by `install.bat` is removed like any other program (*Settings → Apps*), if nothing else needs it.

Linux:

```sh
# remove the certificate from the browsers' database (and from snap Chromium's, if there is one)
certutil -d sql:$HOME/.pki/nssdb -D -n mitmproxy
certutil -d sql:$HOME/snap/chromium/current/.pki/nssdb -D -n mitmproxy
# if it was added system-wide: Debian / Ubuntu
sudo rm /usr/local/share/ca-certificates/mitmproxy.crt && sudo update-ca-certificates --fresh
# … or Fedora
sudo rm /etc/pki/ca-trust/source/anchors/mitmproxy.pem && sudo update-ca-trust
# remove mitmproxy (pipx, or gremlin's own virtual environment)
pipx uninstall mitmproxy
rm -rf ~/.local/share/gremlin
# remove the certificate files and browser profiles
rm -rf ~/.mitmproxy /tmp/mitm-profile-*
```

On the phone: delete the `gremlin` tunnel in the WireGuard app and remove the mitmproxy certificate (iOS: *Settings → General → VPN & Device Management*; Android: *Encryption & credentials → User credentials*).
