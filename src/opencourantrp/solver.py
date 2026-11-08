"""Locate the OpenCourant solver bundled with the application (no GUI dependencies).

In the packaged .exe the solver lives in the ``solver`` folder inside the bundle. When running from
source it is the git-ignored ``solver`` folder at the repository root, populated by
``tools/fetch_solver.py``. ``OPENCOURANTRP_SOLVER`` overrides both.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

STARTER = Path("exec") / "starter_win64.exe"
ENV_OVERRIDE = "OPENCOURANTRP_SOLVER"


def _candidates() -> list[Path]:
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return [Path(override)]
    if getattr(sys, "frozen", False):
        return [Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "solver"]
    return [Path(__file__).resolve().parents[2] / "solver"]


def find_root(folder: Path) -> Optional[Path]:
    """Folder that holds exec/starter_win64.exe, at most one level below ``folder``."""
    if (folder / STARTER).is_file():
        return folder
    if folder.is_dir():
        for sub in folder.iterdir():
            if (sub / STARTER).is_file():
                return sub
    return None


def solver_root() -> Optional[Path]:
    """Root of the bundled solver, or None if it is missing."""
    for c in _candidates():
        root = find_root(c)
        if root:
            return root
    return None
