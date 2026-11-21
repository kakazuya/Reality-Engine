# T-234 brief: free-model reader bake-off vs hy4 (quality, precision, accuracy, speed, tokens)

Ticket: T-234 (Shivam 22 Nov 2026). Reviewer: Wolf (Opus). Free models only; no paid model, no DeepInfra.

Goal: hy4-flash-free's daily quota (reset 05:30 IST) stalls deck and annual-report reading. Measure whether free
readers can take part of the load without lowering quality. Shivam: "measure speed and tokens used as well with
quality, precision and accuracy".

Candidates:
- Image pages (page image + text layer, the T-230 observation prompt unchanged): `google/gemma-4-31b-it` via Google AI
  Studio OpenAI-compatible endpoint (`https://generativelanguage.googleapis.com/v1beta/openai`, key env
  `GEMINI_API_KEY` only, never rotate other keys), Kilo free `nvidia/nemotron-3.5-super-vl:free`,
  `inclusionai/ling-3.2-flash:free`, `particle-ai/particle-1:free` (Kilo base `https://api.kilo.ai/api/gateway`,
  `KILO_API_KEY`). Baseline: hy4 rows already stored (no new hy4 calls; quota is out).
- Text pages (text layer only): Kilo free `baidu/ernie-5.5-flash-preview:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`.

Evidence:
- Reader registry: `reality_engine/scripts/extract_deck_figures.py:103-170` (MODELS; Kilo entries at 128-150 show the
  shape). `reality_engine/v2/observations.py:67-75` hard-codes READER/OBS_READER = hy4.
- Golden: `reality_engine/tests/golden/observations.jsonl` 241 graded rows on 228 pages (158 RIGHT, 45 MINOR, 38 WRONG),
  scorer `reality_engine/scripts/regress.py`, selectors `--only` (docs/FIX_LOOP.md).
- hy4 baseline rows: `D:/RealityEngine/t230/obs_91_i.db` (91 cos), `.tmp/t232read/obs_decks394.db` in the MAIN
  checkout `C:/Users/warri/Downloads/Info_Diffusion_Model` (new cos; a job appends to it after 05:30: copy it first),
  `.tmp/t230ar/obs_ar_91.db` (annual reports, main checkout; copy it).
- Stores: `D:/RealityEngine/tg_build/measure10`, `D:/RealityEngine/tg_build/decks403` (read-only).

Steps:
1. Add a `--reader <MODELS name>` option to observations.py (default hy4, behaviour unchanged) and MODELS entries for
   the six candidates (`key_env`, `base`; Gemma entry with the Google base). Probe each with one page first; a 404 or
   no-image error = model recorded as unavailable, move on.
2. Image set: the 228 golden pages. Run each image model with `--only <selector>` into its own DB
   `D:/RealityEngine/t234/obs_<model>.db`, workers 8 (raise to 16 only if no 429s), same script checks.
3. Text set: 60 annual-report pages from obs_ar_91.db where hy4 stored >= 3 rows and the page has a good text layer
   (seed 234, list saved). Run ERNIE and Nemotron Ultra on text only. Also run the image models' text-only mode on
   these 60 only if cheap; optional.
4. Per model, measure and write `D:/RealityEngine/t234/bakeoff.csv` + `bakeoff.md`:
   - golden: RIGHT rows reproduced (accuracy/recall on graded rows), WRONG rows reproduced, newly produced value for
     each golden key;
   - vs hy4 on the same pages: rows matched on (measure, period, value within 0.5%), model-only rows, hy4-only rows;
   - script-check status mix: verified / unverified / quarantined share; verified rows per page;
   - precision proxy: share of model rows whose value appears in the page text layer (number match), and a seeded
     sample of 40 disagreement rows per model (model-only + mismatched) written to `disagree_<model>.jsonl` with page
     path for Wolf's hand-read (do not grade them yourself);
   - speed: pages/min at the concurrency used, median and p90 seconds per page, errors, 429s and Retry-After seen;
   - tokens: input and output tokens per page (from `usage`), total.
5. Tests for `--reader` (default unchanged, entry lookup) and the scorer; doc: V2_SCHEMA_CONTRACT section 17 "T-234
   reader option" + DEVELOPER_GUIDE reader list.

Files: `reality_engine/v2/observations.py` (only the reader option), `reality_engine/scripts/extract_deck_figures.py`
(MODELS entries only), new `reality_engine/scripts/reader_bakeoff.py` (scoring), tests, the two docs. Do not edit
tasks/STATE.md. If sandbox blocks D: writes, write under `.tmp/t234/` in your worktree and say so.

Pitfalls: do not call hy4 (quota out, and it is reserved for the deck run); never print keys; Kilo free models
rate-limit: back off on 429 with Retry-After, never loop; reasoning models may put JSON in reasoning text - parse
the content field only and count empty replies as failures.

Accept: tests pass; typecheck clean; `--reader` default reproduces hy4 behaviour (a recheck of 5 pages unchanged);
bakeoff.md under 40 lines with one row per model and the raw counts behind every percentage.

Stop if: a model needs a paid key; more than 3 of 6 models unavailable (report which and why).

Budget: about 2 hours, DeepSeek max effort.
