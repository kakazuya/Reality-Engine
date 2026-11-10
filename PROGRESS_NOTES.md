# T-133 v6 progress

- 2026-11-10: label_map v6 implemented (8 ticket steps), built `.tmp/label_map_v6` (41,882/59,326 numeric rows = 70.6% mapped, 2,284 rejected cells, 887 rejected labels / 559 garbled; ports_logistics 59.9% the only family under 60%). Replay over seed-31/37/41/43: 139/139, 170/170, 177/177, 180/180 right rows kept, LOST 0. Tests 61 passed. Docs (V2_SCHEMA_CONTRACT s11, DEVELOPER_GUIDE O24) updated. Next: controller review of review_*.csv, sample_seed47.csv and rejected_seed47.csv; then approve families. No blockers.
