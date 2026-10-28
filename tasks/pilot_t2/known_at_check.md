# known_at check — 5 docs per type vs the filing record

| doc type | doc_id | chunk known_at | record known_at | source | match |
|---|---|---|---|---|---|
| annual_report | sha256:03d8823416aa01815ed | 2026-05-30T11:13:39 | 2026-05-30T11:13:39 | ar_facts.ar_docs.filed_at(sha) | OK |
| annual_report | sha256:0de9970262d1a5b0285 | 2025-08-07T00:15:24 | 2025-08-07T00:15:24 | ar_facts.ar_docs.filed_at(sha) | OK |
| annual_report | sha256:1074d9f0184eeae1185 | 2025-07-07T15:08:26 | 2025-07-07T15:08:26 | ar_facts.ar_docs.filed_at(sha) | OK |
| annual_report | sha256:1394a9282c64e116e12 | 2026-09-03T22:05:59 | 2026-09-03T22:05:59 | ar_facts.ar_docs.filed_at(sha) | OK |
| annual_report | sha256:16f4a5d5a170eb9e5bd | 2026-08-26T17:00:33 | 2026-08-26T17:00:33 | ar_facts.ar_docs.filed_at(sha) | OK |
| concall | sha256:0081b83f8a0731b6320 | 2025-10-27T18:52:21 | 2025-10-27T18:52:21 | corporate_documents.bse_dissem|publication | OK |
| concall | sha256:011a43c936cc4173d47 | 2026-06-02T15:16:47 | 2026-06-02T15:16:47 | corporate_documents.bse_dissem|publication | OK |
| concall | sha256:012d54902ea3ff992b7 | 2024-07-30T17:46:02 | 2024-07-30T17:46:02 | corporate_documents.bse_dissem|publication | OK |
| concall | sha256:0137a9def893c493c20 | 2026-10-16T22:57:06 | 2026-10-16T22:57:06 | nse_announcements.exchdisstime | OK |
| concall | sha256:015568cb8e5cab0c460 | 2024-08-06T18:27:49 | 2024-08-06T18:27:49 | corporate_documents.bse_dissem|publication | OK |
| deck | sha256:00738e12a934c6ee7c9 | 2025-11-07T16:51:20 | 2025-11-07T16:51:20 | deck_sources.known_at | OK |
| deck | sha256:025c253e029e3e85bb2 | 2025-11-13T15:07:26 | 2025-11-13T15:07:26 | deck_sources.known_at | OK |
| deck | sha256:0322311ffccfe36c4fd | 2026-05-29T16:57:56 | 2026-05-29T16:57:56 | deck_sources.known_at | OK |
| deck | sha256:03cf16287c832cc4743 | 2024-07-31T15:02:41 | 2024-07-31T15:02:41 | deck_sources.known_at | OK |
| deck | sha256:06122788a233b572c86 | 2024-08-09T18:09:09 | 2024-08-09T18:09:09 | deck_sources.known_at | OK |
| announcement | sha256:00caea807f673f881b2 | 2026-07-30T17:57:39 | 2026-07-30T17:57:39 | bse_announcements.ann.DissemDT(attachment) | OK |
| announcement | sha256:01f7932d08a96191c7c | 2024-08-26T18:05:13 | 2024-08-26T18:05:13 | nse_announcements.exchdisstime | OK |
| announcement | sha256:04f77661f1b3a3c435e | 2026-10-26T22:47:34 | 2026-10-26T22:47:34 | nse_announcements.exchdisstime | OK |
| announcement | sha256:063064d35c19980cde1 | 2026-07-24T15:14:49 | 2026-07-24T15:14:49 | bse_announcements.ann.DissemDT(attachment) | OK |
| announcement | sha256:06b0fc031113e6f7a97 | 2026-08-01T12:37:14 | 2026-08-01T12:37:14 | bse_announcements.ann.DissemDT(attachment) | OK |

mismatches: 0 / 20
