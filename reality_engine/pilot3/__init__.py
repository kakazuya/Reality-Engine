"""pilot3: one SQLite database built by scripts only (T-049).

No model call and no network anywhere in this package.  ``data_root()`` finds the read-only stores:
``REALITY_DATA_ROOT`` if set, else ``reality_engine/data`` of this checkout when it holds the stores,
else the main checkout's data folder (a worktree has no copy of the stores).

The companies a build reads are data, never a list in this file: a ``--profile`` JSON names them, and without one
the default build reads the ``company`` table of ``REAL_DB`` (``profile.symbols()``), so the legacy three are
whatever that database holds.
"""
from __future__ import annotations

import os
from pathlib import Path

MAIN_DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
SANDBOX = Path(r"D:\RealityEngine\sandbox")
PAGES_DB = Path(r"D:\RealityEngine\pilot3\pages.db")
REAL_DB = MAIN_DATA / "pilot3" / "pilot3.db"
SHP_XBRL = Path(r"D:\RealityEngine\raw\nse_shp_xbrl_pilot")


def data_root() -> Path:
    env = os.environ.get("REALITY_DATA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parents[1] / "data"
    return here if (here / "ar_facts.db").is_file() else MAIN_DATA


def sandbox_db(symbol: str) -> Path:
    """The legacy per-company sandbox database: ``<sandbox>/<symbol lower>_loop/<symbol lower>.db``."""
    name = str(symbol).strip().lower()
    return SANDBOX / f"{name}_loop" / f"{name}.db"


# gap_loop.prepare reads REALITY_DATA_ROOT once at import, so set it before anything imports it.
os.environ.setdefault("REALITY_DATA_ROOT", str(data_root()))
