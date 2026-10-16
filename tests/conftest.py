import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "addons"))

from mitmproxy.test import taddons  # noqa: E402

import mock_errors  # noqa: E402


class Gremlin:
    """The addon wired to a mitmproxy test context and a temporary rules file."""

    def __init__(self, path: Path):
        self.path = path
        self.addon = mock_errors.MockErrors()
        self.tctx = taddons.context(self.addon)
        self._mtime = 1_000_000_000

    def write(self, data, raw: bool = False, encoding: str = "utf-8"):
        text = data if raw else json.dumps(data)
        self.path.write_text(text, encoding=encoding)
        # mtime resolution may be coarse: bump it explicitly so every write is seen as a change
        self._mtime += 10
        os.utime(self.path, (self._mtime, self._mtime))

    def configure(self):
        self.tctx.configure(self.addon, rules_file=str(self.path))

    def load(self, data, **kwargs):
        self.write(data, **kwargs)
        self.configure()
        return self.addon.rules


@pytest.fixture
def gremlin(tmp_path):
    g = Gremlin(tmp_path / "rules.json")
    with g.tctx:
        yield g
