# T-129 progress (final)

- Rule A: `kpi.doc_default_period` -> `_ytd_default` (YTD span + first named quarter on the cover; Q2->H1, Q3->9M, Q1->Q1; Q4 keeps FY; annual reports / >80 pages pass `ytd=False`; own-period sentences unchanged; the quarterly-cue, quarter-after-comparative and T-107 ratio rules now also read H1/9M defaults). SBILIFE evidence: APE 117.5 H1FY27, APE 185.2 / 168.8 and VNB 50.4 9MFY26.
- Rule B: `kpi.derive_quarters` (Q2=H1-Q1, Q3=9M-H1, Q4=FY-9M; flow whitelist `_DERIVABLE_FLOW`; 1% pin; best non-quarantined input; `derived_cumulative_v1`, is_reported 0, quote names both inputs, known_at = later input).
- Rule C: `number_check.check_source_scale` -> `source_scale_mismatch`; MARUTI-127 pair tested.
- Measured on the pilot10 copy (control with A disabled vs real, same code): 215 periods changed; 47 derived rows (revenue 18, PAT 15, EBITDA 9, one each of APE/GWP/new loans/order intake/volumes); all 47 derived rows quarantined by `--part checks` (synthetic quote); kpi verdicts after 2,292 verified / 3,330 unverified / 427 quarantined reported + 47 derived quarantined. Number-check replay: 2 findings, both MARUTI-127 (4,136 and 18,740 crore sourced in million).
- Tests: literal acceptance 123 passed + 6 sandbox `tmp_path` errors; 134 passed over the three files with the sandbox 0o755 workaround.
- Done; docs 9j + guide + STATE updated; two commits on the branch.
