"""Split one master-bank case into sub-questions, deterministically.

A question may ask two things ("... and did the stock absorb it?") and a rubric
may spell out the steps ("compute X -> find Y -> show Z").  The query layer runs
each sub-question through ``router.route`` on its own, so an answer that covers
only one half is no longer ``ANSWERED`` (the strict grader in
``tasks/answer_bench/grade_v1.py`` reads the same split).

Rules, in order (no model, no question-text routing):

1. Split the question at top-level conjunctions (``;`` or ``and`` before an ask
   opener such as *did / how / what / which / was*).  A list "receivables and
   inventory" stays one clause because *inventory* is not an ask opener.
2. If the question yields one clause and the rubric has two or more
   ``required_steps``, those steps are the sub-questions.
3. Rubric steps are otherwise attached to the nearest sub-question as metadata
   (they explain the working, not a second user ask).
4. A later sub-question that says *it / the stock / the shares* and names no
   entity depends on the previous sub-question; the answer supplies the entity
   (the ranking winner) at run time.

``sub_case`` builds the case variant each sub-question is routed on.  The
caller (``answer.py``) fills ``picked`` with the previous sub-question's leading
row so "did the stock absorb it?" is priced on the stock the ranking picked.
"""
from __future__ import annotations

import re
from typing import Any

from .gate import asked_concepts
from .router import APPEND_CONCEPTS, CONCEPT_PHRASE, implied_ask, metric_of, named_document

MAX_SUBS = 3

ASK = ("did", "does", "do", "was", "were", "is", "are", "has", "have", "had", "how", "what",
       "which", "who", "whom", "whose", "why", "where", "whether", "when", "can", "could",
       "should", "will", "would", "kaun", "kya", "kitna", "kitni", "kitne")
SPLIT = re.compile(r"\s*;\s*|\s*,?\s+and\s+(?=(?:" + "|".join(ASK) + r")\b)|\?\s+(?=and\b)",
                   re.I)
RANKING = re.compile(r"\b(which (?:companies|large|mid|small|stocks|names|sector|sectors|index|"
                     r"indices|one)|rank|top \d+|biggest|largest|highest|most|least|worst|best)\b",
                     re.I)
ANAPHOR = re.compile(r"\b(the stocks?|the shares?|the counter|that stock|that name|"
                     r"which stock|the company's stock)\b", re.I)
REACTION = re.compile(r"\b(absorb|reaction|react|respond|response|moved?|held up|recover|"
                      r"performance|price/volume)\b", re.I)
STEP_SPLIT = re.compile(r"\s*(?:->|→|\n|;\s*|\d[).]\s+)\s*")
STOP = set("""the and for with that this from have has had was were are been been its
their there about would could should what which when where how why did does all any
show list compute state note flag map classify measure identify compare mark per
into over under between within during also then than as at of on in to a an it
""".split())


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z]{3,}", text.lower()) if w not in STOP]


def _has_ask(text: str) -> bool:
    return bool(re.search(r"\b(?:" + "|".join(ASK) + r")\b", text, re.I))


def _clean(text: str) -> str:
    text = re.sub(r"^\s*(?:and|but|also|then)\b\s*", "", text.strip(), flags=re.I)
    return re.sub(r"\s+", " ", text).strip(" .;:?")


def _steps(case: dict) -> list[str]:
    rubric = case.get("rubric") or {}
    raw = rubric.get("required_steps") if isinstance(rubric, dict) else None
    if not raw:
        return []
    if isinstance(raw, str):
        parts = STEP_SPLIT.split(raw)
    elif isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict):
                text = item.get("step") or item.get("text") or item.get("description") or ""
            else:
                text = str(item)
            parts.extend(STEP_SPLIT.split(text))
    else:
        return []
    return [part for part in (_clean(p) for p in parts)
            if len(re.findall(r"[A-Za-z]{3,}", part)) >= 2]


def _split_question(question: str) -> list[str]:
    clauses = [c for c in (_clean(p) for p in SPLIT.split(question or "")) if c]
    clauses = [c for c in clauses if len(_words(c)) >= 2 or len(c) >= 12]
    if len(clauses) > MAX_SUBS:
        clauses = clauses[:MAX_SUBS - 1] + ["; ".join(clauses[MAX_SUBS - 1:])]
    return clauses or [_clean(question or "")]


def _overlap(step: str, sub: str) -> int:
    return len(set(_words(step)) & set(_words(sub)))


def _routing_text(text: str, case: dict) -> str:
    """The sub-question as the router reads it: name the implied metric."""
    augmented = text
    if metric_of(augmented)[0] is None and REACTION.search(augmented):
        augmented += " price return"
    if re.search(r"\bdeal date\b", text, re.I):
        augmented += " event"
    return augmented


def decompose(case: dict) -> list[dict[str, Any]]:
    """The case's sub-questions (each with its own routing text and dependency)."""
    question = str(case.get("question") or "")
    clauses = _split_question(question)
    steps = _steps(case)
    if len(clauses) == 1 and len(steps) >= 2:
        clauses = steps[:MAX_SUBS]
        steps_used, steps = steps, []
    else:
        steps_used = []
    subs: list[dict[str, Any]] = []
    for index, text in enumerate(clauses):
        subs.append({"index": index, "text": text, "from": "rubric" if steps_used else "question",
                     "routing_text": _routing_text(text, case), "steps": []})
    if steps and subs:
        for step in steps:
            best = max(subs, key=lambda sub: _overlap(step, sub["text"]))
            best["steps"].append(step)
    parent_concepts = asked_concepts(question + " " + str(case.get("period") or ""))
    for index, sub in enumerate(subs):
        previous_is_ranking = bool(index) and bool(RANKING.search(subs[index - 1]["text"]))
        dependent = (bool(index) and previous_is_ranking and ANAPHOR.search(sub["text"]) and
                     not re.search(r"\b[A-Z][A-Z0-9&\-]{2,}\b", sub["text"]))
        sub["entity_from"] = index - 1 if dependent else None
        sub["universe"] = bool(RANKING.search(sub["text"])) and \
            str(case.get("entity_level") or "stock") != "stock"
        sub["named_document"] = named_document({"question": sub["text"]})
        # A short sub-question that names no concept takes the ask its family /
        # template implies ("which one was worst" -> price return); a sub that
        # names one half of a two-concept ask also carries the other, because the
        # run is judged against the whole ask.  The phrases go into the text the
        # planner AND the gate read, so both see the same asks.
        hints = [hint] if (hint := implied_ask(sub["text"], case)) else []
        named = set(asked_concepts(" ".join([sub["text"], *hints])))
        for concept in parent_concepts:
            phrase = CONCEPT_PHRASE.get(concept)
            if concept in named or concept not in APPEND_CONCEPTS or not phrase or \
                    len(hints) >= 3:
                continue
            hints.append(phrase)
            named |= set(asked_concepts(phrase))
        if hints:
            sub["text"] = f"{sub['text']} ({', '.join(hints)})"
            sub["routing_text"] = f"{sub['routing_text']} ({', '.join(hints)})"
        sub["metric"] = metric_of(sub["routing_text"])[0]
    return subs


DOC_PHRASE = {"deck": "investor presentation", "transcript": "transcript",
              "ar": "annual report", "announcement": "announcement"}


def sub_case(case: dict, sub: dict[str, Any], picked: dict[str, Any] | None = None) -> dict:
    """The case variant one sub-question is routed on."""
    variant = dict(case)
    variant["question"] = sub["routing_text"]
    ok = sub["index"] == 0
    # A later sub-question of a "per its <doc> of <date>" question is still about
    # that document: carry the named document into its routing text.
    parent_doc = named_document({"question": str(case.get("question") or "")})
    if not ok and parent_doc and not sub.get("named_document"):
        variant["question"] = (f"{sub['routing_text']} (per its "
                               f"{DOC_PHRASE.get(parent_doc['doc_type'], parent_doc['doc_type'])} "
                               f"of {parent_doc['date']})")
    # Later sub-questions must not inherit the parent's family/template/metric
    # hints: their own question carries what they ask.
    variant["family"] = list(case.get("family") or []) if ok else []
    variant["template"] = case.get("template") if ok else None
    variant["archetype"] = case.get("archetype") if ok else None
    if not ok:
        variant["answer_kind"] = None
    variant["rubric"] = dict(case.get("rubric") or {}) if ok else {}
    variant["entities"] = list(case.get("entities") or [])
    if sub.get("entity_from") is not None and picked and picked.get("symbol"):
        variant["entities"] = [{"symbol": picked["symbol"], "isin": picked.get("isin")}]
        # One picked entity: this is a single-stock follow-up, not the parent's
        # market-cap-bucket screen.
        variant["entity_level"] = "stock"
    elif sub.get("universe"):
        variant["entities"] = []
    return variant
