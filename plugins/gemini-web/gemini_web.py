"""PARKED 26 Nov 2026: Google rejects sign-in in an automated browser ("This browser or app may not be secure");
by the guard rails below the tool is not worked around. Use a Gemini API key (AI Studio) instead.

gemini-web: ask the Gemini web app (gemini.google.com) from Claude, on Shivam's own signed-in account (26 Nov 2026).

Shivam chose this route knowing it automates the consumer app (Google's terms; account risk). Guard rails, by design:
- one question at a time, MIN_GAP_S between questions, DAILY_CAP questions a day (usage log below);
- no stealth or bot-detection evasion; a captcha / "unusual traffic" / sign-in page stops the tool and writes a LOCK
  file that only Shivam clears (delete it) - the tool never retries past it;
- the browser profile (cookies) lives outside the repo at PROFILE and is never printed or copied.

Usage:
  python plugins/gemini-web/gemini_web.py --login        # one time: a visible Edge window, sign in by hand, close it
  python plugins/gemini-web/gemini_web.py --ask "text"   # one question from the shell (headless)
  python plugins/gemini-web/gemini_web.py --mcp          # stdio MCP server: tools gemini_ask, gemini_status
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

ROOT = Path("C:/RealityEngine/gemini_web")
PROFILE = ROOT / "profile"
USAGE = ROOT / "usage.jsonl"
LOCK = ROOT / "LOCKED.txt"
URL = "https://gemini.google.com/app"
MIN_GAP_S = 20
DAILY_CAP = 150
ANSWER_TIMEOUT_S = 300
STABLE_S = 4                     # the answer text must stop changing this long before it is taken

INPUT_SEL = "rich-textarea div[contenteditable='true'], div.ql-editor[contenteditable='true']"
RESPONSE_SEL = "model-response message-content, model-response .markdown"
BLOCK_CUES = ("unusual traffic", "not a robot", "captcha", "verify it's you", "sign in to continue",
              "couldn't sign you in", "this browser or app may not be secure")


def _log(record: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with USAGE.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _today_count() -> tuple[int, float]:
    if not USAGE.exists():
        return 0, 0.0
    day, n, last = datetime.now().strftime("%Y-%m-%d"), 0, 0.0
    for line in USAGE.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if r.get("kind") == "ask":
            last = max(last, float(r.get("ts", 0)))
            if str(r.get("at", "")).startswith(day):
                n += 1
    return n, last


def status() -> dict:
    n, last = _today_count()
    return {"locked": LOCK.read_text(encoding="utf-8") if LOCK.exists() else None,
            "profile_ready": PROFILE.exists() and any(PROFILE.iterdir()),
            "asked_today": n, "daily_cap": DAILY_CAP, "min_gap_s": MIN_GAP_S,
            "seconds_since_last": round(time.time() - last) if last else None}


def _browser(pw, headless: bool):
    PROFILE.mkdir(parents=True, exist_ok=True)
    return pw.chromium.launch_persistent_context(str(PROFILE), channel="msedge", headless=headless,
                                                 viewport={"width": 1280, "height": 900})


def login() -> None:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _browser(pw, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(URL)
        print("Sign in to Gemini in the Edge window, check a chat opens, then close the window.")
        try:
            page.wait_for_event("close", timeout=0)
        except Exception:
            pass
        ctx.close()
    if LOCK.exists():
        LOCK.unlink()
    print("profile saved:", PROFILE)


def _blocked(page) -> str | None:
    try:
        body = page.inner_text("body", timeout=5000).lower()
    except Exception:
        return None
    for cue in BLOCK_CUES:
        if cue in body:
            return cue
    if "accounts.google.com" in page.url:
        return "redirected to Google sign-in"
    return None


def ask(prompt: str) -> dict:
    st = status()
    if st["locked"]:
        return {"ok": False, "error": f"locked: {st['locked']} - Shivam must check the account, then delete {LOCK}"}
    if not st["profile_ready"]:
        return {"ok": False, "error": "no signed-in profile: run gemini_web.py --login first"}
    if st["asked_today"] >= DAILY_CAP:
        return {"ok": False, "error": f"daily cap {DAILY_CAP} reached"}
    if st["seconds_since_last"] is not None and st["seconds_since_last"] < MIN_GAP_S:
        time.sleep(MIN_GAP_S - st["seconds_since_last"])
    from playwright.sync_api import sync_playwright
    t0 = time.time()
    with sync_playwright() as pw:
        ctx = _browser(pw, headless=True)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            why = _blocked(page)
            if why:
                LOCK.write_text(f"{datetime.now():%Y-%m-%d %H:%M} {why}", encoding="utf-8")
                _log({"kind": "blocked", "at": datetime.now().isoformat(timespec="seconds"), "why": why})
                return {"ok": False, "error": f"stopped: {why} (tool locked)"}
            box = page.locator(INPUT_SEL).first
            box.wait_for(timeout=30000)
            before = page.locator(RESPONSE_SEL).count()
            box.click()
            box.fill(prompt)
            page.keyboard.press("Enter")
            page.wait_for_function(f"document.querySelectorAll({json.dumps(RESPONSE_SEL)}).length > {before}",
                                   timeout=60000)
            last, same_since, text = None, time.time(), ""
            while time.time() - t0 < ANSWER_TIMEOUT_S:
                text = page.locator(RESPONSE_SEL).last.inner_text()
                if text != last:
                    last, same_since = text, time.time()
                elif text.strip() and time.time() - same_since >= STABLE_S:
                    break
                time.sleep(1)
            why = _blocked(page)
            if why:
                LOCK.write_text(f"{datetime.now():%Y-%m-%d %H:%M} {why}", encoding="utf-8")
                return {"ok": False, "error": f"stopped: {why} (tool locked)"}
            sec = round(time.time() - t0, 1)
            _log({"kind": "ask", "at": datetime.now().isoformat(timespec="seconds"), "ts": time.time(),
                  "seconds": sec, "prompt_chars": len(prompt), "answer_chars": len(text)})
            return {"ok": True, "answer": text.strip(), "seconds": sec}
        finally:
            ctx.close()


def serve() -> None:
    from mcp.server.fastmcp import FastMCP
    app = FastMCP("gemini-web")

    @app.tool()
    def gemini_ask(prompt: str) -> dict:
        """Ask the Gemini web app (Shivam's signed-in Pro account) one question; returns its answer text.
        One question at a time, >= 20 s apart, 150 a day; stops and locks on any captcha or sign-in page."""
        return ask(prompt)

    @app.tool()
    def gemini_status() -> dict:
        """Lock state, today's count against the cap, and whether the signed-in profile exists."""
        return status()

    app.run()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--ask")
    ap.add_argument("--mcp", action="store_true")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.ask:
        print(json.dumps(ask(a.ask), ensure_ascii=False, indent=1))
    elif a.mcp:
        serve()
    else:
        print(json.dumps(status(), indent=1))
