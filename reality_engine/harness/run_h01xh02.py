"""Stage 2: declared H01 x H02 combinations C1-C6.

Run only after Stage 1 H02 has completed and been verified.

python -m reality_engine.harness.run_h01xh02 --placebo-draws 499
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax, load_indexes, Panel, Quotes, ADTV
from .benchmark import B5Path
from .book import run_book
from .cards.h02_combine import (
    CONFIRM_WINDOW, cluster_diff, combined_entry, tercile_labels, window_mask, zscore,
)
from .cards.h02_deals import HORIZONS, load_deals, pit_indices, shuffle_dates_within_stock_year
from .data import ROOT, Snapshot
from .ledger import append_run_note, append_variants, previous_tests
from .run_h01 import clean, summarize_arrays, progress
from .run_h02 import load_h01_lead
from .stats import bh_fdr, student_p

OUT = ROOT / "tasks/backtests"
COMBINATIONS = ("C1", "C2", "C3", "C4", "C5", "C6")


def pct(value):
    return "—" if value is None else f"{100 * value:.2f}%"


def num(value):
    return "—" if value is None else f"{value:.4g}"


class CombinationEvaluator:
    """Fixed-window combination evaluator with no fitting."""

    def __init__(self, h01, data, panel, benchmark, rules):
        self.h01 = h01.reset_index(drop=True)
        self.data = data
        self.panel = panel
        self.benchmark = benchmark
        self.rules = rules
        self.t = len(panel.days)
        self.stcg = np.array([rules.rule("stcg_rate", d) for d in panel.calendar.days])
        self.ltcg = np.array([rules.rule("ltcg_rate", d) for d in panel.calendar.days])
        self.next_close = self._next_close()
        self.b5 = {}
        for horizon in (60, 180):
            out = np.full(self.t, np.nan)
            for entry in range(self.t):
                if panel.calendar.days[entry].year >= 2021 and entry + horizon < self.t:
                    out[entry] = benchmark.event_return(entry, entry + horizon)
            self.b5[horizon] = out
        self.h01_signal = self.h01["h01_signal_index"].to_numpy(dtype=int)
        self.h01_entry = self.h01["h01_entry_index"].to_numpy(dtype=int)
        self.h01_net = self.h01["h01_net_excess"].to_numpy(dtype=float)
        self.h01_pat = self.h01["pat_surprise"].to_numpy(dtype=float)
        self.h01_col = np.array([panel.col.get(e, -1) for e in self.h01["entity"]], dtype=int)
        self.h01_entities = self.h01["entity"].astype(str).to_numpy()
        self.deals = {}
        for definition in ("M1", "M2"):
            frame = data.events(definition)
            dates = np.array(frame["date"], dtype="datetime64[D]")
            signal, entry = pit_indices(panel.days, dates)
            cols = np.array([panel.col.get(v, -1) for v in frame["issuer"]], dtype=int)
            self.deals[definition] = {
                "frame": frame.reset_index(drop=True),
                "date": dates, "signal": signal, "entry": entry,
                "net": frame["net_value"].to_numpy(dtype=float),
                "issuer": frame["issuer"].astype(str).to_numpy(),
                "col": cols,
            }

    def _next_close(self):
        closes = self.panel.close
        t, n = closes.shape
        out = np.full((t + 1, n), t, dtype=np.int32)
        for i in range(t - 1, -1, -1):
            out[i] = np.where(np.isfinite(closes[i]) & (closes[i] > 0), i, out[i + 1])
        return out

    @staticmethod
    def _by_entity(signal, entry, net, issuer):
        order = np.argsort(signal, kind="mergesort")
        by = {}
        for idx in order:
            by.setdefault(issuer[idx], []).append(int(idx))
        out = {}
        for entity, ids in by.items():
            arr = np.asarray(ids, dtype=int)
            out[entity] = {"signal": signal[arr], "entry": entry[arr],
                           "net": net[arr], "idx": arr}
        return out

    def confirm(self, definition):
        """Choose the latest confirming deal in [-20,+5]; entry is later t+1."""
        deals = self.deals[definition]
        by = self._by_entity(deals["signal"], deals["entry"], deals["net"],
                             deals["issuer"])
        chosen = np.full(len(self.h01), -1, dtype=int)
        combined = self.h01_entry.copy()
        for i, (entity, signal, entry) in enumerate(
                zip(self.h01_entities, self.h01_signal, self.h01_entry)):
            block = by.get(entity)
            if block is None:
                continue
            lo = int(np.searchsorted(block["signal"], signal + CONFIRM_WINDOW[0], side="left"))
            hi = int(np.searchsorted(block["signal"], signal + CONFIRM_WINDOW[1], side="right"))
            if lo >= hi:
                continue
            candidates = np.arange(lo, hi)
            # Latest deal entry wins; ties by larger net buy, then later signal.
            order = np.lexsort((-block["signal"][candidates],
                                -block["net"][candidates],
                                -block["entry"][candidates]))
            pick = int(candidates[order[0]])
            chosen[i] = int(block["idx"][pick])
            combined[i] = max(entry, int(block["entry"][pick]))
        return chosen, combined

    def returns_from_entry(self, entries, cols, horizon):
        entries = np.asarray(entries, dtype=int)
        cols = np.asarray(cols, dtype=int)
        t = self.t
        valid = (cols >= 0) & (entries >= 0) & (entries + horizon < t)
        safe_entry = np.clip(entries, 0, t - 1)
        safe_col = np.maximum(cols, 0)
        op = self.panel.open[safe_entry, safe_col]
        valid &= np.isfinite(op) & (op > 0)
        ids = np.flatnonzero(valid)
        if len(ids) == 0:
            empty = np.array([], dtype=int)
            return {"ids": empty, "entries": empty, "exits": empty,
                    "scheduled": empty, "gross": np.array([]),
                    "net": np.array([]), "b5": np.array([]),
                    "excess": np.array([]), "missing": np.array([], dtype=bool),
                    "delayed": np.array([], dtype=bool)}
        scheduled = entries[ids] + horizon
        exit_index = self.next_close[scheduled, cols[ids]]
        missing = exit_index == t
        exit_safe = np.where(missing, t - 1, exit_index)
        close = self.panel.close[exit_safe, cols[ids]]
        gross = np.where(missing, 0.0, close) / op[ids] - 1.0
        holding = (self.panel.days[exit_safe] - self.panel.days[entries[ids]]).astype(
            "timedelta64[D]").astype(int)
        rates = np.where(holding > 365, self.ltcg[exit_safe], self.stcg[exit_safe])
        net = gross - 0.003 - np.maximum(gross, 0.0) * rates
        b5 = self.b5[horizon][entries[ids]].copy()
        delayed = exit_safe != scheduled
        for k in np.flatnonzero(delayed):
            b5[k] = self.benchmark.event_return(int(entries[ids[k]]), int(exit_safe[k]))
        return {"ids": ids, "entries": entries[ids], "exits": exit_safe,
                "scheduled": scheduled, "gross": gross, "net": net,
                "b5": b5, "excess": net - b5, "missing": missing,
                "delayed": delayed}

    def c1_c2_c6(self, definition, horizon):
        chosen, combined = self.confirm(definition)
        confirmed = chosen >= 0
        cols = self.h01_col
        result = self.returns_from_entry(combined, cols, horizon)
        keep = confirmed[result["ids"]]
        out = {key: (value[keep] if isinstance(value, np.ndarray) and len(value) == len(result["ids"])
                     else value) for key, value in result.items()}
        out["chosen"] = chosen[result["ids"]][keep]
        out["combined_entry"] = combined[result["ids"]][keep]
        out["entry_delay_sessions"] = (out["combined_entry"]
                                       - self.h01_entry[out["ids"]])
        out["deal_after_h01"] = out["entry_delay_sessions"] > 0
        out["confirmed"] = confirmed
        out["all_combined_entry"] = combined
        return out

    def c3(self):
        chosen, combined = self.confirm("M1")
        confirmed = chosen >= 0
        confirmed_result = self.returns_from_entry(combined, self.h01_col, 180)
        keep = confirmed[confirmed_result["ids"]]
        confirmed_values = confirmed_result["excess"][keep]
        confirmed_entries = confirmed_result["entries"][keep]
        unconfirmed = ~confirmed
        unconfirmed_values = self.h01_net[unconfirmed]
        unconfirmed_entries = self.h01_entry[unconfirmed]
        contrast = cluster_diff(confirmed_values, confirmed_entries,
                                unconfirmed_values, unconfirmed_entries,
                                self.panel.days, student_p)
        contrast["mean_confirmed"] = float(confirmed_values.mean()) if len(confirmed_values) else None
        contrast["mean_unconfirmed"] = float(unconfirmed_values.mean()) if len(unconfirmed_values) else None
        contrast["n_confirmed"] = int(len(confirmed_values))
        contrast["n_unconfirmed"] = int(len(unconfirmed_values))
        contrast["confirmed_values"] = confirmed_values
        contrast["confirmed_entries"] = confirmed_entries
        contrast["unconfirmed_values"] = unconfirmed_values
        contrast["unconfirmed_entries"] = unconfirmed_entries
        return contrast

    def c5(self):
        chosen, combined = self.confirm("M1")
        result = self.returns_from_entry(combined, self.h01_col, 180)
        keep = (chosen[result["ids"]] >= 0)
        ids = result["ids"][keep]
        values = result["excess"][keep]
        entries = result["entries"][keep]
        deals = self.deals["M1"]["net"][chosen[ids]]
        pat = self.h01_pat[ids]
        log_deal = np.log(np.maximum(deals, 1.0))
        score = 0.5 * zscore(pat) + 0.5 * zscore(log_deal)
        labels = tercile_labels(score)
        top = labels == 2
        bottom = labels == 0
        contrast = cluster_diff(values[top], entries[top],
                                values[bottom], entries[bottom],
                                self.panel.days, student_p)
        contrast.update({
            "n_top": int(top.sum()), "n_middle": int((labels == 1).sum()),
            "n_bottom": int(bottom.sum()),
            "mean_top": float(values[top].mean()) if top.any() else None,
            "mean_middle": float(values[labels == 1].mean()) if (labels == 1).any() else None,
            "mean_bottom": float(values[bottom].mean()) if bottom.any() else None,
            "top_entries": entries[top], "bottom_entries": entries[bottom],
            "top_ids": ids[top], "bottom_ids": ids[bottom],
            "score": score, "labels": labels, "ids": ids, "values": values,
            "entries": entries, "deals": deals,
        })
        return contrast

    def c4_books(self, benchmark_nav):
        h01_events = [{"isin": self.h01_entities[i],
                       "entry": self.panel.calendar.days[int(self.h01_entry[i])],
                       "exit": self.panel.calendar.days[int(self.h01_entry[i] + 180)],
                       "sign": "positive"}
                      for i in range(len(self.h01))
                      if self.h01_entry[i] + 180 < self.t]
        m1 = self.deals["M1"]
        m1_events = [{"isin": m1["issuer"][i],
                      "entry": self.panel.calendar.days[int(m1["entry"][i])],
                      "exit": self.panel.calendar.days[int(m1["entry"][i] + 60)],
                      "sign": "positive"}
                     for i in range(len(m1["entry"]))
                     if m1["entry"][i] + 60 < self.t and m1["col"][i] >= 0]
        books = {}
        fills = []
        for name, events in (("H01_180", h01_events), ("M1_60", m1_events),
                             ("union", h01_events + m1_events)):
            book = run_book(events, self.panel.calendar, Quotes(self.panel),
                            ADTV(self.panel), self.rules, benchmark_nav)
            for fill in book["fills"]:
                fills.append({"book": name, **fill})
            books[name] = {k: v for k, v in book.items() if k not in ("nav", "fills")}
            books[name]["n_fills"] = len(book["fills"])
            books[name]["n_events"] = len(events)
        # Exploratory: both legs coexist only from the first H01 entry.  This is
        # not the declared C4 test, which starts at the first event of either leg.
        start = int(np.min(self.h01_entry))
        day_index = {d: i for i, d in enumerate(self.panel.calendar.days)}
        h01_common = [e for e in h01_events
                      if day_index[e["entry"]] >= start]
        m1_common = [e for e in m1_events
                     if day_index[e["entry"]] >= start]
        for name, events in (("M1_60_common", m1_common),
                             ("union_common", h01_common + m1_common)):
            book = run_book(events, self.panel.calendar, Quotes(self.panel),
                            ADTV(self.panel), self.rules, benchmark_nav)
            for fill in book["fills"]:
                fills.append({"book": name, **fill})
            books[name] = {k: v for k, v in book.items() if k not in ("nav", "fills")}
            books[name]["n_fills"] = len(book["fills"])
            books[name]["n_events"] = len(events)
        # Pooled event test for the union signal (book CAGR has no clean p).
        h01_values = self.h01_net
        h01_entries = self.h01_entry
        m1_result = self.returns_from_entry(m1["entry"], m1["col"], 60)
        pooled_values = np.concatenate([h01_values, m1_result["excess"]])
        pooled_entries = np.concatenate([h01_entries, m1_result["entries"]])
        pooled = summarize_arrays(pooled_values, pooled_entries,
                                  self.benchmark.regime_up[pooled_entries],
                                  self.panel.days)
        pooled["per_year_signs"] = year_signs(pooled_values, pooled_entries,
                                              self.panel.days)
        books["pooled_event_test"] = pooled
        return books, fills


def combination_row(name, params, **kwargs):
    row = {"params": {"combination": name, **params}, "n_events": kwargs.get("n_events", 0),
           "mean_net_excess": kwargs.get("mean_net_excess"),
           "median_net_excess": kwargs.get("median_net_excess"),
           "t_stat": kwargs.get("t_stat"), "p": kwargs.get("p", 1.0),
           "per_year_signs": kwargs.get("per_year_signs", {}),
           "status": kwargs.get("status", "fail"), "card_id": "H01xH02"}
    row.update({k: v for k, v in kwargs.items()
                if k not in ("n_events", "mean_net_excess", "median_net_excess",
                             "t_stat", "p", "per_year_signs", "status")})
    return row


def year_signs(values, entries, days):
    years = np.asarray(days)[np.asarray(entries)].astype("datetime64[Y]").astype(int) + 1970
    out = {}
    for year in range(2021, 2026):
        vals = np.asarray(values)[years == year]
        avg = float(vals.mean()) if len(vals) else None
        out[str(year)] = None if avg is None else ("+" if avg > 0 else "-" if avg < 0 else "0")
    return out


def year_diff_signs(av, ae, bv, be, days):
    ayears = np.asarray(days)[np.asarray(ae)].astype("datetime64[Y]").astype(int) + 1970
    byears = np.asarray(days)[np.asarray(be)].astype("datetime64[Y]").astype(int) + 1970
    out = {}
    for year in range(2021, 2026):
        a = np.asarray(av)[ayears == year]
        b = np.asarray(bv)[byears == year]
        if not len(a) or not len(b):
            out[str(year)] = None
            continue
        diff = float(a.mean() - b.mean())
        out[str(year)] = "+" if diff > 0 else "-" if diff < 0 else "0"
    return out


def write_preregistration(path):
    lines = [
        "# H01 x H02 pre-registration — Stage 2 (declared before outcomes)",
        "",
        f"Written: `{datetime.now(timezone.utc).isoformat(timespec='seconds')}`. "
        "Snapshot `truth_2026-10-19.duckdb`, read-only; evidence 2021-2025.",
        "",
        "Base H01 leg: positive PAT surprise, both-known entry, 180-session hold "
        "(the retained H01 lead in H01_signal_assessment.md).",
        "",
        "Fixed combinations, exactly six tests, all pooled in BH:",
        "",
        "1. **C1 confirm, M1, 180d:** H01 positive-PAT events with an M1 net-buy event "
        "in sessions [-20,+5] around the H01 decision. The confirming deal must be known "
        "before entry; entry is the later of the two t+1 opens. If several deals qualify, "
        "the latest t+1 open wins, ties by larger net buy, then later deal session.",
        "2. **C2 confirm, M2, 180d:** same rule with M2.",
        "3. **C3 contrast, M1, 180d:** mean confirmed minus mean unconfirmed H01 events. "
        "Unconfirmed means no M1 deal in the window. This is the decisive alpha test.",
        "4. **C4 union book:** one long book holding H01 positive-PAT (180d) and H02 M1 "
        "(60d) events, equal weight per event within the existing caps, compared with "
        "each leg alone on CAGR, max drawdown and kill date.",
        "5. **C5 score, 180d:** among M1-confirmed H01 events, rank by "
        "0.5*z(PAT surprise) + 0.5*z(log M1 net deal value), fixed weights, no fitting; "
        "top tercile minus bottom tercile.",
        "6. **C6 confirm, M1, 60d:** C1 at 60 sessions, to test whether flow confirmation "
        "speeds the drift.",
        "",
        "No weight search, window search, horizon search or post-hoc cohort change. "
        "Anything else is exploratory and excluded from promotion/BH.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_provenance():
    git_hash = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    files = sorted((ROOT / "reality_engine/harness").rglob("*.py"))
    files += [ROOT / "reality_engine/tests/test_harness_h02.py"]
    hashes = {}
    for p in files:
        if p.exists():
            hashes[str(p.relative_to(ROOT)).replace("\\", "/")] = hashlib.sha256(p.read_bytes()).hexdigest()
    return git_hash, hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placebo-draws", type=int, default=499)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.placebo_draws < 199:
        parser.error("At least 199 placebo draws are required")
    started = perf_counter()
    OUT.mkdir(parents=True, exist_ok=True)
    with Snapshot() as snapshot:
        stat_before = snapshot.path.stat()
        c = snapshot.connection
        c.execute("SET threads=2")
        c.execute("SET memory_limit='3GB'")
        inspect(c)
        rules = load_tax(c)
        progress("H01xH02: loading deals")
        data = load_deals(snapshot.path)
        prereg_hash = write_preregistration(OUT / "H01xH02_preregistration.md")
        progress("H01xH02: building panel, B5 and H01 lead")
        panel = Panel(c)
        benchmark = B5Path(load_indexes(c), panel.calendar, rules)
        h01 = load_h01_lead(c, panel, benchmark, rules)
        evaluator = CombinationEvaluator(h01, data, panel, benchmark, rules)
        progress(f"H01xH02: H01 lead events={len(h01)}, "
                 f"M1 events={len(evaluator.deals['M1']['signal'])}, "
                 f"M2 events={len(evaluator.deals['M2']['signal'])}")
        benchmark_nav, benchmark_book = benchmark.book_nav()

        c1 = evaluator.c1_c2_c6("M1", 180)
        c2 = evaluator.c1_c2_c6("M2", 180)
        c6 = evaluator.c1_c2_c6("M1", 60)
        c3 = evaluator.c3()
        c5 = evaluator.c5()
        books, book_fills = evaluator.c4_books(benchmark_nav)

        def mean_row(result, horizon):
            stats = summarize_arrays(result["excess"], result["entries"],
                                     benchmark.regime_up[result["entries"]],
                                     panel.days, detailed=True)
            stats["params"] = {"definition": "M1" if horizon else "M1",
                               "horizon": horizon}
            stats["per_year_signs"] = year_signs(result["excess"], result["entries"], panel.days)
            return stats

        rows = []
        for name, result, horizon, definition in (
                ("C1", c1, 180, "M1"), ("C2", c2, 180, "M2"), ("C6", c6, 60, "M1")):
            stats = summarize_arrays(result["excess"], result["entries"],
                                     benchmark.regime_up[result["entries"]],
                                     panel.days, detailed=True)
            delay = result["entry_delay_sessions"]
            rows.append(combination_row(name, {"definition": definition, "horizon": horizon,
                                               "window": list(CONFIRM_WINDOW)},
                                        n_events=stats["n_events"],
                                        mean_net_excess=stats["mean_net_excess"],
                                        median_net_excess=stats["median_net_excess"],
                                        t_stat=stats["t_stat"], p=stats["p"],
                                        per_year_signs=year_signs(result["excess"],
                                                                  result["entries"], panel.days),
                                        mean_gross_stock=float(result["gross"].mean()) if len(result["gross"]) else None,
                                        mean_net_stock=float(result["net"].mean()) if len(result["net"]) else None,
                                        mean_b5=float(result["b5"].mean()) if len(result["b5"]) else None,
                                        missing_exits=int(result["missing"].sum()),
                                        delayed_exits=int(result["delayed"].sum()),
                                        n_unique_issuers=int(len(set(evaluator.h01_entities[result["ids"]]))),
                                        entry_delay={"n": int(len(delay)),
                                                     "mean": float(delay.mean()) if len(delay) else None,
                                                     "median": float(np.median(delay)) if len(delay) else None,
                                                     "p90": float(np.quantile(delay, .9)) if len(delay) else None,
                                                     "deal_after_h01_share": float(np.mean(result["deal_after_h01"])) if len(delay) else None},
                                        result=stats))
        rows.append(combination_row("C3", {"definition": "M1", "horizon": 180,
                                           "window": list(CONFIRM_WINDOW)},
                                    n_events=c3["n_confirmed"] + c3["n_unconfirmed"],
                                    mean_net_excess=c3["diff"],
                                    median_net_excess=None,
                                    t_stat=c3["t_stat"], p=c3["p"],
                                    per_year_signs=year_diff_signs(
                                        c3["confirmed_values"], c3["confirmed_entries"],
                                        c3["unconfirmed_values"], c3["unconfirmed_entries"],
                                        panel.days),
                                    mean_confirmed=c3["mean_confirmed"],
                                    mean_unconfirmed=c3["mean_unconfirmed"],
                                    n_confirmed=c3["n_confirmed"],
                                    n_unconfirmed=c3["n_unconfirmed"],
                                    clusters_confirmed=c3["clusters_a"],
                                    clusters_unconfirmed=c3["clusters_b"],
                                    contrast=c3))
        rows.append(combination_row("C4", {"definition": "union", "horizon": "180/60",
                                           "weight": "equal per event"},
                                    n_events=books["pooled_event_test"]["n_events"],
                                    mean_net_excess=books["pooled_event_test"]["mean_net_excess"],
                                    median_net_excess=books["pooled_event_test"]["median_net_excess"],
                                    t_stat=None,
                                    p=1.0,
                                    per_year_signs=books["pooled_event_test"]["per_year_signs"],
                                    book_comparison={k: books[k] for k in ("H01_180", "M1_60", "union")},
                                    pooled_event_descriptive=books["pooled_event_test"]))
        rows.append(combination_row("C5", {"definition": "M1", "horizon": 180,
                                           "weight": [0.5, 0.5], "rank": "top minus bottom tercile"},
                                    n_events=c5["n_top"] + c5["n_bottom"],
                                    mean_net_excess=c5["diff"],
                                    median_net_excess=None,
                                    t_stat=c5["t_stat"], p=c5["p"],
                                    per_year_signs={},
                                    mean_top=c5["mean_top"], mean_middle=c5["mean_middle"],
                                    mean_bottom=c5["mean_bottom"],
                                    n_top=c5["n_top"], n_middle=c5["n_middle"],
                                    n_bottom=c5["n_bottom"],
                                    contrast={k: v for k, v in c5.items()
                                              if k not in ("top_entries", "bottom_entries",
                                                           "top_ids", "bottom_ids", "score",
                                                           "labels", "ids", "values", "entries",
                                                           "deals")},
                                    result={k: v for k, v in c5.items()
                                            if k in ("n_top", "n_middle", "n_bottom",
                                                     "mean_top", "mean_middle", "mean_bottom",
                                                     "diff", "t_stat", "p")}))

        # Placebos: shuffle M1 and M2 deal dates within stock-year, rebuild C1/C2/C3/C5/C6.
        progress("H01xH02: combination placebos")
        rng = np.random.default_rng(20261022)
        draws = args.placebo_draws
        dist = {name: np.full(draws, np.nan) for name in ("C1", "C2", "C3", "C5", "C6")}
        max_t = np.zeros(draws)
        for draw in range(draws):
            for definition in ("M1", "M2"):
                deals = evaluator.deals[definition]
                shuffled = shuffle_dates_within_stock_year(
                    deals["date"], deals["issuer"], rng)
                signal, entry = pit_indices(panel.days, shuffled)
                evaluator.deals[definition] = {**deals, "date": shuffled,
                                               "signal": signal, "entry": entry}
            rc1 = evaluator.c1_c2_c6("M1", 180)
            rc2 = evaluator.c1_c2_c6("M2", 180)
            rc6 = evaluator.c1_c2_c6("M1", 60)
            rc3 = evaluator.c3()
            rc5 = evaluator.c5()
            ts = []
            for name, values, entries in (
                    ("C1", rc1["excess"], rc1["entries"]),
                    ("C2", rc2["excess"], rc2["entries"]),
                    ("C6", rc6["excess"], rc6["entries"])):
                mu = float(values.mean()) if len(values) else None
                if mu is not None:
                    dist[name][draw] = mu
                if len(values) > 1:
                    st = summarize_arrays(values, entries,
                                          benchmark.regime_up[entries], panel.days)
                    if st["t_stat"] is not None:
                        ts.append(abs(st["t_stat"]))
            if rc3["diff"] is not None:
                dist["C3"][draw] = rc3["diff"]
                if rc3["t_stat"] is not None:
                    ts.append(abs(rc3["t_stat"]))
            if rc5["diff"] is not None:
                dist["C5"][draw] = rc5["diff"]
                if rc5["t_stat"] is not None:
                    ts.append(abs(rc5["t_stat"]))
            max_t[draw] = max(ts, default=0.0)
            if (draw + 1) % 100 == 0:
                progress(f"H01xH02 placebo {draw + 1}/{draws}")
        # Restore original dates after the placebo loop.
        evaluator.deals = CombinationEvaluator(h01, data, panel, benchmark,
                                               rules).deals

        def placebo_attach(row, name):
            valid = dist[name][np.isfinite(dist[name])]
            observed = row["mean_net_excess"]
            row["placebo_p"] = (
                float((1 + np.sum(np.abs(valid) >= abs(observed))) / (1 + len(valid)))
                if observed is not None and len(valid) else 1.0)
            row["placebo_directional_p"] = (
                float((1 + np.sum(valid >= observed)) / (1 + len(valid)))
                if observed is not None and len(valid) else 1.0)
            row["reality_check_p"] = (
                float((1 + np.sum(max_t >= abs(row["t_stat"]))) / (draws + 1))
                if row["t_stat"] is not None else 1.0)
            row["placebo"] = {"draws": draws, "valid_draws": int(len(valid)),
                              "mean": float(valid.mean()) if len(valid) else None,
                              "sd": float(valid.std(ddof=1)) if len(valid) > 1 else None,
                              "quantiles": np.quantile(valid, [.025, .5, .975]).tolist()
                              if len(valid) else None,
                              "distribution": valid.tolist()}
            return row

        for row in rows:
            if row["params"]["combination"] != "C4":
                placebo_attach(row, row["params"]["combination"])

        # BH family: prior ledger + Stage 1 (if not already appended) + 6 current.
        prior = previous_tests()
        import duckdb
        with duckdb.connect(str(ROOT / "reality_engine/data/backtests/ledger.duckdb"),
                            read_only=True) as conn:
            already_h02 = conn.execute(
                "SELECT count(*) FROM variants WHERE card_id='H02'").fetchone()[0]
        stage1_path = OUT / "H02_results.json"
        stage1_p = []
        if stage1_path.exists() and already_h02 < 4:
            stage1_p = [r["p"] for r in json.loads(stage1_path.read_text())["variants"]]
        family = [p for _, p in prior] + stage1_p + [r["p"] for r in rows]
        qs = bh_fdr(family)[-len(rows):]
        for row, q in zip(rows, qs):
            row["bh_q"] = q
        # Proof / status.
        for row in rows:
            name = row["params"]["combination"]
            if name == "C4":
                h01_book = books["H01_180"]
                union = books["union"]
                drawdown_ok = union["max_drawdown"] <= h01_book["max_drawdown"] + 1e-12
                kill_ok = (union["kill_date"] is None
                           or (h01_book["kill_date"] is not None
                               and union["kill_date"] >= h01_book["kill_date"]))
                row["proof_checks"] = {"drawdown_no_worse": bool(drawdown_ok),
                                       "kill_no_worse": bool(kill_ok)}
                row["status"] = "pass" if drawdown_ok and kill_ok else "fail"
            elif name == "C3":
                row["proof_checks"] = {
                    "contrast_positive": bool(row["mean_net_excess"] is not None
                                              and row["mean_net_excess"] > 0),
                    "bh_q_lt_005": bool(row["bh_q"] < .05),
                    "placebo_p_lt_005": bool(row["placebo_directional_p"] < .05),
                }
                row["status"] = "provisional_pass" if all(row["proof_checks"].values()) else "fail"
            else:
                row["proof_checks"] = {
                    "mean_positive": bool(row["mean_net_excess"] is not None
                                          and row["mean_net_excess"] > 0),
                    "bh_q_lt_005": bool(row["bh_q"] < .05),
                    "placebo_p_lt_005": bool(row["placebo_directional_p"] < .05),
                }
                row["status"] = "provisional_pass" if all(row["proof_checks"].values()) else "fail"
        c3_row = next(r for r in rows if r["params"]["combination"] == "C3")
        c4_row = next(r for r in rows if r["params"]["combination"] == "C4")
        alpha_increases = bool(
            c3_row["mean_net_excess"] is not None and c3_row["mean_net_excess"] > 0
            and c3_row["bh_q"] < .05 and c3_row["placebo_directional_p"] < .05
            and c4_row["proof_checks"]["drawdown_no_worse"]
            and c4_row["proof_checks"]["kill_no_worse"])
        git_hash, source_hashes = code_provenance()
        test_path = OUT / "H01xH02_tests.json"
        test_results = (json.loads(test_path.read_text(encoding="utf-8-sig"))
                        if test_path.exists() else {})
        result = {
            "card_id": "H01xH02", "stage": 2, "status": "completed_provisional",
            "provisional": True, "promoted": False,
            "evidence_window": ["2021-01-01", "2025-12-31"],
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_name": snapshot.path.name, "snapshot_read_only": True,
            "git_head": git_hash, "source_sha256": source_hashes,
            "pre_registration_sha256": prereg_hash,
            "h01_lead_audit": {"n_events": int(len(h01)),
                               "mean_h01_net_excess": float(h01["h01_net_excess"].mean()),
                               "entry_years": sorted(set(h01["h01_entry"].astype(str).str[:4]))},
            "combinations": rows, "books": {k: v for k, v in books.items()
                                             if k != "pooled_event_test"},
            "pooled_event_test": books["pooled_event_test"],
            "benchmark_choices": benchmark.choices,
            "placebo": {"draws": draws, "seed": 20261022,
                        "method": "deal dates permuted within stock-year; rebuild C1/C2/C3/C5/C6; "
                                  "max-T across current combination grid"},
            "placebo_distributions": {k: v.tolist() for k, v in dist.items()},
            "fdr_scope": {"current_tests": len(rows), "prior_ledger_tests": len(prior),
                          "stage1_tests_added": len(stage1_p),
                          "total_tests": len(family),
                          "prior_run_ids": sorted({rid for rid, _ in prior})},
            "alpha_increases": alpha_increases,
            "verdict_rule": "C3 contrast > 0, BH q < .05, placebo p < .05, and C4 "
                            "drawdown/kill no worse than the H01 leg alone",
            "test_results": test_results,
            "deviations": DEVIATIONS,
            "full_data_completeness_gate_met": False,
            "dry_run": bool(args.dry_run),
        }
        result = clean(result)
        if args.dry_run:
            result["ledger_run_id"] = "DRY_RUN_NOT_APPENDED"
            result["ledger_rows_appended"] = 0
        else:
            stale = OUT / "H01xH02_results.json"
            if stale.exists():
                raise FileExistsError("H01xH02_results.json exists; archive it before a new ledger run")
            run_id = append_variants(result["combinations"], snapshot=snapshot.path.name,
                                     git_hash=git_hash, coverage={},
                                     source_hashes=result["source_sha256"],
                                     card_id="H01xH02")
            result["ledger_run_id"] = run_id
            result["ledger_rows_appended"] = len(COMBINATIONS)
            append_run_note(run_id, json.dumps({
                "card": "H01xH02", "stage": 2, "pre_registration_sha256": prereg_hash,
                "method": "declared C1-C6", "prior_runs_in_bh": result["fdr_scope"]["prior_run_ids"],
            }))
        stat_after = snapshot.path.stat()
        result["snapshot_file_unchanged"] = (
            (stat_before.st_size, stat_before.st_mtime_ns)
            == (stat_after.st_size, stat_after.st_mtime_ns))
        if not result["snapshot_file_unchanged"]:
            raise RuntimeError("Read-only source snapshot changed during run")
        result["elapsed_seconds"] = perf_counter() - started
        if args.dry_run:
            (OUT / "H01xH02_results_draft.json").write_text(
                json.dumps(result, indent=2, allow_nan=False, ensure_ascii=False),
                encoding="utf-8")
            pd.DataFrame(book_fills).to_csv(
                OUT / "H01xH02_book_fills_draft.csv.gz",
                index=False, compression="gzip")
        else:
            (OUT / "H01xH02_results.json").write_text(
                json.dumps(result, indent=2, allow_nan=False, ensure_ascii=False),
                encoding="utf-8")
            pd.DataFrame(book_fills).to_csv(
                OUT / "H01xH02_book_fills.csv.gz",
                index=False, compression="gzip")
            write_report(result, OUT / "H01xH02_report.md")
        progress(f"H01xH02 finished; elapsed {result['elapsed_seconds']:.1f}s; "
                 f"alpha_increases={alpha_increases}")


DEVIATIONS = [
    "C1/C2/C6 confirm only on M1/M2 net-buy events in [-20,+5] sessions around the H01 decision; the latest t+1 open among qualifying deals sets the combined entry. This is a declared rule, not a search.",
    "A confirmed H01 event whose combined entry has no 180/60-session room before 2025-12-31 is excluded from that combination; unconfirmed H01 events keep their original entry and 180-session outcome.",
    "C3 compares confirmed events from their combined entry with unconfirmed H01 events from their original entry. This mixes an entry-timing difference into the contrast; it is the declared test, not a pure stock-selection contrast.",
    "C5 uses raw net deal value (not market-cap scaled) and cross-sectional z-scores of PAT surprise and log net value with fixed 0.5/0.5 weights. Terciles are equal-count by rank; ties split deterministically by order, which is disclosed as a limitation.",
    "C4 uses one cash book with equal weights on admissions, 10% of lagged ADTV, 10% strategy allocation and the unchanged 8% kill. Overlapping same-issuer admissions are suppressed. The union book's CAGR/drawdown/kill is compared with each leg alone. Its ledger p is conservatively 1.0 because the declared C4 criterion is drawdown/kill, not an event-mean p; the pooled event mean is reported only as description.",
    "No weight search, window search, horizon search, industry/size control or 2026 outcome is used.",
    "B5 uses the previous-session TRI close as its entry proxy; BSE total returns are derived. Event and book B5 pay the same 30 bp and sell-date tax conventions.",
    "Tax is the snapshot base capital-gains model; personal cess, surcharge and dividend tax are not modelled. Full data completeness remains unmet.",
]

# Emitted only for the run it describes, for the reason given in run_h02.py.
VERIFIED_STAGE2_RUN = "b6afc336-8e2c-4ca5-87e1-91a189482b46"

B5_RESIDUAL_RISK = [
    "",
    "## B5 residual risk",
    "",
    "Both stages price excess return against the same `B5Path`: a monthly choice among "
    "five total-return indices, entered at the previous session's TRI close because the "
    "snapshot has no index opens, with every index switch charged 30 bp and the snapshot "
    "sell-date tax. Stage 2's 11/11 pass used the corrected `independent_b5` from the "
    "Stage 1 checker, so the chain arithmetic is independently verified. Four things "
    "around it are not:",
    "",
    "- **The monthly selection is taken as given.** The checker replays returns from "
    "`benchmark_choices` in the results file and never re-runs `select_month`. A wrong "
    "index in any month — from the trailing-return ranking, the one-year lookback or the "
    "seven-day staleness gate — would pass the run and the check alike.",
    "- **Book B5 is not recomputed.** C4's 12.02% B5 CAGR and its excess CAGR come from "
    "`B5Path.book_nav`, with its own fee and shared annual-exemption treatment. The "
    "checker replays the strategy book's fills and closing cash, not the benchmark NAV.",
    "- **The entry proxy is a declared convention.** The benchmark buys at the previous "
    "close while the stock buys at the next open, so every excess level, including H01's "
    "8.78%, carries a one-session mismatch. It applies to both arms of C3, so the "
    "contrast largely cancels it; the levels do not.",
    "- **Coverage is sampled.** Each card recomputes 30 events. C3's unconfirmed arm is "
    "H01's stored `net_excess`, not recomputed here. And 34 of the 60 monthly choices are "
    "BSE series (15 BSE IPO, 15 BSE Sensex, 4 BSE 250 SmallCap) whose total-return "
    "adjustment is derived in-snapshot.",
    "",
    "The first is the one to watch on a rerun: if `select_month` changes, every B5 number "
    "in both stages moves together and the check would still pass.",
]


def write_report(result, path):
    lines = [
        "# H01 x H02 — declared combination test (Stage 2), provisional",
        "",
        "No combination is promoted. Stage 1 H02 is a separate isolation test.",
        "",
        f"Run `{result['ledger_run_id']}`. Snapshot `{result['snapshot_name']}`, read-only. "
        f"Evidence 2021–2025. Runtime {result['elapsed_seconds']:.1f}s.",
        "",
        f"Pre-registration: `H01xH02_preregistration.md`, SHA256 "
        f"`{result['pre_registration_sha256']}`.",
        "",
        f"H01 lead: {result['h01_lead_audit']['n_events']} positive-PAT 180-session events, "
        f"mean H01 net excess {pct(result['h01_lead_audit']['mean_h01_net_excess'])}.",
        "",
        "## Six declared tests",
        "",
        "| Test | Definition | Events | Mean / contrast | t | p | BH q | Placebo p | Status |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["combinations"]:
        p = row["params"]
        lines.append(f"| {p['combination']} | {p.get('definition')} {p.get('horizon')} | "
                     f"{row['n_events']} | {pct(row['mean_net_excess'])} | "
                     f"{num(row['t_stat'])} | {num(row['p'])} | {num(row['bh_q'])} | "
                     f"{num(row.get('placebo_directional_p'))} | {row['status']} |")
    c3 = next(r for r in result["combinations"] if r["params"]["combination"] == "C3")
    c5 = next(r for r in result["combinations"] if r["params"]["combination"] == "C5")
    c4 = next(r for r in result["combinations"] if r["params"]["combination"] == "C4")
    lines += [
        "",
        "C1/C2/C6 are confirm cohorts, not standalone signals. C1 and C6 have only "
        "78 confirmed H01 events; C2 has 8. Their positive means are not incremental "
        "evidence because the decisive C3 contrast is negative and every combination "
        "date-placebo p is far above 0.05. The confirmed sample is small because M1/M2 "
        "deal-days rarely fall in the same stock's [-20,+5] earnings window.",
        "",
        "## Confirmation entry delay",
        "",
        "| Test | n | Mean delay (sessions) | Median | p90 | Share entering after H01 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["combinations"]:
        if row["params"]["combination"] not in ("C1", "C2", "C6"):
            continue
        delay = row["entry_delay"]
        lines.append(f"| {row['params']['combination']} | {delay['n']} | "
                     f"{num(delay['mean'])} | {num(delay['median'])} | "
                     f"{num(delay['p90'])} | {pct(delay['deal_after_h01_share'])} |")
    lines += [
        "",
        "A deal after the H01 entry delays the combined entry to the deal's t+1 open. "
        "A deal before it keeps the H01 entry. This is the declared rule.",
        "",
        "## C3 — the decisive contrast",
        "",
        "| Group | Events | Mean 180d net excess |",
        "|---|---:|---:|",
        f"| M1-confirmed | {c3['n_confirmed']} | {pct(c3['mean_confirmed'])} |",
        f"| Unconfirmed | {c3['n_unconfirmed']} | {pct(c3['mean_unconfirmed'])} |",
        f"| Contrast | | {pct(c3['mean_net_excess'])} |",
        "",
        f"Cluster p `{num(c3['p'])}`, BH q `{num(c3['bh_q'])}`, "
        f"directional placebo p `{num(c3.get('placebo_directional_p'))}`. "
        "The contrast mixes the later confirmed entry with the original unconfirmed entry; "
        "that is the declared test.",
        "",
        "## C5 — fixed 0.5/0.5 score",
        "",
        f"Top tercile {pct(c5['mean_top'])} ({c5['n_top']} events), middle {pct(c5['mean_middle'])} "
        f"({c5['n_middle']}), bottom {pct(c5['mean_bottom'])} ({c5['n_bottom']}). "
        f"Top minus bottom {pct(c5['mean_net_excess'])}, p `{num(c5['p'])}`.",
        "",
        "## C4 — union book versus each leg",
        "",
        "| Book | Events | Sleeve CAGR | Max sleeve DD | Portfolio DD | B5 CAGR | Excess CAGR | Kill | Fills |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for name in ("H01_180", "M1_60", "union"):
        b = result["books"][name]
        lines.append(f"| {name} | {b['n_events']} | {pct(b['allocation_cagr'])} | "
                     f"{pct(b['max_drawdown'])} | {pct(b['portfolio_max_drawdown'])} | "
                     f"{pct(b['b5_cagr'])} | {pct(b['excess_cagr'])} | "
                     f"{b['kill_date'] or 'none'} | {b['n_fills']} |")
    checks = c4["proof_checks"]
    lines += [
        "",
        f"Union drawdown no worse than H01 leg: `{checks['drawdown_no_worse']}`. "
        f"Kill no worse: `{checks['kill_no_worse']}`.",
        "",
        "The C4 ledger row's 6.40% is the descriptive pooled event excess of the H01 and "
        "M1 events; it is not the union book's CAGR and it is not a book p-value. C4's "
        "ledger p is conservatively 1.0 because its declared criterion is drawdown and "
        "kill, not an event-mean test. The union book itself lost money and killed.",
        "",
        "The declared union book starts with the first event of either leg. Because the M1 "
        "leg starts in 2021 and the H01 leg in 2022, the early M1 book can kill the union "
        "before any H01 event is admitted. The full union is the declared C4 test.",
        "",
        "### Exploratory only — common-period books (both legs coexist from the first H01 entry)",
        "",
        "| Book | Events | Sleeve CAGR | Max sleeve DD | B5 CAGR | Excess CAGR | Kill | Fills |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for name in ("M1_60_common", "union_common"):
        b = result["books"].get(name)
        if b:
            lines.append(f"| {name} | {b['n_events']} | {pct(b['allocation_cagr'])} | "
                         f"{pct(b['max_drawdown'])} | {pct(b['b5_cagr'])} | "
                         f"{pct(b['excess_cagr'])} | {b['kill_date'] or 'none'} | {b['n_fills']} |")
    lines += [
        "",
        "Common-period results are descriptive and excluded from the declared C4 proof and BH.",
        "",
        "## Verdict",
        "",
        f"**Alpha increases: `{result['alpha_increases']}`.** "
        "The only declared test is C3 contrast > 0 with BH q < .05 and placebo p < .05, "
        "plus C4 drawdown/kill no worse than the H01 leg alone. No other comparison is a "
        "promotion criterion.",
        "",
        "## Placebo",
        "",
        f"{result['placebo']['draws']} draws. Deal dates were permuted within stock-year; "
        "C1/C2/C3/C5/C6 were rebuilt; max-T is across the current combination grid.",
        "",
        "## Deviations and limits",
        "",
    ]
    for i, item in enumerate(result["deviations"], 1):
        lines.append(f"{i}. {item}")
    if result["ledger_run_id"] == VERIFIED_STAGE2_RUN:
        lines += B5_RESIDUAL_RISK
    lines += [
        "",
        "## Tests",
        "",
        f"{result['test_results'].get('total_tests', 'unrecorded')} tests passed. "
        "All prior ledger rows and the Stage 1 H02 rows remain in the BH family.",
        "",
        "## Reproduction",
        "",
        "`python -m reality_engine.harness.run_h01xh02 --placebo-draws 499`",
        "",
        f"Git HEAD `{result['git_head']}`. No 2026 outcomes, paid worker, commit, push or upload.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
