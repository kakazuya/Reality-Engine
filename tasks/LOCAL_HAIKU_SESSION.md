# Local Haiku session: finish the hard deck pages, then use spare quota on hard pages

Written 2026-10-15 ~23:10 by the co-pilot session (its context was 75% full). Shivam has spare weekly Pro quota today
and wants it used on Claude Haiku helper agents in a NEW local session. Read this file first. Background:
`tasks/STATE.md` (hand-off at the top).

## Usage rules (check before every wave)

- Check plan usage with the session tool `get_usage` (ToolSearch "select:mcp__ccd_session_mgmt__get_usage").
- Stop launching waves when the **5-hour window passes ~85%**. Wait for its reset, then continue.
  - Weekly was 30% at 23:00 on 10-15; it resets Friday 23:30.
- One wave = 10 Haiku agents in parallel, one folder of up to 12 slides each. A wave takes ~2-2.5 min and ~1.3M Haiku
  tokens.
- Keep your own context small:
  - never open images, prompts or answer files yourself (one spot-check per batch at most);
  - launch agents in the foreground in parallel waves of 10;
  - read only their one-line replies.

## Agent call (exactly this; one per folder)

`Agent(subagent_type="general-purpose", model="haiku", run_in_background=false, prompt=...)` with:

> Follow C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\claude_queue\<RUN>\AGENT_INSTRUCTIONS.md for the
> folder C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\claude_queue\<RUN>\<bNNN>. Read the pairs one at
> a time (Read the prompt file, then the image). Write each answer file with the Write tool. Do not re-open files you
> already handled, do not explain. Reply with one line: how many files you wrote.

Before launching, list which folders still lack answers, so finished folders are skipped:

```bash
cd reality_engine/data/claude_queue/<RUN> && for b in b*/; do i=$(ls $b*_image.jpg | wc -l); a=$(ls $b*.txt 2>/dev/null | grep -vc prompt); [ "$a" -lt "$i" ] && echo "${b%/} $a/$i"; done
```

## Step 1: batch 7: DONE and imported 10-16 ~01:30 (1,045 pages, branch deleted)

- RUN = `cloud_hard_20261015_141141`: 88 folders b000-b087. b000-b021 are DONE (12 answers each); b022-b087 remain.
- When every folder has its answers, import it, then remove the cloud branch and worktree:

```bash
python -m reality_engine.scripts.claude_page_queue import-deferred --run reality_engine/data/claude_queue/cloud_hard_20261015_141141
git worktree remove --force C:/Users/warri/Downloads/cloud-deck-hard-7 && git branch -D cloud/deck-hard-7 && git push origin --delete cloud/deck-hard-7
```

## Step 2: batch 8 (local, not started)

- RUN = `cloud_hard_20261015_141615`: 76 folders. b066-b075 DONE; b000-b065 remain (66 folders, ~7 waves). Same procedure. Afterwards remove `cloud-deck-hard-8` and
  `cloud/deck-hard-8`.
- Import prints `chart_trends` (rows in the `chart_trends` table: charts without printed values).
- After both batches every disagreement page is done. Batches 1-6 were already imported.

## Step 3: deck pages with NO figures (new, quota permitting)

- These are pages the free readers answered with zero figures although the page's text layer has >= 5 numbers.
- Export in chunks of ~500 pages:

```bash
python -m reality_engine.scripts.claude_page_queue export-hard --select nofig --pages 500 --per-agent 12
```

- The export claims the pages (pages.error = 'claude cloud claim <run>'). Run the folders as above, then import with
  `import-deferred --run <run folder>`.
- Unanswered pages return to their previous state automatically.
- Spot-check one folder first: many such pages may be genuinely figure-free (covers, contact pages). If Haiku finds
  figures on only a few, stop. Haiku also writes `CHART | ...` lines for charts without printed values; those go to
  `chart_trends`.
- The `--select nofig` mode was added 10-15 23:05 and is untested: check the first export's manifest before launching.

## Step 4: hard annual reports (investigate first, quota permitting)

Candidates are reports where many extracted numbers are not found in the source text. Size them:

```sql
-- ar_facts.db (read-only): reports with >10% of numbers not found
SELECT doc_id, symbol, fiscal_year, SUM(value_check='not_found') nf, COUNT(*) n FROM ar_facts WHERE value IS NOT NULL
GROUP BY doc_id HAVING n >= 50 AND 1.0*nf/n > 0.10 ORDER BY 1.0*nf/n DESC;
```

- On 10-15 there were ~141 such reports (~17.5k facts) not explained by the Coptic-digit font issue, which is already
  fixed.
- Look at a few first:
  - garbled text layer: needs page images, so treat it like decks;
  - scanned pages;
  - genuine misreads.
- Then decide whether a Haiku re-read helps.
- There is no export path for annual-report pages to Haiku yet. Design it before spending quota, and tell Shivam the
  plan and the expected quota cost.

## Do not

- Do not restart the annual-report workers to apply nothing. A restart costs ~5 min of warm-up, and killing only the
  parent orphans `--pieces-json` children; the watchdog now kills those.
- Do not use paid models (memory `feedback_free_models_only`).
- Keep each agent to one folder (<= 12 slides): above 100K tokens of context Haiku bills 5x on API/cloud.
