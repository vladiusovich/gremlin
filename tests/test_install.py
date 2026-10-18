"""gremlin install on Linux: which certificate databases of the browsers it writes to."""
import sys

from conftest import ROOT

sys.path.insert(0, str(ROOT / "lib"))
from gremlin_cli import install  # noqa: E402


def setup(tmp_path, monkeypatch, snap_installed: bool, snap_started: bool):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(install.Path, "home", lambda: home)
    snap = tmp_path / "snap-root" / "chromium"
    if snap_installed:
        snap.mkdir(parents=True)
    monkeypatch.setattr(install, "SNAP_CHROMIUM", snap)
    if snap_started:
        (home / "snap" / "chromium" / "current").mkdir(parents=True)
    return home


def test_without_snap_chromium(tmp_path, monkeypatch):
    home = setup(tmp_path, monkeypatch, snap_installed=False, snap_started=False)
    assert install.nss_databases() == [home / ".pki" / "nssdb"]
    assert not install.snap_chromium_never_started()


def test_snap_chromium_that_was_started(tmp_path, monkeypatch):
    home = setup(tmp_path, monkeypatch, snap_installed=True, snap_started=True)
    assert install.nss_databases() == [home / ".pki" / "nssdb",
                                       home / "snap" / "chromium" / "current" / ".pki" / "nssdb"]
    assert not install.snap_chromium_never_started()


def test_snap_chromium_never_started(tmp_path, monkeypatch):
    # its folder in home is created by snapd on the first start: gremlin warns instead of creating it
    home = setup(tmp_path, monkeypatch, snap_installed=True, snap_started=False)
    assert install.nss_databases() == [home / ".pki" / "nssdb"]
    assert install.snap_chromium_never_started()
    assert not (home / "snap").exists()
