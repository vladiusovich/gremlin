"""gremlin test: the test suite in a local virtual environment (.venv), created on the first run.

Any arguments are passed to pytest as is. The proxy itself keeps using the mitmproxy from gremlin install.
"""
from __future__ import annotations

import subprocess

from .common import ROOT, create_venv, info, venv_python


def run(args: list[str]) -> int:
    venv = ROOT / ".venv"
    python = venv_python(venv)
    if not python.exists():
        info("Creating .venv...")
        if not create_venv(venv):
            return 1

    # Reinstall only when requirements-dev.txt is newer than the marker
    requirements = ROOT / "requirements-dev.txt"
    marker = venv / ".deps-installed"
    if not marker.exists() or requirements.stat().st_mtime > marker.stat().st_mtime:
        info("Installing test dependencies...")
        code = subprocess.call([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                                "-r", str(requirements)])
        if code:
            return code
        marker.write_text("ok\n")

    try:
        return subprocess.call([str(python), "-m", "pytest", *args], cwd=ROOT)
    except KeyboardInterrupt:
        return 130
