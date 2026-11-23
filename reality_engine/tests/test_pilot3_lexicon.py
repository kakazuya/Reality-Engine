"""T-194: the sector topic vocabulary and the in-place re-tag that uses it.

The share of statements tagged ``other`` is the measure: 1,064 of 2,765 (38%) on the AUROPHARMA store, where a
pharma call's own words (USFDA, OAI, Form 483, price erosion, ANDA) were not in the general topics.yaml.

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_lexicon.py -q
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from reality_engine.pilot3 import transcripts

TMP = Path(__file__).resolve().parents[2] / ".tmp"
DB = TMP / "pilot3_retag_test.db"
PHARMA_TAGS = {"usfda_inspection", "oai", "vai", "warning_letter", "form_483", "price_erosion", "anda", "launch",
               "biosimilar", "api_pli", "specialty_injectables"}


def test_a_sector_vocabulary_applies_to_its_family_only():
    pharma = {tag for tag, _pats, _c in transcripts.load_topics("pharma")[0]}
    assert PHARMA_TAGS <= pharma, PHARMA_TAGS - pharma
    assert "usfda_inspection" not in {tag for tag, _pats, _c in transcripts.load_topics("nbfc")[0]}
    assert "usfda_inspection" not in {tag for tag, _pats, _c in transcripts.load_topics()[0]}


def test_the_tagger_marks_the_pharma_themes_from_what_management_said():
    topics, _people = transcripts.load_topics("pharma")
    tags = set(transcripts.tag_topics(
        topics, "AUROPHARMA",
        "The USFDA inspection at Unit VII ended with a Form 483 and two OAI observations; ANDA approvals held up."))
    assert {"usfda_inspection", "form_483", "oai", "anda"} <= tags
    general = set(transcripts.tag_topics(transcripts.load_topics()[0], "AUROPHARMA",
                                         "The USFDA inspection at Unit VII ended with a Form 483."))
    assert "usfda_inspection" not in general                # no sector, no sector tag


def _store() -> None:
    TMP.mkdir(exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(transcripts.SCHEMA)
    for seq, (quote, topics) in enumerate((("Pen-G volumes for the US market were in line.", "other"),
                                           ("Price erosion in the US generics business continued and ANDA approvals "
                                            "were steady.", "other"),
                                           ("Margins were steady this quarter.", "margin")), 1):
        con.execute("INSERT INTO transcript_statement(symbol,doc_key,call_date,call_period,page,seq,speaker,role,"
                    "section,topics,period_discussed,period_source,numbers_json,statement,quote,is_fragment,known_at,"
                    "known_at_source,extractor_rule) VALUES ('XYZ','call.pdf','2026-03-10','Q3FY26',1,?,'A B','ceo',"
                    "'qa',?,'Q3FY26','t','[]',?,?,0,'2026-03-12T10:00:00','x','t')",
                    (seq, topics, quote, quote))
    con.commit()
    con.close()


def test_retag_reports_the_other_share_before_and_after(monkeypatch):
    _store()
    monkeypatch.setattr(transcripts, "_sector_of", lambda _symbol: "pharma")
    stats = transcripts.retag(str(DB), ["XYZ"])["XYZ"]
    assert stats["rows"] == 3
    assert stats["other_before_pct"] == 66.7
    assert stats["other_after_pct"] < stats["other_before_pct"]
    con = sqlite3.connect(DB)
    tags = [row[0] for row in con.execute("SELECT topics FROM transcript_statement ORDER BY id")]
    con.close()
    assert "price_erosion" in tags[1] and "anda" in tags[1]
    assert tags[2] == "margin"                              # a tagger output that already answered is kept
