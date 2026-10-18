"""What listens on a TCP port: nothing, a gremlin proxy (with which rules file) or another program.

Checks the listening sockets rather than connecting to the port: a connect also fails when the
program on the port is busy or frozen, and the port would be reported free. A gremlin proxy is
recognized by the --set rules_file=... in its command line (see proxy.py).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .common import ROOT, WINDOWS


def port_owner(port: str, rules: str | None = None) -> tuple[str, str]:
    """Returns (kind, details). Kind: "free", "busy" (only without `rules`), "same" (a gremlin proxy
    with `rules`), "other-rules" (details: its rules file) or "other" (details: the program)."""
    return _windows(port, rules) if WINDOWS else _linux(int(port), rules)


def _windows(port: str, rules: str | None) -> tuple[str, str]:
    command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(ROOT / "lib" / "port-owner.ps1"), "-Port", port]
    if rules:
        command += ["-Rules", rules]
    r = subprocess.run(command, capture_output=True, text=True)
    kind, _, details = r.stdout.strip().partition(" ")
    return (kind or "free"), details


def _linux(port: int, rules: str | None) -> tuple[str, str]:
    inodes = _listening_inodes(port)
    if not inodes:
        return "free", ""
    if not rules:
        return "busy", ""
    pid = _socket_owner(inodes)
    if pid is None:
        # The socket belongs to another user's process, /proc does not tell whose
        return "other", "an unknown process"
    proc = Path("/proc") / str(pid)
    try:
        args = [a.decode(errors="replace") for a in (proc / "cmdline").read_bytes().split(b"\0")]
        name = (proc / "comm").read_text().strip()
    except OSError:
        return "other", "an unknown process"
    running = next((a[len("rules_file="):] for a in args if a.startswith("rules_file=")), None)
    if running is None:
        return "other", f"{name} (PID {pid})"
    same = os.path.realpath(running) == os.path.realpath(rules)
    return ("same", "") if same else ("other-rules", running)


def _listening_inodes(port: int) -> set[str]:
    inodes = set()
    for table in ("tcp", "tcp6"):
        try:
            lines = Path("/proc/net", table).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            # local_address is HEXIP:HEXPORT, state 0A is LISTEN
            if len(fields) > 9 and fields[3] == "0A" and int(fields[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(fields[9])
    return inodes


def _socket_owner(inodes: set[str]) -> int | None:
    targets = {f"socket:[{inode}]" for inode in inodes}
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                try:
                    if os.readlink(fd) in targets:
                        return int(proc.name)
                except OSError:
                    pass
        except OSError:
            continue
    return None
