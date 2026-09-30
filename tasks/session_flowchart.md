# Session Flowchart — Why Everything Was Done (living doc, update after each task action)

> Last updated: 2026-09-23 (survival loop CLOSED: RealityEngine-AnnualDrain hourly Ready; drain + embed live; SELL revoked, P0 brief ready)
> Rule: after each task action, update the mermaid below + this timestamp.

```mermaid
flowchart TD
    OBJ["Objective: cause→effect attribution<br/>explain WHY price moved from available info<br/>residual = mispricing → cash BUY/SELL/HOLD for ROC"]

    OBJ --> GAP["Gap found: 12GB warehouse built<br/>3.1M prices / 662k chunks / moat+ENI+ripple<br/>BUT zero residual/explained/BUY/SELL in orchestrator<br/>WHY: warehouse ≠ model; needed attribution brain"]

    GAP --> LOCAL["Local-only audit: i5-12T / 17GB RAM / RX6700XT / 511GB free<br/>RAM binding not CPU<br/>WHY: run everything on this box, no cloud/PG"]
    LOCAL --> FIND["tasks/local_only_preliminary_findings_2026-09-22.md<br/>7 fixes<br/>WHY: unblock local speed + fix broken serve paths"]

    FIND --> LF1["LlmServeFix<br/>_llm_paths → real Q2_g64 GGUF<br/>ctx 16384 / threads 8<br/>5.8GB .incomplete deleted<br/>WHY: llm-serve always missed"]
    FIND --> LF2["EmbedBackendAuto<br/>onnx → auto, batch 8→32<br/>Vulkan 65 vs DML 32 chunks/s<br/>WHY: 2x embed speed, auto-fallback safe"]
    FIND --> LF3["SearchSingleEmbed<br/>1 embed per search, shared vector<br/>RRF + 0.35 gate kept<br/>WHY: was paying 2x ONNX per query"]
    FIND --> LF4["NightlyIndexRebuild<br/>rebuild only on growth<br/>whisper threads 10→8<br/>WHY: stale index + CPU starvation"]
    FIND --> LF5["RootCleanup<br/>54 scratch files → archive + MANIFEST<br/>WHY: agent context noise"]

    LF1 & LF2 & LF3 & LF4 & LF5 --> V1["Verify 11/11 PASS<br/>paths True/True, auto32, embeds=1<br/>WHY: prove fixes before wave work"]

    V1 --> SPEC["tasks/next_wave_attribution.md<br/>3 slices, frozen 22-col ledger DDL<br/>exact math share=w×1{pred==sign}<br/>WHY: parallel agents need one contract"]
    SPEC --> S1["MoveAttributor<br/>move_attribution ledger<br/>WHY: foundation every slice builds on"]

    S1 --> BUG["Verify catches units bug<br/>floor 45.0 vs move ±1 → is_material always 0<br/>WHY: verification before trust"]
    BUG --> FF["MoveFloorFix<br/>trailing-20σ floor in % pts [0.5,8.0]<br/>RELIANCE material=1 resid 0.63<br/>WHY: floor must be in move units"]
    BUG --> S2["ActionThesis<br/>decide_action 16-cell table<br/>attribution block MD/HTML/JSON + verbs<br/>WHY: turn ledger into BUY/SELL/HOLD"]
    BUG --> S3["PortfolioCalib<br/>portfolio_actions + MTM + summarize<br/>calibration via apply_if_improved gate<br/>WHY: ROC accounting + close the loop"]

    FF & S2 & S3 --> ACC["Wave acceptance<br/>401 rows, 186 material, median resid 0.52<br/>theses carry action<br/>calibration refuses on no-improvement<br/>suite 690 green by shard<br/>WHY: prove slices integrate"]

    ACC --> TR["Track record seed<br/>31 → 128 actions; 82 closed win 0.40 mean -5.07<br/>WHY: day-zero book from realized history"]
    TR --> CALLMINT["MintCallRows: 219 → 1396 material×call<br/>5,139 call rows, 60 dates<br/>WHY: seed converts only where terms exist"]
    TR --> IDX["IndexBackfill: 4 legs 21d → 262d, 1048 rows<br/>2025-09 → 2026-09<br/>WHY: excess needs index legs"]
    TR --> HOR["HorizonReport: 4×4 table + weekly cohorts<br/>WHY: +500bps gate needs the table"]
    TR --> NGT["NightlyTrackWire: track_record stage<br/>13/13 green<br/>WHY: book keeps itself nightly"]

    HOR --> DIAG["Diagnosis on 34 closed BUYs<br/>supply 34/34 = constant; quality 0/34 = constant<br/>sudden-drop 28/34; next-day down 26/34<br/>entry 1.43× floor = noise<br/>WHY: explain -300bps before fixing"]

    DIAG --> PH["PredictorHonesty<br/>levels GATE, flows VOTE; dated Q/P/S → 0<br/>residual → 1.0 honest<br/>WHY: a constant cannot explain a move"]
    DIAG --> ED["EntryDiscipline<br/>BUY needs |move|≥2σ floor<br/>WHY: stop buying 1σ noise dips"]
    DIAG --> TS["TestSpeedInfra: 738 passed, 199s vs 60s MISS<br/>contention-bound GPU queue<br/>WHY: measure speedup honestly"]

    PH & ED --> SEL["SelectionFix<br/>quality_broken = Deteriorating OR moat&lt;2.5 OR ENI&lt;0<br/>BUY needs factor agreement<br/>SELL 52 seeded, 46/46 wins CLAIMED then REVOKED 2026-09-23<br/>WHY: long-framed terms, stop-out booked as gain — see next_wave_plan_2026-09-23.md §2A"]

    SEL --> V5["Book v5: 863 actions, 585 closed<br/>win 0.51, pnl +29.8 = BUY -219.87 + SELL +249.67 artifact<br/>honest 20d read +790bps n=16 on 5 clusters, one index-down regime<br/>BUY still -500bps on fixed 18/6 bracket<br/>WHY: artifact revoked; bracket geometry, not lens verdict"]
    V5 --> CAL["Calibration: folds decided, applied=false<br/>WHY: gate must refuse on losing blend"]
    V5 --> SUITE["Suite re-verify: 714 green<br/>middle 178 + tail 172 + first 364<br/>+ hermeticity fix: fixture screener leaked live ENI -1.38<br/>WHY: trust after every edit"]

    SUITE --> ABORT["Full-universe rerun ABORTED on disk I/O after 3561s<br/>136,642 rows kept via idempotent upserts; quick_check ok<br/>WHY: same verb resumes free — upserts skip done work"]
    ABORT --> PROOF["Proof batch 20/20 exit 0 in 591s (~30s/doc DML)<br/>7,117 chunks, boilerplate filter live<br/>WHY: measure before scaling"]
    PROOF --> VULKAN["embed-server :8099 VERIFIED<br/>health ok + 384-dim norm-1.0 embeddings<br/>WHY: no silent DML fallback"]
    VULKAN --> DRAIN["Drain DETACHED+persistent, GPU 100% per user order<br/>embed-server died clean exit=1 after 1.75M tasks/13h (no crash sig)<br/>restarted pid 15852 verified; drain resumed pid 22376 backend=vulkan<br/>WHY: server loss killed drain exit=58; both revived, resume at ~618/1847"]
    DRAIN --> HANDOFF["Handoff state for fresh window<br/>read: next_wave_plan_2026-09-23.md, strategy_tracker.md, this chart<br/>live: ingest-annual-resume pid 22376 + embed-server pid 15852<br/>gates: SELL revoked, suite 714 green, calibration gated<br/>next: 09-21/22 backfill behind drain checkpoint, then P0 per plan §4"]
    HANDOFF --> SURVIVE["Survival loop CLOSED: RealityEngine-AnnualDrain<br/>hourly Scheduled Task, Ready, run_annual_drain.cmd<br/>reboot/power/session/internet-proof via resumable queue<br/>WHY: detached dies on power loss; scheduler doesn't"]
    SURVIVE --> GATE["Goal gates CORRECTED<br/>❌ SELL leg revoked ❌ bracket fixed 18/6 ❌ quarantine ungated<br/>✅ 714 green ✅ table machinery ✅ calibration gated<br/>🔄 drain live + hourly watchdog ❌ fresh EODs frozen 09-18"]
