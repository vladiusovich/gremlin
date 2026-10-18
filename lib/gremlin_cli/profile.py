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
# Where profiles and the default rules were kept before: still read, with a warning to move them
LEGACY_PROFILES_DIR = ROOT / "env"
LEGACY_DEFAULT_RULES = RULES_DIR / "rules.json"


def find(name: str) -> Path | None:
    """profiles/<name>.env (the name may include .env), else the same file in the old env/ folder."""
    for folder in (PROFILES_DIR, LEGACY_PROFILES_DIR):
        for path in (folder / f"{name}.env", folder / name):
            if path.is_file():
                if folder == LEGACY_PROFILES_DIR:
                    warn(f"Profile {rel('env', path.name)} is in the old env folder: "
                         f"move it to {rel('profiles', path.name)}")
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
    """rules/<profile>.json, rules/default.json without a profile: created empty if missing."""
    return RULES_DIR / f"{path.stem if path else 'default'}.json"


def own_rules(path: Path | None) -> str:
    """The rules file a profile uses without MITM_RULES: own_rules_file(). Until rules/default.json
    exists, the default profile uses the old rules/rules.json if it is there."""
    rules = own_rules_file(path)
    if rules.name == "default.json" and not rules.exists() and LEGACY_DEFAULT_RULES.exists():
        warn(f"Using the old {rel('rules', 'rules.json')}: rename it to {rel('rules', 'default.json')}")
        return str(LEGACY_DEFAULT_RULES)
    return str(rules)


def rules_for(cli_value: str | None, settings: dict[str, str], path: Path | None) -> str:
    """The rules file to use. Priority: -r > MITM_RULES in the profile > the profile's own rules file."""
    if cli_value:
        return rules_path(cli_value, Path.cwd())
    return settings.get("MITM_RULES") or own_rules(path)
