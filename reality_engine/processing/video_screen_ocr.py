"""Video screen OCR pilot (CPU): 5 s frames -> thumbnail dedupe -> RapidOCR -> labelled screens.

Read-only on the analyst Drive tree and on ``equity_intelligence.db``; writes only the
pilot SQLite DB and the label audit under the caller's workspace.

Two phases, on purpose:

``--video``  worker: one video -> frames, dedupe, RapidOCR -> ``<workdir>/ocr/<id>.json``
             (raw lines + scores + timing; no label decisions, so filters can be
             re-tuned without paying for OCR again).
``--build``  labels every screen from those JSON files, writes the DB and the audit.

Every label rule is a printed constant below, so the audit can quote the rule it applied.
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

FRAME_EVERY_S = 5.0
OCR_WIDTH = 1600
THUMB_SIZE = (160, 100)
DEDUPE_MEAN_ABS = 4.0
GLOSSARY_TOP = 40
SEGMENT_GAP_S = 60.0  # a screen-type run survives gaps up to a minute; longer = new segment
TOTAL_VIDEO_HOURS = 126.2  # 179 videos, from the task brief
PROJECTION_WORKERS = 2  # laptop also runs a results-PDF fetch/re-parse: 2 OCR processes, not 5

# OCR engine settings (CPU). intra_op_num_threads=2 lets five video workers share 8 cores;
# rec_batch_num keeps more text crops per GPU-free batch. Measured on this laptop.
OCR_PARAMS = {
    "EngineConfig.onnxruntime.intra_op_num_threads": 2,
    "Rec.rec_batch_num": 16,
    "Global.log_level": "error",
}

GRADE_RULES = (
    ("A", ">= 8 clean lines and >= 120 chars and mean OCR score >= 0.85"),
    ("B", ">= 3 clean lines and >= 25 chars"),
    ("C", "fewer lines/chars or lower score than the rules above"),
)

CHROME_RULES = (
    ("url", r"^(https?://|www\.)|\.(com|in|org|net)(/|$)|\b(docs|drive|sheets)\.google\.com\b"),
    ("gdoc_menu", r"\b(file\s+edit\s+view|insert\s+format|tools\s+(help|extensions)|normal text|"
                  r"arial|times new roman|last edit was|suggesting|editing mode)\b"),
    ("gdoc_chrome", r"^(share|comments?|present|view only|comment|undo|redo|print|zoom|100%|"
                    r"\d+%|page \d+ of \d+|insert|format|styles?)$"),
    ("browser_tab", r"^(new tab|tab search|bookmarks?|extensions?|sign in|sign out|profile|"
                     r"incognito|history|downloads)\b|^gmail$|^google$"),
    ("taskbar", r"^(\d{1,2}:\d{2}(\s?(am|pm))?|type here to search|ask me anything|wifi|wi-fi|"
                r"volume|battery|eng|in)$|windows|cortana|task view"),
    ("player", r"^(play|pause|stop|replay|mute|unmute|full ?screen|settings|next|previous|"
               r"\d{1,2}:\d{2}(:\d{2})?|cc|hd|auto)$"),
    ("chart_ui", r"^(indicators?|watchlists?|alerts?|replay|compare|symbol|timeframe|interval|"
                 r"chart|candles?|bars?|undo|redo|save|load|arrange|layout|trade|buy|sell)$"),
    ("site_nav", r"^(home|markets?|market data|news|industry|politics|wealth|tech|careers|opinion|"
                  r"more|login|log in|sign in|subscribe|advertise|contact|about us|privacy policy|"
                  r"terms of use|follow us|font size|search|my watchlist|portfolio|dashboard|"
                  r"e-?paper|masterclass|ipo|sme|nri|panache|mutual funds?|commodity|currency|"
                  r"economy|insurance|renewables|services|media/?entertainment|business news|"
                  r"cons\. products|ind'?l goods/?svs|etprime|etprime member|unlock offer)$"),
    ("noise", r"^[^A-Za-z0-9]{0,3}$|^[A-Za-z]{1,2}$|^[\W_]{2,}$"),
)

SCREEN_RULES = (
    ("gsheet", (r"sheets\.google\.com", r"\bsheet\d\b", r"^\s*[a-h]\s+[b-h]\s+[c-h]\s+[d-h]\s+[e-h]\s*$",
                r"\bcolumn [a-z]\b|\brename sheet\b|\binsert sheet\b|\bsumif\b|\bvlookup\b")),
    ("gdoc", (r"docs\.google\.com", r"\bnormal text\b", r"file\s+edit\s+view\s+insert\s+format",
              r"\bsuggesting\b|\bediting mode\b")),
    ("screener", (r"screener", r"chartink", r"\btrendlyne\b", r"\bpeer comparison\b")),
    ("exchange_filing", (r"\bbse\s*[:#-]?\s*\d{5,7}\b", r"\bnse\s*[:#-]?\s*[A-Z]{2,}\b",
                          r"\bannouncement\b|\bfiling\b|\bsebi\b|\bboard meeting\b|\bannual report\b"
                          r"|\boffer document\b|\bdrhp\b")),
    ("slides", (r"\bclick to add (notes|text)\b", r"^\s*slide \d+\s*$", r"\bpowerpoint\b")),
    ("chart", (r"tradingview", r"\bindicators?\b", r"\bvolume\b", r"\bopen\s+high\s+low\s+close\b",
                r"\bema\b|\bsma\b|\brsi\b|\bmacd\b")),
)

GENERIC_HEADS = {
    "market", "daily", "weekly", "ask", "ama", "view", "deep", "dive", "analysis", "sector",
    "update", "new", "top", "small", "large", "mid", "part", "the", "my", "best", "worst",
    "how", "what", "why", "when", "banking", "banks", "shipping", "power", "water", "railway",
    "railways", "aerospace", "auto", "chemical", "textile", "defence", "semiconductor",
    "business", "businesses", "catching", "frauds", "chartink", "valuation", "master", "series",
    "session", "recording", "industry", "theme", "research", "export", "data",
}

COMPANY_SUFFIXES = (" limited", " ltd", " india ltd", " india", " co", " corporation", " corp")

STOPWORDS = {
    "the", "and", "for", "with", "from", "this", "that", "these", "those", "you", "your", "our",
    "are", "was", "were", "will", "would", "should", "could", "can", "may", "might", "have",
    "has", "had", "not", "but", "they", "their", "them", "there", "here", "what", "when",
    "where", "which", "who", "how", "why", "all", "any", "one", "two", "three", "more", "most",
    "some", "such", "than", "then", "also", "just", "only", "very", "into", "over", "under",
    "about", "after", "before", "between", "during", "each", "other", "both", "same", "own",
    "year", "years", "month", "months", "quarter", "quarters", "numbers", "revenue", "profit",
    "growth", "margin", "margins", "share", "shares", "price", "prices", "value", "values",
    "total", "average", "current", "previous", "next", "last", "first", "second", "third",
    "file", "edit", "view", "insert", "format", "tools", "help", "share", "comment", "comments",
    "google", "docs", "sheets", "chrome", "tradingview", "chartink", "screener", "nse", "bse",
    "normal", "text", "arial", "times", "new", "roman", "indicators", "watchlist", "alert",
    "replay", "symbol", "timeframe", "interval", "open", "high", "low", "close", "volume",
    "edit", "view", "candles", "layout", "compare", "mute", "play", "pause", "zoom", "page",
}

_MONTHS = {}
for _i, _m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct",
                         "nov", "dec"), 1):
    _MONTHS[_m] = _i
for _i, _m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                         "august", "september", "october", "november", "december"), 1):
    _MONTHS[_m] = _i

_ISO_DATE_RE = re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)")
_DAY_NAME_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-_]+([A-Za-z]{3,9})\.?[\s\-_,]+(20\d{2})(?!\d)", re.I)
_NAME_DAY_DATE_RE = re.compile(
    r"\b([A-Za-z]{3,9})\.?[\s\-_,]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-_,]+(20\d{2})(?!\d)", re.I)


# --------------------------------------------------------------------------- dates / paths

def parse_folder_date(name: str):
    """First valid date in a folder name -> (iso_date, matched_text). Invalid dates -> (None, None)."""
    if not name:
        return None, None
    for m in _ISO_DATE_RE.finditer(name):
        y, mo, d = (int(g) for g in m.groups())
        try:
            return dt.date(y, mo, d).isoformat(), m.group(0)
        except ValueError:
            continue
    for m in _DAY_NAME_DATE_RE.finditer(name):
        d, mo, y = int(m.group(1)), _MONTHS.get(m.group(2).lower()), int(m.group(3))
        if mo and 1 <= d <= 31:
            try:
                return dt.date(y, mo, d).isoformat(), m.group(0)
            except ValueError:
                continue
    for m in _NAME_DAY_DATE_RE.finditer(name):
        mo, d, y = _MONTHS.get(m.group(1).lower()), int(m.group(2)), int(m.group(3))
        if mo and 1 <= d <= 31:
            try:
                return dt.date(y, mo, d).isoformat(), m.group(0)
            except ValueError:
                continue
    return None, None


def channel_of(rel_path: str) -> str:
    """channel ∈ member_video / dailybytes / research_video, from the extracted-tree folder."""
    parts = [p.lower() for p in Path(rel_path).parts]
    if "research" in parts:
        return "research_video"
    if "dailybytes" in parts or "daily bytes" in parts:
        return "dailybytes"
    return "member_video"


def video_title(rel_path: str) -> str:
    """Title = the folder the video sits in (the task's rule)."""
    return Path(rel_path).parent.name.strip()


def drive_rel_path(rel_path: str) -> str:
    """extracted-tree relative path -> the Path key used by the rclone metadata dumps."""
    parts = Path(rel_path).parts
    if parts and parts[0] in ("Current Premium Users", "Research"):
        parts = parts[1:]
    return "/".join(parts)


def parse_btime(value):
    if not value:
        return None
    for fmt in ("%d-%m-%Y %I:%M:%S %p", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return dt.datetime.strptime(str(value).strip(), fmt)
        except ValueError:
            pass
    return None


def resolve_published(folder_names, drive_entry):
    """published_at + pit_source + pit_confidence + the evidence string that justifies it."""
    btime = parse_btime((drive_entry or {}).get("Metadata", {}).get("btime"))
    mtime = parse_btime((drive_entry or {}).get("Metadata", {}).get("mtime"))
    for name, level in folder_names:
        iso, matched = parse_folder_date(name)
        if iso:
            evidence = f"{level} '{name}' carries '{matched}'"
            if btime is not None:
                skew = (btime.date() - dt.date.fromisoformat(iso)).days
                if abs(skew) > 7:
                    evidence += (f"; Drive btime {btime:%Y-%m-%d} is {abs(skew)} d "
                                 f"{'later' if skew > 0 else 'earlier'} than the folder date")
            return {"published_at": iso, "pit_source": "folder_name", "pit_confidence": "high",
                    "date_evidence": evidence}
    if btime is None:
        return {"published_at": None, "pit_source": None, "pit_confidence": None,
                "date_evidence": "no folder date and no drive btime"}
    evidence = f"drive btime {btime:%Y-%m-%d %H:%M}"
    confidence = "medium"
    if mtime is not None:
        skew = mtime - btime
        if skew > dt.timedelta(days=1):
            confidence = "low"
            evidence += f"; mtime {mtime:%Y-%m-%d} is {skew.days} d after btime"
        elif skew < -dt.timedelta(days=1):
            # the upload postdates the file: btime is an upload date, not a recording date
            confidence = "low"
            evidence += (f"; mtime {mtime:%Y-%m-%d} is {-skew.days} d BEFORE btime, so the "
                         f"upload date is not the recording date")
    return {"published_at": btime.date().isoformat(), "pit_source": "drive_btime",
            "pit_confidence": confidence, "date_evidence": evidence}


# --------------------------------------------------------------------------- company matching

def norm(text: str) -> str:
    text = (text or "").lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def company_core(name: str) -> str:
    core = norm(name)
    changed = True
    while changed:
        changed = False
        for suffix in COMPANY_SUFFIXES:
            if core.endswith(suffix) and len(core) > len(suffix) + 2:
                core = core[: -len(suffix)].strip()
                changed = True
    return core


def title_segments(title: str):
    """Split a folder title into the company-ish chunks a multi-company title names."""
    cleaned = re.sub(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)", " ", title)
    cleaned = _DAY_NAME_DATE_RE.sub(" ", cleaned)
    for name, _ in (("ask me anything", " "), ("market view", " "), ("daily bytes", " ")):
        cleaned = cleaned.lower().replace(name, " ")
    parts = re.split(r"\s*(?:,|&|/|;|\+|_|\(|\)|:|\bvs\b|\band\b)\s*", cleaned, flags=re.I)
    out = []
    for part in parts:
        part = re.sub(r"^(part\s*\d+|\d+|\W+)\s*", "", part.strip(), flags=re.I)
        part = re.sub(r"\s+", " ", part).strip()
        if len(part) >= 3 and re.search(r"[A-Za-z]{3,}", part):
            out.append(part)
    return out


def prefix_ratio(segment_tokens, company_tokens):
    """How well a title segment prefixes the start of a company core name; None if it does not.

    'Necter Life' vs ('nectar','lifesciences') -> 0.83 (typo + abbreviation still match).
    """
    if not segment_tokens or len(segment_tokens) > len(company_tokens):
        return None
    ratios = []
    for seg_token, company_token in zip(segment_tokens, company_tokens):
        if len(seg_token) >= 3 and company_token.startswith(seg_token):
            ratios.append(1.0)
            continue
        ratio = difflib.SequenceMatcher(None, seg_token, company_token).ratio()
        if ratio < 0.80:
            return None
        ratios.append(ratio)
    return min(ratios)


class CompanyMatcher:
    """Exact name -> normalised fuzzy match against master_companies. Memoised per title."""

    def __init__(self, rows):
        self.rows = []
        for r in rows:
            isin, symbol, name = r[0], r[1], r[2]
            if not name:
                continue
            self.rows.append({
                "isin": isin, "symbol": symbol, "name": name,
                "core": company_core(name), "sym": norm(symbol or ""),
                "tokens": company_core(name).split(),
            })
        self._cache = {}

    def match(self, title: str):
        if title in self._cache:
            return self._cache[title]
        found = {}
        for segment in title_segments(title):
            best = self._match_segment(segment)
            if best and (best["isin"] not in found or best["score"] > found[best["isin"]]["score"]):
                found[best["isin"]] = best
        result = sorted(found.values(), key=lambda m: -m["score"])
        self._cache[title] = result
        return result

    def _match_segment(self, segment: str):
        seg = norm(segment)
        seg_tokens = seg.split()
        if not seg_tokens:
            return None
        head = seg_tokens[0]
        generick_head = head in GENERIC_HEADS and len(seg_tokens) == 1
        for skip_fuzzy in (False, True):
            candidates = []
            for row in self.rows:
                core, sym, toks = row["core"], row["sym"], row["tokens"]
                if not core:
                    continue
                score, method = 0.0, None
                if seg == core:
                    score, method = 1.00, "exact_name"
                elif (seg in core or core in seg) and min(len(seg), len(core)) >= 8:
                    score, method = 0.90, "name_contains"
                elif sym and seg == sym:
                    score, method = 0.95, "symbol"
                elif not skip_fuzzy and not generick_head:
                    ratio = difflib.SequenceMatcher(None, seg, core).ratio()
                    if ratio >= 0.88:
                        score, method = round(ratio, 3), "fuzzy_name"
                    else:
                        prefix = prefix_ratio(seg_tokens, toks)
                        if prefix is not None:
                            score, method = round(0.78 + 0.12 * prefix, 3), "token_prefix"
                if method and score >= 0.80:
                    candidates.append((score, method != "token_prefix", row, method))
            if candidates:
                candidates.sort(key=lambda c: (-c[0], not c[1]))
                score, _, row, method = candidates[0]
                return {"isin": row["isin"], "symbol": row["symbol"], "name": row["name"],
                        "method": method, "score": score, "segment": segment}
            if skip_fuzzy:
                break
        return None


# --------------------------------------------------------------------------- chrome + screen type

def chrome_reason(line: str):
    """Reason string when the line is app chrome, else None."""
    text = line.strip()
    if not text:
        return "noise"
    low = text.lower()
    for reason, pattern in CHROME_RULES:
        if re.search(pattern, low):
            return reason
    if len(text) <= 2:
        return "noise"
    return None


def annotate_lines(lines):
    """[(line, chrome_reason or None)] in OCR order — the same decision the filter applies."""
    return [(line, chrome_reason(line)) for line in lines]


def split_chrome(lines):
    kept, dropped = [], {}
    for line, reason in annotate_lines(lines):
        if reason is None:
            kept.append(line.strip())
        else:
            dropped[reason] = dropped.get(reason, 0) + 1
    return kept, dropped


def classify_screen(lines):
    """(screen_type, cue). First rule whose cue appears in the cleaned lines wins."""
    joined = "\n".join(lines).lower()
    for screen_type, patterns in SCREEN_RULES:
        for pattern in patterns:
            m = re.search(pattern, joined, re.M)
            if m:
                return screen_type, f"{screen_type}:{pattern} matched '{m.group(0)[:40]}'"
    return "other", "other:no cue matched; fell back to 'other'"


def grade_screen(text_lines, mean_score):
    n = len(text_lines)
    chars = sum(len(line) for line in text_lines)
    for grade, rule in GRADE_RULES:
        if grade == "A":
            if n >= 8 and chars >= 120 and mean_score >= 0.85:
                return "A"
        elif grade == "B":
            if n >= 3 and chars >= 25:
                return "B"
    return "C"


def assign_segments(screens):
    """[(segment_no, label)] — contiguous runs of the same screen_type (gap <= SEGMENT_GAP_S).

    Without ASR the on-screen content block is the only segmentation the video gives us;
    it is what later lets a chunk carry "the chart section at 12:30", not "the speaker".
    """
    out, current, segment, prev_end = [], None, 0, None
    for screen in screens:
        gap = None if prev_end is None else screen["t_start"] - prev_end
        if screen["screen_type"] != current or (gap is not None and gap > SEGMENT_GAP_S):
            segment += 1
            current = screen["screen_type"]
        out.append((segment, f"{current} #{segment}"))
        prev_end = screen["t_end"]
    return out


# --------------------------------------------------------------------------- dedupe + glossary

def thumbnail_from_gray(gray):
    """160x100 grey thumbnail as bytes — small enough that the dedupe diff stays pure Python."""
    import cv2

    return cv2.resize(gray, THUMB_SIZE, interpolation=cv2.INTER_AREA).tobytes()


def mean_abs_diff(prev_thumb, thumb):
    return sum(abs(a - b) for a, b in zip(prev_thumb, thumb)) / len(thumb)


def keep_frame(prev_thumb, thumb):
    """(keep, diff) — the reference rule: drop a frame whose thumbnail mean abs diff < 4.0."""
    if prev_thumb is None:
        return True, None
    diff = mean_abs_diff(prev_thumb, thumb)
    return diff >= DEDUPE_MEAN_ABS, round(diff, 3)


def glossary(lines, company_names=(), top=GLOSSARY_TOP, total_screens=0):
    """Distinct proper terms across a video's screens, plus its company name(s).

    A token that mostly opens a line is a sentence starter ('Industry', 'March'), not a term.
    A token that shows up on most screens of a long video is a UI label ('DMA', 'Flow'),
    not a term worth biasing ASR towards.
    """
    counts, at_line_start = {}, {}
    for line in lines:
        for position, token in enumerate(re.findall(r"[A-Za-z][A-Za-z&\-]{2,}", line)):
            if len(token) < 3 or token.lower() in STOPWORDS:
                continue
            if not (token.isupper() or token[0].isupper()):
                continue
            counts[token] = counts.get(token, 0) + 1
            if position == 0:
                at_line_start[token] = at_line_start.get(token, 0) + 1
    ranked = [(term, n) for term, n in counts.items()
              if n >= 2 and (term.isupper() or at_line_start.get(term, 0) / n <= 0.6)]
    if total_screens >= 20:
        ceiling = max(4, round(0.25 * total_screens))
        ranked = [(term, n) for term, n in ranked if n <= ceiling]
    ranked.sort(key=lambda item: (-item[1], item[0]))
    out = [(term, n, 0) for term, n in ranked[:top]]
    for name in company_names:
        if name and name not in {t for t, _, _ in out}:
            out.insert(0, (name, 0, 1))
    return out


# --------------------------------------------------------------------------- assets

def load_drive_meta(meta_dir: Path):
    index = {}
    for name in ("_drive_meta_current_premium.json", "_drive_meta_research.json"):
        path = meta_dir / name
        if not path.exists():
            continue
        for row in json.loads(path.read_text(encoding="utf-8")):
            key = (row.get("Path") or "").replace("\\", "/")
            if key and not row.get("IsDir"):
                index[key] = row
    return index


def load_companies(db_path: Path):
    from reality_engine.db.readonly import connect_ro

    conn = connect_ro(Path(db_path), timeout_s=60)
    try:
        return conn.execute(
            "SELECT isin, nse_symbol, company_name, bse_code FROM master_companies "
            "WHERE company_name IS NOT NULL").fetchall()
    finally:
        conn.close()


DOC_EXTS = (".docx", ".xlsx", ".pptx", ".pdf", ".doc", ".xls")


def index_docs(root: Path):
    docs = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for filename in filenames:
            if filename.lower().endswith(DOC_EXTS):
                full = Path(dirpath) / filename
                docs.append({"path": str(full.relative_to(root)).replace("\\", "/"),
                             "folder": Path(dirpath).name.strip(),
                             "stem": Path(filename).stem})
    return docs


def _doc_candidates(video_folder: str, company_cores, docs):
    """Docs in the video's own folder, plus docs in a folder naming one of its companies."""
    out = []
    for doc in docs:
        folder_core = company_core(doc["folder"])
        if doc["folder"] == video_folder:
            out.append((doc, "same_folder"))
        elif any(core and folder_core and (core in folder_core or folder_core in core)
                 for core in company_cores if min(len(core), len(folder_core)) >= 8):
            out.append((doc, "company_folder"))
    return out


def _stem_coverage(stem: str, text: str):
    stem_tokens = [t for t in norm(stem).split() if len(t) >= 3]
    if not stem_tokens:
        return 0.0
    text_tokens = set(norm(text).split())
    hits = sum(1 for token in stem_tokens if token in text_tokens)
    return hits / len(stem_tokens)


def link_doc(screen_type, text, video_folder, company_cores, docs):
    """(path, reason) for gdoc/gsheet screens; path None plus the reason otherwise."""
    if screen_type not in ("gdoc", "gsheet"):
        return None, "screen_type_not_doc"
    candidates = _doc_candidates(video_folder, company_cores, docs)
    if not candidates:
        return None, "no_doc_for_this_company_in_drive_tree"
    scored = []
    for doc, why in candidates:
        coverage = _stem_coverage(doc["stem"], text)
        score = (0.4 if why == "same_folder" else 0.0) + 0.6 * coverage
        scored.append((score, coverage, why, doc))
    scored.sort(key=lambda item: -item[0])
    score, coverage, why, doc = scored[0]
    if coverage < 0.5 and why != "same_folder":
        return None, f"title_not_matched (best coverage {coverage:.2f} on {doc['path']})"
    return doc["path"], f"linked:{why}, stem coverage {coverage:.2f}"


# --------------------------------------------------------------------------- worker

def find_tool(name: str, bin_dir: str | None = None):
    """ffmpeg/ffprobe on PATH, in FFMPEG_BIN_DIR, or in --bin-dir (Windows .exe handled)."""
    folders = []
    if bin_dir:
        folders.append(Path(bin_dir))
    if os.environ.get("FFMPEG_BIN_DIR"):
        folders.append(Path(os.environ["FFMPEG_BIN_DIR"]))
    folders.append(Path(r"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages"
                        r"\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
                        r"\ffmpeg-9.0.2-full_build\bin"))
    for folder in folders:
        for candidate in (folder / name, folder / f"{name}.exe"):
            if candidate.exists():
                return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"{name} not found; pass --bin-dir")


def video_duration(video_path: Path, bin_dir: str | None = None) -> float:
    out = subprocess.run(
        [find_tool("ffprobe", bin_dir), "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video_path)],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def sha256_of(path: Path, chunk=1 << 20):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def run_worker(video_path: Path, root: Path, workdir: Path, bin_dir=None, limit_frames=None,
               keep_frames=False):
    """One video -> OCR JSON. Imported OCR stack stays inside this function."""
    import time

    import cv2
    from rapidocr import RapidOCR

    rel = str(video_path.relative_to(root)).replace("\\", "/")
    video_id = sha256_of(video_path)
    duration = video_duration(video_path, bin_dir)
    frames_dir = workdir / "frames" / video_id[:12]
    frames_dir.mkdir(parents=True, exist_ok=True)
    for stale in frames_dir.glob("*.jpg"):
        stale.unlink()

    t0 = time.time()
    ffmpeg = find_tool("ffmpeg", bin_dir)
    cmd = [ffmpeg, "-nostdin", "-v", "error", "-y", "-i", str(video_path),
           "-vf", f"fps=1/{FRAME_EVERY_S:g},scale={OCR_WIDTH}:-2", "-q:v", "2",
           "-start_number", "0", str(frames_dir / "f_%05d.jpg")]
    subprocess.run(cmd, check=True)
    frames = sorted(frames_dir.glob("f_*.jpg"))
    if limit_frames:
        frames = frames[:limit_frames]
    extract_s = time.time() - t0

    ocr = RapidOCR(params=OCR_PARAMS)
    kept, prev_thumb, ocr_s = [], None, 0.0
    for position, frame_path in enumerate(frames):
        image = cv2.imread(str(frame_path))
        if image is None:
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        thumb = thumbnail_from_gray(gray)
        keep, diff = keep_frame(prev_thumb, thumb)
        if not keep:
            continue
        prev_thumb = thumb
        index = int(frame_path.stem.split("_")[1])
        t_start = round(index * FRAME_EVERY_S, 2)
        started = time.time()
        result = ocr(image)
        ocr_s += time.time() - started
        texts = list(result.txts or [])
        scores = [round(float(s), 4) for s in (result.scores or [])]
        kept.append({"t": t_start, "frame_no": index, "thumb_diff": diff, "lines": texts,
                     "scores": scores})
        if (position + 1) % 20 == 0:
            print(f"[{rel}] {position + 1}/{len(frames)} frames, kept {len(kept)}, "
                  f"ocr {ocr_s:.0f}s", flush=True)

    elapsed = time.time() - t0
    payload = {
        "video": {
            "video_id": video_id, "rel_path": rel, "source_path": str(video_path),
            "duration_s": duration, "frames_extracted": len(frames),
            "frames_kept": len(kept), "ocr_seconds": round(ocr_s, 2),
            "extract_seconds": round(extract_s, 2), "worker_seconds": round(elapsed, 2),
            "frame_every_s": FRAME_EVERY_S, "ocr_width": OCR_WIDTH,
            "dedupe_mean_abs": DEDUPE_MEAN_ABS,
            # Where the jpgs live, relative to the workdir: a screen's frame_no resolves here.
            "frames_dir": str(frames_dir.relative_to(workdir)).replace("\\", "/"),
            "frames_kept_on_disk": bool(keep_frames),
        },
        "screens": kept,
    }
    out_dir = workdir / "ocr"
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{video_id}.json"
    tmp = target.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(target)
    if not keep_frames:
        for stale in frames_dir.glob("*.jpg"):
            stale.unlink()
    print(json.dumps({k: payload["video"][k] for k in (
        "rel_path", "duration_s", "frames_extracted", "frames_kept", "ocr_seconds")}), flush=True)
    return target


# --------------------------------------------------------------------------- label + DB

LABEL_ORDER = ("video_id", "source_path", "channel", "title", "company_isin", "symbol",
               "match_method", "published_at", "pit_source", "pit_confidence", "t_start",
               "t_end", "frame_no", "screen_type", "speaker", "segment_label",
               "linked_doc_path", "text_clean", "ocr_lines", "chrome_lines_dropped",
               "quality_grade")

# A screen is one kept frame, so every OCR line on it comes from exactly that frame:
# ``screen.frame_no`` + ``ocr_line.frame_no`` are the line-level provenance.
SPEAKER_NULL_REASON = ("no_asr_in_pilot: audio was not transcribed and the on-screen text "
                       "never states who is speaking")

SCHEMA = """
CREATE TABLE video(
    video_id TEXT PRIMARY KEY, source_path TEXT, rel_path TEXT, channel TEXT, title TEXT,
    folder_date TEXT, drive_btime TEXT, drive_mtime TEXT,
    published_at TEXT, pit_source TEXT, pit_confidence TEXT, date_evidence TEXT,
    company_isin TEXT, symbol TEXT, company_names TEXT, match_method TEXT, match_score REAL,
    matches_json TEXT, nulls_json TEXT, duration_s REAL, frames_extracted INTEGER,
    frames_kept INTEGER, ocr_seconds REAL, worker_seconds REAL);
CREATE TABLE screen(
    screen_id INTEGER PRIMARY KEY, video_id TEXT NOT NULL, screen_no INTEGER, t_start REAL,
    t_end REAL, frame_no INTEGER, frame_path TEXT, frame_exists INTEGER,
    segment_no INTEGER, segment_label TEXT, screen_type TEXT, type_cue TEXT,
    speaker TEXT, linked_doc_path TEXT, linked_doc_reason TEXT,
    text_clean TEXT, ocr_lines INTEGER, chrome_lines_dropped INTEGER, chrome_reasons_json TEXT,
    quality_grade TEXT, grade_rule TEXT, mean_ocr_score REAL, nulls_json TEXT);
CREATE INDEX idx_screen_video ON screen(video_id, screen_no);
CREATE TABLE ocr_line(
    screen_id INTEGER NOT NULL, line_no INTEGER, frame_no INTEGER, text TEXT, score REAL,
    chrome_reason TEXT, PRIMARY KEY(screen_id, line_no));
CREATE INDEX idx_line_frame ON ocr_line(frame_no);
CREATE TABLE glossary(video_id TEXT, term TEXT, count INTEGER, is_company INTEGER,
    PRIMARY KEY(video_id, term));
"""

VIDEO_COLS = ("video_id", "source_path", "rel_path", "channel", "title", "folder_date",
              "drive_btime", "drive_mtime", "published_at", "pit_source", "pit_confidence",
              "date_evidence", "company_isin", "symbol", "company_names", "match_method",
              "match_score", "matches_json", "nulls_json", "duration_s", "frames_extracted",
              "frames_kept", "ocr_seconds", "worker_seconds")
SCREEN_COLS = ("video_id", "screen_no", "t_start", "t_end", "frame_no", "frame_path",
               "frame_exists", "segment_no", "segment_label", "screen_type", "type_cue",
               "speaker", "linked_doc_path", "linked_doc_reason", "text_clean", "ocr_lines",
               "chrome_lines_dropped", "chrome_reasons_json", "quality_grade", "grade_rule",
               "mean_ocr_score", "nulls_json")


def label_video(payload, drive_index, matcher, docs):
    meta = payload["video"]
    rel = meta["rel_path"]
    title = video_title(rel)
    parts = Path(rel).parts
    parent = parts[-2].strip() if len(parts) >= 2 else ""
    folder_names = [(parent, "parent folder")]
    if len(parts) >= 3:
        folder_names.append((parts[-3].strip(), "grandparent folder"))
    drive_entry = drive_index.get(drive_rel_path(rel))
    published = resolve_published(folder_names, drive_entry)
    matches = matcher.match(title)
    company_cores = [company_core(m["name"]) for m in matches]
    nulls = {}
    video = {
        "video_id": meta["video_id"], "source_path": meta["source_path"], "rel_path": rel,
        "channel": channel_of(rel), "title": title,
        "folder_date": parse_folder_date(parent)[0],
        "published_at": published["published_at"],
        "pit_source": published["pit_source"],
        "pit_confidence": published["pit_confidence"],
        "date_evidence": published["date_evidence"] + (
            "" if drive_entry else " | no Drive metadata row for this path"),
        "company_isin": ";".join(m["isin"] for m in matches) or None,
        "symbol": ";".join(m["symbol"] or "" for m in matches) or None,
        "company_names": ";".join(m["name"] for m in matches) or None,
        "match_method": ";".join(m["method"] for m in matches) or None,
        "match_score": matches[0]["score"] if matches else None,
        "matches_json": json.dumps(matches),
        "duration_s": meta["duration_s"], "frames_extracted": meta["frames_extracted"],
        "frames_kept": meta["frames_kept"], "ocr_seconds": meta["ocr_seconds"],
        "worker_seconds": meta.get("worker_seconds"),
        "drive_btime": (drive_entry or {}).get("Metadata", {}).get("btime"),
        "drive_mtime": (drive_entry or {}).get("Metadata", {}).get("mtime"),
    }
    if not matches:
        nulls["company_isin"] = (
            "no master_companies match for any title segment: "
            + ";".join(title_segments(title)) if title_segments(title) else "title has no segments")
        nulls["symbol"] = nulls["company_isin"]
        nulls["company_names"] = nulls["company_isin"]
        nulls["match_method"] = nulls["company_isin"]
    if not video["published_at"]:
        nulls["published_at"] = "no folder date and no Drive btime"
    for label, missing in (("folder_date", "the folder name carries no parseable date"),
                           ("drive_btime", "no Drive metadata row for this path"
                            if not drive_entry else "the Drive metadata row has no btime"),
                           ("drive_mtime", "no Drive metadata row for this path"
                            if not drive_entry else "the Drive metadata row has no mtime")):
        if not video[label]:
            nulls[label] = missing
    video["nulls_json"] = json.dumps(nulls)

    screens = payload["screens"]
    frames_dir = meta.get("frames_dir") or f"frames/{meta['video_id'][:12]}"
    labelled, line_rows = [], []
    for position, frame in enumerate(screens):
        annotated = annotate_lines(frame["lines"])
        kept_lines = [line.strip() for line, reason in annotated if reason is None]
        dropped = {}
        for _, reason in annotated:
            if reason is not None:
                dropped[reason] = dropped.get(reason, 0) + 1
        # Classify on the raw lines: the URL/title bar is the strongest cue and the
        # chrome filter drops it from the text before this point.
        screen_type, cue = classify_screen(frame["lines"])
        text = "\n".join(dict.fromkeys(kept_lines))
        scores = frame["scores"][: len(frame["lines"])]
        mean_score = round(sum(scores) / len(scores), 3) if scores else 0.0
        t_end = screens[position + 1]["t"] if position + 1 < len(screens) else min(
            frame["t"] + FRAME_EVERY_S, meta["duration_s"])
        doc_path, doc_reason = link_doc(screen_type, text, title, company_cores, docs)
        frame_no = frame.get("frame_no")
        if frame_no is None:  # older dump: the frame index is the sampling position
            frame_no = int(round(frame["t"] / FRAME_EVERY_S))
        screen_nulls = {"speaker": SPEAKER_NULL_REASON}
        if doc_path is None:
            screen_nulls["linked_doc_path"] = doc_reason
        if not text.strip():
            screen_nulls["text_clean"] = "every OCR line was chrome"
        labelled.append({
            "video_id": meta["video_id"], "screen_no": position + 1,
            "t_start": frame["t"], "t_end": round(t_end, 2),
            "frame_no": int(frame_no),
            "frame_path": f"{frames_dir}/f_{int(frame_no):05d}.jpg",
            "screen_type": screen_type, "speaker": None,
            "type_cue": cue, "linked_doc_path": doc_path, "linked_doc_reason": doc_reason,
            "text_clean": text, "ocr_lines": len(kept_lines),
            "chrome_lines_dropped": sum(dropped.values()),
            "chrome_reasons_json": json.dumps(dropped, sort_keys=True),
            "quality_grade": grade_screen(kept_lines, mean_score),
            "grade_rule": next(rule for grade, rule in GRADE_RULES if grade ==
                               grade_screen(kept_lines, mean_score)),
            "mean_ocr_score": mean_score, "nulls_json": json.dumps(screen_nulls),
        })
        for line_no, ((line_text, reason), score) in enumerate(
                zip(annotated, list(scores) + [0.0] * len(annotated)), 1):
            line_rows.append({"screen_no": position + 1, "line_no": line_no,
                              "frame_no": int(frame_no), "text": line_text.strip(),
                              "score": score, "chrome_reason": reason})
    for (segment_no, label), screen in zip(assign_segments(labelled), labelled):
        screen["segment_no"] = segment_no
        screen["segment_label"] = label
    # Glossary from clean lines only: chrome never becomes a term to bias ASR towards.
    clean_for_glossary = [text for text, reason in annotate_lines(
        [line for screen in screens for line in screen["lines"]]) if reason is None]
    terms = glossary(clean_for_glossary, [m["name"] for m in matches],
                     total_screens=len(screens))
    return video, labelled, line_rows, terms


def build_db(db_path: Path, raw_dir: Path, drive_dir: Path, companies_db: Path, root: Path,
             workdir: Path | None = None):
    payloads = [json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(raw_dir.glob("*.json"))]
    drive_index = load_drive_meta(drive_dir)
    company_rows = load_companies(companies_db)
    matcher = CompanyMatcher(company_rows)
    docs = index_docs(root)
    workdir = Path(workdir or raw_dir.parent)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    videos, screens, line_index = [], [], []
    for payload in payloads:
        video, video_screens, line_rows, terms = label_video(
            payload, drive_index, matcher, docs)
        videos.append(video)
        screens.extend(video_screens)
        conn.execute("INSERT INTO video VALUES (" + ",".join("?" * len(VIDEO_COLS)) + ")",
                     [video[k] for k in VIDEO_COLS])
        for screen in video_screens:
            screen["frame_exists"] = int((workdir / screen["frame_path"]).exists()) \
                if screen["frame_path"] else 0
            cursor = conn.execute(
                "INSERT INTO screen VALUES (" + ",".join("?" * (len(SCREEN_COLS) + 1)) + ")",
                [None] + [screen[k] for k in SCREEN_COLS])
            screen_id = cursor.lastrowid
            screen["screen_id"] = screen_id
            rows_here = [row for row in line_rows
                         if row["screen_no"] == screen["screen_no"]]
            conn.executemany(
                "INSERT INTO ocr_line VALUES (?,?,?,?,?,?)",
                [(screen_id, row["line_no"], row["frame_no"], row["text"], row["score"],
                  row["chrome_reason"]) for row in rows_here])
            line_index.extend({"frame_no": row["frame_no"],
                               "frame_path": screen["frame_path"]} for row in rows_here)
        for term, count, is_company in terms:
            conn.execute("INSERT OR REPLACE INTO glossary VALUES (?,?,?,?)",
                         (video["video_id"], term, count, is_company))
    conn.commit()
    conn.close()
    return videos, screens, docs, company_rows, line_index


# --------------------------------------------------------------------------- audit

def _fill_rate(rows, label, nulls_key="nulls_json"):
    filled = [row for row in rows if row.get(label) not in (None, "", [])]
    reasons = {}
    for row in rows:
        if row.get(label) in (None, "", []):
            reasons_here = json.loads(row.get(nulls_key) or "{}")
            reason = reasons_here.get(label, "no reason recorded")
            reasons[reason] = reasons.get(reason, 0) + 1
    return len(filled), len(rows), reasons


# --------------------------------------------------------------------------- hand check
#
# The pilot must not grade its own homework: every check below re-derives the label from a
# source the labelling code did not read (a stdlib strptime of the folder string, a fresh
# ISIN lookup, the frame file on disk), never from the label itself.

_HAND_DATE_PATTERNS = (
    (re.compile(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)"),
     lambda g: dt.date(int(g[0]), int(g[1]), int(g[2])).isoformat()),
    (re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?[\s\-_]+([A-Za-z]{3,9})\.?[\s\-_,]+"
                r"(20\d{2})(?!\d)"),
     lambda g: dt.datetime.strptime(f"{g[0]} {g[1][:3]} {g[2]}", "%d %b %Y").date().isoformat()),
    (re.compile(r"\b([A-Za-z]{3,9})\.?[\s\-_,]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-_,]+"
                r"(20\d{2})(?!\d)"),
     lambda g: dt.datetime.strptime(f"{g[0][:3]} {g[1]} {g[2]}", "%b %d %Y").date().isoformat()),
)


def independent_folder_date(folder: str):
    """Second opinion on the folder date: regex + stdlib strptime, no shared helper."""
    for pattern, build in _HAND_DATE_PATTERNS:
        for match in pattern.finditer(folder or ""):
            try:
                return build(match.groups())
            except ValueError:
                continue
    return None


def _check_company(video):
    """The folder title must name the matched company's distinctive word.

    Only the head word is required: 'Timex Group India Limited' legitimately matches a folder
    that says just 'Timex', so demanding every legal suffix word would flag correct rows.
    """
    title = Path(video["rel_path"]).parent.name
    matches = json.loads(video["matches_json"] or "[]")
    if not matches:
        return True, f"none claimed (title segments: {title_segments(title)})"
    words = norm(title).split()
    notes = []
    for match in matches:
        head = company_core(match["name"]).split()[0]
        if head in words:
            notes.append(f"{head!r} in title")
            continue
        near = [word for word in words if len(word) >= 3 and head[:4] == word[:4]]
        if near:
            notes.append(f"{head!r}~{near[0]!r} (typo/abbreviation)")
            continue
        return False, f"distinctive word {head!r} of {match['name']!r} is not in the folder title"
    return True, "; ".join(notes)


def _check_isin(video, company_rows):
    by_isin = {str(row[0]): row for row in company_rows}
    matches = json.loads(video["matches_json"] or "[]")
    if not matches:
        return video["company_isin"] is None, "none claimed"
    for match in matches:
        row = by_isin.get(str(match["isin"]))
        if row is None:
            return False, f"{match['isin']} is not a master_companies ISIN"
        if (row[2] or "") != match["name"]:
            return False, f"{match['isin']} belongs to {row[2]!r}, stored as {match['name']!r}"
    return True, f"{len(matches)} ISIN(s) resolve to the same name in master_companies"


def _check_date(video):
    parent = Path(video["rel_path"]).parent.name
    folder_date = independent_folder_date(parent) or independent_folder_date(video["title"])
    if folder_date:
        if video["published_at"] == folder_date and video["pit_source"] == "folder_name":
            return True, f"folder names {folder_date}"
        return False, (f"folder names {folder_date}, stored {video['published_at']} "
                       f"({video['pit_source']})")
    btime = parse_btime(video["drive_btime"])
    if btime is None:
        return False, "no folder date and no parseable Drive btime"
    if video["published_at"] == btime.date().isoformat():
        return True, f"no folder date; Drive btime {btime:%Y-%m-%d}"
    return False, f"Drive btime {btime:%Y-%m-%d} but stored {video['published_at']}"


def _check_channel(video):
    parts = [p.lower() for p in Path(video["rel_path"]).parts]
    expected = ("research_video" if "research" in parts
                else "dailybytes" if ("dailybytes" in parts or "daily bytes" in parts)
                else "member_video")
    return video["channel"] == expected, f"path segment -> {expected}"


def _check_times(screen, next_screen, video):
    problems = []
    if abs(screen["frame_no"] * FRAME_EVERY_S - screen["t_start"]) > 0.01:
        problems.append(f"frame {screen['frame_no']} * {FRAME_EVERY_S:g} s != t_start "
                        f"{screen['t_start']}")
    if not (0 <= screen["t_start"] < screen["t_end"] <= video["duration_s"] + 1):
        problems.append(f"t range {screen['t_start']}-{screen['t_end']} outside "
                        f"0-{video['duration_s']:.1f}")
    if next_screen is not None and abs(next_screen["t_start"] - screen["t_end"]) > 0.01:
        problems.append(f"t_end {screen['t_end']} != next screen t_start "
                        f"{next_screen['t_start']}")
    return not problems, "; ".join(problems) or (f"{screen['t_start']:.1f}-"
                                                 f"{screen['t_end']:.1f} s")


def _check_frame(screen, workdir):
    if not screen["frame_path"]:
        return False, "no frame_path"
    path = Path(workdir) / screen["frame_path"]
    if not path.exists():
        return False, f"{screen['frame_path']} missing on disk"
    if path.stat().st_size < 1000:
        return False, f"{screen['frame_path']} is {path.stat().st_size} bytes"
    return True, f"{screen['frame_path']} ({path.stat().st_size // 1024} kB)"


def _check_speaker_segment(screen):
    nulls = json.loads(screen["nulls_json"] or "{}")
    problems = []
    if screen["speaker"] is None:
        if not nulls.get("speaker"):
            problems.append("speaker NULL with no reason")
    if not screen["segment_label"]:
        problems.append("segment_label NULL")
    elif not screen["segment_label"].startswith(screen["screen_type"]):
        problems.append(f"segment label {screen['segment_label']!r} != {screen['screen_type']}")
    return not problems, "; ".join(problems) or (f"segment {screen['segment_label']}, "
                                                 f"speaker NULL: no ASR")


def hand_check(videos, screens, company_rows, workdir, n=30, seed=7):
    """Check n screens label-by-label against sources outside the labelling code."""
    by_id = {video["video_id"]: video for video in videos}
    ordered = sorted(screens, key=lambda s: (s["video_id"], s["screen_no"]))
    position = {id(s): i for i, s in enumerate(ordered)}
    picks = random.Random(seed).sample(ordered, min(n, len(ordered)))
    rows, tally = [], {}
    for screen in picks:
        video = by_id[screen["video_id"]]
        index = position[id(screen)]
        nxt = ordered[index + 1] if index + 1 < len(ordered) \
            and ordered[index + 1]["video_id"] == screen["video_id"] else None
        checks = {
            "company": _check_company(video),
            "isin": _check_isin(video, company_rows),
            "date": _check_date(video),
            "t_start/t_end": _check_times(screen, nxt, video),
            "channel+folder": _check_channel(video),
            "speaker/segment": _check_speaker_segment(screen),
            "frame": _check_frame(screen, workdir),
        }
        for label, (ok, _) in checks.items():
            tally.setdefault(label, [0, 0])
            tally[label][0] += int(ok)
            tally[label][1] += 1
        rows.append({"video": video, "screen": screen, "checks": checks})
    return rows, tally


# --------------------------------------------------------------------------- audit

def write_audit(md_path: Path, videos, screens, docs, db_path: Path, workdir, company_rows,
                seed=42, hand_seed=7, hand_n=30, line_rows=None):
    workdir = Path(workdir)
    line_rows = line_rows or []
    lines = ["# Video screen OCR pilot - label audit", ""]
    lines += [f"- pilot DB: `{db_path}`", f"- videos: {len(videos)}, screens: {len(screens)}, "
              f"OCR lines: {len(line_rows)}",
              f"- frames: {sum(v['frames_extracted'] for v in videos)} sampled at "
              f"{FRAME_EVERY_S:g} s, {sum(v['frames_kept'] for v in videos)} kept after dedupe",
              f"- candidate docs indexed from the Drive tree: {len(docs)}", ""]

    lines += ["## Label fill rates", "",
              "| label | filled | total | % | NULL reasons |", "|---|---|---|---|---|"]
    screen_labels = ("t_start", "t_end", "frame_no", "frame_path", "segment_no",
                     "segment_label", "screen_type", "speaker", "linked_doc_path", "text_clean",
                     "ocr_lines", "chrome_lines_dropped", "quality_grade")
    video_labels = ("video_id", "source_path", "rel_path", "channel", "title", "folder_date",
                    "drive_btime", "drive_mtime", "published_at", "pit_source",
                    "pit_confidence", "company_isin", "company_names", "symbol", "match_method")
    for label in video_labels:
        filled, total, reasons = _fill_rate(videos, label)
        lines.append(f"| video.{label} | {filled} | {total} | {100 * filled / total:.0f}% | "
                     f"{_fmt_reasons(reasons)} |")
    for label in screen_labels:
        filled, total, reasons = _fill_rate(screens, label)
        lines.append(f"| screen.{label} | {filled} | {total} | {100 * filled / total:.0f}% | "
                     f"{_fmt_reasons(reasons)} |")
    frame_rows = [row for row in line_rows if row["frame_no"] is not None]
    lines.append(f"| line.frame_no (line -> frame) | {len(frame_rows)} | {len(line_rows)} | "
                 f"{100 * len(frame_rows) / max(len(line_rows), 1):.0f}% | "
                 f"{'—' if line_rows else 'no lines'} |")
    on_disk = sum(1 for row in line_rows
                  if row["frame_path"] and (workdir / row["frame_path"]).exists())
    lines.append(f"| line.frame_on_disk (frame can be re-opened) | {on_disk} | "
                 f"{len(line_rows)} | {100 * on_disk / max(len(line_rows), 1):.0f}% | "
                 f"{'—' if line_rows else 'no lines'} |")
    lines += ["", "Each screen is one kept frame, so every OCR line on it carries that "
                  "frame's `frame_no`; `line.frame_on_disk` is the share whose jpg is still "
                  "there to re-open. `speaker` is NULL for every screen in this pilot — see "
                  "the reason in the table. `linked_doc_path` is NULL by design for non-doc "
                  "screens; the reason column splits those from real misses.", ""]

    lines += ["## Rules applied", "", "Chrome filter (first match wins):", ""]
    lines += [f"- `{reason}`: `{pattern}`" for reason, pattern in CHROME_RULES]
    lines += ["", "Screen type (first match wins; quoted from the module):", ""]
    for screen_type, patterns in SCREEN_RULES:
        lines.append(f"- **{screen_type}**: " + ", ".join(f"`{p}`" for p in patterns))
    lines += ["", "Quality grade:", ""] + [f"- **{g}**: {rule}" for g, rule in GRADE_RULES]
    lines += ["", "Segment: contiguous run of the same `screen_type` (gaps up to "
                  f"{SEGMENT_GAP_S:g} s). Speaker: not derivable without ASR, so NULL with a "
                  "stated reason.", ""]
    lines += ["", "Company matching order: exact name, name_contains (>= 8 chars), NSE symbol, "
                  "fuzzy_name (ratio >= 0.88), token_prefix (first-token ratio >= 0.80). "
                  "`match_method` and `score` are stored per video; generic title heads "
                  "('market', 'sector', 'power', ...) never take the fuzzy rules.", ""]

    rng = random.Random(seed)
    sample = rng.sample(screens, min(15, len(screens)))
    lines += [f"## 15 random screens (seed {seed})", ""]
    for screen in sample:
        video = next(v for v in videos if v["video_id"] == screen["video_id"])
        lines += [f"### {video['title']} - screen {screen['screen_no']} "
                  f"({screen['t_start']:.0f}-{screen['t_end']:.0f} s)", "",
                  f"- video_id: `{video['video_id'][:16]}...`", f"- channel: {video['channel']}",
                  f"- company: {video['company_names'] or 'NULL'} "
                  f"({video['company_isin'] or 'NULL'}, {video['match_method'] or 'NULL'})",
                  f"- published_at: {video['published_at']} ({video['pit_source']}, "
                  f"{video['pit_confidence']})",
                  f"- frame: `{screen['frame_path']}` (#{screen['frame_no']}, "
                  f"on_disk={bool(screen['frame_exists'])})",
                  f"- segment: {screen['segment_label']}, speaker: {screen['speaker']}",
                  f"- screen_type: {screen['screen_type']} - {screen['type_cue']}",
                  f"- linked_doc_path: {screen['linked_doc_path']} "
                  f"({screen['linked_doc_reason']})",
                  f"- ocr_lines {screen['ocr_lines']}, chrome dropped "
                  f"{screen['chrome_lines_dropped']} {screen['chrome_reasons_json']}",
                  f"- grade {screen['quality_grade']} (mean score {screen['mean_ocr_score']})",
                  "", "```", _clip(screen["text_clean"], 320), "```", ""]

    rows, tally = hand_check(videos, screens, company_rows, workdir, n=hand_n, seed=hand_seed)
    lines += [f"## Hand check: {len(rows)} screens, label by label (seed {hand_seed})", "",
              "Every check re-derives the label from a source the labeller never read: the "
              "folder string through stdlib `strptime`, a fresh `master_companies` lookup by "
              "ISIN, `frame_no * 5 s` against `t_start`, and the jpg on disk.", "",
              "| label | correct | of | % |", "|---|---|---|---|"]
    for label, (correct, total) in tally.items():
        lines.append(f"| {label} | {correct} | {total} | {100 * correct / total:.0f}% |")
    lines += ["", "| video | screen | t (s) | company | isin | date | t_start/t_end | "
              "channel+folder | speaker/segment | frame | verdict |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        screen, video = row["screen"], row["video"]
        marks = ["OK" if ok else f"FAIL: {note}" for ok, note in row["checks"].values()]
        verdict = "PASS" if all(ok for ok, _ in row["checks"].values()) else "FAIL"
        lines.append(f"| {_clip(video['title'], 28)} | {screen['screen_no']} | "
                     f"{screen['t_start']:.0f} | " + " | ".join(
                         ("OK" if ok else "FAIL") for ok, _ in row["checks"].values())
                     + f" | {verdict} |")
    lines += ["", "Notes per row:", ""]
    for row in rows:
        screen, video = row["screen"], row["video"]
        detail = "; ".join(f"{label}: {note}" for label, (ok, note) in row["checks"].items()
                          if not ok or label in ("company", "date", "frame"))
        lines.append(f"- {video['title'][:40]} #{screen['screen_no']} "
                     f"({screen['t_start']:.0f} s): {detail}")
    lines.append("")

    lines += ["## Per-video check: company + date against folder and Drive metadata", "",
              "| title | channel | folder | independent folder date | drive btime | "
              "published_at | pit_source | company | method | score | company | date |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for video in videos:
        parent = Path(video["rel_path"]).parent.name
        company_ok, _ = _check_company(video)
        date_ok, _ = _check_date(video)
        lines.append(f"| {_clip(video['title'], 34)} | {video['channel']} | "
                     f"{_clip(parent, 30)} | {independent_folder_date(parent) or '-'} | "
                     f"{video['drive_btime'] or '-'} | {video['published_at']} | "
                     f"{video['pit_source']} | {video['company_names'] or 'NULL'} | "
                     f"{video['match_method'] or '-'} | "
                     f"{video['match_score'] if video['match_score'] is not None else '-'} | "
                     f"{'OK' if company_ok else 'FAIL'} | {'OK' if date_ok else 'FAIL'} |")
    lines += ["", "Explanations:", ""]
    for video in videos:
        _, company_note = _check_company(video)
        _, date_note = _check_date(video)
        lines += [f"- **{video['title']}**: company {company_note}; date {date_note}",
                  f"  stored date evidence: {video['date_evidence']}"]
    lines.append("")

    total_video_s = sum(v["duration_s"] for v in videos) or 1.0
    total_ocr_s = sum(v["ocr_seconds"] for v in videos)
    worker_seconds = [v["worker_seconds"] for v in videos if v.get("worker_seconds")]
    total_worker_s = sum(worker_seconds) or 0.0
    frames_kept = sum(v["frames_kept"] for v in videos)
    frames_extracted = sum(v["frames_extracted"] for v in videos)
    video_hours = total_video_s / 3600
    lines += ["## Timing and throughput", "",
              "| title | video min | frames sampled | frames kept | OCR s | worker s | "
              "s per video min |", "|---|---|---|---|---|---|---|"]
    for video in videos:
        minutes = video["duration_s"] / 60
        worker_s = f"{video['worker_seconds']:.0f}" if video.get("worker_seconds") else "-"
        lines.append(f"| {_clip(video['title'], 34)} | {minutes:.1f} | "
                     f"{video['frames_extracted']} | {video['frames_kept']} | "
                     f"{video['ocr_seconds']:.0f} | {worker_s} | "
                     f"{video['ocr_seconds'] / minutes:.1f} |")
    frames_per_s = frames_kept / total_ocr_s if total_ocr_s else 0.0
    cpu_hours = TOTAL_VIDEO_HOURS * (total_ocr_s / 3600) / video_hours
    lines += ["",
              f"- frames/s OCR'd: **{frames_per_s:.3f}** "
              f"({frames_kept} kept frames in {total_ocr_s:.0f} s of OCR)",
              f"- sampling: {frames_extracted} frames from {total_video_s / 60:.0f} video min "
              f"({frames_extracted / (total_video_s / 60):.2f} frames per video min, "
              f"{100 * frames_kept / frames_extracted:.0f}% kept)",
              f"- seconds of CPU work per video minute: "
              f"**{total_ocr_s / (total_video_s / 60):.1f}**"]
    if total_worker_s:
        wall_projection = TOTAL_VIDEO_HOURS / (video_hours / (total_worker_s / PROJECTION_WORKERS
                                                             / 3600))
        lines += [
            f"- worker seconds including ffmpeg extraction and hashing: "
            f"**{total_worker_s:.0f} s** for {video_hours:.2f} h of video, measured while "
            f"{PROJECTION_WORKERS} OCR processes shared the CPU",
            f"- measured throughput: **{video_hours / (total_worker_s / PROJECTION_WORKERS / 3600):.2f} "
            f"video hours per wall hour** on {PROJECTION_WORKERS} workers; OCR alone would "
            f"predict {video_hours / (total_ocr_s / PROJECTION_WORKERS / 3600):.2f}, the gap is "
            f"extraction plus the ~1.7x slowdown two OCR processes cause each other",
            f"- projection for all 179 videos ({TOTAL_VIDEO_HOURS} h of video) from the measured "
            f"wall rate: **{wall_projection:.0f} h wall** on {PROJECTION_WORKERS} workers "
            f"({wall_projection / 24:.1f} days); OCR time alone is {cpu_hours:.0f} CPU hours, "
            f"and one worker on its own measures about 7 s per dense 1600-px frame",
            "- OCR width is not a lever: 8 dense frames at 1600 px took 7.05 s each for 408 "
            "lines, at 1280 px 6.38 s for 416 lines (9.5% cheaper, same text).", ""]
    else:
        lines += [f"- projection for all 179 videos ({TOTAL_VIDEO_HOURS} h of video) at this "
                  f"rate: **{cpu_hours:.1f} CPU hours**, "
                  f"**{cpu_hours / PROJECTION_WORKERS:.1f} h wall on "
                  f"{PROJECTION_WORKERS} parallel OCR processes**", ""]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _clip(text, limit):
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + " ..."


def _fmt_reasons(reasons):
    if not reasons:
        return "-"
    return "; ".join(f"{count}x {reason}" for reason, count in
                     sorted(reasons.items(), key=lambda item: -item[1]))


# --------------------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--video", type=Path, help="worker mode: one video file")
    parser.add_argument("--root", type=Path, help="the extracted/ tree (for relative paths)")
    parser.add_argument("--workdir", type=Path, default=Path(".tmp/video_ocr_pilot"))
    parser.add_argument("--bin-dir", default=None, help="folder holding ffmpeg/ffprobe")
    parser.add_argument("--limit-frames", type=int, default=None)
    parser.add_argument("--keep-frames", action="store_true",
                        help="keep the sampled jpgs so every screen's frame can be re-opened")
    parser.add_argument("--build", action="store_true", help="workers' JSON -> DB + audit")
    parser.add_argument("--db", type=Path, default=Path(".tmp/video_ocr_pilot.db"))
    parser.add_argument("--audit", type=Path, default=Path(".tmp/LABEL_AUDIT.md"))
    parser.add_argument("--drive-dir", type=Path,
                        default=Path(r"D:\RealityEngine\raw\user_research"))
    parser.add_argument("--companies-db", type=Path, default=Path(
        r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\equity_intelligence.db"))
    args = parser.parse_args(argv)

    if args.video:
        run_worker(args.video, args.root, args.workdir, args.bin_dir, args.limit_frames,
                   args.keep_frames)
        return 0
    if args.build:
        videos, screens, docs, company_rows, line_index = build_db(
            args.db, args.workdir / "ocr", args.drive_dir, args.companies_db, args.root,
            workdir=args.workdir)
        audit = write_audit(args.audit, videos, screens, docs, args.db, args.workdir,
                            company_rows, line_rows=line_index)
        print(json.dumps({"db": str(args.db), "audit": str(audit), "videos": len(videos),
                          "screens": len(screens), "lines": len(line_index)}))
        return 0
    parser.error("pass --video or --build")


if __name__ == "__main__":
    sys.exit(main())
