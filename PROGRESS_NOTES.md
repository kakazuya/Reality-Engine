# Progress notes — tool usage measurement (2026-10-30)

- Found the sources: dsh 208 job dirs / 187 with `result.md.events.jsonl` (93 MB), Claude 26
  transcripts in `~/.claude/projects` (171 MB, 3 of them under `subagents/`), OpenCode
  `opencode.db` + WAL (24 MB, copied to `.tmp` before opening), Codex absent.
  `DSH_WORKER_PROGRESS_NOTES` was empty, so this file lives in the job root.
- Built `reality_engine/scripts/tool_usage_report.py`: streaming readers, first-operation shell
  classifier, 21 classes, detectors a–j, before/after, top sessions, cross-checks, redaction.
- Fixed two real data traps: one Claude API message is split over several lines with the same
  `message.id` (usage once, every `tool_use` kept), and `cost-state` is a live snapshot rather
  than a final total. dsh calls now match the worker's own counter exactly (14,796 / 14,796).
- Accuracy: 9 shell classes × 30 random rows adjudicated by hand from the samples file
  (trigger evidence shown per row); 8 classes at 100%, shell search 96.7% (one `for`-loop poll
  counted as search). Classifier rewritten three times to get there (positional first-operation
  rule, python-invocation detection, edit-wins rule).
- Deliverables written to `tasks/efficiency/`; fixture test passes under unittest (pytest is
  not installed on this box and installs are not allowed).
- Next: controller grades the waste numbers. Nothing blocked.
