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
        for name in ("start_proxy.bat", "run_browser.bat"):
            shutil.copy(ROOT / name, root / name)
        shutil.copytree(ROOT / "lib", root / "lib")
        (root / "env").mkdir()
        (root / "rules").mkdir()
        (root / "addons").mkdir()
        shutil.copy(ROOT / "addons" / "mock_errors.py", root / "addons")

    def profile(self, name: str, text: str):
        (self.root / "env" / f"{name}.env").write_text(text, encoding="ascii")

    def run(self, script: str, *args: str):
        env = dict(os.environ)
        # mitmdump from the test venv, so the scripts find it without install.bat
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        for k in [k for k in env if k.upper().startswith("MITM_")]:
            del env[k]
        r = subprocess.run([str(self.root / script), *args], cwd=self.root, env=env,
                           capture_output=True, timeout=60)
        out = (r.stdout + r.stderr).decode("cp866", errors="replace")
        return r.returncode, out


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path / "gremlin")


def command_line(out: str) -> str:
    """The mitmdump command printed by start_proxy.bat --dry-run."""
    lines = [l.strip() for l in out.splitlines() if "mitm" in l.lower() and " -p " in l]
    assert lines, out
    return lines[-1]


# --- start_proxy.bat --------------------------------------------------------

def test_defaults(project):
    code, out = project.run("start_proxy.bat", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert "mitmdump" in cmd.lower()
    assert " -p 8080 " in cmd
    assert f'rules_file={project.root}\\rules\\rules.json' in cmd
    assert "An empty rules\\rules.json would be created" in out
    # --dry-run creates nothing
    assert not (project.root / "rules" / "rules.json").exists()


def test_all_addons_loaded_except_underscored(project):
    (project.root / "addons" / "extra.py").write_text("addons = []\n")
    (project.root / "addons" / "_helper.py").write_text("")
    code, out = project.run("start_proxy.bat", "--dry-run")
    cmd = command_line(out)
    assert "mock_errors.py" in cmd
    assert "extra.py" in cmd
    assert "_helper.py" not in cmd


def test_default_profile_is_used(project):
    project.profile("default", "MITM_PORT=9001\n")
    code, out = project.run("start_proxy.bat", "--dry-run")
    assert code == 0, out
    assert "Profile:" in out and "default.env" in out
    assert " -p 9001 " in command_line(out)


def test_named_profile_and_relative_rules(project):
    (project.root / "rules" / "staging.json").write_text("[]")
    project.profile("staging", "# comment\nMITM_PORT=9002\nMITM_RULES=rules/staging.json\nMITM_WEB=yes\n")
    code, out = project.run("start_proxy.bat", "-e", "staging", "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9002 " in cmd
    assert "mitmweb" in cmd.lower()
    assert f"rules_file={project.root}\\rules\\staging.json" in cmd


def test_command_line_overrides_profile(project):
    (project.root / "rules" / "other.json").write_text("[]")
    project.profile("default", "MITM_PORT=9001\n")
    code, out = project.run("start_proxy.bat", "-p", "9003", "-r", str(project.root / "rules" / "other.json"),
                            "--dry-run")
    assert code == 0, out
    cmd = command_line(out)
    assert " -p 9003 " in cmd
    assert "other.json" in cmd


def test_missing_profile(project):
    code, out = project.run("start_proxy.bat", "-e", "nope", "--dry-run")
    assert code == 1
    assert "Profile not found: env\\nope.env" in out


def test_missing_non_default_rules_file(project):
    project.profile("p", "MITM_RULES=rules/missing.json\n")
    code, out = project.run("start_proxy.bat", "-e", "p", "--dry-run")
    assert code == 1
    assert "Rules file not found:" in out and "missing.json" in out


def test_unknown_profile_key_warns(project):
    project.profile("default", "MITM_PROT=1\nPATH=C:\\nothing\n")
    code, out = project.run("start_proxy.bat", "--dry-run")
    assert code == 0, out
    assert '[warn]' in out and 'unknown key "MITM_PROT" skipped' in out
    assert 'unknown key "PATH" skipped' in out
    # PATH was not clobbered: mitmdump is still found
    assert "mitmdump" in command_line(out).lower()


@pytest.mark.parametrize("port", ["0", "65536", "abc", "080", "123456", "-1"])
def test_invalid_port(project, port):
    code, out = project.run("start_proxy.bat", "-p", port, "--dry-run")
    assert code == 1
    assert f'Invalid port "{port}"' in out


@pytest.mark.parametrize("port", ["1", "8080", "65535"])
def test_valid_port(project, port):
    code, out = project.run("start_proxy.bat", "-p", port, "--dry-run")
    assert code == 0, out
    assert f" -p {port} " in command_line(out)


@pytest.mark.parametrize("value, ok", [("1", True), ("off", True), ("TRUE", True), ("maybe", False), ("2", False)])
def test_bool_validation(project, value, ok):
    project.profile("default", f"MITM_WEB={value}\n")
    code, out = project.run("start_proxy.bat", "--dry-run")
    assert (code == 0) == ok, out
    if not ok:
        assert f'Invalid value MITM_WEB="{value}"' in out


def test_unknown_option(project):
    code, out = project.run("start_proxy.bat", "--bogus")
    assert code == 1
    assert "Unknown option: --bogus" in out


# --- run_browser.bat --------------------------------------------------------

def browser_line(out: str) -> str:
    lines = [l.strip() for l in out.splitlines() if "--proxy-server=" in l]
    assert lines, out
    return lines[-1]


def test_browser_defaults(project):
    port = free_port()
    code, out = project.run("run_browser.bat", "-p", str(port), "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith("chrome ")
    assert f"--proxy-server=127.0.0.1:{port}" in line
    assert '--proxy-bypass-list="<-loopback>"' in line
    assert "--disable-quic" in line
    assert f"mitm-profile-chrome-{port}" in line
    assert line.endswith('"http://localhost:3001/"')
    assert "--ignore-certificate-errors" not in line
    # the proxy is not running yet, so start_proxy.bat is called with the same port
    assert f" -p {port} " in command_line(out)


def test_browser_profile_and_options(project):
    port = free_port()
    project.profile("default", f"MITM_URL=https://app.example.com/\nMITM_BROWSER=edge\nMITM_PORT={port}\n"
                               "MITM_INSECURE=1\nMITM_WEB=1\n")
    code, out = project.run("run_browser.bat", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.startswith("msedge ")
    assert "--ignore-certificate-errors" in line
    assert line.endswith('"https://app.example.com/"')
    assert "mitmweb" in command_line(out).lower()


def test_browser_url_argument_overrides_profile(project):
    project.profile("default", "MITM_URL=https://app.example.com/\n")
    code, out = project.run("run_browser.bat", "https://other.example.com/x", "-p", str(free_port()),
                            "-k", "--dry-run")
    assert code == 0, out
    line = browser_line(out)
    assert line.endswith('"https://other.example.com/x"')
    assert "--ignore-certificate-errors" in line


def test_browser_invalid_url(project):
    code, out = project.run("run_browser.bat", "app.example.com", "--dry-run")
    assert code == 1
    assert 'Invalid URL "app.example.com"' in out


def test_browser_not_found(project):
    code, out = project.run("run_browser.bat", "-b", "C:\\nope\\browser.exe", "--dry-run")
    assert code == 1
    assert "not found" in out


def test_browser_no_proxy_start(project):
    code, out = project.run("run_browser.bat", "-p", str(free_port()), "--no-proxy-start", "--dry-run")
    assert code == 0, out
    assert "mitmdump" not in out.lower()
    browser_line(out)


def test_browser_reuses_running_proxy(project):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        port = s.getsockname()[1]
        code, out = project.run("run_browser.bat", "-p", str(port), "--dry-run")
    assert code == 0, out
    assert f"Proxy is already listening on port {port}" in out
    assert "mitmdump" not in out.lower()


def test_browser_unknown_option(project):
    code, out = project.run("run_browser.bat", "--bogus")
    assert code == 1
    assert "Unknown option: --bogus" in out
