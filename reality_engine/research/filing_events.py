"""T-231: the filing-level event table -- one dated, quantified corporate event per announcement, per class.

The factor study needs events an investor can date: an order won, a capex approved, capacity commissioned, a fund
raise approved or allotted.  T-228's generic claim extractor read every transcript and annual report and got 18 of
50 verified rows wrong, mostly a fact restated across calls or a parent-company fact filed under a subsidiary.  An
exchange announcement is filed once, on one day, and carries the event itself, so this module builds the table from
``doc_type='announcement'`` and, since T-242 (24 Nov 2026), ``doc_type='press_release'`` (``EVENT_DOC_TYPES``):
the universe stores file some order wins as a press release (4 of 1,188 page-1 texts in full394 read as one).

Rules, each from the 91 measured stores (T-228 stage 2c) or the brief:
* classification is deterministic, on the exchange title plus the first page: a cue word per class, and the cue
  that fired is kept in ``why``.  A board-meeting intimation ("to consider fund raising") is not a raise; an
  outcome that states the approved size is.  A court/tax/regulator order is not an order win (``pilot3.order_wins``
  already draws that line).
* the fields are parsed by script: order wins reuse ``pilot3.order_wins.parse`` (the prescribed Regulation 30
  table and its headline form); capex approval, capacity commissioned and fund raise use the shapes exchanges
  print below, widened past ``driver_claims.announcement_claims`` (which filled 67 filings across the 91).
* every figure carries the exact printed text and page it came from (``value_text``, ``page``, ``quote``).
* only when a classified filing's required number is not printed in a form the script fills, the first two pages
  go once to ``hy4-flash-free`` with a strict JSON schema.  The same printed-text check applies; such rows are
  ``method='model'``.  ``--no-model`` turns that pass off.
* one row per (announcement, class); a filing that bundles items keeps at most one row per class.
* an addendum/corrigendum that names an earlier filing is linked in ``amend``, never emitted as a new event.
* a document labelled a parent/ultimate-holding-company release is kept but ``entity_scope='parent'``: it is
  never the subsidiary's event.
* ``status``: verified (every field printed, script or model, scope company), unverified (a field inferred, an
  amount not filled, or a parent-scope row), quarantined (the value is not on the page).  ``known_at`` always
  comes from ``doc``, never from the model.

Reads the stores at ``T228_STORE_ROOT`` (default ``D:/RealityEngine/tg_build/measure10``) read-only and writes
only ``--out``.  CLI::

    python -m reality_engine.research.filing_events --out .tmp/t231/events.db
    python -m reality_engine.research.filing_events --stores c01 c08 --limit 200 --no-model
    python -m reality_engine.research.filing_events --report .tmp/t231/events.db --report-file .tmp/t231/report_a.md
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from reality_engine.pilot3 import order_wins
from reality_engine.research.driver_claims import (
    Client,
    MODEL,
    MODEL_BODY,
    find_numbers,
    matches_value,
    norm_ws,
    retry_after_of,
    store_path,
)

KINDS = ("order_win", "order_amendment", "capex_approval", "capacity_commissioned", "fund_raise")
DEFAULT_OUT = Path(".tmp/t231/events.db")
DEFAULT_REPORT = Path(".tmp/t231/report_a.md")
DEFAULT_CACHE = Path(".tmp/t231/model_cache.json")
PAGES = 4                    # first pages read (classification and parse; annexure tables carry the size)
MAX_MODEL_CHARS = 20000      # first four pages sent to the model
MAX_QUOTE = 400              # characters of printed context kept on a row
MODEL_STOP_SHARE = 0.30      # brief: more than 30% of non-model-first classified filings needing the model stops
ERROR_STOP_SHARE = 0.05      # T-242: stop if hy4 returns errors on >5% of requests
QUARANTINE_STOP_SHARE = 0.10
MAX_RETRIES = 3
MAX_RETRY_WAIT_S = 900.0
MODEL_FIRST_KINDS = frozenset({"order_win", "fund_raise"})
EVENT_PROMPT_VERSION = "v1"

# ------------------------------------------------------------------ cues
_INTIMATION = re.compile(
    r"\bto\s+consider\b|\bwill\s+consider\b|meeting\s+(?:of\s+the\s+board\s+)?is\s+scheduled"
    r"|scheduled\s+to\s+be\s+held\b|\bboard\s+meeting\s+intimation\b", re.I)
_DONE = re.compile(
    r"considered\s+and\s+approved|has\s+approved|have\s+approved|accorded\s+(?:its\s+)?approval"
    r"|approved\s+the|\ballotted\b|\braised\b|\bsubscribed\b|\bissue\s+(?:has\s+)?(?:opened|closed)\b", re.I)

# capex approval: the board sanctions a spend, and the amount is printed in the same clause.
_CAPEX_CUE = re.compile(
    r"\b(?:capital\s+expenditure|capex|expansion|brownfield|greenfield|new\s+(?:plant|unit|line|facility)"
    r"|setting\s+up\s+(?:of\s+)?(?:a|an|the|its)?\s*(?:new\s+)?(?:plant|unit|line|facility|capacity)"
    r"|project\s+cost|estimated\s+(?:cost|investment))\b", re.I)
_APPROVE = re.compile(r"\b(?:approved|approves|approving|approval|sanctioned|sanction|accorded)\b", re.I)
_CAPEX_AMOUNT_CUE = re.compile(
    r"(?:estimated\s+cost|project\s+cost|total\s+cost|investment\s+of|capital\s+expenditure\s+of|capex\s+of"
    r"|at\s+a\s+cost\s+of|amounting\s+to)\b", re.I)
_COMPLETION = re.compile(
    r"(?:complet\w*|commission\w*|operational\w*|ready)\s*(?:by|in|during|within)\s*(?:the\s+)?(?:end\s+of\s+)?"
    r"(?:Q[1-4]\s*)?(?:FY\s?\d{2}|(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{4}|\d{4})", re.I)

# capacity commissioned: a line starts producing (past/complete -- never an EPC scope of "supply, erection,
# testing and commissioning"), and the capacity it adds is printed beside it.
_COMM_VERB = re.compile(
    r"\b(?:commissioned|commissions|commissioning\s+of"
    r"|commenced\s+(?:commercial\s+)?(?:operations?|production)"
    r"|commencement\s+of\s+(?:commercial\s+)?(?:operations?|production)"
    r"|commercial\s+(?:production|operations?)\s+(?:has\s+|have\s+)?commenc\w*"
    r"|begins?\s+commercial\s+operations?"
    r"|COD\b|started\s+(?:commercial\s+)?(?:production|operations?)"
    r"|put\s+to\s+use|synchroni[sz](?:ed|ation))\b",
    re.I,
)
_CAPACITY_CUE = re.compile(
    r"\b(?:has\s+been\s+commissioned|successfully\s+commissioned|successful\s+commissioning\s+of"
    r"|commissioning\s+of|commissioned|commissions"
    r"|commercial\s+(?:production|operations?)\s+(?:has\s+|have\s+)?commenc\w*"
    r"|commenced\s+(?:commercial\s+)?(?:operations?|production)"
    r"|commencement\s+of\s+(?:commercial\s+)?(?:operations?|production)"
    r"|begins?\s+commercial\s+operations?|COD\b"
    r"|started\s+(?:commercial\s+)?(?:production|operations?)|put\s+to\s+use|synchroni[sz](?:ed|ation)"
    r"|capacity\s+(?:addition|added|enhancement)|capacity\s+(?:has\s+been\s+)?(?:enhanced|expanded|added)"
    r"|enhancement\s+of\s+capacity|new\s+(?:plant|line|unit|facility)[^.]{0,60}(?:operational|commissioned|inaugurated)"
    r"|inaugurated\s+(?:its|the|a)\b)", re.I)
# "supply, erection, testing and commissioning" is a contract's scope of work, not a completed capacity.
_CAPACITY_VETO = re.compile(
    r"erection[^.]{0,60}commissioning|commissioning\s+of\s+(?:each|the|a)\s+(?:transmission|line|project|package)"
    r"|scope\s+of\s+work|testing\s*(?:&|and)\s*commissioning", re.I)
_CAPACITY_REJECT_CLAUSE = re.compile(
    r"\bfoundation\s+stone\b|\bbhoomi\s+pujan\b|\bground[\s-]?breaking\b|\bacquisition\b|\bacquired\b", re.I)
# "expected to be commissioned", "scheduled to become operational": a plan, not a completed commissioning.
_CAPACITY_FORWARD = re.compile(
    r"\b(?:expected|estimated|scheduled|targeted|proposed|planned|plan\s+to|will\s+be|to\s+be)\b[^.;]{0,70}?"
    r"\b(?:commission\w*|operational|installed|complete\w*)|"
    r"\b(?:commission\w*|operational)\b[^.;]{0,40}?\b(?:expected|estimated|scheduled|targeted)\b", re.I)
_CAP_UNIT_RX = (
    r"MWp|kWp|MW|megawatts?|kW|kilowatts?|GW|gigawatts?|MMTPA|MTPA|TPA|TPD|MT"
    r"|tonnes?\s+per\s+annum|tons?\s+per\s+annum|lakh\s+tonnes"
    r"|million\s+(?:tonnes|tons|units|pieces)(?:\s+per\s+annum)?"
    r"|tonnes?|tons?|KL|kilolitres?|units?|pieces(?:\s+per\s+annum)?"
)
_CAPACITY_VALUE = re.compile(
    r"(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>" + _CAP_UNIT_RX + r")\b", re.I)
_CAPACITY_UNIT = {
    "mw": "mw", "mwp": "mwp", "megawatt": "mw", "megawatts": "mw",
    "kw": "kw", "kwp": "kwp", "kilowatt": "kw", "kilowatts": "kw",
    "gw": "gw", "gigawatt": "gw", "gigawatts": "gw",
    "mmtpa": "mmtpa", "mtpa": "mtpa", "tpa": "tpa", "tpd": "tpd", "mt": "mt",
    "tonnes per annum": "tpa", "tons per annum": "tpa",
    "lakh tonnes": "lakh_tonnes",
    "million tonnes": "mt", "million tons": "mtpa",
    "million tonnes per annum": "mtpa", "million tons per annum": "mtpa",
    "million units": "mn_units", "million pieces": "mn_pieces", "million pieces per annum": "mn_pieces",
    "tonne": "tpa", "tonnes": "tpa", "ton": "tpa", "tons": "tpa",
    "kl": "kl", "kilolitre": "kl", "kilolitres": "kl",
    "unit": "units", "units": "units", "pieces": "pieces", "pieces per annum": "pieces",
}
_CAPACITY_TO_FROM = re.compile(
    r"(?P<new>\d[\d,]*(?:\.\d+)?)\s*(?P<u>" + _CAP_UNIT_RX + r")[^.;]{0,30}?\bfrom\s+"
    r"(?P<old>\d[\d,]*(?:\.\d+)?)", re.I)
_CAPACITY_FROM_TO = re.compile(
    r"\bfrom\s+(?P<old>\d[\d,]*(?:\.\d+)?)[^.;]{0,30}?\bto\s+(?P<new>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<u>" + _CAP_UNIT_RX + r")", re.I)
_PLANT = re.compile(
    r"\b(?:at|in)\s+(?:its|the|our)?\s*(?P<name>[A-Z][A-Za-z0-9&.'’\-]*(?:\s+[A-Z][A-Za-z0-9&.'’\-]*){0,4})")

# fund raise: a board approval or a completed allotment, never a "to consider" intimation.
_RAISE_CUE = re.compile(
    r"\b(?:QIP|qualified\s+institutions?\s+placement|preferential\s+(?:issue|allotment|offer)|warrants?"
    r"|rights\s+issue|non[-\s]?convertible(?:\s*,?\s*(?:non[-\s]?cumulative|cumulative|redeemable|secured|unsecured"
    r"|listed|unlisted|rated|unrated|taxable|senior|subordinated))*[,\s]+debentures?|\bNCDs?\b"
    r"|fund\s*[- ]?rais\w+|raising\s+of\s+funds"
    r"|issuance\s+of\s+(?:up\s+to\s+)?\d[\d,]{3,}|issuance\s+of\b[^.]{0,80}?(?:equity\s+)?shares"
    r"|issue\s+of\s+(?:[\d,]+\s+)?(?:equity\s+)?shares"
    r"|allotment\s+of\s+(?:[\d,]+\s+)?(?:equity\s+)?shares"
    r"|\bborrowings?\b)\b", re.I)
_RAISE_ISSUANCE = re.compile(
    r"\b(?:rais(?:e|ing|ed)|issu(?:e|ing|ed|ance)|allot(?:ted|ting|ment)?|QIP|qualified\s+institutions?\s+placement"
    r"|preferential|rights\s+issue|rights\s+basis|private\s+placement\s+of\s+(?:NCDs?|non[-\s]?convertible\s+debentures?))\b",
    re.I)
_RAISE_DEBT_VETO = re.compile(
    r"\b(?:(?:partial|early|full|final|premature)\s+)?redemption\b|\bredeemed\b|\bcall\s+option\b|\bput\s+option\b"
    r"|\bcovenants?\b|\b(?:debenture|bond)\s+trust\s+deed\b"
    r"|\b(?:amendment|modification)\s+(?:in|of|to)\s+(?:the\s+)?(?:clauses|terms|covenants)\b"
    r"|\b(?:certificate\s+regarding\s+)?payment\s+of\s+interest\b|\binterest\s+payment\b"
    r"|\brecord\s+date\s+for\s+(?:interest|redemption)\b", re.I)
_RAISE_DONE = re.compile(
    r"\b(?:allotted|allotment|allotting|raised|subscribed|sanctioned|issued|issuing|issuance|opened|closed"
    r"|concluded|completed)\b", re.I)
_SIZE_CUE = re.compile(
    r"(?:aggregat\w*|amount\w*|issue\s+size|\bsize\b|raising|raise|up\s*to|upto|of)\s*(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)\b", re.I)
_RS_AMOUNT = re.compile(
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|millions?|mn|billions?|bn)\b",
    re.I)
# a full rupee figure ("Rs. 28,59,32,004/-") is a printed amount in crore after /1e7.
_RS_FULL = re.compile(
    r"(?:Rs\.?|INR|₹)\s*(?P<v>\d{1,3}(?:,\s*\d{2,3}){2,}(?:\.\d+)?|\d{7,}(?:\.\d+)?)(?:\s*/-)?", re.I)
_USD_AMOUNT = re.compile(
    r"(?:\bUSD|\bUS\s?\$|\$)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>millions?|mn|billions?|bn)\b", re.I)
# a "fund raise" in an agency disclaimer or a SEBI framework circular is not the company raising money.
_RAISE_VETO = re.compile(
    r"framework\s+for\s+fund\s*raising|large\s+corporates|credit\s+rating|rating\s+(?:action|revision|rationale)"
    r"|the\s+exchange\s+has\s+received\s+the\s+disclosure|disclosure\s+(?:received|under).{0,80}"
    r"(?:SAST|takeover|regulation\s+(?:29|31|18))|u/r\s*7\(2\)|insider\s+trading"
    r"|statement\s+of\s+deviation|utilisation|utilization|\bdeviation\b"
    r"|\bESOPs?\b|\bESOS\b|employee\s+stock\s+options?|stock\s+options?|employee\s+benefit|share\s+based\s+employee"
    r"|sweat\s+equity|\bRSUs?\b|restricted\s+stock"
    r"|open\s+offer|pre[-\s]offer|manager\s+to\s+the\s+offer|takeover"
    r"|exploring|to\s+consider|proposal\s+to|enabling\s+resolution"
    r"|borrowing\s+limits?|limit\s+of\s+borrowings?|increase\s+in\s+(?:the\s+)?borrowing", re.I)
_RAISE_OUTBOUND_VETO = re.compile(
    r"\b(?:shall\s+)?subscrib(?:e|ed|ing)\s+to\b"
    r"|\binvest(?:ing|ed|s)?\s+(?:~?\s*(?:Rs\.?|INR|₹)[^.]{0,40}\s+)?(?:in|into)\s+"
    r"(?!such\s+issu|the\s+(?:issue|offer|qip|rights|securities|equity\s+shares))"
    r"|\bfor\s+an\s+investment\s+of\b"
    r"|\bacquir(?:e|ed|ing)\s+(?:stake|equity|shares)\s+in\b"
    r"|\bacquisition\s+of\s+(?:equity\s+)?shares\s+in\b"
    r"|\bshare\s+subscription\s+and\s+shareholders\s+agreement\b"
    r"|\btarget\s+company\b",
    re.I,
)
# T-242 round 7: a fund_raise needs the LISTED company as ISSUER.  A subscription to or investment in
# another entity's securities, an acquisition of another company's shares (cash or swap), a loan granted to
# a subsidiary, a sale/divestment of a stake and a security that is another company's are never the
# company's own issue, whatever the title says (#10, #14, #24, #29, #33, #38, #50).
_RAISE_FOREIGN_ISSUE_VETO = re.compile(
    r"\bsubscri(?:be|bed|ption|bing)\s+to\b[^.]{0,100}?\b(?:rights|preferential|public|further)\s+"
    r"(?:issue|offer)\s+of\b(?!\s*(?:the\s+Company|our\s+Company|equity\s+shares|shares|securities))"
    r"|\b(?:subsidiar(?:y|ies)|associate(?:\s+compan(?:y|ies))?|joint\s+venture)\b[^.]{0,200}?"
    r"\b(?:has|have|had|is|was)\b[^.]{0,60}?\ballot(?:ted|ment\s+of)\b"
    r"|\bstrategic\s+investment\b[^.]{0,120}\bacquisition\b"
    r"|\bstrategic\s+sale\b|\bsale\s+of\b[^.]{0,80}\bto\b"
    r"|\bacquisition\s+of\s+[\d,]{3,}\s*(?:\([^)]*\)\s*)?(?:equity\s+)?shares\b"
    r"|\bdivest(?:ed|ment|s|ing)?\b[^.]{0,80}\b(?:stake|shareholding|subsidiar(?:y|ies)|business)\b"
    r"|\bsale\s+of\b[^.]{0,60}\b(?:stake|shareholding)\b"
    r"|\bissuance\s+of\s+(?!the\s+Company\b|Company\b)(?-i:[A-Z])[\w&.'’\-]*"
    r"(?:\s+(?-i:[A-Z])[\w&.'’\-]*)?['’]s\s+(?:\w+\s+){0,4}(?:CCPS|CCDs?|shares?|securities|warrants?)\b"
    r"|\bloan\s+agreement\b|\bunsecured\s+loan\b|\bgrant(?:ed|ing|s)?\s+(?:an?\s+)?(?:unsecured\s+)?loan\b"
    r"|\bco[-\s]?invest\b|\bequity\s+investments?\b|\bright\s+to\s+invest\b"
    r"|\binvest(?:ed|ing|s)?\b[^.]{0,200}?\bin\b[^.]{0,20}?(?-i:[A-Z])[\w&.'\-]*\s+"
    r"(?:Private|Limited|Pvt|LLP|Ltd)\b"
    r"|\binvestments?\s+in\b[^.]{0,60}?(?-i:[A-Z])[\w&.'\-]*\s+(?:Private|Limited|Pvt|LLP|Ltd)\b",
    re.I,
)
# T-242: a kind enters VERIFIED_KINDS only after its own strict 60-row grade on stores NO fix was tuned on.
# ``order_win`` was gated after the 24 Nov fresh3 grade (25/5/0/0) but failed the 25 Nov grade on 40 untuned stores
# (fresh5, round 6: 39 R / 5 P / 14 W / 2 J), so since 25 Nov no kind is gated: every event is stored
# ``unverified`` (served labelled) until its kind passes a fresh-store grade.
# 26 Nov: ``order_win`` passed on the model-first r2 code (4a3c41b3), fresh9 = 40 full394 stores no round saw:
# Hydrogen 55/3/1/1, Wolf's own check 52 R / 3 W+J (a BOOT concession revenue stored as an order, row 47).
# ``fund_raise`` failed the same round (49/5/4/2: double counts, one tranche, a 100% warrant price) and stays out.
VERIFIED_KINDS: frozenset[str] = frozenset({"order_win"})
# a title naming the company's own QIP/NCD/preferential/rights issue is never vetoed by the agreement words below
# (the annexure of a genuine issuance also prints "sanction letter" / "facility" boilerplate).
_OWN_ISSUE_TITLE = re.compile(
    r"\bQIP\b|qualified\s+institutions?\s+placement|preferential\s+(?:issue|allotment|offer)"
    r"|rights\s+issue|non[-\s]?convertible\s+debentures?|\bNCDs?\b|\bfund\s*[- ]?rais\w*"
    r"|\braising\s+of\s+funds\b"
    r"|\b(?:issue|issuance|allotment)\s+of\s+(?:[\d,]{2,}\s+)?(?:equity\s+)?(?:shares?|warrants?|debentures?)\b",
    re.I)
# an agreement update is not a fund raise: a credit facility revised or surrendered, a warrant lapse or forfeiture,
# a stake bought in a subsidiary (fresh3 #16, #19, #21, #43, #45).
_RAISE_AGREEMENT_VETO = re.compile(
    r"\bcredit\s+facilit(?:y|ies)\b|\bfacilit(?:y|ies)\s+agreement\b"
    r"|\b(?:working\s+capital|term\s+loan|overdraft)\s+(?:facility|loan|limit)s?\b"
    r"|\b(?:sanction(?:ed|ing)?|sanction\s+letter)\b[^.]{0,40}\b(?:credit|facility|limit|loan|borrowing)\b"
    r"|\b(?:supplemental|amendatory|addendum)\b[^.]{0,80}\b(?:agreement|facility|loan)\b"
    r"|\blimits?\s+(?:stand\s+|stands\s+)?(?:enhanced|reduced|increased|revised|surrendered)\b"
    r"|\b(?:enhanc\w*|reduc\w*|reduction|revis\w*|surrender\w*)\b[^.]{0,30}"
    r"\b(?:credit\s+)?(?:facility|limit|sanction)s?\b"
    r"|\bforfeit\w*\b|\bnon[-\s]receipt\b|\bwarrants?\b[^.]{0,120}\blapse[ds]?\b"
    r"|\binvest\w*\b[^.]{0,60}\b(?:in|into)\b[^.]{0,40}"
    r"\b(?:wholly[-\s]owned|subsidiary|joint\s+venture|associate)s?\b"
    r"|\bsubscri(?:be|bed|ption)\b[^.]{0,60}\b(?:shares|equity)\b[^.]{0,20}\b(?:of|in)\b",
    re.I)
# T-242 round 5: the amount is THIS step's, never a sum of the angles it is printed from.  A clause that
# records an earlier step, a component of this step's consideration (the 25% upfront and the 75% balance of a
# warrant) or the capital before/after the issue is not this step (fresh4/fresh3 #10, #12, #13, #20, #32, #54,
# #57).  The prior-step and capital cues cut the clause at the cue (a genuine total often prints before them);
# a component cue rejects the clause whole (the component is usually printed before its own 25%/75% mark).
_RAISE_PRIOR_STEP = re.compile(
    r"\bhad\s+(?:already\s+)?(?:been\s+)?allotted\b|\bhad\s+raised\b"
    r"|\b(?:already|previously)\s+(?:allotted|raised|issued)\b"
    r"|\b(?:pertaining|informing)\s+(?:to|with\s+respect\s+to)\s+(?:the\s+)?allotment\s+of\b"
    r"|\bwith\s+respect\s+to\s+(?:the\s+)?allotment\s+of\b"
    r"|\b(?:in|since)\s+the\s+FY\s?\d{2,4}\b|\b(?:in|during|since)\s+(?:the\s+)?(?:financial\s+)?year\s+\d{4}\b"
    r"|\b(?:past|earlier|previous)\s+(?:year|issue|allotment|qip|round)\b", re.I)
_RAISE_COMPONENT = re.compile(
    r"\b(?:25|75)\s*(?:%|per\s*cent\b|percent\b)"
    r"|\bequivalent\s+amount\s+to\b|\bremaining\s+(?:exercise\s+price|consideration|amount|payment)\b"
    r"|\b(?:upfront|up-front)\s+(?:payment|consideration|amount|portion)\b", re.I)
# OCR splits a printed count ("1,27,93, 102"); join it so the share count and its total read whole
_RAISE_OCR_SPACE = re.compile(r"(?<=\d),\s+(?=\d{3}\b)")
_RAISE_CAPITAL = re.compile(
    r"\bpaid[-\s]?up\b[^.]{0,60}\b(?:share\s+)?capital\b|\bpre[-\s]?issue\b|\bpost[-\s]?issue\b"
    r"|\bauthori[sz]ed\s+(?:share\s+)?capital\b", re.I)
# a subsidiary's own allotment is not the listed company's issuance (fresh4 #19)
_RAISE_SUBSIDIARY_VETO = re.compile(
    r"\bsubsidiar(?:y|ies)\b[^.]{0,220}?\b(?:has|have|had)\b[^.]{0,80}?\ballotted\b", re.I)
# an exchange advisory or lock-in letter about an earlier issue is not an issuance (fresh4 #21)
_RAISE_ADVISORY_VETO = re.compile(
    r"\badvisory\s+(?:letter|note)\b|\b(?:warning|cautionary|observation)\s+letter\b"
    r"|\b(?:has|have)\s+received\s+an?\s+(?:advisory|warning|cautionary|observation)\b"
    r"|\badvised\s+(?:the\s+)?company\s+to\b|\block[-\s]?in\s+letter\b", re.I)
# "fund raising through debt" names no security: nothing was issued (fresh4 #43)
_RAISE_GENERIC_CUE = re.compile(r"\bfund\s*[- ]?rais\w*|\braising\s+of\s+funds\b", re.I)
_RAISE_SECURITY = re.compile(
    r"\bequity\b|\bshares?\b|\bQIP\b|qualified\s+institutions?|preferential|\brights\b|\bwarrants?\b|\bNCDs?\b"
    r"|non[-\s]?convertible|\bbonds?\b|debentures?|\bcommercial\s+paper\b|\bCPs?\b|\bconvertibles?\b"
    r"|\b(?:issuance|issue)\s+of\s+(?:[\w%]+\s+){0,3}securities\b", re.I)
_MARKET_CAP_CUE = re.compile(r"\bmarket\s+capitali[sz]ation\b|\bmarket\s+cap\b", re.I)
# A regulator's or a court's "order" is not a customer order.  The test is an order-shaped phrase, never the
# bare words GST/customs/tax: "excluding GST" is printed on every genuine order value (it cost BLKASHYAP 910 cr
# and JYOTISTRUC 105.57 cr their events in stage A).
_ORDER_VETO = re.compile(
    r"\b(?:high court|supreme court|tribunal|nclt|nclat|itat|cestat|court)\b"
    r"|\b(?:stay|closure|revocation|assessment|demand|penalty|appeal)\s+order\b"
    r"|\bincome[-\s]tax\b|\bGST\s+(?:demand|notice|order|appeal|penalty)\b"
    r"|\btax\s+(?:appeal|order|demand)\b"
    r"|show[\s-]cause|\bsummons\b|arbitration|insolvency|\bwrit\b|hon.{0,3}ble"
    r"|pollution\s+control\s+board|rumou?r|news\s+item|media\s+report|clarification\s+on\s+news"
    r"|no\s+new\s+order|penalty\s+charged|GST\s+(?:department|authority)"
    r"|\bDRC[-\s]?0?7\b|\bGoods\s+and\s+Services\s+Tax\s+Act\b|\b[CSI]?GST\s+Act\b"
    r"|\bDepartment\s+of\s+(?:Commercial|State|Central)\s+Taxes\b|\bCommercial\s+Taxes\b"
    r"|\bGST\s+(?:Audit\s+)?Authorit(?:y|ies)\b"
    r"|\b(?:demand|assessment|penalty|show[\s-]?cause|adjudication|rectification)\s+(?:order|notice)\b"
    r"|\b(?:tax|total)\s+demand\b|\braised\s+(?:a\s+)?(?:total\s+)?demand\b|\bdemand\s+of\s+(?:Rs\.?|INR|₹)"
    r"|\b(?:imposing|imposed|levied)\s+(?:a\s+)?penalty\b|\bpenalty\s+(?:amount\s+)?of\s+(?:Rs\.?|INR|₹)"
    r"|\border\b[^.]{0,60}\b(?:assessment|demand|penalty|show[\s-]?cause|adjudication|Section\s+73|Section\s+74|Section\s+129|DRC[-\s]?0?7)\b"
    r"|completion\s+of\s+(?:the\s+)?(?:project|order|work)\b", re.I)
_RESULTS_RELEASE = re.compile(
    r"\bresults?\s+(?:press|media)\s+release\b"
    r"|\b(?:press|media|investor)\s+release\b[^.]{0,180}\b(?:financial\s+results|quarterly\s+results|"
    r"Q[1-4]\s*(?:&|and)?\s*(?:9M|H[12])?\s*FY\s?\d{2}|(?:quarter|half\s+year|nine\s+months|year)\s+ended|"
    r"revenue\s+growth|financial\s+highlights)\b"
    r"|\b(?:Q[1-4]|H[12]|9M)\s*(?:&\s*(?:9M|H[12])\s*)?FY\s?\d{2}\s+"
    r"(?:press\s*(?:&|and)\s*media\s+release|investor\s+release|financial\s+highlights)\b"
    r"|\bannounced\s+its\s+(?:unaudited\s+|audited\s+|consolidated\s+|standalone\s+)?financial\s+results\b",
    re.I)
_ORDER_ROLLUP = re.compile(
    r"\b(?:orders?|contracts?)\s+(?:received|secured|won|bagged|awarded)\s+during\s+(?:the\s+)?"
    r"(?:quarter|year|financial\s+year|half[\s-]?year|first\s+half|nine\s+months|Q[1-4]|H[12]|FY\s?\d{2,4})\b"
    r"|\b(?:during|in)\s+(?:Q[1-4](?:\s*FY\s?\d{2,4})?|H[12](?:\s*FY\s?\d{2,4})?|the\s+(?:quarter|first\s+half|second\s+half|half\s+year|nine\s+months))"
    r"[^.]{0,60}\b(?:secured|won|received|bagged)\s+(?:new\s+|multiple\s+|significant\s+|three\s+)?orders?\b"
    r"|\b(?:awarded|received|secured|secures|won|wins|bagged|bags|receives)\s+"
    r"(?:new\s+|multiple\s+|significant\s+)?(?:orders?|contracts?)\s+"
    r"(?:worth|aggregating(?:\s+to)?|valued\s+at|amounting\s+to)\b[^.]{0,80}?\b(?:in|during|for)\s+"
    r"(?:Q[1-4](?:\s*FY\s?\d{2,4})?|H[12](?:\s*FY\s?\d{2,4})?|FY\s?\d{2,4}"
    r"|(?:the\s+|this\s+)?(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s*[-\u2013\u2014]\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+)?"
    r"(?:year|quarter|half[\s-]?year|nine\s+months))\b"
    r"|\bconsolidated\s+order\s+wins?\s+for\s+(?:Q[1-4]|H[12]|FY)\b"
    r"|\beach\s+of\s+the\s+above\s+orders?\s+has\s+already\s+been\s+individually\s+intimated\b",
    re.I)
# "order inflow for the year" is a genuine order-win release's background sentence (KEC/TRANSRAILL): it is a
# period aggregate only when the announcement itself is about it, so this one is read on the title alone.
_ORDER_INFLOW_TITLE = re.compile(
    r"\border\s+(?:inflow|intake)\b[^.]{0,40}\bfor\s+(?:FY\s?\d{2,4}|(?:the\s+)?(?:year|quarter|half[\s-]?year"
    r"|nine\s+months))\b", re.I)
# T-242 round 8: an "order" a tax office, tribunal or regulator issues TO the company is not a customer order,
# and neither is a regulator's approval to launch a product.  The cue is the authority or the order's own nature
# (assessment, penalty, refund, compounding ...), never the bare words GST/tax: "excluding GST" is printed on
# every genuine order value.
_AUTHORITY_ORDER_STRONG = re.compile(
    r"\b(?:compounding|assessment|reassessment|demand|penalty|refund|remand(?:-|\s*)back|adjudication|rectification"
    r"|warning|prosecution|acceptance\s+of\s+reply)\b[^.;]{0,24}?\border\b"
    r"|\border\s+(?:of|for)\s+(?:assessment|reassessment|demand|penalty|refund|compounding|remand(?:-|\s*)back"
    r"|adjudication|rectification|acceptance\s+of\s+reply)\b"
    r"|\b(?:sebi|irdai|rbi|trai|pfrda|nclt|nclat|itat|cestat|tribunal|high\s+court|supreme\s+court)\b"
    r"[^.;]{0,60}?\b(?:issued|passed|imposed|warned|directed)\b[^.;]{0,40}?\border\b",
    re.I)
_AUTHORITY_OFFICE = re.compile(
    r"\bfrom\s+(?:the\s+)?office\s+of\s+(?:the\s+)?[^.;]{0,80}?"
    r"\b(?:commissioner|inspector|superintendent|metrology|adjudicating|regulatory)\b", re.I)
_REGULATOR_APPROVAL = re.compile(
    r"\b(?:received|obtained|granted|grants?)\b[^.;]{0,40}?\b(?:approval|permission)\b[^.;]{0,120}?"
    r"\b(?:sebi|securities\s+and\s+exchange\s+board|irdai|insurance\s+regulatory|rbi|reserve\s+bank|trai|pfrda)\b"
    r"[^.;]{0,80}?\b(?:to\s+)?(?:launch|introduce|commence|offer|sell)\b"
    r"|\b(?:sebi|securities\s+and\s+exchange\s+board|irdai|insurance\s+regulatory|rbi|reserve\s+bank|trai|pfrda)\b"
    r"[^.;]{0,100}?\b(?:approval|approve[ds]?|permission)\b[^.;]{0,60}?\b(?:launch|introduce|commence|offer|sell)\b",
    re.I)
# a real order names its award noun; an authority's letter that merely says "order" does not.
_AWARD_NOUN = re.compile(
    r"\b(?:work\s+order|purchase\s+order|supply\s+order|letter\s+of\s+(?:award|acceptance|intent)|LOA|LOI"
    r"|contract\s+for|order\s+for\s+(?:supply|design|execution|construction|installation))\b", re.I)
_BOARD_OR_APPOINTMENT = re.compile(
    r"\boutcome\s+of\s+(?:the\s+)?(?:board|meeting\s+of\s+the\s+board)\b|\bboard\s+meeting\b"
    r"|\b(?:assumed?|assumption\s+of)\s+(?:the\s+)?charge\b"
    r"|\bappointment\s+of\s+(?:a\s+|an\s+)?(?:director|managing\s+director|chairman|cmd|company\s+secretary|chief)\b"
    r"|\b(?:cessation|resignation)\s+of\b|\bchange\s+in\s+(?:the\s+)?(?:board|directors?)\b", re.I)
# the escape hatch for a board outcome or an appointment letter: it quotes an award (a value, or a named awarder).
_AWARD_QUOTED = re.compile(
    r"\b(?:received|receives|secured|secures|bagged|bags|won|wins|awarded|obtained)\b[^.;]{0,80}?"
    r"\b(?:orders?|contracts?|LOAs?|LOIs?|letters?\s+of\s+(?:award|acceptance)|work\s+order|purchase\s+order)\b"
    r"[^.;]{0,160}?(?:(?:Rs\.?|INR|₹|US\s?\$|\$|USD)\s*[\d,]|\bfrom\s+(?-i:[A-Z])|\bworth\b|\bvalued\s+at\b)",
    re.I)
# an LOI/LoA to set up the company's OWN outlet, dealership or showroom is a territory appointment, not an order.
_SELF_SETUP = re.compile(
    r"\b(?:letters?\s+of\s+intent|LOIs?|letters?\s+of\s+award|LOAs?)\b[^.;]{0,140}?"
    r"\b(?:to\s+(?:establish|set\s+up|open|launch|operate)|for\s+setting\s+up)\b[^.;]{0,140}?"
    r"\b(?:outlets?|dealerships?|showrooms?|experience\s+cent(?:re|er)s?|service\s+cent(?:re|er)s?"
    r"|3S\s+facilit(?:y|ies)|(?-i:[A-Z])[A-Za-z]{2,}\s+facilit(?:y|ies))\b", re.I)
_CAPACITY_TOKEN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:MW|kW|GW|MWh|kWh|MTPA|TPD|TPA|MLD|KL)\b")
_FINANCIAL_METRIC = re.compile(
    r"\b(?:revenues?|ebitda|pat|net\s+profit|profit\s+after\s+tax|total\s+income|turnover)\b", re.I)
_RESULTS_ACTION = re.compile(r"\b(?:approved|approves|awarded|sanctioned)\b", re.I)
_HAS_FIN_RESULTS = re.compile(
    r"\b(?:un-?audited|audited)\s+(?:standalone\s+|consolidated\s+)?financial\s+results\b", re.I)
# the company is the buyer: an EPC contract it signs with its contractor, or an order it places.
_ORDER_BUYER = re.compile(
    r"\b(?:placed\s+an?\s+order\s+with"
    r"|signed\s+(?:and\s+executed\s+)?(?:the\s+(?:aforesaid|said)\s+|an?\s+)?EPC\s+contract\b.{0,320}?\bwith\b"
    r"|entered\s+into\s+(?:an?\s+)?EPC\s+contract\b.{0,320}?\bwith\b"
    r"|EPC\s+contract\s+to\s+be\s+entered\s+into\s+between\b"
    r"|entered\s+into\s+(?:an?\s+)?EPC\s+contract\s+to\s+develop\b)", re.I)
_WIN_FROM = re.compile(
    r"\b(?:received|awarded|bagged|secured|won|got)\b[^.]{0,100}\bfrom\b", re.I)
# order amendments/variations/extensions: an update to an existing order, never a fresh order.
_AMEND_CUE = re.compile(
    r"\bamendment(s)?\b[^.]{0,100}\b(?:order|contract|value|amount)\b"
    r"|\b(?:LOA|LOI|order|contract)\s+variations?\b|\bvariations?\s+orders?\b"
    r"|\b(?:amended|revised)\s+(?:purchase\s+)?(?:order|contract|value)\b"
    r"|\b(?:purchase\s+order|work\s+order|contract|order)\b[^.]{0,40}\b(?:amended|revised|varied)\b"
    r"|\bextension\s+of\s+(?:the\s+)?(?:contract|order)\b|\bextended\b[^.]{0,50}\b(?:contract|order)\b"
    r"|\benhanced\s+from\b|\bincrease[ds]?\s+(?:in\s+)?(?:the\s+)?(?:total\s+)?value\b", re.I)
_CANCEL_REDUCE_CUE = re.compile(
    r"\b(?:cancell?(?:ed|ation)|withdrawn|withdrawal|short[-\s]?clos(?:ed|ure|ing)|reduc(?:ed|tion)"
    r"|reduce\s+(?:the\s+)?(?:awarded\s+)?(?:orders?|contracts?|value|scope|deliveries)"
    r"|descop(?:ed|ing)?|foreclos(?:ed|ure))\b", re.I)
# a periodic deviation/utilisation statement is not a capex approval.
_CAPEX_VETO = re.compile(r"statement\s+of\s+deviation|utilisation|utilization|\bdeviation\b|post[-\s]issue"
                         r"|new\s+line\s+of\s+business|credit\s+rating|audited\s+financial\s+statements"
                         r"|financial\s+statements?\s+for\s+the\s+(?:year|quarter)"
                         r"|\brefinanc\w*\b|\bexisting\s+debts?\b"
                         r"|exploring|to\s+consider|proposal\s+to|enabling\s+resolution"
                         # T-242: a stake bought is not the company's capex, and the target's project cost is
                         # never its spend (fresh3 #51).
                         r"|\b(?:acquir\w*|acquisition)\b[^.]{0,80}?\b\d{1,3}(?:\.\d+)?\s*(?:%|per\s*cent)"
                         r"\s*(?:equity\s+)?(?:stake|shareholding|interest|shares?)\b"
                         r"|\b\d{1,3}(?:\.\d+)?\s*(?:%|per\s*cent)\s*(?:equity\s+)?(?:stake|shareholding)\b"
                         r"|\bshare\s+purchase\s+agreement\b"
                         r"|\binvestment\s+in\b[^.]{0,50}\b(?:subsidiary|joint\s+venture|associate)\b", re.I)
_CAPEX_STRONG = re.compile(
    r"\b(?:capital\s+expenditure|capex|project\s+cost|estimated\s+cost"
    r"|expansion\s+(?:project|programme|plan|at|of)\b|capacity\s+expansion|greenfield|brownfield"
    r"|setting\s+up\s+(?:of\s+)?(?:a|an|the|its)?\s*(?:new\s+)?(?:plant|unit|line|facility))\b", re.I)
_AMEND_VETO = re.compile(r"credit\s+rating|rating\s+(?:action|revision|reaffirm)"
                         r"|statement\s+of\s+deviation|utilisation|utilization", re.I)
# an L-1/lowest-bidder intimation is an award, never a variation of an existing order (fresh3 #52).
_LOWEST_BIDDER = re.compile(r"\bL\s*[-\u2013]\s*1\b|\blowest\s+(?:bidder|tenderer)\b|\bL1\s+(?:status|bidder)\b"
                            r"|\bemerged\s+as\s+L\s*[-\u2013]?\s*1\b", re.I)
# an approved/proposed capacity is a plan until the sentence says it is commissioned.
_CAPACITY_APPROVED = re.compile(r"\b(?:approved|approves|proposed|setting\s+up|to\s+be\s+set\s+up|will\s+set\s+up)\b",
                                re.I)
_ORDER_WORD = re.compile(
    r"\b(?:order|orders|purchase\s+order|work\s+order|contract|contracts|LOA|LOI|letter\s+of\s+award"
    r"|letter\s+of\s+acceptance|letter\s+of\s+variation)\b", re.I)
# T-242 round 6: an L1-only intimation stays unverified unless an award is ALSO stated as received.  Round 8:
# the award verb must be followed by the order noun itself ("received a Letter of Acceptance"), so the table
# label "Name of the entity awarding the order(s)" is never read as an award.
_AWARD_RECEIVED = re.compile(
    r"\b(?:receiv(?:ed|es)?|receipt(?:\s+of)?|bagged|bags|secured|secures|won|wins|obtained|been\s+awarded)\b"
    r"\s*(?:an?\s+|the\s+|new\s+|fresh\s+|another\s+|additional\s+)?"
    r"\b(?:orders?|contracts?|LOAs?|LOIs?|letters?\s+of\s+(?:award|acceptance|intent)|work\s+orders?"
    r"|purchase\s+orders?|work\s+order\s*/\s*LOI)\b",
    re.I)
_CS_GAP = r"[^;]{0,240}?"      # "USD 762,860.08" and "ie." must not end the gap
_AMEND_FROM_TO = re.compile(
    r"\bfrom\b" + _CS_GAP + r"(?:Rs\.?|INR|₹)\s*(?P<a>[\d,]+(?:\.\d+)?)\s*(?P<au>crores?|cr\.?|lakhs?|lacs?)"
    + _CS_GAP + r"\bto\b" + _CS_GAP + r"(?:Rs\.?|INR|₹)\s*(?P<b>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<bu>crores?|cr\.?|lakhs?|lacs?)", re.I)
_AMEND_AGGREGATE = re.compile(
    r"\b(?:aggregate|total)(?:\s+(?:contract|order))?\s+value\b[^.;]{0,80}?(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)\b", re.I)
_AMEND_AGGREGATE_FULL = re.compile(
    r"\b(?:aggregate|total)(?:\s+contract)?\s+value\b[^.;]{0,80}?(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>\d[\d,]{6,})(?:\s*/-)?", re.I)
# a scan prints "crares"/"lakhs": the unit word is damaged, the two printed ends are not.
_AMEND_FROM_TO_LENIENT = re.compile(
    r"\bfrom\b" + _CS_GAP + r"(?:Rs\.?|INR|₹)\s*(?P<a>[\d,]+(?:\.\d+)?)\s*[A-Za-z]{4,9}"
    + _CS_GAP + r"\bto\b" + _CS_GAP + r"(?:Rs\.?|INR|₹)\s*(?P<b>[\d,]+(?:\.\d+)?)\s*[A-Za-z]{4,9}", re.I)
# a printed consortium/JV share of the award: the company's event value is its share, not the total.
_CONSORTIUM = re.compile(r"\b(?:consortium|joint\s+venture|\bJV\b|equity\s+share)\b", re.I)
_CONSORTIUM_LEAD = (
    r"(?:(?:the\s+)?company['’]?s?|our|[A-Z][A-Za-z0-9&.'’\-]{2,30}['’]s?)\s+"
    r"(?:share|order\s+value|contract\s+value|portion|stake)"
    r"|share\s+of\s+(?:the\s+)?(?:company|[A-Z][A-Za-z0-9&.'’\-]{2,30})"
)
_CONSORTIUM_AMOUNT = re.compile(
    r"(?:" + _CONSORTIUM_LEAD + r")[^.]{0,180}?(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)", re.I)
_CONSORTIUM_AMOUNT_FULL = re.compile(
    r"(?:" + _CONSORTIUM_LEAD + r")[^.]{0,180}?(?:Rs\.?|INR|₹)\s*(?P<v>\d[\d,]{6,})(?:\s*/-)?", re.I)
_CONSORTIUM_PCT = re.compile(
    r"(?:(?:the\s+)?company['’]?s?|our)\s+share[^.]{0,80}?(?P<p>\d+(?:\.\d+)?)\s*%"
    r"|share\s+of\s+(?:the\s+)?(?:company|[A-Z][A-Za-z0-9&.'’\-]{2,30})\s+(?:is|at|being)\s+(?P<p3>\d+(?:\.\d+)?)\s*%"
    r"|(?:holds?|holding)\s+(?:a\s+)?(?P<p4>\d+(?:\.\d+)?)\s*%\s*(?:partnership\s+|equity\s+|jv\s+|consortium\s+)?(?:stake|share|interest)"
    r"|(?:equity\s+)?share\s+of\s+(?P<p2>\d+(?:\.\d+)?)\s*%", re.I)
_ANNUAL_CUE = re.compile(r"\b(?:annual(?:ly)?|yearly|per\s+annum|per\s+year|p\.\s?a\.)\b", re.I)
_ORDER_UPDATE = re.compile(r"\border\s+book\b|\border\s+intake\b|\border\s+inflow\b|\bbacklog\b", re.I)
_WIN_VERB = re.compile(
    r"\b(?:secures?|secured|bagged?|wins?|won|awarded|received|receipt|obtained|entered\s+into)\b", re.I)
# the order's printed size when the prescribed table is absent: a labelled value row, never a stray amount.
_ORDER_VALUE_LABEL = re.compile(
    r"(?:order|contract|loa|loi|work)[^.;]{0,80}?(?:value|amount|size|price|consideration)[^.;]{0,40}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)\b",
    re.I)
_ORDER_VALUE_ROW = re.compile(
    r"\b(?:value|order\s+value|contract\s+value|total\s+value|value\s+of\s+(?:the\s+)?(?:order|work|contract)"
    r"|order\s+size|contract\s+price|estimated\s+value|annual\s+revenue)\b[^.;]{0,30}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)\b",
    re.I)
# T-242 round 8: a GDV, a project cost, an order-book target or the company's own investment is not the order's
# size (#39, #48, #54).  The label must sit beside the figure: a genuine value next to an "order intake" headline
# keeps its number (r5 #39 TRANSRAILL "fresh orders worth Rs 534 crore; order intake crosses ...").
_NOT_ORDER_SIZE_BEFORE = re.compile(
    r"\b(?:order[-\s]?book(?:\s+target)?|order\s+(?:intake|inflow)|backlog)\b", re.I)
_NOT_ORDER_SIZE_NEAR = re.compile(
    r"\b(?:GDV|gross\s+develop(?:ment)?\s+value|project\s+cost|project\s+value|guidance|target(?:ing|ed)?"
    r"|ambition|cumulative\s+investment|investment|capex|capital\s+expenditure)\b", re.I)
# a label printed AFTER the figure only disqualifies a project metric ("Rs 400 Cr GDV Project"); a Capex/Opex
# component note after a genuine contract value does not ("Rs 3002.99 crore [Capex ...]").
_NOT_ORDER_SIZE_AFTER = re.compile(r"\b(?:GDV|gross\s+develop(?:ment)?\s+value)\b", re.I)
# the size a free-form release states in words ("supply and commissioning of an approximately INR 400 crore ...").
_ORDER_SIZE_SENTENCE = re.compile(
    r"\b(?:supply(?:\s+and\s+commissioning)?|commissioning|execution|contract|order|project)s?\b[^.;]{0,60}?"
    r"\b(?:approximately|approx\.?|about|around)\s+(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)\b", re.I)
# a non-INR, non-USD value stays as printed in value_text; never convert it without a printed rate (#13, #51).
_FOREIGN_VALUE = re.compile(
    r"\b(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>million|mn|billion|bn|crores?|lakhs?|lacs?)?\s*"
    r"(?P<cur>euros?|eur|gbp|pounds?|jpy|yen|chf|francs?|aed|dirhams?|sgd|aud|cad)\b"
    r"|\b(?P<cur2>euros?|eur|gbp|pounds?|jpy|yen|chf|aed|sgd|aud|cad)\s*(?P<v2>[\d,]+(?:\.\d+)?)"
    r"\s*(?P<u2>million|mn|billion|bn|crores?|lakhs?|lacs?)?\b", re.I)
_PRICE = re.compile(
    r"(?:issue\s+price|price\s+per\s+(?:equity\s+)?share|price\s+of|at\s+(?:an?\s+)?price\s+of"
    r"|at)\s*(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)(?:\s*/-)?(?:\s*(?:per|each)\s+(?:equity\s+)?share)?", re.I)
_SHARES = re.compile(
    r"(?P<v>\d[\d,]*)\s*(?:\([^)]{0,140}\)\s*)?(?:fully\s+)?(?:convertible\s+)?(?:partly\s+)?"
    r"(?:paid[-\s]?up\s+)?(?:equity\s+)?(?:shares?|warrants?)\b", re.I)
_NCD_RX = re.compile(
    r"non[-\s]?convertible(?:\s*,?\s*(?:non[-\s]?cumulative|cumulative|redeemable|secured|unsecured"
    r"|listed|unlisted|rated|unrated|taxable|senior|subordinated))*[,\s]+debentures?|\bNCDs?\b",
    re.I,
)
_INSTRUMENTS = (
    ("qip", re.compile(r"\bQIP\b|qualified\s+institutions?\s+placement", re.I)),
    ("ncd", _NCD_RX),
    ("preferential", re.compile(r"preferential\s+(?:issue|allotment|offer)", re.I)),
    ("warrant", re.compile(r"\bwarrants?\b", re.I)),
    ("rights", re.compile(r"\brights\s+(?:issue|basis)\b", re.I)),
    ("borrowing", re.compile(r"\bborrowings?\b", re.I)),
    ("equity", re.compile(r"issue\s+of\s+(?:equity\s+)?shares|allotment\s+of\s+(?:equity\s+)?shares", re.I)),
)
_TO_CR = {"crore": 1.0, "cr": 1.0, "lakh": 0.01, "lac": 0.01, "million": 0.1, "mn": 0.1,
          "billion": 100.0, "bn": 100.0}
_TO_USD_MN = {"million": 1.0, "mn": 1.0, "billion": 1000.0, "bn": 1000.0}

_ADDENDUM = re.compile(r"\b(?:addendum|corrigendum|revised|supplementary)\b", re.I)
_PARENT_SCOPE = re.compile(r"\bparent\s+company\b|\bultimate\s+holding\s+company\b|\bholding\s+company\s+(?:call|release|announcement)\b", re.I)
# T-242 round 6: a subsidiary's order is a real order for the listed group -- keep its status and label the
# scope.  The printed name is captured, never inferred; a bare "a subsidiary" leaves the scope company.
_SUB_QUALITY = (r"(?:wholly[-\s]?owned|material|step[-\s]?down|unlisted|listed|direct|indirect|foreign|overseas"
                r"|US[-\s]?based|UK[-\s]?based)")
_SUB_WORD = r"subs(?:idi|di)ar(?:y|ies)"          # subsidiary / subsidiaries / the printed "subsdiary" typo
_SUB_NAME = (r"(?P<name>(?-i:[A-Z])[A-Za-z0-9\u00c0-\u024f&.'’()\-]*"
             r"(?:\s+(?:(?-i:[A-Z0-9])[A-Za-z0-9\u00c0-\u024f&.'’()\-]*|\([A-Za-z0-9\u00c0-\u024f&.'’\-]{1,25}\)"
             r"|of|the|and|i|och|van|der|la|el|di|da|du|de"
             r"|(?i:private|pvt|limited|ltd|llp|inc|llc|gmbh|corp|corporation|company))){0,6})")
# "<Name>, a wholly owned subsidiary of the Company, has received" / "<Name> (wholly owned subsidiary)" /
# "<Name> which is the Material Subsidiary of the Company has received".  Round 8 adds the "which is" form.
_SUB_AFTER_NAME = re.compile(
    _SUB_NAME + r"[\"'”’]?(?:\s*\([A-Z]{2,8}\))?\s*(?:,\s*(?:both\s+)?|\s*\(\s*|\s*[-\u2013\u2014]\s*"
    r"|\s+which\s+(?:is|are)\s+|\s+)\s*(?:a|an|the|our|its|their|both)?\s*"
    r"(?:(?:" + _SUB_QUALITY + r")\s+){0,3}" + _SUB_WORD + r"\b", re.I)
# "our subsidiary <Name>" / "material subsidiary, <Name>" / "subsidiary of <Parent>, <Name>" /
# "Material Subsidiary of the Company, M/s <Name>" / "<subsidiary> Company i.e. <Name>" (round 8).
_SUB_BEFORE_NAME = re.compile(
    r"(?:(?i:the\s+Company'?s?|our|its|their)\s+)?(?:(?:" + _SUB_QUALITY + r")\s+){0,3}" + _SUB_WORD
    + r"\s*(?:company\s*)?"
    r"(?:[-\u2013\u2014:]\s*|of\s+(?:the\s+)?company\s*,?\s*|\s*i\.e\.?,?\s+|of\s+(?-i:[A-Z])[^,.;]{2,60},\s*"
    r"|\s*,\s*(?:i\.e\.?,?\s*)?|\s+which\s+(?:is|are)\s+|\s+)"
    r"(?:M/s\.?\s+|Messrs\.?\s+)?[\"'“‘]?" + _SUB_NAME, re.I)
_SUB_STOP = frozenset({
    "company", "the", "and", "its", "their", "our", "material", "wholly", "owned", "step", "down",
    "subsidiary", "subsidiaries", "a", "an", "of", "i.e",
})
# a bare legal form as the first word is the tail of a longer name, never the name ("AB (Sweden)").
_SUB_LEGAL_LEAD = frozenset({"ab", "as", "asa", "oy", "oyj", "ag", "sa", "sas", "nv", "bv", "pl", "spa", "pte"})
_SUB_NAME_STOP = re.compile(
    r"\s+(?i:has|have|had|having|received|receives|receipt|secured|secures|won|wins|bagged|bags|awarded"
    r"|is|are|was|were|will|would|continues?|through|by|from|for|to|with|order|orders|contract|loa|loi"
    r"|purchase|work|respectively|dear|sirs?|madams?|ma['’]?ams?|we|our|its|their|the\s+company)\b")
_SUB_GENERIC = re.compile(
    r"(?i)^(?:the\s+)?(?:our|its|their|wholly[-\s]?owned|material|step[-\s]?down|unlisted|listed|direct|indirect"
    r"|foreign|overseas|us[-\s]?based|uk[-\s]?based|company|subsidiar(?:y|ies))(?:\s+(?:wholly[-\s]?owned|material"
    r"|step[-\s]?down|unlisted|listed|direct|indirect|foreign|overseas|us[-\s]?based|uk[-\s]?based|company))?$")
_SUB_HOLDER = re.compile(r"(?i)\b(?:vide|its|their|our)\b")
# boilerplate that can precede the marker in a title ("EQ Subject <Parent>'s Wholly Owned Subsidiary") is not a name.
_SUB_JUNK = re.compile(r"(?i)\b(?:wholly|owned|formerly|known|subject|exchange|stock|bombay|bse|nse|entity|name)\b")
_SUB_SUFFIX = re.compile(r"(?i)\b(?:limited|ltd|llp|inc|llc|gmbh|corp(?:oration)?|pvt|private"
                         r"|ab|asa?|oyj?|ag|sas?|nv|bv|pl|spa)\b")
_SUB_UNIT_TOKEN = re.compile(r"\b(?:MWp?|kWp?|GWp?|MVA|kVA|MTPA|MMTPA|TPD|TPA|DC|AC)\b", re.I)
_SUB_COMPANY_ITEM = re.compile(
    r"(?P<item>(?!(?i:limited|ltd|llp|inc|llc|gmbh)\b)(?-i:[A-Z])[A-Za-z0-9&.'’\-]*"
    r"(?:\s+(?!(?i:limited|ltd|llp|inc|llc|gmbh)\b)(?:(?-i:[A-Z0-9])[A-Za-z0-9&.'’\-]*|of|the|and|for)){0,8}"
    r"\s+(?i:Private\s+Limited|Private\s+Ltd\.?|Pvt\.?\s+Ltd\.?|Limited|Ltd\.?|LLP|Inc\.?|GmbH|LLC|Corp(?:oration)?\.?))"
)
_ORDER_BOOK = re.compile(r"\border\s+book\b|\border\s+intake\b|\border\s+inflow\b|\bbacklog\b", re.I)
_DATE_DMY = re.compile(r"\b(?:dated?|made\s+on)\s+(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", re.I)
_DATE_MD = re.compile(
    r"\b(?:dated?|made\s+on)\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December),?\s+(\d{4})\b", re.I)
_DATE_MDY = re.compile(
    r"\b(?:dated?|made\s+on)\s+(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
_MONTHS = {name: i for i, name in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"), 1)}

COLUMNS = (
    "event_id", "store", "symbol", "isin", "doc_key", "kind", "method", "status", "entity_scope", "why",
    "title", "filing_date", "event_date", "known_at", "page", "seq", "amount_inr_cr", "amount_usd_mn", "value_text",
    "value_annual", "value_total", "share_pct",
    "customer", "customer_desc", "execution_months", "order_kind", "purpose", "completion", "capacity_value",
    "capacity_unit",
    "plant", "price_per_share", "shares", "instrument", "raise_stage", "raise_id", "raise_primary",
    "quote", "amends", "detail",
)
SCHEMA = """
CREATE TABLE event (
  event_id INTEGER PRIMARY KEY,
  store TEXT, symbol TEXT, isin TEXT, doc_key TEXT NOT NULL,
  kind TEXT NOT NULL, method TEXT NOT NULL, status TEXT NOT NULL, entity_scope TEXT NOT NULL DEFAULT 'company',
  why TEXT, title TEXT, filing_date TEXT, event_date TEXT, known_at TEXT, page INTEGER, seq INTEGER NOT NULL DEFAULT 1,
  amount_inr_cr REAL, amount_usd_mn REAL, value_text TEXT,
  value_annual REAL, value_total REAL, share_pct REAL,
  customer TEXT, customer_desc TEXT, execution_months REAL, order_kind TEXT,
  purpose TEXT, completion TEXT, capacity_value REAL, capacity_unit TEXT, plant TEXT,
  price_per_share REAL, shares REAL, instrument TEXT,
  raise_stage TEXT, raise_id TEXT, raise_primary INTEGER,
  quote TEXT, amends TEXT, detail TEXT,
  UNIQUE (doc_key, kind, seq)
);
CREATE INDEX ix_event_symbol_date ON event (symbol, filing_date);
CREATE INDEX ix_event_kind_status ON event (kind, status);
CREATE TABLE amend (
  doc_key TEXT PRIMARY KEY, symbol TEXT, amends TEXT NOT NULL, filing_date TEXT, known_at TEXT, why TEXT
);
CREATE TABLE skip_log (
  skip_id INTEGER PRIMARY KEY,
  store TEXT, symbol TEXT, doc_key TEXT NOT NULL,
  candidate_kind TEXT, event_type TEXT, stage TEXT, instrument TEXT,
  reason TEXT, title TEXT, filing_date TEXT
);
CREATE TABLE run_meta (key TEXT PRIMARY KEY, value TEXT);
"""


# ------------------------------------------------------------------ text helpers
def _flat(text: Any) -> str:
    return norm_ws(text)


_SEBI_AMEND_BOILERPLATE = re.compile(
    r"(?:SEBI\s*\(?LODR\)?[^.]{0,80}|Regulations,?\s*2015)\s*,?\s*(?:and\s+)?amendments?\s+thereof"
    r"|\b(?:as\s+amended|amended\s+from\s+time\s+to\s+time)\b",
    re.I,
)
_FILING_SUBJECT_RE = re.compile(
    r"\bSub(?:ject)?\s*[.:]\s*(.+?)(?=[•●▪✓✔]|\b(?:Dear\s+Sir|Sir\s*/?\s*Madam|Ref\s*[.:]|Pursuant\s+to|In\s+terms\s+of"
    r"|With\s+reference|We\s+(?:hereby|wish)|Major\s+Highlights|Phone\s*:|CIN\s*:|E-?mail\s*:|Thanking\s+[Yy]ou)\b"
    r"|(?<=Press\sRelease)\.\s+|$)",
    re.I,
)
_HEADER_SKIP_RE = re.compile(
    r"^(?:Ref\.?:|Date:|To\b|BSE\s+Limited|National\s+Stock\s+Exchange|Exchange\s+Plaza|Phiroze|Dalal\s+Street"
    r"|Scrip\s+(?:Code|Symbol|ID)|Symbol:|Security\s+code|ISIN:|Dear\s+Sir|Sir\s*/?\s*Madam|Sub(?:ject)?\s*[.:]"
    r"|Regd\.?\s*Office|Registered\s+Office|Corporate\s+Office|CIN\b|Tel\b|Phone\b|Fax\b|E-?mail\b|Web(?:site)?\b"
    r"|Thanking\s+you|Yours\s+(?:faithfully|sincerely|truly)|Encl\b|Digitally\s+signed|Copy\s+to\b"
    r"|We\s+(?:hereby\s+)?(?:furnish|enclose|forward|attach)\s+(?:herewith\s+)?(?:a\s+)?copy\s+of)",
    re.I,
)


def _subject_and_first_sentences(title: str, head: str, count: int = 2) -> tuple[str, list[str]]:
    """Return (subject_line, first `count` substantive event sentences after address/salutation boilerplate)."""
    flat_head = _flat(head[:3500])
    sub_m = _FILING_SUBJECT_RE.search(flat_head)
    subject = _flat(sub_m.group(1)) if sub_m else ""
    body_start = sub_m.end() if sub_m else 0
    rest = flat_head[body_start:] if body_start and body_start < len(flat_head) else flat_head
    rest = re.sub(r"^\bRef\.?:[^.]{0,120}?(?=\b(?:With\s+reference|Pursuant|In\s+terms|Dear\s+Sir)\b)", "", rest, flags=re.I)
    dear_m = re.search(r"\b(?:Dear\s+Sir(?:\(s\)|\s*/?\s*Madam)?|Sir\s*/?\s*Madam)\b[,:\s]*", rest, re.I)
    if dear_m and dear_m.start() < 1200:
        rest = rest[dear_m.end():]
    # Cover letters attach a Press Release on page 2 without a sentence stop before "PRESS RELEASE".
    pr_m = re.search(r"\bPRESS\s+RELEASE\b", rest, re.I)
    if pr_m and re.search(
        r"\b(?:furnish|enclose|forward|attach)\b|\bPress\s+Release\b",
        f"{title} {subject} {rest[:200]}",
        re.I,
    ):
        rest = rest[pr_m.end():]
    raw_clauses = _clauses(rest)
    substantive: list[str] = []
    for clause in raw_clauses:
        cleaned = re.sub(
            r"^(?:Dear\s+Sir(?:\s*/?\s*Madam)?\s*,?\s*)?"
            r"(?:(?:Pursuant\s+to|In\s+(?:terms|compliance)\s+of|With\s+reference\s+to)\b[^,]{0,180}?,\s*)?"
            r"(?:we\s+(?:wish\s+to\s+|hereby\s+)?inform(?:\s+you)?\s+(?:that|about)\s+)?",
            "",
            clause,
            flags=re.I,
        ).strip()
        if not cleaned or _HEADER_SKIP_RE.match(cleaned) or len(cleaned) < 15:
            continue
        substantive.append(clause)
        if len(substantive) >= count:
            break
    return subject, substantive


def _clauses(text: str) -> list[str]:
    # PDF line wrapping is not a sentence end ("... from X crore to\nsupport the expansion"); a full stop ends a
    # clause only before a capital or a bracket, so "Rs. 650" and "Ltd. 650" stay whole.
    # Bullet symbols mark separate highlights even without a trailing full stop.
    flat_text = _flat(text)
    out: list[str] = []
    for block in re.split(r"\s*[•●▪✓✔]\s*", flat_text):
        flat_block = _flat(block)
        if not flat_block:
            continue
        for clause in re.split(
            r"(?<!\bDistt\.)(?<!\bNo\.)(?<!\bSr\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<=[.!?])\s+(?=[A-Z(])",
            flat_block,
        ):
            if clause.strip():
                out.append(clause.strip())
    return out


def _around(text: str, match: re.Match[str], width: int = MAX_QUOTE) -> str:
    start = max(0, match.start() - width // 3)
    end = min(len(text), start + width)
    return text[start:end].strip()


def _to_cr(value: str, unit: str) -> float | None:
    try:
        number = float(value.replace(",", ""))
        key = unit.lower().rstrip(".").rstrip("s")
        if key == "crore" and number >= 1e6:
            # "Rs. 7,40,06,30,000 Crore": a full rupee figure mislabelled with a crore suffix
            return round(number / 1e7, 4)
        return round(number * _TO_CR[key], 4)
    except (KeyError, ValueError):
        return None


def _digits(value: str) -> float:
    """A printed number's digits, whatever OCR spacing it carries ("2, 94, 72, 78500")."""
    return float(re.sub(r"[^\d.]", "", value))


def _sane_cr(value: Any) -> float | None:
    """A rupee "crore" figure with 7+ digits is a full rupee amount mislabelled Crore ("Rs. 7,40,06,30,000 Crore")."""
    if value is None:
        return None
    number = float(value)
    return round(number / 1e7, 4) if number >= 1e6 else number


def _to_usd_mn(value: str, unit: str) -> float | None:
    try:
        return round(float(value.replace(",", "")) * _TO_USD_MN[unit.lower().rstrip(".").rstrip("s")], 4)
    except (KeyError, ValueError):
        return None


def _amounts_rs(text: str) -> list[tuple[float, str, int]]:
    out: list[tuple[float, str, int]] = []
    for m in _RS_AMOUNT.finditer(text or ""):
        value = _to_cr(m.group("v"), m.group("u"))
        if value is not None:
            out.append((value, m.group(0), m.start()))
    return out


def _page_of(pages: dict[int, str], value_text: str | None) -> int:
    needle = _flat(value_text)
    if needle:
        for page in sorted(pages):
            if needle in _flat(pages[page]):
                return int(page)
    return int(sorted(pages)[0]) if pages else 1


def _canon_capacity_unit(unit: str) -> str:
    key = _flat(unit).lower().rstrip(".")
    if key in _CAPACITY_UNIT:
        return _CAPACITY_UNIT[key]
    return re.sub(r"\s+", " ", key.rstrip("s"))


_PLANT_BAD = frozenset({
    "india", "the", "company", "unit", "regulation", "regulations", "sebi", "bse", "nse",
    "phone", "fax", "email", "cin", "website", "ref", "regd", "office",
    "with", "total", "phase", "stage", "project", "plant", "facility", "january", "february",
    "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
})


def _clean_plant_name(raw: str) -> str | None:
    name = _flat(raw).strip(" .,-–'\"’”")
    name = re.sub(r"\s+(?:Dear\s+Sir|Sir\s*/?\s*Madam)\b.*$", "", name, flags=re.I)
    name = re.sub(r"\s+(?:in\s+)?India$", "", name, flags=re.I).strip(" .,-–'\"’”")
    words = name.split()
    if len(words) >= 2 and words[-1].lower() == words[-2].lower():
        name = " ".join(words[:-1])
    if not name or len(name) <= 1 or len(name) > 80 or name.lower() in _PLANT_BAD:
        return None
    if re.fullmatch(r"(?:FY|Q[1-4]|CY)\s?\d{2,4}", name, re.I):
        return None
    return name


def _plant(sentence: str) -> str | None:
    for match in _PLANT.finditer(sentence or ""):
        name = _clean_plant_name(match.group("name"))
        if name:
            return name
    host = re.search(
        r"\bat\s+(?:its|the|our)\s+\d[\d.,]*\s*(?:" + _CAP_UNIT_RX + r")\s+"
        r"(?P<name>[A-Z][A-Za-z0-9&.'’\-]*(?:\s+[A-Z][A-Za-z0-9&.'’\-]*){0,4})",
        sentence or "",
        re.I,
    )
    if host:
        name = _clean_plant_name(host.group("name"))
        if name:
            return name
    return None


# ------------------------------------------------------------------ classification + script parse
def _capex_clause(title: str, text: str) -> str | None:
    """The clause that sanctions a spend: capex word and approval word together, never a "to consider" line."""
    for sentence in [title] + _clauses(text):
        if not (_CAPEX_STRONG.search(sentence) and _APPROVE.search(sentence)):
            continue
        if _FINANCIAL_METRIC.search(sentence):
            continue
        if _RAISE_CUE.search(sentence) and not re.search(r"capital\s+expenditure|capex|project\s+cost",
                                                         sentence, re.I):
            continue                  # "preferential issue ... to accelerate expansion" is a raise, not a capex
        if _INTIMATION.search(sentence) and not _DONE.search(sentence):
            continue
        return sentence
    return None


def _order_amendment_clause(title: str, head: str) -> str | None:
    """The clause that amends/variates/extends/cancels/reduces an existing order (never a fresh order).

    The amendment word must sit in the title, subject, or first two event sentences (never SEBI LODR
    'amendments thereof' boilerplate), while the printed value may sit in the annexure.
    """
    clean_title = _SEBI_AMEND_BOILERPLATE.sub(" ", title or "")
    clean_head = _SEBI_AMEND_BOILERPLATE.sub(" ", head or "")
    opening = _flat(f"{clean_title} {clean_head[:2000]}")
    whole = _flat(f"{clean_title} {clean_head}")
    if _AMEND_VETO.search(_flat(clean_title)) or _LOWEST_BIDDER.search(opening) \
            or _ORDER_VETO.search(opening) or not _ORDER_WORD.search(whole):
        return None
    subject, first_sents = _subject_and_first_sentences(clean_title, clean_head, count=3)
    gate_texts = [clean_title, subject, *first_sents]
    not_applicable = re.compile(r"\bnot\s+applicable\b", re.I)
    gate_amends = [t for t in gate_texts if t and _AMEND_CUE.search(t) and not not_applicable.search(t)]
    gate_reduces = [t for t in gate_texts if t and _CANCEL_REDUCE_CUE.search(t) and not not_applicable.search(t)]
    if not (gate_amends or gate_reduces):
        return None
    if not gate_amends and not any(re.search(r"\bextension\b|\bextended\b", t, re.I)
                                   for t in gate_texts if t) \
            and re.search(r"\bletter\s+of\s+award\b|\bnew\s+orders?\b", opening, re.I):
        # a fresh letter of award whose project name says "loss reduction" is a win, never a negative variation
        # (fresh3 #58); an extension stays an amendment.
        return None
    sentences = [clean_title] + _clauses(clean_head)
    cue_at = next(
        (index for index, sentence in enumerate(sentences)
         if (_AMEND_CUE.search(sentence) or _CANCEL_REDUCE_CUE.search(sentence))
         and not re.search(r"\bnot\s+applicable\b", sentence, re.I)),
        None,
    )
    if cue_at is None:
        return None
    for sentence in sentences[cue_at:]:
        if not _ORDER_WORD.search(sentence):
            continue
        if _AMEND_FROM_TO.search(sentence) or _AMEND_AGGREGATE.search(sentence) \
                or _AMEND_AGGREGATE_FULL.search(sentence) or _RS_AMOUNT.search(sentence) \
                or _RS_FULL.search(sentence):
            return sentence
    if any(_CANCEL_REDUCE_CUE.search(s) for s in sentences[cue_at:]):
        for sentence in sentences[:cue_at]:
            if _ORDER_WORD.search(sentence) and (_RS_AMOUNT.search(sentence) or _RS_FULL.search(sentence)):
                return f"{sentence} {sentences[cue_at]}"
    return None


def _capex_candidate(title: str, head: str) -> bool:
    combined = _flat(f"{title} {head}")
    if _CAPEX_VETO.search(combined):
        return False
    if _capex_clause(title, head):
        return True
    if _RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}")) or _HAS_FIN_RESULTS.search(_flat(f"{title} {head[:1500]}")):
        return False
    if not (_APPROVE.search(head[:1500]) or _DONE.search(head[:1500])):
        return False
    return any(_CAPEX_STRONG.search(sentence) and _RS_AMOUNT.search(sentence)
               and not _FINANCIAL_METRIC.search(sentence)
               and not (_RAISE_CUE.search(sentence)
                        and not re.search(r"capital\s+expenditure|capex|project\s+cost", sentence, re.I))
               for sentence in _clauses(head))


def classify(title: str, head: str, filing_date: str | None = None, text: str | None = None) -> list[str]:
    """The classes one announcement names, at most once each, from its title and first two pages.

    ``text`` (the held pages) is only read for a raise whose step amount is printed past page 2 (KPIGREEN #47):
    the class still needs the size, so a title-and-head cue alone never makes a fund_raise.
    """
    body = _flat(f"{title} {head}")
    is_results = bool(_RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}")))
    is_rollup = bool(_ORDER_ROLLUP.search(body)) or bool(_ORDER_INFLOW_TITLE.search(title))
    found: list[str] = []

    amendment = _order_amendment_clause(title, head)
    if amendment:
        found.append("order_amendment")
        prose = _prose_order_records(title, head)
        if not is_results and not is_rollup and len({round(float(record["value_cr"]), 4) for record in prose}) >= 2 \
                and not re.search(r"variation|amendment|extension|cancel|reduc|withdraw|short[-\s]?clos|descop|foreclos",
                                  title, re.I):
            found.append("order_win")            # one fresh LOA and one variation in the same letter (MICEL 463)
    elif not is_results and not is_rollup \
            and (order_wins.parse(_flat(title), _flat(head)) or _loose_order_record(title, head)) \
            and not _ORDER_VETO.search(body) and not _is_buyer_side(title, head) \
            and not _not_an_order(title, head):
        found.append("order_win")

    # capex: one clause approves a named spend with the amount printed; an unquantified "approved a plan"
    # is not a factor event (it was the main false-positive source in the stage-A read).
    if _capex_candidate(title, head):
        probe = capex_fields(title, head, head)
        if probe is not None and probe.get("amount_inr_cr") is not None:
            found.append("capex_approval")

    # capacity commissioned: a completed commissioning and the capacity it added, in one clause.
    if capacity_fields(title, head, head, filing_date=filing_date):
        found.append("capacity_commissioned")

    # fund raise: a decided raise (or an explicit raise title whose details are inside), not a rating or a
    # SEBI framework circular that merely says "fund raising".
    if raise_fields(title, head, text or head):
        found.append("fund_raise")
    return found


def _why(kind: str, title: str, text: str) -> str:
    rx = {"capex_approval": _CAPEX_CUE, "capacity_commissioned": _CAPACITY_CUE,
          "fund_raise": _RAISE_CUE, "order_amendment": _AMEND_CUE}.get(kind)
    if kind == "order_amendment":
        for source in (title, text):
            match = _AMEND_CUE.search(source or "") or _CANCEL_REDUCE_CUE.search(source or "")
            if match:
                return _flat(source[max(0, match.start() - 30): match.end() + 60])[:200]
        return kind
    if rx is None:
        win = order_wins.WIN.search(_flat(f"{title} {text[:1200]}"))
        if win:
            head = _flat(f"{title} {text[:1200]}")
            return head[max(0, win.start() - 30): win.end() + 60][:200]
        return "order_wins.parse"
    for source in (title, text):
        match = rx.search(source or "")
        if match:
            return _flat(source[max(0, match.start() - 30): match.end() + 60])[:200]
    return kind


_BAD_CUSTOMER = re.compile(
    r"contract\s*\(\s*s\s*\)|contact\s*\(\s*s\s*\)|international\s+client|^i\s+|^name\b|^n/?a$|^none$|^details?"
    r"|date\s+of\s+issue|letter\s+of\s+(?:acceptance|award)|work\s+order|order\s*\(\s*s\s*\)"
    r"|\b(?:received|multiple|new|repeat)\s+orders?\b|\border(?:\(\s*s\s*\)|s)?\s+from\b"
    r"|the\s+company|interest\s+in\s+the\s+entity|\bwhether\s+(?:the\s+)?promoter\b|\bpromoter\s*(?:/|group)\b"
    r"|related\s+party|thereof"
    r"|\b(?:rs\.?|inr|worth|crores?|lakhs?|lacs?)\b|₹"
    r"|our\s+valued\s+customer|valued\s+customer|\ba\s+leading\b|\ba\s+renowned\b|\ba\s+renowed\b"
    r"|\ba\s+reputed\b|\ba\s+prominent\b|\ba\s+listed\s+company\b|\bone\s+of\s+the\b"
    r"|\bcustomers?\b|\bclient\s+firm\b|\bsame\s+client\b|\btraders\s+to\b"
    r"|\bbased\s+(?:renow[ne]d|reputed|prominent|at\s+(?:ahmedabad|gujarat|maharashtra|india))\b", re.I)
# T-242 round 6/7: a press-release headline or dateline is not the awarder ("BSNL to Power India's Telecom Future
# BANGALORE - January 01", "Top US Institutional Supplier Mumbai - 17th May").
_MONTH_NAME_RX = (
    r"(?:january|february|march|april|may|june|july|august|september|october|november|december)"
)
_HEADLINE_CUSTOMER = re.compile(
    r"\bto\s+(?:power|build|transform|shape|drive|accelerate|unlock|energi[sz]e|revolutioni[sz]e|lead|light)\b"
    r"|\b" + _MONTH_NAME_RX + r"\s+\d{1,2}\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH_NAME_RX + r"\b",
    re.I)
_HEADLINE_PLACE = re.compile(
    r"\b[A-Z]{4,}\s+[-\u2013\u2014]\s*[A-Z0-9]"
    r"|\b[A-Z][A-Za-z/]{2,}\s*[-\u2013\u2014|,]\s*(?:\d{1,2}(?:st|nd|rd|th)?\s+(?i:" + _MONTH_NAME_RX
    + r")|(?i:" + _MONTH_NAME_RX + r")\s+\d{1,2})\b"
)
_ANY_MONTH_RX = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?"
    r"|jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_SINGLE_DATE_TOKEN_RX = (
    r"(?:\d{1,2}(?:st|nd|rd|th)?\s+" + _ANY_MONTH_RX + r"(?:,?\s*\d{2,4})?"
    r"|" + _ANY_MONTH_RX + r"(?:\s+\d{1,2}(?:st|nd|rd|th)?)?(?:,?\s*\d{2,4})?"
    r"|\d{1,4}[./-]\d{1,2}[./-]\d{2,4}"
    r"|(?:(?:Q[1-4]|H[12]|9M)(?:\s*(?:[-\u2013\u2014/]|to)\s*Q[1-4])?\s*(?:FY|CY)?\s*'?\d{2,4}(?:\s*[-\u2013\u2014/]\s*\d{2,4})?)"
    r"|(?:FY|CY)\s*'?\d{2,4}(?:\s*[-\u2013\u2014/]\s*\d{2,4})?"
    r"|Q[1-4](?:\s*(?:[-\u2013\u2014/]|to)\s*Q[1-4])?)"
)
_DATE_OR_PERIOD_CUSTOMER = re.compile(
    r"^(?:from\s+|during\s+|between\s+)?"
    + _SINGLE_DATE_TOKEN_RX
    + r"(?:\s*(?:to|and|[-\u2013\u2014/]|till|until)\s*" + _SINGLE_DATE_TOKEN_RX + r")?$",
    re.I,
)
_SINGLE_GENERIC_CUSTOMERS = frozenset({
    "public", "office", "government", "department", "client", "customer", "entity", "company",
    "authority", "ministry", "board", "corporation", "division", "party", "vendor", "supplier",
    "bank", "railway", "railways", "metro", "state", "central", "domestic", "international",
    "same", "order", "orders", "contract", "contracts", "project", "work",
})
_OWN_PARTY_PREFIX = re.compile(r"^(?:our|its|their|(?:the\s+)?company['’]s)\b", re.I)
_HEADER_PARTY_PREFIX = re.compile(
    r"^(?:redevelopment(?:\s*\(\s*s?\s*\))?|letter\s+of\s+(?:intent|acceptance|award)|particulars|details"
    r"|description|nature\s+of|significant\s+terms|broad\s+(?:commercial\s+)?consideration|time\s+period"
    r"|whether\b|sr\.?\s*no\.?|s\.?\s*no\.?|works?\s+to\s+be\b"
    r"|(?:appointment|engagement|supply|construction|preparation|carrying|providing|execution|consultancy)\s+of)\b",
    re.I,
)
_COUNTRIES_AND_REGIONS = frozenset({
    "afghanistan", "algeria", "argentina", "australia", "austria", "bahrain", "bangladesh", "belgium",
    "bhutan", "brazil", "bulgaria", "cambodia", "canada", "chile", "china", "colombia", "croatia",
    "cyprus", "czech republic", "czechia", "denmark", "egypt", "estonia", "ethiopia", "finland",
    "france", "germany", "ghana", "greece", "hong kong", "hungary", "iceland", "india", "indonesia",
    "iran", "iraq", "ireland", "israel", "italy", "japan", "jordan", "kazakhstan", "kenya", "korea",
    "south korea", "kuwait", "laos", "latvia", "lebanon", "libya", "lithuania", "luxembourg",
    "malaysia", "maldives", "mauritius", "mexico", "mongolia", "morocco", "myanmar", "nepal",
    "netherlands", "new zealand", "nigeria", "norway", "oman", "pakistan", "peru", "philippines",
    "poland", "portugal", "qatar", "romania", "russia", "rwanda", "saudi arabia", "senegal",
    "serbia", "singapore", "slovakia", "slovenia", "south africa", "spain", "sri lanka", "sudan",
    "sweden", "switzerland", "taiwan", "tanzania", "thailand", "tunisia", "turkey", "turkiye",
    "uganda", "uk", "united kingdom", "ukraine", "uae", "united arab emirates", "usa",
    "united states", "united states of america", "uzbekistan", "vietnam", "yemen", "zambia",
    "zimbabwe",
    "africa", "african", "americas", "apac", "asia", "east asia", "emea", "europe",
    "european union", "gulf", "gcc", "latin america", "middle east", "north africa",
    "north america", "south america", "south asia", "southeast asia", "south east asia",
    "abroad", "overseas",
})
_CUSTOMER_CUTS = re.compile(
    r"(?:,?\s+for\s+|\s+amounting\b|\s+as\s+per\b|\s+worth\b|\s+signif\w*\b|\s+towards\b"
    r"|\s+Ref\.?(?:\s*:|\s*$)|\s+(?:on\s+\d|dated\s|of\s+worth|having\s))", re.I)
_FOR_ENTITY_HEAD = re.compile(
    r"^(?:centre|center|institute|council|society|agency|authority|foundation|department|association|board"
    r"|(?:national\s+)?bank|corporation|commission|directorate|ministry|university)\b", re.I)
# T-242: an awarder the filing describes instead of naming ("A hyperscale partner", "leading telecom
# infrastructure company", "customers in the renewable energy sector") belongs in customer_desc, not customer.
_CUSTOMER_DESCRIPTION = re.compile(
    r"^(?:a|an|leading|key|domestic|customers?|clients?|one\s+of|various|several|major|large|prestigious"
    r"|reputed|renowned|prominent|multinational)\b", re.I)
# T-242: "from <Entity Name> (Limited|Ltd|Nigam|Corporation|Authority|...)" -- the awarder a press release names
# in prose without a Reg 30 annexure row (fresh3 #30).  The printed suffix, never a bare "from the Company".
_ENTITY_TAIL = (
    r"(?:Limited|Ltd|LLC|Inc|Corporation|Corpn|Authority|Nigam|Board|Commission|Ministry|Department"
    r"|Government|University|Institute|Society|Bank|Company|Corporates?|Enterprises?|Industries"
    r"|Services?|Technologies?|Infrastructure|Ports?|Railways?|Metro|Council|Foundation)")
_FROM_ENTITY = re.compile(
    r"(?:[Ff]rom|[Aa]warded\s+[Bb]y|[Nn]ame\s+of\s+(?:the\s+)?[Pp]arty\b[^A-Za-z0-9]{0,60}?)"
    r"\s+(?:M/s\.?\s+|Messrs\.?\s+)?"
    r"(?P<name>[A-Z][A-Za-z0-9&.'’()\-]*"
    r"(?:\s+(?:\([A-Za-z0-9&.'’\-]{1,20}\)|[A-Z][A-Za-z0-9&.'’()\-]*|of|the|and|for)){0,8}\s+" + _ENTITY_TAIL
    + r"(?:\s*\([^)]{0,20}\))?)(?=[\s,.;:)•]|$)")
_ANNEXURE_AWARDER = re.compile(
    r"\bname\s*(?:\(\s*s?\s*\))?\s*of\s+(?:the\s+)?(?:entity|entities|customer|client|party)"
    r"[^:;]{0,140}?\s*(?P<cust>(?<!\w).+?)"
    r"(?=\s*(?:\b[b-k]\s*[.)]?\s*(?:significant|nature|whether|time|broad|details|date|objects|indicative|total)"
    r"|\b[2-9]\s*[.)]?\s*(?:significant|nature|whether|time|broad|details|date|objects|indicative|total)"
    r"|\bsignificant\s+terms|\bnature\s+of\s+(?:the\s+)?(?:o\S{0,2}der|contract)"
    r"|\b(?:enhancement\s+in\s+)?size\s+of\s+(?:the\s+)?(?:o\S{0,2}der|contract)"
    r"|\bwhether\s+(?:the\s+)?(?:o\S{0,2}der|contract|domestic|promoter|acquisitions?)"
    r"|\bobjects?\s+and\s+effects|\bindicative\s+time\s+period|\btotal\s+cost"
    r"|\btime\s+period\s+by\s+which|\bbroad\s+(?:commercial\s+)?consideration|$))",
    re.I)
_ANNEXURE_TARGET_AWARDER = re.compile(
    r"\bname\s+of\s+(?:the\s+)?target\s+entity(?:\s+details\s+in\s+brief[^:;\n]{0,60}?etc\.?)?"
    r"[^:;]{0,40}?\s*(?P<cust>(?<!\w).+?)"
    r"(?=\s*(?:\bwhether\s+(?:the\s+)?(?:acquisitions?|o\S{0,2}der|contract|domestic|promoter)"
    r"|\bobjects?\s+and\s+effects|\bindicative\s+time\s+period|\btotal\s+cost|$))",
    re.I,
)
_ANNEXURE_LABEL_STRIP = re.compile(
    r"\b(?:to\s+which|from\s+which)\b[^:;\n]{0,50}?\bawarded\b"
    r"|\bawarding\s+(?:the\s+)?"
    r"|/?\s*redevelopment(?:\s*[\[\(]\s*s?\s*[\)\]])?"
    r"|/?\s*letter\s+of\s+(?:intent|acceptance|award)\b"
    r"|\bo\S{0,2}der\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?(?:\s*(?:/|or|and|&)\s*)?con\S{1,10}?[cz]?t"
    r"\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|\/\s*con\S{1,10}?[cz]?t\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|\bo\S{0,2}der\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|(?:the\s+)?con\S{0,8}?[cz]?t(?:\s?\(?s?\)?)?\s*(?=[:;|]|$)",
    re.I)


def _annexure_awarders(text: str) -> list[str]:
    """Extract customer names from Reg 30 annexure rows ('Name of the entity ... awarding ...')."""
    out: list[str] = []
    flat = _flat(text)
    for rx, strip_label in ((_ANNEXURE_AWARDER, True), (_ANNEXURE_TARGET_AWARDER, False)):
        for match in rx.finditer(flat):
            raw = _ANNEXURE_LABEL_STRIP.sub(" ", match.group("cust")) if strip_label else match.group("cust")
            raw = re.sub(r"\s+", " ", raw).strip(" ;:,.-|/")
            raw = re.sub(r"^(?:details?|particulars|contract|order|entity|party|name)\b[\s:;-]*",
                         "", raw, flags=re.I)
            if raw:
                out.append(raw)
        if out:
            break
    return out


_PARTY_EDGE_PUNCT = " ;:,.-—–/|•●▪✓✔◦·*"
_LEADING_PARTY_JUNK = re.compile(
    r"^(?:[•●▪✓✔◦·*\-\u2013\u2014:;,.|/\\]+\s*"
    r"|[a-z]\s*[:|]\s*"
    r"|con\S{1,10}?\(?s?\)?\s*[:|]\s*"
    r"|[b-z]\s+(?=[A-Z]))+",
)
_UNDISCLOSED_CUSTOMER = re.compile(
    r"(?:^|\b)(?:not\s+disclosed|undisclosed|withheld)\b"
    r"|^(?:(?:kept\s+|strictly\s+)?confidential)\b"
    r"|\bconfidential\s+(?:terms?|agreement|clause|reasons?|understanding|nature)\b",
    re.I,
)


def _strip_unbalanced_brackets(value: str) -> str:
    """Drop an edge bracket with no partner ("( Hindustan Aeronautics Limited"); a balanced "(AVS Group)" stays."""
    for opener, closer in (("(", ")"), ("[", "]"), ("{", "}")):
        while value.startswith(opener) and value.count(opener) > value.count(closer):
            value = value[1:].lstrip(_PARTY_EDGE_PUNCT + " \t")
        while value.endswith(closer) and value.count(closer) > value.count(opener):
            value = value[:-1].rstrip(_PARTY_EDGE_PUNCT + " \t")
    return value


def _strip_party_junk(text: Any) -> str:
    """Strip OCR bullets, single-letter list markers and edge punctuation around a customer name."""
    value = re.sub(r"[\ue000-\uf8ff|]", " ", _flat(text))
    # OCR wraps a long word across a line ("AVS Hous- ing and Construction"): join it.  An all-caps run
    # keeps its hyphen without the space ("BHEL- TRSL" -> "BHEL-TRSL").
    value = re.sub(r"(?<=[a-z])-\s+(?=[a-z])", "", value)
    value = re.sub(r"(?<=[A-Z])-\s+(?=[A-Z])", "-", value)
    value = re.sub(r"\s+", " ", value).strip(_PARTY_EDGE_PUNCT)
    value = _LEADING_PARTY_JUNK.sub("", value)
    value = _strip_unbalanced_brackets(value.strip(_PARTY_EDGE_PUNCT))
    return re.sub(r"\s+", " ", value).strip(_PARTY_EDGE_PUNCT)


def _is_customer_description(value: Any) -> bool:
    """A printed category, not a named awarder: all lower case or a generic lead ("A hyperscale partner")."""
    desc = _flat(value)
    return bool(desc) and (desc.islower() or bool(_CUSTOMER_DESCRIPTION.match(desc)))


def _split_customer(row: dict[str, Any]) -> None:
    """Clean punctuation, mark undisclosed customers as NULL+detail, and move descriptions to ``customer_desc``."""
    raw_customer = row.get("customer")
    if not raw_customer:
        return
    parts: list[str] = []
    undisclosed = False
    for part in str(raw_customer).split(";"):
        cleaned = _strip_party_junk(part)
        if not cleaned:
            continue
        if _UNDISCLOSED_CUSTOMER.search(cleaned):
            undisclosed = True
            continue
        if _names_subsidiary(cleaned, row.get("_subsidiary")):
            continue                  # a subsidiary's name is the issuer's scope, never the awarder (#53)
        parts.append(cleaned)
    if not parts:
        row["customer"] = None
        if undisclosed:
            row["_undisclosed_customer"] = True
        return
    kept_named: list[str] = []
    kept_desc: list[str] = []
    for part in parts:
        if _is_customer_description(part):
            kept_desc.append(part)
        else:
            kept_named.append(part)
    row["customer"] = "; ".join(kept_named)[:300] or None
    if kept_desc and not row.get("customer_desc"):
        row["customer_desc"] = "; ".join(kept_desc)[:300]
    if undisclosed and not kept_named:
        row["_undisclosed_customer"] = True


def _clean_party(text: Any, *, from_annexure: bool = False) -> str | None:
    """A printed awarder name without OCR bullets, table junk, a date clause or generic descriptions."""
    value = _strip_party_junk(text)
    value = re.sub(r"^.+?\bdepartment\s+of\s+the\s+", "", value, flags=re.I)
    # T-242: an annexure cell that runs into the letter's salutation or the city after the legal suffix.
    value = re.sub(r"[\s,;:/&.\-]*\b(?:dear\s+|respected\s+)?(?:sirs?|madams?|ma['’]?ams?)"
                   r"(?:\s*[/,&-]\s*(?:sirs?|madams?|ma['’]?ams?))?[\s,;:/&.\-]*$", "", value, flags=re.I)
    # A bare place after a company's legal suffix is an address ("Signatureglobal (India) Limited Mumbai"); after a
    # public body's word it is usually the name ("Municipal Corporation Jodhpur"), so there only a comma cuts it.
    entity = re.match(
        r"^(?P<name>.+?\b(?:Limited|Ltd|LLP))\s*(?:,\s*)?(?P<tail>[A-Z][A-Za-z.]{2,})$", value) or re.match(
        r"^(?P<name>.+?\b(?:Corporation|Corpn|Nigam|Authority|Railways?|Division)),\s*(?P<tail>[A-Z][A-Za-z.]{2,})$",
        value)
    if entity and not re.search(_ENTITY_TAIL, entity.group("tail"), re.I):
        value = entity.group("name")
    if from_annexure:
        non_for = re.search(
            r"(?:\s+amounting\b|\s+as\s+per\b|\s+worth\b|\s+signif\w*\b|\s+towards\b"
            r"|\s+Ref\.?(?:\s*:|\s*$)|\s+(?:on\s+\d|dated\s|of\s+worth|having\s))",
            value, re.I)
        if non_for and non_for.start() > 3:
            value = value[:non_for.start()]
        head, sep, _tail = value.partition(" for ")
        if sep and len(head) > 3 and not _FOR_ENTITY_HEAD.match(head.strip()):
            value = head
        value = re.split(r",\s*\d+\s*[/-]", value)[0]      # a printed street address after the entity
        value = re.sub(r"\s+under\s+(?:the\s+)?(?:administrative\s+)?control\s+of\b.*$", "", value,
                       flags=re.I)                        # "Society under the administrative control of ..."
        value = re.sub(r"\),\s*(?:[A-Z][A-Za-z.&'-]*\s+){1,6}(?:University|College|Vidyalaya)\b.*$",
                       ")", value)                        # "Institute (MPMMCC), Banaras Hindu University, Varanasi"
    else:
        cut = _CUSTOMER_CUTS.search(value)
        if cut and cut.start() > 3:
            value = value[:cut.start()]
    value = _strip_party_junk(value)
    value = re.sub(r"^(?:the|m/s\.?|messrs\.?)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+Ref\.?(?:\s*:.*)?$", "", value)
    value = re.sub(r"\s+[1-9]$", "", value)
    value = _strip_party_junk(value)
    if not value:
        return None
    if _UNDISCLOSED_CUSTOMER.search(value):
        return value
    if _DATE_OR_PERIOD_CUSTOMER.match(value) or _HEADLINE_CUSTOMER.search(value) or _HEADLINE_PLACE.search(value):
        return None
    if _OWN_PARTY_PREFIX.search(value) or _HEADER_PARTY_PREFIX.search(value):
        return None
    low = value.lower()
    if (len(value.split()) == 1 and low in _SINGLE_GENERIC_CUSTOMERS) \
            or low in _COUNTRIES_AND_REGIONS \
            or re.sub(r"\s+region$", "", low).strip(" ,.-") in _COUNTRIES_AND_REGIONS:
        return None
    if len(value) < 3 or len(value) > (120 if from_annexure else 80) or _BAD_CUSTOMER.search(value):
        return None
    if not re.search(r"[A-Z]", value) or re.search(r"\bFY\s?\d{2}\b", value):
        return None
    if len(value) > 18 and " " in value and value.islower():
        return None
    return value


def _valid_sub_name(raw: str) -> str | None:
    name = _SUB_NAME_STOP.split(raw)[0]
    name = re.sub(r"^(?:M/s\.?|Messrs\.?)\s+", "", name, flags=re.I)
    name = re.sub(r"\s*\(?\s*(?:formerly|earlier|now)\s+known\s+as\b.*$", "", name, flags=re.I)
    name = re.sub(r"\s+", " ", name).strip(" ;:,.-—–\"'“”‘’")
    if ")" in name and "(" not in name:
        name = name.rstrip(") ").strip()
    if "(" in name and ")" not in name:
        name = name.split("(", 1)[0].strip()
    if re.search(r"['’]s$", name, re.I):      # "<Parent>'s Subsidiary" names the parent, not the child
        return None
    # "Provigil Surveillance Limited. Bombay Stock Exchange Limited" runs past the sentence end.
    name = re.sub(r"\.\s+(?!(?i:ltd|limited|pvt|private|llp|inc|llc|gmbh|corp|corporation)\b).*$", "", name).strip()
    if len(name) < 4 or len(name) > 60 or not name[0].isupper() \
            or name.lower() in _COUNTRIES_AND_REGIONS \
            or re.search(r"(?i)subsidiar", name) or _SUB_GENERIC.match(name) \
            or _SUB_HOLDER.search(name) or re.search(r"['’]s\b", name) or _SUB_JUNK.search(name) \
            or re.search(r"\d", name) or _SUB_UNIT_TOKEN.search(name) \
            or (not _SUB_SUFFIX.search(name) and (len(name.split()) == 1 or len(name.split()) > 3)) \
            or re.fullmatch(r"(?i)(?:the\s+)?(?:company|listed\s+company|parent)", name) \
            or name.split()[0].strip(".,").lower() in _SUB_LEGAL_LEAD \
            or all(word.strip(".,;:").lower() in _SUB_STOP for word in name.split()):
        return None
    return name


def _subsidiary_names_from_span(span: str) -> list[str]:
    """Extract consecutive company names separated by commas/'and' from a subsidiary list span."""
    names: list[str] = []
    for item in _SUB_COMPANY_ITEM.finditer(span):
        cleaned = _valid_sub_name(item.group("item"))
        if cleaned and cleaned not in names:
            names.append(cleaned)
    return names


def _subsidiary_name(title: str, text: str) -> str | None:
    """The printed name(s) of the subsidiary receiving the order, or None for a bare 'a subsidiary'."""
    body = re.sub(r"\b(?:M/s\.?|Messrs\.?)\s+", "", _flat(f"{title} {(text or '')[:2500]}"), flags=re.I)
    for rx, name_first in ((_SUB_AFTER_NAME, True), (_SUB_BEFORE_NAME, False)):
        for match in rx.finditer(body):
            before = body[max(0, match.start() - 40): match.start()]
            if name_first:
                # "X, a subsidiary of Raymond Limited" is a third party's subsidiary unless X itself is receiving.
                tail = body[match.end(): match.end() + 140]
                if re.search(r"\b(?:from|awarded\s+by)\s+(?:M/s\.?\s+)?$", before, re.I):
                    continue
                if re.match(r"\s*of\s+", tail) \
                        and not re.match(r"\s*of\s+(?:the\s+|our\s+)?(?i:company|listed\s+company)\b", tail) \
                        and not re.search(
                            r"\b(?:has|have)\b[^.]{0,50}?\b(?:received|secured|won|bagged|awarded)\b", tail, re.I):
                    continue
                # Check for a multi-subsidiary list preceding the marker ("A Pvt Ltd, B Pvt Ltd and C Pvt Ltd — Subsidiaries").
                pre_start = max(0, match.start() - 280)
                pre_chunk = body[pre_start: match.start() + len(match.group("name"))]
                clause_split = re.split(r"(?:(?<=\bthat)|(?<=\bnamely)|(?<=\bas)|[:;])\s+", pre_chunk, flags=re.I)
                list_span = clause_split[-1] if clause_split else pre_chunk
                if re.search(r"\b(?:from|awarded\s+by)\s+(?:M/s\.?\s+)?$",
                             body[max(0, match.start() - len(list_span) - 35): match.start()], re.I):
                    continue
                multi = _subsidiary_names_from_span(list_span) if (
                    "subsidiaries" in match.group(0).lower() or re.search(r"(?:,|and)\s*$", body[pre_start:match.start()])
                ) else []
                if len(multi) >= 2:
                    window = body[:600] + body[max(0, match.start() - 240): match.end() + 180]
                    if re.search(r"(?i)\b(?:receiv|receipt|secur|bagg|won|order|contract|loa|loi|award)", window):
                        return "; ".join(multi)
            else:
                if re.search(r"\b(?:from|awarded\s+by)\s+(?:M/s\.?\s+)?$", before, re.I):
                    continue
                if "subsidiaries" in match.group(0).lower():
                    name_start = match.start("name")
                    after_span = _SUB_NAME_STOP.split(body[name_start: name_start + 320])[0]
                    multi = _subsidiary_names_from_span(after_span)
                    if len(multi) >= 2:
                        window = body[:600] + body[max(0, match.start() - 180): match.end() + 260]
                        if re.search(r"(?i)\b(?:receiv|receipt|secur|bagg|won|order|contract|loa|loi|award)", window):
                            return "; ".join(multi)
            name = _valid_sub_name(match.group("name"))
            if not name:
                continue
            # the subsidiary must sit in an order sentence, not a passing mention of the group structure.
            window = body[:600] + body[max(0, match.start() - 180): match.end() + 180]
            if not re.search(r"(?i)\b(?:receiv|receipt|secur|bagg|won|order|contract|loa|loi|award)", window):
                continue
            return name
    return None


def _l1_only(title: str, text: str) -> bool:
    """A lowest-bidder/L1 intimation with no award stated as received is not an order win yet.

    T-242 round 8: the L1 phrase sits in the annexure table past the first 600 characters (#5 "has issued a letter
    intimating ... as the L1 bidder"), and the title's "Receipt of Order" is not the award the rule asks for.
    """
    body = _flat(f"{title} {(text or '')[:2600]}")
    if not _LOWEST_BIDDER.search(body):
        return False
    return not _AWARD_RECEIVED.search(_flat((text or "")[:2600]))


def _self_setup_loi(clause: str) -> bool:
    """An LOI/LoA to set up the company's own outlet, dealership or showroom is not an order won (#28, #46, #54).

    A capacity project ("set up a 250 MW solar facility") stays an order: the capacity token disqualifies the
    brand-facility wording.
    """
    for match in _SELF_SETUP.finditer(clause or ""):
        tail = match.group(0).lower()
        if _CAPACITY_TOKEN.search(clause) and "facilit" in tail \
                and not re.search(r"outlet|dealership|showroom|3s", tail):
            continue
        return True
    return False


def _not_an_order(title: str, head: str) -> str | None:
    """Why this filing's "order" is not a customer order (T-242 round 8), or None when it is one.

    The company (or a named subsidiary) must RECEIVE or BE AWARDED a contract, LoA, LoI, work or purchase order
    from a counter-party.  An order issued BY an authority, a regulator's approval to launch a product, a
    board-meeting outcome or appointment, and an LOI to set up the company's own outlet are all vetoed here.
    """
    if _l1_only(title, head):
        return "l1_only: lowest bidder stated, no award received"
    for clause in [title, *_clauses(head)[:60]]:
        flat_clause = _flat(clause)
        if not flat_clause:
            continue
        if _REGULATOR_APPROVAL.search(flat_clause):
            return "regulator approval, not a customer order"
        if _AUTHORITY_ORDER_STRONG.search(flat_clause) or (
                _AUTHORITY_OFFICE.search(flat_clause) and not _AWARD_NOUN.search(flat_clause)):
            return "authority order, not a customer order"
        if _self_setup_loi(flat_clause):
            return "LOI/LoA to set up the company's own outlet, not an order"
    opening = _flat(f"{title} {head[:600]}")
    if _BOARD_OR_APPOINTMENT.search(opening) and not _AWARD_QUOTED.search(_flat(head)):
        return "board outcome or appointment, not an order"
    return None


_JOINT_RECEIVER = re.compile(
    r"\b(?:the\s+)?company\b[^.;]{0,100}?\band\b[^.;]{0,160}?"
    r"\b(?:subsidiar(?:y|ies)|step[-\s]?down\s+subsidiar(?:y|ies))\b[^.;]{0,120}?"
    r"\b(?:has|have)\s+(?:also\s+)?(?:received|secured|been\s+awarded)\b"
    r"|\b(?:the\s+)?(?:wholly[-\s]?owned|material|step[-\s]?down)\s+subsidiar(?:y|ies)\b[^.;]{0,120}?"
    r"\band\s+(?:the\s+)?company\b", re.I)
# "<Company> ... and ... subsidiary ... Rs A ... and ... Rs B ... respectively": A is the company's printed share.
_JOINT_SHARE = re.compile(
    r"\b(?:the\s+)?company\b[^;]{0,160}?\band\b[^;]{0,220}?"
    r"\b(?:subsidiar(?:y|ies)|step[-\s]?down)\b[^;]{0,200}?"
    r"\b(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?)"
    r"[^;]{0,100}?\band\b[^;]{0,80}?\b(?:Rs\.?|INR|₹)\s*(?P<v2>[\d,]+(?:\.\d+)?)"
    r"\s*(?P<u2>crores?|cr\.?|lakhs?|lacs?)", re.I)


def _joint_receiver(title: str, text: str) -> bool:
    """Does the company AND a subsidiary receive the order together (one joint group award)?"""
    return bool(_JOINT_RECEIVER.search(_flat(f"{title} {(text or '')[:2500]}")))


def _joint_share(title: str, text: str) -> tuple[float, str] | None:
    """The company's own printed share of a joint company + subsidiary award, when the filing splits the two."""
    match = _JOINT_SHARE.search(_flat(f"{title} {(text or '')[:2500]}"))
    if not match:
        return None
    amount = _to_cr(match.group("v"), match.group("u"))
    if amount is None:
        return None
    return amount, match.group(0)


def _names_subsidiary(value: Any, subsidiary: str | None) -> bool:
    """Is this printed awarder actually the group's subsidiary?  A subsidiary name is never the customer."""
    if not value or not subsidiary:
        return False
    left = set(_customer_key(value).split())
    right = [word for word in _customer_key(subsidiary).split() if len(word) >= 4]
    return bool(right) and all(word in left for word in right)


def _not_order_size(span: str | None, *sources: str) -> bool:
    """True when the printed amount sits beside a GDV/project-cost/target/guidance label (#39, #48, #54)."""
    needle = _flat(span)
    if not needle:
        return False
    for source in sources:
        flat = _flat(source)
        pos = flat.find(needle)
        if pos < 0:
            continue
        before = flat[max(0, pos - 60): pos]
        after = flat[pos + len(needle): pos + len(needle) + 40]
        first_digit = next((i for i, ch in enumerate(needle) if ch.isdigit()), len(needle))
        lead_in = needle[:first_digit]
        if _NOT_ORDER_SIZE_BEFORE.search(before) or _NOT_ORDER_SIZE_NEAR.search(f"{before} {lead_in}") \
                or _NOT_ORDER_SIZE_AFTER.search(f"{needle} {after}"):
            return True
    return False


def _foreign_value(*sources: str) -> str | None:
    """The printed value of an order in a currency we do not convert (EUR/GBP/JPY ...), exactly as printed."""
    for source in sources:
        match = _FOREIGN_VALUE.search(_flat(source))
        if match:
            return _flat(match.group(0))
    return None


def _order_value_from_text(text: str) -> tuple[float, str] | None:
    """A printed order/contract value row the prescribed table did not carry (a scanned or free-form letter)."""
    for rx in (_ORDER_SIZE_SENTENCE, _ORDER_VALUE_ROW, _ORDER_VALUE_LABEL):
        for match in rx.finditer(text or ""):
            value = _to_cr(match.group("v"), match.group("u"))
            if value is not None and not _not_order_size(match.group(0), text):
                return value, match.group(0)
    return None


def _is_buyer_side(title: str, text: str) -> bool:
    body = _flat(f"{title} {text}")
    return bool(_ORDER_BUYER.search(body) and not _WIN_FROM.search(body))


_PAST_ORDER_CLAUSE = re.compile(
    r"\b(?:(?:has|have|had)\s+(?:already\s+)?(?:been\s+)?(?:executed\s*(?:&|and)\s*delivered|delivered"
    r"|already\s+executed|previously\s+executed)"
    r"|(?:earlier|previous|prior)\s+(?:export\s+|purchase\s+|work\s+)?orders?)\b",
    re.I,
)
_NEW_ORDER_WIN_VERB = re.compile(
    r"\b(?:received|receives|secured|secures|bagged|bags|won|wins|awarded|additional\s+(?:\w+\s+)?order"
    r"|new\s+(?:\w+\s+)?order)\b",
    re.I,
)
_PAST_ORDER_PHRASE = re.compile(
    r"\b(?:(?:has|have|had)\s+(?:already\s+)?)?(?:executed\s*(?:&|and)\s*delivered|delivered"
    r"|already\s+executed|previously\s+executed)\b[^.;]{0,90}?\b(?:order|valued|worth)\b[^.;]{0,90}?"
    r"(?:Rs\.?|INR|₹|US\s?\$|\$)\s*[\d,]+(?:\.\d+)?(?:\s*(?:crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn))?"
    r"|\b(?:earlier|previous|prior)\s+(?:export\s+|purchase\s+|work\s+)?orders?\b[^.;]{0,90}?"
    r"(?:Rs\.?|INR|₹|US\s?\$|\$)\s*[\d,]+(?:\.\d+)?(?:\s*(?:crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn))?",
    re.I,
)


def _strip_past_order_values(text: str) -> str:
    """Remove past delivered/executed/earlier/previous order values so they cannot be picked as the new order."""
    if not text or not _PAST_ORDER_CLAUSE.search(text):
        return text
    kept: list[str] = []
    for clause in _clauses(text):
        if _PAST_ORDER_CLAUSE.search(clause) and not _NEW_ORDER_WIN_VERB.search(clause):
            continue
        kept.append(_PAST_ORDER_PHRASE.sub(" ", clause))
    return " ".join(kept)


def _loose_order_record(title: str, text: str) -> dict[str, Any] | None:
    """A free-form order letter (no prescribed table): a win sentence plus a printed "(e) Value" row."""
    clean_text = _strip_past_order_values(text[:2500])
    body = _flat(f"{title} {clean_text}")
    if _ORDER_VETO.search(body) or _is_buyer_side(title, text):
        return None
    win_in_title = bool(_WIN_VERB.search(title) and _ORDER_WORD.search(title))
    if not win_in_title and not re.search(
            r"\b(?:secured|received|awarded|bagged|won|obtained|entered\s+into)\b[^.]{0,140}?"
            r"\b(?:order|contract|letter\s+of\s+award|letter\s+of\s+acceptance|contract\s+agreement)\b",
            body, re.I):
        return None
    match = re.search(
        r"(?:\([a-z]\)\s*)?(?:value|contract\s+value|order\s+value|total\s+value|estimated\s+value"
        r"|broad\s+(?:commercial\s+)?consideration)\b[^.;]{0,90}?(?:Rs\.?|INR|₹)\s*"
        r"(?P<v>[\d,]+(?:\.\d+)?)\s*"
        r"(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)?", body, re.I)
    if match:
        amount = (_to_cr(match.group("v"), match.group("u")) if match.group("u")
                  else (round(_digits(match.group("v")) / 1e7, 4)
                        if len(re.sub(r"\D", "", match.group("v"))) >= 7 else None))
        value_text: str | None = match.group(0)
    else:
        fallback = _order_value_from_text(body)
        if fallback is None:
            return {"seq": 1, "awarder": None, "value_cr": None, "value_usd_mn": None, "value_text": None,
                    "duration_months": order_wins.months(text), "title_value_cr": None, "title_mismatch": 0,
                    "quote": _flat(text)[:400], "extractor_rule": "loose_order_v1"}
        amount, value_text = fallback
    customer = None
    for source in (_flat(clean_text), _flat(title)):
        named = re.search(r"(?:contract\s+agreement|order|contract)\s+(?:with|from|awarded\s+by)\s+([A-Z][^.;]{3,120})",
                          source)
        if named:
            customer = _flat(named.group(1))[:200]
            break
    return {"seq": 1, "awarder": customer, "value_cr": amount, "value_usd_mn": None, "value_text": value_text,
            "duration_months": order_wins.months(text), "title_value_cr": None, "title_mismatch": 0,
            "quote": _flat(text)[:400], "extractor_rule": "loose_order_v1"}


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One print of a figure can appear twice (cover letter + annexure): never sum it twice.

    Two genuine orders of the same value with different printed awarders stay two records (C5).
    """
    out: list[dict[str, Any]] = []
    for record in records:
        value = _sane_cr(record.get("value_cr"))
        usd = record.get("value_usd_mn")
        awarder = _clean_party(record.get("awarder"))
        duplicate = False
        for kept in out:
            if _sane_cr(kept.get("value_cr")) != value or kept.get("value_usd_mn") != usd:
                continue
            kept_awarder = _clean_party(kept.get("awarder"))
            if awarder == kept_awarder or not awarder or not kept_awarder:
                duplicate = True
                break
        if not duplicate:
            out.append(record)
    return out


def _order_kind(title: str, quote: str) -> str:
    """A new order stays a new order even when the press release also quotes the order book (ASIANENE 63)."""
    head = _flat(f"{title} {quote}")
    if _WIN_VERB.search(head) and re.search(r"\bnew\s+(?:order|contract)|secures?|secured|bagged|awarded"
                                             r"|received|receipt", head, re.I):
        return "new_order"
    return "order_book_update" if _ORDER_UPDATE.search(head) else "new_order"


def _tenure_years(text: str, execution_months: float | None) -> float | None:
    if execution_months:
        return execution_months / 12.0
    match = re.search(r"\bfrom\s+([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})\s+to\s+"
                      r"([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4})", _flat(text), re.I)
    if not match:
        return None

    def _day(raw: str) -> date | None:
        found = re.match(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", raw)
        if not found:
            return None
        month = _MONTHS.get(found.group(1).lower())
        if not month:
            return None
        try:
            return date(int(found.group(3)), month, int(found.group(2)))
        except ValueError:
            return None

    start, end = _day(match.group(1)), _day(match.group(2))
    if start and end and end > start:
        return (end - start).days / 365.25
    return None


def _issuer_tokens(text: str, symbol: str) -> set[str]:
    tokens: set[str] = set()
    if symbol and len(symbol) >= 3:
        tokens.add(symbol.upper()[:4])
    for m in re.finditer(
        r"\b(?:For(?:\s+and\s+on\s+behalf\s+of)?|The)\s+(?:M/s\.?\s+)?([A-Z][A-Za-z0-9&.'’\-]{3,})\b",
        text,
    ):
        word = m.group(1).upper().rstrip(".")
        if word not in {"COMPANY", "LIMITED", "INDIA", "PRIVATE", "BOARD", "EXCHANGE", "LISTING", "STOCK"}:
            tokens.add(word[:6] if len(word) >= 6 else word)
    return tokens


def _matches_issuer(span: str, tokens: set[str]) -> bool:
    up = span.upper()
    if re.search(r"\b(?:THE\s+)?COMPANY\b|\bOUR\b", up):
        return True
    return any(tok in up for tok in tokens)


def _consortium_share(text: str, symbol: str) -> tuple[float | None, float | None, str | None]:
    """(printed share %, printed share amount in crore, span) when the filing states the company's consortium share."""
    if not _CONSORTIUM.search(text):
        return None, None, None
    tokens = _issuer_tokens(text, symbol)
    pct_val: float | None = None
    for match in _CONSORTIUM_PCT.finditer(text):
        pct = match.group("p") or match.group("p3") or match.group("p4") or match.group("p2")
        if not pct:
            continue
        before = text[max(0, match.start() - 60): match.start()]
        subject = f"{before} {match.group(0)}"
        if not match.group("p") and tokens and not _matches_issuer(subject, tokens):
            continue
        pct_val = float(pct)
        break
    for match in _CONSORTIUM_AMOUNT.finditer(text):
        if tokens and not _matches_issuer(match.group(0), tokens):
            continue
        amount = _sane_cr(_to_cr(match.group("v"), match.group("u")))
        if pct_val is None:
            pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", match.group(0))
            if pct_m:
                pct_val = float(pct_m.group(1))
        return pct_val, amount, _flat(match.group(0))
    for match in _CONSORTIUM_AMOUNT_FULL.finditer(text):
        if tokens and not _matches_issuer(match.group(0), tokens):
            continue
        amount = _sane_cr(round(_digits(match.group("v")) / 1e7, 4))
        if pct_val is None:
            pct_m = re.search(r"(\d+(?:\.\d+)?)\s*%", match.group(0))
            if pct_m:
                pct_val = float(pct_m.group(1))
        rs_m = _RS_FULL.search(match.group(0))
        return pct_val, amount, _flat(rs_m.group(0) if rs_m else match.group(0))
    return pct_val, None, None


_FILING_TOTAL = re.compile(
    r"\b(?:total|aggregate)\s+(?:order\s+|contract\s+)?value\b(?:\s+of\s+order\s+is)?[^.;]{0,30}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?|millions?|mn|billions?|bn)\b"
    r"|\b(?:aggregat\w*|totall?\w*)\s+(?:orders?\s+)?(?:worth|to|of)\s+(?:Rs\.?|INR|₹)\s*"
    r"(?P<v2>[\d,]+(?:\.\d+)?)\s*(?P<u2>crores?|cr\.?|lakhs?|lacs?|millions?|mn|billions?|bn)\b"
    # the aggregate is printed in full rupees with no unit word ("is ₹ 2,14,27,36,930/-")
    r"|\b(?:total|aggregate)\s+(?:order\s+|contract\s+)?value\b[^.;]{0,80}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<v3>\d[\d,]{6,})(?:\s*/-)?",
    re.I)


def _filing_total_cr(title: str, text: str) -> float | None:
    match = _FILING_TOTAL.search(_flat(f"{title} {text[:2500]}"))
    if not match:
        return None
    val = match.group("v") or match.group("v2")
    unit = match.group("u") or match.group("u2")
    if val and unit:
        return _sane_cr(_to_cr(val, unit))
    full = match.group("v3")
    return round(_digits(full) / 1e7, 4) if full else None


def order_fields(title: str, text: str, symbol: str = "",
                 records_override: list[dict[str, Any]] | None = None,
                 allow_body_customer: bool = True,
                 filing_total_cr: float | None = None) -> dict[str, Any] | None:
    """One order event: the size, customer and execution period, with annual/consortium handling."""
    clean_text = _strip_past_order_values(text)
    if records_override is not None:
        records = records_override
    else:
        if _ORDER_VETO.search(_flat(f"{title} {text}")) or _is_buyer_side(title, text) \
                or _not_an_order(title, text):
            return None
        records = order_wins.parse(_flat(title), _flat(clean_text))
        if not records:
            loose = _loose_order_record(title, text)
            if loose is None:
                return None
            records = [loose]
        records = _dedupe_records(records)
    valued = [r for r in records if r.get("value_cr") is not None or r.get("value_usd_mn") is not None]
    inr = [value for value in (_sane_cr(r["value_cr"]) for r in records if r.get("value_cr") is not None)
           if value is not None]
    usd = [r["value_usd_mn"] for r in records if r.get("value_usd_mn") is not None]
    amount: float | None = None
    usd_mn: float | None = None
    detail = ""
    value_text = "; ".join(str(r.get("value_text") or "") for r in valued if r.get("value_text")) or None
    derived = 0
    if len(records) == 1:
        amount, usd_mn = _sane_cr(records[0].get("value_cr")), records[0].get("value_usd_mn")
        value_text = records[0].get("value_text")
    elif len(inr) == len(records):
        if valued and not valued[0].get("title_mismatch") and valued[0].get("title_value_cr") is not None:
            amount = _sane_cr(valued[0]["title_value_cr"])
            match = _RS_AMOUNT.search(title or "")
            value_text = match.group(0) if match else value_text
        else:
            amount, derived = round(sum(inr), 4), 1
    elif len(usd) == len(records):
        usd_mn = round(sum(usd), 4)
    if amount is None and usd_mn is None:
        fallback = _order_value_from_text(_flat(clean_text))
        if fallback:
            amount, value_text = fallback
            derived = 0
    # T-242 round 8: a GDV, project cost, order-book target or guidance figure is never the order's size.
    if (amount is not None or usd_mn is not None) and _not_order_size(value_text, title, text):
        amount = usd_mn = None
        derived = 0
        fallback = _order_value_from_text(_flat(clean_text))
        if fallback:
            amount, value_text = fallback
    quote = _flat(records[0].get("quote")) or _flat(value_text) or ""
    if value_text and _flat(value_text) in _flat(text):
        match = re.search(re.escape(_flat(value_text)), _flat(text))
        if match:
            quote = _around(_flat(text), match)
    if amount is None and usd_mn is None:
        foreign = _foreign_value(str(records[0].get("value_text") or ""), _flat(value_text), _flat(clean_text))
        if foreign:
            value_text = foreign
            detail = f"printed in a non-INR/non-USD currency ({foreign}); not converted without a printed rate"
    subsidiary = _subsidiary_name(title, text)
    customers: list[str] = []

    def add_customer(value: str | None) -> None:
        if value and not _names_subsidiary(value, subsidiary):
            customers.append(value)

    # Prefer the annexure's 'Name of the entity awarding' over title/body guesses (T-242 round 7).
    for record in records:
        if record.get("extractor_rule") == "loose_order_v1":
            continue
        add_customer(_clean_party(record.get("awarder"), from_annexure=True))
    if not customers and allow_body_customer:
        for raw in _annexure_awarders(text):
            add_customer(_clean_party(raw, from_annexure=True))
    if not customers:
        for record in records:
            if record.get("extractor_rule") != "loose_order_v1":
                continue
            add_customer(_clean_party(record.get("awarder"), from_annexure=False))
    if not customers and allow_body_customer:
        named = re.search(
            r"(?:(?:work\s+order|order|contract|letter\s+of\s+award)"
            r"[^.;|]{0,140}?\bfrom|(?:sub-?\s*contract|contract\s+agreement)[^.;|]{0,40}?\bwith)\s+"
            r"(?:M/s\.?\s+)?([A-Z](?:[^.;,|]|\.(?=[A-Za-z0-9])|(?<=\b[A-Z])\.(?=\s+(?:\(|towards|for|worth|amounting|dated|on))){2,100})",
            _flat(clean_text), re.I)
        if named:
            add_customer(_clean_party(named.group(1), from_annexure=False))
    if not customers and allow_body_customer:
        for match in _FROM_ENTITY.finditer(_flat(clean_text)):
            add_customer(_clean_party(match.group("name"), from_annexure=False))
            if customers:
                break
    if not customers and allow_body_customer:
        # "the order ... is to be supplied to the <X> consortium" names the awarder in prose, not in a row.
        consortium = re.search(
            r"\b(?:to\s+be\s+)?(?:supplied|supply|delivered|delivery|executed|exported)\s+to\s+(?:the\s+)?"
            r"(?P<name>[A-Z][^;.]{2,90}?\bconsortium)\b", _flat(clean_text))
        if consortium:
            add_customer(_clean_party(consortium.group("name"), from_annexure=False))
    months = {r["duration_months"] for r in records if r.get("duration_months") is not None}
    execution_months = months.pop() if len(months) == 1 else None
    if execution_months is None:
        period = re.search(r"(\d{1,2}(?:\.\d+)?)\s*[- ]?\s*(years?|months?)[^.;]{0,30}?"
                           r"\b(?:duration|contract|period|execution)", _flat(text), re.I)
        if period:
            execution_months = float(period.group(1)) * (12.0 if period.group(2).lower().startswith("year") else 1.0)
    value_words = _flat(f"{value_text or ''} {quote} {text}")
    value_annual: float | None = None
    value_total: float | None = filing_total_cr
    share_pct: float | None = None
    if amount is not None:
        # T-242 round 8: a company AND a subsidiary awarded together is a joint group order; when the filing
        # splits the printed amounts ("Company ... Rs 300 cr and NPC ... Rs 700 cr respectively"), the event is
        # the company's own share, never the group total (#44).
        if _joint_receiver(title, text):
            joint = _joint_share(title, text)
            if joint is not None and abs(joint[0] - amount) > 0.005 * max(1.0, amount):
                value_total, amount, value_text = amount, joint[0], joint[1]
                detail = "joint company + subsidiary order; the company's printed share"
        # T-242: the title prints the aggregate and the table prints one item of it ("secures 214.27 crore from
        # TPSODL & TPWODL", table 115.0194 + 99.2543): the event is the printed aggregate, not one item.
        aggregate = _sane_cr(records[0].get("title_value_cr")) if len(records) == 1 else None
        if aggregate is not None and records[0].get("title_mismatch"):
            printed_total = filing_total_cr if filing_total_cr is not None else _filing_total_cr(title, text)
            if printed_total is not None and abs(aggregate - printed_total) <= 0.005 * max(1.0, printed_total) \
                    and abs(amount - aggregate) > 0.005 * max(1.0, aggregate):
                value_total, amount = aggregate, aggregate
                match = _RS_AMOUNT.search(title or "")
                value_text = match.group(0) if match else value_text
                detail = "title aggregate; the table prints one item of it"
        share_pct, share_amount, share_span = _consortium_share(value_words, symbol)
        if share_amount is not None:
            if abs(amount - share_amount) > 0.005 * max(1.0, share_amount):
                value_total, amount = amount, share_amount
            if share_span:
                value_text = share_span
            pct_note = f"{share_pct:g}% " if share_pct is not None else ""
            gross_note = f" (gross value Rs. {value_total:g} cr)" if value_total and value_total > amount else ""
            detail = f"JV/consortium {pct_note}share{gross_note}"
        elif share_pct is not None:
            value_total, amount, derived = amount, round(amount * share_pct / 100.0, 4), 1
            detail = f"consortium share {share_pct:g}% of the printed total"
        ten_years = _tenure_years(text, execution_months)
        annual = bool(_ANNUAL_CUE.search(_flat(f"{value_text or ''} {quote}")))
        monthly = bool(re.search(r"\bmonthly\b|\bper\s+month\b", _flat(f"{value_text or ''} {quote}"), re.I))
        if annual:
            value_annual = amount
            if ten_years:
                value_total = round(amount * ten_years, 4)
                amount, derived = value_total, 1
                detail = "annual value x printed tenure (computed)"
            else:
                derived = 1
                detail = "annual value; tenure not printed, not a total"
        elif monthly and execution_months:
            value_total = amount = round(amount * execution_months, 4)
            derived = 1
            detail = "monthly value x execution months (computed)"
    described = [name for name in dict.fromkeys(customers) if _is_customer_description(name)]
    customers = [name for name in dict.fromkeys(customers) if not _is_customer_description(name)]
    return {
        "amount_inr_cr": amount, "amount_usd_mn": usd_mn, "value_text": value_text,
        "value_annual": value_annual, "value_total": value_total, "share_pct": share_pct,
        "customer": "; ".join(customers)[:300] or None,
        "customer_desc": "; ".join(described)[:300] or None,
        "execution_months": execution_months,
        "order_kind": _order_kind(title, quote),
        "quote": quote[:MAX_QUOTE] or None,
        "detail_hint": detail,
        "derived": derived,
    }


_PROSE_AMOUNT = re.compile(
    r"\bfrom\s+(?P<customer>(?:the\s+)?[A-Z][^.]{3,400}?)\s+for\s+an\s+amount\s+of\s+(?:Rs\.?|INR|₹)\s*"
    r"(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|lakhs?|lacs?)?", re.I)
_ITEM_LOA_AMOUNT = re.compile(
    r"(?:\bworth|\bfor(?:\s+an\s+amount\s+of)?)\s+(?:Rs\.?|INR|₹)\s*(?P<v>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<u>crores?|cr\.?|lakhs?|lacs?)?(?:\s*/-)?[^.;\n]{0,90}?"
    r"\bvide\s+(?:LOA|LOI|PO(?:\s+No\.?)?|Purchase\s+Order|Work\s+Order)\b",
    re.I)


def _prose_order_records(title: str, text: str) -> list[dict[str, Any]]:
    """Two or more LOAs printed as prose in one filing ("from X ... for an amount of Rs A"), one record each."""
    body = _flat(text)
    if _is_buyer_side(title, text) or not _ORDER_WORD.search(body):
        return []
    records: list[dict[str, Any]] = []
    for match in _PROSE_AMOUNT.finditer(body):
        raw, unit = match.group("v"), match.group("u")
        amount = _to_cr(raw, unit) if unit else (round(_digits(raw) / 1e7, 4) if len(re.sub(r"\D", "", raw)) >= 7
                                                 else None)
        if amount is None:
            continue
        customer = _clean_party(match.group("customer"))
        tail = body[match.end():match.end() + 220]
        records.append({
            "seq": len(records) + 1, "awarder": customer, "value_cr": amount, "value_usd_mn": None,
            "value_text": match.group(0)[-120:], "duration_months": order_wins.months(tail),
            "title_value_cr": None, "title_mismatch": 0, "quote": match.group(0)[-300:],
            "extractor_rule": "prose_orders_v1",
        })
    if len({round(float(r["value_cr"]), 4) for r in records}) < 2:
        item_records: list[dict[str, Any]] = []
        annex_customers = [_clean_party(c, from_annexure=True) for c in _annexure_awarders(text)]
        for idx, match in enumerate(_ITEM_LOA_AMOUNT.finditer(body)):
            raw, unit = match.group("v"), match.group("u")
            amount = _to_cr(raw, unit) if unit else (round(_digits(raw) / 1e7, 4)
                                                     if len(re.sub(r"\D", "", raw)) >= 7 else None)
            if amount is None:
                continue
            val_m = _RS_AMOUNT.search(match.group(0)) or _RS_FULL.search(match.group(0))
            vtext = val_m.group(0) if val_m else match.group(0)[:80]
            cust = annex_customers[idx] if idx < len(annex_customers) else None
            if cust is None and len(annex_customers) == 1:
                cust = annex_customers[0]
            tail = body[match.end():match.end() + 180]
            item_records.append({
                "seq": len(item_records) + 1, "awarder": cust, "value_cr": amount, "value_usd_mn": None,
                "value_text": vtext, "duration_months": order_wins.months(tail),
                "title_value_cr": None, "title_mismatch": 0, "quote": match.group(0)[:300],
                "extractor_rule": "item_loa_orders_v1",
            })
        if len({round(float(r["value_cr"]), 4) for r in item_records}) >= 2:
            return item_records
    distinct = {round(float(record["value_cr"]), 4) for record in records}
    return records if len(distinct) >= 2 else []


def order_rows(title: str, text: str, symbol: str = "",
               exclude_amounts: set[float] | None = None,
               head: str | None = None) -> list[dict[str, Any]]:
    """One row per order in the filing (C5); a repeated cover/annexure figure stays one row."""
    veto_text = _flat(f"{title} {head if head is not None else text}")
    if _ORDER_VETO.search(veto_text) or _RESULTS_RELEASE.search(_flat(f"{title} {(head or text)[:1500]}")) \
            or _ORDER_ROLLUP.search(veto_text) or _ORDER_INFLOW_TITLE.search(title) \
            or _is_buyer_side(title, head or text) or _not_an_order(title, head or text):
        return []
    clean_text = _strip_past_order_values(text)
    clean_head = _strip_past_order_values(head) if head is not None else clean_text
    records = order_wins.parse(_flat(title), _flat(clean_text))
    prose = _prose_order_records(title, clean_text)
    if len(prose) > len(records):
        records = prose
    loose = _loose_order_record(title, clean_head)
    if not records or (not any(r.get("value_cr") is not None or r.get("value_usd_mn") is not None
                               for r in records) and loose is not None):
        records = [loose] if loose else records
    if exclude_amounts:
        def _kept(record: dict[str, Any]) -> bool:
            value = _sane_cr(record.get("value_cr"))
            if value is None:
                return True
            return not any(abs(value - other) <= 1e-4 * max(1.0, other) for other in exclude_amounts)

        records = [record for record in records if _kept(record)]
    records = _dedupe_records(records)
    if not records:
        return []
    if len(records) == 1:
        fields = order_fields(title, text, symbol, records_override=records)
        return [fields] if fields else []
    total_cr = _filing_total_cr(title, head or text)
    annex_customers = _annexure_awarders(text)
    rows: list[dict[str, Any]] = []
    for idx, record in enumerate(records):
        if not record.get("awarder") and idx < len(annex_customers):
            record = {**record, "awarder": annex_customers[idx]}
        fields = order_fields(title, text, symbol, records_override=[record],
                              allow_body_customer=False, filing_total_cr=total_cr)
        if fields:
            rows.append(fields)
    return rows


def _amendment_customer(title: str, head: str, text: str) -> str | None:
    for raw in _annexure_awarders(text):
        cleaned = _clean_party(raw, from_annexure=True)
        if cleaned:
            return cleaned
    combined = _flat(f"{title} {head[:2500]}")
    for rx in (
        r"(?:work\s+order|purchase\s+order|order|contract|loa|loi)\s+(?:worth[^.;]{0,80}?\s+)?"
        r"(?:received\s+)?(?:from|awarded\s+by|by)\s+(?:M/s\.?\s+)?"
        r"([A-Z](?:[^.;,]|\.(?=[A-Za-z0-9])|(?<=\b[A-Z])\.(?=\s)){2,100})",
        r"([A-Z][A-Za-z0-9&.'’\s()-]{2,80}?)\s+has\s+(?:further\s+)?decided\s+to\s+(?:reduce|cancel|withdraw|short[-\s]?close)",
    ):
        for match in re.finditer(rx, combined, re.I):
            raw = re.sub(r"^.*?\b(?:inform(?:\s+you)?\s+that|that)\s+", "", match.group(1), flags=re.I)
            raw = re.sub(r"\s+(?:Pursuant\s+to|Dear\s+Sir|Ref\s*[.:]|In\s+terms\s+of)\b.*$", "",
                         raw, flags=re.I)
            cleaned = _clean_party(raw, from_annexure=False)
            if cleaned:
                return cleaned
    return None


def order_amendment_fields(title: str, head: str, text: str) -> dict[str, Any] | None:
    """An amendment/variation/extension/cancellation/reduction of an existing order: signed delta, never a new order."""
    base = _order_amendment_clause(title, head)
    if base is None:
        return None
    is_cancel_reduce = bool(_CANCEL_REDUCE_CUE.search(base) or _CANCEL_REDUCE_CUE.search(title))
    match = _AMEND_FROM_TO.search(base) if is_cancel_reduce else (_AMEND_FROM_TO.search(base) or _AMEND_FROM_TO.search(text))
    lenient = None if (match or is_cancel_reduce) else (_AMEND_FROM_TO_LENIENT.search(base) or _AMEND_FROM_TO_LENIENT.search(text))
    value_annual = value_total = share_pct = None
    detail = ""
    chosen = match or lenient
    if chosen is not None:
        if match is not None:
            old = _to_cr(match.group("a"), match.group("au"))
            new = _to_cr(match.group("b"), match.group("bu"))
        else:
            old = round(float(chosen.group("a").replace(",", "")), 4)
            new = round(float(chosen.group("b").replace(",", "")), 4)
        if old is None or new is None:
            return None
        amount, derived = round(new - old, 4), 1
        value_text = chosen.group(0)
        value_total = new
        detail = "amendment increment = printed new total - printed old total (computed)"
    else:
        aggregate = _AMEND_AGGREGATE.search(base) or (None if is_cancel_reduce else _AMEND_AGGREGATE.search(text))
        full_aggregate = None if (aggregate or is_cancel_reduce) else (
            _AMEND_AGGREGATE_FULL.search(base) or _AMEND_AGGREGATE_FULL.search(text))
        if aggregate:
            amount = _to_cr(aggregate.group("v"), aggregate.group("u"))
            value_text, derived = aggregate.group(0), 0
            value_total = None if is_cancel_reduce else amount
        elif full_aggregate:
            amount = round(_digits(full_aggregate.group("v")) / 1e7, 4)
            value_text, derived = full_aggregate.group(0), 0
            value_total = None if is_cancel_reduce else amount
        else:
            amounts = [(value, span) for value, span, _start in _amounts_rs(base)]
            amounts += [(round(_digits(m.group("v")) / 1e7, 4), m.group(0))
                        for m in _RS_FULL.finditer(base)]
            distinct = {round(value, 4) for value, _span in amounts}
            if not distinct:
                return None
            amount = round(sum(distinct), 4) if len(distinct) > 1 else next(iter(distinct))
            value_text = "; ".join(dict.fromkeys(span for _v, span in amounts))
            derived = 1 if len(distinct) > 1 else 0
            value_total = None if is_cancel_reduce else amount
            detail = "variation increment" if len(distinct) == 1 else "sum of distinct printed variation increments"
    if is_cancel_reduce and amount is not None and amount > 0:
        amount = -amount
        if not detail:
            detail = "order cancelled/reduced (negative amount)"
    quote = _flat(base)
    return {
        "amount_inr_cr": amount, "amount_usd_mn": None, "value_text": value_text,
        "value_annual": value_annual, "value_total": value_total, "share_pct": share_pct,
        "customer": _amendment_customer(title, head, text), "execution_months": order_wins.months(text),
        "order_kind": None, "quote": quote[:MAX_QUOTE] or None, "detail_hint": detail, "derived": derived,
        "_base_value": _to_cr(match.group("a"), match.group("au")) if match else None,
    }


_CAPEX_FROM_TO = re.compile(
    r"\bfrom\s+(?:Rs\.?|INR|₹)\s*(?P<a>[\d,]+(?:\.\d+)?)\s*(?P<au>crores?|cr\.?|lakhs?|million|mn)"
    r"[^.;]{0,40}?\bto\s+(?:Rs\.?|INR|₹)\s*(?P<b>[\d,]+(?:\.\d+)?)\s*(?P<bu>crores?|cr\.?|lakhs?|million|mn)\b",
    re.I)
_CAPEX_REVISED_VIS = re.compile(
    r"\brevis(?:ed|ion)\b[^.;]{0,120}?\bto\s+(?:Rs\.?|INR|₹)\s*(?P<b>[\d,]+(?:\.\d+)?)\s*(?P<bu>crores?|cr\.?|lakhs?|million|mn)"
    r"[^.;]{0,90}?\b(?:vis(?:\s*-\s*|\s+)[àa](?:\s*-\s*|\s+)vis|against|over|from)\b[^.;]{0,70}?"
    r"(?:Rs\.?|INR|₹)\s*(?P<a>[\d,]+(?:\.\d+)?)\s*(?P<au>crores?|cr\.?|lakhs?|million|mn)\b",
    re.I,
)


def capex_fields(title: str, head: str, text: str) -> dict[str, Any] | None:
    """The approved capex amount, its purpose clause and any printed completion phrase.

    ``None`` when no clause sanctions a spend (the classifier then does not fire); a sanctioned clause whose
    amount sits elsewhere returns fields with ``amount_inr_cr=None`` so the model may read that filing once.
    """
    if _CAPEX_VETO.search(_flat(f"{title} {head}")):
        return None
    strict_results = bool(
        _RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}"))
        or _HAS_FIN_RESULTS.search(_flat(f"{title} {head[:1500]}"))
    )
    sentences = [title] + _clauses(text)
    base = _capex_clause(title, head)
    if base is None:
        if strict_results or not _capex_candidate(title, head):
            return None
        base = next((s for s in sentences if _CAPEX_STRONG.search(s) and _RS_AMOUNT.search(s)
                     and not _FINANCIAL_METRIC.search(s)
                     and not (_RAISE_CUE.search(s)
                              and not re.search(r"capital\s+expenditure|capex|project\s+cost", s, re.I))), None)
        if base is None:
            return None
    revised = _CAPEX_FROM_TO.search(base) or _CAPEX_REVISED_VIS.search(base)
    if revised:
        old = _to_cr(revised.group("a"), revised.group("au"))
        new = _to_cr(revised.group("b"), revised.group("bu"))
        if old is not None and new is not None and new != old:
            completion = _COMPLETION.search(text)
            delta = round(new - old, 4)
            return {
                "amount_inr_cr": new, "value_text": revised.group(0),
                "purpose": _flat(base)[:300],
                "completion": _flat(completion.group(0))[:100] if completion else None,
                "quote": _flat(base)[:MAX_QUOTE],
                "detail_hint": f"cost revision: prior Rs {old:g} cr -> Rs {new:g} cr (delta {delta:+g} cr)",
                "derived": 0,
            }
    match = _RS_AMOUNT.search(base)
    winner = base
    if match is None and not strict_results:
        index = next((i for i, sentence in enumerate(sentences) if sentence == base), 0)
        for sentence in sentences[index:index + 4]:
            if _CAPEX_AMOUNT_CUE.search(sentence) and not _FINANCIAL_METRIC.search(sentence):
                match = _RS_AMOUNT.search(sentence)
                if match:
                    winner = sentence
                    break
    if match is None and not strict_results:
        title_match = _RS_AMOUNT.search(title or "")
        if title_match and _CAPEX_CUE.search(title or "") and not _FINANCIAL_METRIC.search(title or ""):
            match, winner = title_match, title
    if match is None and not strict_results:
        # one distinct spend named in a clause that also speaks of capex/approval; a results bundle has many
        # amounts, so two or more distinct values means the script stays unsure and the row goes to the model.
        found: dict[float, str] = {}
        for sentence in sentences:
            if _FINANCIAL_METRIC.search(sentence):
                continue
            amount = _RS_AMOUNT.search(sentence)
            if amount and (_CAPEX_CUE.search(sentence) or _APPROVE.search(sentence)):
                found.setdefault(round(_to_cr(amount.group("v"), amount.group("u")) or -1.0, 4), sentence)
        if len(found) == 1:
            winner = next(iter(found.values()))
            match = _RS_AMOUNT.search(winner)
    if match is None:
        return {"amount_inr_cr": None, "purpose": _flat(base)[:300], "quote": _flat(base)[:MAX_QUOTE],
                "completion": None, "value_text": None, "derived": 0}
    value = _to_cr(match.group("v"), match.group("u"))
    if value is None:
        return {"amount_inr_cr": None, "purpose": _flat(base)[:300], "quote": _flat(base)[:MAX_QUOTE],
                "completion": None, "value_text": None, "derived": 0}
    anchor = _flat(winner)[:80]
    flat_text = _flat(text)
    pos = flat_text.find(anchor) if anchor else -1
    window = flat_text[pos:pos + 500] if pos >= 0 else _flat(winner)
    completion = _COMPLETION.search(window)
    return {
        "amount_inr_cr": value, "value_text": match.group(0),
        "purpose": _flat(base)[:300],
        "completion": _flat(completion.group(0))[:100] if completion else None,
        "quote": _flat(winner)[:MAX_QUOTE],
        "derived": 0,
    }


def _printed_event_date(text: str) -> str | None:
    """A date the sentence prints ("commissioned on 12 Dec 2025", "w.e.f. 1 July 2026"), as ISO."""
    body = _flat(text)
    match = re.search(r"\b(?:on|w\.e\.f\.?|with\s+effect\s+from)\s+(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})", body, re.I)
    if not match:
        match = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9}),?\s+(\d{4})", body, re.I)
    if not match:
        return None
    month = _MONTHS.get(match.group(2).lower().rstrip("."))
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1))).isoformat()
    except ValueError:
        return None


def _is_stale_commissioning_clause(clause: str, filing_date: str | None) -> bool:
    """True when the clause dates the commissioning >90 days before ``filing_date`` (restated history).

    T-242: a numeric date the clause prints for the capacity ("vide our letter dated 01.08.2018") is the
    commissioning date; more than 12 months before the filing it is restated history (#6).
    """
    if not filing_date:
        return False
    try:
        filed = date.fromisoformat(str(filing_date))
    except ValueError:
        return False
    body = _flat(clause)
    for pattern in (r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"):
        for m in re.finditer(pattern, body):
            parts = [int(m.group(i)) for i in range(1, 4)]
            try:
                dt = date(parts[2], parts[1], parts[0]) if pattern.startswith(r"\b(\d{1,2})") \
                    else date(parts[0], parts[1], parts[2])
            except ValueError:
                continue
            if (filed - dt).days > 365:
                return True
    month_abbr = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
        **{k: v for k, v in _MONTHS.items()},
    }
    ref_prefix = re.compile(r"(?:letter|intimation|approval|notice|circular|order)\s+dated\s*$", re.I)
    for m in re.finditer(
        r"(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(\d{4})", body, re.I
    ):
        if ref_prefix.search(body[max(0, m.start() - 30):m.start()]):
            continue
        mon = month_abbr.get(m.group(2).lower().rstrip("."))
        if not mon:
            continue
        try:
            dt = date(int(m.group(3)), mon, int(m.group(1)))
        except ValueError:
            continue
        if (filed - dt).days > 90:
            return True
    for m in re.finditer(
        r"\b(?:in|since|from)\s+([A-Za-z]{3,9})[,']?\s+(\d{4})\b", body, re.I
    ):
        mon = month_abbr.get(m.group(1).lower().rstrip("."))
        if not mon:
            continue
        year = int(m.group(2))
        last_day = calendar.monthrange(year, mon)[1]
        if (filed - date(year, mon, last_day)).days > 90:
            return True
    return False


def _pick_capacity_match(sentence: str) -> re.Match[str] | None:
    """Pick the commissioned unit's capacity in ``sentence``, skipping host-plant or project-name sizes."""
    matches = list(_CAPACITY_VALUE.finditer(sentence or ""))
    if not matches:
        return None
    kept: list[re.Match[str]] = []
    for m in matches:
        before = sentence[max(0, m.start() - 45):m.start()]
        after = sentence[m.end():m.end() + 45]
        if re.search(r"\bat\s+(?:its|the|our)\s+(?:existing\s+)?$", before, re.I) \
                and re.match(r"^\s*(?:[A-Z][A-Za-z0-9&'-]*\s+){0,3}(?:Refinery|Plant|Complex|Facility|Factory)\b", after, re.I):
            continue
        if len(matches) > 1:
            if re.search(r'["“][^"”]{0,30}$', before) and re.search(r'^\s*(?:Solar\s+Power\s+)?Project["”]', after, re.I):
                continue
            if re.search(r"\b(?:towards|target|overall|total\s+installed|designed\s+to\s+reach|future)\b[^.;]{0,30}$",
                         before, re.I):
                continue
        kept.append(m)
    return kept[0] if kept else None


def capacity_fields(title: str, head: str, text: str,
                    filing_date: str | None = None) -> dict[str, Any] | None:
    """The capacity a completed commissioning adds, with its unit and (when printed) the plant.

    "enhanced to 174 mtpa from 170 mtpa" adds 4 mtpa: the delta is what the factor needs, and it is a
    derived figure (both ends printed), so the row is ``unverified`` with both ends in ``value_text``.
    """
    if _CAPACITY_VETO.search(_flat(f"{title} {head[:1500]}")):
        return None
    subject, first_sents = _subject_and_first_sentences(title, head, count=2)
    if _CAPACITY_REJECT_CLAUSE.search(title or "") and not _COMM_VERB.search(title or ""):
        return None
    if subject and _CAPACITY_REJECT_CLAUSE.search(subject) and not _COMM_VERB.search(subject):
        return None
    has_comm_gate = any(
        _COMM_VERB.search(s) or re.search(r"\binaugurated\s+(?:its|the|a)\b", s, re.I)
        for s in (title or "", subject, *first_sents) if s
    )
    if not has_comm_gate:
        return None
    sentences = [title] + _clauses(head)
    winner = next(
        (s for s in sentences
         if _CAPACITY_CUE.search(s) and not _CAPACITY_REJECT_CLAUSE.search(s)
         and not _CAPACITY_FORWARD.search(s)
         and not re.search(r"\bplanned\b|\bplan\s+to\b", s, re.I)
         and not _is_stale_commissioning_clause(s, filing_date)
         and _pick_capacity_match(s) is not None),
        None,
    )
    cap_source = winner
    if winner is None:
        # When the commissioning sentence does not print the unit's own capacity (e.g. host refinery size only,
        # or Reg 30 table / following sentence states "installed capacity addition 120 KL"), accept an explicit
        # installed-capacity sentence in the same commissioning filing.
        comm_idx = next(
            (i for i, s in enumerate(sentences)
             if i > 0 and _COMM_VERB.search(s) and not _CAPACITY_REJECT_CLAUSE.search(s)
             and not _CAPACITY_FORWARD.search(s)
             and not _is_stale_commissioning_clause(s, filing_date)),
            None,
        )
        if comm_idx is not None:
            winner = sentences[comm_idx]
            for j in range(comm_idx + 1, min(len(sentences), comm_idx + 6)):
                cand = sentences[j]
                if _CAPACITY_REJECT_CLAUSE.search(cand) or _CAPACITY_FORWARD.search(cand):
                    continue
                if re.search(r"\bexisting\s+capacity\b", cand, re.I) and not re.search(r"\baddition\b", cand, re.I):
                    continue
                if re.search(r"\b(?:with\s+a\s+capacity\s+of|installed\s+capacity(?:\s+addition)?|capacity\s+addition)\b",
                             cand, re.I) and _pick_capacity_match(cand) is not None:
                    cap_source = cand
                    break
            if cap_source is winner:
                winner = None
    past = re.search(
        r"has\s+(?:successfully\s+)?been\s+commissioned|has\s+successfully\s+commissioned|successfully\s+commissioned"
        r"|successful\s+commissioning\s+of|commissioning\s+of|commissioned\s+(?:on|the|its|a|an|\d)"
        r"|commenced\s+(?:commercial\s+)?(?:operations?|production)|commencement\s+of\s+(?:commercial\s+)?(?:operations?|production)"
        r"|started\s+(?:commercial\s+)?(?:production|operations?)|put\s+to\s+use|synchroni[sz]ed|\bCOD\b",
        f"{title} {subject} {winner or ''}", re.I,
    )
    if winner is None or cap_source is None or (_CAPACITY_FORWARD.search(head) and not past):
        return None                   # a plan ("expected to be commissioned") is not a completed commissioning
    if _CAPACITY_APPROVED.search(winner) and not past:
        return None                   # "approved setting up" / "proposed capacity addition" is a plan
    value: float | None = None
    unit = ""
    value_text = ""
    derived = 0
    span = _CAPACITY_TO_FROM.search(cap_source) or _CAPACITY_FROM_TO.search(cap_source)
    if span:
        try:
            new = float(span.group("new").replace(",", ""))
            old = float(span.group("old").replace(",", ""))
        except ValueError:
            new = old = 0.0
        if new > old:
            value, unit, derived = new - old, _canon_capacity_unit(span.group("u")), 1
            value_text = span.group(0)
    if value is None:
        match = _pick_capacity_match(cap_source)
        if match is None:
            return None
        try:
            value = float(match.group("v").replace(",", ""))
        except ValueError:
            return None
        unit, value_text = _canon_capacity_unit(match.group("u")), match.group(0)
    if re.search(r"MT\s*/\s*M\b|MT\s+per\s+month|tonnes?\s+per\s+month", cap_source, re.I):
        unit = "mt_per_month"
    plant = _plant(winner) or _plant(subject) or _plant(title)
    return {
        "capacity_value": value, "capacity_unit": unit, "value_text": value_text,
        "event_date": _printed_event_date(winner),
        "plant": plant, "quote": _flat(winner)[:MAX_QUOTE], "derived": derived,
    }


_SHARES_BAD_CONTEXT = re.compile(
    r"authorised|authorized|paid[-\s]?up\s+capital|paid[-\s]?up\s+share\s+capital|share\s+capital"
    r"|post[\s-]?(?:right|issue|effect|split)|ratio|for\s+every|for\s+each", re.I)


def _shares_in(sentence: str) -> tuple[float | None, str | None]:
    """A share/warrant count, never a ratio, authorised capital, post-issue total or face value."""
    if re.search(r"authorised\s+(?:share\s+)?capital|authorized\s+(?:share\s+)?capital", sentence, re.I):
        return None, None
    kept: list[tuple[float, str]] = []
    for match in _SHARES.finditer(sentence):
        before = sentence[max(0, match.start() - 70):match.start()]
        after = sentence[match.end():match.end() + 45]
        if _SHARES_BAD_CONTEXT.search(before) or _SHARES_BAD_CONTEXT.search(after):
            continue
        try:
            kept.append((float(match.group("v").replace(",", "")), match.group(0)))
        except ValueError:
            continue
    if not kept:
        return None, None
    values = sorted({value for value, _span in kept})
    if values and max(values) >= 1000:
        values = [value for value in values if value >= 100]   # "each warrant into 1 share" is not issued here
    # an equity + warrant issue prints two counts; a conversion prints the same count twice
    total = sum(values) if len(values) > 1 and re.search(r"warrants?", sentence, re.I) \
        and re.search(r"equity\s+shares?", sentence, re.I) else max(values)
    span = ", ".join(dict.fromkeys(span for _value, span in kept))
    return total, span


# T-242 round 7: the step's size is the printed total of THIS step, else the securities ALLOTTED IN THIS
# FILING times their issue price.  A figure that names a component of the consideration is not the step:
# the green shoe ("up to X including a green shoe option of Rs Y": X is the amount, #2), a premium or
# accrued interest (#7), a base issue, cash/balance consideration of an acquisition (#49, #60), a partly
# paid tranche.  The component cue sits immediately before its figure ("premium amounting to Rs X"), so
# only the prefix is read: a genuine total may follow the same words ("including a premium ..., aggregating
# to Rs X") and keeps its own figure.  A price is the issue price of the security this step converts
# (warrants at 260, CCDs at 1,00,000), never the 75%/25% instalment or a share's conversion price.
_RAISE_COMPONENT_BEFORE = re.compile(
    r"\b(?:green\s*shoe(?:\s+option)?|premium(?:\s+and\s+accrued\s+interest)?|accrued\s+interest"
    r"|base\s+issue|cash\s+consideration|balance\s+consideration|upfront\s+(?:payment|consideration))"
    r"\b(?:\s+(?:and|of|amounting|aggregating|to|up\s*to|upto|an?|the|only|total))*\s*$", re.I)
_RAISE_PRICE_BAD = re.compile(
    r"\bconversion\s+price\b|\b(?:25|75)\s*(?:%|per\s*cent)\b|\bremaining\b|\bbalance\b"
    r"|\bupfront\b|\bup-front\b|\bdiscount\b", re.I)
# a clause about the balance/instalment a warrant holder paid is not the step's total: the RUSHIL
# conversion letters print the 75% receipt with "aggregating to" (fresh5 #17, #19, #21, #41).
_RAISE_BALANCE_CLAUSE = re.compile(
    r"\bremaining\s+(?:75|25)\s*%|\bbalance\s+subscription\s+amount\b|\bin\s+aggregate\s+towards\b"
    r"|\bbeing\s+(?:25|75)\s*%\b|\bbalance\s+(?:payment|amount|consideration)\b"
    r"|\bi\.?\s?e\.?\s+\(?(?:25|75)\s*%|\b(?:25|75)\s*%\s+of\s+the\s+(?:issue|exercise)\s+price\b", re.I)
# the count THIS clause allots/issues/converts, right after the verb ("approved the allotment of 66,00,000
# equity shares"), never a total, a balance or a background count (#17, #19, #21, #31, #41).
_STEP_COUNT = re.compile(
    r"\b(?:approved|allotted|allotment\s+of|issued|outstanding\s+of|issue\s+and\s+allotment\s+of|issue\s+of"
    r"|issuance\s+of|conversion\s+of|converted\s+(?:total\s+)?|converts?\s+(?:total\s+)?)"
    r"[,\s]+(?:up\s*to\s+|upto\s+)?(?P<n>\d[\d,]*)\s*(?:\([^)]{0,120}\)\s*)?"
    r"(?:(?:fully|partly)\s+)?(?:paid[-\s]?up\s+)?"
    r"(?:(?:compulsorily\s+)?convertible\s+)?(?:equity\s+)?"
    r"(?P<kind>shares?|warrants?|debentures?|CCDs?|NCDs?|securities|preference\s+shares?)\b", re.I)
# "convert total 1,10,00,000 warrants into 1,10,00,000 equity shares": the ALLOTTED security is the share
# count, not the pre-conversion warrant count (the split can make them differ ten-fold, #19, #41).
_CONVERT_INTO = re.compile(
    r"\bconvert(?:ed|s)?\s+(?:total\s+)?[\d,]{3,}[^.]{0,60}?\binto\s+(?P<n>[\d,]{3,})\s*"
    r"(?:\([^)]{0,120}\)\s*)?(?:fully\s+paid[-\s]?up\s+)?(?:equity\s+)?shares?\b", re.I)
_RAISE_FULL_AMOUNT = re.compile(
    r"(?P<cue>total\s+aggregat\w*|aggregat\w*(?:\s+consideration)?|amount\w*|issue\s+size"
    r"|size\s+of\s+(?:the\s+)?issue|total\s+consideration|consideration)"
    r"\s*(?:of|to|for)?\s*(?:up[-\s]*to|upto)?\s*(?:Rs\.?|INR|₹)\s*(?P<v>\d[\d,]{6,}(?:\.\d+)?)(?:\s*/-)?",
    re.I)
# the SEBI template row that states the step's total ("total number of securities ... issued", "for an
# aggregate consideration of Rs X"): the row is the printed total even without a raise verb in it (#32).
_RAISE_STEP_TOTAL = re.compile(
    r"\btotal\s+(?:number\s+of\s+securities|amount\s+(?:for\s+which|of))\b"
    r"|\bfor\s+an\s+aggregate\s+consideration\b|\baggregate\s+consideration\s+of\b", re.I)
# a clause about a proposed allottee that fell away, or about an acquisition's consideration, is not this
# filing's raise (#16, #60).
_RAISE_NOT_STEP = re.compile(
    r"\bbecame\s+ineligible\b|\bcould\s+not\s+be\s+allotted\b|\bno\s+longer\s+(?:eligible|an?\s+allottee)\b"
    r"|\bnot\s+(?:been\s+)?allotted\b|\bwarrants?\b[^.]{0,60}\blapsed\b"
    r"|\btill\s+date\b|\b(?:after|before)\s+this\s+allotment\b|\bincluding\s+(?:the\s+)?(?:current|this)\s+allotment\b"
    r"|\baccordingly,?\s+total\b|\bout\s+of\s+the\s+balance\b", re.I)
_RAISE_OTHER_DEAL = re.compile(
    r"\bcash\s+consideration\b[^.]{0,160}\bacquisition\b"
    r"|\bbalance\s+consideration\b[^.]{0,60}\bcash\b"
    r"|\bconsideration\s+other\s+than\s+cash\b"
    r"|\bacquisition\b[^.]{0,240}\bconsideration\b", re.I)


def _raise_component_before(sentence: str, start: int) -> bool:
    """Is the figure at ``start`` the component the words immediately before it name (premium, green shoe)?"""
    return bool(_RAISE_COMPONENT_BEFORE.search(sentence[max(0, start - 110):start]))


def _raise_component_after(sentence: str, start: int, end: int) -> bool:
    """Is the figure itself an instalment/balance component ("being 25% of", "remaining exercise price")?"""
    return bool(_RAISE_COMPONENT.search(sentence[end:end + 90])
                or _RAISE_COMPONENT.search(sentence[max(0, start - 12):start]))


def _step_count(sentence: str) -> tuple[float | None, str | None]:
    """The count of securities THIS clause allots, issues or converts, never a cumulative or balance count."""
    if _RAISE_STEP_TOTAL.search(sentence):
        # a SEBI template row ("total number of securities ... issued") states the security count itself
        row = re.search(
            r"(?:securities|issued|to\s+be\s+issued)\s+(?:approximately\s+)?(?P<n>\d[\d,\s]{2,}?)\s*"
            r"(?:\([^)]{0,120}\)\s*)?(?:(?:fully|partly)\s+)?(?:paid[-\s]?up\s+)?(?:equity\s+)?shares?\b",
            sentence, re.I)
        if row:
            digits = re.sub(r"[^\d]", "", row.group("n"))
            if digits and int(digits) >= 100:
                return float(digits), "shares"
    into = _CONVERT_INTO.search(sentence)
    if into:
        try:
            value = float(into.group("n").replace(",", ""))
            if value >= 100:
                return value, "equity shares"
        except ValueError:
            pass
    for match in _STEP_COUNT.finditer(sentence):
        try:
            value = float(match.group("n").replace(",", ""))
        except ValueError:
            continue
        if value >= 100:
            return value, match.group("kind")
    return None, None


def _raise_instrument(sentence: str) -> str | None:
    """The security this clause converts: CCDs/warrants are converted, the resulting shares are not priced."""
    if re.search(r"\bCCDs?\b|compulsorily\s+convertible\s+debentures?", sentence, re.I):
        return "ccd"
    if re.search(r"\bwarrants?\b", sentence, re.I) and re.search(r"\bconvers|convert|exercis", sentence, re.I):
        return "warrant"
    return None


def _instrument_price(sentence: str, body: str, instrument: str | None,
                      count_kind: str | None) -> tuple[float | None, str | None]:
    """The issue price of the security this step converts/allots, never an instalment or a share's conversion price."""
    units: list[str] = []
    kind = (count_kind or "").lower()
    if "share" in kind:
        if instrument == "warrant":
            units = [r"warrants?", r"(?:equity\s+)?shares?"]
        else:
            units = [r"(?:equity\s+)?shares?"]
    elif "warrant" in kind:
        units = [r"warrants?"]
    elif "debenture" in kind or "ccd" in kind:
        units = [r"(?:CCDs?|debentures?)"]
    else:
        units = [r"(?:equity\s+)?shares?", r"warrants?", r"(?:CCDs?|debentures?)"]
    for unit in units:
        for strict in (True, False):
            for source in (sentence, body):
                for match in _PRICE.finditer(source):
                    prefix = source[max(0, match.start() - 100):match.start()]
                    if _raise_component_before(source, match.start()) or _RAISE_PRICE_BAD.search(prefix[-60:]) \
                            or re.search(r"\b(?:conversion|exercise)\s+$", prefix, re.I):
                        continue
                    try:
                        price = float(match.group("v").replace(",", ""))
                    except ValueError:
                        continue
                    if not (0.01 <= price <= 100_000):
                        continue
                    window = source[match.start():match.end() + 180]
                    other = re.search(r"\bper\s+(CCDs?|debentures?|warrants?|(?:equity\s+)?shares?)",
                                      window, re.I)
                    if other and not re.fullmatch(unit, other.group(1), re.I):
                        continue
                    if re.search(r"\b(?:per|each)\s+" + unit + r"\b", window, re.I) \
                            or re.match(r"issue\s+price", match.group(0), re.I) \
                            or re.search(r"\bissue\s+$", prefix, re.I):
                        return price, match.group(0)
                    if not strict and re.search(r"\beach\b", source[match.end():match.end() + 50], re.I) \
                            and re.search(unit, source[:match.start()], re.I):
                        return price, match.group(0)
    return None, None


def _raise_size_family(sentence: str) -> str:
    """The coarse instrument a size belongs to, so a second instrument in one filing still adds (#15)."""
    if re.search(r"\bwarrants?\b", sentence, re.I):
        return "warrant"
    if re.search(r"\bCCDs?\b|compulsorily\s+convertible", sentence, re.I):
        return "ccd"
    if re.search(r"\bNCDs?\b|non[-\s]*convertible", sentence, re.I):
        return "ncd"
    if re.search(r"\b(?:preference|OCRPS|CCPS)\b", sentence, re.I):
        return "preference"
    if re.search(r"\bshares?\b|\bQIP\b|qualified\s+institutions?|preferential|rights\s+issue", sentence, re.I):
        return "equity"
    return "other"


# T-242 r7b: a warrant/CCD conversion receives the BALANCE of the issue price at conversion and the letter
# prints it.  The printed receipt is the step ("upon receipt of amount aggregating to Rs X ... (being remaining
# 75% of the issue price per warrant)", RATNAVEER #17), never a computed 100% from the full issue price; when
# only the per-unit balance is printed ("Post receipt of balance amount at the rate of Rs. 48.75 per warrant,
# N Equity Shares have been allotted") the step is N x that balance price (MANAKCOAT #22, #41, #45).
_RAISE_BALANCE_MARK = re.compile(r"\bbeing\s+(?:the\s+)?remaining\s+(?:25|75)\s*%", re.I)
_RAISE_AGGREGATE_RS = re.compile(
    r"\baggregat(?:ing|ed)?\s*(?:to|upto|up\s*to)?\s*(?:Rs\.?|INR|₹)\s*(?P<v>\d[\d,]{6,}(?:\.\d+)?)", re.I)
_RAISE_BALANCE_UNIT = re.compile(
    r"(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*(?:/-)?\s*(?:per|each)\s+(?:warrant|equity\s+share|share)\b", re.I)
# T-242 r7b: the listed company's OWN issue is an issuance, whatever else the pages mention.  A share swap that
# pays another company's sellers in the company's own shares allots its own paper, so "acquisition"/"investment"
# on the same page is the consideration, not another issuer (#24, #50); a priced issuance ("at a price of Rs
# X per share") is the company's raise, an unpriced swap tranche inside a cash raise still is not (#49).
_OWN_PRICED_ISSUE = re.compile(
    r"\b(?:issue|issued|issuance|issuing|allotment|allotted)\b[\s\S]{0,200}?\b(?:equity\s+|preference\s+)?shares?\b"
    r"[\s\S]{0,160}?\bprice\s+(?:of|per)\s+(?:Rs\.?|INR|₹)\s*\d[\d,]*", re.I)
_OWN_ISSUE_RAISE = re.compile(
    r"\b(?:issuance|issue|allotment)\s+(?:of\s+)?(?:the\s+)?(?:[\d,]+\s+)?(?:non[-\s]?convertible\s+)?"
    r"(?:debentures?|NCDs?)\b", re.I)


def _balance_receipt(body: str) -> tuple[float, str, str] | None:
    """(crore, printed span, clause) of the balance a conversion letter says it received, else None."""
    for match in _RAISE_AGGREGATE_RS.finditer(body):
        window = body[match.end():match.end() + 240]
        if _RAISE_BALANCE_MARK.search(window):
            return (round(_digits(match.group("v")) / 1e7, 4), match.group(0),
                    body[max(0, match.start() - 200):match.end() + 240])
    return None


def _balance_unit_price(body: str) -> float | None:
    """The balance price per warrant/share the letter prints ("at the rate of Rs. 48.75 per warrant")."""
    for match in _RAISE_BALANCE_UNIT.finditer(body):
        before = body[max(0, match.start() - 220):match.start()]
        if not _RAISE_BALANCE_CLAUSE.search(before):
            continue
        try:
            price = float(match.group("v").replace(",", ""))
        except ValueError:
            continue
        if 0.01 <= price <= 100_000:
            return price
    return None


def _raise_count_size(sentence: str, body: str) -> tuple[float | None, str | None, int, int]:
    """The securities THIS clause allots or converts, times the issue price of that security."""
    shares, count_kind = _step_count(sentence)
    if shares is None and _PRICE.search(sentence):
        # a SEBI template cell prints the count without a raise verb ("Up to 48,134 Equity Shares of the
        # Company ... at a price of INR 1454.30"); the price in the same clause anchors it (#18).
        shares, _span = _shares_in(sentence)
        count_kind = "equity shares" if shares else None
    if shares is None:
        return None, None, 0, 0
    balance = _balance_unit_price(body)
    if balance:
        # a warrant conversion pays the BALANCE of the issue price at conversion: count x the balance price
        # the letter prints, never count x the full issue price (MANAKCOAT #22, #41, #45).
        return round(shares * balance / 1e7, 4), f"{count_kind or 'shares'} x balance price {balance:g}", 1, 0
    price, price_span = _instrument_price(sentence, body, _raise_instrument(sentence), count_kind)
    if shares and price:
        label = price_span or f"{price:g}"
        return round(shares * price / 1e7, 4), f"{count_kind or ''} x {label}", 1, 0
    return None, None, 0, 0


def _raise_size(sentence: str, body: str) -> tuple[float | None, str | None, int, int]:
    """(size in crore, printed span, computed?, rank) of one raise clause: its printed total, else its own count x price."""
    best: tuple[int, float, str] | None = None
    balance = bool(_RAISE_BALANCE_CLAUSE.search(sentence))
    for match in _RAISE_FULL_AMOUNT.finditer(sentence):
        if _raise_component_before(sentence, match.start()) \
                or _raise_component_after(sentence, match.start(), match.end()):
            continue
        value = round(_digits(match.group("v")) / 1e7, 4)
        rank = 2 if re.search(r"aggregat|total|size", match.group("cue"), re.I) else 1
        if best is None or (rank, value) > (best[0], best[1]):
            best = (rank, value, match.group(0))
    for match in _SIZE_CUE.finditer(sentence):
        prefix = sentence[max(0, match.start() - 60):match.start()]
        if _MARKET_CAP_CUE.search(prefix) or _raise_component_before(sentence, match.start()) \
                or _raise_component_after(sentence, match.start(), match.end()):
            continue
        value = _to_cr(match.group("v"), match.group("u"))
        if value is None or value <= 0:
            continue
        rank = 2 if re.search(r"aggregat|total|size", match.group(0), re.I) else 1
        if best is None or (rank, value) > (best[0], best[1]):
            best = (rank, value, match.group(0))
    if best is not None and not _RAISE_BALANCE_CLAUSE.search(sentence):
        return best[1], best[2], 0, best[0]
    if balance:
        return _raise_count_size(sentence, body)
    for value, span, start in _amounts_rs(sentence):
        prefix = sentence[max(0, start - 60):start]
        if _MARKET_CAP_CUE.search(prefix) or _raise_component_before(sentence, start) \
                or _raise_component_after(sentence, start, start + len(span)):
            continue
        if best is None or value > best[1]:
            best = (1, value, span)
    if best is not None and not balance:
        return best[1], best[2], 0, best[0]
    return _raise_count_size(sentence, body)


_RAISE_STAGE_RANK = {
    "allotted": 5, "allotment": 5,
    "completion": 4, "approved_shareholders": 4,
    "approval": 3, "approved_board": 3, "in_principle": 3,
    "listing": 2,
    "proposed": 1, "filed_offer_doc": 1,
}
# T-242: only a completed allotment is ``allotment``; a board meeting that approves an issue is ``approval``
# even when the annexure prints "allotment" in a future sense ("allotment of up to", "date of allotment") (#29,
# #46, #60).  "allotted" alone is not enough: "to be allotted"/"assumed to be allotted" state a plan.
# Round 5: a committee that "allotted 300 NCDs" or "considered and approved the allotment of 1,19,99,847
# Equity Shares" completed the allotment whatever the title of the letter says (#1, #5, #23, #25, #40, #46,
# #49); a bare "allotted" stays excluded when it is a plan ("to be allotted", "will be allotted").
_ALLOTMENT_DONE = re.compile(
    r"\b(?:completed|has|have|had)\s+(?:the\s+)?(?:issue|issuance)\s+and\s+allotment\b"
    r"|\b(?:has|have|had)\s+(?:today\s+|also\s+)?(?:been\s+)?allotted\b"
    r"|\b(?:shares?|warrants?|debentures?|securities|NCDs?)\s+(?:have|has|were|was)\s+been\s+allotted\b"
    r"|\ballotment\s+of\s+[\d,]{3,}\s*(?:\([^)]{0,140}\)\s*)?(?:equity\s+)?(?:shares?|warrants?|debentures?"
    r"|NCDs?|securities)\b"
    r"|\b(?:considered\s+and\s+)?approved\s+(?:the\s+)?allotment\s+of\s+[\d,]{3,}"
    r"|\ballotted\s+(?:on|today|pursuant)\b"
    r"|\b(?<!\bbe\s)(?<!\bbeen\s)allotted\s+[\d,]"
    r"|\bbasis\s+of\s+allotment\b", re.I)
_APPROVAL_ONLY = re.compile(
    r"\bapproved\s+(?:the\s+)?(?:issuance|issue)\b"
    r"|\bconsidered\s+and\s+approved\b"
    r"|\bsubject\s+to\s+(?:the\s+)?(?:approval|consent)\s+of\s+(?:the\s+)?(?:shareholders?|members?)\b"
    r"|\benabling\s+resolution\b", re.I)
_SEBI_TEMPLATE_LINE = re.compile(
    r"\bin\s+case\s+of\s+(?:preferential\s+issue|bonus\s+issue|issuance\s+of)[^.\n]{0,220}?(?:not\s+applicable|n\.?\s?a\.?)"
    r"|\btype\s+of\s+issuance\s*\([^)]+\)"
    r"|\bcompanies\s*\(\s*prospectus\s+and\s+allotment\s+of\s+securities\s*\)",
    re.I,
)


# T-242 round 5: a postal-ballot or EGM notice asks for the approval; a board that approved only a draft
# notice has not raised anything yet (#31, #51, #53).  The notice must name itself in the subject line: a board
# outcome that merely lists "the notice of the EGM" among its resolutions approved the issue (#6, #33).
_RAISE_NOTICE = re.compile(
    r"\bnotice\s+of\s+(?:the\s+)?(?:postal\s+ballot|extra[-\s]?ordinary\s+general\s+meeting|egm"
    r"|annual\s+general\s+meeting|agm)\b"
    r"|\bpostal\s+ballot\s+notice\b|\b(?:egm|agm)\s+to\s+be\s+held\b"
    r"|\bprior\s+intimation\b[^.]{0,140}\b(?:special\s+)?resolution\b"
    r"|\bresolution\b[^.]{0,80}\bto\s+be\s+passed\s+at\b[^.]{0,40}\b(?:agm|egm|annual|extra)\b", re.I)
# T-242 round 7: a recommendation to seek members' approval, a resolution to be passed at the AGM or the
# AGM's own business ("for raising of funds") is proposed, not approved: the board has not approved the
# issue itself (#11, #45, #47, #59).  The round-5 #6/#33 shape -- the board approved the raising AND
# convened the EGM -- has no "for raising of funds" and stays an approval.
_RAISE_RECOMMEND = re.compile(
    r"\brecommend\w*\b[^.]{0,90}\b(?:seeking|seek)\b[^.]{0,50}\b(?:approval|consent)\b"
    r"|\brecommend\w*\b[^.]{0,90}\b(?:offer|issue|allot|raising|raise)\b[^.]{0,80}"
    r"\b(?:shareholders?|members?)\b", re.I)
_RAISE_AGM_AGENDA = re.compile(
    r"\b(?:members?|shareholders?)\b[^.]{0,100}\bwill\s+(?:inter\s+alia\s+)?consider\b"
    r"[^.]{0,140}\b(?:resolutions?|issues?)\b"
    r"|\bseek(?:ing)?\s+(?:the\s+)?approval\s+of\s+the\s+(?:members?|shareholders?)\b"
    r"[^.]{0,320}?\bfor\s+(?:raising|saising)\s+of\s+(?:funds?|fands?)\b", re.I)
# a press release after the issue completed reports the completed step, not a proposal (#55)
_RAISE_CONCLUDED = re.compile(
    r"\b(?:successfully\s+)?(?:concluded|completed|closed|closes)\b[^.]{0,60}\b(?:capital\s+raise|raise|QIP"
    r"|qualified\s+institutions?|issue|placement)\b"
    r"|\b(?:raised|raises)\s+(?:USD|US\s?\$|INR|Rs\.?|₹)\b", re.I)
_RAISE_NOTICE_DONE = re.compile(
    r"\b(?:voting|scrutini[sz]er'?s?)\s+results?\b|\bresults?\s+of\s+(?:the\s+)?(?:postal\s+ballot|egm|agm)\b"
    r"|\bsummary\s+of\s+proceedings\b|\boutcome\s+of\s+(?:the\s+)?(?:egm|agm|postal\s+ballot)\b"
    r"|\b(?:members?|shareholders?)\s+(?:have\s+)?(?:passed|approved)\b", re.I)
_RAISE_DRAFT_ONLY = re.compile(
    r"\b(?:approved|approving|considered)\b[^.]{0,120}\bdraft\b[\s\S]{0,220}?"
    r"(?:QIP|qualified\s+institutions?|preferential|rights\s+issue|raising\s+(?:of\s+)?(?:funds|capital)"
    r"|issue\s+of\s+[\w\s]{0,30}(?:shares|securities)|Rs\.?\s*[\d,]|₹\s*[\d,])", re.I)
# an exchange in-principle approval clears the issue; a listing/trading approval is the step after the allotment
_RAISE_IN_PRINCIPLE = re.compile(r"\bin[-\s]?principle\s+approval\b|\binprinciple\s+approval\b", re.I)
_RAISE_LISTING = re.compile(
    r"\blisting\s+approval\b|\btrading\s+approval\b|\bapproval\s+for\s+(?:listing|trading)\b"
    r"|\b(?:shares?|securities)\s+(?:have\s+been|are|were)\s+listed\b|\bcommencement\s+of\s+(?:trading|listing)\b"
    r"|\badmitted\s+to\s+dealings\b", re.I)
_RAISE_COMPLETION = re.compile(
    r"\bissue\s+(?:fully\s+)?(?:opened|closed|subscribed)\b|\b(?:successfully\s+)?(?:raised|raises)\b[^.]{0,40}"
    r"\b(?:the\s+)?(?:issue|QIP|placement|funds?)\b|\bcompleted\s+the\s+(?:issue|placement)\b", re.I)


def _raise_stage(title: str, head: str) -> str:
    """The stage this filing reports: allotment, notice, draft-only notice, approval, in-principle, listing.

    T-242 round 5: ``intimation`` is not a stage -- every filing is mapped by what it states, in this order
    (fresh4/fresh3 #1, #5, #6, #7, #23, #25, #31, #33, #40, #46, #49, #51, #53).
    """
    title_low = _flat(title).lower()
    heading = _SEBI_TEMPLATE_LINE.sub(" ", _flat(head)).lower()
    stage_text = title_low + " " + heading
    opening = title_low + " " + heading[:300]          # a notice names itself in the subject line
    if re.search(r"\b(?:draft\s+letter\s+of\s+offer|\bdlof\b|addendum\s+to\s+(?:the\s+)?(?:dlof|draft\s+letter\s+of\s+offer|letter\s+of\s+offer))\b", stage_text):
        return "proposed"
    if _ALLOTMENT_DONE.search(stage_text):
        return "allotment"
    if re.search(r"\bpost[-\s]?allotment\b", stage_text) and not _APPROVAL_ONLY.search(stage_text):
        return "allotment"              # an outcome-of-subscription table prints the completed allotment
    if _RAISE_DRAFT_ONLY.search(stage_text):
        return "proposed"               # a board that approved only the draft notice has not raised anything yet
    if _RAISE_NOTICE.search(opening) and not _RAISE_NOTICE_DONE.search(opening):
        return "proposed"
    if _RAISE_CONCLUDED.search(stage_text):
        return "allotment"              # a press release says the issue completed: report the completed step
    if _RAISE_RECOMMEND.search(stage_text):
        return "proposed"               # the board recommended seeking members' approval; nothing is issued yet
    if _RAISE_AGM_AGENDA.search(stage_text):
        return "proposed"               # the AGM's own business (a resolution to be passed), not a board approval
    if _RAISE_IN_PRINCIPLE.search(stage_text):
        return "approval"               # an exchange in-principle approval is not the listing
    if _RAISE_LISTING.search(title_low):
        return "listing"
    if _APPROVAL_ONLY.search(stage_text):
        return "approval"
    if re.search(r"\bnot\s+exceeding\b|postal ballot|approved|approval|shareholders.{0,30}approved|key terms", heading):
        return "approval"
    if _RAISE_COMPLETION.search(stage_text):
        return "completion"
    if _RAISE_LISTING.search(heading):
        return "listing"
    return "proposed"


def _raise_step_sizes(title: str, head: str, text: str) \
        -> tuple[list[tuple[float, str | None, int]], list[str], list[str]]:
    """(the distinct sizes THIS step prints, the clauses they were printed in, their instrument families).

    T-242 round 5: a clause that records an earlier step is cut at that cue, a clause that states the capital
    before/after the issue is cut at the capital phrase, and a clause that quotes a component of this step's
    consideration (the 25% upfront or the 75% balance of a warrant) is skipped whole: the step's value is never
    a sum of those angles (fresh4/fresh3 #10, #12, #13, #20, #32, #54, #57).  A bundled outcome still carries
    one printed size per instrument, and those add (a preferential issue and warrants, #15).
    """
    is_results = bool(_RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}")))
    text = _RAISE_OCR_SPACE.sub(",", text)
    body = _flat(f"{title} {text}")
    receipt = _balance_receipt(body)
    if receipt is not None:
        # the title still names this step's count and issue price, so it stays a winner beside the receipt
        winners = [title, receipt[2]] if title else [receipt[2]]
        return [(receipt[0], receipt[1], 0)], winners, [_raise_size_family(receipt[2])]
    # the subject line names the step ("Allotment of 75,000 Equity shares upon conversion of warrants"): the
    # count it prints is what THIS filing allot, and the letter's later background/balance figures cannot
    # replace it (#17, #19, #21, #41).
    if title and _step_count(title)[0] is not None:
        title_size = _raise_size(title, body)
        if title_size[0] is not None:
            return [(title_size[0], title_size[1], title_size[2])], [title], [_raise_size_family(title)]
    sentences = [title] + _clauses(text)
    sizes: list[tuple[float, str | None, int, str, int]] = []
    winners: list[str] = []
    continuation = False
    for sentence in sentences:
        if _RAISE_DEBT_VETO.search(sentence) or _RAISE_OUTBOUND_VETO.search(sentence) \
                or _RAISE_NOT_STEP.search(sentence) \
                or (_RAISE_OTHER_DEAL.search(sentence) and not _OWN_PRICED_ISSUE.search(sentence)):
            continuation = False
            continue
        cut = len(sentence)
        for cue in (_RAISE_PRIOR_STEP, _RAISE_CAPITAL):
            match = cue.search(sentence)
            if match:
                cut = min(cut, match.start())
        sentence = sentence[:cut].strip()
        if not sentence:
            continuation = False
            continue
        if is_results and _FINANCIAL_METRIC.search(sentence):
            continuation = False
            continue
        has_cue = bool(_RAISE_CUE.search(sentence) and _RAISE_ISSUANCE.search(sentence)) \
            or bool(_RAISE_STEP_TOTAL.search(sentence))
        if not has_cue and not (continuation and (_SIZE_CUE.search(sentence) or _amounts_rs(sentence)
                                                  or _SHARES.search(sentence) or _PRICE.search(sentence))):
            continuation = False
            continue
        if _INTIMATION.search(sentence) and not _DONE.search(sentence):
            continuation = False
            continue
        if is_results and not _RESULTS_ACTION.search(sentence):
            continuation = False
            continue
        decided = has_cue and (_DONE.search(sentence) or _RAISE_DONE.search(sentence) or _APPROVE.search(sentence)
                               or _RAISE_STEP_TOTAL.search(sentence)
                               or re.search(r"allotment\s+of|allotted|issuance\s+of|issue\s+price"
                                            r"|being\s+the\s+issue\s+price", sentence, re.I))
        if not decided and not continuation:
            continue
        value, span, computed, rank = _raise_size(sentence, body)
        if value is None:
            continuation = has_cue and decided and not is_results
            continue
        if computed and value < 0.01:
            continuation = False
            continue
        continuation = False
        sizes.append((round(value, 4), span, computed, _raise_size_family(sentence), rank))
        winners.append(sentence)
    # the same figure printed twice is one size; a declared total ("total aggregating to", "size of the
    # issue") absorbs the smaller component prints of the same instrument (a base issue, a partly-paid
    # tranche), and a printed size beats a shares x price computation.  A second instrument still adds (#15).
    merged: list[tuple[float, str | None, int]] = []
    families: list[str] = []
    ranks: list[int] = []
    for value, span, computed, family, rank in sorted(sizes, key=lambda item: -item[0]):
        for index, (known, _kspan, kcomputed) in enumerate(merged):
            if abs(value - known) <= 0.01 * max(1.0, known):
                if rank > ranks[index] or (not computed and kcomputed):
                    merged[index] = (value, span, computed)
                    ranks[index] = rank
                    families[index] = family
                break
        else:
            merged.append((value, span, computed))
            families.append(family)
            ranks.append(rank)
    kept: list[tuple[float, str | None, int]] = []
    kept_families: list[str] = []
    for index, (value, span, computed) in enumerate(merged):
        family = families[index]
        if any(ranks[other] == 2 and families[other] == family and merged[other][0] > value
               for other in range(len(merged)) if other != index):
            continue                      # a component of the same instrument's declared total
        if computed and any(families[other] == family and not merged[other][2]
                            for other in range(len(merged))):
            continue                      # the instrument's printed total beats a shares x price read
        kept.append((value, span, computed))
        kept_families.append(family)
    if any(not computed for _value, _span, computed in kept):
        kept = [item for item in kept if not item[2]]      # a printed total is the step, never computed beside it
    return kept, winners, kept_families


def _raise_family_ok(instrument: str | None, family: str) -> bool:
    """Does a printed size belong to the instrument the row reports?  A QIP row never takes the NCD resolution."""
    if instrument in (None, "mixed", "borrowing", "other") or family == "other":
        return True
    if instrument == "ncd":
        return family == "ncd"
    if instrument in ("qip", "rights", "equity"):
        return family in ("equity", "warrant", "ccd", "preference")
    if instrument == "preferential":
        return family in ("equity", "warrant", "ccd", "preference", "ncd")
    if instrument == "warrant":
        return family in ("warrant", "equity", "ccd")
    return True


def raise_step_amount(text: str) -> tuple[float | None, str | None]:
    """(amount in crore, how it was read) of the step a fund-raise filing reports -- never a sum of angles.

    The step's own value is one printed total ("aggregating to Rs X"), or the shares it issued times the issue
    price.  The 25% upfront and the 75% balance of a warrant, an earlier step's aggregate, a past year's figure
    and the capital before or after the issue are not this step: a filing that prints 8,00,000 shares at Rs 124
    and a Rs 4,65,00,000 receipt of the earlier warrant subscription is worth Rs 9,92,00,000, not both.
    """
    merged, _winners, _families = _raise_step_sizes("", _flat(text), _flat(text))
    if not merged:
        return None, None
    amount = round(sum(value for value, _span, _computed in merged), 4)
    how = "; ".join(dict.fromkeys(span for _value, span, _computed in merged if span))
    return amount, how or "shares x issue price"


def raise_fields(title: str, head: str, text: str) -> dict[str, Any] | None:
    """The raise size, issue price, share count and instrument a fund-raise filing prints.

    A bundled outcome can carry several raises (a preferential issue and warrants): each clause gives its own
    printed size, the filing is one event, and distinct printed sizes are summed (computed -> unverified).
    """
    if _RAISE_VETO.search(_flat(f"{title} {head}")) or not _RAISE_CUE.search(_flat(f"{title} {head}")):
        return None                 # a note deep in a financial statement is not the company's raise
    opening = re.split(r"\bAnnexure\b", head, maxsplit=1, flags=re.I)[0][:1200]
    flat_opening = _flat(f"{title} {opening}")
    merged, winners, families = _raise_step_sizes(title, head, text)
    if _RAISE_FOREIGN_ISSUE_VETO.search(_flat(f"{title} {head}")) and not any(
        _OWN_PRICED_ISSUE.search(winner) or _OWN_ISSUE_RAISE.search(winner) for winner in winners
    ):
        return None                 # the listed company is not the issuer: another entity's issue, an acquisition, a loan
    whole = _flat(f"{title} {head}")
    if _RAISE_AGREEMENT_VETO.search(whole) \
            and not _OWN_ISSUE_TITLE.search(_flat(title)):
        return None                 # a facility/loan revision, warrant lapse or stake purchase is not an issuance
    if _RAISE_DEBT_VETO.search(flat_opening):
        return None
    if _RAISE_SUBSIDIARY_VETO.search(_flat(f"{title} {head[:1500]}")) \
            and not _OWN_ISSUE_TITLE.search(_flat(title)):
        return None                 # the subsidiary allotted its own shares: the listed company issued nothing
    if _RAISE_ADVISORY_VETO.search(whole):
        return None                 # an exchange advisory or lock-in letter about an earlier issue is not one
    if _RAISE_GENERIC_CUE.search(whole) and not _RAISE_SECURITY.search(whole):
        return None                 # "fund raising through debt" names no security: nothing was issued
    if _RAISE_OUTBOUND_VETO.search(flat_opening) and not _OWN_PRICED_ISSUE.search(flat_opening) and not re.search(
        r"\braising\s+of\s+funds\b|\bfund\s*[- ]?rais|\bQIP\b|\brights\s+issue\b|\bpreferential\s+(?:issue|allotment)\b"
        r"|\bnon[-\s]?convertible\b|\bNCDs?\b",
        flat_opening, re.I,
    ):
        return None
    body = _flat(f"{title} {text}")
    clean_body = _SEBI_TEMPLATE_LINE.sub(" ", body)
    instrument, best_count = None, 0
    for name, rx in _INSTRUMENTS:
        count = sum(1 for _ in rx.finditer(clean_body))
        if count > best_count:       # the words the filing repeats most name the instrument; tie keeps priority
            instrument, best_count = name, count
    if re.search(r"\bany\s+instrument\s+or\s+security\b|\bor\s+(?:a|any)\s+combination\s+thereof\b", clean_body, re.I) \
            and sum(1 for _name, rx in _INSTRUMENTS[:6] if rx.search(clean_body)) >= 3:
        instrument = "mixed"
    # a size belongs to the instrument the row reports: a QIP notice never takes the NCD resolution's amount
    merged = [size for size, family in zip(merged, families) if _raise_family_ok(instrument, family)]
    if not merged:
        return None                      # procedural filing: no size and no shares x price on the held pages
    amount = round(sum(value for value, _span, _computed in merged), 4)
    derived = 1 if len(merged) > 1 or any(computed for _value, _span, computed in merged) else 0
    price_match = next((m for m in (_PRICE.search(s) for s in winners) if m), None) or _PRICE.search(body)
    price_per_share = float(price_match.group("v").replace(",", "")) if price_match else None
    if price_per_share is not None and not (0.01 <= price_per_share <= 100_000):
        price_per_share = None          # "share capital stands at Rs 44,31,28,000" is not an issue price
    shares: float | None = None
    for winner in winners:
        shares, _span = _shares_in(winner)
        if shares is not None:
            break
    if shares is None:
        shares, _span = _shares_in(body)
    if amount and shares and price_per_share:
        implied = shares * price_per_share / 1e7
        if implied <= 0 or not (0.5 <= implied / amount <= 2):
            shares = None             # a post-issue total or a ratio, not the shares this raise issued
    quote = " ".join(dict.fromkeys(winners))[:MAX_QUOTE]
    raw_counts = {float(m.group("v").replace(",", "")) for winner in winners for m in _SHARES.finditer(winner)}
    if instrument in ("warrant", "equity", "preferential") and len(raw_counts) > 1 \
            and re.search(r"equity\s+shares?", quote, re.I) and re.search(r"warrants?", quote, re.I):
        instrument = "equity+warrant"
    return {
        "amount_inr_cr": amount,
        "value_text": "; ".join(dict.fromkeys(span for _value, span, _computed in merged if span)),
        "price_per_share": price_per_share, "shares": shares, "instrument": instrument,
        "raise_stage": _raise_stage(title, head),
        "quote": quote or None, "derived": derived,
        "purpose": None, "completion": None,
    }


# ------------------------------------------------------------------ row assembly
def blank_row(doc: dict[str, Any], kind: str) -> dict[str, Any]:
    title, text = doc.get("title") or "", doc.get("text") or ""
    parent = bool(_PARENT_SCOPE.search(_flat(f"{title} {text[:1500]}")))
    head = doc.get("head") or text
    subsidiary = None if parent or kind != "order_win" else _subsidiary_name(title, head)
    joint = bool(kind == "order_win" and not parent and _joint_receiver(title, head))
    row: dict[str, Any] = {column: None for column in COLUMNS}
    row.update({
        "store": doc["store"], "symbol": doc.get("symbol"), "isin": doc.get("isin"),
        "doc_key": doc.get("doc_key"), "kind": kind, "method": "script", "status": "unverified",
        "entity_scope": ("parent" if parent else "joint" if joint
                         else ("subsidiary" if subsidiary else "company")),
        "_subsidiary": subsidiary,
        "title": doc.get("title"), "filing_date": doc.get("filing_date"), "known_at": doc.get("known_at"),
        "page": 1, "seq": 1, "detail": "", "why": "", "_text": _flat(f"{title} {doc.get('head') or ''}"),
    })
    return row


def _printed_values(text: str, kind: str) -> list[tuple[str, float]]:
    """Every (printed span, value) a page offers for one class, in printed order."""
    out: list[tuple[str, float]] = []
    if kind == "capacity_commissioned":
        for match in _CAPACITY_TO_FROM.finditer(text):
            try:
                out.append((match.group(0), float(match.group("new").replace(",", ""))
                            - float(match.group("old").replace(",", ""))))
            except ValueError:
                pass
        for match in _CAPACITY_FROM_TO.finditer(text):
            try:
                out.append((match.group(0), float(match.group("new").replace(",", ""))
                            - float(match.group("old").replace(",", ""))))
            except ValueError:
                pass
        for match in _CAPACITY_VALUE.finditer(text):
            try:
                out.append((match.group(0), float(match.group("v").replace(",", ""))))
            except ValueError:
                pass
        return out
    if kind in ("order_win", "order_amendment", "fund_raise", "capex_approval"):
        for match in _RS_AMOUNT.finditer(text):
            value = _to_cr(match.group("v"), match.group("u"))
            if value is not None:
                out.append((match.group(0), value))
        for match in _RS_FULL.finditer(text):
            try:
                out.append((match.group(0), round(_digits(match.group("v")) / 1e7, 6)))
            except ValueError:
                pass
        for match in _USD_AMOUNT.finditer(text):
            value = _to_usd_mn(match.group("v"), match.group("u"))
            if value is not None:
                out.append((match.group(0), value))
    return out


def _locate(row: dict[str, Any], doc: dict[str, Any]) -> str | None:
    """Put the exact printed span and page on the row; return the reason when the number is not on the page."""
    if row.get("amount_inr_cr") is not None:
        target, unit = float(row["amount_inr_cr"]), "inr_cr"
    elif row.get("amount_usd_mn") is not None:
        target, unit = float(row["amount_usd_mn"]), "usd_mn"
    elif row.get("capacity_value") is not None:
        target, unit = float(row["capacity_value"]), "count"
    else:
        return "no value to print-check"
    check_target = abs(target) if row.get("kind") == "order_amendment" and target < 0 else target
    pages: dict[int, str] = doc["pages"]
    if row.get("value_text"):
        needle = _flat(row["value_text"])
        for page in sorted(pages):
            if needle and needle in _flat(pages[page]) and matches_value(check_target, find_numbers(needle), unit):
                row["page"] = page
                return None
    for page in sorted(pages):
        for span, value in _printed_values(_flat(pages[page]), row["kind"]):
            same = (abs(value - check_target) <= 1e-4 * max(1.0, abs(check_target)) if unit != "count"
                    else abs(value - check_target) < 1e-9)
            if same:
                row["value_text"], row["page"] = span, page
                return None
    # the exchange headline is printed with the filing; an OCR-damaged page can leave the title as the only copy.
    title = _flat(doc.get("title"))
    if title and row.get("value_text") and _flat(row["value_text"]) in title \
            and matches_value(check_target, find_numbers(row["value_text"]), unit):
        row["page"], row["detail"] = 0, "value in the exchange headline"
        return None
    for span, value in _printed_values(title, row["kind"]):
        same = (abs(value - check_target) <= 1e-4 * max(1.0, abs(check_target)) if unit != "count"
                else abs(value - check_target) < 1e-9)
        if same:
            row["value_text"], row["page"], row["detail"] = span, 0, "value in the exchange headline"
            return None
    return "value not printed on the page"


def _gate_status(row: dict[str, Any]) -> None:
    """Only a kind that passed its own fresh strict 60-row grade is stored ``verified`` (T-242).

    The quarantine and parent-scope branches keep their own status; this is the last gate before ``verified``.
    """
    if row["kind"] in VERIFIED_KINDS:
        row["status"] = "verified"
        return
    row["status"] = "unverified"
    note = f"kind_not_gated: {row['kind']} awaits its own 60-row grade"
    row["detail"] = f"{row['detail']}; {note}" if row.get("detail") else note


def _finish_scope(row: dict[str, Any], title: str, head: str) -> dict[str, Any]:
    """T-242 round 6: label a subsidiary's order and unverify an L1-only row before it leaves the builder."""
    if row["kind"] == "order_win" and row["status"] != "quarantined" \
            and not str(row.get("detail") or "").startswith("amount not filled by script") \
            and _l1_only(title, head):
        row["status"] = "unverified"
        row["why"] = "l1_only"
        note = "l1_only (lowest bidder stated, no award received)"
        row["detail"] = f"{row['detail']}; {note}" if row.get("detail") else note
    if row["entity_scope"] == "subsidiary" and row.get("_subsidiary"):
        note = f"subsidiary: {row['_subsidiary']}"
        row["detail"] = f"{row['detail']}; {note}" if row.get("detail") else note
    if row["entity_scope"] == "joint":
        note = "joint: company and subsidiary awarded together"
        row["detail"] = f"{row['detail']}; {note}" if row.get("detail") else note
    if row.pop("_undisclosed_customer", False):
        note = "customer not disclosed"
        row["detail"] = f"{row['detail']}; {note}" if row.get("detail") else note
    return row


def _assemble_row(doc: dict[str, Any], kind: str, fields: dict[str, Any],
                  seq: int = 1) -> tuple[dict[str, Any], bool]:
    title, text = doc.get("title") or "", doc.get("text") or ""
    head = doc.get("head") or text
    row = blank_row(doc, kind)
    row["seq"] = seq
    row["why"] = _why(kind, title, head)
    derived = int(fields.pop("derived", 0))
    detail_hint = str(fields.pop("detail_hint", "") or "")
    if "_base_value" in fields:
        row["_base_value"] = fields.pop("_base_value")
    row.update({k: v for k, v in fields.items() if k in COLUMNS})
    _split_customer(row)
    if detail_hint:
        row["detail"] = detail_hint
    if row.get("value_text"):
        row["page"] = _page_of(doc["pages"], row["value_text"])
    required = (row.get("amount_inr_cr") is not None or row.get("amount_usd_mn") is not None
                if kind != "capacity_commissioned" else row.get("capacity_value") is not None)
    if not required:
        note = "amount not filled by script"
        row["detail"] = f"{note}; {row['detail']}" if row.get("detail") else note
        if not row.get("quote"):
            row["quote"] = _flat(text)[:MAX_QUOTE]
        return _finish_scope(row, title, head), True
    if derived:
        # the amount is a sum, a delta or annual x tenure; the inputs are printed, the figure is derived.
        row["status"] = "unverified"
        row["detail"] = row.get("detail") or "amount derived from printed values (see value_text)"
        row["page"] = _page_of(doc["pages"], row.get("value_text"))
        return _finish_scope(row, title, head), False
    problem = _locate(row, doc)
    if problem:
        row["status"] = "quarantined"
        row["detail"] = problem
    elif row["entity_scope"] == "parent":
        row["status"] = "unverified"
        row["detail"] = "parent-company release"
    else:
        _gate_status(row)
    return _finish_scope(row, title, head), False


def event_rows(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """(script event rows, classes whose required number the script could not fill)."""
    title, text = doc.get("title") or "", doc.get("text") or ""
    head = doc.get("head") or text
    filing_date = doc.get("filing_date")
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    classes = classify(title, head, filing_date=filing_date, text=text)
    amendment_fields = order_amendment_fields(title, head, text) or {} if "order_amendment" in classes else {}
    excluded = {round(float(amendment_fields["amount_inr_cr"]), 4)} \
        if amendment_fields.get("amount_inr_cr") is not None else None
    for kind in classes:
        if kind == "order_win":
            order_fields_list = order_rows(title, text, doc.get("symbol") or "",
                                           exclude_amounts=excluded, head=head)
            for seq, fields in enumerate(order_fields_list, 1):
                row, absent = _assemble_row(doc, kind, fields, seq)
                rows.append(row)
                if absent:
                    missing.append(kind)
            continue
        if kind == "order_amendment":
            fields = amendment_fields
        elif kind == "capex_approval":
            fields = capex_fields(title, head, text) or {}
        elif kind == "capacity_commissioned":
            fields = capacity_fields(title, head, text, filing_date=filing_date) or {}
        else:
            fields = raise_fields(title, head, text) or {}
        row, absent = _assemble_row(doc, kind, fields, 1)
        rows.append(row)
        if absent:
            missing.append(kind)
    return rows, missing


def _event_values(row: dict[str, Any]) -> list[float]:
    return [float(row[key]) for key in ("amount_inr_cr", "amount_usd_mn", "value_annual", "value_total")
            if row.get(key) is not None]


def _same_value(first: dict[str, Any], second: dict[str, Any], tolerance: float = 0.01) -> bool:
    for left in _event_values(first):
        for right in _event_values(second):
            if abs(left - right) <= tolerance * max(1.0, abs(left), abs(right)):
                return True
    return False


def _exact_value(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return any(abs(left - right) <= 1e-6 for left in _event_values(first) for right in _event_values(second))


def _customer_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", _flat(value).lower()).strip()


_CUSTOMER_STOP = frozenset({"and", "of", "the", "ltd", "limited", "private", "pvt"})


def _initialism_of(token: str, words: list[str]) -> bool:
    """Does a contiguous run of ``words`` spell ``token`` in initials ("TPSODL" of "TP Southern Odisha ...")?"""
    parts = [word[:2] if len(word) == 2 else word[0] for word in words]
    for start in range(len(parts)):
        joined = ""
        for part in parts[start:]:
            joined += part
            if joined == token:
                return True
            if len(joined) >= len(token) or not token.startswith(joined):
                break
    return False


def _same_customer(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Equal, a prefix ("... Research" vs "... Research, Maharashtra"), or the same first three words
    ("Airports Authority of India, Patna" vs "Airports Authority of India (AAI)"); a name printed once in
    full and once as its initialism ("TPSODL and TPWODL") is the same customer (T-242)."""
    left, right = _customer_key(first.get("customer")), _customer_key(second.get("customer"))
    if not left or not right:
        return False
    if left == right or left.startswith(right) or right.startswith(left):
        return True
    words_left, words_right = left.split(), right.split()
    if len(words_left) >= 3 and len(words_right) >= 3 and words_left[:3] == words_right[:3]:
        return True
    short, long = (words_left, words_right) if len(words_left) <= len(words_right) else (words_right, words_left)
    keys = [word for word in short if len(word) >= 2 and word not in _CUSTOMER_STOP]
    return bool(keys) and all(_initialism_of(word, long) for word in keys)


def _customer_compatible(first: dict[str, Any], second: dict[str, Any]) -> bool:
    """Same customer when both are printed; an unprinted one is accepted when its name is named in the other."""
    left, right = _flat(first.get("customer")), _flat(second.get("customer"))
    if left and right:
        return _same_customer(first, second)
    known = left or right
    other = second if left else first
    if not known:
        return _exact_value(first, second)
    other_text = _flat(other.get("_text")).lower()
    tokens = [token for token in re.findall(r"[a-z]{3,}", known.lower()) if token not in ("limited", "ltd", "the")]
    return bool(other_text and any(token in other_text for token in tokens))


def _date_named(text: str, iso: str) -> bool:
    """Does ``text`` name the earlier filing's date in a printed form?"""
    try:
        day = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return False
    months = ("January", "February", "March", "April", "May", "June", "July", "August", "September",
              "October", "November", "December")
    month = months[day.month - 1]
    forms = (iso, f"{day.day:02d}.{day.month:02d}.{day.year}", f"{day.day}/{day.month:02d}/{day.year}",
             f"{month} {day.day}, {day.year}", f"{day.day} {month} {day.year}",
             f"{month} {day.day:02d}, {day.year}")
    low = _flat(text).lower()
    return any(form.lower() in low for form in forms)


_PRESS_RELEASE_ORDER = re.compile(r"\b(?:press|media)\s+release\b", re.I)


def _named_customer(row: dict[str, Any]) -> str:
    cust = _strip_party_junk(row.get("customer"))
    return "" if not cust or _UNDISCLOSED_CUSTOMER.search(cust) else cust


def _fold_same_order(rows: list[dict[str, Any]], amends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """B2: the same order filed twice (Reg 30 + press release) is one event at the earlier ``known_at``."""
    kept: list[dict[str, Any]] = []
    dropped: set[int] = set()
    for row in sorted((r for r in rows if r["kind"] == "order_win"),
                      key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or ""))):
        match = None
        row_is_pr = bool(_PRESS_RELEASE_ORDER.search(f"{row.get('title') or ''} {(row.get('_text') or '')[:800]}"))
        for prior in kept:
            if prior["doc_key"] == row["doc_key"] or prior["symbol"] != row["symbol"]:
                continue
            try:
                gap = abs((date.fromisoformat(str(row["filing_date"]))
                           - date.fromisoformat(str(prior["filing_date"]))).days)
            except (TypeError, ValueError):
                continue
            prior_is_pr = bool(
                _PRESS_RELEASE_ORDER.search(f"{prior.get('title') or ''} {(prior.get('_text') or '')[:800]}"))
            if (row_is_pr or prior_is_pr) and gap <= 10:
                left_c, right_c = _named_customer(prior), _named_customer(row)
                both_named = bool(left_c and right_c)
                same_cust = _same_customer(prior, row) if both_named else False
                p_vals, r_vals = _event_values(prior), _event_values(row)
                same_val = _same_value(prior, row, tolerance=0.005)
                same_title = bool(_customer_key(row.get("title"))) \
                    and _customer_key(row.get("title")) == _customer_key(prior.get("title"))
                if (same_val and (same_cust or not both_named)) or (same_cust and not p_vals and not r_vals) \
                        or (same_title and bool(p_vals) != bool(r_vals)):
                    match = prior
                    break
            if not _customer_compatible(prior, row):
                continue
            if gap <= 7 and _same_value(prior, row, tolerance=0.005):
                match = prior
                break
            if 7 < gap <= 120:
                # C2: a later press-release recap must name the earlier date or repeat the value within 0.05%
                tighter = any(abs(left - right) <= 0.0005 * max(1.0, abs(left), abs(right))
                              for left in _event_values(prior) for right in _event_values(row))
                if tighter or _date_named(str(row.get("_text") or ""), str(prior["filing_date"])):
                    match = prior
                    break
        if match is None:
            kept.append(row)
            continue
        if not _event_values(match) and _event_values(row):
            # the unvalued cover letter was known earlier: keep its known_at, take the twin's printed figures.
            for field in ("amount_inr_cr", "amount_usd_mn", "value_text", "value_total", "value_annual"):
                match[field] = row.get(field)
            match["detail"] = "amount and value taken from the twin filing of the same order"
        dropped.add(id(row))
        amends.append({
            "doc_key": row["doc_key"], "symbol": row["symbol"], "amends": match["doc_key"],
            "filing_date": row.get("filing_date"), "known_at": row.get("known_at"),
            "why": "same order: value within 0.5% and a compatible customer, within 7 days; earlier known_at kept",
        })
    return [row for row in rows if id(row) not in dropped]


def _link_amendments(rows: list[dict[str, Any]]) -> None:
    """B3: an order amendment/variation/extension points at the earlier order it changes."""
    orders = [r for r in rows if r["kind"] == "order_win"]
    for row in rows:
        if row["kind"] != "order_amendment":
            continue
        best: dict[str, Any] | None = None
        best_days = 10_000
        for candidate in orders:
            if candidate["symbol"] != row["symbol"] or not row.get("filing_date") or not candidate.get("filing_date"):
                continue
            try:
                days = (date.fromisoformat(str(row["filing_date"]))
                        - date.fromisoformat(str(candidate["filing_date"]))).days
            except ValueError:
                continue
            if days < 0 or days > 90:
                continue
            base = row.get("_base_value")
            amount = candidate.get("amount_inr_cr")
            value_match = (base is not None and amount is not None
                           and abs(float(base) - float(amount)) <= 0.01 * max(1.0, abs(float(base))))
            if not value_match and not _same_customer(row, candidate):
                continue
            if days < best_days:
                best, best_days = candidate, days
        row["amends"] = best["doc_key"] if best else None


def _row_size(row: dict[str, Any]) -> float | None:
    for key in ("amount_inr_cr", "value_total", "value_annual"):
        if row.get(key) is not None:
            return float(row[key])
    return None


def _raise_family(instrument: Any) -> str:
    value = _flat(instrument).lower()
    return "equity" if value in ("preferential", "warrant", "equity", "equity+warrant", "qip", "mixed") else value


def _assign_raise_ids(rows: list[dict[str, Any]]) -> None:
    """C1: one raise across its stages -- same instrument, size within 5%, within 365 days -- one raise_id.

    Every stage stays as its own dated row; ``raise_primary=1`` marks the one row a factor may use.
    Dedupe verified rows on (symbol, instrument, amount, stage) so only one row per stage stays verified.
    """
    clusters: dict[str, list[dict[str, Any]]] = {}
    raises = sorted((r for r in rows if r["kind"] == "fund_raise"),
                    key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or ""), int(r.get("seq") or 1)))
    for row in raises:
        size, family = _row_size(row), _raise_family(row.get("instrument"))
        gid = None
        for existing, members in clusters.items():
            anchor = members[0]
            anchor_family = _raise_family(anchor.get("instrument"))
            compatible = (anchor_family == family
                          or (not family and anchor_family == "equity")
                          or (not anchor_family and family == "equity"))
            if anchor["symbol"] != row["symbol"] or not compatible:
                continue
            anchor_size = _row_size(anchor)
            if size is None or anchor_size is None:
                continue
            try:
                gap = abs((date.fromisoformat(str(row["filing_date"]))
                           - date.fromisoformat(str(anchor["filing_date"]))).days)
            except (TypeError, ValueError):
                continue
            near = abs(size - anchor_size) <= 0.05 * max(1.0, anchor_size)
            doubled = gap == 0 and (abs(size - 2 * anchor_size) <= 0.02 * max(1.0, 2 * anchor_size)
                                    or abs(anchor_size - 2 * size) <= 0.02 * max(1.0, 2 * size))
            if gap <= 365 and (near or doubled):
                gid = existing
                break
        if gid is None:
            base = f"{row['symbol']}:{row.get('filing_date') or ''}:{row.get('instrument') or 'raise'}"
            gid, suffix = base, 2
            while gid in clusters:
                gid, suffix = f"{base}:{suffix}", suffix + 1
            clusters[gid] = []
        clusters[gid].append(row)
        row["raise_id"], row["raise_primary"] = gid, 0
    seen_stage: set[tuple[Any, ...]] = set()
    for row in raises:
        if row.get("status") != "verified":
            continue
        size = _row_size(row)
        if size is None:
            continue
        key = (row.get("symbol"), _flat(row.get("instrument")).lower(), round(size, 2), row.get("raise_stage"))
        if key in seen_stage:
            row["status"] = "unverified"
            row["detail"] = row.get("detail") or "duplicate raise stage (already filed)"
        else:
            seen_stage.add(key)
    for members in clusters.values():
        best_rank = max(_RAISE_STAGE_RANK.get(str(r.get("raise_stage")), 0) for r in members)
        top = [r for r in members if _RAISE_STAGE_RANK.get(str(r.get("raise_stage")), 0) == best_rank]
        best = min(top, key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or ""),
                                       int(r.get("seq") or 1)))
        best["raise_primary"] = 1


def _same_doc_text(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """True when two filings of the same symbol share the same (or >=92% identical) normalised body text."""
    import difflib

    left = re.sub(r"\s+", " ", _flat(first.get("_text_full") or first.get("_text") or "")).strip().lower()
    right = re.sub(r"\s+", " ", _flat(second.get("_text_full") or second.get("_text") or "")).strip().lower()
    if len(left) < 120 or len(right) < 120:
        return False
    if left[:3000] == right[:3000]:
        return True
    if abs(len(left) - len(right)) > 0.20 * max(len(left), len(right)):
        return False
    return difflib.SequenceMatcher(None, left[:3000], right[:3000]).ratio() >= 0.92


def _is_revised_outcome(row: Mapping[str, Any]) -> bool:
    title = _flat(row.get("title") or "")
    return bool(re.search(r"\brevised\b", title, re.I) and re.search(
        r"\b(?:outcome|board|committee|intimation|disclosure|allotment)\b|^revised\b", title, re.I
    ))


def _fold_same_raise(rows: list[dict[str, Any]], amends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C1/T-242 round 5 + model r2: fold repeat filings, same-text duplicates, and same-day revised outcomes.

    Same company, an amount within 0.5%, the same printed share count, or identical body text within 10 days:
    the restating/superseded row names the kept step in ``amends``.  A same-day "Revised" outcome supersedes
    the original.  Two letters filed the same day about one step keep the more advanced stage; a step *after*
    the earlier one, a notice (a postal-ballot or EGM notice is its own dated step) and an earlier-stage row
    that is not the same day are never folded.
    """
    kept: list[dict[str, Any]] = []
    dropped: set[int] = set()
    raises = sorted((r for r in rows if r["kind"] == "fund_raise"),
                    key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or "")))
    for row in raises:
        match = None
        fold_reason = ("same raise step: same stage or a restatement, amount within 0.5% or the same share count, "
                       "within 10 days; the completed step and its earlier known_at are kept")
        for prior in kept:
            if prior["symbol"] != row["symbol"] or prior.get("doc_key") == row.get("doc_key"):
                continue
            try:
                gap = abs((date.fromisoformat(str(row.get("filing_date")))
                           - date.fromisoformat(str(prior.get("filing_date")))).days)
            except (TypeError, ValueError):
                continue
            if gap > 10:
                continue
            same_day = str(row.get("filing_date")) == str(prior.get("filing_date"))
            row_rev, prior_rev = _is_revised_outcome(row), _is_revised_outcome(prior)
            if same_day and row_rev != prior_rev and not _RAISE_NOTICE.search(_flat(row.get("title"))):
                match = prior
                fold_reason = "same-day revised outcome supersedes original"
                break
            same_text = gap <= 7 and _same_doc_text(prior, row)
            same_amount = _same_value(prior, row, tolerance=0.005)
            same_shares = (prior.get("shares") is not None and row.get("shares") is not None
                           and abs(float(prior["shares"]) - float(row["shares"])) < 1e-6)
            if not (same_text or same_amount or same_shares):
                continue
            if not same_text and _RAISE_NOTICE.search(_flat(row.get("title"))):
                continue
            rank = _RAISE_STAGE_RANK.get(str(row.get("raise_stage")), 0)
            prior_rank = _RAISE_STAGE_RANK.get(str(prior.get("raise_stage")), 0)
            if not same_text and not same_day and rank > prior_rank:
                continue            # a later stage is a new dated step of the same raise
            row_has_amt = row.get("amount_inr_cr") is not None or row.get("amount_usd_mn") is not None
            prior_has_amt = prior.get("amount_inr_cr") is not None or prior.get("amount_usd_mn") is not None
            if not same_text and same_day and rank > prior_rank and not row_has_amt and prior_has_amt:
                continue            # never drop a quantified raise step for an unquantified same-day twin
            match = prior
            if same_text:
                fold_reason = "duplicate filing: same document text filed twice"
            break
        if match is None:
            kept.append(row)
            continue
        rank = _RAISE_STAGE_RANK.get(str(row.get("raise_stage")), 0)
        prior_rank = _RAISE_STAGE_RANK.get(str(match.get("raise_stage")), 0)
        row_has_amt = row.get("amount_inr_cr") is not None or row.get("amount_usd_mn") is not None
        match_has_amt = match.get("amount_inr_cr") is not None or match.get("amount_usd_mn") is not None
        same_day = str(row.get("filing_date")) == str(match.get("filing_date"))
        row_wins = (
            (same_day and _is_revised_outcome(row) and not _is_revised_outcome(match))
            or (not (same_day and _is_revised_outcome(match) and not _is_revised_outcome(row))
                and (
                    rank > prior_rank
                    or (rank == prior_rank and (match.get("method") == "computed" and row.get("method") != "computed"))
                    or (rank == prior_rank and not (row.get("method") == "computed" and match.get("method") != "computed")
                        and row_has_amt and not match_has_amt)
                ))
        )
        if row_wins:
            winner, loser = row, match
            kept[kept.index(match)] = row
            dropped.add(id(match))
        else:
            winner, loser = match, row
            dropped.add(id(row))
        amends.append({
            "doc_key": loser["doc_key"], "symbol": loser["symbol"], "amends": winner["doc_key"],
            "filing_date": loser.get("filing_date"), "known_at": loser.get("known_at"),
            "why": fold_reason,
        })
    return [row for row in rows if id(row) not in dropped]


def _drop_restated_capacity(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """C4: a capacity event narrated as background in a later filing is dropped; a first disclosure keeps the
    printed event date."""
    kept: list[dict[str, Any]] = []
    dropped: set[int] = set()
    capacity = sorted((r for r in rows if r["kind"] == "capacity_commissioned"),
                      key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or "")))
    for row in capacity:
        value, unit = row.get("capacity_value"), row.get("capacity_unit")
        earlier = [k for k in kept if k["symbol"] == row["symbol"] and k.get("capacity_unit") == unit
                   and k.get("capacity_value") is not None and value is not None
                   and abs(float(k["capacity_value"]) - float(value)) <= 0.01 * max(1.0, abs(float(value)))]
        subject, first_sents = _subject_and_first_sentences(str(row.get("title") or ""), str(row.get("_text") or ""), count=1)
        background = not any(_CAPACITY_CUE.search(s) for s in (str(row.get("title") or ""), subject, *first_sents) if s)
        if background and earlier:
            dropped.add(id(row))
            continue
        event_date = row.get("event_date")
        if event_date and row.get("filing_date") and str(event_date) < str(row["filing_date"]):
            near = [k for k in kept if k["symbol"] == row["symbol"] and k.get("filing_date")
                    and abs((date.fromisoformat(str(event_date))
                             - date.fromisoformat(str(k["filing_date"]))).days) <= 10]
            if near:
                dropped.add(id(row))
                continue
        kept.append(row)
    return [row for row in rows if id(row) not in dropped]


# ------------------------------------------------------------------ documents
EVENT_DOC_TYPES = ("announcement", "press_release")   # T-242: order wins also arrive as press releases


def load_docs(store: str) -> list[dict[str, Any]]:
    """Every announcement of one store with its first pages (main DB, OCR fallback) -- read-only."""
    from reality_engine.db.readonly import connect_ro
    from reality_engine.research.driver_claims import ocr_page_texts

    con = connect_ro(store_path(store), timeout_s=60)
    con.row_factory = sqlite3.Row
    try:
        doc_rows: list[Any] = list(con.execute(
            "SELECT doc_key, symbol, isin, title, filing_date, known_at, pages FROM doc "
            f"WHERE doc_type IN ({','.join('?' for _ in EVENT_DOC_TYPES)}) "
            "ORDER BY COALESCE(known_at, filing_date), doc_key", EVENT_DOC_TYPES) or [])
        company_name = ""
        try:
            comp_rows: list[Any] = list(con.execute("SELECT name FROM company LIMIT 1") or [])
            if comp_rows and comp_rows[0] is not None and comp_rows[0][0]:
                company_name = str(comp_rows[0][0])
        except sqlite3.Error:
            company_name = ""
        docs: list[dict[str, Any]] = [
            {column: row[column] for column in
             ("doc_key", "symbol", "isin", "title", "filing_date", "known_at", "pages")}
            for row in doc_rows]
        pages: dict[str, dict[int, str]] = defaultdict(dict)
        page_rows: list[Any] = list(con.execute(
            "SELECT doc_key, page, text FROM doc_page ORDER BY doc_key, page") or [])
        for row in page_rows:
            pages[str(row["doc_key"])][int(row["page"])] = str(row["text"] or "")
    finally:
        con.close()
    ocr = ocr_page_texts(store, EVENT_DOC_TYPES)
    out: list[dict[str, Any]] = []
    for doc in docs:
        key = str(doc["doc_key"])
        doc["store"] = store
        doc["doc_key"] = key
        doc["company_name"] = company_name
        kept = {page: pages[key][page] for page in sorted(pages.get(key, {}))[:PAGES]}
        for page in kept:
            if not _flat(kept[page]) and (key, page) in ocr:
                kept[page] = ocr[(key, page)]
        doc["pages"] = kept
        doc["text"] = "\n".join(kept[page] for page in sorted(kept))
        doc["head"] = "\n".join(kept[page] for page in sorted(kept)[:2])
        out.append(doc)
    return out


def _referenced_date(title: str, text: str) -> str | None:
    body = _flat(f"{title} {text[:1500]}")
    match = _DATE_DMY.search(body)
    if match:
        day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
        if year < 100:
            year += 2000
        try:
            return f"{year:04d}-{month:02d}-{day:02d}"
        except ValueError:
            return None
    for rx, order in ((_DATE_MD, "dm"), (_DATE_MDY, "md")):
        match = rx.search(body)
        if not match:
            continue
        if order == "dm":
            day, month, year = int(match.group(1)), _MONTHS[match.group(2).lower()], int(match.group(3))
        else:
            month, day, year = _MONTHS[match.group(1).lower()], int(match.group(2)), int(match.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"
    return None


_TITLE_STOP = frozenset(
    "addendum corrigendum revised supplementary clarification intimation dated company limited ltd that this with "
    "from under regulation regulations sebi circular letter update regarding into the and for are was were will".split())


def _content_words(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z]{4,}", _flat(text).lower()) if word not in _TITLE_STOP}


def amend_rows(docs: list[dict[str, Any]], classified: set[str]) -> tuple[list[dict[str, Any]], set[str]]:
    """Addendum/corrigendum rows linked to the earlier filing they name; those documents are skipped.

    Only a filing that is itself an event, or an addendum to one, is linked: a charter-party addendum is
    not an order/capex/raise event and must not clutter the table.
    """
    amends: list[dict[str, Any]] = []
    skipped: set[str] = set()
    earlier = [(d["doc_key"], d.get("filing_date"), d.get("title") or "",
                d.get("symbol"), d.get("known_at")) for d in docs]
    for doc in docs:
        title = doc.get("title") or ""
        if not _ADDENDUM.search(title):
            continue
        dated = _referenced_date(title, doc.get("text") or "")
        if not dated:
            continue
        candidates = [row for row in earlier
                      if row[1] == dated and row[0] != doc["doc_key"] and row[3] == doc.get("symbol")]
        if not candidates:
            continue
        target = sorted(candidates, key=lambda row: row[4] or "")[-1]
        if doc["doc_key"] not in classified and target[0] not in classified:
            continue
        if not (_content_words(title) & _content_words(target[2])):
            continue                 # "charter party" addendum is not an addendum to the order filed that day
        skipped.add(doc["doc_key"])
        amends.append({"doc_key": doc["doc_key"], "symbol": doc.get("symbol"), "amends": target[0],
                       "filing_date": doc.get("filing_date"), "known_at": doc.get("known_at"),
                       "why": _flat(f"{title} dated {dated}")[:200]})
    return amends, skipped


# ------------------------------------------------------------------ model-first + fallback
_HARD_RAISE_VETO = re.compile(
    r"framework\s+for\s+fund\s*raising|large\s+corporates?|credit\s+rating|rating\s+(?:action|revision|rationale)"
    r"|the\s+exchange\s+has\s+received\s+the\s+disclosure|disclosure\s+(?:received|under).{0,80}"
    r"(?:SAST|takeover|regulation\s+(?:29|31|18))|u/r\s*7\(2\)|insider\s+trading"
    r"|statement\s+of\s+deviation|utilisation|utilization|\bdeviation\b"
    r"|\bESOPs?\b|\bESOS\b|employee\s+stock\s+options?|stock\s+options?|employee\s+benefit|share\s+based\s+employee"
    r"|sweat\s+equity|\bRSUs?\b|restricted\s+stock"
    r"|open\s+offer|pre[-\s]offer|manager\s+to\s+the\s+offer|takeover"
    r"|borrowing\s+limits?|limit\s+of\s+borrowings?|increase\s+in\s+(?:the\s+)?borrowing",
    re.I,
)

EVENT_PROMPT_V1 = """Read one Indian stock-exchange filing (headline + up to first 4 pages). Return STRICT JSON only, no prose, no code fence.

Classify whether this filing discloses an actual customer ORDER WIN (`order_win`) or the listed company's own FUND RAISE (`fund_raise`), or `not_event`.
If the filing discloses multiple distinct orders (different orders/contracts), return one object per order in `events`.
If the filing is NOT an order win and NOT the company's own fund raise, return ONE object in `events` with `"is_event": false, "event_type": "not_event"` and a short `not_event_reason`.

JSON shape:
{"events":[{"is_event":true,"event_type":"order_win|fund_raise|not_event","not_event_reason":null,"stage":"received|loa|l1_only|amended|cancelled|approved_board|approved_shareholders|filed_offer_doc|allotted|in_principle|withdrawn","instrument":"equity|warrants|ncd|ccd|qip|rights|preferential|ipo|bonus|other|null","amounts":[{"value_text":"exact substring from text","number":0.0,"unit":"crore|lakh|million|billion|unit","currency":"INR|USD|EUR|GBP|...","role":"order_size|annual_value|tranche|total_issue|equity_leg|warrant_leg|board_limit|offered_size|threshold|other"}],"tenure_years":null,"awardee":"exact printed name or null","awardee_is_subsidiary":false,"awardee_is_joint":false,"customer":"exact printed customer or null","execution_period":"exact printed period or null","execution_months":null,"shares":null,"price_per_share":null}]}

Rules for `amounts` (NEVER invent or convert numbers):
- Copy `value_text` VERBATIM as a contiguous substring from the filing text, INCLUDING the currency symbol/code and scale word (e.g. "Rs. 40.58 Crores", "USD 9.28 million", "Rs. 1,60,00,00,000/-", "€ 4,222,683").
- Set `number` to the exact number printed inside `value_text` BEFORE any unit conversion (e.g. 1600000000 for "Rs. 1,60,00,00,000/-", 40.58 for "Rs. 40.58 Crores", 2593125 for "USD 2,593,125").
- Set `unit` to the scale word printed in `value_text` ("crore", "lakh", "million", "billion") or "unit" if it is a full currency amount with no scale word.
- Set `currency` to the printed currency ("INR", "USD", "EUR", "GBP", etc.). Keep USD in USD and EUR in EUR; NEVER convert USD/EUR to INR.

Rules for `order_win`:
- NOT an order win (`is_event`: false, `event_type`: "not_event") if it is: a Government/Ministry order appointing or removing a director/CMD; a SEBI/IRDAI/RBI/Court/Tribunal/NCLT/Regional Director/Tax/GST/Customs/Legal Metrology order or regulatory approval to launch products; a coal block termination, PLI ineligibility, or MoU called off; a board meeting outcome with no order; an LOI/LoA to set up the company's OWN outlet, dealership, showroom or 3S facility; a quarterly/annual order-inflow roll-up or order-book summary; or an EPC contract where the listed company is the BUYER paying a contractor.
- `stage`: "loa" (LoA/LoI received), "received" (PO/work order/contract received), "l1_only" (declared L1/lowest bidder only, no award/LoA received yet), "amended" (variation/extension of existing order), "cancelled" (order cancelled/terminated).
- `amounts`: use role "order_size" for the value of THIS new order (for a JV/consortium or joint company+subsidiary order that prints the company's own share separately from the gross value, put the company's own share as "order_size" and the gross value as "other"). Use role "annual_value" ONLY when the value is explicitly per annum/yearly/monthly, and set `tenure_years` if the contract tenure is printed in years. Put past/delivered order values, project GDV, project cost, FY order-book targets/guidance, or the company's own capex as "other", NEVER "order_size".
- `awardee`: the exact printed name of the entity winning the order (the listed company or its named subsidiary). Set `awardee_is_subsidiary`: true ONLY when the awardee itself is a subsidiary of the listed company (and NEVER when the CUSTOMER is described as a subsidiary of another group like "SECL (Subsidiary Company) of Coal India Limited"). Set `awardee_is_joint`: true ONLY when the listed company AND its subsidiary receive the order together.
- `customer`: exact printed name of the entity awarding the order (null if confidential/withheld/undisclosed, or generic like "a leading domestic company", or a bare country/own business segment/headline).

Rules for `fund_raise`:
- NOT a fund raise (`is_event`: false, `event_type`: "not_event") if it is: a divestment/stake sale/SPV sale; an acquisition/investment/subscription in another entity's shares/CCPS/OCRPS or asset/IPR purchase; an unsecured loan granted to a subsidiary; an NCLT/NCLAT scheme update with no actual share/debt issuance in this filing; a credit facility/bank loan revision, ESOP, SAST/open offer, statement of deviation/utilisation, debt redemption/interest payment, or warrant lapse.
- `stage`: "allotted" (actual allotment/conversion/issue closure), "approved_board" (board/committee approval or enabling resolution), "approved_shareholders" (AGM/EGM/postal ballot voting result), "filed_offer_doc" (draft prospectus/offer doc/DLOF or EGM/postal ballot notice), "in_principle" (exchange in-principle approval), "withdrawn" (proposed issue withdrawn/cancelled).
- `instrument`: "equity" | "warrants" | "ncd" | "ccd" | "qip" | "rights" | "preferential" | "ipo" | "bonus" | "other". Use "bonus" for bonus share issues.
- `amounts`:
  - Use role "total_issue" for the actual total size of THIS filing's step (whether allotted, approved by board/shareholders, or offered in this prospectus). If a filing prints multiple tranches AND a combined total (e.g. Rs 420 cr + Rs 980 cr aggregating to Rs 1,400 cr), mark the combined total as "total_issue" and each tranche as "tranche".
  - Use role "tranche", "equity_leg", or "warrant_leg" when the filing issues/approves multiple tranches or equity+warrant legs and prints each leg's rupee amount.
  - Use role "board_limit" ONLY for an EARLIER umbrella board limit quoted as background in a later filing (prospectus, allotment, clarification) — NEVER label this filing's own board approval size as "board_limit".
  - Use role "offered_size" for the offered/maximum issue size when a smaller amount is actually allotted in this filing.
  - Use role "threshold" for a regulatory/single-QIB size threshold.
  - Use role "other" for paid-up/authorised share capital, a 25% upfront / 75% balance partial instalment when the full total is separate, green shoe already included inside `total_issue`, premium/accrued interest, or acquisition consideration.
- `shares`: number of shares/warrants/NCDs in THIS step only (null if only post-issue/cumulative count is printed). `price_per_share`: printed issue price per unit."""


def prompt_fingerprint(version: str = EVENT_PROMPT_VERSION, model: str = MODEL) -> str:
    """Short sha256 fingerprint of the active model-first prompt template and model id."""
    template = EVENT_PROMPT_V1 if version == "v1" else EVENT_PROMPT_V1
    return hashlib.sha256(f"{model}\n{version}\n{template}".encode("utf-8")).hexdigest()[:12]


def _order_win_candidate(title: str, head: str) -> bool:
    """True when the existing classifier or a soft-vetoed order cue puts this filing in ``order_win``."""
    body = _flat(f"{title} {head}")
    if _ORDER_VETO.search(body):
        return False
    if _RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}")):
        return False
    amend = _order_amendment_clause(title, head)
    if amend:
        prose = _prose_order_records(title, head)
        if not (len({round(float(r["value_cr"]), 4) for r in prose}) >= 2
                and not re.search(r"variation|amendment|extension|cancel|reduc|withdraw|short[-\s]?clos|descop|foreclos",
                                  title, re.I)):
            return False
    return bool(
        order_wins.parse(_flat(title), _flat(head))
        or _loose_order_record(title, head)
        or order_wins.WIN.search(body)
    )


def _fund_raise_candidate(title: str, head: str, text: str) -> bool:
    """True when the existing classifier or a soft-vetoed raise cue puts this filing in ``fund_raise``."""
    body = _flat(f"{title} {head}")
    full = _flat(f"{title} {text}")
    if not _RAISE_CUE.search(body):
        return False
    if _HARD_RAISE_VETO.search(body) or _RAISE_DEBT_VETO.search(_flat(f"{title} {head[:1200]}")) \
            or _RAISE_ADVISORY_VETO.search(body):
        return False
    if _INTIMATION.search(body) and not (_DONE.search(body) or _RAISE_DONE.search(body)):
        return False
    return bool(_RAISE_ISSUANCE.search(full) or _RAISE_STEP_TOTAL.search(full) or _RAISE_CONCLUDED.search(full))


def _legacy_model_prompt(doc: dict[str, Any], kinds: list[str]) -> str:
    text = (doc.get("text") or doc.get("head") or "")[:MAX_MODEL_CHARS]
    schema = (
        '{"events":[{"kind":"order_win|capex_approval|capacity_commissioned|fund_raise",'
        '"amount_inr_cr":null,"amount_usd_mn":null,"value_text":null,"customer":null,'
        '"execution_months":null,"purpose":null,"completion":null,"capacity_value":null,'
        '"capacity_unit":null,"plant":null,"price_per_share":null,"shares":null,"instrument":null}]}'
    )
    return (
        "You read one Indian exchange announcement. Return STRICT JSON only, no prose, no code fence.\n"
        f"Classes to fill: {', '.join(kinds)}.\n"
        "Copy every number as printed on the page. value_text must be the exact sentence/table text from the "
        "announcement that prints the number; if the number is not printed, leave it null. Do not infer a "
        "number that the text does not print. amount_inr_cr is in crore; keep a dollar amount in amount_usd_mn. "
        "capacity_value is the number and capacity_unit the printed unit (MW, TPA, MT, KL ...).\n"
        f"JSON shape: {schema}\n\n"
        f"TITLE: {doc.get('title') or ''}\n\nPAGES:\n{text}"
    )


def model_prompt(doc: dict[str, Any], kinds: list[str] | None = None) -> str:
    """Build the model prompt over the filing's first 4 pages (v1 schema for order_win/fund_raise)."""
    if kinds and not any(k in MODEL_FIRST_KINDS for k in kinds):
        return _legacy_model_prompt(doc, kinds)
    text = (doc.get("text") or doc.get("head") or "")[:MAX_MODEL_CHARS]
    company = doc.get("company_name") or doc.get("symbol") or ""
    cand = ", ".join(kinds) if kinds else "order_win, fund_raise"
    return (
        f"{EVENT_PROMPT_V1}\n\n"
        f"LISTED COMPANY: {company} (SYMBOL: {doc.get('symbol') or ''})\n"
        f"FILING DATE: {doc.get('filing_date') or ''}\n"
        f"CANDIDATE KINDS: {cand}\n"
        f"TITLE: {doc.get('title') or ''}\n\n"
        f"PAGES (first {PAGES}):\n{text}"
    )


def parse_model_reply(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*|\s*```$", "", text.strip())
    obj_start, obj_end = text.find("{"), text.rfind("}")
    arr_start, arr_end = text.find("["), text.rfind("]")
    if arr_start >= 0 and (obj_start < 0 or arr_start < obj_start) and arr_end > arr_start:
        try:
            items = json.loads(text[arr_start:arr_end + 1])
            if isinstance(items, list):
                return [e for e in items if isinstance(e, dict)]
        except ValueError:
            pass
    if obj_start < 0 or obj_end <= obj_start:
        return []
    try:
        payload = json.loads(text[obj_start:obj_end + 1])
    except ValueError:
        return []
    if isinstance(payload, dict):
        if "events" in payload:
            return [e for e in (payload.get("events") or []) if isinstance(e, dict)]
        if any(k in payload for k in ("event_type", "is_event", "kind")):
            return [payload]
    return []


def _model_unit_printed(row: dict[str, Any]) -> bool:
    """A model amount needs its scale word in the quoted text, else the unit is the model's guess."""
    text = row.get("value_text") or ""
    if not text:
        return False
    if row.get("amount_inr_cr") is not None:
        return bool(_RS_FULL.search(text) or re.search(r"crore|\bcr\b|lakh|lacs?\b|million|\bmn\b|billion|\bbn\b|/-",
                                                      text, re.I))
    if row.get("amount_usd_mn") is not None:
        return bool(re.search(r"million|\bmn\b|billion|\bbn\b", text, re.I))
    unit = (row.get("capacity_unit") or "").lower()
    return bool(unit and unit.split("_")[0] in text.lower())


_INR_CUR_RX = re.compile(r"(?:₹|\bRs\.?|\bINR\b|\bRupees?\b)", re.I)
_USD_CUR_RX = re.compile(r"(?:\bUSD\b|\bUS\s?\$|\bUS\s+Dollars?\b|\$)", re.I)
_FOREIGN_CUR_RX = re.compile(
    r"(?:€|\bEUR\b|\bEuros?\b|£|\bGBP\b|\bPounds?\b|¥|\bJPY\b|\bYen\b|\bAUD\b|\bSGD\b|\bAED\b|\bDirhams?\b|\bCHF\b|\bCAD\b)",
    re.I,
)
_SCALE_WORD_RX = re.compile(
    r"(?<![a-zA-Z])(crores?|cr\.?|crs\.?|lakhs?|lacs?|millions?|mn|billions?|bn)(?![a-zA-Z])",
    re.I,
)
_SKIP_STAGES = frozenset({"l1_only", "cancelled", "withdrawn", "intimation"})
_MAX_EVENT_INR_CR = 100_000.0
_PAREN_WORDS_GLOSS_RX = re.compile(r"\(\s*(?:Indian\s+)?Rupees?\b[^)]*\)", re.I)
_ABOUT_BOILERPLATE_HEAD_RX = re.compile(
    r"(?:^|\n)\s*About\s+(?:the\s+Company|Us|[A-Z][A-Za-z0-9&.'’\-]*(?:\s+[A-Z][A-Za-z0-9&.'’\-]*){0,5})\s*[:\-–—]",
    re.I,
)
_ABOUT_BOILERPLATE_END_RX = re.compile(
    r"\n\s*(?:For\s+more\s+information|For\s+further\s+information|Media\s+(?:queries|contact)|DISCLAIMER|Follow\s+us\s+on)\b",
    re.I,
)


def _find_printed_span(pages: dict[int, str], title: str, value_text: str) -> tuple[str | None, int | None]:
    """Find whitespace-normalised ``value_text`` on pages 1..PAGES (or headline page 0); return (matched_span, page)."""
    needle = _flat(value_text)
    if not needle:
        return None, None
    # Try exact substring first across pages 1..PAGES, then headline
    for page in sorted(pages):
        if int(page) > PAGES:
            continue
        flat_page = _flat(pages[page])
        if needle in flat_page:
            return needle, int(page)
    flat_title = _flat(title)
    if flat_title and needle in flat_title:
        return needle, 0
    # Fallback: symbol spacing differences (e.g. "₹ 1,000" vs "₹1,000") and OCR "¥" for "₹" beside crore/lakh
    has_ind_scale = bool(re.search(r"crore|lakh|\bcr\b|\blacs?\b", needle, re.I))
    parts = [re.escape(needle)]
    flex = re.sub(r"(?:\\₹|\\\$|\\€|\\£|Rs\\\.?|INR|USD)\\\s+", lambda m: m.group(0).rstrip("\\ ") + r"\s*", parts[0], flags=re.I)
    flex = re.sub(r"([₹$€£])", r"\1\\s*", flex)
    if has_ind_scale:
        flex = flex.replace(r"\₹", r"[₹¥]").replace("₹", "[₹¥]")
    for page in sorted(pages):
        if int(page) > PAGES:
            continue
        m = re.search(flex, _flat(pages[page]), re.I)
        if m:
            return m.group(0), int(page)
    if flat_title:
        m = re.search(flex, flat_title, re.I)
        if m:
            return m.group(0), 0
    return None, None


def _norm_currency(raw: Any) -> str:
    val = _flat(raw).upper()
    if val in ("INR", "RS", "RS.", "₹", "RUPEES", "RUPEE"):
        return "INR"
    if val in ("USD", "US$", "$", "US DOLLAR", "US DOLLARS"):
        return "USD"
    if val in ("EUR", "€", "EURO", "EUROS"):
        return "EUR"
    if val in ("GBP", "£", "POUND", "POUNDS"):
        return "GBP"
    if val in ("JPY", "¥", "YEN"):
        return "JPY"
    return val


def _norm_scale(raw: Any) -> str:
    val = _flat(raw).lower().rstrip(".")
    if val in ("crore", "crores", "cr", "crs"):
        return "crore"
    if val in ("lakh", "lakhs", "lac", "lacs"):
        return "lakh"
    if val in ("million", "millions", "mn"):
        return "million"
    if val in ("billion", "billions", "bn"):
        return "billion"
    return "unit" if val in ("", "unit", "units", "rupees", "rupee", "inr", "usd", "dollar", "dollars", "full", "none") else val


def _parse_printed_amount(amt: Mapping[str, Any], pages: dict[int, str], title: str) -> dict[str, Any]:
    """Verify one model amount dict against the printed pages: substring, number, unit, and currency."""
    raw_vt = _flat(amt.get("value_text"))
    role = _flat(amt.get("role") or "other").lower()
    if not raw_vt:
        return {"ok": False, "role": role, "reason": "empty value_text"}
    matched_span, page = _find_printed_span(pages, title, raw_vt)
    if matched_span is None or page is None:
        return {"ok": False, "role": role, "reason": "value_text not printed on page", "value_text": raw_vt}

    # Extract numbers printed inside matched_span (plus OCR-spaced decimals like "43. 50")
    num_tokens = re.findall(r"\d[\d,]*(?:\.\d+)?", matched_span)
    parsed_nums: list[float] = []
    for tok in num_tokens:
        try:
            parsed_nums.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    collapsed_span = re.sub(r"(\d)\.\s+(\d{1,2})\b", r"\1.\2", matched_span)
    collapsed_nums: list[float] = []
    if collapsed_span != matched_span:
        for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", collapsed_span):
            try:
                collapsed_nums.append(float(tok.replace(",", "")))
            except ValueError:
                pass
    if not parsed_nums and not collapsed_nums:
        return {"ok": False, "role": role, "reason": "no number printed in value_text", "value_text": matched_span}

    model_num = amt.get("number")
    try:
        target_num = float(str(model_num).replace(",", "")) if model_num not in (None, "") else None
    except (TypeError, ValueError):
        target_num = None
    if target_num is None:
        return {"ok": False, "role": role, "reason": "model number missing", "value_text": matched_span}
    chosen_num: float | None = None
    for n in parsed_nums:
        if abs(n - target_num) <= 1e-4 * max(1.0, abs(n), abs(target_num)):
            chosen_num = n
            break
    if chosen_num is None:
        for n in collapsed_nums:
            if abs(n - target_num) <= 1e-4 * max(1.0, abs(n), abs(target_num)):
                chosen_num = n
                break
    if chosen_num is None and target_num > 0:
        # Recover exact digits when LLM miscounts zeros in Indian comma notation (10x/100x/1000x slip)
        for n in parsed_nums:
            if n > 0:
                ratio = max(n, target_num) / min(n, target_num)
                if any(abs(ratio - p) <= 1e-4 * p for p in (10.0, 100.0, 1000.0)):
                    chosen_num = n
                    break
    if chosen_num is None:
        return {"ok": False, "role": role, "reason": "number does not parse from value_text",
                "value_text": matched_span}

    # Check currency and scale are printed (allowing OCR ¥->₹ on crore/lakh, Indian comma full rupees, and page unit headers)
    # Strip parenthetical written-out rupee glosses only when chosen_num >= 100k (a full-rupee integer),
    # so "INR 3,849,088,060 (Indian Rupees Three Billion ...)" stays in rupees while "Rs. 660.79/- (Rupees ... Crore ...)"
    # keeps its Crore scale word (T-242 r2).
    scale_span = _PAREN_WORDS_GLOSS_RX.sub(" ", matched_span) if chosen_num >= 100_000.0 else matched_span
    scale_matches = [_norm_scale(m.group(1)) for m in _SCALE_WORD_RX.finditer(scale_span)]
    if not scale_matches and _norm_scale(amt.get("unit")) in ("crore", "lakh", "million", "billion"):
        scale_matches = [_norm_scale(m.group(1)) for m in _SCALE_WORD_RX.finditer(matched_span)]
    has_inr = bool(_INR_CUR_RX.search(matched_span))
    has_usd = bool(_USD_CUR_RX.search(matched_span))
    foreign_m = _FOREIGN_CUR_RX.search(matched_span)
    decl_cur = _norm_currency(amt.get("currency"))
    decl_unit = _norm_scale(amt.get("unit"))
    page_text = _flat(pages.get(page, "") or title)
    if foreign_m and foreign_m.group(0) == "¥" and decl_cur == "INR" and any(s in ("crore", "lakh") for s in scale_matches):
        has_inr = True
        foreign_m = None

    table_header_scale: str | None = None
    if has_usd and (decl_cur == "USD" or not has_inr):
        currency = "USD"
    elif has_inr and (decl_cur == "INR" or not has_usd):
        currency = "INR"
    elif foreign_m:
        currency = _norm_currency(foreign_m.group(0))
    elif decl_cur == "INR" and any(s in ("crore", "lakh") for s in scale_matches):
        currency = "INR"
    elif decl_cur == "INR" and chosen_num >= 100_000.0 \
            and re.search(r"\b\d{1,2}(?:,\d{2}){2,},\d{3}(?:\.\d+)?\b", matched_span) \
            and _INR_CUR_RX.search(page_text):
        currency = "INR"
    elif decl_cur == "INR" and decl_unit in ("crore", "lakh") and not scale_matches \
            and ("." in matched_span or chosen_num >= 10.0) \
            and re.search(rf"(?:₹|Rs\.?|INR)\s*(?:in\s*)?{decl_unit}s?|in\s*(?:₹|Rs\.?|INR)\s*{decl_unit}s?", page_text, re.I):
        currency = "INR"
        table_header_scale = decl_unit
    else:
        return {"ok": False, "role": role, "reason": "currency not printed in value_text", "value_text": matched_span}
    if decl_cur and decl_cur != currency:
        # e.g. model said INR on a USD string or vice versa
        return {"ok": False, "role": role, "reason": f"currency mismatch ({decl_cur} vs {currency} in value_text)",
                "value_text": matched_span}

    # Check unit is printed in value_text (or proven by page table header)
    if decl_unit in ("crore", "lakh", "million", "billion"):
        if decl_unit not in scale_matches and table_header_scale != decl_unit:
            return {"ok": False, "role": role, "reason": f"unit '{decl_unit}' not printed in value_text",
                    "value_text": matched_span}
        scale = decl_unit
    elif decl_unit == "unit":
        if scale_matches and chosen_num < 100_000.0:
            # e.g. model set unit='unit' when 'crore' was actually printed (not a full >=100k rupee figure)
            scale = scale_matches[0]
        elif scale_matches and any(s in ("crore", "lakh") for s in scale_matches) and chosen_num >= 100_000.0:
            scale = scale_matches[0]
        else:
            min_full = 100_000.0 if currency == "INR" else 10_000.0
            if chosen_num < min_full:
                return {"ok": False, "role": role, "reason": "unit not printed in value_text",
                        "value_text": matched_span}
            scale = "unit"
    else:
        return {"ok": False, "role": role, "reason": f"unknown/unprinted unit '{decl_unit}'",
                "value_text": matched_span}

    inr_cr: float | None = None
    usd_mn: float | None = None
    if currency == "INR":
        if scale == "unit":
            inr_cr = round(chosen_num / 1e7, 4)
        else:
            factor = _TO_CR[scale]
            inr_cr = round(chosen_num / 1e7, 4) if (scale == "crore" and chosen_num >= 1e6) else round(chosen_num * factor, 4)
        if inr_cr > _MAX_EVENT_INR_CR:
            return {"ok": False, "role": role, "reason": f"amount {inr_cr:g} cr exceeds {_MAX_EVENT_INR_CR:g} cr limit",
                    "value_text": matched_span}
    elif currency == "USD":
        if scale == "unit":
            usd_mn = round(chosen_num / 1e6, 4)
        elif scale in _TO_USD_MN:
            usd_mn = round(chosen_num * _TO_USD_MN[scale], 4)
        else:
            return {"ok": False, "role": role, "reason": f"invalid USD scale '{scale}'", "value_text": matched_span}

    return {
        "ok": True,
        "role": role,
        "value_text": matched_span,
        "page": page,
        "number": chosen_num,
        "scale": scale,
        "currency": currency,
        "inr_cr": inr_cr,
        "usd_mn": usd_mn,
    }


def _awardee_printed(awardee: str, pages: dict[int, str], title: str) -> bool:
    needle = _flat(awardee)
    if not needle or len(needle) < 3:
        return False
    haystack = _flat(" ".join([title] + [pages[p] for p in sorted(pages) if int(p) <= PAGES])).lower()
    if needle.lower() in haystack:
        return True
    # Allow minor punctuation/comma differences ("Co. Ltd." vs "Co., Ltd.")
    def _alnum_ws(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()
    norm_needle = _alnum_ws(needle)
    return bool(norm_needle and len(norm_needle) >= 3 and norm_needle in _alnum_ws(haystack))


def _is_listed_company_name(awardee: str, doc: Mapping[str, Any]) -> bool:
    comp = _flat(doc.get("company_name") or "").lower()
    aw = _flat(awardee).lower()
    if not comp or not aw:
        return False
    clean = lambda s: re.sub(r"\b(?:limited|ltd|private|pvt)\b", "", re.sub(r"[^\w\s]", " ", s)).split()
    c_words, a_words = clean(comp), clean(aw)
    return bool(c_words and a_words and c_words == a_words)


def _verified_tenure_years(raw_tenure: Any, exec_months: Any, text: str) -> float | None:
    """Return tenure in years only when printed on the page."""
    if raw_tenure not in (None, ""):
        try:
            yrs = float(raw_tenure)
        except (TypeError, ValueError):
            yrs = None
        if yrs and yrs > 0:
            flat_t = _flat(text)
            tok = str(int(yrs)) if abs(yrs - round(yrs)) < 1e-6 else f"{yrs:g}"
            if re.search(rf"\b{re.escape(tok)}\s*(?:\([^)]*\)\s*)?(?:years?|yrs?)\b", flat_t, re.I):
                return yrs
    if exec_months not in (None, ""):
        try:
            m = float(exec_months)
            if m > 0:
                return round(m / 12.0, 4)
        except (TypeError, ValueError):
            pass
    return _tenure_years(text, None)


def _norm_instrument(raw: Any) -> str | None:
    val = _flat(raw).lower()
    if not val or val == "null":
        return None
    mapping = {"warrants": "warrant", "warrant": "warrant", "ncds": "ncd", "ncd": "ncd",
               "ccds": "ccd", "ccd": "ccd", "qip": "qip", "rights": "rights",
               "preferential": "preferential", "equity": "equity", "ipo": "ipo",
               "bonus": "bonus", "other": "other"}
    return mapping.get(val, val)


def _script_amount_pairs(script_rows: list[dict[str, Any]]) -> list[tuple[float | None, float | None]]:
    return [(r.get("amount_inr_cr"), r.get("amount_usd_mn")) for r in script_rows
            if r.get("amount_inr_cr") is not None or r.get("amount_usd_mn") is not None]


def _check_script_mismatch(row: dict[str, Any], script_rows: list[dict[str, Any]] | None) -> str | None:
    """Compare model amount against script parse when both have an amount; return detail string on >1% mismatch."""
    if not script_rows:
        return None
    m_inr, m_usd = row.get("amount_inr_cr"), row.get("amount_usd_mn")
    if m_inr is None and m_usd is None:
        return None
    pairs = _script_amount_pairs(script_rows)
    if not pairs:
        return None
    # Match against closest script row (supports multi-order filings)
    for s_inr, s_usd in pairs:
        if m_inr is not None and s_inr is not None and abs(m_inr - s_inr) <= 0.01 * max(1.0, abs(m_inr), abs(s_inr)):
            return None
        if m_usd is not None and s_usd is not None and abs(m_usd - s_usd) <= 0.01 * max(1.0, abs(m_usd), abs(s_usd)):
            return None
    s_inr, s_usd = pairs[0]
    m_str = f"Rs {m_inr:g} cr" if m_inr is not None else f"USD {m_usd:g} mn"
    s_str = f"Rs {s_inr:g} cr" if s_inr is not None else f"USD {s_usd:g} mn"
    return f"amount mismatch: model={m_str} vs script={s_str}"


def _legacy_model_rows(doc: dict[str, Any], kinds: list[str], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        kind = str(event.get("kind") or "")
        if kind not in kinds:
            continue
        row = blank_row(doc, kind)
        row["method"] = "model"
        row["why"] = "model: script could not fill the amount"
        for key in ("customer", "value_text", "purpose", "completion", "capacity_unit", "plant", "instrument"):
            value = event.get(key)
            row[key] = _flat(value)[:500] if isinstance(value, str) and _flat(value) else None
        for key in ("amount_inr_cr", "amount_usd_mn", "execution_months", "capacity_value",
                    "price_per_share", "shares"):
            value = event.get(key)
            try:
                row[key] = None if value in (None, "") else float(value)
            except (TypeError, ValueError):
                row[key] = None
        _split_customer(row)
        if kind == "order_win" and not row.get("order_kind"):
            row["order_kind"] = "new_order"
        size_note = ""
        if kind == "order_win" and (row.get("amount_inr_cr") is not None or row.get("amount_usd_mn") is not None) \
                and _not_order_size(row.get("value_text"), row.get("value_text") or "", doc.get("text") or ""):
            row["amount_inr_cr"] = row["amount_usd_mn"] = None
            size_note = "amount sits beside a GDV/project-cost/target label, not the order size (model)"
        amt_raw = row.get("amount_inr_cr")
        if kind == "order_win" and amt_raw is not None \
                and _ANNUAL_CUE.search(row.get("value_text") or ""):
            annual_val = float(amt_raw)
            row["value_annual"] = annual_val
            tenure = _tenure_years(doc.get("text") or "", row.get("execution_months"))
            if tenure:
                row["value_total"] = round(annual_val * tenure, 4)
                row["amount_inr_cr"] = row["value_total"]
            else:
                row["amount_inr_cr"] = None
        check_doc = {**doc, "pages": {page: text for page, text in doc["pages"].items() if int(page) <= PAGES}}
        if row.get("value_text"):
            row["page"] = _page_of(check_doc["pages"], row["value_text"])
        required = (row.get("capacity_value") if kind == "capacity_commissioned"
                    else row.get("amount_inr_cr") or row.get("amount_usd_mn") or row.get("value_annual"))
        if not required:
            row["status"] = "unverified"
            row["detail"] = size_note or "model filled no amount"
        elif not _model_unit_printed(row) and row.get("value_annual") is None:
            row["status"] = "unverified"
            row["detail"] = "amount unit not printed in the quoted text (model)"
        elif row.get("value_annual") is not None:
            row["status"] = "unverified"
            row["detail"] = ("annual value x printed tenure (model)" if row.get("value_total") is not None
                             else "annual value; tenure not printed, not a total (model)")
        elif _locate(row, check_doc):
            row["status"] = "quarantined"
            row["detail"] = "model value not printed on the first four pages"
        elif row["entity_scope"] == "parent":
            row["status"] = "unverified"
            row["detail"] = "parent-company release"
        else:
            _gate_status(row)
        _finish_scope(row, doc.get("title") or "", doc.get("head") or doc.get("text") or "")
        row["quote"] = row.get("quote") or _flat(doc.get("text"))[:MAX_QUOTE]
        rows.append(row)
    best: dict[str, dict[str, Any]] = {}
    rank = {"verified": 3, "unverified": 2, "quarantined": 1}
    for row in rows:
        current = best.get(row["kind"])
        if current is None or rank.get(row["status"], 0) > rank.get(current["status"], 0):
            best[row["kind"]] = row
    return list(best.values())


_ESOP_PLAN_VETO = re.compile(
    r"\b(?:ESOPs?|ESOS|ESPS|RSUs?)\b|employee\s+stock\s+option|stock\s+option\s+(?:plan|scheme)"
    r"|(?:management|employee|staff|long[-\s]?term)\s+incentive\s+plan|share\s+based\s+employee\s+benefit"
    r"|sweat\s+equity|restricted\s+stock\s+unit|\bexercise\s+of\s+(?:(?:employee|stock|incentive)\s+)+options?\b",
    re.I,
)
_NOT_CASH_RAISE_RX = re.compile(r"\bconsideration\s+other\s+than\s+cash\b|\bshare\s+swap\b", re.I)
_SCHEME_ALLOT_RX = re.compile(
    r"(?:pursuant\s+to|under|in\s+terms\s+of)\s+(?:the\s+|a\s+)?scheme\s+of\s+(?:amalgamation|arrangement)\b"
    r"|\bscheme\s+of\s+(?:amalgamation|arrangement)\b[^.;]{0,140}\b(?:allot\w*|issu\w*)",
    re.I,
)
_BOARD_INTIMATION_MEETING_RX = re.compile(
    r"\b(?:board\s+meeting\s+intimation|intimation\s+of\s+(?:forthcoming\s+)?board\s+meeting"
    r"|prior\s+intimation\b[^.]{0,80}\bregulation\s*(?:29|50))\b"
    r"|\b(?:meeting\s+of\s+the\s+board(?:\s+of\s+directors)?|board\s+meeting)\b[^.]{0,100}\b"
    r"(?:will\s+be\s+held|is\s+scheduled(?:\s+to\s+be\s+held)?|scheduled\s+on|to\s+be\s+held)\b",
    re.I,
)
_BOARD_INTIMATION_CONSIDER_RX = re.compile(
    r"\b(?:to\s+consider|will\s+consider|may\b[^.]{0,30}\bconsider|to\s+transact)\b", re.I
)
_BOARD_OUTCOME_DONE_RX = re.compile(
    r"\b(?:outcome\s+of\s+(?:the\s+)?(?:board|committee)\s+meeting"
    r"|board\s+(?:of\s+directors\s+)?(?:at\s+(?:its|their)\s+meeting\s+)?(?:held\s+(?:today|on)|has\s+(?:,?\s*inter[-\s]?alia\s*,?\s*)?(?:considered\s+and\s+)?approved)"
    r"|commenced\s+at\b[^.]{0,60}\bconcluded\s+at\b)",
    re.I,
)
_SHAREHOLDER_MEETING_NOTICE_RX = re.compile(
    r"\b(?:notice\s+of\s+(?:the\s+)?(?:EGM|AGM|postal\s+ballot|extra[-\s]?ordinary\s+general\s+meeting|annual\s+general\s+meeting)"
    r"|postal\s+ballot\s+notice"
    r"|(?:EGM|AGM|extra[-\s]?ordinary\s+general\s+meeting|annual\s+general\s+meeting)\s+of\s+(?:the\s+)?members)\b",
    re.I,
)
_CAPEX_PRESS_LEAD_RX = re.compile(
    r"\b(?:greenfield\s+plant|brownfield|expand\s+capacity|capacity\s+expansion"
    r"|setup\s+(?:a\s+)?(?:new\s+)?(?:greenfield\s+)?plant|setting\s+up\s+(?:a\s+)?(?:new\s+)?(?:plant|facility)"
    r"|new\s+manufacturing\s+facilit(?:y|ies)|new\s+facilities"
    r"|with\s+(?:Rs\.?|INR|₹|\"?\s*\d+)[^.;]{0,30}(?:investment|capex))\b",
    re.I,
)
_ORDER_REPEAT_RX = re.compile(
    r"\b(?:this\s+is\s+)?further\s+to\s+our\s+(?:disclosure|letter|announcement|intimation)\s+dated\b"
    r"|\bin\s+continuation\s+(?:to|of)\s+our\s+(?:earlier\s+)?(?:disclosure|letter|announcement|intimation)\s+dated\b"
    r"|\badditional\s+announcement\s+in\s+relation\s+to\b",
    re.I,
)
_SHARES_PRINT_RX = re.compile(
    r"(?P<v>\d[\d,]*)\s*(?:\([^)]{0,140}\)\s*)?(?:fully\s+)?(?:convertible\s+)?(?:partly\s+)?"
    r"(?:paid[-\s]?up\s+)?(?:unlisted\s+)?(?:secured\s+|unsecured\s+)?(?:non[-\s]?convertible\s+)?"
    r"(?:equity\s+)?(?:shares?|warrants?|NCDs?|CCDs?|debentures?|units?)\b",
    re.I,
)
_PREMIUM_OF_RX = re.compile(r"(?:at\s+(?:a\s+)?)?premium\s+of\s+(?:Rs\.?|INR|₹|Re\.?)\s*(?P<p>\d[\d,]*(?:\.\d+)?)", re.I)
_FACE_VALUE_BEFORE_RX = re.compile(
    r"(?:face\s+value(?:\s+of)?|equity\s+shares?\s+of|shares?\s+of)\s*(?:Rs\.?|INR|₹|Re\.?)\s*(?P<f>\d[\d,]*(?:\.\d+)?)",
    re.I,
)
_INR_EQV_TAIL_RX = re.compile(
    r"^\s*(?:\(|,|\s)*(?:equivalent\s+to|eqv\.?|eq\.?)?\s*\(?\s*(?:equivalent\s+to\s+|eqv\.?\s+)?"
    r"(?:approx\.?\s*|approximately\s*|~\s*)?(?:Rs\.?|INR|₹)\s*(?:approx\.?\s*|~\s*)?"
    r"(?P<v>\d[\d,]*(?:\.\d+)?)\s*(?P<u>crores?|cr\.?|crs\.?|lakhs?|lacs?|millions?|mn|billions?|bn)?\b",
    re.I,
)


def _in_about_boilerplate(span: str, pages: dict[int, str], title: str) -> bool:
    """True when every occurrence of ``span`` sits inside an 'About <Company>:' boilerplate block."""
    needle = _flat(span)
    if not needle:
        return False
    if _flat(title) and needle in _flat(title):
        return False
    found_in_bp = False
    for page in sorted(pages):
        if int(page) > PAGES:
            continue
        raw = str(pages[page] or "")
        if not raw.strip():
            continue
        spans_bp: list[tuple[int, int]] = []
        for hm in _ABOUT_BOILERPLATE_HEAD_RX.finditer(raw):
            em = _ABOUT_BOILERPLATE_END_RX.search(raw, hm.end())
            spans_bp.append((hm.start(), em.start() if em else len(raw)))
        if not spans_bp:
            if needle in _flat(raw):
                return False
            continue
        outside_parts: list[str] = []
        pos = 0
        for s_idx, e_idx in spans_bp:
            if s_idx > pos:
                outside_parts.append(raw[pos:s_idx])
            if needle in _flat(raw[s_idx:e_idx]):
                found_in_bp = True
            pos = max(pos, e_idx)
        if pos < len(raw):
            outside_parts.append(raw[pos:])
        if needle in _flat("\n".join(outside_parts)):
            return False
    return found_in_bp


def _has_plus_band(span: str, pages: dict[int, str], title: str) -> tuple[bool, str]:
    """True when ``span`` (or its immediate suffix on the page) ends with '+' (a band floor, not exact)."""
    needle = _flat(span)
    if not needle:
        return False, needle
    if re.search(r"\+\s*$", needle) or re.search(
        r"\d\s*\+\s*(?:crores?|cr\.?|crs\.?|lakhs?|lacs?|millions?|mn|billions?|bn)\b", needle, re.I
    ):
        return True, needle
    for src in [title] + [pages[p] for p in sorted(pages) if int(p) <= PAGES]:
        flat_src = _flat(src)
        idx = flat_src.find(needle)
        if idx >= 0:
            tail = flat_src[idx + len(needle): idx + len(needle) + 4]
            if re.match(r"^\s*\+", tail):
                return True, needle + "+"
    return False, needle


def _printed_inr_equivalent(
    chosen: Mapping[str, Any], valid_amounts: list[dict[str, Any]], pages: dict[int, str], title: str
) -> tuple[float | None, str | None]:
    """Find a printed INR equivalent beside a foreign-currency order amount."""
    vt = _flat(chosen.get("value_text"))
    page = chosen.get("page")
    page_text = _flat(title if page == 0 else (pages.get(page or 1) or ""))
    if not vt or not page_text:
        return None, None
    idx = page_text.find(vt)
    tail = page_text[idx + len(vt): idx + len(vt) + 160] if idx >= 0 else ""
    for candidate in (vt, tail):
        if not candidate:
            continue
        # Require an equivalence word or parenthesized INR beside the foreign amount
        if candidate is vt and "(" not in vt and not re.search(r"\bequivalent\b|\beqv\b", vt, re.I):
            continue
        if candidate is tail and not re.match(
            r"^\s*(?:\(|,|\s)*(?:equivalent\b|eqv\b|eq\.|\(\s*(?:approx|approximately|~)?\s*(?:Rs\.?|INR|₹))",
            tail, re.I,
        ):
            continue
        for a in valid_amounts:
            if a.get("currency") == "INR" and a.get("inr_cr") is not None and _flat(a.get("value_text")) in candidate:
                return float(a["inr_cr"]), _flat(a["value_text"])
        search_str = candidate if candidate is tail else candidate[max(0, candidate.find("(")):]
        m = _INR_EQV_TAIL_RX.search(search_str)
        if m:
            num = float(m.group("v").replace(",", ""))
            u = _norm_scale(m.group("u") or "")
            if u in _TO_CR:
                val = round(num * _TO_CR[u], 4)
            elif num >= 100_000.0:
                val = round(num / 1e7, 4)
            else:
                val = None
            if val is not None and 0 < val <= _MAX_EVENT_INR_CR:
                return val, _flat(m.group(0)).strip("(), ")
    return None, None


def _not_a_fund_raise_reason(
    doc: Mapping[str, Any], ev: Mapping[str, Any], instr: str | None, quote: str
) -> tuple[str | None, str | None]:
    """Return ``(stage_override, reason)`` when a model fund_raise is not a listed-company cash raise."""
    title = _flat(doc.get("title") or "")
    head = _flat(doc.get("head") or doc.get("text") or "")
    text = _flat(doc.get("text") or "")
    lead = f"{title} {head[:1600]}"
    # Step 2: Reg 29 / Reg 50 notice of a future Board Meeting ("will consider")
    raw_head = ((doc.get("pages") or {}).get(1) or doc.get("head") or doc.get("text") or "")[:2000]
    sub_m_lead = re.search(r"(?:Sub(?:ject)?|Ref)\s*[:.\-]\s*[^\n]{0,250}", raw_head, re.I)
    subj_line = _flat(f"{title} {sub_m_lead.group(0) if sub_m_lead else ''}")
    is_sh_notice = bool(
        _SHAREHOLDER_MEETING_NOTICE_RX.search(subj_line)
        or re.search(r"\b(?:EGM|AGM|Extra[-\s]?Ordinary\s+General\s+Meeting|Annual\s+General\s+Meeting)\b[^.]{0,60}\b(?:will\s+be\s+held|is\s+scheduled)\b",
                     lead, re.I)
    )
    if not _BOARD_OUTCOME_DONE_RX.search(lead) and not is_sh_notice:
        if _BOARD_INTIMATION_MEETING_RX.search(lead) and _BOARD_INTIMATION_CONSIDER_RX.search(lead):
            return "intimation", "board meeting intimation (stage intimation), not an approved raise"
    # Step 1(c): ESOP / ESOS / Incentive Plan / options exercise
    if _ESOP_PLAN_VETO.search(f"{title} {text}"):
        return None, "ESOP / incentive plan / options exercise, not a fund raise"
    # Step 1(a) & 1(b): consideration other than cash, share swap, or Scheme of Amalgamation/Arrangement allotment
    pages_map = doc.get("pages") or {}
    p1_head = _flat(pages_map.get(1) or head)[:3500]
    has_cash_raise = bool(
        re.search(r"\bfor\s+cash\b|\breceived\s+(?:Rs\.?|INR|₹)\s*[\d,]+|\b(?:NCDs?|non[-\s]?convertible\s+debentures?|QIP)\b",
                  f"{title} {p1_head} {quote}", re.I)
    )
    # Check title + Subject line + the specific clause around the raise (not unrelated later agenda items)
    sub_m = re.search(r"(?:Sub(?:ject)?|Ref)\s*[:.\-]\s*[^\n]{0,250}", _flat(pages_map.get(1) or head), re.I)
    raise_head = f"{title} {sub_m.group(0) if sub_m else ''}"
    has_non_cash_head = bool(_NOT_CASH_RAISE_RX.search(raise_head) or (not has_cash_raise and _NOT_CASH_RAISE_RX.search(p1_head)))
    has_scheme_head = bool(_SCHEME_ALLOT_RX.search(raise_head) or (not has_cash_raise and _SCHEME_ALLOT_RX.search(p1_head)))
    if has_non_cash_head:
        return None, "consideration other than cash / share swap, not a fund raise"
    if has_scheme_head:
        return None, "scheme of amalgamation/arrangement allotment, not a fund raise"
    full = f"{title} {text}"
    if (_NOT_CASH_RAISE_RX.search(full) or _SCHEME_ALLOT_RX.search(full)) and not has_cash_raise:
        reason = ("consideration other than cash / share swap, not a fund raise"
                  if _NOT_CASH_RAISE_RX.search(full)
                  else "scheme of amalgamation/arrangement allotment, not a fund raise")
        return None, reason
    # Step 1(d): subsidiary's own DRHP/IPO, or an OFS by the company
    if instr == "ipo" and re.search(
        r"\b(?:subsidiary|DRHP|RHP|initial\s+public\s+offer|offer\s+for\s+sale|\bOFS\b)", full, re.I
    ):
        return None, "subsidiary DRHP/IPO or OFS, not listed company's fund raise"
    if re.search(
        r"\b(?:subsidiary\b[^.]{0,120}\b(?:DRHP|RHP|IPO|initial\s+public\s+offer)"
        r"|(?:DRHP|RHP|initial\s+public\s+offer)\b[^.]{0,120}\bsubsidiary"
        r"|\boffer\s+for\s+sale\s*\(?\s*OFS\s*\)?)",
        raise_head, re.I,
    ):
        return None, "subsidiary DRHP/IPO or OFS, not listed company's fund raise"
    return None, None


def _not_an_order_win_reason(doc: Mapping[str, Any], row: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Return ``(reason, referenced_date)`` when a model order_win is background capex or a repeat update."""
    has_val = any(row.get(k) is not None for k in ("amount_inr_cr", "amount_usd_mn", "value_annual")) or bool(
        row.get("value_text")
    )
    if has_val:
        return None, None
    title = _flat(doc.get("title") or "")
    head = _flat(doc.get("head") or doc.get("text") or "")
    text = _flat(doc.get("text") or "")
    if _CAPEX_PRESS_LEAD_RX.search(f"{title} {head[:900]}") \
            and not re.search(r"\b(?:order|orders|contract|contracts|LOA|LOI|letter\s+of\s+(?:award|acceptance|intent))\b", title, re.I) \
            and not re.search(r"name\s+of\s+the\s+entity\s+awarding\s+the\s+order", text, re.I):
        return "capex/plant press release mentioning order as background only", None
    if _ORDER_REPEAT_RX.search(f"{title} {head[:1500]}") and not re.search(
        r"\b(?:received\s+(?:a\s+)?(?:new|fresh|additional)\s+(?:order|contract|LOA)"
        r"|value\s+of\s+(?:the\s+)?(?:order|contract)\s+is\s+(?:Rs\.?|INR|₹|USD|\$)\s*\d)",
        f"{title} {head[:1500]}", re.I,
    ):
        ref_date = _referenced_date(title, "") or _referenced_date(title, text)
        reason = (f"repeat/update of earlier disclosure dated {ref_date} (no new value)"
                  if ref_date else "repeat/update of earlier disclosure (no new value)")
        return reason, ref_date
    return None, None


def _fix_issue_price(pps: float, pages: dict[int, str], title: str) -> tuple[float, bool]:
    """When ``pps`` is the printed premium and face value precedes it, return ``(face + premium, True)``."""
    flat_all = _flat(" ".join([title] + [pages[p] for p in sorted(pages) if int(p) <= PAGES]))
    for m in _PREMIUM_OF_RX.finditer(flat_all):
        try:
            prem = float(m.group("p").replace(",", ""))
        except ValueError:
            continue
        if abs(prem - pps) > 1e-4 * max(1.0, pps):
            continue
        before_short = flat_all[max(0, m.start() - 40): m.start()]
        if re.search(r"\b(?:includ\w*|with\s+(?:a\s+)?)\s*$", before_short, re.I):
            continue
        before = flat_all[max(0, m.start() - 180): m.start()]
        fv_matches = list(_FACE_VALUE_BEFORE_RX.finditer(before))
        if fv_matches:
            try:
                fv = float(fv_matches[-1].group("f").replace(",", ""))
            except ValueError:
                continue
            if 0 < fv <= 1000.0:
                return round(fv + prem, 4), True
    return pps, False


def _printed_share_counts(pages: dict[int, str], title: str) -> list[float]:
    flat_all = _flat(" ".join([title] + [pages[p] for p in sorted(pages) if int(p) <= PAGES]))
    out: list[float] = []
    for m in _SHARES_PRINT_RX.finditer(flat_all):
        try:
            val = float(m.group("v").replace(",", ""))
            if val > 0:
                out.append(val)
        except ValueError:
            pass
    return out


def _fix_printed_shares(shares: float, pages: dict[int, str], title: str) -> float:
    """Fix Indian-comma 10x/100x/1000x LLM slips on ``shares`` using printed security counts."""
    counts = _printed_share_counts(pages, title)
    if not counts:
        return shares
    if any(abs(n - shares) <= 1e-4 * max(1.0, shares) for n in counts):
        return shares
    for n in counts:
        ratio = max(n, shares) / min(n, shares)
        if any(abs(ratio - p) <= 1e-4 * p for p in (10.0, 100.0, 1000.0)):
            return n
    return shares


def _is_number_printed(num: float, pages: dict[int, str], title: str) -> bool:
    flat_all = _flat(" ".join([title] + [pages[p] for p in sorted(pages) if int(p) <= PAGES]))
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", flat_all):
        try:
            v = float(tok.replace(",", ""))
            if abs(v - num) <= 1e-4 * max(1.0, abs(num), abs(v)):
                return True
        except ValueError:
            pass
    return False


def _merge_same_filing_raises(
    fr_rows: list[dict[str, Any]], doc: Mapping[str, Any], script_check: Mapping[str, list[dict[str, Any]]] | None
) -> list[dict[str, Any]]:
    """Combine multiple fund_raise events from the same filing into one event (Step 3b)."""
    if not fr_rows:
        return []
    if len(fr_rows) > 1:
        # Deduplicate distinct leg amounts (within 0.5%) so a combined total repeated on 2 legs isn't double-counted
        amt_legs: list[tuple[float, str, str | None]] = []
        for r in fr_rows:
            a = r.get("amount_inr_cr")
            if a is None:
                continue
            if not any(abs(a - prev_a) <= 0.005 * max(1.0, abs(a), abs(prev_a)) for prev_a, _vt, _in in amt_legs):
                amt_legs.append((float(a), str(r.get("value_text") or ""), r.get("instrument")))
        base = dict(fr_rows[0])
        if len(amt_legs) > 1:
            # Check if one leg already equals the sum of the others
            amt_legs_sorted = sorted(amt_legs, key=lambda x: x[0], reverse=True)
            top_a = amt_legs_sorted[0][0]
            rest_sum = sum(x[0] for x in amt_legs_sorted[1:])
            if abs(top_a - rest_sum) <= 0.01 * max(1.0, top_a):
                base["amount_inr_cr"] = round(top_a, 4)
                base["value_text"] = amt_legs_sorted[0][1] or None
                leg_note = f"printed total {top_a:g} cr covers legs"
            else:
                total_cr = round(sum(x[0] for x in amt_legs), 4)
                if total_cr <= _MAX_EVENT_INR_CR:
                    base["amount_inr_cr"] = total_cr
                vts = [x[1] for x in amt_legs if x[1]]
                base["value_text"] = "; ".join(vts) if vts else None
                if all(r.get("method") == "computed" for r in fr_rows if r.get("amount_inr_cr") is not None):
                    base["method"] = "computed"
                else:
                    base["method"] = "model"
                leg_desc = " + ".join(f"{x[2] or 'leg'} Rs {x[0]:g} cr" for x in amt_legs)
                leg_note = f"sum of printed legs ({leg_desc})"
            base["status"] = "unverified"
        elif len(amt_legs) == 1:
            base["amount_inr_cr"] = round(amt_legs[0][0], 4)
            base["value_text"] = amt_legs[0][1] or None
            leg_note = ""
        else:
            leg_note = ""
        instrs = list(dict.fromkeys(r["instrument"] for r in fr_rows if r.get("instrument")))
        if len(instrs) > 1:
            base["instrument"] = "mixed"
        elif instrs:
            base["instrument"] = instrs[0]
        # Sum distinct share counts across legs (if legs have distinct share counts)
        share_vals: list[float] = []
        for r in fr_rows:
            sh = r.get("shares")
            if sh is not None and not any(abs(sh - s0) < 1.0 for s0 in share_vals):
                share_vals.append(float(sh))
        if share_vals:
            base["shares"] = sum(share_vals)
        # Re-merge notes cleanly
        details: list[str] = []
        for r in fr_rows:
            for part in str(r.get("detail") or "").split(";"):
                p = part.strip()
                if p and not p.startswith("amount mismatch:") and p not in details:
                    details.append(p)
        if leg_note and leg_note not in details:
            details.append(leg_note)
        base["detail"] = "; ".join(details)
        fr_rows = [base]

    # Run script cross-check after combining same-filing legs
    for r in fr_rows:
        if r.get("status") == "quarantined":
            continue
        mismatch = _check_script_mismatch(r, (script_check or {}).get("fund_raise"))
        if mismatch:
            parts = [p.strip() for p in str(r.get("detail") or "").split(";") if p.strip()]
            if mismatch not in parts:
                parts.append(mismatch)
            r["detail"] = "; ".join(parts)
            r["status"] = "unverified"
    return fr_rows


def model_rows(doc: dict[str, Any], kinds: list[str], raw: str, *,
               script_check: Mapping[str, list[dict[str, Any]]] | None = None,
               skips_out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Validate one model reply against the first 4 printed pages; collect skip_log rows for skipped filings."""
    events = parse_model_reply(raw)
    if not events:
        return []
    # Keep legacy fallback test/schema support when events carry only legacy ``kind`` without v1 keys
    if all("kind" in ev and "event_type" not in ev and "amounts" not in ev and "is_event" not in ev for ev in events):
        return _legacy_model_rows(doc, kinds, events)

    title = doc.get("title") or ""
    text = doc.get("text") or ""
    head = doc.get("head") or text
    pages = doc.get("pages") or {1: text}
    rows_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for ev in events:
        etype = _flat(ev.get("event_type")).lower()
        is_event = ev.get("is_event")
        stage = _flat(ev.get("stage")).lower()
        instr = _norm_instrument(ev.get("instrument"))
        if is_event is False or etype == "not_event" or stage in _SKIP_STAGES or instr == "bonus":
            reason = _flat(ev.get("not_event_reason")) or (
                "bonus issue raises no funds" if instr == "bonus"
                else f"stage {stage}" if stage in _SKIP_STAGES
                else "not an event"
            )
            if skips_out is not None:
                skips_out.append({
                    "store": doc.get("store"),
                    "symbol": doc.get("symbol"),
                    "doc_key": doc.get("doc_key"),
                    "candidate_kind": ",".join(kinds),
                    "event_type": etype or "not_event",
                    "stage": stage or None,
                    "instrument": instr,
                    "reason": reason[:300],
                    "title": title[:300],
                    "filing_date": doc.get("filing_date"),
                })
            continue
        if etype not in MODEL_FIRST_KINDS:
            continue

        row = blank_row(doc, etype)
        row["method"] = "model"
        row["why"] = f"model:{EVENT_PROMPT_VERSION}:{stage or etype}"
        notes: list[str] = []
        force_unverified = False
        quarantined_reason = ""

        # Parse & script-verify every printed amount (skip non-monetary capacity counts & per-share price entries)
        raw_amounts = [a for a in (ev.get("amounts") or []) if isinstance(a, Mapping)]
        parsed_with_raw = [(a, _parse_printed_amount(a, pages, title)) for a in raw_amounts]
        valid_amounts = [p for _, p in parsed_with_raw if p["ok"]]
        pps = ev.get("price_per_share")
        rejected_amounts = []
        for raw_a, p in parsed_with_raw:
            if p["ok"]:
                continue
            vt_s = _flat(raw_a.get("value_text"))
            is_capacity = raw_a.get("currency") is None and bool(
                re.search(r"\b(MW|MWp|KW|KWp|GW|GWh|MWh|MVA|KVA|MT|MTPA|KL|KM|pieces|nos|units?|vehicles?|buses?|sets?)\b", vt_s, re.I)
            )
            is_pps = False
            if etype == "fund_raise" and pps not in (None, "") and raw_a.get("number") not in (None, ""):
                try:
                    if _norm_scale(raw_a.get("unit")) == "unit" and abs(float(raw_a["number"]) - float(pps)) < 1e-4:
                        is_pps = True
                except (TypeError, ValueError):
                    pass
            if not (is_capacity or is_pps):
                rejected_amounts.append(p)

        relevant_roles = ("order_size", "annual_value") if etype == "order_win" else (
            "total_issue", "tranche", "equity_leg", "warrant_leg"
        )
        rejected_relevant = [a for a in rejected_amounts if a.get("role") in relevant_roles]

        if etype == "order_win":
            order_sizes = [a for a in valid_amounts if a["role"] == "order_size"
                           and not _not_order_size(a["value_text"], title, text)]
            annuals = [a for a in valid_amounts if a["role"] == "annual_value"]
            if order_sizes:
                chosen = order_sizes[0]
                is_band, band_vt = _has_plus_band(chosen["value_text"], pages, title)
                row["page"] = chosen["page"]
                if is_band:
                    row["value_text"] = band_vt
                    notes.append(f"band floor (not exact): {band_vt}")
                    force_unverified = True
                else:
                    row["value_text"] = chosen["value_text"]
                    if chosen["currency"] == "INR":
                        row["amount_inr_cr"] = chosen["inr_cr"]
                    elif chosen["currency"] == "USD":
                        row["amount_usd_mn"] = chosen["usd_mn"]
                        eq_cr, eq_span = _printed_inr_equivalent(chosen, valid_amounts, pages, title)
                        if eq_cr is not None:
                            row["amount_inr_cr"] = eq_cr
                            notes.append(f"INR equivalent printed ({eq_span})")
                    else:
                        eq_cr, eq_span = _printed_inr_equivalent(chosen, valid_amounts, pages, title)
                        if eq_cr is not None:
                            row["amount_inr_cr"] = eq_cr
                            notes.append(f"printed in {chosen['currency']} with INR equivalent ({eq_span})")
                        else:
                            notes.append(f"printed in non-INR/non-USD currency ({chosen['currency']}); not converted")
            elif annuals:
                ann = annuals[0]
                row["value_text"] = ann["value_text"]
                row["page"] = ann["page"]
                tenure = _verified_tenure_years(ev.get("tenure_years"), ev.get("execution_months"), text)
                if ann["currency"] == "INR" and ann["inr_cr"] is not None:
                    row["value_annual"] = ann["inr_cr"]
                    if tenure:
                        row["value_total"] = round(ann["inr_cr"] * tenure, 4)
                        row["amount_inr_cr"] = row["value_total"]
                        notes.append("annual value x printed tenure (computed)")
                    else:
                        notes.append("annual value; tenure not printed, not a total")
                elif ann["currency"] == "USD" and ann["usd_mn"] is not None:
                    if tenure:
                        row["amount_usd_mn"] = round(ann["usd_mn"] * tenure, 4)
                        notes.append("annual USD value x printed tenure (computed)")
                    else:
                        notes.append("annual USD value; tenure not printed")
                force_unverified = True
            elif any(_not_order_size(a["value_text"], title, text) for a in valid_amounts if a["role"] == "order_size"):
                notes.append("amount sits beside a GDV/project-cost/target label, not the order size")
                force_unverified = True
            elif rejected_relevant:
                quarantined_reason = rejected_relevant[0]["reason"]
        else:
            # fund_raise: total_issue wins over sum of tranche/leg rows; never add board_limit/offered_size/threshold
            raw_totals = [a for a in valid_amounts if a["role"] == "total_issue"]
            raw_parts = [a for a in valid_amounts if a["role"] in ("tranche", "equity_leg", "warrant_leg")]
            totals = [a for a in raw_totals if not _in_about_boilerplate(a["value_text"], pages, title)]
            parts = [a for a in raw_parts if not _in_about_boilerplate(a["value_text"], pages, title)]
            bp_rejected = (len(totals) < len(raw_totals)) or (len(parts) < len(raw_parts))
            if bp_rejected and not totals and not parts:
                notes.append("rejected amount in About boilerplate")
                force_unverified = True
            if totals:
                inr_totals: list[dict[str, Any]] = []
                for a in totals:
                    if a["currency"] == "INR" and a["inr_cr"] is not None:
                        if not any(abs(a["inr_cr"] - prev["inr_cr"]) <= 0.005 * max(1.0, abs(a["inr_cr"]), abs(prev["inr_cr"]))
                                   for prev in inr_totals):
                            inr_totals.append(a)
                usd_totals = [a for a in totals if a["currency"] == "USD" and a["usd_mn"] is not None]
                if len(inr_totals) > 1:
                    by_amt = sorted(inr_totals, key=lambda x: x["inr_cr"], reverse=True)
                    top_a = by_amt[0]["inr_cr"]
                    rest_sum = sum(x["inr_cr"] for x in by_amt[1:])
                    if abs(top_a - rest_sum) <= 0.01 * max(1.0, top_a):
                        chosen = by_amt[0]
                        row["value_text"] = chosen["value_text"]
                        row["page"] = chosen["page"]
                        row["amount_inr_cr"] = chosen["inr_cr"]
                    else:
                        total_cr = round(sum(x["inr_cr"] for x in inr_totals), 4)
                        row["page"] = inr_totals[0]["page"]
                        if total_cr <= _MAX_EVENT_INR_CR:
                            row["amount_inr_cr"] = total_cr
                        row["value_text"] = "; ".join(x["value_text"] for x in inr_totals)
                        notes.append("sum of printed tranche/leg amounts")
                        force_unverified = True
                elif inr_totals:
                    chosen = inr_totals[0]
                    row["value_text"] = chosen["value_text"]
                    row["page"] = chosen["page"]
                    row["amount_inr_cr"] = chosen["inr_cr"]
                else:
                    chosen = usd_totals[0] if usd_totals else totals[0]
                    row["value_text"] = chosen["value_text"]
                    row["page"] = chosen["page"]
                    if chosen["currency"] == "USD":
                        row["amount_usd_mn"] = chosen["usd_mn"]
                    else:
                        notes.append(f"printed in non-INR/non-USD currency ({chosen['currency']}); not converted")
            elif parts:
                inr_parts = []
                seen_part: set[tuple[float, str]] = set()
                for p in parts:
                    if p["currency"] == "INR" and p["inr_cr"] is not None:
                        pk = (round(p["inr_cr"], 4), p["value_text"])
                        if pk not in seen_part:
                            seen_part.add(pk)
                            inr_parts.append(p)
                if inr_parts:
                    row["page"] = inr_parts[0]["page"]
                    if len(inr_parts) == 1:
                        row["amount_inr_cr"] = inr_parts[0]["inr_cr"]
                        row["value_text"] = inr_parts[0]["value_text"]
                    else:
                        total_cr = round(sum(p["inr_cr"] for p in inr_parts), 4)
                        if total_cr <= _MAX_EVENT_INR_CR:
                            row["amount_inr_cr"] = total_cr
                        row["value_text"] = "; ".join(p["value_text"] for p in inr_parts)
                        notes.append("sum of printed tranche/leg amounts")
                        force_unverified = True
                else:
                    usd_parts = [p for p in parts if p["currency"] == "USD" and p["usd_mn"] is not None]
                    if usd_parts:
                        row["page"] = usd_parts[0]["page"]
                        row["amount_usd_mn"] = round(sum(p["usd_mn"] for p in usd_parts), 4)
                        row["value_text"] = "; ".join(dict.fromkeys(p["value_text"] for p in usd_parts))
                        if len(usd_parts) > 1:
                            notes.append("sum of printed USD tranche/leg amounts")
                            force_unverified = True
            elif rejected_relevant:
                quarantined_reason = rejected_relevant[0]["reason"]

        # Awardee / entity_scope check
        parent = bool(_PARENT_SCOPE.search(_flat(f"{title} {text[:1500]}")))
        awardee = _flat(ev.get("awardee"))
        if parent:
            row["entity_scope"] = "parent"
            notes.append("parent-company release")
            force_unverified = True
        elif ev.get("awardee_is_joint"):
            row["entity_scope"] = "joint"
            notes.append("joint: company and subsidiary awarded together")
        elif awardee:
            printed = _awardee_printed(awardee, pages, title)
            is_listed = _is_listed_company_name(awardee, doc) or awardee.lower() in ("the company", "company")
            if not printed and not (not ev.get("awardee_is_subsidiary") and is_listed):
                notes.append("awardee not printed on page")
                force_unverified = True
                row["entity_scope"] = "company"
            elif ev.get("awardee_is_subsidiary") and printed and not _is_listed_company_name(awardee, doc) \
                    and not re.search(r"Company\)?\s+of\s+Coal\s+India", awardee, re.I):
                row["entity_scope"] = "subsidiary"
                row["_subsidiary"] = awardee[:120]
                notes.append(f"subsidiary: {awardee[:120]}")
            else:
                row["entity_scope"] = "company"
                row["_subsidiary"] = None
        else:
            row["entity_scope"] = "company"
            row["_subsidiary"] = None

        # Kind-specific fields
        if etype == "order_win":
            row["order_kind"] = _order_kind(title, text[:800])
            cust = ev.get("customer")
            if isinstance(cust, str) and _flat(cust):
                row["customer"] = _clean_party(cust, from_annexure=True) or _flat(cust)[:300]
            _split_customer(row)
            exec_m = ev.get("execution_months")
            if exec_m not in (None, ""):
                try:
                    row["execution_months"] = float(exec_m)
                except (TypeError, ValueError):
                    row["execution_months"] = None
            if row["execution_months"] is None and isinstance(ev.get("execution_period"), str):
                row["execution_months"] = order_wins.months(ev["execution_period"])
        else:
            row["instrument"] = instr
            row["raise_stage"] = stage or "approved_board"
            for num_k in ("shares", "price_per_share"):
                val = ev.get(num_k)
                if val not in (None, ""):
                    try:
                        row[num_k] = float(str(val).replace(",", ""))
                    except (TypeError, ValueError):
                        row[num_k] = None
            if row.get("shares") is not None:
                row["shares"] = _fix_printed_shares(row["shares"], pages, title)
            changed_pps = False
            if row.get("price_per_share") is not None:
                row["price_per_share"], changed_pps = _fix_issue_price(row["price_per_share"], pages, title)
                if changed_pps:
                    notes.append("issue price = face + premium")
            if row.get("amount_inr_cr") is None and row.get("amount_usd_mn") is None \
                    and not quarantined_reason and not bp_rejected:
                sh, pps_val = row.get("shares"), row.get("price_per_share")
                if sh and pps_val and 0.01 <= pps_val <= 100_000.0:
                    sh_ok = _is_number_printed(sh, pages, title) or any(
                        abs(n - sh) <= 1e-4 * max(1.0, sh) for n in _printed_share_counts(pages, title)
                    )
                    pps_ok = changed_pps or _is_number_printed(pps_val, pages, title)
                    if sh_ok and pps_ok:
                        comp_amt = round(sh * pps_val / 1e7, 4)
                        if 0 < comp_amt <= _MAX_EVENT_INR_CR:
                            row["amount_inr_cr"] = comp_amt
                            row["method"] = "computed"
                            row["value_text"] = None
                            force_unverified = True
                            notes.append(f"computed: {int(sh):,} x Rs {pps_val:g} / 1e7")
            if row.get("amount_inr_cr") is None and row.get("amount_usd_mn") is None and not quarantined_reason:
                notes.append("no printed issue amount")
                force_unverified = True

        # Quote around matched value_text or opening text
        if row.get("value_text"):
            flat_all = _flat(text)
            idx = flat_all.find(_flat(row["value_text"]))
            if idx >= 0:
                start = max(0, idx - MAX_QUOTE // 3)
                row["quote"] = flat_all[start:min(len(flat_all), start + MAX_QUOTE)].strip()
        if not row.get("quote"):
            row["quote"] = _flat(text)[:MAX_QUOTE]

        if etype == "fund_raise":
            row["_text_full"] = _flat(f"{title} {text}")
            fr_stage, fr_skip = _not_a_fund_raise_reason(doc, ev, instr, row["quote"])
            if fr_skip:
                if skips_out is not None:
                    skips_out.append({
                        "store": doc.get("store"),
                        "symbol": doc.get("symbol"),
                        "doc_key": doc.get("doc_key"),
                        "candidate_kind": ",".join(kinds),
                        "event_type": etype,
                        "stage": fr_stage or stage or None,
                        "instrument": instr,
                        "reason": fr_skip[:300],
                        "title": title[:300],
                        "filing_date": doc.get("filing_date"),
                    })
                continue
        else:
            ow_skip, ref_date = _not_an_order_win_reason(doc, row)
            if ow_skip:
                if skips_out is not None:
                    skips_out.append({
                        "store": doc.get("store"),
                        "symbol": doc.get("symbol"),
                        "doc_key": doc.get("doc_key"),
                        "candidate_kind": ",".join(kinds),
                        "event_type": etype,
                        "stage": stage or None,
                        "instrument": instr,
                        "reason": ow_skip[:300],
                        "title": title[:300],
                        "filing_date": doc.get("filing_date"),
                        "_ref_date": ref_date,
                    })
                continue

        # Cross-check against script parse (fund_raise runs after merging same-filing legs)
        if etype == "order_win":
            mismatch = _check_script_mismatch(row, (script_check or {}).get(etype))
            if mismatch:
                notes.append(mismatch)
                force_unverified = True

        if quarantined_reason:
            row["status"] = "quarantined"
            row["amount_inr_cr"] = None
            row["amount_usd_mn"] = None
            row["value_text"] = None
            notes.insert(0, quarantined_reason)
        elif force_unverified:
            row["status"] = "unverified"
        else:
            _gate_status(row)

        if notes:
            # Preserve kind_not_gated alongside other notes without duplicates
            existing_detail = [p.strip() for p in str(row.get("detail") or "").split(";") if p.strip()]
            for n in notes:
                if n not in existing_detail:
                    existing_detail.append(n)
            row["detail"] = "; ".join(existing_detail)
        if row.pop("_undisclosed_customer", False):
            row["detail"] = f"{row['detail']}; customer not disclosed" if row.get("detail") else "customer not disclosed"

        rows_by_kind[etype].append(row)

    if rows_by_kind.get("fund_raise"):
        rows_by_kind["fund_raise"] = _merge_same_filing_raises(rows_by_kind["fund_raise"], doc, script_check)

    out: list[dict[str, Any]] = []
    for k, kind_rows in rows_by_kind.items():
        for seq, row in enumerate(kind_rows, 1):
            row["seq"] = seq
            out.append(row)
    return out


def ask(client: Client, doc: dict[str, Any], kinds: list[str]) -> str:
    """One hy4 read of the first 4 pages: the raw reply ("" when every try failed)."""
    prompt = model_prompt(doc, kinds)
    for attempt in range(MAX_RETRIES):
        code, body, _usage = client.chat(prompt)
        if code == 200:
            return body
        wait = retry_after_of(client) if code == 429 else 0.0
        if wait > 0:
            time.sleep(min(wait, MAX_RETRY_WAIT_S))
        else:
            time.sleep(2.0 * (attempt + 1))
    return ""


def _load_cache(cache_path: Path | None) -> dict[str, str]:
    cache: dict[str, str] = {}
    if not cache_path or not cache_path.exists():
        return cache
    if cache_path.suffix == ".jsonl":
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                if isinstance(rec, dict) and "key" in rec and "raw" in rec:
                    cache[str(rec["key"])] = str(rec["raw"])
            except ValueError:
                continue
        return cache
    try:
        loaded = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return {str(k): str(v) for k, v in loaded.items()}
    except (OSError, ValueError):
        pass
    return {}


def run_model(pending: list[dict[str, Any]], workers: int,
              cache_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One hy4-flash-free read per pending filing; replies are cached by ``(doc_key, prompt_fp)``.

    Honours 429 Retry-After across workers and halts new requests if errors exceed ``ERROR_STOP_SHARE``.
    """
    fp = prompt_fingerprint()
    if not pending:
        return [], {"requests": 0, "rows": 0, "cached": 0, "errors": 0, "skips": [], "prompt_fp": fp, "stopped": None}
    cache = _load_cache(cache_path)
    client = Client(MODEL, MODEL_BODY, "t242-filing-events")
    out: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    lock = threading.Lock()
    requests = 0
    cached = 0
    errors = 0
    cooldown_until = 0.0
    stop_event = threading.Event()
    dirty = 0

    def flush_json() -> None:
        if cache_path and cache_path.suffix != ".jsonl":
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache), encoding="utf-8")

    def append_jsonl(key: str, raw: str) -> None:
        if cache_path and cache_path.suffix == ".jsonl":
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            with cache_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "raw": raw}, ensure_ascii=False) + "\n")

    def key_of(doc: dict[str, Any]) -> str:
        kinds = sorted(doc.get("_missing") or [])
        if any(k in MODEL_FIRST_KINDS for k in kinds):
            return f"{doc['doc_key']}|{fp}"
        return f"{doc['doc_key']}|{','.join(kinds)}|{fp}"

    def one(doc: dict[str, Any]) -> None:
        nonlocal requests, cached, errors, cooldown_until, dirty
        if stop_event.is_set():
            return
        key = key_of(doc)
        kinds = list(doc.get("_missing") or ["order_win", "fund_raise"])
        with lock:
            raw = cache.get(key)
        if raw is None:
            # Respect any shared 429 cooldown before firing
            with lock:
                delay = cooldown_until - time.monotonic()
            if delay > 0:
                time.sleep(min(delay, MAX_RETRY_WAIT_S))
            if stop_event.is_set():
                return
            prompt = model_prompt(doc, kinds)
            raw = ""
            for attempt in range(MAX_RETRIES):
                code, body, _usage = client.chat(prompt)
                if code == 200 and body:
                    raw = body
                    break
                wait = retry_after_of(client) if code == 429 else 0.0
                if code == 429 and wait > 0:
                    bounded = min(wait, MAX_RETRY_WAIT_S)
                    with lock:
                        cooldown_until = max(cooldown_until, time.monotonic() + bounded)
                    time.sleep(bounded)
                else:
                    time.sleep(2.0 * (attempt + 1))
            with lock:
                requests += 1
                if raw:
                    cache[key] = raw
                    dirty += 1
                    if cache_path and cache_path.suffix == ".jsonl":
                        append_jsonl(key, raw)
                    elif dirty >= 10:
                        flush_json()
                        dirty = 0
                else:
                    errors += 1
                if requests >= 20 and errors / requests > ERROR_STOP_SHARE:
                    stop_event.set()
        else:
            with lock:
                cached += 1
        if raw:
            doc_skips: list[dict[str, Any]] = []
            rows = model_rows(doc, kinds, raw, script_check=doc.get("_script_check"), skips_out=doc_skips)
            with lock:
                out.extend(rows)
                skips.extend(doc_skips)

    try:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, pending))
    finally:
        if dirty:
            flush_json()

    stopped_msg = (f"hy4 error rate {errors}/{requests} ({errors/requests:.1%}) > {ERROR_STOP_SHARE:.0%}"
                   if requests >= 20 and errors / requests > ERROR_STOP_SHARE else None)
    return out, {"requests": requests, "cached": cached, "errors": errors,
                 "rows": len(out), "skips": skips, "prompt_fp": fp, "stopped": stopped_msg}


# ------------------------------------------------------------------ build + report
def _insert(con: sqlite3.Connection, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
            meta: dict[str, Any] | None = None, skips: list[dict[str, Any]] | None = None) -> None:
    con.executemany(
        f"INSERT INTO event ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(row.get(column) for column in COLUMNS) for row in rows])
    con.executemany(
        "INSERT INTO amend (doc_key, symbol, amends, filing_date, known_at, why) VALUES (?,?,?,?,?,?)",
        [(a["doc_key"], a.get("symbol"), a["amends"], a.get("filing_date"), a.get("known_at"), a.get("why"))
         for a in amends])
    if skips:
        con.executemany(
            "INSERT INTO skip_log (store, symbol, doc_key, candidate_kind, event_type, stage, instrument, "
            "reason, title, filing_date) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(s.get("store"), s.get("symbol"), s["doc_key"], s.get("candidate_kind"), s.get("event_type"),
              s.get("stage"), s.get("instrument"), s.get("reason"), s.get("title"), s.get("filing_date"))
             for s in skips])
    if meta is not None:
        con.executemany("INSERT INTO run_meta (key, value) VALUES (?, ?)",
                        [(key, json.dumps(value)) for key, value in meta.items()])


def write_db(path: Path, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
             meta: dict[str, Any], skips: list[dict[str, Any]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        _insert(con, rows, amends, meta, skips=skips)
        con.commit()
    finally:
        con.close()


def _ensure_event_columns(con: sqlite3.Connection) -> None:
    """A baseline built before a new event column exists: add it before inserting (additive, no rewrite)."""
    have = {row[1] for row in con.execute("PRAGMA table_info(event)")}
    for column in COLUMNS:
        if column not in have:
            con.execute(f"ALTER TABLE event ADD COLUMN {column} TEXT")
    con.execute(
        "CREATE TABLE IF NOT EXISTS skip_log ("
        "skip_id INTEGER PRIMARY KEY, store TEXT, symbol TEXT, doc_key TEXT NOT NULL, "
        "candidate_kind TEXT, event_type TEXT, stage TEXT, instrument TEXT, reason TEXT, title TEXT, filing_date TEXT)"
    )


def merge_db(path: Path, baseline: Path, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
             meta: dict[str, Any], doc_keys: Iterable[str],
             skips: list[dict[str, Any]] | None = None) -> None:
    """T-233: copy ``baseline`` to ``path`` and replace only the filings this scoped run re-read."""
    from reality_engine.research.selector import copy_db

    copy_db(baseline, path)
    con = sqlite3.connect(path)
    try:
        _ensure_event_columns(con)
        keys = list(dict.fromkeys(str(key) for key in doc_keys))
        if keys:
            marks = ",".join("?" * len(keys))
            con.execute(f"DELETE FROM event WHERE doc_key IN ({marks})", keys)
            con.execute(f"DELETE FROM amend WHERE doc_key IN ({marks})", keys)
            con.execute(f"DELETE FROM skip_log WHERE doc_key IN ({marks})", keys)
        _insert(con, rows, amends, skips=skips)
        con.execute("DELETE FROM run_meta WHERE key='scoped_merge'")
        con.execute("INSERT INTO run_meta (key, value) VALUES ('scoped_merge', ?)",
                    (json.dumps({"baseline": str(baseline), "documents": len(keys),
                                 "rows": len(rows), "seconds": meta.get("seconds")}),))
        con.commit()
    finally:
        con.close()


def _script_cross_check(doc: dict[str, Any], want_ow: bool, want_fr: bool) -> dict[str, list[dict[str, Any]]]:
    """Run existing script parse in memory for ``order_win`` / ``fund_raise`` amount cross-check only."""
    title, text = doc.get("title") or "", doc.get("text") or ""
    head = doc.get("head") or text
    out: dict[str, list[dict[str, Any]]] = {}
    if want_ow:
        ow_list = order_rows(title, text, doc.get("symbol") or "", head=head)
        if ow_list:
            out["order_win"] = ow_list
    if want_fr:
        fr = raise_fields(title, head, text)
        if fr:
            out["fund_raise"] = [fr]
    return out


def build(stores: list[str] | None = None, limit: int | None = None, use_model: bool = True,
          workers: int = 4, out: Path = DEFAULT_OUT, cache: Path | None = DEFAULT_CACHE,
          only: Any = None, baseline: Path | str | None = None) -> dict[str, Any]:
    """Scan every store's announcements and write the event DB. Returns the run counts.

    Model-first for ``order_win`` and ``fund_raise`` when ``use_model=True`` (no 30% MODEL_STOP_SHARE stop for
    those two kinds); ``capex_approval``, ``capacity_commissioned`` and ``order_amendment`` stay script-first.
    """
    from reality_engine.research.driver_claims import list_stores

    chosen = stores or list_stores()
    if only is not None:
        chosen = [store for store in chosen if only.store(store)]
    rows: list[dict[str, Any]] = []
    amends: list[dict[str, Any]] = []
    skips: list[dict[str, Any]] = []
    pending_first: list[dict[str, Any]] = []
    pending_fallback: list[dict[str, Any]] = []
    by_class: Counter[str] = Counter()
    filings = 0
    other_classified = 0
    docs_seen = 0
    doc_keys: list[str] = []
    docs_by_store: dict[str, list[dict[str, Any]]] = {}
    for store in chosen:
        try:
            docs = load_docs(store)
        except (OSError, sqlite3.Error) as exc:
            print(f"skip {store}: {exc}")
            continue
        if only is not None:
            docs = [doc for doc in docs if only.doc(store, doc["doc_key"])]
        subset: list[dict[str, Any]] = []
        for doc in docs:
            if limit is not None and docs_seen >= limit:
                break
            docs_seen += 1
            doc_keys.append(str(doc["doc_key"]))
            subset.append(doc)
        docs_by_store[store] = subset
        parsed: list[tuple[dict[str, Any], list[dict[str, Any]], list[str], list[str]]] = []
        classified_keys: set[str] = set()
        for doc in subset:
            title, text = doc.get("title") or "", doc.get("text") or ""
            head = doc.get("head") or text
            filing_date = doc.get("filing_date")
            classes = classify(title, head, filing_date=filing_date, text=text)
            if use_model:
                want_ow = ("order_win" in classes) or _order_win_candidate(title, head)
                want_fr = ("fund_raise" in classes) or _fund_raise_candidate(title, head, text)
                cand_kinds = [k for k, flag in (("order_win", want_ow), ("fund_raise", want_fr)) if flag]
                other_classes = [k for k in classes if k not in MODEL_FIRST_KINDS]
                found: list[dict[str, Any]] = []
                missing: list[str] = []
                amendment_fields = order_amendment_fields(title, head, text) or {} if "order_amendment" in other_classes else {}
                for kind in other_classes:
                    if kind == "order_amendment":
                        fields = amendment_fields
                    elif kind == "capex_approval":
                        fields = capex_fields(title, head, text) or {}
                    else:
                        fields = capacity_fields(title, head, text, filing_date=filing_date) or {}
                    row, absent = _assemble_row(doc, kind, fields, 1)
                    found.append(row)
                    if absent:
                        missing.append(kind)
                if found or cand_kinds:
                    classified_keys.add(doc["doc_key"])
                parsed.append((doc, found, missing, cand_kinds))
            else:
                found, missing = event_rows(doc)
                if found:
                    classified_keys.add(doc["doc_key"])
                parsed.append((doc, found, missing, []))
        amend, skipped = amend_rows(subset, classified_keys)
        amends.extend(amend)
        for doc, found, missing, cand_kinds in parsed:
            if doc["doc_key"] in skipped:
                continue
            if found:
                filings += 1
                other_classified += 1
            by_class.update({kind: 1 for kind in {row["kind"] for row in found}})
            rows.extend(found)
            if cand_kinds:
                by_class.update({k: 1 for k in cand_kinds})
                doc["_missing"] = cand_kinds
                doc["_script_check"] = _script_cross_check(
                    doc, "order_win" in cand_kinds, "fund_raise" in cand_kinds,
                )
                pending_first.append(doc)
            if missing:
                doc_fb = dict(doc)
                doc_fb["_missing"] = missing
                pending_fallback.append(doc_fb)
        if limit is not None and docs_seen >= limit:
            break

    fb_denom = other_classified or len({row["doc_key"] for row in rows})
    need_share = len(pending_fallback) / fb_denom if fb_denom else 0.0
    fp = prompt_fingerprint()
    meta: dict[str, Any] = {
        "stores": len(chosen), "docs": docs_seen,
        "classified_filings": len({row["doc_key"] for row in rows}) + len(pending_first),
        "by_class": dict(by_class), "script_rows": len(rows),
        "model_first_candidates": len(pending_first),
        "need_model": len(pending_fallback),
        "need_model_share": round(need_share, 4),
        "model_rows": 0, "model_requests": 0, "model_cached": 0, "model_errors": 0,
        "skipped": 0, "skip_reasons": {},
        "prompt_version": EVENT_PROMPT_VERSION, "prompt_fp": fp,
        "workers": workers, "stopped": None,
    }
    if use_model and pending_first:
        modelled_first, stats_first = run_model(pending_first, workers, cache)
        rows.extend(modelled_first)
        skips.extend(stats_first["skips"])
        meta["model_rows"] += stats_first["rows"]
        meta["model_requests"] += stats_first["requests"]
        meta["model_cached"] += stats_first["cached"]
        meta["model_errors"] += stats_first["errors"]
        if stats_first.get("stopped"):
            meta["stopped"] = stats_first["stopped"]
    if pending_fallback and use_model and need_share > MODEL_STOP_SHARE:
        fb_stop = f"more than {MODEL_STOP_SHARE:.0%} of fallback filings need the model ({len(pending_fallback)}/{fb_denom})"
        meta["stopped"] = f"{meta['stopped']}; {fb_stop}" if meta["stopped"] else fb_stop
    elif pending_fallback and use_model and not meta["stopped"]:
        modelled, stats = run_model(pending_fallback, workers, cache)
        def _has_val(r: dict[str, Any]) -> bool:
            return any(r.get(k) is not None
                       for k in ("amount_inr_cr", "amount_usd_mn", "value_annual", "capacity_value"))

        covered = {(row["doc_key"], row["kind"]) for row in modelled
                   if row["status"] != "quarantined" and _has_val(row)
                   and "amount unit not printed" not in str(row.get("detail") or "")
                   and "model filled no amount" not in str(row.get("detail") or "")}
        rows = [row for row in rows if not ((row["doc_key"], row["kind"]) in covered and row["method"] == "script"
                                            and str(row.get("detail") or "").startswith("amount not filled by script"))]
        rows.extend(modelled)
        meta["model_rows"] += stats["rows"]
        meta["model_requests"] += stats["requests"]
        meta["model_cached"] += stats["cached"]
        meta["model_errors"] += stats["errors"]
    elif pending_fallback and not use_model:
        meta["stopped"] = "model pass disabled (--no-model)"

    meta["skipped"] = len(skips)
    meta["skip_reasons"] = dict(Counter(s["reason"] for s in skips))

    rows = _fold_same_order(rows, amends)
    rows = _fold_same_raise(rows, amends)
    # Link skipped repeat/update order_win filings (Step 5b) to the earlier filing on _ref_date
    kept_order_dks = {str(r["doc_key"]) for r in rows if r["kind"] == "order_win"}
    for sk in skips:
        ref_d = sk.pop("_ref_date", None)
        if not ref_d:
            continue
        pool = [
            d for d in docs_by_store.get(str(sk.get("store") or ""), [])
            if d.get("symbol") == sk.get("symbol")
            and d.get("filing_date") == ref_d
            and d["doc_key"] != sk["doc_key"]
        ]
        if not pool:
            continue
        sk_words = _content_words(f"{sk.get('title') or ''}")
        pool.sort(key=lambda d: (
            0 if d["doc_key"] in kept_order_dks else 1,
            -len(sk_words & _content_words(f"{d.get('title') or ''} {(d.get('text') or '')[:600]}")),
            str(d.get("known_at") or ""),
        ))
        target = pool[0]
        amends.append({
            "doc_key": sk["doc_key"], "symbol": sk.get("symbol"), "amends": target["doc_key"],
            "filing_date": sk.get("filing_date"), "known_at": None,
            "why": sk.get("reason") or f"repeat/update of earlier disclosure dated {ref_d}",
        })
        sk["reason"] = f"{sk['reason']}; amends={target['doc_key']}"[:300]
    amends = list({item["doc_key"]: item for item in amends}.values())
    _link_amendments(rows)
    _assign_raise_ids(rows)
    rows = _drop_restated_capacity(rows)

    # one event per (filing, class, seq), the best-filled row stands
    rank = {"verified": 3, "unverified": 2, "quarantined": 1}
    best: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in rows:
        key = (str(row["doc_key"]), str(row["kind"]), int(row.get("seq") or 1))
        current = best.get(key)
        if current is None or rank.get(row["status"], 0) > rank.get(current["status"], 0):
            best[key] = row
    rows = list(best.values())
    # the exchange feed files the same document twice (BSE + NSE): one dated quantified event, not two
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or ""))):
        value = (row.get("amount_inr_cr"), row.get("amount_usd_mn"), row.get("capacity_value"))
        if any(part is not None for part in value):
            key = (row.get("symbol"), row.get("filing_date"), row.get("kind"), int(row.get("seq") or 1),
                   *(round(float(part), 4) if part is not None else None for part in value))
            if key in seen:
                continue
            seen.add(key)
        unique.append(row)
    rows = unique
    quarantined = sum(1 for row in rows if row["status"] == "quarantined")
    meta["quarantined"] = quarantined
    meta["quarantined_share"] = round(quarantined / len(rows), 4) if rows else 0.0
    if rows and quarantined / len(rows) > QUARANTINE_STOP_SHARE and not meta["stopped"]:
        meta["stopped"] = (f"more than {QUARANTINE_STOP_SHARE:.0%} of events quarantined "
                           f"({quarantined}/{len(rows)})")
    if baseline is not None:
        merge_db(out, Path(baseline), rows, amends, meta, doc_keys, skips=skips)
    else:
        write_db(out, rows, amends, meta, skips=skips)
    return meta


def _report_lines(db: Path, seed: int = 7) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        meta = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM run_meta")}
        total = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        lines = [f"# T-231 filing events -- {db}", "", f"events: {total}"]
        if meta.get("prompt_fp"):
            lines.append(f"prompt: {meta.get('prompt_version')} (fp={meta.get('prompt_fp')})")
        if meta.get("stopped"):
            lines.append(f"STOPPED: {meta['stopped']}")
        lines.append(f"announcements read: {meta.get('docs')} in {meta.get('stores')} stores; "
                     f"classified filings: {meta.get('classified_filings')}")
        lines.append("filings per class: " + ", ".join(
            f"{kind} {meta.get('by_class', {}).get(kind, 0)}" for kind in KINDS))
        lines.append("events by status and method:")
        for r in con.execute("SELECT kind, status, method, COUNT(*) n FROM event "
                             "GROUP BY kind, status, method ORDER BY kind, status, method"):
            lines.append(f"  {r['kind']} {r['status']} {r['method']}: {r['n']}")
        has_skip = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skip_log'").fetchone()
        if has_skip:
            skip_total = con.execute("SELECT COUNT(*) FROM skip_log").fetchone()[0]
            lines.append(f"skipped (skip_log): {skip_total}")
            for r in con.execute("SELECT reason, COUNT(*) n FROM skip_log GROUP BY reason ORDER BY n DESC LIMIT 20"):
                lines.append(f"  skip [{r['n']}]: {r['reason']}")
        lines.append("companies / month-ends with >=1 verified event:")
        for kind in ("order_win", "capex_approval", "fund_raise"):
            row = con.execute(
                "SELECT COUNT(DISTINCT symbol) s, COUNT(DISTINCT substr(filing_date,1,7)) m "
                "FROM event WHERE kind=? AND status='verified'", (kind,)).fetchone()
            months = [r[0] for r in con.execute(
                "SELECT substr(filing_date,1,7) m FROM event WHERE kind=? AND status='verified' "
                "GROUP BY m ORDER BY m", (kind,))]
            lines.append(f"  {kind}: companies {row['s']}, month-ends {row['m']} "
                         f"({', '.join(months[:24])}{' ...' if len(months) > 24 else ''})")
        ids = [r[0] for r in con.execute("SELECT event_id FROM event WHERE status='verified' ORDER BY event_id")]
        sample = random.Random(seed).sample(ids, min(30, len(ids))) if ids else []
        lines += ["", f"## 30 random verified events (seed {seed})", ""]
        for event_id in sample:
            r = con.execute("SELECT * FROM event WHERE event_id=?", (event_id,)).fetchone()
            amount = (f"{r['amount_inr_cr']:g} cr" if r["amount_inr_cr"] is not None else
                      f"USD {r['amount_usd_mn']:g} mn" if r["amount_usd_mn"] is not None else
                      f"{r['capacity_value']:g} {r['capacity_unit'] or ''}".strip())
            lines.append(f"### {event_id} {r['symbol']} {r['kind']} {r['filing_date']} -- {amount}")
            lines.append(f"doc: {r['doc_key']} p{r['page']}")
            lines.append(f"value_text: {r['value_text']}")
            lines.append(f"quote: {r['quote']}")
            lines.append("")
        return lines
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--stores", nargs="*", default=None, help="store names (default: every measured store)")
    ap.add_argument("--limit", type=int, default=None, help="stop after N announcements across the run")
    ap.add_argument("--workers", type=int, default=4, help="parallel model calls")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--no-model", action="store_true", help="script parse only; no hy4 call")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE), help="model reply cache (never re-spends a reply)")
    ap.add_argument("--report", default=None, help="write the report for an existing --out DB and exit")
    ap.add_argument("--report-file", default=str(DEFAULT_REPORT))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--only", default="",
                    help="T-233 selector JSON: re-read only these stores/doc_keys (with --baseline, patch a copy)")
    ap.add_argument("--baseline", default="", help="with --only: copy this DB to --out and replace those filings")
    args = ap.parse_args(argv)
    if args.report:
        lines = _report_lines(Path(args.report), args.seed)
    else:
        # T-242 (26 Nov): the store root comes from T228_STORE_ROOT and silently defaulted to measure10, where the
        # same cNN names hold other companies; a fresh9 rerun read the wrong set.  Name the root first, refuse a
        # --stores name missing under it.
        from reality_engine.research.driver_claims import STORE_ROOT
        src = "T228_STORE_ROOT" if os.environ.get("T228_STORE_ROOT") else "default; set T228_STORE_ROOT"
        print(f"store root: {STORE_ROOT} ({src})", flush=True)
        if args.stores and not os.environ.get("T228_STORE_ROOT"):
            print("error: --stores needs T228_STORE_ROOT set (the default root reuses cNN names)", file=sys.stderr)
            return 2
        missing = [s for s in (args.stores or []) if not store_path(s).is_file()]
        if missing:
            print(f"error: {len(missing)} store(s) not under {STORE_ROOT}: {' '.join(missing[:10])}", file=sys.stderr)
            return 2
        only = None
        if args.only:
            from reality_engine.research.selector import Selector
            only = Selector.load(args.only)
        meta = build(args.stores, args.limit, not args.no_model, args.workers, Path(args.out),
                     Path(args.cache), only=only, baseline=args.baseline or None)
        print(json.dumps({k: v for k, v in meta.items() if k != "by_class"}, indent=2))
        lines = _report_lines(Path(args.out), args.seed)
    report = Path(args.report_file)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:30]))
    print(f"\nreport: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
