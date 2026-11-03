# night_eval: the night loop's deterministic checks

Scripts for `tasks/night_loop/GOAL.md` (v2). They read the question set and a branch's `pilot3.db`; they never
call a model, never open a network socket, and never print a hidden-split question. Standard library + sqlite3.

| Script | Answers |
|---|---|
| `qset.py check` | Phase 1 checks Q1 (sector fit), Q2 (lens / order / document-type coverage), Q3 (variations, near-duplicates) + the line schema |
| `qset.py split` | the fixed 70 / 30 hash split: `dev.jsonl` beside the set, hidden to `.tmp/night_eval/hidden.jsonl` |
| `answerable.py` | A1: every need a question names, met or not, point in time (`known_at <= as_of`) |
| `guards.py` | A3 provenance, A4 counts, A5 build, A6 record, A7 cost |
| `decide.py` | ACCEPT / REJECT with every reason |
| `run_loop.py` | one hidden headless Opus session (the wrapper's call; the tests only dry-run it) |
| `audit.py` | hidden-split reads in loop and worker transcripts |

## Question set

JSON Lines, one question per line: `{qid, symbol, sector, text, variations: [str], order: 1|2|3, lens,
sector_fit: [metric id], from_mids: [str] | "new", new_reason, as_of: YYYY-MM-DD, answer_kind, needs: [need]}`.
A need is `{"kind": "row", "table": <typed table>, "metric": <metric/line_item/category>, "period":
FY26|Q1FY27|H1FY26|9MFY26|YYYY-MM-DD, "basis": consolidated|standalone|null}` or `{"kind": "text", "doc_type":
<doc.doc_type>, "terms": [str], "period": optional}`. Sector vocabularies: `tasks/night_loop/sector_vocab.json`.

## The commands

```bash
python -m reality_engine.night_eval.qset check tasks/night_loop/questions --out .tmp/night_eval/qset.json
python -m reality_engine.night_eval.qset split tasks/night_loop/questions
python -m reality_engine.night_eval.answerable --db <pilot3.db> --qset <dev|hidden>.jsonl --out base_dev.json
python -m reality_engine.night_eval.answerable --db <pilot3.db> --qset <hidden>.jsonl --hidden --out base_hidden.json
python -m reality_engine.night_eval.guards --db <pilot3.db> --base main --branch loop_07 --a6 ok --out guards_cand.json
python -m reality_engine.night_eval.decide --base base_dev.json --base base_hidden.json \
    --cand cand_dev.json --cand cand_hidden.json --guards guards_cand.json --guards-base guards_base.json
python -m reality_engine.night_eval.audit D:\RealityEngine\night_loop\transcripts\loop_07.jsonl
python -m reality_engine.night_eval.run_loop --n 7 --prompt D:\RealityEngine\night_loop\prompts\loop_07.txt
```

`guards --parts kpi` overrides the changed build parts; without `--base-db` A3 scores every quoted row up to
`--limit` (default 4000) instead of only the rows the branch added. `decide` needs both splits of `answerable`;
the tell is each file's own `hidden` flag. A4 and A7 are only compared when `--guards-base` is given.

## The thresholds (GOAL section 2 and 3)

Q1 no violation; Q2 each lens >= 10 per company, orders 1st >= 40 %, 2nd >= 25 %, 3rd >= 10 %; Q3 every
order-1 question has >= 3 forms and no pair of questions exceeds 0.8 token Jaccard. A1 dev must rise, hidden and
every company must hold. A3 >= 98 %; A4 counts must not rise; A5 must pass (no literal, no protected file, the
build parts run with sockets blocked); A6 green; A7 build seconds / pages read may rise <= 20 % unless A1-dev
gains at least a percentage point. A hidden question is never printed and never committed.

The hidden split is `int(sha256(qid)[:8], 16) % 10 < 7` = dev, so the same qid always lands on the same side.

## Tests

```bash
python -m pytest reality_engine/tests/test_night_eval.py -q
```

The test builds its own sqlite fixture databases and question sets under `.tmp/night_eval/test/`, and its own
temporary git repository for the A5 literal and protected-file checks. pytest's `tmp_path` is not used (the dsh
sandbox denies it).
