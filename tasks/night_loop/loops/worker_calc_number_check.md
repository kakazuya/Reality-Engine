# Worker: calculator tool and number checker

Goal: answer workers stop writing wrong sums and ten-times unit slips. They get a calculator tool with crore and lakh formatting, and a checker that recomputes each answer's numbers and refuses to record one that fails.

Ticket: T-072

Evidence: measured by Opus on 5 Nov from the 600 hand-read answers (`D:\RealityEngine\pilot10\answer_a2\`, one `<SYM>_answers.jsonl` per company; `event=answer` rows hold `qid`, `answer`, `numbers`).
- 31 of the 120 misses are sums or units. Real ones: ETERNAL-082 market cap written Rs 32.20 lakh crore (3.22 is right); HDFCBANK-022 Rs 3,41,79,459 crore (3,417,946 is right); HDFCBANK-030 a fall of 31.8 crore shares written 3.18 crore; HDFCBANK-097 gross NPA Rs 3,574 crore (about 35,736); SUNPHARMA-116 Rs 2,711.9 million written about Rs 27 crore (271); INFY-019 11,178 / 115 written 101.6x (97.2x); KEC-119 8,421 / 22,882 written 5.7% (36.8%); ETERNAL-057 Rs 48 crore called 9% of PAT (13%).
- The data was right in these; the worker's head sum was wrong. Workers have no calculator: the answer brief allows only MCP tools, and no tool computes.
- `D:\RealityEngine\pilot10\answer_a2\t072_dev.tsv`: columns `qid`, `kind` (`arith_miss` or `right`), `reason`: 16 known misses and 240 answers graded right. This is your whole development set. **Do not open `grades.tsv`, `grades_notes.txt`, `grades_firstpass_120.tsv` or `grading\`**: Opus scores your checker on the other misses and the other right answers.
- Answer format today: `{"qid","answer","numbers":[{"value","unit","period","source","quote"}],"status","tools"}`, written by `D:\RealityEngine\pilot10\answer_a2\record.py` (39 lines, outside the repo, no check at all).
- MCP tools: `plugins/reality-data/server/server.py` `pilot3_kpi` at line 427 onward is the pattern; helpers in `plugins/reality-data/server/lookups_pilot3.py`; tests `plugins/reality-data/tests/test_lookups_pilot3.py`.

Do:
1. Tool `pilot3_calc` in the reality-data server. Takes an arithmetic expression (+ - * / ** parentheses, sum, avg, min, max, round; evaluated by walking the AST, never `eval`) with optional named inputs and their units (rupees, crore, lakh, lakh crore, million, billion, shares, percent). Returns the exact value and, for money and share counts, all of: rupees, crore, lakh crore, and Indian digit grouping. Bad input returns a clear error, never a guess. Tool description must tell a worker to use it for every number not copied straight from a row.
2. `reality_engine/pilot3/number_check.py`, CLI `python -m reality_engine.pilot3.number_check <answers.jsonl | answer.json> [--tsv out.tsv]`. Answer format gains optional `formula` and `inputs` on each number. Checks, each with its own reason code in the output:
   - a number with `formula` and `inputs` is recomputed; it fails beyond its printed rounding;
   - each amount in the `answer` text, normalised to rupees through its unit words and digit grouping, must match a `numbers` entry; a match only at 10x, 100x or 1000x is a unit slip;
   - a `numbers` value against its own `quote`, same normalisation;
   - stated working in the text ("A / B is X", "X% of Y", "from A to B is C bps") is recomputed where both sides are readable;
   - comma grouping that is neither valid Indian nor Western is flagged.
   Old answers carry no `formula`, so the replay rests on the last four checks.
3. `reality_engine/pilot3/answer_record.py`: same CLI as `record.py` (`<SYM> start <qid>`, `<SYM> answer <file>`, writing `.tmp\<SYM>_answers.jsonl`), running the checker first. A failing answer is not recorded: print each failure and exit non-zero, so the worker fixes it. A second attempt on the same qid carrying `"check_override": "<reason>"` records it with the failures attached, so no question gets stuck and every override can be read.

Accept:
1. `python -m reality_engine.pilot3.number_check` replayed over all ten answer files; print per company answers, flagged, by reason code. On the dev set print which of the 16 are caught, and how many of the 240 right answers are flagged. Target: every ten-times or unit slip and every stated-working sum in the 16 caught; at most 12 of the 240 flagged. Read every flag on a right answer and say whether it is a false alarm or a real slip the grader missed. List misses the checker cannot catch (wrong logic, wrong choice of inputs) and why; do not stretch rules to reach them.
2. New tests from real rows of the dev set, in `reality_engine/tests/test_pilot3_number_check.py` and in the plugin test file for `pilot3_calc`. `python -m pytest <each file> -q`, one file per process. `mcp__code-tools__typecheck` on changed files: no new errors.

Rules: general rules only, no qid, company name or fixed value in the code. Do not edit answer files, the grader, any database, or the question bank. Do not start any model or worker run.

Files: `plugins/reality-data/server/server.py`, `plugins/reality-data/server/lookups_pilot3.py` or a new module beside it, `plugins/reality-data/tests/`, `reality_engine/pilot3/number_check.py`, `reality_engine/pilot3/answer_record.py`, `reality_engine/tests/test_pilot3_number_check.py`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide section O in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`.

Stop if: more than 12 of the 240 right answers stay flagged as false alarms after two rule rounds; report the rows.

Budget: 60 tool calls. End with the replay numbers, the flags read, test results and a `Docs updated:` line. Then wait: Opus reviews in this same session and sends the next round.
