# Finds Python 3.10+ and stores its path in PYTHON (empty if not found).
# Sourced by gremlin and install.sh.
PYTHON=
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
    PYTHON=$(command -v "$candidate")
    break
  fi
done
