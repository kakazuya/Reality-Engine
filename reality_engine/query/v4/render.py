"""The v4 renderer (§D.4): one typed block per part, never prose over numbers.

``render`` prints a measured value with its unit, period, entity/ISIN, source and
``known_at``; an estimate with its method and inputs; a proxy with its
assumption, confidence, sources, ``search_log`` and approval; a NOT IN DATA block
with the four-gate wording (what was tried, what was checked, why, how to close).
``render_run`` adds the part counts the gate reads: ``real_answered`` and
``proxy_answered`` are separate, and an unapproved proxy or a typed NID is not an
answer.  The LLM's prose is allowed to connect these blocks and nothing else.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from .execute import answer_counts, approved_proxy, as_result


def _number(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return "—" if value is None else str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if abs(value) >= 1000:
            return f"{value:,.2f}"
        if abs(value) >= 1:
            return f"{value:.4f}".rstrip("0").rstrip(".")
        return f"{value:.6f}".rstrip("0").rstrip(".")
    return str(value)


def _entity(result) -> str:
    if result.isin:
        return str(result.isin)
    if result.entities:
        return f"{len(result.entities)} entities"
    return "market-wide"


def _source(result) -> str:
    return result.source_ref or "—"


def _known(result) -> str:
    return result.known_at or "—"


def _dims_text(row: Mapping[str, Any], result) -> str:
    """The row's dims the part did not name: a series must label what distinguishes rows."""
    asked = {str(key) for key in (result.dims or {})}
    extra = {str(key): value for key, value in (row.get("dims") or {}).items()
             if str(key) not in asked}
    return (" [" + " ".join(f"{key}={value}" for key, value in sorted(extra.items())) + "]"
            if extra else "")


def _assumed(result) -> str:
    return f"; assumption: {result.assumption}" if result.assumption else ""


def _measured(result) -> str:
    head = f"P{result.part_index + 1} measured — {_entity(result)}"
    label = result.measure or result.formula or "result"
    if result.shape == "ranked_list" or (result.entities and not result.isin
                                         and result.operator in
                                         ("rank", "screen", "compare", "join_entity_set")):
        rows = []
        for row in result.entities or []:
            rows.append(f"{row.get('rank') or '—'}. {row.get('entity_id')} "
                        f"{_number(row.get('value'))} {row.get('unit') or result.unit or ''}"
                        f" ({row.get('period') or '—'}, {row.get('source_ref') or _source(result)},"
                        f" known {row.get('known_at') or _known(result)})")
        return (f"{head} {label}: {len(rows)} entity(ies) — " + "; ".join(rows)
                + f"; known_at {_known(result)}")
    if result.shape == "passage":
        quotes = []
        for row in result.values[:5]:
            quote = str(row.get("quote") or "").strip()
            page = row.get("page_no")
            topic = row.get("topic") or ""
            quotes.append(f"{(topic + ': ') if topic else ''}{quote}"
                          f"{f' (p.{page})' if page else ''}")
        return (f"{head} {label}: " + " | ".join(quotes)
                + f"; source {_source(result)}; known_at {_known(result)}")
    if result.shape == "path":
        hops = "; ".join(
            f"hop {row.get('hop')}: {row.get('node')} → {row.get('target')} "
            f"({row.get('mechanism') or 'no mechanism'}, strength {row.get('strength')}, "
            f"known {row.get('known_at')})" for row in result.values)
        return (f"{head} {label}: {result.verdict or ''} — {hops}; "
                f"source {_source(result)}; known_at {_known(result)}")
    if result.shape == "verdict" or result.verdict is not None:
        numbers = ", ".join(f"{key}={_number(value)}"
                            for key, value in (result.numbers or {}).items()
                            if not isinstance(value, (list, dict)))
        return (f"{head} {label}: verdict {result.verdict}"
                f"{f' (rule: {result.rule_used})' if result.rule_used else ''}"
                f"{f'; numbers: {numbers}' if numbers else ''}; "
                f"period {result.period or '—'}; source {_source(result)}; "
                f"known_at {_known(result)}")
    if result.operator == "near_high":
        numbers = result.numbers or {}
        head_line = (
            f"{head} {label}: {_number(result.value)} {result.unit or ''} — threshold "
            f"{_number(numbers.get('threshold_pct'))}%, window "
            f"{numbers.get('window_from') or '—'}..{numbers.get('window_to') or '—'}, "
            f"{numbers.get('n_qualifying') or 0} of {numbers.get('n_sessions') or 0} "
            f"sessions, basis {numbers.get('basis') or _source(result)}, exchange "
            f"{numbers.get('exchange') or '—'}")
        if numbers.get("forward_sessions"):
            head_line += (f"; forward {numbers.get('forward_sessions')} sessions: "
                          f"complete {numbers.get('forward_complete')}, incomplete "
                          f"{numbers.get('forward_incomplete')}, winners "
                          f"{numbers.get('winners')}, losers {numbers.get('losers')}, "
                          f"flat {numbers.get('flat')}")
            if "mean_pct" in numbers:
                head_line += (f", mean {_number(numbers.get('mean_pct'))}%, median "
                              f"{_number(numbers.get('median_pct'))}%, min "
                              f"{_number(numbers.get('min_pct'))}%, max "
                              f"{_number(numbers.get('max_pct'))}%")
        sessions = []
        for row in result.values:
            text = (f"{row.get('period')} close {_number(row.get('close'))} "
                    f"high52 {_number(row.get('high_52w'))} dist "
                    f"{_number(row.get('distance_pct'))}%")
            if row.get("forward_pct") is not None:
                text += (f" fwd {row.get('forward_end')} "
                         f"{_number(row.get('forward_pct'))}%")
            elif row.get("forward_status"):
                text += f" fwd {row.get('forward_status')}"
            sessions.append(text)
        return (head_line + (f"; sessions: {'; '.join(sessions)}" if sessions else "")
                + f"; source {_source(result)}; known_at {_known(result)}{_assumed(result)}")
    if result.shape == "series":
        unit = result.unit or (result.values[0].get("unit") if result.values else None)
        shown = result.values
        suffix = ""
        if len(shown) > 15:
            shown = list(shown[:6]) + list(shown[-6:])
            suffix = f" … ({len(result.values) - 12} points elided)"
        points = "; ".join(
            f"{row.get('period')}={_number(row.get('value'))}{_dims_text(row, result)}"
            for row in shown)
        first = result.values[0].get("period") if result.values else "—"
        last = result.values[-1].get("period") if result.values else "—"
        return (f"{head} {label}: {len(result.values)} points {first}..{last} "
                f"[{points}]{suffix} {unit or ''}; source {_source(result)}; "
                f"known_at {_known(result)}")
    return (f"{head} {label}: {_number(result.value)} {result.unit or ''}"
            f"; period {result.period or '—'}; source {_source(result)}; "
            f"known_at {_known(result)}{_assumed(result)}")


def _estimate(result) -> str:
    inputs = result.inputs
    if isinstance(inputs, dict):
        inputs_text = ", ".join(f"{key}={_number(value)}" for key, value in inputs.items())
    elif isinstance(inputs, list):
        inputs_text = "; ".join(
            f"{item.get('atom') or item}" if isinstance(item, Mapping) else str(item)
            for item in inputs) or "none recorded"
    else:
        inputs_text = str(inputs) if inputs is not None else "none recorded"
    return (f"P{result.part_index + 1} estimate — {_entity(result)} "
            f"{result.measure or result.formula}: {_number(result.value)} "
            f"{result.unit or ''}; period {result.period or '—'}; "
            f"method {result.method or '—'}; inputs: {inputs_text}; "
            f"confidence {_number(result.confidence)}; source {_source(result)}; "
            f"known_at {_known(result)}")


def _proxy(result) -> str:
    approved = approved_proxy(result)
    state = f"approved_by {result.approved_by}" if approved else (
        "NOT APPROVED / no search_log ref — does not count as answered")
    sources = ", ".join(result.sources) or "—"
    return (f"P{result.part_index + 1} proxy — {_entity(result)} "
            f"{result.measure or result.formula}: {_number(result.value)} "
            f"{result.unit or ''}; period {result.period or '—'}; "
            f"assumption: {result.assumption or '— (a proxy without an assumption is a ticket)'}; "
            f"confidence: {_number(result.confidence)}; sources: {sources}; "
            f"search_log: {result.search_log or '—'}; {state}")


def _tried_text(result) -> str:
    items = []
    for item in result.tried or []:
        rows = item.get("rows_after_pit")
        rows_text = f"{rows} rows after PIT" if rows is not None else "not queried"
        items.append(f"{item.get('store') or '?'}: {item.get('query') or ''} "
                     f"({rows_text} at {item.get('at') or '—'})")
    return "; ".join(items) or "none — this is not a triaged NOT IN DATA"


def _checked_text(result) -> str:
    if result.checked:
        return "; ".join(f"{item.get('store')}: {item.get('rows_after_pit')} rows"
                         for item in result.checked)
    stores: dict[str, Any] = {}
    for item in result.tried or []:
        store = str(item.get("store") or "?")
        stores[store] = item.get("rows_after_pit")
    return "; ".join(f"{store} ({'absent' if rows is None else f'{rows} rows after PIT'})"
                     for store, rows in stores.items()) or "no store recorded"


def _not_in_data(result) -> str:
    fact = result.measure or result.formula or "the asked fact"
    return (f"P{result.part_index + 1} not_in_data — NOT IN DATA: {fact} — "
            f"Tried: {_tried_text(result)} — Checked: {_checked_text(result)} — "
            f"Why: {result.nid_reason or 'no reason recorded'} — "
            f"To close: {result.to_close or 'no closing action recorded'}")


BLOCKS = {"measured": _measured, "estimate": _estimate, "proxy": _proxy,
          "not_in_data": _not_in_data}


def render(result: Any) -> str:
    """One block for one result, its type always printed first."""
    r = as_result(result)
    block = BLOCKS.get(str(r.answer_type))
    if block is None:
        return (f"P{r.part_index + 1} invalid — answer_type {r.answer_type!r} is not one "
                f"of measured|estimate|proxy|not_in_data")
    return block(r)


def render_run(results: Iterable[Any], *, question: str | None = None,
               as_of: str | None = None, assumption: str | None = None) -> str:
    """The whole answer: the contract counters, then one block per part in order."""
    rows = sorted((as_result(result) for result in results),
                  key=lambda item: item.part_index)
    counts = answer_counts(rows)
    header = []
    if question:
        header.append(f"Question: {question}")
    if as_of:
        header.append(f"As of: {as_of}")
    if assumption:
        header.append(f"Assumption: {assumption}")
    header.append(
        f"Parts: {counts['parts']} · real_answered: {counts['real_answered']} · "
        f"proxy_answered: {counts['proxy_answered']} · "
        f"not_answered: {counts['not_answered']}"
        + (f" (unapproved proxy debt: {counts['unapproved_proxy']})"
           if counts["unapproved_proxy"] else "")
        + f" · case_answered: {'yes' if counts['case_answered'] else 'no'}")
    body = [render(result) for result in rows]
    return "\n".join(header + [""] + body) + "\n"


def answer_contract(results: Sequence[Any] | Iterable[Any]) -> dict[str, Any]:
    """The per-part contract block the gate stores with a v4 answer."""
    rows = sorted((as_result(result) for result in results),
                  key=lambda item: item.part_index)
    counts = answer_counts(rows)
    counts["parts_detail"] = [
        {"part_index": row.part_index,
         "measure": row.measure or row.formula,
         "answer_type": row.answer_type,
         "approved": approved_proxy(row),
         "counted": counts_as(row)}
        for row in rows]
    return counts


def counts_as(result: Any) -> bool:
    """Whether the block counts as an answered part (§D.4)."""
    r = as_result(result)
    if r.answer_type in ("measured", "estimate"):
        return True
    return approved_proxy(r)
