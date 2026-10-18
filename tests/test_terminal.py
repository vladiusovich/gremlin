"""The proxy window on Linux: a terminal emulator that fails to start is skipped for the next one.

Fake terminals stand in for real ones (the list is replaced), so no window is opened.
"""
import sys
import time

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "lib"))
from gremlin_cli import terminal  # noqa: E402
from gremlin_cli.common import Fail  # noqa: E402

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Linux terminal emulators")


def fake_terminal(path, script):
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def desktop(monkeypatch):
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv("TERMINAL", raising=False)


def test_crashing_terminal_is_skipped(tmp_path, monkeypatch, capsys, desktop):
    crashing = fake_terminal(tmp_path / "crashing", "echo 'No suitable font found' >&2\nexit 134\n")
    # a working terminal runs the command after -e, like xterm does
    marker = tmp_path / "ran"
    working = fake_terminal(tmp_path / "working", '[ "$1" = -e ] && shift\nexec "$@"\n')
    monkeypatch.setattr(terminal, "TERMINALS", ((crashing, ["-e"]), (working, ["-e"])))
    terminal.open_window("mitmproxy :1", ["sh", "-c", f"touch {marker}"])
    for _ in range(50):
        if marker.exists():
            break
        time.sleep(0.1)
    assert marker.exists()


def test_all_terminals_fail(tmp_path, monkeypatch, capsys, desktop):
    crashing = fake_terminal(tmp_path / "crashing", "echo 'No suitable font found' >&2\nexit 134\n")
    monkeypatch.setattr(terminal, "TERMINALS", ((crashing, ["-e"]),))
    with pytest.raises(Fail):
        terminal.open_window("mitmproxy :1", ["true"])
    out = capsys.readouterr().out
    assert "No terminal emulator could open the proxy window" in out
    assert "exited with code 134: No suitable font found" in out
    assert "./gremlin proxy run" in out


def test_terminal_that_hands_the_window_over_counts_as_started(tmp_path, monkeypatch, desktop):
    # gnome-terminal asks its server for a window and exits with 0 right away
    quick = fake_terminal(tmp_path / "quick", "exit 0\n")
    monkeypatch.setattr(terminal, "TERMINALS", ((quick, ["--"]),))
    terminal.open_window("mitmproxy :1", ["true"])


def test_failing_command_keeps_the_window_open():
    import subprocess
    r = subprocess.run(["sh", "-c", terminal.HOLD, "gremlin", "sh", "-c", "exit 3"], input="\n",
                       capture_output=True, text=True)
    assert "Exited with code 3. Press Enter to close this window." in r.stdout
