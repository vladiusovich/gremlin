"""gremlin browser run: a browser with a dedicated profile whose traffic all goes through the proxy.

If no proxy listens on the port yet, starts gremlin proxy run in a separate window. A proxy already
running on the port is reused only if it has the same rules file; with other rules, or another program
on the port, the command stops with an error instead of opening a browser through the wrong proxy.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import profile, proxy
from .common import (MAIN, PROG, WINDOWS, detail, fail, find_mitmdump, info, is_on, ok,
                     parse_options, show, validate_bool, validate_port)
from .ports import port_owner
from .terminal import open_window

BROWSERS = "chrome, edge" if WINDOWS else "chrome, chromium, edge"
USAGE = (f"Usage: {PROG} browser run [URL] [--profile NAME] [-b {BROWSERS.replace(', ', '|')}|path] [-p PORT] "
         "[-r RULES] [-w] [-k] [--dry-run]")

OPTIONS = {
    "--profile": ("profile", True),
    "-b": ("browser", True), "--browser": ("browser", True),
    "-p": ("port", True), "--port": ("port", True),
    "-r": ("rules", True), "--rules": ("rules", True),
    "-w": ("web", False), "--web": ("web", False),
    "-k": ("insecure", False), "--insecure": ("insecure", False),
    "--dry-run": ("dry", False),
}

# Names of the known browsers: executables looked up on PATH, then (Windows) in the registry and
# the usual install folders. "chrome" falls back to Chromium on Linux.
LINUX_NAMES = {
    "chrome": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "chromium": ["chromium", "chromium-browser"],
    "edge": ["microsoft-edge", "microsoft-edge-stable"],
}
WINDOWS_NAMES = {
    "chrome": ("chrome.exe", [r"Google\Chrome\Application"]),
    "edge": ("msedge.exe", [r"Microsoft\Edge\Application"]),
}


def run(args: list[str]) -> int:
    opts = parse_options(args, OPTIONS, USAGE, positional="url")
    settings, profile_file = profile.load(opts.get("profile"))
    if profile_file:
        ok(f"Profile: {profile_file}")

    url = opts.get("url") or settings.get("MITM_URL") or "http://localhost:3001/"
    browser = opts.get("browser") or settings.get("MITM_BROWSER") or "chrome"
    port = opts.get("port") or settings.get("MITM_PORT") or "8080"
    rules = profile.rules_for(opts.get("rules"), settings, profile_file)
    web = bool(opts.get("web")) or is_on(settings.get("MITM_WEB"))
    insecure = bool(opts.get("insecure")) or is_on(settings.get("MITM_INSECURE"))
    dry = bool(opts.get("dry"))

    validate_port(port)
    validate_bool("MITM_WEB", settings.get("MITM_WEB"))
    validate_bool("MITM_INSECURE", settings.get("MITM_INSECURE"))
    if not url.lower().startswith(("http://", "https://")):
        fail(f'Invalid URL "{url}": must start with http:// or https:// (URL argument or MITM_URL in the profile)')

    exe = find_browser(browser)
    if not exe:
        what = "exe" if WINDOWS else "executable"
        fail(f'Browser "{browser}" not found: use {BROWSERS} or a full path to the browser {what} '
             "(option -b or MITM_BROWSER in the profile)")

    owner, details = port_owner(port, rules)
    if owner == "same":
        ok(f"Proxy is already listening on port {port}, rules: {rules}")
    elif owner == "other-rules":
        fail(f"A proxy with other rules is already running on port {port}: {details}",
             f"This profile needs: {rules}",
             "Stop that proxy (Ctrl+C in its window) and run again, or use another port: -p PORT")
    elif owner != "free":
        fail(f"Port {port} is used by {details}, not by the gremlin proxy.",
             "Close that program or use another port: -p PORT (or MITM_PORT in the profile)")
    else:
        # Pass the profile on, so the proxy resolves its own settings (e.g. WireGuard) the same way
        proxy_args = (["--profile", opts["profile"]] if opts.get("profile") else []) + ["-p", port, "-r", rules]
        proxy_args += ["--web"] if web else []
        if dry:
            if proxy.run(proxy_args + ["--dry-run"]) != 0:
                return 1
        else:
            start_proxy(port, proxy_args)

    return open_browser(browser, exe, port, url, insecure, dry)


def start_proxy(port: str, proxy_args: list[str]):
    # Fail here with a clear message instead of in a window that closes right away
    if not find_mitmdump():
        fail(f"mitmdump not found. Run: {PROG} install")
    title = f"mitmproxy :{port}"
    info(f'Starting the proxy in a separate window "{title}"')
    open_window(title, [sys.executable, str(MAIN), "proxy", "run", *proxy_args])
    for _ in range(30):
        if port_owner(port)[0] != "free":
            return
        time.sleep(1)
    fail(f'The proxy did not start within 30 seconds, see the "{title}" window.')


def open_browser(browser: str, exe: str, port: str, url: str, insecure: bool, dry: bool) -> int:
    # A separate profile per browser+port pair: otherwise the flags are ignored if the browser is already open
    profile_dir = Path(tempfile.gettempdir()) / f"mitm-profile-{Path(browser).stem}-{port}"
    command = [
        exe,
        f"--user-data-dir={profile_dir}",
        f"--proxy-server=127.0.0.1:{port}",
        # removes the built-in localhost bypass, so a local dev server goes through the proxy too
        "--proxy-bypass-list=<-loopback>",
        # HTTP/3 runs over UDP and would skip the proxy
        "--disable-quic",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if not WINDOWS:
        # a new profile would otherwise ask to unlock the desktop keyring
        command.append("--password-store=basic")
    if insecure:
        command.append("--ignore-certificate-errors")
    command.append(url)

    info(f'Opening {browser} -> "{url}"')
    if dry:
        detail(show(command))
        return 0
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         **({} if WINDOWS else {"start_new_session": True}))
    except OSError as e:
        fail(f'Failed to start "{exe}": {e}', "Specify the full path to the browser: -b PATH")
    return 0


def find_browser(name: str) -> str | None:
    key = name.lower()
    if WINDOWS and key in WINDOWS_NAMES:
        exe, folders = WINDOWS_NAMES[key]
        return shutil.which(exe) or _app_path(exe) or _install_folder(exe, folders)
    if not WINDOWS and key in LINUX_NAMES:
        return next((p for p in map(shutil.which, LINUX_NAMES[key]) if p), None)
    if Path(name).is_file():
        return os.path.abspath(name)
    return shutil.which(name)


def _app_path(exe: str) -> str | None:
    """Where the installer registered the browser (what "start chrome" uses)."""
    import winreg
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}") as k:
                path = winreg.QueryValue(k, None).strip('"')
        except OSError:
            continue
        if path and Path(path).is_file():
            return path
    return None


def _install_folder(exe: str, folders: list[str]) -> str | None:
    for var in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        base = os.environ.get(var)
        for folder in folders:
            if base and (Path(base) / folder / exe).is_file():
                return str(Path(base) / folder / exe)
    return None
