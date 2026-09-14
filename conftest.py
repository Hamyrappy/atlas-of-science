"""Puts the repository root on `sys.path` so tests import `atlas` without an install."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
