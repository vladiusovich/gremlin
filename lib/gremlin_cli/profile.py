"""Settings profiles (profiles/<name>.env files with MITM_* keys) and the rules file each one uses."""
from __future__ import annotations

import os
from pathlib import Path

from .common import ROOT, fail, rel, warn

# Keep in sync with profiles/example.env and README.md
ENV_KEYS = ("MITM_URL", "MITM_BROWSER", "MITM_PORT", "MITM_RULES", "MITM_WEB", "MITM_INSECURE",
            "MITM_WIREGUARD", "MITM_WG_PORT")
PROFILES_DIR = ROOT / "profiles"
RULES_DIR = ROOT / "rules"


def find(name: str) -> Path | None:
    """profiles/<name>.env; the name may include .env."""
    for path in (PROFILES_DIR / f"{name}.env", PROFILES_DIR / name):
        if path.is_file():
            return path
    return None


def load(name: str | None) -> tuple[dict[str, str], Path | None]:
    """Reads a profile: profiles/<name>.env, or profiles/default.env (if present) without a name.

    Format: KEY=VALUE per line, lines starting with # are comments. Only ENV_KEYS are accepted (all
    optional), anything else is skipped with a warning, so a typo is visible. An empty value counts as
    not set. MITM_RULES is resolved with rules_path() against the project root. Values are validated by
    the commands that use them. Returns the settings and the loaded file (None if there is none).
    """
    path = find(name or "default")
    if not path:
        if not name:
            return {}, None
        fail(f"Profile not found: {rel('profiles', name + '.env')}")

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
        values["MITM_RULES"] = rules_path(values["MITM_RULES"], ROOT)
    return values, path


def rules_path(value: str, base: Path) -> str:
    """A rules file given in -r or MITM_RULES. A short name (no .json at the end) is rules/<name>.json,
    subfolders included ("trade/errors"); anything else is a path, a relative one resolved against `base`."""
    if not os.path.isabs(value) and not value.lower().endswith(".json"):
        return os.path.abspath(RULES_DIR / f"{value}.json")
    return os.path.abspath(base / value)


def own_rules_file(path: Path | None) -> Path:
    """The rules file a profile uses without MITM_RULES: rules/<profile>.json (rules/default.json without
    a profile). Created empty if missing."""
    return RULES_DIR / f"{path.stem if path else 'default'}.json"


def rules_for(cli_value: str | None, settings: dict[str, str], path: Path | None) -> str:
    """The rules file to use. Priority: -r > MITM_RULES in the profile > the profile's own rules file."""
    if cli_value:
        return rules_path(cli_value, Path.cwd())
    return settings.get("MITM_RULES") or str(own_rules_file(path))
