import csv
import json
from pathlib import Path

from reality_engine.scripts import sql_ab_sample as s


def _make_fixture(base):
    a3 = base / "pilot10" / "answer_a3"
    a3.mkdir(parents=True, exist_ok=True)
    qs = [{"qid": f"C{i}-001", "question": f"q{i}", "as_of": "2026-11-04"} for i in range(5)]
    (a3 / "C0_questions.json").write_text(json.dumps(qs), encoding="utf-8")
    grades = a3 / "grades.tsv"
    grades.write_text("qid\tgrade\tcause\treason\nC0-001\tP\tread\tx\n", encoding="utf-8")
    u8 = base / "u8.csv"
    with open(u8, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "symbol", "grade", "question", "as_of"])
        w.writerow(["U1", "ACME", "right", "uq", "2026-11-04"])
        w.writerow(["U2", "ACME", "partly", "uq2", "2026-11-04"])
    q12 = base / "q12.csv"
    with open(q12, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "symbol", "grade", "question", "as_of"])
        w.writerow(["Q1", "BETA", "right", "qq", "2026-10-19"])
    return base, u8, q12


def test_determinism_small_fixture():
    base = Path("fix_t179")
    if base.exists():
        import shutil; shutil.rmtree(base)
    base.mkdir()
    base, u8, q12 = _make_fixture(base)
    rows1 = s.build_sample(
        pilot10_dir=base / "pilot10",
        grades_path=base / "pilot10" / "answer_a3" / "grades.tsv",
        pilot10_db="P.db",
        u8_csv=u8,
        q12_csv=q12,
        u8_db="U.db",
        q12_db="Q.db",
        seed=123,
    )
    rows2 = s.build_sample(
        pilot10_dir=base / "pilot10",
        grades_path=base / "pilot10" / "answer_a3" / "grades.tsv",
        pilot10_db="P.db",
        u8_csv=u8,
        q12_csv=q12,
        u8_db="U.db",
        q12_db="Q.db",
        seed=123,
    )
    assert rows1 == rows2
    from collections import Counter
    c = Counter(r["symbol"] for r in rows1)
    assert all(v <= 12 for v in c.values())


def test_cli_writes_csv():
    base = Path("fix_t179b")
    if base.exists():
        import shutil; shutil.rmtree(base)
    base.mkdir()
    base, u8, q12 = _make_fixture(base)
    out = base / "out"
    rc = s.main(["--out", str(out), "--seed", "1", "--pilot10-dir", str(base / "pilot10"),
                 "--u8-csv", str(u8), "--q12-csv", str(q12), "--pilot10-db", "P.db",
                 "--u8-db", "U.db", "--q12-db", "Q.db"])
    assert rc == 0
    assert (out / "questions.csv").exists()
    with open(out / "questions.csv") as fh:
        r = list(csv.DictReader(fh))
    assert len(r) >= 1
    assert set(r[0].keys()) == {"qid", "symbol", "store path", "as_of", "question", "earlier_grade", "source_run"}