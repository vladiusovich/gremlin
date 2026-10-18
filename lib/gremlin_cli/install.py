"""gremlin install: mitmproxy (asks before installing) and trust in its root certificate.

Python itself is checked and installed before this runs, by install.bat / install.sh.
Safe to re-run: steps already done are skipped.
"""
from __future__ import annotations

import base64
import os
import shutil
import subprocess
import time
from pathlib import Path

from .common import (MITMPROXY_VENV, PROG, WINDOWS, ask, create_venv, detail, fail, find_mitmdump, info,
                     install_packages, ok, parse_options, venv_python, warn)

USAGE = f"Usage: {PROG} install [-y]\n  -y, --yes   answer yes to every question"
OPTIONS = {"-y": ("yes", False), "--yes": ("yes", False)}

CA_DIR = Path.home() / ".mitmproxy"
CA_PEM = CA_DIR / "mitmproxy-ca-cert.pem"
CA_CER = CA_DIR / "mitmproxy-ca-cert.cer"
NSS_NAME = "mitmproxy"


def run(args: list[str]) -> int:
    yes = bool(parse_options(args, OPTIONS, USAGE).get("yes"))
    mitmdump = ensure_mitmproxy(yes)
    ensure_certificate(mitmdump)
    if WINDOWS:
        trust_windows()
    else:
        trust_linux(yes)
    print()
    print(f"Done. To start the proxy and a browser through it: {PROG} browser run")
    return 0


def ensure_mitmproxy(yes: bool) -> str:
    found = find_mitmdump()
    if found:
        ok(f"mitmproxy is already installed: {found}")
        return found
    info("mitmproxy is not installed.")
    if not ask("Install mitmproxy now?", yes):
        fail("mitmproxy is required. Install it from https://mitmproxy.org/downloads/ "
             f"and run {PROG} install again")

    if WINDOWS and shutil.which("winget"):
        info("Installing mitmproxy with winget...")
        subprocess.call(["winget", "install", "--id", "mitmproxy.mitmproxy", "-e",
                         "--accept-package-agreements", "--accept-source-agreements"])
        found = find_mitmdump()
    elif not WINDOWS and shutil.which("pipx"):
        info("Installing mitmproxy with pipx...")
        subprocess.call(["pipx", "install", "mitmproxy"])
        found = find_mitmdump()

    if not found:
        # Its own virtual environment: works without admin rights and without touching the system
        # Python (pip install --user is blocked on recent Debian / Ubuntu, PEP 668)
        info(f"Installing mitmproxy with pip into {MITMPROXY_VENV}")
        if create_venv(MITMPROXY_VENV, yes):
            subprocess.call([str(venv_python(MITMPROXY_VENV)), "-m", "pip", "install", "--upgrade",
                             "--disable-pip-version-check", "mitmproxy"])
            found = find_mitmdump()

    if not found:
        fail("Failed to install mitmproxy. Install it from https://mitmproxy.org/downloads/ "
             f"and run {PROG} install again")
    ok(f"mitmproxy installed: {found}")
    return found


def ensure_certificate(mitmdump: str):
    """The mitmproxy root CA is created on the proxy's first start: run it briefly on a free port."""
    needed = [CA_PEM, CA_CER] if WINDOWS else [CA_PEM]
    if all(p.exists() for p in needed):
        return
    info("Generating the mitmproxy certificate...")
    proc = subprocess.Popen([mitmdump, "-p", "0"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if all(p.exists() for p in needed):
                break
            time.sleep(0.5)
    finally:
        proc.kill()
        proc.wait()
    if not all(p.exists() for p in needed):
        fail(f"The certificate was not generated: {CA_PEM}")


# --- Windows: the current user's Trusted Root Certification Authorities ---------------------------

def trust_windows():
    # Look up by thumbprint in both user and machine stores: the CA may have been regenerated
    check = ("$t = (New-Object Security.Cryptography.X509Certificates.X509Certificate2 $env:CA_CER).Thumbprint; "
             "foreach ($loc in 'CurrentUser','LocalMachine') { "
             "$s = New-Object Security.Cryptography.X509Certificates.X509Store 'Root', $loc; $s.Open('ReadOnly'); "
             "$found = $s.Certificates.Find('FindByThumbprint', $t, $false).Count; $s.Close(); "
             "if ($found) { exit 0 } }; exit 1")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", check], env={**os.environ, "CA_CER": str(CA_CER)})
    if r.returncode == 0:
        ok("The mitmproxy certificate is already trusted.")
        return
    info("Adding the certificate to Trusted Root Certification Authorities (current user).")
    detail('Windows will show a security warning - answer "Yes".')
    if subprocess.run(["certutil", "-user", "-addstore", "Root", str(CA_CER)],
                      stdout=subprocess.DEVNULL).returncode != 0:
        fail(f"Failed to add the certificate. To add it manually, open {CA_CER}")
    ok("Certificate installed. Restart browsers that are already open.")


# --- Linux: the browsers' NSS database, and optionally the system store -------------------------

def trust_linux(yes: bool):
    trust_nss(yes)
    trust_system(yes)


# Chromium from snap (Ubuntu): where it is installed, and its own home folder, created by snapd
# on the first start (current is a link to the revision folder, so gremlin does not create it)
SNAP_CHROMIUM = Path("/snap/chromium")


def snap_chromium_home() -> Path:
    return Path.home() / "snap" / "chromium" / "current"


def nss_databases() -> list[Path]:
    """Chrome, Chromium and Edge on Linux trust the certificates in ~/.pki/nssdb, not the system store.
    Chromium from snap (Ubuntu) has its own copy of that folder."""
    dbs = [Path.home() / ".pki" / "nssdb"]
    if snap_chromium_home().is_dir():
        dbs.append(snap_chromium_home() / ".pki" / "nssdb")
    return dbs


def snap_chromium_never_started() -> bool:
    return SNAP_CHROMIUM.is_dir() and not snap_chromium_home().is_dir()


def _pem_der(text: str) -> bytes:
    body = "".join(l for l in text.splitlines() if l and not l.startswith("-----"))
    return base64.b64decode(body)


def trust_nss(yes: bool):
    if not shutil.which("certutil"):
        install_packages({"apt-get": "libnss3-tools", "dnf": "nss-tools", "pacman": "nss",
                          "zypper": "mozilla-nss-tools"},
                         "Adding the certificate to the browsers' certificate database needs certutil (NSS tools).",
                         yes)
    if not shutil.which("certutil"):
        warn("certutil not found: the browser will not trust the proxy's certificate. Install the NSS tools "
             f"and run {PROG} install again, or ignore certificate errors with -k / MITM_INSECURE=1")
        return
    ours = _pem_der(CA_PEM.read_text())
    for db in nss_databases():
        where = f"sql:{db}"
        if not (db / "cert9.db").exists():
            db.mkdir(parents=True, exist_ok=True)
            subprocess.run(["certutil", "-d", where, "-N", "--empty-password"], check=False)
        current = subprocess.run(["certutil", "-d", where, "-L", "-n", NSS_NAME, "-a"],
                                 capture_output=True, text=True)
        if current.returncode == 0:
            try:
                if _pem_der(current.stdout) == ours:
                    ok(f"The mitmproxy certificate is already trusted in {db}")
                    continue
            except ValueError:
                pass
            # An old certificate (mitmproxy was reinstalled): replace it
            subprocess.run(["certutil", "-d", where, "-D", "-n", NSS_NAME], capture_output=True)
        r = subprocess.run(["certutil", "-d", where, "-A", "-t", "C,,", "-n", NSS_NAME, "-i", str(CA_PEM)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            fail(f"Failed to add the certificate to {db}: {r.stderr.strip()}")
        ok(f"Certificate added to {db}. Restart browsers that are already open.")
    if snap_chromium_never_started():
        warn("Chromium from snap is installed but was never started, so its certificate database does not "
             f"exist yet. Start Chromium once, close it and run {PROG} install again")


# Where each distribution family takes extra trusted certificates from, and the command that applies them
SYSTEM_STORES = (
    (Path("/usr/local/share/ca-certificates"), "mitmproxy.crt", ["update-ca-certificates"]),  # Debian, Ubuntu
    (Path("/etc/pki/ca-trust/source/anchors"), "mitmproxy.pem", ["update-ca-trust"]),  # Fedora, RHEL
    (Path("/etc/ca-certificates/trust-source/anchors"), "mitmproxy.crt", ["update-ca-trust"]),  # Arch
    (Path("/etc/pki/trust/anchors"), "mitmproxy.pem", ["update-ca-certificates"]),  # openSUSE
)


def trust_system(yes: bool):
    """Optional: curl, wget and other command-line tools use the system store."""
    for folder, name, update in SYSTEM_STORES:
        if folder.is_dir() and shutil.which(update[0]):
            break
    else:
        return
    target = folder / name
    if target.is_file() and target.read_bytes() == CA_PEM.read_bytes():
        ok(f"The mitmproxy certificate is already trusted system-wide: {target}")
        return
    info("The browser is set up. curl and other command-line tools use the system certificate store instead.")
    if not ask("Also trust the mitmproxy certificate system-wide (needs sudo)?", yes):
        detail(f"Skipped. To do it later: {PROG} install")
        return
    sudo = [] if os.geteuid() == 0 else ["sudo"]
    if (subprocess.call(sudo + ["cp", str(CA_PEM), str(target)]) != 0
            or subprocess.call(sudo + update) != 0):
        # Optional step: the browser already trusts the certificate
        warn(f"Failed to add the certificate to the system store. To do it later: {PROG} install")
        return
    ok(f"Certificate added to the system store: {target}")
