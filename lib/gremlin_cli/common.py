"""Shared helpers of the gremlin commands: output, options, validation, finding programs."""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "lib" / "main.py"
WINDOWS = sys.platform == "win32"
# How the user calls gremlin in messages: Linux shells never run programs from the current folder by name
PROG = "gremlin" if WINDOWS else "./gremlin"
BOOL_VALUES = ("1", "0", "true", "false", "yes", "no", "on", "off")


class Fail(Exception):
    """An error that was already explained to the user: the command exits with code 1."""


def ok(msg: str):
    print(f"[ok] {msg}", flush=True)


def info(msg: str):
    print(f"[..] {msg}", flush=True)


def warn(msg: str):
    print(f"[warn] {msg}", flush=True)


def detail(msg: str):
    print(f"     {msg}", flush=True)


def fail(msg: str, *details: str) -> NoReturn:
    print(f"[!!] {msg}", flush=True)
    for d in details:
        detail(d)
    raise Fail(msg)


def rel(*parts: str) -> str:
    """A path inside the project, as shown in messages: rules\\default.json on Windows, rules/default.json elsewhere."""
    return os.path.join(*parts)


# cmd.exe treats these as special even inside an argument, so such arguments are shown in quotes
_CMD_SPECIAL = re.compile(r'[\s"&<>|^%()!]')


def quote(arg: str) -> str:
    if WINDOWS:
        return f'"{arg}"' if not arg or _CMD_SPECIAL.search(arg) else arg
    return shlex.quote(arg)


def show(args) -> str:
    """A command line the way a user would type it in this platform's console."""
    return " ".join(quote(str(a)) for a in args)


def is_on(value: str | None) -> bool:
    return (value or "").lower() in ("1", "true", "yes", "on")


def validate_port(value: str, where: str = "-p or MITM_PORT"):
    if not re.fullmatch(r"[1-9][0-9]{0,4}", value) or int(value) > 65535:
        fail(f'Invalid port "{value}": must be a number 1-65535 (option {where} in the profile)')


def validate_bool(name: str, value: str | None):
    if value and value.lower() not in BOOL_VALUES:
        fail(f'Invalid value {name}="{value}": must be 1 or 0 (or true/false, yes/no, on/off)')


def parse_options(args: list[str], options: dict[str, tuple[str, bool]], usage: str,
                  positional: str | None = None) -> dict[str, str | bool]:
    """Parses `args` by `options` ({"-p": ("port", True), "-w": ("web", False)}, True = takes a value).

    Options are case-insensitive, like in the batch scripts this replaced. A bare argument is stored
    under `positional` (the last one wins); without `positional` it is an unknown option.
    """
    result: dict[str, str | bool] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        spec = options.get(arg.lower())
        if arg.lower() in ("-h", "--help"):
            print(usage)
            raise Fail("help")
        if spec is None:
            if positional is None or arg.startswith("-"):
                print(f"[!!] Unknown option: {arg}")
                print(usage)
                raise Fail(arg)
            result[positional] = arg
        elif spec[1]:
            if i + 1 >= len(args):
                print(f"[!!] Option {arg} needs a value")
                print(usage)
                raise Fail(arg)
            i += 1
            result[spec[0]] = args[i]
        else:
            result[spec[0]] = True
        i += 1
    return result


def ask(question: str, assume_yes: bool = False) -> bool:
    """Asks a yes/no question; Enter means yes. Without a console to answer in, the answer is no."""
    if assume_yes:
        print(f"[??] {question} [Y/n] y (-y)", flush=True)
        return True
    if not sys.stdin or not sys.stdin.isatty():
        print(f"[??] {question} [Y/n] n (no console to answer in: run with -y to agree)", flush=True)
        return False
    while True:
        try:
            answer = input(f"[??] {question} [Y/n] ").strip().lower()
        except EOFError:
            return False
        if answer in ("", "y", "yes"):
            return True
        if answer in ("n", "no"):
            return False


def data_dir() -> Path:
    """Where gremlin keeps what it installs itself (the mitmproxy virtual environment)."""
    if WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "gremlin"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "gremlin"


MITMPROXY_VENV = data_dir() / "mitmproxy"


def venv_bin(venv: Path) -> Path:
    return venv / ("Scripts" if WINDOWS else "bin")


def venv_python(venv: Path) -> Path:
    return venv_bin(venv) / ("python.exe" if WINDOWS else "python")


def exe_name(name: str) -> str:
    return f"{name}.exe" if WINDOWS else name


def find_mitmdump() -> str | None:
    """mitmdump on PATH, or where the installers put it while PATH in this console may be stale."""
    found = shutil.which("mitmdump")
    if found:
        return found
    dirs = []
    if WINDOWS:
        for var in ("ProgramFiles", "LOCALAPPDATA"):
            base = os.environ.get(var)
            if base:
                dirs.append(Path(base) / ("Programs" if var == "LOCALAPPDATA" else "") / "mitmproxy" / "bin")
    else:
        dirs.append(Path.home() / ".local" / "bin")  # pipx and pip --user
    # pip install into the Python running gremlin, globally or with --user
    for scheme in (None, f"{os.name}_user"):
        try:
            dirs.append(Path(sysconfig.get_path("scripts", scheme) if scheme else sysconfig.get_path("scripts")))
        except KeyError:
            pass
    dirs.append(venv_bin(MITMPROXY_VENV))  # gremlin install without winget / pipx
    for d in dirs:
        exe = d / exe_name("mitmdump")
        if exe.is_file():
            return str(exe)
    return None


def create_venv(venv: Path, assume_yes: bool = False) -> bool:
    """Creates a virtual environment; on Debian/Ubuntu offers to install python3-venv if it is missing."""
    for attempt in (1, 2):
        r = subprocess.run([sys.executable, "-m", "venv", str(venv)], capture_output=True, text=True)
        if r.returncode == 0:
            return True
        shutil.rmtree(venv, ignore_errors=True)
        if attempt == 1 and not WINDOWS and "ensurepip" in (r.stdout + r.stderr):
            if install_packages({"apt-get": "python3-venv"}, "Python cannot create virtual environments "
                                "without the python3-venv package.", assume_yes):
                continue
        print((r.stdout + r.stderr).strip())
        print(f"[!!] Failed to create a virtual environment in {venv}", flush=True)
        return False
    return False


PACKAGE_MANAGERS = (
    ("apt-get", ["apt-get", "install", "-y"]),
    ("dnf", ["dnf", "install", "-y"]),
    ("pacman", ["pacman", "-S", "--needed", "--noconfirm"]),
    ("zypper", ["zypper", "install", "-y"]),
)


def install_packages(packages: dict[str, str], why: str, assume_yes: bool = False) -> bool:
    """Installs Linux packages with the system package manager, after asking. `packages`: manager -> names."""
    for manager, command in PACKAGE_MANAGERS:
        if manager in packages and shutil.which(manager):
            break
    else:
        info(why)
        detail("Install it with your package manager: " + ", ".join(f"{m}: {p}" for m, p in packages.items()))
        return False
    sudo = [] if os.geteuid() == 0 else ["sudo"]
    full = sudo + command + packages[manager].split()
    # apt needs a fresh package list first: on a new system (e.g. WSL) it is empty
    update = sudo + ["apt-get", "update"] if manager == "apt-get" else None
    info(why)
    shown = f"{show(update)} && {show(full)}" if update else show(full)
    if not ask(f"Install it now with: {shown}?", assume_yes):
        return False
    if update and subprocess.call(update) != 0:
        return False
    return subprocess.call(full) == 0
