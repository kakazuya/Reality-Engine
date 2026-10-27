# Task — video screen OCR pilot on CPU, with every metadata label checked

## Goal
Prove, on 5 analyst videos, that each on-screen text record we extract carries every label it needs, correctly,
before we run all 179 videos. Output: a pilot SQLite DB plus a label audit. CPU only.

## Inputs (read-only)
- Videos: `D:\RealityEngine\raw\user_research\extracted\` (179 unique). Durations and paths are in
  `D:\RealityEngine\raw\user_research\_asr_test\..\` (use ffprobe yourself). Pick 5 across types: 2 company
  deep-dives under `Current Premium Users\Member Videos\<date> <Company>\`, 1 "Ask Me Anything", 1 DailyBytes,
  1 under `Research\Completed\...`.
- Drive dates: `D:\RealityEngine\raw\user_research\_drive_meta_current_premium.json` and `_drive_meta_research.json`
  (rclone lsjson --metadata: Path, ModTime, Metadata.btime / mtime).
- Analyst Drive docs (to link a screen to the doc it shows): same `extracted\` tree (`.docx`, `.xlsx`).
- Company identity: `reality_engine.db.readonly.connect_ro` on `reality_engine/data/equity_intelligence.db`
  (`master_companies`: isin, nse_symbol, bse_code, company_name). Bounded queries only.
- Tools on this laptop (measured): ffmpeg at
  `C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe`.
  RapidOCR is installed in `.venv-layout`. **The venv's own python.exe cannot write files** (antivirus). Run the
  system `python` with `PYTHONPATH=C:\Users\warri\Downloads\Info_Diffusion_Model\.venv-layout\Lib\site-packages`.
  Use the CPU: GPU OCR measured 4.7× slower.
- Reference implementation from the manager's test:
  - frames every 5 s;
  - drop a frame whose 160×100 grey thumbnail has mean abs diff < 4.0 vs the last kept one;
  - `RapidOCR()` per kept frame;
  - ~5.5 s per dense 1600-px frame;
  - about a third of lines are app chrome (Google Docs menus, browser tabs, URLs), which you must filter.

## Per screen record: labels to fill (each must be right, or NULL with a reason)
| label | rule |
|---|---|
| video_id | sha256 of the file |
| source_path, channel | channel ∈ member_video / dailybytes / research_video, from the folder |
| title | folder name |
| company_isin / symbol | from folder title via master_companies (exact name, then normalised fuzzy); multi-company titles ("Garware Hitech Films & AMA") give several; AMA / Market View give none. Record `match_method` + score |
| published_at, pit_source, pit_confidence | folder date (YYYY-MM-DD or "18th feb 2026" style) if present → `folder_name`, high; else Drive btime → `drive_btime`, medium; mtime > btime by > 1 day → low |
| t_start, t_end | seconds into the video for the screen |
| screen_type | gdoc / gsheet / chart / screener / exchange_filing / slides / other, from OCR cues (window title, URL, layout) |
| linked_doc_path | when screen_type is gdoc/gsheet: the matching analyst doc in the Drive tree (title match + same company), else NULL |
| text_clean | OCR lines minus chrome |
| ocr_lines, chrome_lines_dropped | counts |
| quality_grade | A/B/C by rules you define and print |

Also store a per-video **glossary** (distinct proper terms from all its screens + company name) for later ASR fixes.

## Output
- `.tmp/video_ocr_pilot.db` with tables `video`, `screen`, `glossary`.
- `.tmp/LABEL_AUDIT.md`:
  - fill rate per label;
  - 15 random screens printed with all labels;
  - for each of the 5 videos, your own check of the company and date labels against the folder and Drive metadata,
    with any mismatch explained.
- Timing: frames/s, seconds per video minute, and the projected hours for all 179 videos (126.2 h of video).

## Rules
- Read-only on all data. Write only in your worktree (`.tmp/`). No network. No paid APIs. Do not commit.
- Do not OCR more than the 5 videos.

## Acceptance checks
1. Five videos done, with the DB and audit present.
2. Every label has a fill rate, and each NULL has a reason.
3. Company and date checked by hand for all 5.
4. Timing projection given.
5. Tests for any reusable code (`reality_engine/tests/test_video_ocr_pilot.py`).

## Test command(s)
```bash
python -m unittest reality_engine.tests.test_video_ocr_pilot
```

## Report
Summary, label fill table, audit rows, timing, open problems, tool calls.
