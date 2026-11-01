"""T-038 wiring: contract-passing extract rows, quoted passages, and the KEC loader.

The fixtures are the stores' own shape, never the live databases: an extract store with
one passing and one contract-failing measure row, a fact store built by ``load_fact``, and
a chunk store with three Hindalco pages (one known after the as_of).  The expected values
are read back from those stores, not typed into the assertions.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from reality_engine.query.v4 import execute, load_fact, run
from reality_engine.query.v4.decompose import decompose_case, load_registry

REPO = Path(__file__).resolve().parents[2]
BANK = REPO / "tasks" / "pilot60" / "PILOT_BANK_2026-10-31.jsonl"
KEC_RAW = Path(r"D:\RealityEngine\raw\kec_transcripts")
sys.path.insert(0, str(REPO / "tasks" / "pilot60" / "proto3_text"))
import kec_load  # noqa: E402

BAJ, HIND = "INE296A01032", "INE038A01020"
AS_OF = "2026-10-19"

EXTRACT_DDL = """
CREATE TABLE lender_metrics(
    isin TEXT NOT NULL, period_end TEXT NOT NULL, metric TEXT NOT NULL, value REAL NOT NULL,
    unit TEXT NOT NULL, source TEXT NOT NULL, doc_id TEXT, known_at TEXT NOT NULL, quote TEXT,
    page INTEGER, PRIMARY KEY (isin, period_end, metric)) WITHOUT ROWID;
"""

#: one passing NIM, one contract-failing NIM (90% is outside 0..25), one gross NPA the
#: registry has no atom for, and one NIM known after AS_OF.
EXTRACT_ROWS = [
    (BAJ, "2026-06-30", "nim_pct", 3.5, "pct", "chunks_v3", "sha256:aaa",
     "2026-08-10T18:00:00", "Net interest margin (NIM) of 3.5% for the quarter.", 41),
    (BAJ, "2026-03-31", "nim_pct", 90.0, "pct", "chunks_v3", "sha256:bbb",
     "2026-05-10T18:00:00", "Net interest margin (NIM) of 90% for the year.", 12),
    (BAJ, "2026-06-30", "gnpa_pct", 2.1, "pct", "chunks_v3", "sha256:aaa",
     "2026-08-10T18:00:00", "Gross non-performing assets (GNPA) at 2.1% of advances.", 42),
    (BAJ, "2026-09-30", "nim_pct", 4.0, "pct", "chunks_v3", "sha256:ccc",
     "2026-11-01T18:00:00", "Net interest margin (NIM) of 4.0% in the September quarter.", 7),
]

#: (chunk_id, isin, doc_type, page_from, page_to, body, known_at)
CHUNK_ROWS = [
    (1, HIND, "concall", 4, 4,
     "Hindalco concall remark: management said the copper hedge is around 30% at about "
     "2,570 and the margin should hold.", "2026-08-07T18:00:00"),
    (2, HIND, "deck", 9, 9,
     "Hindalco is a global sustainability leader in the S&P Global Yearbook 2026.",
     "2026-05-22T18:00:00"),
    (3, HIND, "concall", 30, 30,
     "Hindalco concall remark filed later: the hedge is around 30% again.",
     "2026-11-01T18:00:00"),
]


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    return con


def _extract(root: Path) -> Path:
    path = root / "extract_proto3.db"
    con = _connect(path)
    con.executescript(EXTRACT_DDL)
    con.executemany("INSERT INTO lender_metrics VALUES (?,?,?,?,?,?,?,?,?,?)", EXTRACT_ROWS)
    con.commit()
    con.close()
    return path


def _chunks(root: Path) -> Path:
    path = root / "chunks_v3_pilot.db"
    con = _connect(path)
    con.executescript(
        """
        CREATE TABLE chunk(chunk_id INTEGER PRIMARY KEY, doc_id TEXT, chunk_index INTEGER,
                           header TEXT, body TEXT, section TEXT, page_from INTEGER,
                           page_to INTEGER, isin TEXT, doc_type TEXT, known_at TEXT);
        CREATE TABLE doc(doc_id TEXT PRIMARY KEY, sha256 TEXT, isin TEXT, doc_type TEXT,
                         known_at TEXT);
        """
    )
    con.executemany(
        "INSERT INTO chunk(chunk_id, doc_id, isin, doc_type, page_from, page_to, body, "
        "known_at) VALUES (?,?,?,?,?,?,?,?)",
        [(chunk_id, f"sha256:{chunk_id:03d}", isin, doc_type, page_from, page_to, body,
          known_at)
         for chunk_id, isin, doc_type, page_from, page_to, body, known_at in CHUNK_ROWS])
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?)",
                    [(f"sha256:{chunk_id:03d}", f"{chunk_id:03d}", isin, doc_type, known_at)
                     for chunk_id, isin, doc_type, _, _, _, known_at in CHUNK_ROWS])
    con.commit()
    con.close()
    return path


def _fact_db(root: Path) -> Path:
    """The fact store's shape (fact_view.sql) plus the load's provenance side table."""
    path = root / "v4" / "fact_v4_pilot.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect(path)
    con.executescript(
        """
        CREATE TABLE fact(entity_id TEXT NOT NULL, atom TEXT NOT NULL,
                          dims TEXT NOT NULL DEFAULT '', period_start TEXT NOT NULL,
                          period_end TEXT NOT NULL, value, unit TEXT,
                          known_at TEXT NOT NULL, source_ref TEXT NOT NULL,
                          PRIMARY KEY (entity_id, atom, dims, period_start, period_end))
                          WITHOUT ROWID;
        """
    )
    con.commit()
    con.close()
    return path


@pytest.fixture()
def stores() -> Iterator[SimpleNamespace]:
    root = REPO / ".tmp" / f"proto3-wiring-{uuid.uuid4().hex[:10]}"
    root.mkdir(parents=True, exist_ok=True)
    extract = _extract(root)
    fact = _fact_db(root)
    stats = load_fact.load(extract, fact)
    chunks = _chunks(root)
    v4 = fact.parent
    (v4 / "v4.db").touch()
    ledger = run.Stores(v4, market=root / "none.db", chunks=chunks)
    resolver = run.Resolver({"BAJFINANCE": BAJ, "HINDALCO": HIND},
                            {"Bajaj Finance Limited": BAJ,
                             "Hindalco Industries Limited": HIND}, {BAJ, HIND})
    yield SimpleNamespace(root=root, extract=extract, fact=fact, chunks=chunks,
                          stats=stats, stores=ledger, resolver=resolver,
                          registry=load_registry())
    ledger.close()


def _part(atom: str, **dims) -> execute.Part:
    return execute.Part(atom=atom, dims=dict(dims), operator="value_at", shape="scalar")


def _one(ledger: SimpleNamespace, atom: str, as_of: str = AS_OF):
    return execute.execute(_part(atom), as_of, ledger.stores, entity=BAJ,
                           registry=ledger.registry)


# --- 0. a disputed number stays out unless a re-read settled on the stored number --
@pytest.mark.parametrize("resolved, loads", [(None, False), ("9.9", False), ("3.5", True)])
def test_a_disputed_number_is_not_loaded(stores, resolved, loads):
    con = _connect(stores.extract)
    con.execute("CREATE TABLE number_check(table_name TEXT, row_pk TEXT, printed_token TEXT, "
                "status TEXT, resolved_value TEXT)")
    pk = f"isin={BAJ}|period_end=2026-06-30|metric=nim_pct"
    con.execute("INSERT INTO number_check VALUES ('lender_metrics', ?, '3.5', 'disputed', ?)",
                (pk, resolved))
    con.commit()
    con.close()
    fact = _fact_db(stores.root / uuid.uuid4().hex[:8])
    stats = load_fact.load(stores.extract, fact)
    con = _connect(fact)
    values = [row["value"] for row in con.execute("SELECT value FROM fact WHERE atom = 'fin.nim'")]
    con.close()
    assert (3.5 in values) is loads, values
    assert stats["number_disputed"] == (0 if loads else 1)


# --- 1. the contracts gate the load -----------------------------------------
def test_a_contract_failing_row_is_not_loaded(stores):
    # the 90% NIM is refused by contracts.check (value_above_range), the 3.5% one passes
    assert stores.stats["contract_failed"] == 1
    reasons = stores.stats["contract_reasons"]
    assert any("nim_pct" in reason and "above_range" in reason for reason in reasons), reasons
    con = _connect(stores.fact)
    values = [row["value"] for row in con.execute(
        "SELECT value FROM fact WHERE atom = 'fin.nim' ORDER BY period_end")]
    con.close()
    assert values == [3.5, 4.0], values
    assert all(value != 90.0 for value in values)


def test_a_passing_row_answers_its_own_measure_not_a_nearby_one(stores):
    nim = _one(stores, "fin.nim")
    assert nim.answer_type == "measured", nim.nid_reason
    assert nim.value == pytest.approx(3.5)
    # gross NPA has no atom in the registry: it is counted, listed, and never loaded as
    # the net-NPA atom that sits beside it.
    assert ("lender_metrics", "gnpa_pct") in stores.stats["unmapped"]
    npa = _one(stores, "fin.npa")
    assert npa.answer_type == "not_in_data"
    assert "no fin.npa row" in (npa.nid_reason or "")


# --- 2. point in time on both stores ---------------------------------------
def test_a_row_known_after_as_of_is_not_returned(stores):
    at_as_of = _one(stores, "fin.nim", as_of=AS_OF)
    assert at_as_of.answer_type == "measured"
    assert at_as_of.value == pytest.approx(3.5)          # 2026-09-30 row is known later
    after = _one(stores, "fin.nim", as_of="2026-11-02")
    assert after.answer_type == "measured"
    assert after.value == pytest.approx(4.0)


def test_a_passage_known_after_as_of_is_not_returned(stores):
    case = {"mid": "T038#PIT", "as_of": AS_OF,
            "question": "What did the Hindalco concall remark say about the copper hedge?",
            "entities": [{"isin": HIND, "symbol": "HINDALCO"}]}
    row = run.run_case(case, stores.stores, stores.resolver, stores.registry)
    quotes = [value["quote"] for result in row["results"]
              if result.get("answer_type") == "passages" for value in result["values"]]
    assert quotes, [result.get("nid_reason") for result in row["results"]]
    con = _connect(stores.chunks)
    bodies = {row["chunk_id"]: (row["body"], row["known_at"])
              for row in con.execute("SELECT chunk_id, body, known_at FROM chunk")}
    con.close()
    served = set()
    for result in row["results"]:
        for value in result.get("values") or []:
            body, known = bodies[value["chunk_id"]]
            served.add(value["chunk_id"])
            assert value["quote"] in body                     # an exact quote
            assert known[:10] <= AS_OF                        # PIT
    assert 3 not in served                                    # the later page stays out


# --- 3. narrative: passages, apart from answered ---------------------------
def _narrative(question: str) -> dict:
    return {"mid": "T038#N", "as_of": AS_OF, "question": question,
            "entities": [{"isin": HIND, "symbol": "HINDALCO"}]}


def test_a_narrative_with_no_decomposer_topic_returns_quoted_passages(stores):
    case = _narrative("Hindalco concall remark on the copper hedge")
    ask = decompose_case(dict(case), stores.registry)
    assert any(part.atom in ("claim.claim", "text.passage") for part in ask.parts), \
        [(part.atom, part.shape) for part in ask.parts]
    assert not any(part.dims.get("topic") for part in ask.parts), \
        [(part.atom, part.dims) for part in ask.parts]
    row = run.run_case(case, stores.stores, stores.resolver, stores.registry)
    passages = [result for result in row["results"]
                if result.get("answer_type") == "passages"]
    assert len(passages) == 1, [result.get("nid_reason") for result in row["results"]]
    result = passages[0]
    assert result["shape"] == "passage"
    assert 0 < len(result["values"]) <= 5
    con = _connect(stores.chunks)
    bodies = {row["chunk_id"]: row["body"]
              for row in con.execute("SELECT chunk_id, body FROM chunk")}
    con.close()
    for value in result["values"]:
        assert value["quote"] and value["quote"] in bodies[value["chunk_id"]]
        assert value["doc_id"] and value["page_no"] and value["known_at"]
    assert row["case_answered"] is False        # a passage is never an answered value
    assert execute.counts_as_answered(result) is False


def test_a_narrative_with_no_matching_passage_refuses(stores):
    case = _narrative("Hindalco concall remark about a merger in Brazil")
    row = run.run_case(case, stores.stores, stores.resolver, stores.registry)
    results = [result for result in row["results"]
               if result.get("atom") in ("claim.claim", "text.passage")]
    assert results and all(result["answer_type"] == "not_in_data" for result in results), \
        [(result.get("atom"), result.get("answer_type")) for result in row["results"]]
    assert all(not (result.get("values") or []) for result in results)


# --- 4. the KEC loader ------------------------------------------------------
@pytest.mark.skipif(not KEC_RAW.is_dir(), reason="the raw KEC transcript directory is absent")
def test_kec_loader_keeps_known_at_from_the_file_and_a_second_run_adds_nothing():
    entries = json.loads((KEC_RAW / "_known_at.json").read_text(encoding="utf-8"))[:2]
    root = REPO / ".tmp" / f"kec-{uuid.uuid4().hex[:10]}"
    raw = root / "raw"
    raw.mkdir(parents=True)
    for entry in entries:
        shutil.copy2(KEC_RAW / f"{entry['sha256']}.pdf", raw / f"{entry['sha256']}.pdf")
    manifest = raw / "_known_at.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")
    db = root / "chunks.db"
    first = kec_load.load(db, manifest, raw)
    assert first["docs_added"] == len(entries) and first["chunks"] > 0
    con = _connect(db)
    docs = {row["sha256"]: dict(row) for row in con.execute(
        "SELECT sha256, known_at, isin, doc_type, symbol_at_time FROM doc")}
    assert set(docs) == {entry["sha256"] for entry in entries}
    for entry in entries:
        assert docs[entry["sha256"]]["known_at"] == entry["known_at"]
        assert docs[entry["sha256"]]["isin"] == "INE389H01022"
        assert docs[entry["sha256"]]["doc_type"] == "concall"
    assert con.execute("SELECT COUNT(*) FROM chunk WHERE isin = 'INE389H01022' "
                       "AND doc_type = 'concall' AND body <> '' AND page_from >= 1"
                       ).fetchone()[0] == first["chunks"]
    con.close()
    second = kec_load.load(db, manifest, raw)
    assert second["docs_added"] == 0 and second["docs_skipped"] == len(entries)
    con = _connect(db)
    assert con.execute("SELECT COUNT(*) FROM doc").fetchone()[0] == len(entries)
    con.close()
    assert len(list(raw.glob("*.pdf"))) == len(entries)     # nothing moved or deleted
