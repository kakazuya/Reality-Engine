Goal: strict grade of audit checkpoint 3 of the widened deck read (obs_decks_wide.db): the first pages read under the two new options, pages with only 1-3 printed figures and pages whose text layer is jumbled (rows with text_source='text_layer_jumbled'). T-242. The deck prompt's author (Wolf) does not grade; Eagle records.
Evidence: pack C:/RealityEngine/t242/decks_wide_ckpt3/pack.jsonl (60 lines; part00/01), checkpoint rows first; each line has the row plus page_text and previous_page_text. Rubric: docs/grading/number_rubric.md (read first). The deck baseline passed 57/1/2/0 on normal table pages.
Steps:
1. Find each value in page_text. On a jumbled layer the label may sit far from its figure: the row is R only if the page clearly ties that figure to that label and period (same table row or chart series); a guessed pairing is W.
2. Check period from the printed column or series header, unit and scale from the printed unit line, and entity: the company's own figure, not market, peer or industry data.
3. Grade R / P / W / J.
Accept: final answer = one CSV block "n,grade,reason" with 60 lines, then counts R/P/W/J, the same counts for jumbled-layer rows alone, the W and J kinds with row numbers.
Stop if: a row's page text is empty: grade J "page not found" and go on. Never write a file.
Files: none written (read-only).
Budget: 60 minutes.
Ticket: T-242
