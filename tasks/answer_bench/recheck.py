"""Hand audit of the ANSWERED rows: a full answer means every part of the ask.

The probe is lexical, so it can mark a case ANSWERED when it retrieved the right
kind of evidence for the wrong part of a multi-part question.  This pass reads
RESULTS.jsonl, applies the hand judgements below (question -> answer -> verdict),
and rewrites RESULTS.jsonl in place.  Every downgrade carries the missing hop.

Run after run_bench.py, before rollup.py.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# mid -> (grade, blocker, gap)  -- applied only to rows currently ANSWERED
DOWNGRADE = {
    "MB0008": ("PARTIAL",
               "the start close and the dividend record came back, but the 3-year CAGR needs a "
               "second close and was not computed", "G8"),
    "MB0016": ("PARTIAL",
               "the policy hop matched an RBI facility note, not the repo-hike cause; the "
               "MPC-minutes passage is evidence, the causal trace is not there", "G10"),
    "MB0019": ("PARTIAL",
               "transcript and AR passages came back, but there is no El Nino series and no "
               "dairy peer table, so the question's two parts are not both answered", "G12"),
    "MB0025": ("PARTIAL",
               "promoter holding answered; the equity-share count came back as a divestment "
               "passage, not as the count", "G1"),
    "MB0883": ("PARTIAL",
               "one quarter's promoter % plus the price; whether the promoter group RAISED its "
               "stake needs two quarters compared, and the dilution effect needs shares "
               "outstanding", "G1"),
    "MB0983": ("PARTIAL",
               "one close only; the range edges and the number of tests need intraday bars or "
               "a technical-feature table", "G3"),
    "MB0411": ("BLOCKED_SCHEMA",
               "no impairment / write-down field in any store; the screen answered an EBITDA "
               "ranking instead", "G11"),
    "MB0151": ("PARTIAL",
               "one company's PBT and price; which companies swung Q4->Q1 is not readable "
               "without the unmapped results concept map", "G11"),
    "MB0152": ("PARTIAL",
               "one company's PBT and price; the across-company swing screen is not readable "
               "without the unmapped results concept map", "G11"),
    "MB0164": ("PARTIAL",
               "one day's premium came back; tracking error over the window needs a daily "
               "iNAV series", "G12"),
    "MB0310": ("PARTIAL",
               "raw YTD high only; the adjusted-for-corporate-action high is not produced by "
               "price_extreme(adjusted=True) over a YTD window", "G8"),
    "MB0655": ("PARTIAL",
               "the policy event matches exactly; the transmission trace to sectors and "
               "companies is missing", "G10"),
    "MB0752": ("PARTIAL",
               "transcript commentary on crude volatility only; the lag to the margin trough "
               "needs the input-share and pass-through series", "pass_through"),
}


def main() -> None:
    path = HERE / "RESULTS.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    changed = []
    for r in rows:
        if r["grade"] != "ANSWERED":
            continue
        fix = DOWNGRADE.get(r["mid"])
        if not fix:
            continue
        grade, blocker, gap = fix
        r["grade"] = grade
        r["blocker"] = blocker
        r["gap"] = gap
        r["hand_audit"] = "downgraded from ANSWERED: the retrieved evidence answered part of the ask"
        changed.append(r["mid"])
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    kept = [r["mid"] for r in rows if r["grade"] == "ANSWERED"]
    print(f"downgraded {len(changed)}: {changed}")
    print(f"ANSWERED kept {len(kept)}: {kept}")


if __name__ == "__main__":
    main()
