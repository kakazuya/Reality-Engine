"""pilot3: one SQLite database for KEC, BAJFINANCE and HINDALCO, built by scripts only (T-049).

No model call and no network anywhere in this package.  ``data_root()`` finds the read-only stores:
``REALITY_DATA_ROOT`` if set, else ``reality_engine/data`` of this checkout when it holds the stores,
else the main checkout's data folder (a worktree has no copy of the stores).
"""
from __future__ import annotations

import os
from pathlib import Path

SYMBOLS = ("KEC", "BAJFINANCE", "HINDALCO")
MAIN_DATA = Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
SANDBOX = Path(r"D:\RealityEngine\sandbox")
SHP_XBRL = Path(r"D:\RealityEngine\raw\nse_shp_xbrl_pilot")
SANDBOX_DB = {s: SANDBOX / f"{s.lower()}_loop" / f"{s.lower()}.db" for s in SYMBOLS}


def data_root() -> Path:
    env = os.environ.get("REALITY_DATA_ROOT")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parents[1] / "data"
    return here if (here / "ar_facts.db").is_file() else MAIN_DATA


# gap_loop.prepare reads REALITY_DATA_ROOT once at import, so set it before anything imports it.
os.environ.setdefault("REALITY_DATA_ROOT", str(data_root()))
