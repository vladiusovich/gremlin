"""The gremlin commands: profiles, validation and command-line options, checked through --dry-run.

They run through the platform's entry point (gremlin.bat on Windows, gremlin on Linux) in a copy of
the project in a temp folder, so profiles/ and rules/ of the real checkout are never touched. Fake browser
executables on PATH stand in for Chrome and Edge, so the tests do not depend on what is installed.
"""
import os
import shutil
import socket
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "lib"))
from gremlin_cli.common import quote  # noqa: E402

WINDOWS = sys.platform == "win32"
ENTRY = "gremlin.bat" if WINDOWS else "gremlin"
FAKE_BROWSERS = {"chrome": "chrome.exe", "edge": "msedge.exe"} if WINDOWS else \
    {"chrome": "google-chrome", "edge": "microsoft-edge"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Project:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        for name in ("gremlin.bat", "gremlin", "install.bat", "install.sh"):
            shutil.copy(ROOT / name, root / name)
        shutil.copytree(ROOT / "lib", root / "lib", ignore=shutil.ignore_patterns("__pycache__"))
        self.extra_env: dict[str, str] = {}
        self.bin = root.parent / "fakebin"
        self.bin.mkdir()
        self.browsers = {}
        for key, name in FAKE_BROWSERS.items():
            exe = self.bin / name
            exe.write_text("")
            exe.chmod(0o755)
            self.browsers[key] = str(exe)
        (root / "profiles").mkdir()
        (root / "rules").mkdir()
        (root / "addons").mkdir()
        shutil.copy(ROOT / "addons" / "mock_errors.py", root / "addons")

    def profile(self, name: str, text: str):
        (self.root / "profiles" / f"{name}.env").write_text(text, encoding="ascii")

    def rules(self, name: str) -> Path:
        """An empty rules file rules/<name>.json (subfolders included); returns its path."""
        path = self.root / "rules" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[]", encoding="ascii")
        return path

    def run(self, *args: str):
        env = dict(os.environ)
        # mitmdump from the test venv, so the scripts find it without install.bat
        env["PATH"] = os.pathsep.join([str(Path(sys.executable).parent), str(self.bin), env.get("PATH", "")])
        env["PYTHONIOENCODING"] = "utf-8"
        for k in [k for k in env if k.upper().startswith("MITM_")]:
            del env[k]
        env.update(self.extra_env)
        r = subprocess.run([str(self.root / ENTRY), *args], cwd=self.root, env=env,
                           capture_output=True, timeout=60)
        out = (r.stdout + r.stderr).decode("utf-8", errors="replace")
        return r.returncode, out


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path / "gremlin")


def command_line(out: str) -> str:
    """The mitmdump command printed by "gremlin proxy run --dry-run"."""
    lines = [l.strip() for l in out.splitlines() if "mitm" in l.lower() and " -p " in l]
    assert lines, out
    return lines[-1]


# --- gremlin proxy run ---------------------------------------------------

def test_defaults(project):
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert "mitmdump" in cmd.lower()
    assert " -p 8080 " in cmd
    assert quote(f"rules_file={project.root / 'rules' / 'default.json'}") in cmd
    assert f"An empty {os.path.join('rules', 'default.json')} would be created" in out
    assert "--mode" not in cmd
    assert "WireGuard" not in out
    # --dry-run creates nothing
    assert not (project.root / "rules" / "default.json").exists()


def test_all_addons_loaded_except_underscored(project):
    (project.root / "addons" / "extra.py").write_text("addons = []\n")
    (project.root / "addons" / "_helper.py").write_text("")
    code, out = project.run("proxy", "run", "--dry-run")
    cmd = command_line(out)
    assert "mock_errors.py" in cmd
    assert "extra.py" in cmd
    assert "_helper.py" not in cmd


def test_default_profile_is_used(project):
    project.profile("default", "MITM_PORT=9001\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    assert "Profile:" in out and "default.env" in out
    assert " -p 9001 " in command_line(out)


def test_named_profile_and_relative_rules(project):
    (project.root / "rules" / "staging.json").write_text("[]")
    project.profile("staging", "# comment\nMITM_PORT=9002\nMITM_RULES=rules/staging.json\nMITM_WEB=yes\n")
    code, out = project.run("proxy", "run", "--profile", "staging", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9002 " in cmd
    assert "mitmweb" in cmd.lower()
    assert quote(f"rules_file={project.root / 'rules' / 'staging.json'}") in cmd


def test_command_line_overrides_profile(project):
    (project.root / "rules" / "other.json").write_text("[]")
    project.profile("default", "MITM_PORT=9001\n")
    code, out = project.run("proxy", "run", "-p", "9003", "-r", str(project.root / "rules" / "other.json"),
                            "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9003 " in cmd
    assert "other.json" in cmd


def test_missing_profile(project):
    code, out = project.run("proxy", "run", "--profile", "nope", "--dry-run")
    assert code == 1
    assert f"Profile not found: {os.path.join('profiles', 'nope.env')}" in out


@pytest.mark.parametrize("flag", ["--profile", "--PROFILE"])
def test_profile_option(project, flag):
    project.profile("staging", "MITM_PORT=9005\n")
    code, out = project.run("proxy", "run", flag, "staging", "--dry-run")
    assert code == 0, out
    assert " -p 9005 " in command_line(out)


def test_profile_uses_its_own_rules_file(project):
    project.profile("staging", "MITM_PORT=9006\n")
    code, out = project.run("proxy", "run", "--profile", "staging", "--dry-run")
    assert code == 0, out
    assert quote(f"rules_file={project.root / 'rules' / 'staging.json'}") in command_line(out)
    # missing: created empty, like the default one
    assert f"An empty {os.path.join('rules', 'staging.json')} would be created" in out


def test_default_profile_uses_default_rules_file(project):
    project.rules("default")
    project.profile("default", "MITM_PORT=9007\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    assert quote(f"rules_file={project.root / 'rules' / 'default.json'}") in command_line(out)
    assert "would be created" not in out


@pytest.mark.parametrize("name, parts", [("trade-errors", ("trade-errors.json",)),
                                         ("trade/errors", ("trade", "errors.json"))])
def test_rules_by_short_name(project, name, parts):
    project.rules(name)
    code, out = project.run("proxy", "run", "-r", name, "--dry-run")
    assert code == 0, out
    assert quote(f"rules_file={project.root.joinpath('rules', *parts)}") in command_line(out)


def test_rules_by_short_name_in_profile(project):
    project.rules("trade-errors")
    project.profile("staging", "MITM_RULES=trade-errors\n")
    code, out = project.run("proxy", "run", "--profile", "staging", "--dry-run")
    assert code == 0, out
    assert quote(f"rules_file={project.root / 'rules' / 'trade-errors.json'}") in command_line(out)


def test_missing_rules_by_short_name(project):
    # a short name that is not the profile's own file must exist: a typo is not created silently
    code, out = project.run("proxy", "run", "-r", "trade-erors", "--dry-run")
    assert code == 1
    assert "Rules file not found:" in out and os.path.join("rules", "trade-erors.json") in out


def test_missing_non_default_rules_file(project):
    project.profile("p", "MITM_RULES=rules/missing.json\n")
    code, out = project.run("proxy", "run", "--profile", "p", "--dry-run")
    assert code == 1
    assert "Rules file not found:" in out and "missing.json" in out


def test_unknown_profile_key_warns(project):
    project.profile("default", "MITM_PROT=1\nPATH=/nothing\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    assert '[warn]' in out and 'unknown key "MITM_PROT" skipped' in out
    assert 'unknown key "PATH" skipped' in out
    # PATH was not clobbered: mitmdump is still found
    assert "mitmdump" in command_line(out).lower()


@pytest.mark.parametrize("port", ["0", "65536", "abc", "080", "123456", "-1"])
def test_invalid_port(project, port):
    code, out = project.run("proxy", "run", "-p", port, "--dry-run")
    assert code == 1
    assert f'Invalid port "{port}"' in out


@pytest.mark.parametrize("port", ["1", "8080", "65535"])
def test_valid_port(project, port):
    code, out = project.run("proxy", "run", "-p", port, "--dry-run")
    assert code == 0, out
    assert f" -p {port} " in command_line(out)


@pytest.mark.parametrize("value, ok", [("1", True), ("off", True), ("TRUE", True), ("maybe", False), ("2", False)])
def test_bool_validation(project, value, ok):
    project.profile("default", f"MITM_WEB={value}\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert (code == 0) == ok, out
    if not ok:
        assert f'Invalid value MITM_WEB="{value}"' in out


def test_unknown_option(project):
    code, out = project.run("proxy", "run", "--bogus")
    assert code == 1
    assert "Unknown option: --bogus" in out


# --- WireGuard: gremlin proxy run -g / gremlin mobile run -------------------

@pytest.mark.parametrize("flag", ["-g", "--wireguard"])
def test_wireguard_option(project, flag):
    code, out = project.run("proxy", "run", flag, "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    # the regular proxy keeps its port, WireGuard gets its own
    assert " -p 8080 --mode regular --mode wireguard@51820 " in cmd
    assert "mitmdump" in cmd.lower()
    assert "WireGuard for phones on UDP port 51820" in out
    assert "add -w to get it as a QR code" in out
    assert ("localport=51820" if WINDOWS else "sudo ufw allow 51820/udp") in out


def test_mobile_run_is_wireguard_in_mitmweb(project):
    code, out = project.run("mobile", "run", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert "mitmweb" in cmd.lower()
    assert " --mode regular --mode wireguard@51820 " in cmd
    assert "Capture tab" in out


def test_mobile_run_options(project):
    (project.root / "rules" / "mobile.json").write_text("[]")
    code, out = project.run("Mobile", "Run", "-p", "9010", "--wg-port", "51999",
                            "-r", str(project.root / "rules" / "mobile.json"), "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9010 --mode regular --mode wireguard@51999 " in cmd
    assert "mobile.json" in cmd


def test_wireguard_from_profile_and_override(project):
    project.profile("default", "MITM_WIREGUARD=yes\nMITM_WG_PORT=51900\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    assert " --mode wireguard@51900 " in command_line(out)
    code, out = project.run("proxy", "run", "--wg-port", "51901", "--dry-run")
    assert code == 0, out
    assert " --mode wireguard@51901 " in command_line(out)


def test_wg_port_ignored_without_wireguard(project):
    project.profile("default", "MITM_WG_PORT=51900\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 0, out
    assert "--mode" not in command_line(out)


@pytest.mark.parametrize("port", ["0", "abc", "70000"])
def test_invalid_wg_port(project, port):
    code, out = project.run("mobile", "run", "--wg-port", port, "--dry-run")
    assert code == 1
    assert f'Invalid port "{port}"' in out
    assert "--wg-port or MITM_WG_PORT" in out


def test_invalid_wireguard_value(project):
    project.profile("default", "MITM_WIREGUARD=maybe\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 1
    assert 'Invalid value MITM_WIREGUARD="maybe"' in out


def test_browser_starts_proxy_with_wireguard_from_profile(project):
    # gremlin browser run passes the profile on, so the proxy it starts gets WireGuard too
    project.profile("default", "MITM_WIREGUARD=1\n")
    port = free_port()
    code, out = project.run("browser", "run", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert f" -p {port} --mode regular --mode wireguard@51820 " in command_line(out)
    assert f"--proxy-server=127.0.0.1:{port}" in browser_line(out)


# --- gremlin browser run ------------------------------------------------

def browser_line(out: str) -> str:
    lines = [l.strip() for l in out.splitlines() if "--proxy-server=" in l]
    assert lines, out
    return lines[-1]


def test_browser_defaults(project):
    port = free_port()
    code, out = project.run("browser", "run", "-p", str(port), "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith(quote(project.browsers["chrome"]) + " ")
    assert f"--proxy-server=127.0.0.1:{port}" in line
    assert quote("--proxy-bypass-list=<-loopback>") in line
    assert "--disable-quic" in line
    assert f"mitm-profile-chrome-{port}" in line
    assert line.endswith(" " + quote("http://localhost:3001/"))
    assert "--ignore-certificate-errors" not in line
    # the proxy is not running yet, so gremlin proxy run is called with the same port
    assert f" -p {port} " in command_line(out)


def test_browser_profile_and_options(project):
    port = free_port()
    project.profile("default", f"MITM_URL=https://app.example.com/\nMITM_BROWSER=edge\nMITM_PORT={port}\n"
                               "MITM_INSECURE=1\nMITM_WEB=1\n")
    code, out = project.run("browser", "run", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith(quote(project.browsers["edge"]) + " ")
    assert "--ignore-certificate-errors" in line
    assert line.endswith(" " + quote("https://app.example.com/"))
    assert "mitmweb" in command_line(out).lower()


def test_browser_url_argument_overrides_profile(project):
    project.profile("default", "MITM_URL=https://app.example.com/\n")
    code, out = project.run("browser", "run", "https://other.example.com/x", "-p", str(free_port()),
                            "-k", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.endswith(" " + quote("https://other.example.com/x"))
    assert "--ignore-certificate-errors" in line


def test_browser_url_with_special_characters_from_profile(project):
    # the profile is the shell-independent way to pass & and %20 (see README, Consoles)
    project.profile("default", "MITM_URL=https://app.example.com/a%20b?x=1&y=2\n")
    code, out = project.run("browser", "run", "-p", str(free_port()), "--dry-run")
    assert code == 0, out
    assert browser_line(out).endswith(" " + quote("https://app.example.com/a%20b?x=1&y=2"))


def test_browser_invalid_url(project):
    code, out = project.run("browser", "run", "app.example.com", "--dry-run")
    assert code == 1
    assert 'Invalid URL "app.example.com"' in out


def test_browser_not_found(project):
    code, out = project.run("browser", "run", "-b", str(project.root / "nope" / "browser"), "--dry-run")
    assert code == 1
    assert "not found" in out


class Listener:
    """A process listening on a free port, with "rules_file=..." in its command line like the gremlin proxy."""

    def __init__(self, rules: str | None):
        code = textwrap.dedent("""
            import socket, sys, time
            s = socket.socket()
            s.bind(("127.0.0.1", 0))
            s.listen()
            print(s.getsockname()[1], flush=True)
            time.sleep(120)
        """)
        args = [sys.executable, "-c", code] + (["--set", f"rules_file={rules}"] if rules else [])
        self.proc = subprocess.Popen(args, stdout=subprocess.PIPE, text=True)
        self.port = int(self.proc.stdout.readline())

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.proc.kill()
        self.proc.wait()


def test_browser_reuses_proxy_with_the_same_rules(project):
    with Listener(str(project.root / "rules" / "default.json")) as proxy:
        code, out = project.run("browser", "run", "-p", str(proxy.port), "--dry-run")
    assert code == 0, out
    assert f"Proxy is already listening on port {proxy.port}" in out
    assert "mitmdump" not in out.lower()
    assert f"--proxy-server=127.0.0.1:{proxy.port}" in browser_line(out)


def test_browser_refuses_proxy_with_other_rules(project):
    # the profile asks for other rules than the running proxy has: reusing it would silently apply the wrong ones
    (project.root / "rules" / "staging.json").write_text("[]")
    project.profile("staging", "")
    with Listener(str(project.root / "rules" / "default.json")) as proxy:
        code, out = project.run("browser", "run", "--profile", "staging", "-p", str(proxy.port), "--dry-run")
    assert code == 1, out
    assert f"A proxy with other rules is already running on port {proxy.port}" in out
    assert "default.json" in out and "staging.json" in out
    assert "--proxy-server=" not in out


def test_browser_refuses_port_of_another_program(project):
    with Listener(None) as other:
        code, out = project.run("browser", "run", "-p", str(other.port), "--dry-run")
    assert code == 1, out
    assert f"Port {other.port} is used by python" in out
    assert "--proxy-server=" not in out


def test_browser_unknown_option(project):
    code, out = project.run("browser", "run", "--bogus")
    assert code == 1
    assert "Unknown option: --bogus" in out


# --- gremlin dispatcher -----------------------------------------------------

@pytest.mark.parametrize("args", [(), ("help",), ("--help",)])
def test_gremlin_help(project, args):
    code, out = project.run(*args)
    assert code == 1
    assert all(c in out for c in ("gremlin browser run", "gremlin proxy run", "gremlin mobile run",
                                  "gremlin install", "gremlin test"))
    assert "gremlin run" not in out and "phone run" not in out


@pytest.mark.parametrize("args", [("proxy",), ("proxy", "stop"), ("mobile",), ("run",), ("phone", "run"), ("nope",)])
def test_gremlin_unknown_command(project, args):
    code, out = project.run(*args)
    assert code == 1
    assert "Unknown command: gremlin " + " ".join(args) in out


def test_gremlin_commands_are_case_insensitive(project):
    code, out = project.run("Proxy", "RUN", "-p", "9004", "--dry-run")
    assert code == 0, out
    assert " -p 9004 " in command_line(out)


def test_gremlin_passes_quoted_arguments_unchanged(project):
    # spaces, % and & inside a quoted argument survive the extra hop through gremlin.bat / gremlin;
    # the space also makes subprocess quote the URL, as a user would in cmd
    (project.root / "rules" / "my rules.json").write_text("[]", encoding="ascii")
    code, out = project.run("browser", "run", "https://app.example.com/a%20b c?x=1&y=2",
                            "-r", str(project.root / "rules" / "my rules.json"),
                            "-p", str(free_port()), "--dry-run")
    assert code == 0, out
    assert quote("https://app.example.com/a%20b c?x=1&y=2") in browser_line(out)
    assert "my rules.json" in command_line(out)


def test_gremlin_install_passes_options_on(project):
    # install goes through install.bat / install.sh (they work without Python), then to the Python part
    code, out = project.run("Install", "--bogus")
    assert code == 1
    assert "[ok] Python:" in out
    assert "Unknown option: --bogus" in out


@pytest.mark.skipif(WINDOWS, reason="Linux: the proxy window is a terminal emulator of the desktop session")
def test_browser_without_a_graphical_session(project):
    # nothing listens on the port, so the proxy would be started in a new terminal window: there is none
    project.extra_env = {"DISPLAY": "", "WAYLAND_DISPLAY": ""}
    code, out = project.run("browser", "run", "-p", str(free_port()))
    assert code == 1, out
    assert "No graphical session" in out
    assert "./gremlin proxy run" in out
