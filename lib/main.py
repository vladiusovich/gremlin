"""Entry point of the gremlin commands, called by gremlin.bat (Windows) and gremlin (Linux)."""
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit("[!!] gremlin needs Python 3.10 or newer")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gremlin_cli.cli import main  # noqa: E402

sys.exit(main())
