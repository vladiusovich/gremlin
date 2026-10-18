"""Settings profiles: env/<name>.env files with MITM_* keys."""
from __future__ import annotations

import os
from pathlib import Path

from .common import ROOT, fail, rel, warn

# Keep in sync with env/example.env and README.md
ENV_KEYS = ("MITM_URL", "MITM_BROWSER", "MITM_PORT", "MITM_RULES", "MITM_WEB", "MITM_INSECURE",
            "MITM_WIREGUARD", "MITM_WG_PORT")


def load(name: str | None) -> tuple[dict[str, str], Path | None]:
    """Reads a profile: env/<name>.env, or env/default.env (if present) without a name.

    Format: KEY=VALUE per line, lines starting with # are comments. Only ENV_KEYS are accepted (all
    optional), anything else is skipped with a warning, so a typo is visible. An empty value counts as
    not set. A relative MITM_RULES is resolved against the project root. Values are validated by the
    commands that use them. Returns the settings and the loaded file (None if there is none).
    """
    env_dir = ROOT / "env"
    if not name:
        path = env_dir / "default.env"
        if not path.is_file():
            return {}, None
    else:
        path = env_dir / f"{name}.env"
        if not path.is_file() and (env_dir / name).is_file():
            path = env_dir / name
        if not path.is_file():
            fail(f"Profile not found: {rel('env', name + '.env')}")

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] == '"':
            value = value[1:-1]
        if key.upper() not in ENV_KEYS:
            warn(f'{path}: unknown key "{key}" skipped. Allowed keys: {" ".join(ENV_KEYS)}')
            continue
        if value:
            values[key.upper()] = value

    if "MITM_RULES" in values:
        values["MITM_RULES"] = os.path.abspath(ROOT / values["MITM_RULES"])
    return values, path
