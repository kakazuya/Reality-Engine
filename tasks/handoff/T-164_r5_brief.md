Ticket: T-164
Goal: T-164 round 5: make call-statement entity tags precise. Rounds 1-4 ran on Beam (branch Eagle-T164-statements, head af0dc0de); this round starts from that branch. Round 4 is good on everything except entity precision: statements are identical to a main-code rebuild for all 20 symbols, the hand lists are gone, the whole-turn lookup is fixed, tests pass. Scripts only, no AI, no company lists.
Evidence: controller's own sample of 12 u8 statements with entities after round 4 (the worker claimed 99.2%; the controller found about half wrong):
- person names tagged: "Prashant", "Souza" (from "Mr. Sunil D'Souza"), "Ankit", "Nitin Padmanabhan Perfect" + "Nitin" + "Padmanabhan" + "Perfect";
- fragments beside the full span in the same statement: "Azure Cognitive Search" + "Cognitive" + "Azure";
- generic words: "Drink" (from "Ready- to-Drink"), "AI", "IT", "Services Industry";
- good ones to keep: "Home Loans", "Organic India", "North America", "BFSI", "DOGE", "Azure Cognitive Search", NGC, QRSAM, Dahlias, BSNL.
Grader on round 3 also listed misses that must be found: Teradata, Snowflake, Kochi Metro, Chennai Metro, Madhya Pradesh, NourishCo, DRDO, Vadhavan Port. Virupaksha is not in the main-code statements at all (statement splitting drops that page-break turn): report it, do not change splitting.
Steps:
1. Persons out: drop any span that is a speaker name or part of one in the same call (transcript_statement.speaker values, the participant block, tokens after Mr./Ms./Mrs./Dr./Shri, and first names used as direct address "Prashant, ..." when that name is a call speaker or participant).
2. Longest span wins: when a span is inside another tagged span of the same statement, drop the shorter one.
3. Single words: keep a single word only if it is an all-caps acronym of 2-6 letters that is not a finance metric in the lexicon and not an ordinary word (AI, IT stay out unless part of a longer name), or a capitalised word not in reality_engine/pilot3/en_vocab.txt that recurs in >= 2 statements of the call; hyphen-split pieces ("Drink" from "Ready- to-Drink") never.
4. Measure honestly on a NEW seed (seed 5164) 40 statements with entities per store from rebuilt .tmp/t164/u8.db and q12.db: write .tmp/t164/r5_entity.csv with statement text, each entity and right/wrong; precision must be >= 85% per store; recall on 20 statements per store that contain a capitalised multi-word name and no entity. The controller will regrade your csv rows independently, so mark honestly.
5. Keep the zero diff against the main-code baseline (.tmp/t164/main_u8.db, main_q12.db).
Files: reality_engine/pilot3/transcripts.py, reality_engine/tests/test_pilot3_transcripts.py (a test per step with the real texts above), docs/PILOT3_BLUEPRINT.md, docs/DEVELOPER_GUIDE.md.
Accept: (a) pytest -p no:cacheprovider per file: test_pilot3_transcripts, test_pilot3_speakers, test_pilot3_kpi, test_pilot3_no_company_literals, test_pilot3_guidance, test_pilot3_answer_check, test_pilot3_doc_identity, test_pilot3_profile, plugins/reality-data/tests/test_lookups_pilot3.py, test_lookups_docs: all pass; (b) baseline diff zero; (c) r5_entity.csv >= 85% per store; (d) docs; (e) exact tool-call count.
Stop if: a rule needs a company or person list.
Budget: 2 hours, <=100 tool calls, <=20 before first edit. Commit your work. Do not edit tasks/STATE.md. Do not write D:/. Do not commit PROGRESS_NOTES.md.
