"""Location of the package's static assets."""

from pathlib import Path

STATIC = Path(__file__).resolve().parent

__all__ = ["STATIC"]
