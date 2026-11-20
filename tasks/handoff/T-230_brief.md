# T-230 brief: observation schema for deck and note visuals (stage A only)

Ticket: T-230 (Shivam 21 Nov 2026; promotes idea I-016 in tasks/IDEA_BOX.md). Reviewer: Wolf (Opus). Do ONLY stage A,
then stop and report. Later stages come as follow-up messages.

Goal: deck and annual-report visuals (maps of plants/ports, capacity bars, revenue-mix pies, plant lists) must be
stored so their figures can feed a factor study: one row per printed quantity WITH its meaning. Shivam: this is a
schema problem, not a reading problem. The flat `page_cell` (row_label, col_header, value_text) loses the slide's
groups, which chart a number belongs to, and whether it is the company's figure or the industry's.

Evidence: (real; check them yourself)
- c08 JSW Infrastructure, deck `.../investor_presentation/20792b21-8723-4898-8e7c-16788527e1a0.pdf` page 14: port
  projects in mtpa under three groups "Projects Approved / Projects Under Review / Pipeline of Potential Projects"
  plus a FY25 177 -> FY28E 292 -> FY30E 400 capacity path. hy4-flash-free read 12 of 14 values right, swapped
  LPG at Jaigarh 1.8 / Container New Mangalore 2.0, and kept no group. Text layer: store `doc_page` text.
- c26 Nelcast, deck `.../f95278f2-78d1-4c6d-9322-6c1cc9d23785.pdf` page 20: two charts, tractor industry sales
  (thousand units, FY20-24: 705, 899, 842, 945, 874) and M&HCV industry sales (lakh units: 2.2 ... 3.7); both stored
  under one label "Sale units (in Thousands)", no series, no scope (both are industry figures, not Nelcast's).
- Stores: `D:/RealityEngine/tg_build/measure10/cNN/cNN.db` (read-only): `doc`, `doc_page`, `kpi_series`, routes in
  `cNN/routes.csv` (route table_or_chart). hy4 page cells for 80 stores: `D:/RealityEngine/hy4_quota/cNN_hy4.db`
  (`page_read`, `page_cell`; read-only; a job is still writing some of them - open read-only, tolerate a missing table).
- Existing pieces to reuse, not rewrite: page image rendering and the hy4 call in `reality_engine/v2/page_reader.py`
  and `reality_engine/scripts/extract_deck_figures.py` (model table ~line 109; `reasoning_effort: "none"` required;
  stable session ids via `reality_engine/scripts/go_session.session_id`; key OPENCODE_GO_API_KEY, never print it).
- Schema contract: `docs/V2_SCHEMA_CONTRACT.md`; idea text: tasks/IDEA_BOX.md I-016 (measure dictionary, dimension
  vocabularies, verification by parts-sum-to-total, XBRL, the same figure in another document).

Steps (stage A):
1. Schema (write it as a new section in `docs/V2_SCHEMA_CONTRACT.md`): table `observation` with company symbol, doc_key,
   page, region (x0,y0,x1,y1 when known), known_at (copied from the doc row, never the model), measure (dictionary id)
   + printed_label verbatim + printed_axis verbatim, value, value_text verbatim, unit, scale, period (fiscal label or
   date) + period_kind (actual / estimate / target), dims as columns (segment, product, geography, plant, customer),
   group_path verbatim (e.g. "Projects Under Review"), stage (operating / under_construction / approved /
   under_review / potential / null), series_id (which chart/table on the page), entity_scope (company / subsidiary /
   industry / country / customer / peer), status (verified / unverified / quarantined) + status_reason. Plus
   `measure_dict` (id, name, unit family, node in the T-228 driver tree: revenue.volume, capacity.add, ...) and
   `dim_vocab` (kind, canonical, aliases).
2. Reader: one hy4 prompt for a visual page (page image + its text layer) returning observations in that shape as JSON.
   Script checks (independent of the model): value_text must be in the page text layer when the page has one (else
   unverified); group_path and printed_label must be substrings of the text layer when it has text; units by family;
   a series whose parts carry a printed total must sum to it within rounding (pass -> verified for those parts).
3. Writer: `reality_engine/v2/observations.py` writes to a separate output DB (`--out`, default `.tmp/t230/obs.db`),
   never a store. CLI: --stores, --limit, --workers.
4. Tests `reality_engine/tests/test_observations.py` (synthetic, no network): substring checks, unit family, parts-sum,
   known_at copied, schema columns present.
5. Pilot: deck pages routed table_or_chart from c08, c26 and 3 more stores chosen by seed 11; at most 150 pages; the two
   evidence pages must be in it.
6. Report (under 40 lines; full detail in `.tmp/t230/report_a.md`): counts by status, measure, scope, stage; the two
   evidence pages' observations in full; 40 random observations (seed 17) each with page ref and the page text excerpt
   around the value; every error.

Files: new `reality_engine/v2/observations.py`, `reality_engine/tests/test_observations.py`; edit only
`docs/V2_SCHEMA_CONTRACT.md` (new section). Do not edit tasks/STATE.md.

Accept: `python -m pytest -q reality_engine/tests/test_observations.py` passes; typecheck clean; pilot report written.

Limits and pitfalls:
- Read-only on stores and hy4_quota DBs; writes only in your worktree.
- hy4-flash-free only (free on Go). No paid model. Another hy4 job runs with ~200 requests in flight on the same key;
  keep the pilot at --workers 10 and log any 429.
- Never store a model-computed number as verified (a sum, a share the slide did not print).
- Industry and country figures are kept, but with entity_scope set: they must never look like the company's.
- CPU is busy; run pytest per file.

Stop if:
- hy4 returns empty or non-JSON on more than 20% of pilot pages: stop, report 5 raw replies.
- More than 10% of observations quarantined: stop with examples.

Budget: about 2-3 hours, DeepSeek max effort.
