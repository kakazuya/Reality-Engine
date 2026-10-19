# Prompt v3 changes — v2 -> v3, and the 6.6 loader gate

**Date:** 2026-10-20 03:54 IST, DeepSeek (Hotline job 3)
**Inputs:** `prompt_v2.md` (schema lines 7–27, rules 29–45); `review_readers_1.md` §6 lines 144–204 (fixes
6.1–6.10); `concall_deepseek.py` and `concall_pilot.py` for the `cc_items` DDL and loader behaviour. `concall_facts.db`
was not opened in this job; field names below come from the loader DDL and the review.
**Output:** `prompt_v3.md`. No database, loader, job or `cc_*` table was modified.

## 1. Rule map (v2 -> v3)

| v2 | v3 | Change |
|---|---|---|
| 1 Quotes | 1 | Kept. Added the numeric value-in-quote sentence and the rule-3 exception pointer (prompt half of 6.6). |
| 2 basis | 5 | Kept. 6.9 added: if `metric` already says standalone/consolidated, set `basis` to it; `segment` only when the call states that figure is for a segment; else `unknown`. |
| 3 direction | 4 | Kept. 6.3 added: "well on track" / "maintain" / "reiterate" / "stick to" / "on course" -> `maintained`, never `new`; `new` only for a first-introduced figure. |
| 4 Do not infer | 11 | Kept, renumbered; wording unchanged. |
| 5 Attribute correctly | 3 + 6 | Split. Analyst-origin numbers now rule 3 (6.2). Management corrections and "yes" handling stay in rule 6. |
| 6 Guidance is the company's own outlook | 6 | Kept; extended to exclude a parent/global figure as well as an industry figure or analyst estimate (6.1). |
| 7 Capacity is not capex | 7 | Kept; merged with 6.8: a capex item needs a money amount, else put it in `capacity_and_projects` or qualitative guidance. |
| 8 Inconsistent figures | 10 | Kept; 6.7 merged. Names the fields where the flag can live: `metric`, `statement`, `inflow_or_pipeline`. |
| 9 management_tone | 12 | Kept, renumbered. |
| 10 investor_takeaway | 13 | Kept, renumbered. |

**New rules**

| Review fix | v3 | What was added |
|---|---|---|
| 6.1 Entity/scope for capex and guidance | 2 | Name the entity (company / subsidiary / JV / parent-global) before a capex or guidance item; JV/project total or parent/global figure is not the company's; company's own share goes in `amount` (capex) or `value` (guidance); label "JV total, not company capex" / "global parent, not India"; name the subsidiary/JV. Includes the short ELITe and BASF examples. |
| 6.2 Analyst-origin numbers | 3 | A number only in an analyst's question never goes into `key_numbers`, `order_book`, `guidance` or `capex`; if confirmed, use the exact "(confirmed analyst's figure)" label, the analyst's number+question in `question_gist` (`order_book`: `inflow_or_pipeline`), commitment date in `period`/`as_of`, and quote management's confirmation; otherwise omit. Includes the SINGERIND Rs 2.3 crore example. |
| 6.3 Direction for reiterated targets | 4 | Merged into v3 rule 4 (v2 rule 3). |
| 6.4 Unit field | 9 | `unit` is a unit token, never a noun phrase; multiple as value 2/unit x or value double/unit x; inconsistent transcript unit -> `unclear` and say why. |
| 6.5 Period/as_of | 8 | Reporting period or measurement date, not a start date or call date; cumulative capex "since May 2023" or fiscal year; orders use order-book date, completion in `inflow_or_pipeline`. |
| 6.6 Value-in-quote gate | 1 + loader gate | Prompt half in rule 1; mechanical half specified in §3 below. |
| 6.7 Inconsistent figures | 10 | Merged into v2 rule 8 (now v3 rule 10). |
| 6.8 Capex amount required | 7 | Merged into v2 rule 7. |
| 6.9 Basis when metric says standalone/consolidated | 5 | Merged into v2 rule 2. |
| 6.10 Name the subsidiary/JV | 2 | Merged into 6.1 (v3 rule 2). |

## 2. Schema and loader compatibility

- **No v2 field renamed or removed.** All v2 list names, field names, enum values and ordering are unchanged. The four
  placeholders are unchanged: `{company}`, `{symbol}`, `{date}`, `{text}`.
- **One optional field placement added:** `question_gist` in `guidance`, `capex` and `key_numbers` (the key already
  exists in `analyst_pushback`; no new field name). It exists because 6.2 and 6.6 require the analyst's number and
  question to be checkable somewhere, and these three lists had no field for it. `order_book` already has
  `inflow_or_pipeline`; `analyst_pushback` already has `question_gist`.
- `cc_items` is unaffected: the loader still writes `value` or `amount` into `cc_items.value`, and `question_gist` lives
  only inside `item_json`. No DDL change, no column rename, no query change. Readers that ignore the field are unaffected;
  it is filled only for a confirmed analyst's figure (prompt rule 3).
- The gate must read the item dict before insertion, not the `cc_items` row, so it sees `question_gist` and `purpose`.
- **Not wired yet:** `concall_deepseek.py` still reads `prompt_v2.md` (line 122). Claude must switch that one line to
  `prompt_v3.md`; until then the new rules and gate are not in effect. This job did not edit the loader.

## 3. 6.6 mechanical value-in-quote gate — precise spec

### 3.1 Where it goes

Hook: `reality_engine/scripts/concall_deepseek.py`, `save()`, inside the `for k in LISTS` / `for i, it` loop, **before**
`INSERT INTO cc_items` (currently line ~143). Add a pure function in `reality_engine/scripts/concall_pilot.py`, e.g.
`value_in_quote_ok(list_name, item) -> (bool, reason)`, and call it for every reader (DeepSeek, `beam-free`, MiniMax,
LongCat) and from `renormalise()` so a re-save cannot bypass it. It is additional to `machine_check`: `machine_check`
checks the value's numbers against the **whole transcript** (`bad_number`), this gate checks them against the item's
**own quote**.

### 3.2 Which lists, which fields

| List | Numeric field | Label carrier (exact phrase) | Analyst-number carrier |
|---|---|---|---|
| `key_numbers` | `value` | `metric` | `question_gist` |
| `guidance` | `value` (only if numeric) | `metric` | `question_gist` |
| `capex` | `amount` | `purpose` | `question_gist` |
| `order_book` | `value` | `inflow_or_pipeline` | `inflow_or_pipeline` |

Anything else (`capacity_and_projects`, commentary lists, tone, takeaway) is out of scope.

### 3.3 What counts as a number

- Read the field as text; strip currency symbols, commas and whitespace; extract every `\d+(?:\.\d+)?`.
- `1,600` -> `1600`; `2.30` -> `2.3`; `15%` -> `15`; `250-270` -> `250` and `270`; `Rs 2.3 crore` -> `2.3`.
- Compare tokens as decimal values (so `2.3` = `2.30`, `1600` = `1,600` = `1600.0`), token by token, not by substring
  (`60` must not match `1,600`).
- No numeric token -> **pass automatically**. This covers qualitative guidance ("below depreciation") and an empty
  `capex.amount`; an empty capex amount is a 6.8 failure, not a 6.6 failure.
- Spelled-out numbers ("double", "one thousand") are not numeric tokens. They pass this gate; 6.4 handles the unit.

### 3.4 What passes

**P1.** The numeric field has no numeric token. Pass.

**P2.** Every numeric token of the value appears in the item's own `quote` (after the same normalization). Pass.
The label is irrelevant if the number is in the quote. Percent/currency/commas/sign are not part of the match; every
endpoint of a range must be present (`250-270` needs both `250` and `270`).

**P3. Confirmed-analyst exception.** Pass only if **all three** hold:

1. The label carrier contains the exact phrase `(confirmed analyst's figure)` — case-insensitive, optional whitespace,
   straight or curly apostrophe, e.g. regex `\(\s*confirmed analyst['’]s figure\s*\)`.
2. Every numeric token of the value appears in the analyst-number carrier (`question_gist`; `order_book`:
   `inflow_or_pipeline`). A carrier that is missing/empty fails.
3. The `quote` is management's confirmation and is not a bare "yes": after stripping punctuation, at least **six**
   whitespace-separated tokens, and it is not composed only of confirmation words
   (`yes/yeah/yep/no/nope/correct/right/true/absolutely/confirmed/sure/okay/ok/exactly/indeed/definitely`).
   Example that fails: "Yes, Laksh, absolutely." (three tokens).

Otherwise (not P1, not P2, and P3 does not hold) -> **fail**.

### 3.5 What fails

- A numeric value whose token is absent from `quote` and whose P3 exception does not hold -> `number_not_in_quote`.
- The label is present but the number is absent from `question_gist` / `inflow_or_pipeline` -> `analyst_number_missing`.
- The label and analyst-number carrier are valid but `quote` is empty -> `quote_empty`.
- The label and analyst-number carrier are valid but `quote` is a bare confirmation -> `bare_confirmation`.

The gate does **not** check speaker, scope, period, direction, basis, unit, or whether the figure is the company's own.
Those stay with prompt rules 2/4/5/8/9 and `cc_item_checks.speaker_role`. A capex item can pass this gate and still be
wrong under rule 2 (the ESTER JV total is exactly that case). The gate is necessary, not sufficient.

### 3.6 Action on failure

- Drop the item from that list before the insert; do **not** rewrite `value`, `unit`, `quote` or `metric`, and do not
  insert a partial row. `status` stays `ok`; the document simply has one fewer item.
- Record counts per list in `cc_docs.checks_json` (e.g. `{"value_in_quote": {"checked": N, "dropped": M, "by_list":
  {...}, "samples": [...]}}`) and one WARNING log line with `doc_id`, list, idx, value and a truncated quote. Do not
  create a new table and do not touch other docs.
- This is the same shape as `machine_check`'s existing drop (`continue`), so it does not change the DB schema.

### 3.7 Audit / backfill

`reality_engine/scripts/concall_facts_checks.py` currently computes `cc_item_checks.value_in_quote`; update its predicate
to exactly P1/P2/P3 (read `item_json` for `question_gist` and `purpose`), then re-run it. P1 rows may stay NULL (not
applicable) or become 1, but never 0. Rows with `value_in_quote = 0` are the current violations; they can be listed
read-only with:

```sql
SELECT i.doc_id, i.list_name, i.idx, i.metric, i.value, i.quote
FROM cc_items i JOIN cc_item_checks c USING (doc_id, list_name, idx)
WHERE c.value_in_quote = 0;
```

The review found `value_in_quote` NULL for Beam and MiniMax rows, so run the checks script before quoting a pass rate.
Do not delete or update those rows as part of this gate; quarantining existing wrong rows is Claude's call.

### 3.8 Worked examples

| Case | Item | Result |
|---|---|---|
| Value in quote | `key_numbers.value = "2.3"`, quote "... income tax paid is Rs. 2.3 crores ..." | pass (P2) |
| Analyst number, no label | `key_numbers.value = "2.3"`, quote "the advance tax is always paid based on the projection ..." | fail `number_not_in_quote` |
| Analyst order, bare quote | `order_book.value = "200"`, quote "Yes, Laksh, absolutely.", `inflow_or_pipeline` labels the analyst figure and names 200 | fail `bare_confirmation` |
| Analyst number, labelled | `key_numbers.value = "200"`, `metric` has the label, `question_gist` names the analyst and 200, quote "Yes, we have received that order; it completes by June 2027" | pass (P3) |
| JV total in capex | `capex.amount = "1,600"`, quote "That is a project of about INR1,600 crores capex." | pass this gate; rule 2 still rejects it unless `amount` is Ester's share and `purpose` labels the JV total |
| Range half-stated | `value = "250-270"`, quote mentions only 250 | fail (270 missing) |
| Qualitative guidance | `guidance.value = "below depreciation"` | pass (P1; no numeric token) |
| Empty capex | `capex.amount = ""` | pass this gate; drop under 6.8 |

## 4. Length

`prompt_v3.md` is ~6.5 KB vs ~3.9 KB for v2: the 13-rule block, the two required short examples, and three optional
`question_gist` keys. No schema block was reflowed beyond adding those keys. At ~19,000 transcripts the extra
prompt tokens are small relative to transcript tokens; the rules that cost the most (scope, analyst, gate) are the ones
that prevent a wrong row, which is cheaper than re-reading a transcript.
