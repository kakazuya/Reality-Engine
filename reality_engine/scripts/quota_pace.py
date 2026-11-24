"""How much of each 5-hour window an account should spend to reach its weekly target by a deadline (Shivam 24 Nov).

Shivam's estimate: one full 5-hour window costs ~8-9% of the weekly quota.  The plan:

    weekly_left   = target_pct - weekly_used                       (points of weekly quota still to spend)
    k             = weekly points per full 5-hour window            (measured from samples, else 8.5)
    windows_avail = (1 - five_used/100) of the current window       (what is left of it)
                    + whole and part windows from its reset to the deadline
    max_reach     = weekly_used + k * windows_avail                 (spending 100% of every window)
    spend_pct     = min(100, weekly_left / (k * windows_avail) * 100)   (share of EVERY window, current included)
    five_now_due  = five_used target now: what the current window should show by now at spend_pct, linear in time

``spend_pct`` of 100 means "every window to its limit and still short" (max_reach < target).  ``k`` is learned:
each call appends (time, weekly, five, five_reset) to ``.tmp/quota_samples.jsonl``; within one 5-hour window the
ratio of weekly growth to 5-hour growth is k/100, so ``k = 100 * sum(d_weekly) / sum(d_five)`` over samples with
``d_five >= 5`` (weekly is a rounded integer, so small steps are noise).

    python -m reality_engine.scripts.quota_pace            # both accounts, from ops_rules.json "quota"
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RULES = Path(__file__).with_name("ops_rules.json")
SAMPLES = ROOT / ".tmp" / "quota_samples.jsonl"
WINDOW_H = 5.0
DEFAULT_K = 8.5


def read_usage(config: str) -> dict[str, Any] | None:
    try:
        st = json.loads(Path(config, "usage_status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lim = st.get("rate_limits") or {}
    five, seven = lim.get("five_hour") or {}, lim.get("seven_day") or {}
    if five.get("used_percentage") is None or seven.get("used_percentage") is None:
        return None
    return {"five": float(five["used_percentage"]), "five_reset": int(five.get("resets_at") or 0),
            "weekly": float(seven["used_percentage"]), "saved_at": st.get("_saved_at", "")}


def record(name: str, u: dict[str, Any], path: Path | None = None) -> None:
    path = path or SAMPLES
    path.parent.mkdir(parents=True, exist_ok=True)
    last = None
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("name") == name:
                last = r
    row = {"name": name, "five": u["five"], "weekly": u["weekly"], "five_reset": u["five_reset"],
           "saved_at": u["saved_at"]}
    if last and all(last.get(k) == row[k] for k in ("five", "weekly", "five_reset")):
        return
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def learned_k(name: str, path: Path | None = None) -> tuple[float, str]:
    """Weekly points per full 5-hour window from this account's samples, else DEFAULT_K."""
    path = path or SAMPLES
    rows = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("name") == name:
                rows.append(r)
    d_week = d_five = 0.0
    by_window: dict[int, list[dict[str, Any]]] = {}
    for r in rows:
        by_window.setdefault(int(r["five_reset"]), []).append(r)
    for win in by_window.values():
        if len(win) < 2:
            continue
        first, last = win[0], win[-1]
        if last["five"] - first["five"] >= 5:
            d_five += last["five"] - first["five"]
            d_week += last["weekly"] - first["weekly"]
    if d_five >= 20 and d_week > 0:
        return 100 * d_week / d_five, f"measured over {d_five:.0f} five-hour points"
    return DEFAULT_K, "Shivam's estimate (8-9%), not yet measured"


def plan(u: dict[str, Any], target_pct: float, deadline: dt.datetime, now: dt.datetime, k: float) -> dict[str, Any]:
    reset = dt.datetime.fromtimestamp(u["five_reset"]) if u["five_reset"] else now + dt.timedelta(hours=WINDOW_H)
    win_start = reset - dt.timedelta(hours=WINDOW_H)
    current_left = max(0.0, 1 - u["five"] / 100)
    after = max(0.0, (deadline - reset).total_seconds() / 3600 / WINDOW_H) if deadline > reset else 0.0
    if deadline < reset:                      # deadline inside the current window
        current_left *= max(0.0, (deadline - now) / (reset - now)) if reset > now else 0.0
    windows = current_left + after
    weekly_left = max(0.0, target_pct - u["weekly"])
    max_reach = u["weekly"] + k * windows
    spend = 100.0 if windows <= 0 else min(100.0, weekly_left / (k * windows) * 100)
    elapsed = min(1.0, max(0.0, (now - win_start) / (reset - win_start)))
    return {"weekly": u["weekly"], "five": u["five"], "target": target_pct, "deadline": deadline.isoformat(" ", "minutes"),
            "k": round(k, 2), "windows_left": round(windows, 2), "max_reach": round(max_reach, 1),
            "spend_pct": round(spend), "five_due_now": round(spend * elapsed),
            "five_by_reset": round(spend), "reset": reset.isoformat(" ", "minutes"),
            "short": max_reach < target_pct}


def accounts(now: dt.datetime | None = None, rules_path: Path = RULES) -> list[dict[str, Any]]:
    now = now or dt.datetime.now()
    rules = json.loads(rules_path.read_text(encoding="utf-8"))["quota"]
    out = []
    for acc in rules["accounts"]:
        u = read_usage(acc["config"])
        if u is None:
            continue
        record(acc["name"], u)
        k, k_src = learned_k(acc["name"])
        p = plan(u, float(acc["target_pct"]), dt.datetime.fromisoformat(acc["by"]), now, k)
        p.update(name=acc["name"], k_source=k_src, source=acc["source"])
        out.append(p)
    return out


def line(p: dict[str, Any]) -> str:
    head = (f"{p['name']}: weekly {p['weekly']:.0f}% -> target {p['target']:.0f}% by {p['deadline']}; "
            f"{p['windows_left']} five-hour windows left at k={p['k']}%/window ({p['k_source']})")
    if p["short"]:
        return (head + f". SHORT: even 100% of every window reaches only {p['max_reach']}% - run every window to "
                f"the limit (now {p['five']:.0f}%, should be {p['five_due_now']}%, 100% by {p['reset']})")
    return (head + f". Spend {p['spend_pct']}% of each window: now {p['five']:.0f}% vs due {p['five_due_now']}%, "
            f"{p['five_by_reset']}% by reset {p['reset']}")


def main() -> int:
    for p in accounts():
        print(line(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
