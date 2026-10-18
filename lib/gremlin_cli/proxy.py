"""gremlin proxy run / gremlin mobile run: mitmproxy with every addon from addons/, in the current console."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from . import profile
from .common import (PROG, ROOT, WINDOWS, detail, exe_name, fail, find_mitmdump, info, is_on,
                     ok, parse_options, rel, show, validate_bool, validate_port)

USAGE = f"Usage: {PROG} proxy run [--profile NAME] [-p PORT] [-r RULES] [-w] [-g] [--wg-port PORT] [--dry-run]"
MOBILE_USAGE = f"Usage: {PROG} mobile run [--profile NAME] [-p PORT] [-r RULES] [--wg-port PORT] [--dry-run]"

OPTIONS = {
    # -e / --env: the old name of --profile, still accepted
    "--profile": ("profile", True), "-e": ("profile", True), "--env": ("profile", True),
    "-p": ("port", True), "--port": ("port", True),
    "-r": ("rules", True), "--rules": ("rules", True),
    "-w": ("web", False), "--web": ("web", False),
    "-g": ("wireguard", False), "--wireguard": ("wireguard", False),
    "--wg-port": ("wg_port", True),
    "--dry-run": ("dry", False),
}


def run(args: list[str], mobile: bool = False) -> int:
    """Starts mitmdump (or mitmweb) and returns its exit code. Stop it with Ctrl+C.

    Priority: command line > profile > built-in default. Every addons/*.py is loaded, files starting
    with "_" are skipped (shared helpers). `mobile` = gremlin mobile run: WireGuard in mitmweb.
    WireGuard keys are kept in ~/.mitmproxy/wireguard.conf, so a phone set up once keeps working
    across restarts. The regular proxy keeps listening on the port next to it.
    """
    opts = parse_options(args, OPTIONS, MOBILE_USAGE if mobile else USAGE)
    settings, profile_file = profile.load(opts.get("profile"))
    if profile_file:
        ok(f"Profile: {profile_file}")

    port = opts.get("port") or settings.get("MITM_PORT") or "8080"
    rules = profile.rules_for(opts.get("rules"), settings, profile_file)
    web = mobile or bool(opts.get("web")) or is_on(settings.get("MITM_WEB"))
    wireguard = mobile or bool(opts.get("wireguard")) or is_on(settings.get("MITM_WIREGUARD"))
    wg_port = opts.get("wg_port") or settings.get("MITM_WG_PORT") or "51820"
    dry = bool(opts.get("dry"))

    validate_port(port)
    validate_bool("MITM_WEB", settings.get("MITM_WEB"))
    validate_bool("MITM_WIREGUARD", settings.get("MITM_WIREGUARD"))
    if wireguard:
        validate_port(wg_port, "--wg-port or MITM_WG_PORT")

    mitmdump = find_mitmdump()
    if not mitmdump:
        fail(f"mitmdump not found. Run: {PROG} install")
    tool = mitmdump
    if web:
        # mitmweb ships next to mitmdump
        tool = str(Path(mitmdump).with_name(exe_name("mitmweb")))
        if not Path(tool).is_file():
            fail(f"mitmweb not found next to {mitmdump}. Reinstall mitmproxy: {PROG} install")

    if not Path(rules).exists():
        own = profile.own_rules_file(profile_file)
        if os.path.normcase(rules) != os.path.normcase(str(own)):
            fail(f"Rules file not found: {rules}")
        # The profile's own rules file is personal and not in git: start with an empty rule set
        shown = rel("rules", own.name)
        if dry:
            info(f"An empty {shown} would be created")
        else:
            own.write_text("[]\n", encoding="utf-8")
            ok(f"Created an empty {shown}, example rules: {rel('rules', 'examples.json')}")

    addons = sorted(p for p in (ROOT / "addons").glob("*.py") if not p.name.startswith("_"))
    command = [tool, "-p", port]
    if wireguard:
        # -p applies to the regular mode, the WireGuard mode has its own port
        command += ["--mode", "regular", "--mode", f"wireguard@{wg_port}"]
    for addon in addons:
        command += ["-s", str(addon)]
    # gremlin browser run recognizes its proxy by this option in the process command line
    command += ["--set", f"rules_file={rules}"]

    info(f"Proxy 127.0.0.1:{port}, rules: {rules}")
    if wireguard:
        phone_help(wg_port, web)
    if dry:
        detail(show(command))
        return 0
    set_title(f"mitmproxy :{port}")
    return run_tool(command)


def phone_help(wg_port: str, web: bool):
    info(f"WireGuard for phones on UDP port {wg_port}. On the phone, once:")
    detail("1. Install the WireGuard app and add a tunnel from the QR code:")
    if web:
        detail("   mitmweb opens in the browser: Capture tab, WireGuard section.")
    else:
        detail("   the client config is printed below; add -w to get it as a QR code in mitmweb.")
    detail("2. Turn the tunnel on, open http://mitm.it and install the certificate (README: Phones).")
    if WINDOWS:
        detail(f"Phone cannot connect? Allow UDP {wg_port} in Windows Firewall (admin console):")
        detail(f'  netsh advfirewall firewall add rule name="gremlin WireGuard" dir=in action=allow '
               f'protocol=UDP localport={wg_port}')
    else:
        detail(f"Phone cannot connect? If a firewall is on, allow UDP {wg_port}:")
        detail(f"  sudo ufw allow {wg_port}/udp    (or: sudo firewall-cmd --add-port={wg_port}/udp)")


def set_title(title: str):
    """The console window title, so the proxy window is easy to find."""
    if WINDOWS:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(title)
    elif sys.stdout.isatty():
        sys.stdout.write(f"\033]0;{title}\007")
        sys.stdout.flush()


def run_tool(command: list[str]) -> int:
    if not WINDOWS:
        # Replace this process: Ctrl+C and the exit code go straight to mitmproxy
        sys.stdout.flush()
        os.execv(command[0], command)
    # Windows has no real exec. Ctrl+C reaches mitmproxy too (same console), so wait for it to shut down.
    proc = subprocess.Popen(command)
    while True:
        try:
            return proc.wait()
        except KeyboardInterrupt:
            continue
