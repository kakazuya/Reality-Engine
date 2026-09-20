"""One-time migration: vectors.json -> vectors.npy + vectors_meta.json.

Reads the 585 MB JSON fallback store once, writes:
  vectors.npy       float32 matrix (N x 384), memory-mappable
  vectors_meta.json list of {id, symbol, isin, source_type, document_date, text}
                    (no vector payloads)

Idempotent: skips rows whose id is already present; re-runnable.
Keeps vectors.json on disk as audit source; only stops READING it
(VectorStoreManager._load prefers npy + sidecar when both exist).

Usage:  python reality_engine/scripts/migrate_vector_store.py [--limit N]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=0, help="Migrate first N rows only (0=all)")
    args = parser.parse_args(argv)

    from reality_engine.config import LANCEDB_DIR

    src = Path(LANCEDB_DIR) / "vectors.json"
    npy_path = Path(LANCEDB_DIR) / "vectors.npy"
    meta_path = Path(LANCEDB_DIR) / "vectors_meta.json"
    if not src.exists():
        print(f"no source {src}; nothing to migrate")
        return 1

    import numpy as np

    existing_ids: set = set()
    metas: list = []
    if meta_path.exists():
        try:
            metas = json.loads(meta_path.read_text(encoding="utf-8"))
            existing_ids = {m.get("id") for m in metas}
            print(f"resuming: {len(metas)} rows already migrated")
        except (OSError, json.JSONDecodeError):
            metas, existing_ids = [], set()

    t0 = time.perf_counter()
    print(f"parsing {src} ({src.stat().st_size / 1e6:.0f} MB) ...")
    rows = json.loads(src.read_text(encoding="utf-8"))
    print(f"parsed {len(rows)} rows in {time.perf_counter() - t0:.1f}s")
    if args.limit:
        rows = rows[: args.limit]
    fresh = [r for r in rows if r.get("id") not in existing_ids]
    print(f"fresh rows: {len(fresh)} (skipping {len(rows) - len(fresh)} already present)")
    if not fresh:
        print("nothing to do")
        return 0

    dim = len(fresh[0].get("vector") or [])
    assert dim > 0, "first fresh row has no vector"
    mat = np.zeros((len(fresh), dim), dtype="float32")
    new_metas = []
    for i, r in enumerate(fresh):
        v = r.get("vector") or []
        if len(v) != dim:
            raise ValueError(f"row {i} dim {len(v)} != {dim}")
        mat[i] = v
        new_metas.append({k: r.get(k) for k in ("id", "symbol", "isin", "source_type", "document_date", "text")})

    if meta_path.exists() and metas:
        old = np.load(str(npy_path), mmap_mode="r")
        assert old.shape[1] == dim, f"dim drift {old.shape[1]} != {dim}"
        mat = np.concatenate([np.asarray(old), mat], axis=0)
    np.save(str(npy_path), mat)
    metas.extend(new_metas)
    meta_path.write_text(json.dumps(metas), encoding="utf-8")
    print(f"wrote {npy_path} {mat.shape} ({npy_path.stat().st_size / 1e6:.0f} MB) + {len(new_metas)} metas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
