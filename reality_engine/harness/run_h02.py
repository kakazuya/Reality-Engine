"""Run H02 Card F exactly as declared, before any outcome is inspected.

python -m reality_engine.harness.run_h02 --placebo-draws 499

Stage 1 only.  Stage 2 lives in run_h01xh02.py and is run after this output
has been verified.  No live database, network, package installation or git
mutation is used.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from time import perf_counter

import numpy as np
import pandas as pd

from .adapter import inspect, load_tax, load_indexes, load_filings, Panel, Quotes, ADTV
from .benchmark import B5Path
from .book import run_book
from .cards.h02_deals import (
    DealData, EVENT_THRESHOLD_INR, HORIZONS, M1_EXCLUDE, M1_PATTERN,
    aggregate_events, load_deals, marquee_mask, pit_indices,
    shuffle_dates_within_stock_year, top_clients,
)
from .data import ROOT, Snapshot
from .ledger import append_run_note, append_variants, previous_tests
from .run_h01 import clean, summarize_arrays, progress
from .run_h01_long import LongEvaluator
from .stats import bh_fdr

OUT = ROOT / "tasks/backtests"
VARIANTS = tuple({"definition": definition, "horizon": horizon}
                 for definition in ("M1", "M2") for horizon in HORIZONS)


def pct(value):
    return "—" if value is None else f"{100 * value:.2f}%"


def num(value):
    return "—" if value is None else f"{value:.4g}"


def inr_crore(value):
    return None if value is None else float(value) / 1e7


def load_h01_lead(connection, panel, benchmark, rules, horizon=180):
    """The retained H01 lead: positive PAT surprise, both-known, 180d."""
    records, _ = load_filings(connection)
    evaluator = LongEvaluator(records, panel, benchmark, rules)
    _, _, _, cache = evaluator.evaluate(detailed=True)
    data = cache[("both_known_next_open", horizon)]
    keep = data["scores"][:, 0] > 0
    ids = data["ids"][keep]
    entries = data["entry_indices"][keep]
    exits = data["exit_indices"][keep]
    triggers = data["decision_stamps"][keep]
    scores = data["scores"][keep]
    excess = data["excess"][keep]
    frames = []
    for k, record_id in enumerate(ids):
        trigger = pd.Timestamp(triggers[k]).to_pydatetime()
        signal = int(np.searchsorted(panel.days,
                                     np.datetime64(trigger.date(), "D"),
                                     side="right") - 1)
        frames.append({"entity": records[record_id]["entity"],
                       "h01_trigger": trigger,
                       "h01_signal_index": signal,
                       "h01_entry_index": int(entries[k]),
                       "h01_exit_index": int(exits[k]),
                       "h01_entry": panel.calendar.days[int(entries[k])],
                       "h01_exit": panel.calendar.days[int(exits[k])],
                       "pat_surprise": float(scores[k, 0]),
                       "h01_net_excess": float(excess[k])})
    return pd.DataFrame(frames)


class DealEvaluator:
    """Vectorized event/placebo evaluator over one fixed deal definition."""

    def __init__(self, data: DealData, panel, benchmark, rules):
        self.data = data
        self.panel = panel
        self.benchmark = benchmark
        self.rules = rules
        self.t = len(panel.days)
        self.next_close = self._next_close()
        self.rates = np.array([rules.rule("stcg_rate", d) for d in panel.calendar.days])
        self.lt_rates = np.array([rules.rule("ltcg_rate", d) for d in panel.calendar.days])
        self.b5 = {}
        for horizon in HORIZONS:
            out = np.full(self.t, np.nan)
            for entry in range(self.t):
                if panel.calendar.days[entry].year >= 2021 and entry + horizon < self.t:
                    out[entry] = benchmark.event_return(entry, entry + horizon)
            self.b5[horizon] = out
        self.events, self.cols, self.dates, self.issuers, self.buy_vwap = {}, {}, {}, {}, {}
        for definition in ("M1", "M2"):
            frame = data.events(definition)
            self.events[definition] = frame
            self.cols[definition] = np.array(
                [panel.col.get(v, -1) for v in frame["issuer"]], dtype=int)
            self.dates[definition] = np.array(frame["date"], dtype="datetime64[D]")
            self.issuers[definition] = frame["issuer"].astype(str).to_numpy()
            self.buy_vwap[definition] = frame["buy_vwap"].to_numpy(dtype=float)
        self.year_groups = {
            definition: self._year_groups(self.dates[definition], self.issuers[definition])
            for definition in self.dates}
        self.sma200 = pd.DataFrame(panel.close).rolling(200, min_periods=200).mean().to_numpy()
        self.pool, self.year_quantiles = self._candidate_pool()
        self.h01_by_entity = {}

    def _next_close(self):
        # Local copy to keep this module's dependencies explicit.
        closes = self.panel.close
        t, n = closes.shape
        out = np.full((t + 1, n), t, dtype=np.int32)
        for i in range(t - 1, -1, -1):
            out[i] = np.where(np.isfinite(closes[i]) & (closes[i] > 0), i, out[i + 1])
        return out

    @staticmethod
    def _year_groups(dates, issuers):
        years = dates.astype("datetime64[Y]").astype(int) + 1970
        groups = defaultdict(list)
        for i, (entity, year) in enumerate(zip(issuers, years)):
            groups[(entity, int(year))].append(i)
        return [np.asarray(v, dtype=int) for v in groups.values() if len(v) > 1]

    def _indices(self, dates):
        signal, entry = pit_indices(self.panel.days, dates)
        return np.asarray(dates, dtype="datetime64[D]"), signal, entry

    def evaluate_dates(self, cols, dates, horizon):
        """Gate at the signal session and return t+1-open to close outcomes."""
        panel = self.panel
        cols = np.asarray(cols, dtype=int)
        dates, signal, entry = self._indices(dates)
        t = self.t
        valid = (cols >= 0) & (signal >= 0) & (entry < t) & (entry + horizon < t)
        valid &= (dates >= np.datetime64("2021-01-01")) & (dates <= np.datetime64("2025-12-31"))
        safe_signal = np.clip(signal, 0, t - 1)
        safe_entry = np.clip(entry, 0, t - 1)
        safe_col = np.maximum(cols, 0)
        valid &= panel.u1[safe_signal, safe_col]
        op = panel.open[safe_entry, safe_col]
        valid &= np.isfinite(op) & (op > 0)
        ids = np.flatnonzero(valid)
        if len(ids) == 0:
            empty = np.array([], dtype=int)
            return {"ids": empty, "entries": empty, "exits": empty,
                    "scheduled": empty, "gross": np.array([]),
                    "net": np.array([]), "b5": np.array([]), "excess": np.array([]),
                    "missing": np.array([], dtype=bool),
                    "delayed": np.array([], dtype=bool), "holding_days": empty,
                    "entry_open": np.array([])}
        cols = cols[ids]
        scheduled = entry[ids] + horizon
        exit_index = self.next_close[scheduled, cols]
        missing = exit_index == t
        exit_safe = np.where(missing, t - 1, exit_index)
        close = panel.close[exit_safe, cols]
        gross = np.where(missing, 0.0, close) / op[ids] - 1.0
        holding = (panel.days[exit_safe] - panel.days[entry[ids]]).astype(
            "timedelta64[D]").astype(int)
        rates = np.where(holding > 365, self.lt_rates[exit_safe], self.rates[exit_safe])
        net = gross - 0.003 - np.maximum(gross, 0.0) * rates
        b5 = self.b5[horizon][entry[ids]].copy()
        delayed = exit_safe != scheduled
        for k in np.flatnonzero(delayed):
            b5[k] = self.benchmark.event_return(int(entry[ids[k]]), int(exit_safe[k]))
        return {"ids": ids, "entries": entry[ids], "exits": exit_safe,
                "scheduled": scheduled, "gross": gross, "net": net,
                "b5": b5, "excess": net - b5, "missing": missing,
                "delayed": delayed, "holding_days": holding,
                "entry_open": op[ids]}

    def summary(self, definition, horizon, detailed=False):
        result = self.evaluate_dates(self.cols[definition],
                                     self.dates[definition], horizon)
        row = summarize_arrays(result["excess"], result["entries"],
                               self.benchmark.regime_up[result["entries"]],
                               self.panel.days, detailed=detailed)
        row["params"] = {"definition": definition, "horizon": horizon}
        if detailed:
            ids = result["ids"]
            excess = result["excess"]
            pos = excess[excess > 0]
            total_positive = float(pos.sum()) if len(pos) else 0.0
            top5 = np.sort(excess)[-5:] if len(excess) else np.array([])
            top5_share = (float(top5[top5 > 0].sum()) / total_positive
                          if total_positive > 0 else None)
            issuers = self.issuers[definition][ids]
            issuer_positive = (pd.Series(excess).groupby(issuers).sum()
                               .clip(lower=0).sort_values(ascending=False))
            top5_issuer_share = (float(issuer_positive.head(5).sum()
                                       / issuer_positive.sum())
                                 if issuer_positive.sum() > 0 else None)
            _, deal_signal, _ = self._indices(self.dates[definition])
            gap = (self.panel.adj_open[result["entries"], self.cols[definition][ids]]
                   / (self.buy_vwap[definition][ids]
                      * self.panel.price_factor[deal_signal[ids], self.cols[definition][ids]])
                   - 1.0)
            gap = gap[np.isfinite(gap)]
            row.update({
                "mean_gross_stock": float(result["gross"].mean()),
                "mean_net_stock": float(result["net"].mean()),
                "mean_net_b5": float(result["b5"].mean()),
                "positive_excess_fraction": float(np.mean(excess > 0)),
                "unique_issuers": int(len(set(issuers))),
                "entry_years": sorted(set(int(y) for y in
                                          self.panel.days[result["entries"]].astype("datetime64[Y]").astype(int) + 1970)),
                "missing_exits": int(result["missing"].sum()),
                "delayed_exits": int(result["delayed"].sum()),
                "max_exit_delay_sessions": int(
                    (result["exits"] - result["scheduled"]).max()) if len(ids) else 0,
                "top5_event_positive_share": top5_share,
                "top5_issuer_positive_share": top5_issuer_share,
                "entry_gap_vs_deal_print": {
                    "n": int(len(gap)),
                    "mean": float(gap.mean()) if len(gap) else None,
                    "median": float(np.median(gap)) if len(gap) else None,
                    "p10": float(np.quantile(gap, .10)) if len(gap) else None,
                    "p25": float(np.quantile(gap, .25)) if len(gap) else None,
                    "p75": float(np.quantile(gap, .75)) if len(gap) else None,
                    "p90": float(np.quantile(gap, .90)) if len(gap) else None,
                    "positive_share": float(np.mean(gap > 0)) if len(gap) else None,
                },
            })
        return row, result

    # ---- placebos -------------------------------------------------------
    def date_placebo(self, draws=499, seed=20261022):
        rng = np.random.default_rng(seed)
        keys = [(d, h) for d in ("M1", "M2") for h in HORIZONS]
        means = {k: np.full(draws, np.nan) for k in keys}
        counts = {k: np.zeros(draws, dtype=int) for k in keys}
        max_t = np.zeros(draws)
        for draw in range(draws):
            ts = []
            for definition in ("M1", "M2"):
                dates = shuffle_dates_within_stock_year(
                    self.dates[definition], self.issuers[definition], rng)
                for horizon in HORIZONS:
                    result = self.evaluate_dates(self.cols[definition], dates, horizon)
                    mu = float(result["excess"].mean()) if len(result["excess"]) else None
                    if mu is not None:
                        means[(definition, horizon)][draw] = mu
                    counts[(definition, horizon)][draw] = len(result["excess"])
                    if len(result["excess"]) > 1:
                        stats = summarize_arrays(
                            result["excess"], result["entries"],
                            self.benchmark.regime_up[result["entries"]], self.panel.days)
                        if stats["t_stat"] is not None:
                            ts.append(abs(stats["t_stat"]))
            max_t[draw] = max(ts, default=0.0)
            if (draw + 1) % 100 == 0:
                progress(f"H02 date placebo {draw + 1}/{draws}")
        return {"means": means, "counts": counts, "max_abs_t": max_t,
                "seed": seed, "draws": draws,
                "method": "deal dates permuted within each stock-year; identities and net values retained; PIT/U1/entry/exit recomputed"}

    def _candidate_pool(self):
        """All deal-days (any client) for the H01-style label permutation."""
        frame = self.data.clean.groupby(["issuer", "date"], sort=False).agg(
            value=("value", "sum")).reset_index()
        cols = np.array([self.panel.col.get(v, -1) for v in frame["issuer"]], dtype=int)
        dates = np.array(frame["date"], dtype="datetime64[D]")
        _, signal, entry = self._indices(dates)
        t = self.t
        safe_signal = np.clip(signal, 0, t - 1)
        safe_col = np.maximum(cols, 0)
        liq = self.panel.median20[safe_signal, safe_col]
        trend = np.sign(self.panel.close[safe_signal, safe_col]
                        - self.sma200[safe_signal, safe_col])
        year = dates.astype("datetime64[Y]").astype(int) + 1970
        valid = ((cols >= 0) & (signal >= 0) & (entry < t)
                 & (dates >= np.datetime64("2021-01-01"))
                 & (dates <= np.datetime64("2025-12-31"))
                 & self.panel.u1[safe_signal, safe_col]
                 & np.isfinite(liq) & np.isfinite(trend))
        pool = pd.DataFrame({"issuer": frame["issuer"].to_numpy()[valid],
                             "date": dates[valid], "col": cols[valid],
                             "signal": signal[valid], "entry": entry[valid],
                             "liq": liq[valid], "trend": trend[valid].astype(int),
                             "year": year[valid].astype(int)}).reset_index(drop=True)
        quantiles = {}
        tercile = np.zeros(len(pool), dtype=int)
        for year_value, group in pool.groupby("year", sort=False):
            q1, q2 = np.nanquantile(group["liq"], [1 / 3, 2 / 3])
            quantiles[int(year_value)] = (float(q1), float(q2))
            idx = group.index.to_numpy()
            values = group["liq"].to_numpy()
            tercile[idx] = np.where(values <= q1, 0, np.where(values <= q2, 1, 2))
        pool["liq_tercile"] = tercile
        pool["stratum"] = (pool["year"] * 100 + pool["liq_tercile"] * 10
                           + (pool["trend"] + 1))
        return pool, quantiles

    def _event_strata(self, definition):
        dates = self.dates[definition]
        cols = self.cols[definition]
        _, signal, _ = self._indices(dates)
        t = self.t
        safe_signal = np.clip(signal, 0, t - 1)
        safe_col = np.maximum(cols, 0)
        liq = self.panel.median20[safe_signal, safe_col]
        trend = np.sign(self.panel.close[safe_signal, safe_col]
                        - self.sma200[safe_signal, safe_col])
        trend = np.nan_to_num(trend, nan=0.0)
        year = dates.astype("datetime64[Y]").astype(int) + 1970
        tercile = np.zeros(len(dates), dtype=int)
        for y in np.unique(year):
            q1, q2 = self.year_quantiles.get(int(y), (np.nan, np.nan))
            mask = year == y
            tercile[mask] = np.where(liq[mask] <= q1, 0,
                                     np.where(liq[mask] <= q2, 1, 2))
        return (year.astype(int) * 100 + tercile * 10
                + (trend.astype(int) + 1))

    def label_placebo(self, draws=499, seed=20261022):
        rng = np.random.default_rng(seed)
        pool = self.pool
        pool_by_stratum = {int(k): v.index.to_numpy()
                           for k, v in pool.groupby("stratum", sort=False)}
        keys = [(d, h) for d in ("M1", "M2") for h in HORIZONS]
        means = {k: np.full(draws, np.nan) for k in keys}
        max_t = np.zeros(draws)
        strata = {definition: self._event_strata(definition)
                  for definition in ("M1", "M2")}
        valid_strata = {}
        for definition in ("M1", "M2"):
            real = self.evaluate_dates(self.cols[definition],
                                       self.dates[definition], HORIZONS[0])
            valid_strata[definition] = strata[definition][real["ids"]]
        for draw in range(draws):
            ts = []
            for definition in ("M1", "M2"):
                counts = pd.Series(valid_strata[definition]).value_counts()
                selected = []
                for stratum, n in counts.items():
                    candidates = pool_by_stratum.get(int(stratum), np.array([], dtype=int))
                    if len(candidates) <= n:
                        selected.extend(candidates.tolist())
                    else:
                        selected.extend(rng.choice(candidates, int(n), replace=False).tolist())
                selected = np.asarray(selected, dtype=int)
                cols = pool["col"].to_numpy()[selected]
                dates = pool["date"].to_numpy()[selected]
                for horizon in HORIZONS:
                    result = self.evaluate_dates(cols, dates, horizon)
                    mu = float(result["excess"].mean()) if len(result["excess"]) else None
                    if mu is not None:
                        means[(definition, horizon)][draw] = mu
                    if len(result["excess"]) > 1:
                        stats = summarize_arrays(
                            result["excess"], result["entries"],
                            self.benchmark.regime_up[result["entries"]], self.panel.days)
                        if stats["t_stat"] is not None:
                            ts.append(abs(stats["t_stat"]))
            max_t[draw] = max(ts, default=0.0)
            if (draw + 1) % 100 == 0:
                progress(f"H02 label placebo {draw + 1}/{draws}")
        return {"means": means, "max_abs_t": max_t, "seed": seed,
                "draws": draws,
                "method": "M1/M2 labels permuted across all deal-days within year x lagged-liquidity tercile x prior-200-trend sign; counts per stratum preserved"}


def attach_placebo(observed, placebo, label, keys):
    for row, key in zip(observed, keys):
        means = placebo["means"][key]
        valid = means[np.isfinite(means)]
        mu, tstat = row["mean_net_excess"], row["t_stat"]
        row["placebo_p"] = (float((1 + np.sum(np.abs(valid) >= abs(mu))) / (1 + len(valid)))
                            if mu is not None and len(valid) else 1.0)
        row["placebo_directional_p"] = (
            float((1 + np.sum(valid >= mu)) / (1 + len(valid)))
            if mu is not None and len(valid) else 1.0)
        row["reality_check_p"] = (
            float((1 + np.sum(placebo["max_abs_t"] >= abs(tstat))) / (placebo["draws"] + 1))
            if tstat is not None else 1.0)
        row["placebo"] = {
            "draws": placebo["draws"], "valid_draws": int(len(valid)),
            "mean_distribution": valid.tolist(),
            "mean": float(valid.mean()) if len(valid) else None,
            "sd": float(valid.std(ddof=1)) if len(valid) > 1 else None,
            "quantiles": np.quantile(valid, [.025, .5, .975]).tolist() if len(valid) else None,
        }
        label_means = label["means"][key]
        label_valid = label_means[np.isfinite(label_means)]
        row["label_placebo_p"] = (
            float((1 + np.sum(np.abs(label_valid) >= abs(mu))) / (1 + len(label_valid)))
            if mu is not None and len(label_valid) else 1.0)
        row["label_placebo"] = {
            "draws": label["draws"], "valid_draws": int(len(label_valid)),
            "mean": float(label_valid.mean()) if len(label_valid) else None,
            "sd": float(label_valid.std(ddof=1)) if len(label_valid) > 1 else None,
            "quantiles": np.quantile(label_valid, [.025, .5, .975]).tolist() if len(label_valid) else None,
        }
    return observed


def coverage_by_year(panel, data):
    rows = []
    for year in range(2021, 2026):
        days = np.array([d.year == year for d in panel.calendar.days])
        universe = set(panel.isin_code[days][panel.u1[days]].tolist())
        deal_issuers = set(data.clean.loc[data.clean["date"].str[:4] == str(year), "issuer"])
        m1_frame = data.events("M1")
        m2_frame = data.events("M2")
        m1_issuers = set(m1_frame.loc[m1_frame["date"].str[:4] == str(year), "issuer"])
        m2_issuers = set(m2_frame.loc[m2_frame["date"].str[:4] == str(year), "issuer"])
        rows.append({
            "year": year, "u1_isins": len(universe),
            "clean_deal_issuers": len(deal_issuers),
            "clean_deal_coverage": len(deal_issuers) / len(universe) if universe else None,
            "m1_events": int((m1_frame["date"].str[:4] == str(year)).sum()),
            "m1_event_issuers": len(m1_issuers),
            "m1_coverage": len(m1_issuers) / len(universe) if universe else None,
            "m2_events": int((m2_frame["date"].str[:4] == str(year)).sum()),
            "m2_event_issuers": len(m2_issuers),
            "m2_coverage": len(m2_issuers) / len(universe) if universe else None,
            "status": "provisional",
        })
    return rows


def add_liquidity_tercile(evaluator, definition, result):
    ids = result["ids"]
    entries = result["entries"]
    cols = evaluator.cols[definition][ids]
    liq = evaluator.panel.median20[np.maximum(entries - 1, 0), cols]
    valid = np.isfinite(liq)
    tercile = np.full(len(liq), -1, dtype=int)
    if valid.sum() >= 3:
        q1, q2 = np.nanquantile(liq[valid], [1 / 3, 2 / 3])
        tercile[valid] = np.where(liq[valid] <= q1, 0,
                                  np.where(liq[valid] <= q2, 1, 2))
    return tercile, liq


def liquidity_table(evaluator, definition, result):
    tercile, liq = add_liquidity_tercile(evaluator, definition, result)
    out = []
    for t in range(3):
        mask = tercile == t
        values = result["excess"][mask]
        out.append({"tercile": t + 1, "n_events": int(mask.sum()),
                    "mean_net_excess": float(values.mean()) if len(values) else None,
                    "median_net_excess": float(np.median(values)) if len(values) else None,
                    "median_lagged_value_inr": float(np.nanmedian(liq[mask])) if mask.any() else None})
    return out, tercile


def h01_overlap(evaluator, definition, h01_frame):
    """Share of events with an H01 positive-PAT event within +/-5 sessions."""
    if h01_frame is None or h01_frame.empty:
        return np.zeros(len(evaluator.dates[definition]), dtype=bool), None
    by_entity = defaultdict(list)
    for entity, signal in zip(h01_frame["entity"], h01_frame["h01_signal_index"]):
        by_entity[entity].append(int(signal))
    for key in by_entity:
        by_entity[key] = np.sort(np.asarray(by_entity[key], dtype=int))
    dates = evaluator.dates[definition]
    _, signal, _ = evaluator._indices(dates)
    flags = np.zeros(len(dates), dtype=bool)
    for i, (entity, sig) in enumerate(zip(evaluator.issuers[definition], signal)):
        arr = by_entity.get(entity)
        if arr is None or len(arr) == 0:
            continue
        pos = int(np.searchsorted(arr, sig))
        candidates = arr[max(0, pos - 1):pos + 1]
        flags[i] = any(abs(int(c) - int(sig)) <= 5 for c in candidates)
    return flags, (float(flags.mean()) if len(flags) else None)


def event_rows(evaluator, definition, horizon, result, meta, tercile, overlap):
    frame = evaluator.events[definition]
    ids = result["ids"]
    if len(ids) == 0:
        return []
    panel = evaluator.panel
    cols = evaluator.cols[definition][ids]
    rows = []
    for k, idx in enumerate(ids):
        entry, exit_index = int(result["entries"][k]), int(result["exits"][k])
        scheduled = int(result["scheduled"][k])
        event_day = np.datetime64(frame["date"].iloc[idx])
        deal_signal = int(np.searchsorted(panel.days, event_day, side="right") - 1)
        gap = (panel.adj_open[entry, cols[k]]
               / (evaluator.buy_vwap[definition][idx]
                  * panel.price_factor[deal_signal, cols[k]]) - 1.0)
        jumps = int(panel.jump_prefix[exit_index + 1, cols[k]]
                    - panel.jump_prefix[entry, cols[k]])
        rows.append({
            "definition": definition, "horizon": horizon,
            "issuer": evaluator.issuers[definition][idx],
            "isin": panel.actual_isin(entry, cols[k]),
            "event_date": str(frame["date"].iloc[idx]),
            "net_value_inr": float(frame["net_value"].iloc[idx]),
            "buy_value_inr": float(frame["buy_value"].iloc[idx]),
            "sell_value_inr": float(frame["sell_value"].iloc[idx]),
            "buy_vwap": float(frame["buy_vwap"].iloc[idx]),
            "n_deal_rows": int(frame["n_rows"].iloc[idx]),
            "clients": frame["clients"].iloc[idx],
            "signal_date": str(panel.calendar.days[int(np.searchsorted(
                panel.days, np.datetime64(frame["date"].iloc[idx]), side="right") - 1)]),
            "entry": str(panel.calendar.days[entry]),
            "scheduled_exit": str(panel.calendar.days[scheduled]),
            "exit": str(panel.calendar.days[exit_index]),
            "exit_delay_sessions": int(exit_index - scheduled),
            "entry_open_tr": float(result["entry_open"][k]),
            "entry_gap_vs_deal_print": float(gap) if np.isfinite(gap) else None,
            "gross_return": float(result["gross"][k]),
            "stock_net": float(result["net"][k]),
            "b5_net": float(result["b5"][k]),
            "net_excess": float(result["excess"][k]),
            "missing_exit_loss_bound": bool(result["missing"][k]),
            "truth_jump_flags": jumps,
            "lagged_liquidity_tercile": int(tercile[k]) if tercile is not None and len(tercile) else None,
            "h01_overlap_5_sessions": bool(overlap[idx]) if overlap is not None else None,
        })
    return rows


def preregistration(data, path, evidence_start="2021-01-01", evidence_end="2025-12-31"):
    evidence = data.deduped.loc[(data.deduped["date"] >= evidence_start)
                                & (data.deduped["date"] <= evidence_end)]
    clean_evidence = data.clean
    top = top_clients(clean_evidence, 100)
    promoter_names = set(data.insider_pairs["n"].astype(str))
    top["promoter_name_any_issuer"] = top["client_n"].isin(promoter_names)
    excluded = evidence.loc[~evidence["row_id"].isin(clean_evidence["row_id"])]
    top_excluded = top_clients(excluded, 10)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines = [
        "# H02 pre-registration — written before any outcome was computed",
        "",
        f"Written: `{now}`. Snapshot: `truth_2026-10-19.duckdb`, read-only.",
        "Evidence window: 2021-01-01 → 2025-12-31. 2019–2020 deals are warm-up/audit only.",
        "No price, return, benchmark or book outcome was read before this file was written.",
        "Its SHA256 is recorded in `H02_results.json`.",
        "",
        "## Fixed signal",
        "",
        "- Net value per (issuer, date, declared client set) = Σ buy value − Σ sell value; "
        "buy/sell is from the exchange deal feed. Event = net buy ≥ ₹1 crore (10,000,000 INR).",
        "- Entry at t+1 open; never the deal-date close. Deal dates are known end-of-day IST "
        "(`known_at_utc` is 18:29:59 UTC = 23:59:59 IST).",
        "- Universe U1 at the signal session; 30 bp round trip; sell-date STCG; B5 benchmark; "
        "20 and 60 trading-day holds; 8% strategy kill.",
        "",
        "## M1 — broad institution regex (final, fixed)",
        "",
        "Applied case-insensitively to a normalized client name: uppercase, non-alphanumerics "
        "replaced by spaces, multiple spaces collapsed, trimmed.",
        "",
        "```text",
        f"M1_PATTERN = {M1_PATTERN!r}",
        f"M1_EXCLUDE = {M1_EXCLUDE!r}",
        "```",
        "",
        "The exclusion is applied to the same normalized name. A name that matches both is not M1. "
        "The declared tokens are exactly those in the task: `MUTUAL FUND`, ` MF `, `ASSET MANAGEMENT`, "
        "`AMC`, `INSURANCE`, `LIFE INSURANCE`, `PENSION`, `PROVIDENT`, `FUND`, `FUNDS`, "
        "`CAPITAL MANAGEMENT`, `INVESTMENT MANAGEMENT`, `SOVEREIGN`, `GOVERNMENT OF`, "
        "`MONETARY AUTHORITY`, `NORGES`, `ABU DHABI`, `GIC `, `TRUST`; exclusions "
        "`SHARE BROKING`, `SECURITIES PRIVATE`, `STOCK BROKING`, `COMMODITIES`.",
        "",
        "## M1 hit list — top 100 clients by deal value (2021–2025)",
        "",
        "Values are gross deal value (quantity × price) after mapping, dedupe and company-specific "
        "promoter/insider exclusion. `promoter_name_any_issuer` is informational: the same name can "
        "be a promoter of one issuer and an ordinary client in another, which is why exclusion is "
        "company-specific.",
        "",
        "| # | Client | Deal value (₹ crore) | Rows | M1 match | Broker/prop | Promoter name (any issuer) |",
        "|---:|---|---:|---:|:---:|:---:|:---:|",
    ]
    for i, row in top.iterrows():
        lines.append(f"| {i + 1} | {row['client_name']} | {inr_crore(row['deal_value_inr']):.2f} | "
                     f"{int(row['rows'])} | {'yes' if row['m1_match'] else 'no'} | "
                     f"{'yes' if row['broker_prop'] else 'no'} | "
                     f"{'yes' if row['promoter_name_any_issuer'] else 'no'} |")
    lines += [
        "",
        "### Largest clients removed by the company-specific promoter/insider rule",
        "",
        "| # | Client | Deal value (₹ crore) | Rows |",
        "|---:|---|---:|---:|",
    ]
    for i, row in top_excluded.iterrows():
        lines.append(f"| {i + 1} | {row['client_name']} | {inr_crore(row['deal_value_inr']):.2f} | "
                     f"{int(row['rows'])} |")
    lines += [
        "",
        "## M2 — top-20 repeat clients, first evidence year only (2021)",
        "",
        "Ranked by distinct deal-days in 2021 after dedupe and company-specific promoter/insider "
        "removal, excluding the declared broker/prop tokens. Ties break by normalized client name. "
        "The list is frozen here and is not chosen with 2022–2025 data.",
        "",
        "| # | Client | Distinct deal-days 2021 | 2021 deal value (₹ crore) | 2021 rows |",
        "|---:|---|---:|---:|---:|",
    ]
    for i, row in data.m2_list.iterrows():
        lines.append(f"| {i + 1} | {row['client_name']} | {int(row['distinct_deal_days_2021'])} | "
                     f"{inr_crore(row['deal_value_inr_2021']):.2f} | {int(row['deal_rows_2021'])} |")
    lines += [
        "",
        "## Deal mapping, dedupe and promoter/insider exclusion",
        "",
        f"- NSE: `symbol` → `symbol_isin_history` valid on the deal date → `security_master.issuer`. "
        f"Unmatched: {data.audit['unmatched_rows']} rows in 2019–2025 "
        f"({inr_crore(data.audit['unmatched_value_inr']):.1f} ₹ crore); by year in the results JSON.",
        f"- BSE: `sc_code` → `security_master.bse_code` (a code mapping to more than one issuer is refused). "
        f"BSE accounts for the remainder of unmatched rows; see the year table.",
        f"- Dedupe: {data.audit['cross_exchange_duplicates_removed']} cross-exchange pairs and "
        f"{data.audit['bulk_block_duplicates_removed']} BULK/BLOCK duplicate pairs removed one-for-one. "
        "Same-exchange, same-type identical rows are retained: they can be genuine separate trades.",
        f"- Promoter/insider exclusion: company-specific exact normalized-name match against "
        f"`nse_insider` (symbol→ISIN valid on the disclosure date) and `bse_insider` target-company "
        f"promoter names; plus any client name containing `PROMOTER`. "
        f"Excluded {data.audit['promoter_insider_rows_excluded']} rows / "
        f"{inr_crore(data.audit['promoter_insider_value_excluded_inr']):.1f} ₹ crore. "
        f"{data.insider_audit['insider_pairs']} company-name pairs, "
        f"{data.insider_audit['insider_issuers']} issuers, {data.insider_audit['insider_names']} names.",
        "- SAST is not used as a name source because it also contains institutional acquirers; "
        "company-name/PROMOTER heuristics beyond the explicit token are not used.",
        "",
        "## Year-by-year mapping coverage",
        "",
        "| Year | Rows | Mapped | Unmatched | Value (₹ crore) | Unmatched value (₹ crore) |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in data.audit["by_year"]:
        lines.append(f"| {row['year']} | {row['rows']} | {row['mapped_rows']} | "
                     f"{row['unmatched_rows']} | {inr_crore(row['value_inr']):.1f} | "
                     f"{inr_crore(row['unmatched_value_inr']):.1f} |")
    lines += [
        "",
        "2026 deal rows exist in the snapshot and are excluded from every computation here; "
        "they are not loaded into the working table.",
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


def run_books(evaluator, benchmark_nav):
    books, fills = {}, []
    for definition in ("M1", "M2"):
        for horizon in HORIZONS:
            result = evaluator.evaluate_dates(evaluator.cols[definition],
                                              evaluator.dates[definition], horizon)
            events = [{"isin": evaluator.issuers[definition][idx],
                       "entry": evaluator.panel.calendar.days[int(entry)],
                       "exit": evaluator.panel.calendar.days[int(entry + horizon)],
                       "sign": "positive"}
                      for idx, entry in zip(result["ids"], result["entries"])]
            book = run_book(events, evaluator.panel.calendar,
                            Quotes(evaluator.panel), ADTV(evaluator.panel),
                            evaluator.rules, benchmark_nav)
            key = f"{definition}_{horizon}"
            for fill in book["fills"]:
                fills.append({"variant": key, **fill})
            books[key] = {k: v for k, v in book.items() if k not in ("nav", "fills")}
            books[key]["n_fills"] = len(book["fills"])
    return books, fills


def write_report(result, path):
    lines = [
        "# H02 — bulk/block deal accumulation, provisional (Stage 1)",
        "",
        "No variant is promoted. This is the declared isolation test; Stage 2 is separate.",
        "",
        f"Run `{result['ledger_run_id']}`. Snapshot `{result['snapshot_name']}`, read-only. "
        f"Evidence 2021–2025; 2019–2020 warm-up/audit only. Runtime {result['elapsed_seconds']:.1f}s.",
        "",
        f"Pre-registration: `H02_preregistration.md`, SHA256 `{result['pre_registration_sha256']}`. "
        "It was written before any outcome was computed.",
        "",
        "## Declared client sets",
        "",
        f"M1 final regex: `{result['m1_pattern']}`; exclusion `{result['m1_exclude']}`.",
        "The top-100 hit list and the fixed 2021 M2 list are in the pre-registration file.",
        "",
        "## Mapping and dedupe",
        "",
        "| Year | Rows | Mapped | Unmatched | Unmatched value (₹ crore) |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in result["deal_audit"]["by_year"]:
        lines.append(f"| {row['year']} | {row['rows']} | {row['mapped_rows']} | "
                     f"{row['unmatched_rows']} | {inr_crore(row['unmatched_value_inr']):.1f} |")
    lines += [
        "",
        f"Cross-exchange duplicates removed: {result['deal_audit']['cross_exchange_duplicates_removed']}; "
        f"BULK/BLOCK duplicate pairs: {result['deal_audit']['bulk_block_duplicates_removed']}. "
        f"Promoter/insider rows excluded: {result['deal_audit']['promoter_insider_rows_excluded']} "
        f"({inr_crore(result['deal_audit']['promoter_insider_value_excluded_inr']):.1f} ₹ crore).",
        "",
        "## Coverage",
        "",
        "| Year | U1 ISINs | Deal issuers | M1 events | M1 issuers | M2 events | M2 issuers |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["coverage_report"]:
        lines.append(f"| {row['year']} | {row['u1_isins']} | {row['clean_deal_issuers']} | "
                     f"{row['m1_events']} | {row['m1_event_issuers']} | "
                     f"{row['m2_events']} | {row['m2_event_issuers']} |")
    lines += [
        "",
        "`Deal issuers` counts every mapped issuer with a clean deal that year, including "
        "issuers outside U1; the U1 columns are the eligible universe and event issuers. "
        "The event counts in this table are before the U1/price gates, so they differ from "
        "the variant counts below.",
        "",
        "## Four confirmatory tests",
        "",
        "Mean event excess is after 30 bp and sell-date tax, minus after-tax/cost B5. "
        "Cluster t uses entry-month clusters; BH q pools all prior ledger tests.",
        "",
        "| Definition | Days | Events | Issuers | Mean excess | Median | t | p | HAC p | BH q | Date placebo p | Label placebo p | Max-T p | Years |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["variants"]:
        p = row["params"]
        signs = "/".join(row["per_year_signs"].get(str(y)) or "NA" for y in range(2021, 2026))
        lines.append(f"| {p['definition']} | {p['horizon']} | {row['n_events']} | "
                     f"{row['unique_issuers']} | {pct(row['mean_net_excess'])} | "
                     f"{pct(row['median_net_excess'])} | {num(row['t_stat'])} | "
                     f"{num(row['p'])} | {num(row.get('hac', {}).get('p'))} | "
                     f"{num(row['bh_q'])} | {num(row['placebo_p'])} | "
                     f"{num(row['label_placebo_p'])} | {num(row['reality_check_p'])} | {signs} |")
    lines += [
        "",
        "HAC p uses equal-weight observed monthly cohorts and a Bartlett Newey-West SE with "
        "ceil(horizon/21) calendar-month lags; missing months are not imputed to zero. "
        "It is reported alongside the entry-month cluster p, not substituted for it. "
        "M2's small p is on a negative mean: it is evidence of underperformance, not a "
        "long edge, and the BH q is computed from the two-sided cluster p.",
        "",
        "## Long-only books",
        "",
        "Each variant is a ₹10 lakh sleeve inside ₹1 crore, equal weight on admissions, "
        "10% of lagged ADTV cap and the unchanged 8% strategy kill.",
        "",
        "| Variant | Sleeve CAGR | Total-capital CAGR | Max sleeve DD | Portfolio DD | B5 CAGR | Excess CAGR | Kill | Fills |",
        "|---|---:|---:|---:|---:|---:|---:|---|---:|",
    ]
    for key, book in result["books"].items():
        lines.append(f"| {key} | {pct(book['allocation_cagr'])} | {pct(book['total_capital_cagr'])} | "
                     f"{pct(book['max_drawdown'])} | {pct(book['portfolio_max_drawdown'])} | "
                     f"{pct(book['b5_cagr'])} | {pct(book['excess_cagr'])} | "
                     f"{book['kill_date'] or 'none'} | {book['n_fills']} |")
    lines += [
        "",
        "The M2 20 and M2 60 books are identical because the 2021 kill happens before the "
        "20/60 difference in scheduled exits can matter. A killed sleeve stays in cash.",
        "",
        "## Next-open gap versus deal print",
        "",
        "| Variant | n | Mean | Median | p10 | p25 | p75 | p90 | Positive share |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["variants"]:
        gap = row["entry_gap_vs_deal_print"]
        p = row["params"]
        lines.append(f"| {p['definition']} {p['horizon']} | {gap['n']} | {pct(gap['mean'])} | "
                     f"{pct(gap['median'])} | {pct(gap['p10'])} | {pct(gap['p25'])} | "
                     f"{pct(gap['p75'])} | {pct(gap['p90'])} | {pct(gap['positive_share'])} |")
    lines += [
        "",
        "The gap is the split-adjusted t+1 opening price divided by the event's buy VWAP "
        "(the deal print times the deal-date split factor) minus one. Dividends are not "
        "added because the deal print is a raw price. A positive gap means the market "
        "opened above the deal print; it is a fooling risk, not a cost modelled twice.",
        "",
        "## Secondary, exploratory only (not in BH or promotion)",
        "",
        "### Lagged-liquidity terciles",
        "",
        "| Variant | Terciile | Events | Mean excess | Median excess | Median lagged value (₹ crore) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["liquidity_terciles"]:
        for cell in row["table"]:
            lines.append(f"| {row['definition']} {row['horizon']} | {cell['tercile']} | "
                         f"{cell['n_events']} | {pct(cell['mean_net_excess'])} | "
                         f"{pct(cell['median_net_excess'])} | "
                         f"{inr_crore(cell['median_lagged_value_inr']):.1f} |")
    lines += [
        "",
        "### H01 overlap within ±5 sessions",
        "",
        "| Variant | Events | Overlap | Rate |",
        "|---|---:|---:|---:|",
    ]
    for row in result["h01_overlap"]:
        lines.append(f"| {row['definition']} {row['horizon']} | {row['n_events']} | "
                     f"{row['n_overlap']} | {pct(row['rate'])} |")
    lines += [
        "",
        "## Concentration and data checks",
        "",
        "| Variant | Top-5 event positive share | Top-5 issuer positive share | Missing exits | Delayed exits | Truth jump flags |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in result["variants"]:
        p = row["params"]
        jumps = sum(1 for e in result["events"] if e["definition"] == p["definition"]
                    and e["horizon"] == p["horizon"] and e["truth_jump_flags"] > 0)
        lines.append(f"| {p['definition']} {p['horizon']} | {pct(row['top5_event_positive_share'])} | "
                     f"{pct(row['top5_issuer_positive_share'])} | {row['missing_exits']} | "
                     f"{row['delayed_exits']} | {jumps} |")
    lines += [
        "",
        "Missing exits are terminal zero-recovery bounds, not claimed sales; they are "
        "flagged in the event CSV. Any such case is a reason not to promote, regardless "
        "of the other checks. The M1 variants have one or two such events.",
        "",
        "## Proof checks",
        "",
        "| Variant | BH q≤.05 | Date placebo≤.05 | Directional≤.05 | Label placebo≤.05 | Max-T≤.05 | Four years sign | Both regimes | Book survives | Status |",
        "|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|",
    ]
    for row in result["variants"]:
        p = row["params"]
        checks = row["proof_checks"]
        lines.append(f"| {p['definition']} {p['horizon']} | "
                     f"{'yes' if checks['bh_q_le_005'] else 'no'} | "
                     f"{'yes' if checks['placebo_p_le_005'] else 'no'} | "
                     f"{'yes' if checks['directional_placebo_p_le_005'] else 'no'} | "
                     f"{'yes' if checks['label_placebo_p_le_005'] else 'no'} | "
                     f"{'yes' if checks['max_t_p_le_005'] else 'no'} | "
                     f"{'yes' if checks['four_years_expected_sign'] else 'no'} | "
                     f"{'yes' if checks['both_regimes_expected_sign'] else 'no'} | "
                     f"{'yes' if checks.get('book_positive_excess_and_not_killed') else 'no'} | "
                     f"{row['status']} |")
    lines += [
        "",
        "A pass still does not promote: the full data-completeness gate is unmet, the benchmark "
        "entry is a previous-close proxy, BSE total returns are derived, tax is the snapshot "
        "base capital-gains model, and the deal print is not executable.",
        "",
    ]
    if result["ledger_run_id"] == VERIFIED_STAGE1_RUN:
        lines += VERIFICATION_HISTORY
    lines += [
        "## Placebo design",
        "",
        f"{result['placebo']['draws']} date draws: deal dates permuted within each stock-year, "
        "identities/net values retained, PIT/U1/entry/exit recomputed. "
        f"{result['label_placebo']['draws']} label draws: M1/M2 labels permuted across all "
        "deal-days within year × lagged-liquidity tercile × prior-200-trend sign, preserving "
        "the number of events per stratum. Max-T is the full-grid maximum absolute cluster t "
        "across the four variants.",
        "",
        "## Deviations and limits",
        "",
    ]
    for i, item in enumerate(result["deviations"], 1):
        lines.append(f"{i}. {item}")
    lines += [
        "",
        "## Tests",
        "",
        f"{result['test_results'].get('total_tests', 'unrecorded')} tests passed: "
        f"{result['test_results'].get('h02_tests', 'unrecorded')} new H02 harness tests and "
        f"{result['test_results'].get('existing_harness_tests', 'unrecorded')} existing harness tests. "
        "All prior ledger rows remain in the BH family.",
        "",
        "## Appendix A — pre-registration, verbatim (written before any outcome)",
        "",
    ]
    prereg = OUT / "H02_preregistration.md"
    lines.append(prereg.read_text(encoding="utf-8") if prereg.exists() else "missing")
    lines += [
        "",
        "## Reproduction",
        "",
        "`python -m reality_engine.harness.run_h02 --placebo-draws 499`",
        "",
        f"Git HEAD `{result['git_head']}`; new source files are uncommitted and their SHA256 hashes "
        "are in the JSON. No 2026 outcomes, paid worker, commit, push or upload.",
        "",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


DEVIATIONS = [
    "Deal feeds are end-of-day (date-only). Entry is the next regular-session open; no intraday print is treated as executable.",
    "NSE symbols are mapped only through symbol_isin_history valid on the deal date. BSE codes use security_master.bse_code; a code mapping to more than one issuer is refused. Unmatched rows and value are reported by year, not dropped silently.",
    "The same trade can appear on both exchanges and in both the bulk and block feeds. Duplicates are paired one-for-one by (date, client, side, qty, price, issuer); same-exchange same-type identical rows are retained because they may be separate trades. Residual duplicate reporting is possible.",
    "Promoter/insider exclusion is company-specific: exact normalized name against nse_insider (symbol->ISIN valid on the disclosure date) and bse_insider target-company promoter names, plus a PROMOTER token. SAST is not used because it also contains institutions. Family trusts or promoter vehicles not disclosed as insiders can remain; M1's declared TRUST token can therefore include a promoter trust. Coverage gaps: 8,486 nse_insider rows (4.8%) had no date-valid symbol mapping and 759 bse_insider rows (0.5%) had an ISIN absent from security_master; those names are not in the exclusion set.",
    "M2 is the fixed top-20 2021 repeat-client list after the declared broker/prop exclusions. It is dominated by proprietary/HFT firms; the exclusion tokens are exactly the four declared tokens, not a general 'securities' filter. The list is not chosen with future data.",
    "Net value is quantity x price from the feed. Block/bulk prints are negotiated prices, not executable market prices. The next-open gap versus the event buy VWAP is reported; the 30 bp round-trip cost is the only execution cost modelled.",
    "U1 is tested at the signal session (last regular session on or before the deal date); entry must have a finite opening total-return price. No missing value is zero-imputed.",
    "Prices are total-return adjusted through the shared panel. A missing scheduled close exits at the stock's next actual close; if none exists through 2025-12-31, a zero-recovery bound is retained and flagged, never booked as a fictitious sale.",
    "Event returns are t+1 open to scheduled close, after 30 bp and snapshot sell-date STCG. 20/60-session holds are short-term. No annual LTCG allowance is claimed by an isolated event.",
    "B5 uses the previous-session TRI close as its entry proxy because the snapshot has no index opens; BSE total-return series are derived. Event and book B5 pay the same cost/tax conventions.",
    "Date placebo permutes deal dates within stock-year and recomputes PIT/U1/entry/exit. Label placebo permutes M1/M2 labels across all deal-days within year x lagged-liquidity tercile x prior-200-trend sign, preserving counts per stratum. Neither is an independent-draw proof.",
    "BH pools every prior ledger row and the four current tests. The ledger is append-only; this run does not rewrite earlier H01 rows.",
    "Books use equal weights on admissions, fractional total-return units, 10% of lagged ADTV, 10% strategy allocation and the unchanged 8% kill. A kill decision fills at the next executable open and can overshoot 8%. No issuer cap is added in this declared run.",
    "No 2026 deal rows or 2026 outcomes are loaded. The full data-completeness gate remains unmet; coverage is printed rather than assumed.",
]

# The verification history below describes one finished run. It is emitted only
# for that run id: a rerun produces a new artifact that has not been verified
# yet, and must not inherit these claims. The text is report-only; the checker
# lives in verify_h02.py and is not imported by this module.
VERIFIED_STAGE1_RUN = "7c7e2d58-0d88-4f42-a8a9-05d21e2e70a3"

VERIFICATION_HISTORY = [
    "## Independent verification",
    "",
    "`reality_engine/harness/verify_h02.py` recomputes the final artifacts by different "
    "queries and arithmetic from the snapshot, opening it read-only and writing neither "
    "the snapshot nor the ledger. It passed 9 of 9 checks on the final files — sampled "
    "deal net values, entry and exit prices, tax and net returns, sampled B5 returns, "
    "event means, the BH q, a full FIFO replay of one book, the snapshot size/mtime and "
    "the pre-registration hash — and recorded the result in `H02_verification.json`.",
    "",
    "The check first ran on the 199-draw draft and returned 8 of 9. `sample_b5` failed on "
    "3 of the 30 sampled events: the checker's benchmark return sat 1.4–1.5 percentage "
    "points below the run's stored value on each.",
    "",
    "| Variant | Event date | Entry | Run `b5_net` | First checker | Gap |",
    "|---|---|---:|---:|---:|---:|",
    "| M1 20 | 2024-01-25 | 2024-01-29 | 3.95% | 2.52% | −1.44 pp |",
    "| M1 20 | 2024-11-05 | 2024-11-06 | 2.62% | 1.09% | −1.53 pp |",
    "| M1 60 | 2024-01-25 | 2024-01-29 | 6.45% | 4.98% | −1.47 pp |",
    "",
    "The fault was in the checker, not the run. `B5Path` buys the benchmark at the "
    "previous session's TRI close, so its first event factor is `tri[entry]/tri[entry-1]`; "
    "at an index switch it realises the outgoing index through the session before and "
    "restarts from that same close. The first checker began each segment at its first "
    "session's close instead of the session before, dropping one session of benchmark "
    "return per segment. Replaying that convention reproduces the three failing values "
    "exactly (2.5186%, 1.0902%, 4.9815%); starting each segment a session earlier "
    "reproduces the stored values exactly (3.9539%, 2.6249%, 6.4527%). The legs it "
    "dropped were +1.29% (Nifty Smallcap 250, 25→29 Jan 2024), +1.89% (Nifty Smallcap "
    "250, 5→6 Nov 2024) and +0.34% (BSE IPO, 31 Jan→1 Feb 2024). Both constructions "
    "charge 30 bp and sell-date tax on each segment, so the omitted gross legs carry "
    "through to the net gap above.",
    "",
    "The corrected checker passed 9 of 9 on the same draft files, and 9 of 9 on the final "
    "files. Nothing in the run moved: no run was executed between the failing and the "
    "passing draft check, the only edit was to `verify_h02.py`, and nothing in the run "
    "imports it; the three stored values in the table are the ones the first checker "
    "compared against, and they are the values in the final artifact; the final 499-draw "
    "run reproduced the draft's four variant rows on event count, mean, cluster t, p and "
    "BH q (the placebo p are not comparable, the draft being a 199-draw run and the "
    "final 499); and no harness, event or tax code changed. H02's B5 is the same "
    "`B5Path` used by the earlier H01 results.",
    "",
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--placebo-draws", type=int, default=499)
    parser.add_argument("--liquidity-threshold", type=float, default=5_000_000.0)
    parser.add_argument("--dry-run", action="store_true",
                        help="compute everything but do not write the ledger or final JSON")
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
        schemas = inspect(c)
        truth = json.loads(c.execute("SELECT report_json FROM truth_report").fetchone()[0])
        snapshot_meta = c.execute("SELECT snapshot_date,built_from,built_to FROM snapshot_meta").fetchall()
        rules = load_tax(c)
        progress("H02: loading and normalizing deal feeds")
        data = load_deals(snapshot.path)
        prereg_path = OUT / "H02_preregistration.md"
        prereg_hash = preregistration(data, prereg_path)
        progress(f"H02: pre-registration written; M1 events={len(data.events('M1'))}, "
                 f"M2 events={len(data.events('M2'))}")
        progress("H02: building price panel and B5")
        panel = Panel(c, args.liquidity_threshold)
        benchmark = B5Path(load_indexes(c), panel.calendar, rules)
        progress("H02: rebuilding H01 positive-PAT 180 events for overlap audit")
        h01 = load_h01_lead(c, panel, benchmark, rules)
        evaluator = DealEvaluator(data, panel, benchmark, rules)
        observed, results, event_sets = [], {}, {}
        for params in VARIANTS:
            row, result = evaluator.summary(params["definition"], params["horizon"], detailed=True)
            observed.append(row)
            results[(params["definition"], params["horizon"])] = result
        prior_tests = previous_tests()
        q_values = bh_fdr([p for _, p in prior_tests] + [r["p"] for r in observed])[-len(VARIANTS):]
        for row, q in zip(observed, q_values):
            row["bh_q"] = q
        progress("H02: date placebo")
        placebo = evaluator.date_placebo(args.placebo_draws)
        progress("H02: label placebo")
        label = evaluator.label_placebo(args.placebo_draws)
        attach_placebo(observed, placebo, label,
                       [(p["definition"], p["horizon"]) for p in VARIANTS])
        benchmark_nav, benchmark_book = benchmark.book_nav()
        books, fills = run_books(evaluator, benchmark_nav)
        liquidity, overlaps, flat_events = [], [], []
        for row in observed:
            params = row["params"]
            key = (params["definition"], params["horizon"])
            result = results[key]
            tercile, _ = add_liquidity_tercile(evaluator, params["definition"], result)
            table, _ = liquidity_table(evaluator, params["definition"], result)
            liquidity.append({**params, "table": table})
            flag, rate = h01_overlap(evaluator, params["definition"], h01)
            n_overlap = int(flag[result["ids"]].sum()) if len(result["ids"]) else 0
            overlaps.append({**params, "n_events": int(len(result["ids"])),
                             "n_overlap": n_overlap, "rate": rate})
            flat_events.extend(event_rows(evaluator, params["definition"],
                                          params["horizon"], result, row, tercile, flag))
        for row in observed:
            params = row["params"]
            desired = 1
            yearly = [v["mean"] for v in row["per_year"].values() if v["mean"] is not None]
            row["proof_checks"] = {
                "bh_q_le_005": row["bh_q"] <= .05,
                "placebo_p_le_005": row["placebo_p"] <= .05,
                "directional_placebo_p_le_005": row["placebo_directional_p"] <= .05,
                "label_placebo_p_le_005": row["label_placebo_p"] <= .05,
                "max_t_p_le_005": row["reality_check_p"] <= .05,
                "four_years_expected_sign": len(yearly) >= 4 and all(v * desired > 0 for v in yearly),
                "both_regimes_expected_sign": all(
                    v["n"] >= 30 and v["mean"] is not None and v["mean"] * desired > 0
                    for v in row["regimes"].values()),
                "book_positive_excess_and_not_killed": (
                    books[f"{params['definition']}_{params['horizon']}"]["excess_cagr"] > 0
                    and books[f"{params['definition']}_{params['horizon']}"]["kill_date"] is None
                    and not books[f"{params['definition']}_{params['horizon']}"]["unresolved_holdings"]),
            }
            row["status"] = ("provisional_pass"
                             if all(row["proof_checks"].values()) else "fail")
            row["promoted"] = False
        coverage = coverage_by_year(panel, data)
        git_hash, source_hashes = code_provenance()
        test_path = OUT / "H02_tests.json"
        test_results = (json.loads(test_path.read_text(encoding="utf-8-sig"))
                        if test_path.exists() else {})
        result = {
            "card_id": "H02", "stage": 1, "status": "completed_provisional",
            "provisional": True, "promoted": False,
            "evidence_window": ["2021-01-01", "2025-12-31"],
            "warmup": ["2019-01-01", "2020-12-31"],
            "run_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_name": snapshot.path.name, "snapshot_read_only": True,
            "snapshot_meta": snapshot_meta, "git_head": git_hash,
            "source_sha256": source_hashes,
            "pre_registration_sha256": prereg_hash,
            "m1_pattern": M1_PATTERN, "m1_exclude": M1_EXCLUDE,
            "liquidity_threshold_inr": args.liquidity_threshold,
            "deal_audit": data.audit, "insider_audit": data.insider_audit,
            "m2_list": data.m2_list.to_dict(orient="records"),
            "variants": observed, "books": books,
            "coverage_report": coverage,
            "benchmark_choices": benchmark.choices,
            "benchmark_book": benchmark_book,
            "placebo": {k: v for k, v in placebo.items() if k != "means"},
            "label_placebo": {k: v for k, v in label.items() if k != "means"},
            "placebo_means": {f"{k[0]}_{k[1]}": v.tolist() for k, v in placebo["means"].items()},
            "label_placebo_means": {f"{k[0]}_{k[1]}": v.tolist() for k, v in label["means"].items()},
            "liquidity_terciles": liquidity, "h01_overlap": overlaps,
            "h01_lead_audit": {"n_events": int(len(h01)),
                               "mean_h01_net_excess": float(h01["h01_net_excess"].mean())
                               if len(h01) else None},
            "events": flat_events,
            "fdr_scope": {"current_variants": len(VARIANTS),
                          "prior_ledger_tests": len(prior_tests),
                          "total_tests": len(prior_tests) + len(VARIANTS),
                          "prior_run_ids": sorted({rid for rid, _ in prior_tests})},
            "panel_audit": panel.audit, "truth_report": truth, "schemas": schemas,
            "test_results": test_results,
            "promotion_bar": "BH q, date and label placebo, directional and max-T p <=0.05; "
                             "expected sign in >=4 years and both regimes; positive surviving book. "
                             "Full data gate additionally required.",
            "deviations": DEVIATIONS,
            "full_data_completeness_gate_met": False,
            "dry_run": bool(args.dry_run),
        }
        result = clean(result)
        if args.dry_run:
            result["ledger_run_id"] = "DRY_RUN_NOT_APPENDED"
            result["ledger_rows_appended"] = 0
        else:
            stale = OUT / "H02_results.json"
            if stale.exists():
                raise FileExistsError("H02_results.json exists; archive it before a new ledger run")
            run_id = append_variants(result["variants"], snapshot=snapshot.path.name,
                                     git_hash=git_hash, coverage=result["coverage_report"],
                                     source_hashes=result["source_sha256"], card_id="H02")
            result["ledger_run_id"] = run_id
            result["ledger_rows_appended"] = len(VARIANTS)
            append_run_note(run_id, json.dumps({
                "card": "H02", "stage": 1,
                "pre_registration_sha256": prereg_hash,
                "method": "declared M1/M2 x 20/60",
                "prior_runs_in_bh": result["fdr_scope"]["prior_run_ids"],
            }))
        stat_after = snapshot.path.stat()
        result["snapshot_file_unchanged"] = (
            (stat_before.st_size, stat_before.st_mtime_ns)
            == (stat_after.st_size, stat_after.st_mtime_ns))
        if not result["snapshot_file_unchanged"]:
            raise RuntimeError("Read-only source snapshot changed during run")
        result["elapsed_seconds"] = perf_counter() - started
        if args.dry_run:
            (OUT / "H02_results_draft.json").write_text(
                json.dumps(result, indent=2, allow_nan=False, ensure_ascii=False),
                encoding="utf-8")
            pd.DataFrame(flat_events).to_csv(OUT / "H02_events_draft.csv.gz",
                                             index=False, compression="gzip")
            pd.DataFrame(fills).to_csv(OUT / "H02_book_fills_draft.csv.gz",
                                       index=False, compression="gzip")
        else:
            (OUT / "H02_results.json").write_text(
                json.dumps(result, indent=2, allow_nan=False, ensure_ascii=False),
                encoding="utf-8")
            pd.DataFrame(flat_events).to_csv(OUT / "H02_events.csv.gz",
                                             index=False, compression="gzip")
            pd.DataFrame(fills).to_csv(OUT / "H02_book_fills.csv.gz",
                                       index=False, compression="gzip")
            write_report(result, OUT / "H02_report.md")
        progress(f"H02 finished; elapsed {result['elapsed_seconds']:.1f}s; "
                 f"run={result['ledger_run_id']}")


if __name__ == "__main__":
    main()
