"""Aeon-V2 command-line entry points."""
import argparse
from pathlib import Path

from .core.config import Config

# Mirrors aeon-v1's memory/ layout (see aeon-v1/memory/README.md).
MEMORY_SUBDIRS = [
    "raw",
    "episodic",
    "semantic",
    "reflections",
    "consolidations",
    "media/uploads",
    "logs",
    "staging",
    "approved",
    "schemas",
    "tool_additions",
]

TOP_LEVEL_DIRS = ["vault", "skills", "research"]


def init_data(argv: list[str] | None = None) -> int:
    """Scaffold the Aeon data root (memory tree, vault mirror, skills, research)."""
    parser = argparse.ArgumentParser(
        prog="aeon-init-data",
        description="Create the Aeon-V2 data directory tree at AEON_DATA_DIR (or --root).",
    )
    parser.add_argument("--root", type=Path, default=None, help="Override AEON_DATA_DIR")
    args = parser.parse_args(argv)

    config = Config(base_path=args.root) if args.root else Config()
    root = config.base_path
    for sub in MEMORY_SUBDIRS:
        (root / "memory" / sub).mkdir(parents=True, exist_ok=True)
    for top in TOP_LEVEL_DIRS:
        (root / top).mkdir(parents=True, exist_ok=True)
    print(f"Aeon data root ready: {root.resolve()}")
    return 0
