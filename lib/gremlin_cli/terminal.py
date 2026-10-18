"""Running a command in a new console / terminal window, for the proxy started by gremlin browser run."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .common import PROG, WINDOWS, fail, quote

# Seconds a terminal emulator gets to fail before it counts as started
TERMINAL_STARTUP = 1.5

# Keeps a Linux terminal window open when the command fails, so its errors can be read
# (cmd /k does the same on Windows). After Ctrl+C or a normal exit the window closes.
HOLD = ('"$@" || { code=$?; echo; echo "[!!] Exited with code $code. Press Enter to close this window."; '
        'read _; }')

# Terminal emulators and how each one takes the command to run: the arguments go after these
TERMINALS = (
    ("gnome-terminal", ["--"]),
    ("ptyxis", ["--"]),
    ("konsole", ["-e"]),
    ("xfce4-terminal", ["-x"]),
    ("kgx", ["--"]),
    ("kitty", []),
    ("alacritty", ["-e"]),
    ("wezterm", ["start", "--"]),
    ("foot", []),
    ("x-terminal-emulator", ["-e"]),
    ("xterm", ["-e"]),
)


def open_window(title: str, args: list[str]):
    if WINDOWS:
        # cmd /k keeps the window open, so startup errors stay visible. The outer quotes are
        # stripped by cmd, everything inside stays quoted.
        inner = " ".join(quote(a) for a in args)
        subprocess.Popen(f'cmd.exe /k "title {title} & {inner}"', creationflags=subprocess.CREATE_NEW_CONSOLE)
        return

    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        fail("No graphical session to open the proxy window in.",
             f"Start the proxy in another terminal first: {PROG} proxy run (with the same -e / -p / -r),",
             "then run this command again: it finds the running proxy and only opens the browser.")
    held = ["sh", "-c", HOLD, "gremlin", *args]
    candidates = []
    if os.environ.get("TERMINAL"):
        candidates.append((os.environ["TERMINAL"], ["-e"]))
    candidates += TERMINALS
    failed = []
    for name, prefix in candidates:
        exe = shutil.which(name)
        if not exe:
            continue
        error = _launch([exe, *prefix, *held])
        if error is None:
            return
        failed.append(f"{name}: {error}")
    if failed:
        fail("No terminal emulator could open the proxy window:", *failed,
             "Set the TERMINAL environment variable to a working one (called as $TERMINAL -e COMMAND),",
             f"or start the proxy in another terminal first: {PROG} proxy run (with the same -e / -p / -r).")
    fail("No terminal emulator found to open the proxy window in. Tried: "
         + ", ".join(name for name, _ in TERMINALS),
         "Set the TERMINAL environment variable to yours (it is called as $TERMINAL -e COMMAND),",
         f"or start the proxy in another terminal first: {PROG} proxy run (with the same -e / -p / -r).")


def _launch(command: list[str]) -> str | None:
    """Starts a terminal; returns why it failed, or None if it is running (or handed the window over)."""
    with tempfile.TemporaryFile() as log:
        try:
            proc = subprocess.Popen(command, start_new_session=True, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=log)
        except OSError as e:
            return str(e)
        try:
            # A terminal that cannot start (no display, a missing font, …) exits within a moment.
            # Exit code 0 is fine: gnome-terminal hands the window to its server and exits.
            code = proc.wait(TERMINAL_STARTUP)
        except subprocess.TimeoutExpired:
            return None
        if code == 0:
            return None
        log.seek(0)
        lines = [l for l in log.read().decode(errors="replace").splitlines() if l.strip()]
    return f"exited with code {code}" + (f": {lines[-1].strip()}" if lines else "")
