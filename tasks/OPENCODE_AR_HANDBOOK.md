# OpenCode Zen route for annual reports: handbook

Written 2026-10-12, revised the same day after the first runs. Authority: `tasks/FRAMEWORK.md`, then `tasks/STATE.md`.
This handbook covers ONE job: reading annual reports (ARs) with the OpenCode **Zen** free models.

## How it works

ARs are read page by page by free models. Every fact is stored with its page and quote in
`reality_engine/data/ar_facts.db`. Two independent workers share the queue:

| Worker | Readers | Order | How it runs |
|---|---|---|---|
| Python run (`ingest_annual_reports.py`) | LongCat on OpenCode **Go**, Gemma 4 31B on 8 Google keys | newest filing first | detached process, kept alive by the resource watchdog |
| Zen route (`ar_queue.py`) | OpenCode **Zen** free models | oldest filing first | `export` -> `drive` -> `import` |

- **Claims keep the two apart.** `export` claims reports in table `ar_claims`. The Python run skips claimed reports,
  and `export` skips any report the Python run has started. Claims are atomic; an unimported claim expires after
  72 hours.
- **Why a driver, not subagents.** The Zen free tier only answers from inside OpenCode.
  - It refused custom agent prompts (`.opencode/agents/ar-reader.md`, 2026-10-12), so those agents were removed.
  - The built-in `general` subagent reads with the session's own model, so it can't test a named model.
  - An orchestrating OpenCode session runs out of context long before hundreds of pieces.
- **What `drive` does instead.** It starts one fresh `opencode run -m opencode/<model> -f <piece>` per piece, using
  OpenCode's stock agent and the background service's login.
  - The piece file is attached; the model uses no tools.
  - The answer is read from stdout and saved as `NNNN.out.txt`.
  - A failed piece is retried twice; after the third failure, the error is kept in `NNNN.err.txt`.
- **Logs.** `reality_engine/data/ar_queue/drive.log` has one line per piece.

## Rules

1. Quality over speed. Numbers are copied exactly as printed; no reader computes, converts or adds.
2. Only models that passed the admission test read production pieces. Passed: `longcat-2.5-preview-free`
   (25/25 on the Go API route). Any other model needs a pass on this route first.
3. Never edit `ar_facts.db` rows by hand. All writes go through `ar_queue.py import`.
4. Do not start, stop or edit the Python run, and do not change the prompt (`PROMPT` in `ingest_annual_reports.py`).
5. Free models only. "Model access is disabled" means a paid model was named.
6. RAM: each `opencode run` process takes about 170 MB. Keep the total at or below about 15 processes.
   The machine also runs the AR and deck jobs.

## Register of passed models

`reality_engine/scripts/zen_models.json` lists every model that passed, with its test result and slots. **A listed
model is never retested.** A rate-limited model benches itself for 20 min and rejoins by itself; no restart is needed.
Add a model there after it passes; restart the Zen worker to pick it up.

## Admission test (new model)

```
python -m reality_engine.scripts.ar_queue test-export --run t-<short> --model <zen-model-id>
python -m reality_engine.scripts.ar_queue drive --run t-<short> --workers 1
python -m reality_engine.scripts.ar_queue test-score --run t-<short>
```

**Pass** means all three of:
- 25/25 must-find facts;
- under 1% of numbers not found in the text;
- all 110 pieces answered.

The score is written to `t-<short>/SCORE.md`. Add one line to `tasks/ar_study/free_test/FINDINGS.md`.

Zen free models on 2026-10-12 16:40 (`opencode models`):
- `longcat-2.5-preview-free`: passed.
- Tests running: `mimo-v2.6-flash-free`, `step-5-preview-free`, `muse-spark-1.3-contributor-free`,
  `ling-3.1-flash-free`, `nemotron-3.5-lightning-free`, `nemotron-3-ultra-free`, `space-bunny-free`, `big-pickle`.
- Dead: `exo-free` (deprecated) and `ling-3.0-flash-fin-free` (unavailable).
- Gone from the list: `muse-spark-1.2-contributor-free` and `jev-1.13-free`.
- Muse prompts are used for Meta training. That is acceptable here: ARs are public filings.

## Production loop

```
python -m reality_engine.scripts.ar_queue export --run zen<NN> --docs 3 --model longcat-2.5-preview-free
python -m reality_engine.scripts.ar_queue drive --run zen<NN> --workers 3
python -m reality_engine.scripts.ar_queue import --run zen<NN>
python -m reality_engine.scripts.ar_queue status
```

- Use a new run name each batch. `--model` is stored on every fact as `zen:<model>`.
- `import` can be repeated safely. If a run has `.err.txt` pieces, run `drive` on it again, then `import` again.
- After import, check the value checks: `page` / `piece` = found in the text, `not_found` = not in the text.
  Stop and report if more than 2% are `not_found`.
- Several runs can be driven at once with `--run zen05,zen06`.

## Files

- `reality_engine/scripts/ar_queue.py`: export / drive / import / test-export / test-score / status.
- `reality_engine/data/ar_queue/<run>/`: `manifest.json`, `NNNN.prompt.txt`, `NNNN.out.txt` and `NNNN.err.txt`.
- `reality_engine/data/ar_queue/drive.log`: one line per piece read or failed.
- `reality_engine/data/ar_facts.db`: `ar_docs`, `ar_pieces`, `ar_facts` and `ar_claims`.
