# Free models: in use vs idle (2026-10-14 03:10)

Purpose (Shivam): know which free models have spare capacity for other work (boilerplate coding, planning strategy
tests) once ingestion is done. Sources: `reader_watch.json` (free lists, refreshed every 2 h by `new_reader_check.py`),
`zen_models.json`, `tasks/ar_study/READER_FINDINGS.md`, deck verdicts in `reality_engine/data/reader_tests/`.

**Shared quotas matter more than the model list:**
- **Zen**: one daily allowance per machine/IP (~1,800 calls / ~35M tokens, reset 05:30 IST). Any Zen model used for
  other work eats the same allowance the annual-report Zen worker uses.
- **Kilo**: free models go through Kilo's own OpenRouter account; every Kilo key shares one quota per model.
- **Google**: per project and per model; Gemini Flash models have small daily caps (~20/day/project for 3.8 Flash).

## Idle (free, not used by ingestion)

| Model | Provider | Why idle | Fit for other work |
|---|---|---|---|
| Nemotron 3 Ultra 550B | Kilo (also Zen) | AR fail (shallow, slow) | Large reasoning model: planning, strategy design |
| Nemotron 3 Super 120B | Kilo | AR fail | Reasoning, review |
| Nemotron 3 Nano Omni 30B (reasoning, multimodal) | Kilo | never tested | Light reasoning, image reading |
| Nemotron 3.5 Lightning | Kilo (also Zen) | AR fail (422 facts) | Fast, simple tasks |
| Laguna S 2.1 (Poolside) | Kilo | AR fail (misreads numbers) | Coding model: boilerplate code |
| Laguna XS 2.1 (Poolside) | Kilo | never tested | Small coding model |
| Cohere North Mini Code | Kilo | AR fail 19/25, 4,492 facts (10-14); no rate limit seen in ~140 calls | Coding model |
| Inkling Small (Thinking Machines) | Kilo | never tested; 1,000/day cap shared by all Kilo keys | General |
| Glyph Cluster (stealth) | Kilo | AR fail 18/25 | General |
| Ling 3.1 Flash | Kilo / Zen | upstream overloaded / endpoint down | Unreliable |
| LFM 2.5 2.6B (Liquid) | Kilo | tiny model | Classification, formatting only |
| MiMo V2.6 Flash | Zen | AR fail (1,525 facts); deck pass 93.7% (in the deck pool, Zen quota) | General; shares Zen quota |
| Nemotron (Zen copies) | Zen | AR fail | Shares Zen quota |
| Dots 3 Note | Kilo x2 accounts | deck primary; first deck pass finished 10-11, so idle now | Image/slide reading, general |
| Gemini 3.5 / 3.6 / 3.7 / 3.8 Flash | Google | deck test pending (Google overloaded at US peak); small daily caps | Strong general models, a few calls a day per project |
| kilo-auto/free, openrouter/free | Kilo | routers to whatever free model is up | Quick experiments |

Not usable: Gemini Omni 1.1 Flash, Gemini 4 Argon, 3.1 Pro Preview (no free tier); Gemini 2.5 Flash/Pro (retired for new
users); Exo, Ling 3.0 Flash Fin (dead on Zen); Lyria (music); Nemotron 3.5 Content Safety (classifier); DeepSeek V4 on
Token Harbor (~40 free calls).

## In use (no spare capacity)

| Model | Provider | Job |
|---|---|---|
| LongCat 2.5 Preview | Go x2 (128 slots each), Zen | annual reports (main workhorse) |
| Cat Jam | Go x2 (64 each, quota-limited), Zen | annual reports |
| Gemma 4 31B, Gemma 4 26B, Flash-Lite 3.5 / 3.1 | Google, 37 projects | annual reports |
| Space Bunny, Muse Spark 1.3, Big Pickle | Zen | annual reports (Zen daily quota) |
| Step 5 Preview | Kilo, Go account 2, Zen | deck second readings (all at their rate limits) |
