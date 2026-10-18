#!/bin/sh
# Sets gremlin up on Linux: Python 3.10+ (asks before installing it with the package manager), then
# "./gremlin install" in Python: mitmproxy (asks too) and trust in its certificate.
# Safe to re-run: steps already done are skipped.
#
#   ./install.sh [-y]       -y answers yes to every question
ROOT=$(cd "$(dirname "$0")" && pwd)
YES=
for arg in "$@"; do
  case "$arg" in -y|--yes) YES=1 ;; esac
done

ask() {
  if [ -n "$YES" ]; then
    echo "[??] $1 [Y/n] y (-y)"
    return 0
  fi
  if ! [ -t 0 ]; then
    echo "[??] $1 [Y/n] n (no terminal to answer in: run with -y to agree)"
    return 1
  fi
  printf '[??] %s [Y/n] ' "$1"
  read -r answer
  case "$answer" in ""|[Yy]|[Yy][Ee][Ss]) return 0 ;; *) return 1 ;; esac
}

. "$ROOT/lib/find-python.sh"
if [ -n "$PYTHON" ]; then
  echo "[ok] Python: $PYTHON"
else
  echo "[..] Python 3.10 or newer is not installed. gremlin's commands are written in Python."
  # venv: gremlin installs mitmproxy and the test dependencies into virtual environments.
  # apt needs a fresh package list first: on a new system (e.g. WSL) it is empty
  update=
  if command -v apt-get >/dev/null 2>&1; then update="apt-get update"; install="apt-get install -y python3 python3-venv"
  elif command -v dnf >/dev/null 2>&1; then install="dnf install -y python3"
  elif command -v pacman >/dev/null 2>&1; then install="pacman -S --needed --noconfirm python"
  elif command -v zypper >/dev/null 2>&1; then install="zypper install -y python3"
  else
    echo "[!!] No known package manager found. Install Python 3.10+ and run ./install.sh again."
    exit 1
  fi
  if [ "$(id -u)" -ne 0 ]; then
    install="sudo $install"
    [ -z "$update" ] || update="sudo $update"
  fi
  if ! ask "Install Python now with: ${update:+$update && }$install?"; then
    echo "[!!] Python is required. Install Python 3.10+ and run ./install.sh again."
    exit 1
  fi
  if [ -n "$update" ]; then
    $update || { echo "[!!] Failed to update the package list."; exit 1; }
  fi
  $install || { echo "[!!] Failed to install Python."; exit 1; }
  . "$ROOT/lib/find-python.sh"
  if [ -z "$PYTHON" ]; then
    echo "[!!] Python 3.10+ is still not found: the distribution may ship an older one. Install a newer Python and run ./install.sh again."
    exit 1
  fi
  echo "[ok] Python installed: $PYTHON"
fi

exec "$PYTHON" "$ROOT/lib/main.py" install "$@"
