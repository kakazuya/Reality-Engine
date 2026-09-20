"""
Wave B — Telegram alerts + 23:00 nightly digest (stdlib only, no new deps).

Owns ONLY this file. Never touches ``cli.py`` or ``pipeline/nightly*``.

* ``send_telegram(message, dry_run=False)`` reads ``TELEGRAM_BOT_TOKEN`` and
  ``TELEGRAM_CHAT_ID`` from the environment and POSTs via ``urllib``.
  Missing credentials → log a warning + return ``False``; transport or API
  errors → log + return ``False``. Never raises for missing creds or
  network failures (only ``dry_run`` misuse / bad types raise).
* ``format_nightly_digest(health_json_path, validation_summary)`` builds the
  23:00 digest text: pipeline stages, checkpoint %, top-20 overlap,
  hit-rates, and failures. Accepts a path, a JSON string, or an already
  parsed dict for either argument; never raises — worst case it returns a
  short "data unavailable" digest.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("reality_engine.reporting.notifier")

TELEGRAM_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
MAX_MESSAGE_CHARS = 4000


def _coerce_mapping(
    arg: Union[str, Path, Dict[str, Any], None], name: str
) -> Dict[str, Any]:
    """Best-effort coerce of path | JSON string | dict → dict ({} when empty)."""
    if arg is None:
        return {}
    if isinstance(arg, dict):
        return arg
    try:
        text = str(arg)
        p = Path(text)
        if p.exists() and p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
        return json.loads(text)
    except Exception as exc:
        logger.warning("notifier: could not parse %s (%s); using {}", name, exc)
        return {}


def send_telegram(message: str, dry_run: bool = False) -> bool:
    """Send ``message`` via the Telegram Bot API (stdlib ``urllib`` only).

    Returns True on HTTP-200 + Telegram ``ok:true``; False when credentials
    are missing (warning logged) or delivery fails. Never raises for those
    cases. ``dry_run=True`` validates credentials presence without sending
    and returns True when creds exist (False otherwise).
    """
    if not isinstance(message, str) or not message.strip():
        raise ValueError("message must be a non-empty string")
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        logger.warning(
            "notifier: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set; "
            "message not sent (%d chars)", len(message))
        return False
    if dry_run:
        logger.info("notifier: dry_run — credentials present, message not sent")
        return True
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message[:MAX_MESSAGE_CHARS],
    }).encode("utf-8")
    url = TELEGRAM_API_TEMPLATE.format(token=token)
    try:
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = getattr(resp, "status", 200)
        try:
            ok = bool(json.loads(body).get("ok", False)) and status == 200
        except Exception:
            ok = status == 200
        if not ok:
            logger.warning("notifier: telegram API non-ok response: %s", body[:300])
        return ok
    except Exception as exc:
        logger.warning("notifier: telegram send failed: %s", exc)
        return False


def _fmt_pct(x: Any) -> str:
    try:
        return f"{float(x) * 100:.1f}%" if abs(float(x)) <= 1.5 else f"{float(x):.1f}%"
    except Exception:
        return "n/a"


def _fmt_ret(x: Any) -> str:
    try:
        return f"{float(x) * 100:+.2f}%"
    except Exception:
        return "n/a"


def _collect_failures(health: Dict[str, Any]) -> List[str]:
    failures: List[str] = []
    try:
        actions = health.get("actions") or {}
        for stage, res in actions.items():
            if isinstance(res, dict):
                if res.get("error"):
                    failures.append(f"{stage}: {res['error']}")
                for sub in ("prune_decayed_signals", "monthly_distillation"):
                    inner = res.get(sub)
                    if isinstance(inner, dict) and inner.get("error"):
                        failures.append(f"{stage}.{sub}: {inner['error']}")
            elif isinstance(res, list):
                for item in res:
                    if isinstance(item, dict) and item.get("error") and not item.get("skipped"):
                        failures.append(f"{stage}@{item.get('date', '?')}: {item['error']}")
    except Exception:
        pass
    return failures


def format_nightly_digest(
    health_json_path: Union[str, Path, Dict[str, Any], None],
    validation_summary: Union[str, Path, Dict[str, Any], None] = None,
) -> str:
    """Build the 23:00 IST nightly digest text.

    Covers: pipeline stages (per-stage one-liners), checkpoint %
    (price-delivery coverage of the requested window when present),
    top-20 overlap (validation ``n``/universe when present), per-horizon
    hit-rates + IC, thesis hit-rate, and failures. Never raises.
    """
    try:
        health = _coerce_mapping(health_json_path, "health")
        val: Dict[str, Any] = _coerce_mapping(validation_summary, "validation_summary")
        # Validation summaries are sometimes wrapped: {"summary": {...}} or a list.
        if isinstance(val, dict) and not val.get("horizons") and "summary" in val:
            inner = val.get("summary")
            if isinstance(inner, dict):
                val = inner

        lines: List[str] = []
        today = health.get("today_ist", "?")
        lines.append(f"🌙 Reality Engine — nightly digest 23:00 IST ({today})")
        lines.append(f"mode={health.get('mode', '?')} dry_run={health.get('dry_run', '?')}")

        missing = health.get("missing_trading_days") or []
        lines.append(f"missing trading days: {len(missing)}"
                    + (f" ({', '.join(map(str, missing[:5]))})" if missing else ""))

        actions = health.get("actions") or {}
        if actions:
            lines.append("stages:")
            for stage in ("aux_feeds", "backfill", "distillation", "pruning",
                          "eod_corrections", "event_corrections"):
                res = actions.get(stage, "—")
                if isinstance(res, dict):
                    if res.get("skipped"):
                        lines.append(f"  • {stage}: skipped ({res.get('reason', '')})")
                    elif res.get("error"):
                        lines.append(f"  • {stage}: FAILED — {res['error']}")
                    else:
                        compact = {k: v for k, v in res.items()
                                   if k in ("sessions_ingested", "distilled", "ran",
                                            "symbols_corrected", "requested", "candidates")}
                        lines.append(f"  • {stage}: ok {json.dumps(compact, default=str)}")
                elif isinstance(res, list):
                    n_ok = sum(1 for i in res if isinstance(i, dict) and not i.get("error")
                               and not i.get("skipped"))
                    n_skip = sum(1 for i in res if isinstance(i, dict) and i.get("skipped"))
                    n_err = sum(1 for i in res if isinstance(i, dict) and i.get("error"))
                    lines.append(f"  • {stage}: {n_ok} ok / {n_skip} skipped / {n_err} failed")
                else:
                    lines.append(f"  • {stage}: {res}")
        else:
            lines.append("stages: n/a (no health data)")

        # Checkpoint % — price-delivery coverage if the health payload has it,
        # else backfill sessions vs requested as a rough proxy.
        ckpt = health.get("checkpoint_pct", health.get("checkpoint_percent"))
        if ckpt is None and isinstance(actions.get("backfill"), dict):
            bf = actions["backfill"]
            try:
                if bf.get("sessions_ingested") is not None and bf.get("requested"):
                    ckpt = float(bf["sessions_ingested"]) / float(bf["requested"])
            except Exception:
                ckpt = None
        lines.append(f"checkpoint: {_fmt_pct(ckpt) if ckpt is not None else 'n/a'}")

        horizons = val.get("horizons") or {}
        if horizons:
            lines.append(f"validation: {val.get('mode', '?')} asof={val.get('asof_date', '?')} "
                         f"regime={val.get('regime_tag', '?')} "
                         f"scored={val.get('n_scored', '?')}/{val.get('n_predictions', '?')}")
            for h in sorted(horizons, key=lambda x: int(x)):
                hs = horizons[h]
                lines.append(
                    f"  • H+{h}d: n={hs.get('n', '?')} "
                    f"hit={_fmt_pct(hs.get('hit_rate'))} "
                    f"top20={_fmt_ret(hs.get('mean_fwd_ret_top20'))} "
                    f"univ={_fmt_ret(hs.get('universe_mean_ret'))} "
                    f"IC={hs.get('ic') if hs.get('ic') is not None else 'n/a'}")
            if val.get("thesis_hit_rate") is not None:
                lines.append(f"  • theses: hit={_fmt_pct(val.get('thesis_hit_rate'))} "
                             f"(n={val.get('thesis_n', '?')})")
        else:
            lines.append("validation: n/a (no scores yet — needs prediction history + "
                         "forward prices; see harness docstring)")

        failures = _collect_failures(health)
        val_err = val.get("error") or val.get("note")
        if val_err and not horizons:
            failures.append(f"validation: {val_err}")
        lines.append("failures: " + ("none ✅" if not failures
                                     else "; ".join(failures[:8])))
        return "\n".join(lines)
    except Exception as exc:  # last-resort guard: digest must never crash callers
        logger.warning("notifier: digest formatting failed: %s", exc)
        return "🌙 Reality Engine — nightly digest unavailable (data error)."
