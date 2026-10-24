"""DeepInfra decision-model pilot on our own documents (2026-10-24).

Arms
  A1  BSE announcement classification (200 items, 9-way choice)
  A2  AR passage relevance (48 questions x top-6 NVFP4 candidates, yes/no)
  B   Calibrated event outcome (100 point-in-time insider/bulk-deal buys, yes/no)

Endpoints: POST https://api.deepinfra.com/v1/decisions with {model, state, questions}.
Pricing (input only, output free): clef-flash $0.038/M, drex-v2.0 $0.06/M, drex-max $0.12/M.

Resumable: every response is cached under cache/responses/<model>/<arm>/<id>.json and
re-used on the next run. The spend ledger is spend.json and the cap is hard: no request
is sent once cumulative spend reaches --max-usd.

Data prep (already run; outputs are in data/):
    python tasks/research/decision_pilot/prep_a1.py
    python tasks/research/decision_pilot/prep_a2.py
    python tasks/research/decision_pilot/prep_b.py

    python tasks/research/decision_pilot/run_pilot.py [--arms A1,A2,B] [--models ...]
"""
import argparse
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = ROOT / "cache"
OUT = ROOT
API = "https://api.deepinfra.com/v1/decisions"
PRICE = {
    "Cloudflare/clef-flash": 0.038,
    "nace-ai/drex-v2.0": 0.06,
    "nace-ai/drex-max": 0.12,
}
CTX_TOKENS = {"Cloudflare/clef-flash": 24_576, "nace-ai/drex-v2.0": 131_072, "nace-ai/drex-max": 262_144}
CATS = ["Company Update", "AGM/EGM", "Insider Trading / SAST", "Others",
        "Board Meeting", "Corp. Action", "Mutual Fund", "Result", "Other / not listed"]
CAT_DESC = {
    "Company Update": "general company update, regulation 30 disclosure, compliance certificate, management change",
    "AGM/EGM": "annual or extraordinary general meeting notice, proceedings, postal ballot, voting result",
    "Insider Trading / SAST": "insider trading disclosure, trading-window closure, SAST/PIT filing",
    "Others": "exchange catch-all for an announcement that does not fit another category",
    "Board Meeting": "board meeting intimation or outcome",
    "Corp. Action": "dividend, split, bonus, rights, record date, book closure",
    "Mutual Fund": "mutual fund NAV or monthly portfolio disclosure",
    "Result": "financial results",
    "Other / not listed": "none of the above",
}


_KEY = None


def key():
    global _KEY
    if _KEY:
        return _KEY
    k = os.environ.get("DEEPINFRA_API_KEY")
    if not k:
        k = subprocess.run(["powershell", "-NoProfile", "-c",
                            "[Environment]::GetEnvironmentVariable('DEEPINFRA_API_KEY','User')"],
                           capture_output=True, text=True).stdout
    k = k.strip()
    if not k:
        raise SystemExit("DEEPINFRA_API_KEY not found")
    _KEY = k
    return k


def slug(model):
    return model.replace("/", "__")


class Ledger:
    def __init__(self, path, cap):
        self.path, self.cap, self.lock = path, cap, threading.Lock()
        self.data = json.load(open(path)) if path.exists() else {"usd": 0.0, "entries": []}
        self.data.setdefault("entries", [])
        self.stop = False

    def can_spend(self, est):
        with self.lock:
            if self.stop or self.data["usd"] + est > self.cap:
                self.stop = True
                return False
            return True

    def add(self, model, arm, item, tokens, usd, latency_ms, status, retries, output_tokens=0):
        with self.lock:
            self.data["usd"] += usd
            self.data["entries"].append({
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "model": model, "arm": arm,
                "id": item, "input_tokens": tokens, "output_tokens": output_tokens,
                "usd": round(usd, 8), "latency_ms": latency_ms, "status": status, "retries": retries})
            if self.data["usd"] >= self.cap:
                self.stop = True
            json.dump(self.data, open(self.path, "w"), indent=1)

    @property
    def usd(self):
        return self.data["usd"]


def clean_state(state, model):
    """Truncate a string state to the model context (3 chars/token, 90% headroom)."""
    if not isinstance(state, str):
        return state, False
    cap = int(CTX_TOKENS[model] * 3 * 0.9)
    if len(state) > cap:
        return state[:cap], True
    return state, False


def call(model, state, questions, k, ledger, arm, item, max_attempts=8):
    state, truncated = clean_state(state, model)
    body = {"model": model, "state": state, "questions": questions}
    est = len(json.dumps(body)) / 3.0 / 1e6 * PRICE[model] * 1.5
    if not ledger.can_spend(est):
        return {"status": "cap", "truncated": truncated}
    retries = 0
    n429 = 0
    for attempt in range(max_attempts):
        t0 = time.perf_counter()
        try:
            r = requests.post(API, headers={"Authorization": "Bearer " + k}, json=body, timeout=180)
        except Exception as e:
            retries += 1
            if attempt == max_attempts - 1:
                return {"status": "network", "error": repr(e), "truncated": truncated, "_429": n429}
            time.sleep(min(30, 1.5 * 2 ** attempt))
            continue
        ms = round((time.perf_counter() - t0) * 1000, 1)
        if r.status_code == 200:
            j = r.json()
            u = j.get("usage") or {}
            tok = int(u.get("input_tokens") or 0)
            out = int(u.get("output_tokens") or 0)
            usd = tok * PRICE[model] / 1e6
            ledger.add(model, arm, item, tok, usd, ms, "ok", retries, out)
            j["status"] = "ok"
            j["_latency_ms"] = ms
            j["_retries"] = retries
            j["_429"] = n429
            j["_truncated"] = truncated
            return j
        retries += 1
        if r.status_code == 429:
            n429 += 1
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == max_attempts - 1:
                return {"status": "http", "code": r.status_code, "body": r.text[:300],
                        "truncated": truncated, "_429": n429}
            time.sleep(min(30, 2 ** attempt) + 0.3 * attempt)
            continue
        return {"status": "http", "code": r.status_code, "body": r.text[:300],
                "truncated": truncated, "_429": n429}
    return {"status": "http", "truncated": truncated}


def cached_run(model, arm, items, make_body, ledger, workers=6):
    """items: list of dicts with id + payload for make_body -> (state, questions)."""
    d = CACHE / "responses" / slug(model) / arm
    d.mkdir(parents=True, exist_ok=True)
    todo = []
    for it in items:
        p = d / (re.sub(r"[^A-Za-z0-9_.-]", "_", it["id"]) + ".json")
        if p.exists():
            try:
                old = json.load(open(p))
                if "status" not in old and "answers" in old:
                    old["status"] = "ok"
                    json.dump(old, open(p, "w"), indent=1)
                if old.get("status") == "ok":
                    continue
            except Exception:
                pass
        todo.append((it, p))
    print(f"  {model} {arm}: {len(items)-len(todo)} cached, {len(todo)} to call", flush=True)
    done = 0

    def one(it, p):
        nonlocal done
        state, questions = make_body(it)
        j = call(model, state, questions, key(), ledger, arm, it["id"])
        j["_arm"], j["_model"], j["_id"] = arm, model, it["id"]
        tmp = p.with_suffix(".tmp")
        json.dump(j, open(tmp, "w"), indent=1)
        tmp.replace(p)
        done += 1
        if done % 25 == 0:
            print(f"    {done}/{len(todo)} (spent ${ledger.usd:.4f})", flush=True)
        return j

    if todo:
        with ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(one, it, p) for it, p in todo]
            for f in as_completed(futs):
                f.result()
    out = []
    for it in items:
        p = d / (re.sub(r"[^A-Za-z0-9_.-]", "_", it["id"]) + ".json")
        try:
            out.append(json.load(open(p)))
        except Exception:
            out.append({"status": "missing", "_id": it["id"], "_model": model, "_arm": arm})
    return out


def probe(models, ledger, k):
    p = CACHE / "probes.json"
    old = json.load(open(p)) if p.exists() else {}
    for m in models:
        if m in old and old[m].get("status") == "ok":
            continue
        body = {"model": m, "state": {"headline": "Board approves buyback", "symbol": "XYZ"},
                "questions": {"material": {"type": "noul", "instructions": "Is this materially positive?"},
                              "category": {"type": "choice", "instructions": "Which category?",
                                           "criteria": {"board": "Board outcome", "other": "Other"}}}}
        t0 = time.perf_counter()
        try:
            r = requests.post(API, headers={"Authorization": "Bearer " + k}, json=body, timeout=120)
            ms = round((time.perf_counter() - t0) * 1000, 1)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200:
                tok = int((j.get("usage") or {}).get("input_tokens") or 0)
                ledger.add(m, "probe", "probe", tok, tok * PRICE[m] / 1e6, ms, "ok", 0)
                old[m] = {"status": "ok", "latency_ms": ms, "response": j, "at": datetime.now(timezone.utc).isoformat()}
            else:
                old[m] = {"status": "http", "code": r.status_code, "body": r.text[:300], "latency_ms": ms,
                          "at": datetime.now(timezone.utc).isoformat()}
        except Exception as e:
            old[m] = {"status": "network", "error": repr(e), "at": datetime.now(timezone.utc).isoformat()}
        json.dump(old, open(p, "w"), indent=1)
        print("probe", m, old[m]["status"], flush=True)
    return old


# ---------------------------------------------------------------- metrics

def ece_binary(p, y, bins=10):
    p = np.clip(np.asarray(p, float), 0, 1)
    y = np.asarray(y, float)
    edges = np.linspace(0, 1, bins + 1)
    e, table = 0.0, []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        m = (p >= lo) & (p < hi if i < bins - 1 else p <= hi)
        if not m.any():
            continue
        mp, my = float(p[m].mean()), float(y[m].mean())
        e += m.sum() / len(p) * abs(mp - my)
        table.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()), "mean_p": round(mp, 4), "obs": round(my, 4)})
    return e, table


def auc_rank(p, y):
    p = np.asarray(p, float); y = np.asarray(y, int)
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return None
    order = np.argsort(np.concatenate([pos, neg]), kind="merged")
    ranks = np.empty(len(order), float)
    ranks[order] = np.arange(1, len(order) + 1)
    # average ties
    allv = np.concatenate([pos, neg])
    for v in np.unique(allv):
        idx = np.where(allv == v)[0]
        if len(idx) > 1:
            ranks[idx] = ranks[idx].mean()
    rp = ranks[:len(pos)].sum()
    return float((rp - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def logit(p, eps=1e-6):
    p = np.clip(np.asarray(p, float), eps, 1 - eps)
    return np.log(p / (1 - p))


def calib_slope(p, y):
    x = logit(p); X = np.column_stack([np.ones(len(x)), x])
    y = np.asarray(y, float); b = np.zeros(2)
    for _ in range(100):
        eta = X @ b; mu = 1 / (1 + np.exp(-np.clip(eta, -30, 30)))
        w = np.clip(mu * (1 - mu), 1e-9, None)
        H = X.T @ (w[:, None] * X) + np.eye(2) * 1e-6
        g = X.T @ (y - mu)
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-8:
            break
    return float(b[1])


def brier(p, y):
    return float(np.mean((np.asarray(p, float) - np.asarray(y, float)) ** 2))


def logloss(p, y):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def macro_f1(y_true, y_pred, labels):
    f1s = []
    for c in labels:
        tp = sum(1 for a, b in zip(y_true, y_pred) if a == c and b == c)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a != c and b == c)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == c and b != c)
        f1s.append(0.0 if tp == 0 else 2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s)), f1s


def pct(x, n=4):
    return None if x is None else round(float(x), n)


# ---------------------------------------------------------------- arms

def run_a1(models, ledger, workers, results, limit=None):
    items = json.load(open(DATA / "a1_items.json", encoding="utf-8"))
    if limit:
        items = items[:limit]
    questions = {"category": {"type": "choice",
                              "instructions": "Which BSE announcement category best describes this filing? "
                                              "Choose the single best category.",
                              "criteria": {c: CAT_DESC[c] for c in CATS}}}

    def make(it):
        return it["state"], questions
    res = results.setdefault("A1", {})
    res["dataset"] = {"n": len(items), "categories": CATS,
                      "attachment_text": sum(bool(x.get("attachment_text")) for x in items)}
    res["label_audit"] = audit_summary(items)
    res.setdefault("models", {})
    for m in models:
        if m not in PRICE:
            continue
        print(f"A1 {m}", flush=True)
        raws = cached_run(m, "A1", items, make, ledger, workers)
        y, pred, conf, errs, hist = [], [], [], 0, []
        for it, r in zip(items, raws):
            if r.get("status") != "ok":
                errs += 1; y.append(it["label"]); pred.append(None); conf.append(0.0); continue
            a = (r.get("answers") or {}).get("category") or {}
            probs = a.get("probabilities") or {}
            if not probs or abs(sum(probs.values()) - 1) > 0.02 or a.get("choice") not in CATS:
                errs += 1; y.append(it["label"]); pred.append(None); conf.append(0.0); continue
            y.append(it["label"]); pred.append(a["choice"]); conf.append(float(max(probs.values())))
            hist.append(float(max(probs.values())))
        ok = [i for i, p in enumerate(pred) if p is not None]
        correct = [pred[i] == y[i] for i in ok]
        acc = float(np.mean(correct)) if correct else None
        mf1, per = macro_f1([y[i] for i in ok], [pred[i] for i in ok], CATS[:-1])
        e, ece_table = ece_multiclass(conf, [1 if pred[i] == y[i] else 0 for i in range(len(y))], ok)
        per_acc = {}
        for c in CATS[:-1]:
            idx = [i for i in ok if y[i] == c]
            per_acc[c] = pct(np.mean([pred[i] == y[i] for i in idx])) if idx else None
        lat = [r["_latency_ms"] for r in raws if r.get("status") == "ok"]
        usd = sum(r.get("usage", {}).get("input_tokens", 0) * PRICE[m] / 1e6 for r in raws
                  if r.get("status") == "ok")
        # audited-clean subset
        audit = {x["id"]: x for x in audit_items()}
        clean = [i for i in ok if audit.get(items[i]["id"], {}).get("label_ok") == 1]
        cacc = float(np.mean([pred[i] == y[i] for i in clean])) if clean else None
        cmf1, _ = macro_f1([y[i] for i in clean], [pred[i] for i in clean], CATS[:-1]) if clean else (None, None)
        ce, ctable = ece_multiclass([conf[i] for i in clean], [1 if pred[i] == y[i] else 0 for i in clean],
                                    list(range(len(clean)))) if clean else (None, [])
        res["models"][m] = {
            "n_scored": len(ok), "accuracy": pct(acc), "accuracy_incl_errors": pct(sum(correct) / len(items)),
            "macro_f1": pct(mf1), "per_class_f1": dict(zip(CATS[:-1], [pct(x) for x in per])),
            "per_class_accuracy": per_acc,
            "ece_top_label": pct(e), "reliability": ece_table,
            "format_errors": errs, "format_error_rate": pct(errs / len(items)),
            "clean_n": len(clean), "clean_accuracy": pct(cacc), "clean_macro_f1": pct(cmf1), "clean_ece": pct(ce),
            "clean_reliability": ctable,
            "histogram": np.histogram(hist, bins=np.linspace(0, 1, 11))[0].tolist() if hist else [],
            "latency_ms": {"p50": pct(np.percentile(lat, 50), 1) if lat else None,
                           "p95": pct(np.percentile(lat, 95), 1) if lat else None},
            "retries": sum(r.get("_retries", 0) for r in raws), "http_429": sum(r.get("_429", 0) for r in raws),
            "truncated": sum(bool(r.get("_truncated")) for r in raws),
            "cost_usd": round(usd, 5), "cost_per_1k": round(usd / max(len(ok), 1) * 1000, 3),
            "confusion": confusion(y, pred, CATS[:-1]),
        }
        print(json.dumps({k: v for k, v in res["models"][m].items() if k not in ("confusion", "per_class_f1")}),
              flush=True)
    return results


def ece_multiclass(conf, correct, idx):
    if not idx:
        return None, []
    c = np.array([conf[i] for i in idx], float)
    y = np.array([correct[i] for i in idx], float)
    e, table = ece_binary(c, y, 10)
    return e, table


def confusion(y, pred, labels):
    mat = {a: {b: 0 for b in labels} for a in labels}
    for a, b in zip(y, pred):
        if b is not None and a in mat and b in mat:
            mat[a][b] += 1
    return mat


def audit_items():
    sample = json.load(open(DATA / "a1_audit_sample.json", encoding="utf-8"))
    verdicts = {x["n"]: x for x in json.load(open(DATA / "a1_audit.json", encoding="utf-8"))["items"]}
    out = []
    for s in sample:
        v = verdicts.get(s["n"], {})
        out.append({**s, "label_ok": v.get("label_ok"), "reason": v.get("reason")})
    return out


def audit_summary(items):
    audit = audit_items()
    bad = [a for a in audit if a["label_ok"] == 0]
    return {"n": len(audit), "wrong": len(bad), "noise_rate": pct(len(bad) / len(audit)),
            "clean_n": len(audit) - len(bad), "wrong_ids": [a["id"] for a in bad],
            "verdicts": audit}


def run_a2(models, ledger, workers, results, limit=None):
    data = json.load(open(DATA / "a2_pairs.json", encoding="utf-8"))
    pairs = data["pairs"]
    if limit:
        pairs = [p for p in pairs if p["qid"] < limit]
    qs = {}
    for p in pairs:
        qs.setdefault(p["qid"], []).append(p)
    no_cand = sum(1 for rows in qs.values() if not any(x["label"] for x in rows))
    base = {"nvfp4_alone": {"hit@1": data["hit@1"], "hit@3": data["hit@3"]},
            "nemotron35_rerank_8b": {"hit@1": 0.812, "hit@3": 0.958, "cost_usd": 0.0345},
            "nemotron3_embed_8b": {"hit@1": 0.625, "hit@3": 0.917}}
    res = results.setdefault("A2", {})
    res["dataset"] = {"questions": len(qs), "pairs": len(pairs),
                      "candidate_model": data["model"], "ranks": data["ranks"],
                      "questions_without_candidate": no_cand,
                      "max_hit@3": pct((len(qs) - no_cand) / len(qs)) if qs else None}
    res["baselines"] = base
    res.setdefault("models", {})

    def make(it):
        return {"question": it["question"], "passage": it["state"]}, {
            "answers": {"type": "noul", "instructions": "Does this passage contain the information needed to answer the question?"}}
    for m in models:
        if m not in PRICE:
            continue
        print(f"A2 {m}", flush=True)
        raws = cached_run(m, "A2", pairs, make, ledger, workers)
        byq = {}
        p_all, y_all, errs = [], [], 0
        for p, r in zip(pairs, raws):
            if r.get("status") != "ok":
                errs += 1; prob = None
            else:
                prob = (r.get("answers") or {}).get("answers", {}).get("noul")
                if prob is None:
                    errs += 1
            byq.setdefault(p["qid"], []).append({**p, "p": prob})
            y_all.append(p["label"]); p_all.append(0.5 if prob is None else float(prob))
        auc = auc_rank(p_all, y_all)
        hits = {1: 0, 3: 0}
        ranks = []
        for qid, rows in byq.items():
            rows = sorted(rows, key=lambda x: (-(x["p"] if x["p"] is not None else 0.5), x["cand_rank"]))
            ranks.append(next((i for i, x in enumerate(rows, 1) if x["label"]), None))
            for k in (1, 3):
                if any(x["label"] for x in rows[:k]):
                    hits[k] += 1
        e, table = ece_binary(p_all, y_all, 10)
        lat = [r["_latency_ms"] for r in raws if r.get("status") == "ok"]
        usd = sum(r.get("usage", {}).get("input_tokens", 0) * PRICE[m] / 1e6 for r in raws
                  if r.get("status") == "ok")
        res["models"][m] = {
            "auc": pct(auc), "hit@1": pct(hits[1] / len(byq)), "hit@3": pct(hits[3] / len(byq)),
            "ranks": ranks,
            "brier": pct(brier(p_all, y_all)), "ece": pct(e), "format_errors": errs,
            "format_error_rate": pct(errs / len(pairs)), "histogram": np.histogram(p_all, bins=np.linspace(0, 1, 11))[0].tolist(),
            "reliability": table,
            "latency_ms": {"p50": pct(np.percentile(lat, 50), 1) if lat else None,
                           "p95": pct(np.percentile(lat, 95), 1) if lat else None},
            "retries": sum(r.get("_retries", 0) for r in raws), "http_429": sum(r.get("_429", 0) for r in raws),
            "truncated": sum(bool(r.get("_truncated")) for r in raws),
            "cost_usd": round(usd, 5), "cost_per_1k_pairs": round(usd / max(len(pairs), 1) * 1000, 3),
            "cost_per_query": round(usd / len(byq), 5) if byq else None,
        }
        print(json.dumps({k: v for k, v in res["models"][m].items() if k not in ("reliability", "histogram")}),
              flush=True)
    return results


def run_b(models, ledger, workers, results, limit=None):
    items = json.load(open(DATA / "b_events.json", encoding="utf-8"))
    if limit:
        items = items[:limit]
    questions = {"beat": {"type": "noul",
                          "instructions": "Will the stock beat the Nifty 50 total return index over the next 20 trading days?"}}

    def make(it):
        return it["state"], questions
    base = float(np.mean([x["label"] for x in items]))
    res = results.setdefault("B", {})
    res["dataset"] = {"n": len(items), "base_rate": pct(base),
                      "insider": sum(x["state"]["event_type"] == "insider_buy" for x in items),
                      "bulk": sum(x["state"]["event_type"] == "bulk_deal_buy" for x in items),
                      "window": [min(x["known_at"] for x in items), max(x["known_at"] for x in items)],
                      "pit_ok": sum(bool(x["pit_check"].get("ok")) for x in items),
                      "sector_unknown": sum(x["state"]["sector"] == "Unknown" for x in items),
                      "delivery_missing": sum(x["state"]["delivery_pct"] is None for x in items),
                      "max_state_chars": max(len(json.dumps(x["state"])) for x in items)}
    res.setdefault("models", {})
    res["dataset"]["base_rate_brier"] = pct(np.mean((base - np.array([x["label"] for x in items])) ** 2))
    for m in models:
        if m not in PRICE:
            continue
        print(f"B {m}", flush=True)
        raws = cached_run(m, "B", items, make, ledger, workers)
        p, y, errs = [], [], 0
        for it, r in zip(items, raws):
            y.append(it["label"])
            prob = (r.get("answers") or {}).get("beat", {}).get("noul") if r.get("status") == "ok" else None
            if prob is None:
                errs += 1; p.append(0.5)
            else:
                p.append(float(prob))
        p = np.array(p); y = np.array(y)
        e, table = ece_binary(p, y, 10)
        slope = calib_slope(p, y)
        lat = [r["_latency_ms"] for r in raws if r.get("status") == "ok"]
        usd = sum(r.get("usage", {}).get("input_tokens", 0) * PRICE[m] / 1e6 for r in raws
                  if r.get("status") == "ok")
        res["models"][m] = {
            "brier": pct(brier(p, y)), "base_brier": res["dataset"]["base_rate_brier"],
            "brier_skill": pct(1 - brier(p, y) / res["dataset"]["base_rate_brier"]) if res["dataset"]["base_rate_brier"] else None,
            "log_loss": pct(logloss(p, y)), "ece": pct(e), "slope": pct(slope), "auc": pct(auc_rank(p, y)),
            "format_errors": errs, "format_error_rate": pct(errs / len(items)),
            "histogram": np.histogram(p, bins=np.linspace(0, 1, 11))[0].tolist(), "reliability": table,
            "latency_ms": {"p50": pct(np.percentile(lat, 50), 1) if lat else None,
                           "p95": pct(np.percentile(lat, 95), 1) if lat else None},
            "retries": sum(r.get("_retries", 0) for r in raws), "http_429": sum(r.get("_429", 0) for r in raws),
            "truncated": sum(bool(r.get("_truncated")) for r in raws),
            "cost_usd": round(usd, 5), "cost_per_1k": round(usd / max(len(items), 1) * 1000, 3),
            "mean_p": pct(p.mean()), "hit_rate": pct(y.mean()),
        }
        print(json.dumps({k: v for k, v in res["models"][m].items() if k not in ("reliability", "histogram")}),
              flush=True)
    return results


def add_verdicts(results):
    """Pre-declared markers from the brief, applied to the metrics as stored."""
    v = {}
    for m, r in (results.get("A1", {}).get("models") or {}).items():
        ok = (r["clean_accuracy"] or 0) >= 0.90 and (r["clean_macro_f1"] or 0) >= 0.85 \
             and (r["clean_ece"] or 1) <= 0.05 and (r["format_error_rate"] or 1) <= 0.01
        v.setdefault("A1", {})[m] = {"pass": bool(ok), "strong": bool(ok and (r["clean_accuracy"] or 0) >= 0.95)}
    for m, r in (results.get("A2", {}).get("models") or {}).items():
        ok = (r["auc"] or 0) >= 0.90 and (r["hit@3"] or 0) >= 0.917
        strong = bool(ok and (r["hit@1"] or 0) >= 0.812 and (r["cost_per_query"] or 1) < 0.0345 / 48)
        v.setdefault("A2", {})[m] = {"pass": bool(ok), "strong": strong}
    base_brier = results.get("B", {}).get("dataset", {}).get("base_rate_brier")
    for m, r in (results.get("B", {}).get("models") or {}).items():
        ok = base_brier is not None and r["brier"] is not None and r["brier"] <= base_brier - 0.01 \
             and r["slope"] is not None and 0.7 <= r["slope"] <= 1.3
        v.setdefault("B", {})[m] = {"pass": bool(ok), "strong": bool((r["auc"] or 0) >= 0.60)}
    results["verdicts"] = v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arms", default="A1,A2,B")
    ap.add_argument("--models", default="Cloudflare/clef-flash,nace-ai/drex-v2.0")
    ap.add_argument("--a2-models", default="Cloudflare/clef-flash,nace-ai/drex-v2.0,nace-ai/drex-max")
    ap.add_argument("--max-usd", type=float, default=0.45)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--probe", action="store_true")
    a = ap.parse_args()
    arms = a.arms.split(","); models = a.models.split(","); a2m = a.a2_models.split(",")
    ledger = Ledger(OUT / "spend.json", a.max_usd)
    results_path = OUT / "results.json"
    results = json.load(open(results_path)) if results_path.exists() else {}
    results.setdefault("spend_at_start", ledger.usd)
    results["pricing_usd_per_m"] = PRICE
    if a.probe:
        results["probes"] = probe(sorted(set(models + a2m)), ledger, key())
    if "A1" in arms:
        run_a1(models, ledger, a.workers, results, a.limit)
    if "A2" in arms:
        run_a2(a2m, ledger, a.workers, results, a.limit)
    if "B" in arms:
        run_b(models, ledger, a.workers, results, a.limit)
    results["spend"] = {"usd": round(ledger.usd, 6), "cap": a.max_usd}
    results["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    add_verdicts(results)
    json.dump(results, open(results_path, "w"), indent=1)
    print(f"TOTAL spend ${ledger.usd:.4f} / ${a.max_usd}", flush=True)


if __name__ == "__main__":
    main()
