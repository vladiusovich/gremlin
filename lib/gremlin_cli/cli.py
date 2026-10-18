"""Routes "gremlin <command> [options]" to the commands. Commands are case-insensitive."""
from __future__ import annotations

import sys

from . import browser, install, proxy, testing
from .common import PROG, Fail

HELP = f"""Usage:
  {PROG} browser run [URL] [-e profile] [-b {browser.BROWSERS.replace(', ', '|')}|path] [-p PORT] [-r rules.json] [-w] [-k] [--dry-run]
                      proxy (if not running yet) + browser
  {PROG} proxy run   [-e profile] [-p PORT] [-r rules.json] [-w] [-g] [--wg-port PORT] [--dry-run]
                      proxy only, in this console; -g adds WireGuard for phones
  {PROG} mobile run  [-e profile] [-p PORT] [-r rules.json] [--wg-port PORT] [--dry-run]
                      proxy + WireGuard for phones, QR code in mitmweb
  {PROG} install     [-y]
                      install mitmproxy and trust its certificate
  {PROG} test        [pytest options]"""


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    group = args[0].lower() if args else ""
    command = args[1].lower() if len(args) > 1 else ""
    try:
        if command == "run" and group in ("browser", "proxy", "mobile"):
            rest = args[2:]
            if group == "browser":
                return browser.run(rest)
            return proxy.run(rest, mobile=group == "mobile")
        if group == "install":
            return install.run(args[1:])
        if group == "test":
            return testing.run(args[1:])
        if group not in ("", "help", "-h", "--help"):
            print(f"[!!] Unknown command: gremlin {' '.join(args)}")
        print(HELP)
        return 1
    except Fail:
        return 1
    except KeyboardInterrupt:
        return 130
