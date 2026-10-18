"""Batch scripts: profiles, validation and command-line options, checked through --dry-run.

The scripts run in a copy of the project in a temp folder, so env/ and rules/ of the
real checkout are never touched.
"""
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import ROOT

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="batch scripts are Windows-only")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Project:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir()
        shutil.copy(ROOT / "gremlin.bat", root / "gremlin.bat")
        shutil.copytree(ROOT / "commands", root / "commands")
        shutil.copytree(ROOT / "lib", root / "lib")
        (root / "env").mkdir()
        (root / "rules").mkdir()
        (root / "addons").mkdir()
        shutil.copy(ROOT / "addons" / "mock_errors.py", root / "addons")

    def profile(self, name: str, text: str):
        (self.root / "env" / f"{name}.env").write_text(text, encoding="ascii")

    def run(self, *args: str):
        env = dict(os.environ)
        # mitmdump from the test venv, so the scripts find it without install.bat
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        for k in [k for k in env if k.upper().startswith("MITM_")]:
            del env[k]
        r = subprocess.run([str(self.root / "gremlin.bat"), *args], cwd=self.root, env=env,
                           capture_output=True, timeout=60)
        out = (r.stdout + r.stderr).decode("cp866", errors="replace")
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
    assert f'rules_file={project.root}\\rules\\rules.json' in cmd
    assert "An empty rules\\rules.json would be created" in out
    assert "--mode" not in cmd
    assert "WireGuard" not in out
    # --dry-run creates nothing
    assert not (project.root / "rules" / "rules.json").exists()


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
    code, out = project.run("proxy", "run", "-e", "staging", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9002 " in cmd
    assert "mitmweb" in cmd.lower()
    assert f"rules_file={project.root}\\rules\\staging.json" in cmd


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
    code, out = project.run("proxy", "run", "-e", "nope", "--dry-run")
    assert code == 1
    assert "Profile not found: env\\nope.env" in out


def test_missing_non_default_rules_file(project):
    project.profile("p", "MITM_RULES=rules/missing.json\n")
    code, out = project.run("proxy", "run", "-e", "p", "--dry-run")
    assert code == 1
    assert "Rules file not found:" in out and "missing.json" in out


def test_unknown_profile_key_warns(project):
    project.profile("default", "MITM_PROT=1\nPATH=C:\\nothing\n")
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


# --- WireGuard: gremlin proxy run -g / gremlin phone run --------------------

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
    assert "localport=51820" in out


def test_phone_run_is_wireguard_in_mitmweb(project):
    code, out = project.run("phone", "run", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert "mitmweb" in cmd.lower()
    assert " --mode regular --mode wireguard@51820 " in cmd
    assert "Capture tab" in out


def test_phone_run_options(project):
    (project.root / "rules" / "mobile.json").write_text("[]")
    code, out = project.run("Phone", "Run", "-p", "9010", "--wg-port", "51999",
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
    code, out = project.run("phone", "run", "--wg-port", port, "--dry-run")
    assert code == 1
    assert f'Invalid port "{port}"' in out
    assert "--wg-port or MITM_WG_PORT" in out


def test_invalid_wireguard_value(project):
    project.profile("default", "MITM_WIREGUARD=maybe\n")
    code, out = project.run("proxy", "run", "--dry-run")
    assert code == 1
    assert 'Invalid value MITM_WIREGUARD="maybe"' in out


def test_run_starts_proxy_with_wireguard_from_profile(project):
    # gremlin run passes the profile on, so the proxy it starts gets WireGuard too
    project.profile("default", "MITM_WIREGUARD=1\n")
    port = free_port()
    code, out = project.run("run", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert f" -p {port} --mode regular --mode wireguard@51820 " in command_line(out)
    assert f"--proxy-server=127.0.0.1:{port}" in browser_line(out)


# --- gremlin run / gremlin browser run -----------------------------------

def browser_line(out: str) -> str:
    lines = [l.strip() for l in out.splitlines() if "--proxy-server=" in l]
    assert lines, out
    return lines[-1]


def test_browser_defaults(project):
    port = free_port()
    code, out = project.run("run", "-p", str(port), "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith("chrome ")
    assert f"--proxy-server=127.0.0.1:{port}" in line
    assert '--proxy-bypass-list="<-loopback>"' in line
    assert "--disable-quic" in line
    assert f"mitm-profile-chrome-{port}" in line
    assert line.endswith('"http://localhost:3001/"')
    assert "--ignore-certificate-errors" not in line
    # the proxy is not running yet, so proxy-run.bat is called with the same port
    assert f" -p {port} " in command_line(out)


def test_browser_profile_and_options(project):
    port = free_port()
    project.profile("default", f"MITM_URL=https://app.example.com/\nMITM_BROWSER=edge\nMITM_PORT={port}\n"
                               "MITM_INSECURE=1\nMITM_WEB=1\n")
    code, out = project.run("run", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith("msedge ")
    assert "--ignore-certificate-errors" in line
    assert line.endswith('"https://app.example.com/"')
    assert "mitmweb" in command_line(out).lower()


def test_browser_url_argument_overrides_profile(project):
    project.profile("default", "MITM_URL=https://app.example.com/\n")
    code, out = project.run("run", "https://other.example.com/x", "-p", str(free_port()),
                            "-k", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.endswith('"https://other.example.com/x"')
    assert "--ignore-certificate-errors" in line


def test_browser_url_with_special_characters_from_profile(project):
    # the profile is the shell-independent way to pass & and %20 (see README, Consoles)
    project.profile("default", "MITM_URL=https://app.example.com/a%20b?x=1&y=2\n")
    code, out = project.run("run", "-p", str(free_port()), "--dry-run")
    assert code == 0, out
    assert browser_line(out).endswith('"https://app.example.com/a%20b?x=1&y=2"')

def test_browser_invalid_url(project):
    code, out = project.run("run", "app.example.com", "--dry-run")
    assert code == 1
    assert 'Invalid URL "app.example.com"' in out


def test_browser_not_found(project):
    code, out = project.run("run", "-b", "C:\\nope\\browser.exe", "--dry-run")
    assert code == 1
    assert "not found" in out


def test_browser_only(project):
    port = free_port()
    code, out = project.run("browser", "run", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert "mitmdump" not in out.lower()
    assert f"No proxy on port {port}" in out
    assert f"--proxy-server=127.0.0.1:{port}" in browser_line(out)


def test_browser_only_with_running_proxy(project):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        code, out = project.run("browser", "run", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert "No proxy" not in out
    browser_line(out)


@pytest.mark.parametrize("option", [("-w",), ("-r", "rules.json")])
def test_browser_only_rejects_proxy_options(project, option):
    code, out = project.run("browser", "run", *option, "--dry-run")
    assert code == 1
    assert f"{option[0]} is a proxy option" in out
    assert "Usage: gremlin browser run" in out


def test_browser_reuses_running_proxy(project):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        code, out = project.run("run", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert f"Proxy is already listening on port {port}" in out
    assert "mitmdump" not in out.lower()


def test_browser_unknown_option(project):
    code, out = project.run("run", "--bogus")
    assert code == 1
    assert "Unknown option: --bogus" in out


# --- gremlin dispatcher -----------------------------------------------------

@pytest.mark.parametrize("args", [(), ("help",), ("--help",)])
def test_gremlin_help(project, args):
    code, out = project.run(*args)
    assert code == 1
    assert all(c in out for c in ("gremlin run", "gremlin proxy run", "gremlin browser run", "gremlin phone run"))


@pytest.mark.parametrize("args", [("proxy",), ("proxy", "stop"), ("phone",), ("nope",)])
def test_gremlin_unknown_command(project, args):
    code, out = project.run(*args)
    assert code == 1
    assert "Unknown command: gremlin " + " ".join(args) in out


def test_gremlin_commands_are_case_insensitive(project):
    code, out = project.run("Proxy", "RUN", "-p", "9004", "--dry-run")
    assert code == 0, out
    assert " -p 9004 " in command_line(out)


def test_gremlin_passes_quoted_arguments_unchanged(project):
    # spaces, % and & inside a quoted argument survive the extra hop through gremlin.bat;
    # the space also makes subprocess quote the URL, as a user would in cmd
    (project.root / "rules" / "my rules.json").write_text("[]", encoding="ascii")
    code, out = project.run("run", "https://app.example.com/a%20b c?x=1&y=2",
                            "-r", str(project.root / "rules" / "my rules.json"),
                            "-p", str(free_port()), "--dry-run")
    assert code == 0, out
    assert '"https://app.example.com/a%20b c?x=1&y=2"' in browser_line(out)
    assert "my rules.json" in command_line(out)
