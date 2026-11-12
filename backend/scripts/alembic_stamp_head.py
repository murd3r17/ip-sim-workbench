"""Stamp the live database to alembic head without running migrations."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alembic.config import Config
from alembic import command


def main() -> int:
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.stamp(cfg, "head")
    print("stamped live database to alembic head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
