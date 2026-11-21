"""T-233: the selector for a scoped re-run (``--only <selector.json>``).

A fix should re-run only the rows/pages it touches.  The three pipelines that write rows an
investor reads -- ``v2.observations``, ``research.filing_events`` and ``research.driver_claims``
(``--repair``) -- accept the same tiny JSON file::

    {"stores": ["c32.db"], "doc_keys": ["2a8d0712"], "pages": [14, 28],
     "where": "measure = 'loans'"}

Every list is optional.  Lists match by value or prefix (a Wolf read prints an 8-character
``doc_key``; the store holds the full document path).  A row is selected only when every list that
is present matches and ``where`` -- a SQL predicate over the output table's own columns -- is true.
An empty file selects everything and is refused: a scoped run that is not scoped is the waste this
loop exists to remove.

The pipeline copies its baseline DB to ``--out`` first (:func:`copy_db`) and re-processes only the
selected rows, so everything else in the copy is byte-for-byte what it was.
"""
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = ["Selector", "copy_db"]


def _store_names(store: str | Path) -> set[str]:
    """The ways one store is written: ``c32``, ``c32.db`` or a full path."""
    base = Path(str(store)).name
    stem = base[:-3] if base.endswith(".db") else base
    return {base, stem}


@dataclass(frozen=True)
class Selector:
    """One scoped selection of stores / documents / pages, plus an optional SQL predicate."""

    stores: tuple[str, ...] = ()
    doc_keys: tuple[str, ...] = ()
    pages: tuple[int, ...] = ()
    where: str = ""

    def __post_init__(self) -> None:
        if not (self.stores or self.doc_keys or self.pages or self.where):
            raise ValueError("an empty --only selector selects everything; name stores, doc_keys, pages or a where")
        if any(bad in self.where for bad in (";", "--", "/*", "*/")):
            raise ValueError("--only where must be one SQL expression over the output row, not a script")

    @classmethod
    def load(cls, path: str | Path) -> "Selector":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: a selector is a JSON object")
        return cls(
            stores=tuple(str(s) for s in data.get("stores") or ()),
            doc_keys=tuple(str(s) for s in data.get("doc_keys") or ()),
            pages=tuple(int(p) for p in data.get("pages") or ()),
            where=str(data.get("where") or "").strip(),
        )

    # -- the three dimensions -------------------------------------------------
    def _store_ok(self, store: str | Path | None) -> bool:
        if not self.stores:
            return True
        if not store:
            return False
        names = _store_names(store)
        return any(want == str(store) or want in names or _store_names(want) & names for want in self.stores)

    def _doc_ok(self, doc_key: str | None) -> bool:
        if not self.doc_keys:
            return True
        key = str(doc_key or "")
        return any(want in key for want in self.doc_keys)

    def _page_ok(self, page: int | None) -> bool:
        if not self.pages:
            return True
        try:
            return int(page) in self.pages       # type: ignore[arg-type]
        except (TypeError, ValueError):
            return False

    # -- the calls a pipeline makes ------------------------------------------
    def store(self, store: str | Path | None) -> bool:
        """Is this store selected?  (documents and pages are checked per row.)"""
        return self._store_ok(store)

    def page(self, store: str | Path | None, doc_key: str | None, page: int | None) -> bool:
        """Is this page selected?  Honours all four dimensions."""
        return self._store_ok(store) and self._doc_ok(doc_key) and self._page_ok(page)

    def doc(self, store: str | Path | None, doc_key: str | None) -> bool:
        """Is this document selected?  ``pages`` is a page-level idea and is ignored here."""
        return self._store_ok(store) and self._doc_ok(doc_key)

    def row(self, row: Mapping[str, Any]) -> bool:
        """Is this output row selected by the lists?  ``where`` is applied as SQL, not here."""
        keep = True
        if self.stores:
            keep = keep and self._store_ok(row.get("store") if "store" in row else None)
        if keep and self.doc_keys:
            keep = self._doc_ok(str(row.get("doc_key") or ""))
        if keep and self.pages:
            keep = self._page_ok(row.get("page"))
        return keep

    def where_sql(self) -> str:
        """The row predicate to AND into the pipeline's own query (``1=1`` when absent)."""
        return f"({self.where})" if self.where else "1=1"


def copy_db(source: str | Path, out: str | Path) -> None:
    """Copy a baseline DB to ``out`` so a scoped run never touches the baseline.

    The pipeline DBs are SQLite in rollback-journal mode and closed cleanly, so the file copy is
    complete; a WAL that is still open would need its ``-wal`` file too, which a fix round never has.
    """
    source, out = Path(source), Path(out)
    if source.resolve() == out.resolve():
        raise ValueError("--baseline and --out must be different files (the baseline is never written)")
    if not source.is_file():
        raise FileNotFoundError(f"baseline not found: {source}")
    if (source.parent / (source.name + "-wal")).is_file():
        raise ValueError(f"{source} still has a -wal file; close its writer (or checkpoint it) before a scoped run")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)
