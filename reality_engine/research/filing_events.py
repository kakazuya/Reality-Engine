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
import json
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
from typing import Any, Iterable

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
MAX_MODEL_CHARS = 6000       # first two pages sent to the model
MAX_QUOTE = 400              # characters of printed context kept on a row
MODEL_STOP_SHARE = 0.30      # brief: more than 30% of classified filings needing the model stops the run
QUARANTINE_STOP_SHARE = 0.10
MAX_RETRIES = 3
MAX_RETRY_WAIT_S = 900.0

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
    r"\b(?:allotted|allotment|allotting|raised|subscribed|sanctioned|issued|issuing|issuance|opened|closed)\b", re.I)
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
# T-242: a kind enters VERIFIED_KINDS only after its own fresh strict 60-row grade.  ``order_win`` passed it
# (25 R / 5 P / 0 W / 0 J on the 24 Nov 2026 fresh3 grade); every other kind is stored ``unverified`` until its
# own 60-row pass, so a non-order row is never presented as verified evidence.
VERIFIED_KINDS = frozenset({"order_win"})
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
    r"|\b(?:awarded|received|secured|won|bagged)\s+(?:orders?|contracts?)\s+(?:worth|aggregating|valued\s+at"
    r"|amounting\s+to)\b[^.]{0,60}?\b(?:in|during|for)\s+(?:FY\s?\d{2,4}|(?:the\s+|this\s+)?"
    r"(?:year|quarter|half[\s-]?year|nine\s+months))\b"
    r"|\bconsolidated\s+order\s+wins?\s+for\s+(?:Q[1-4]|H[12]|FY)\b"
    r"|\beach\s+of\s+the\s+above\s+orders?\s+has\s+already\s+been\s+individually\s+intimated\b",
    re.I)
# "order inflow for the year" is a genuine order-win release's background sentence (KEC/TRANSRAILL): it is a
# period aggregate only when the announcement itself is about it, so this one is read on the title alone.
_ORDER_INFLOW_TITLE = re.compile(
    r"\border\s+(?:inflow|intake)\b[^.]{0,40}\bfor\s+(?:FY\s?\d{2,4}|(?:the\s+)?(?:year|quarter|half[\s-]?year"
    r"|nine\s+months))\b", re.I)
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
_LOWEST_BIDDER = re.compile(r"\bL\s*[-\u2013]\s*1\b|\blowest\s+(?:bidder|tenderer)\b|\bL1\s+(?:status|bidder)\b",
                            re.I)
# an approved/proposed capacity is a plan until the sentence says it is commissioned.
_CAPACITY_APPROVED = re.compile(r"\b(?:approved|approves|proposed|setting\s+up|to\s+be\s+set\s+up|will\s+set\s+up)\b",
                                re.I)
_ORDER_WORD = re.compile(
    r"\b(?:order|orders|purchase\s+order|work\s+order|contract|contracts|LOA|LOI|letter\s+of\s+award"
    r"|letter\s+of\s+acceptance|letter\s+of\s+variation)\b", re.I)
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
_CONSORTIUM_AMOUNT = re.compile(
    r"(?:company'?s?|our)\s+share[^.]{0,180}?(?:Rs\.?|INR|₹)\s*(?P<v>[\d,]+(?:\.\d+)?)\s*"
    r"(?P<u>crores?|cr\.?|lakhs?|lacs?|million|mn|billions?|bn)", re.I)
_CONSORTIUM_PCT = re.compile(
    r"(?:company'?s?|our)\s+share[^.]{0,80}?(?P<p>\d+(?:\.\d+)?)\s*%"
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
_ORDER_BOOK = re.compile(r"\border\s+book\b|\border\s+intake\b|\border\s+inflow\b|\bbacklog\b", re.I)
_DATE_DMY = re.compile(r"\bdated?\s+(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", re.I)
_DATE_MD = re.compile(
    r"\bdated?\s+(\d{1,2})(?:st|nd|rd|th)?\s+(January|February|March|April|May|June|July|August|September|"
    r"October|November|December),?\s+(\d{4})\b", re.I)
_DATE_MDY = re.compile(
    r"\bdated?\s+(January|February|March|April|May|June|July|August|September|October|November|December)"
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


def classify(title: str, head: str, filing_date: str | None = None) -> list[str]:
    """The classes one announcement names, at most once each, from its title and first two pages."""
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
            and not _ORDER_VETO.search(body) and not _is_buyer_side(title, head):
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
    if raise_fields(title, head, head):
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
    r"contract\(?s?\)?|contact\(?s?\)?|international\s+client|^i\s+|^name\b|^n/?a$|^none$|^details?"
    r"|date\s+of\s+issue|letter\s+of\s+(?:acceptance|award)|work\s+order|order\(?s?\)"
    r"|the\s+company|interest\s+in\s+the\s+entity|promoter|related\s+party|thereof"
    r"|\b(?:rs\.?|inr|worth|crores?|lakhs?|lacs?)\b|₹"
    r"|our\s+valued\s+customer|valued\s+customer|\ba\s+leading\b|\ba\s+renowned\b|\ba\s+renowed\b"
    r"|\ba\s+reputed\b|\ba\s+prominent\b|\ba\s+listed\s+company\b|\bone\s+of\s+the\b"
    r"|\bcustomer\b|\bclient\s+firm\b|\btraders\s+to\b"
    r"|\bbased\s+(?:renow[ne]d|reputed|prominent|at\s+(?:ahmedabad|gujarat|maharashtra|india))\b", re.I)
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
    r"(?=\s*(?:\b[b-k]\s*[.)]?\s*(?:significant|nature|whether|time|broad|details|date)"
    r"|\b[2-9]\s*[.)]?\s*(?:significant|nature|whether|time|broad|details|date)"
    r"|\bsignificant\s+terms|\bnature\s+of\s+(?:the\s+)?(?:o\S{0,2}der|contract)"
    r"|\b(?:enhancement\s+in\s+)?size\s+of\s+(?:the\s+)?(?:o\S{0,2}der|contract)"
    r"|\bwhether\s+(?:the\s+)?(?:o\S{0,2}der|contract|domestic|promoter)"
    r"|\btime\s+period\s+by\s+which|\bbroad\s+(?:commercial\s+)?consideration|$))",
    re.I)
_ANNEXURE_LABEL_STRIP = re.compile(
    r"\b(?:to\s+which|from\s+which)\b[^:;\n]{0,50}?\bawarded\b"
    r"|\bawarding\s+(?:the\s+)?"
    r"|\bo\S{0,2}der\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?(?:\s*(?:/|or|and|&)\s*)?con\S{1,8}?ct"
    r"\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|\/\s*con\S{1,8}?ct\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|\bo\S{0,2}der\s*(?:[\[\(]\s*s?\s*[\)\]]\s*)?"
    r"|(?:the\s+)?contract(?:\s?\(?s?\)?)?\s*(?=[:;|]|$)",
    re.I)



def _annexure_awarders(text: str) -> list[str]:
    """Extract customer names from Reg 30 annexure rows ('Name of the entity ... awarding ...')."""
    out: list[str] = []
    flat = _flat(text)
    for match in _ANNEXURE_AWARDER.finditer(flat):
        raw = _ANNEXURE_LABEL_STRIP.sub(" ", match.group("cust"))
        raw = re.sub(r"\s+", " ", raw).strip(" ;:,.-|")
        raw = re.sub(r"^(?:details?|particulars|contract|order|entity|party|name)\b[\s:;-]*",
                     "", raw, flags=re.I)
        if raw:
            out.append(raw)
    return out


def _is_customer_description(value: Any) -> bool:
    """A printed category, not a named awarder: all lower case or a generic lead ("A hyperscale partner")."""
    desc = _flat(value)
    return bool(desc) and (desc.islower() or bool(_CUSTOMER_DESCRIPTION.match(desc)))


def _split_customer(row: dict[str, Any]) -> None:
    """Move a description out of ``customer`` into ``customer_desc`` so a category is never served as an awarder."""
    customer = row.get("customer")
    if customer and _is_customer_description(customer):
        row["customer_desc"] = row.get("customer_desc") or _flat(customer)[:300]
        row["customer"] = None


def _clean_party(text: Any, *, from_annexure: bool = False) -> str | None:
    """A printed awarder name without OCR bullets, table junk, a date clause or generic descriptions."""
    value = re.sub(r"[\ue000-\uf8ff|]", " ", _flat(text))
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
    value = re.sub(r"\s+", " ", value).strip(" ;:,.-—–")
    value = re.sub(r"^(?:[—–\-•]+\s*)*(?:the|m/s\.?|messrs\.?)\s+", "", value, flags=re.I)
    value = re.sub(r"\s+Ref\.?(?:\s*:.*)?$", "", value)
    value = re.sub(r"\s+[1-9]$", "", value)
    value = value.strip(" ;:,.-—–")
    if not value or len(value) < 3 or len(value) > (120 if from_annexure else 80) \
            or _BAD_CUSTOMER.search(value):
        return None
    if not re.search(r"[A-Z]", value) or re.search(r"\bFY\s?\d{2}\b", value):
        return None
    if len(value) > 18 and " " in value and value.islower():
        return None
    return value


def _order_value_from_text(text: str) -> tuple[float, str] | None:
    """A printed order/contract value row the prescribed table did not carry (a scanned or free-form letter)."""
    for rx in (_ORDER_VALUE_ROW, _ORDER_VALUE_LABEL):
        for match in rx.finditer(text or ""):
            value = _to_cr(match.group("v"), match.group("u"))
            if value is not None:
                return value, match.group(0)
    return None


def _is_buyer_side(title: str, text: str) -> bool:
    body = _flat(f"{title} {text}")
    return bool(_ORDER_BUYER.search(body) and not _WIN_FROM.search(body))


def _loose_order_record(title: str, text: str) -> dict[str, Any] | None:
    """A free-form order letter (no prescribed table): a win sentence plus a printed "(e) Value" row."""
    body = _flat(f"{title} {text[:2500]}")
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
    named = re.search(r"(?:contract\s+agreement|order|contract)\s+(?:with|from|awarded\s+by)\s+([A-Z][^.;]{3,120})",
                      body)
    if named:
        customer = _flat(named.group(1))[:200]
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


def _consortium_share(text: str, symbol: str) -> tuple[float | None, float | None]:
    """(printed share %, printed share amount in crore) when the filing states the company's consortium share."""
    if not _CONSORTIUM.search(text):
        return None, None
    amount_match = _CONSORTIUM_AMOUNT.search(text)
    if amount_match:
        amount = _sane_cr(_to_cr(amount_match.group("v"), amount_match.group("u")))
        pct_match = re.search(r"(\d+(?:\.\d+)?)\s*%", amount_match.group(0))
        return (float(pct_match.group(1)) if pct_match else None), amount
    token = symbol.upper()[:4]
    for match in _CONSORTIUM_PCT.finditer(text):
        pct = match.group("p") or match.group("p2")
        if not pct:
            continue
        before = text[max(0, match.start() - 60): match.start()]
        if match.group("p2") and token and token not in before.upper():
            continue
        return float(pct), None
    return None, None


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
    if records_override is not None:
        records = records_override
    else:
        if _ORDER_VETO.search(_flat(f"{title} {text}")) or _is_buyer_side(title, text):
            return None
        records = order_wins.parse(_flat(title), _flat(text))
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
        fallback = _order_value_from_text(_flat(text))
        if fallback:
            amount, value_text = fallback
            derived = 0
    quote = _flat(records[0].get("quote")) or _flat(value_text) or ""
    if value_text and _flat(value_text) in _flat(text):
        match = re.search(re.escape(_flat(value_text)), _flat(text))
        if match:
            quote = _around(_flat(text), match)
    customers = []
    for record in records:
        awarder = _clean_party(record.get("awarder"), from_annexure=True)
        if awarder:
            customers.append(awarder)
    if not customers and allow_body_customer:
        for raw in _annexure_awarders(text):
            awarder = _clean_party(raw, from_annexure=True)
            if awarder:
                customers.append(awarder)
    if not customers and allow_body_customer:
        named = re.search(
            r"(?:(?:work\s+order|order|contract|letter\s+of\s+award)"
            r"[^.;|]{0,140}?\bfrom|(?:sub-?\s*contract|contract\s+agreement)[^.;|]{0,40}?\bwith)\s+"
            r"(?:M/s\.?\s+)?([A-Z](?:[^.;,|]|\.(?=[A-Za-z0-9])|(?<=\b[A-Z])\.(?=\s+(?:\(|towards|for|worth|amounting|dated|on))){2,100})",
            _flat(text), re.I)
        if named:
            awarder = _clean_party(named.group(1), from_annexure=False)
            if awarder:
                customers.append(awarder)
    if not customers and allow_body_customer:
        for match in _FROM_ENTITY.finditer(_flat(text)):
            awarder = _clean_party(match.group("name"), from_annexure=False)
            if awarder:
                customers.append(awarder)
                break
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
    detail = ""
    if amount is not None:
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
        share_pct, share_amount = _consortium_share(value_words, symbol)
        if share_amount is not None:
            value_total, amount = amount, share_amount
            share_match = _CONSORTIUM_AMOUNT.search(value_words)
            if share_match:
                value_text = _flat(share_match.group(0))
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
            or _is_buyer_side(title, head or text):
        return []
    records = order_wins.parse(_flat(title), _flat(text))
    prose = _prose_order_records(title, text)
    if len(prose) > len(records):
        records = prose
    loose = _loose_order_record(title, head or text)
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
    r"|post[\s-]?(?:right|issue)|ratio|for\s+every|for\s+each", re.I)


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


def _raise_size(sentence: str, body: str) -> tuple[float | None, str | None, int]:
    """(size in crore, printed span, computed?) of one raise clause: aggregate, else shares x printed price."""
    for size_match in _SIZE_CUE.finditer(sentence):
        prefix = sentence[max(0, size_match.start() - 60):size_match.start()]
        if _MARKET_CAP_CUE.search(prefix):
            continue
        value = _to_cr(size_match.group("v"), size_match.group("u"))
        if value is not None:
            return value, size_match.group(0), 0
    for full in re.finditer(r"(?:aggregat\w*|amount|issue\s+size|size)[^.;]{0,50}?(?:Rs\.?|INR|₹)\s*"
                            r"(?P<v>\d[\d,]{6,})(?:\s*/-)?", sentence, re.I):
        prefix = sentence[max(0, full.start() - 60):full.start()]
        if _MARKET_CAP_CUE.search(prefix):
            continue
        return round(_digits(full.group("v")) / 1e7, 4), full.group(0), 0
    amounts = []
    for value, span, start in _amounts_rs(sentence):
        prefix = sentence[max(0, start - 60):start]
        if _MARKET_CAP_CUE.search(prefix):
            continue
        if re.search(r"issue\s+price|price\s+of|price\s+per|face\s+value|nominal\s+value|premium"
                     r"|at\s+(?:a\s+)?price", prefix, re.I):
            continue
        amounts.append((value, span))
    if amounts:
        value, span = max(amounts, key=lambda pair: pair[0])
        return value, span, 0
    shares, shares_span = _shares_in(sentence)
    price_match = _PRICE.search(sentence) or _PRICE.search(body)
    if shares and price_match:
        price = float(price_match.group("v").replace(",", ""))
        if not (0.01 <= price <= 100_000):
            return None, None, 0
        return round(shares * price / 1e7, 4), f"{shares_span or ''} x {price_match.group(0)}", 1
    return None, None, 0


_RAISE_STAGE_RANK = {"allotment": 5, "completion": 4, "approval": 3, "listing": 2, "proposed": 1, "intimation": 1}
# T-242: only a completed allotment is ``allotment``; a board meeting that approves an issue is ``approval``
# even when the annexure prints "allotment" in a future sense ("allotment of up to", "date of allotment") (#29,
# #46, #60).  "allotted" alone is not enough: "to be allotted"/"assumed to be allotted" state a plan.
_ALLOTMENT_DONE = re.compile(
    r"\b(?:issue|issuance)\s+and\s+allotment\b"
    r"|\b(?:has|have|had)\s+(?:been\s+)?allotted\b"
    r"|\b(?:shares?|warrants?|debentures?|securities)\s+(?:have|has|were|was)\s+been\s+allotted\b"
    r"|\ballotment\s+of\s+[\d,]{3,}\s+(?:equity\s+)?(?:shares?|warrants?|debentures?)\b"
    r"|\ballotted\s+(?:on|today|pursuant)\b"
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


def _raise_stage(title: str, head: str) -> str:
    title_low = _flat(title).lower()
    heading = _SEBI_TEMPLATE_LINE.sub(" ", _flat(head)).lower()
    combined = title_low + " " + heading[:2500]
    if re.search(r"\b(?:draft\s+letter\s+of\s+offer|\bdlof\b|addendum\s+to\s+(?:the\s+)?(?:dlof|draft\s+letter\s+of\s+offer|letter\s+of\s+offer))\b", combined):
        return "proposed"
    if re.search(r"\bnotice\s+of\s+(?:the\s+)?(?:extra[-\s]?ordinary\s+general\s+meeting|egm|annual\s+general\s+meeting|agm)\b"
                 r"|\b(?:egm|agm)\s+to\s+be\s+held\b", combined) \
            and not re.search(r"\bsummary\s+of\s+proceedings|\boutcome\s+of\s+(?:the\s+)?(?:egm|agm)\b", combined):
        return "proposed"
    stage_text = title_low + " " + heading
    if _ALLOTMENT_DONE.search(stage_text):
        return "allotment"
    if re.search(r"\bpost[-\s]?allotment\b", stage_text) and not _APPROVAL_ONLY.search(stage_text):
        return "allotment"              # an outcome-of-subscription table prints the completed allotment
    if re.search(r"listing\s+approval|trading\s+approval|in[-\s]?principle\s+approval|admitted to dealings",
                 title_low):
        return "listing"
    if _APPROVAL_ONLY.search(stage_text):
        return "approval"
    if re.search(r"\bnot\s+exceeding\b|postal ballot|approved|approval|shareholders.{0,30}approved|key terms", heading):
        return "approval"
    if re.search(r"issue (?:opened|closed)|completed the issue|proceeds of the (?:issue|rights)", heading):
        return "completion"
    if re.search(r"listing\s+approval|trading\s+approval|in[-\s]?principle\s+approval", heading):
        return "listing"
    return "intimation"


def raise_fields(title: str, head: str, text: str) -> dict[str, Any] | None:
    """The raise size, issue price, share count and instrument a fund-raise filing prints.

    A bundled outcome can carry several raises (a preferential issue and warrants): each clause gives its own
    printed size, the filing is one event, and distinct printed sizes are summed (computed -> unverified).
    """
    if _RAISE_VETO.search(_flat(f"{title} {head}")) or not _RAISE_CUE.search(_flat(f"{title} {head}")):
        return None                 # a note deep in a financial statement is not the company's raise
    opening = re.split(r"\bAnnexure\b", head, maxsplit=1, flags=re.I)[0][:1200]
    flat_opening = _flat(f"{title} {opening}")
    if _RAISE_AGREEMENT_VETO.search(_flat(f"{title} {head}")) \
            and not _OWN_ISSUE_TITLE.search(_flat(title)):
        return None                 # a facility/loan revision, warrant lapse or stake purchase is not an issuance
    if _RAISE_DEBT_VETO.search(flat_opening):
        return None
    if _RAISE_OUTBOUND_VETO.search(flat_opening) and not re.search(
        r"\braising\s+of\s+funds\b|\bfund\s*[- ]?rais|\bQIP\b|\brights\s+issue\b|\bpreferential\s+(?:issue|allotment)\b"
        r"|\bnon[-\s]?convertible\b|\bNCDs?\b",
        flat_opening, re.I,
    ):
        return None
    is_results = bool(_RESULTS_RELEASE.search(_flat(f"{title} {head[:1500]}")))
    body = _flat(f"{title} {text}")
    sentences = [title] + _clauses(text)
    sizes: list[tuple[float, str | None, int]] = []
    winners: list[str] = []
    continuation = False
    for sentence in sentences:
        if _RAISE_DEBT_VETO.search(sentence) or _RAISE_OUTBOUND_VETO.search(sentence):
            continuation = False
            continue
        if is_results and _FINANCIAL_METRIC.search(sentence):
            continuation = False
            continue
        has_cue = bool(_RAISE_CUE.search(sentence) and _RAISE_ISSUANCE.search(sentence))
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
                               or re.search(r"allotment\s+of|allotted|issuance\s+of|issue\s+price"
                                            r"|being\s+the\s+issue\s+price", sentence, re.I))
        if not decided and not continuation:
            continue
        value, span, computed = _raise_size(sentence, body)
        if value is None:
            continuation = has_cue and decided and not is_results
            continue
        if computed and value < 0.01:
            continuation = False
            continue
        continuation = False
        sizes.append((round(value, 4), span, computed))
        winners.append(sentence)
    # the same figure printed in two clauses is one size; a printed size beats a shares x price computation
    merged: list[tuple[float, str | None, int]] = []
    for value, span, computed in sorted(sizes, key=lambda item: -item[0]):
        for index, (known, _kspan, kcomputed) in enumerate(merged):
            if abs(value - known) <= 0.01 * max(1.0, known):
                if not computed and kcomputed:
                    merged[index] = (value, span, computed)
                break
        else:
            merged.append((value, span, computed))
    if any(not computed for _value, _span, computed in merged):
        merged = [item for item in merged if not item[2]]
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
    clean_body = _SEBI_TEMPLATE_LINE.sub(" ", body)
    instrument, best_count = None, 0
    for name, rx in _INSTRUMENTS:
        count = sum(1 for _ in rx.finditer(clean_body))
        if count > best_count:       # the words the filing repeats most name the instrument; tie keeps priority
            instrument, best_count = name, count
    if re.search(r"\bany\s+instrument\s+or\s+security\b|\bor\s+(?:a|any)\s+combination\s+thereof\b", clean_body, re.I) \
            and sum(1 for _name, rx in _INSTRUMENTS[:6] if rx.search(clean_body)) >= 3:
        instrument = "mixed"
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
    row: dict[str, Any] = {column: None for column in COLUMNS}
    row.update({
        "store": doc["store"], "symbol": doc.get("symbol"), "isin": doc.get("isin"),
        "doc_key": doc.get("doc_key"), "kind": kind, "method": "script", "status": "unverified",
        "entity_scope": ("parent" if _PARENT_SCOPE.search(
            _flat(f"{doc.get('title') or ''} {(doc.get('text') or '')[:1500]}")) else "company"),
        "title": doc.get("title"), "filing_date": doc.get("filing_date"), "known_at": doc.get("known_at"),
        "page": 1, "seq": 1, "detail": "", "why": "", "_text": _flat(f"{doc.get('title') or ''} {doc.get('head') or ''}"),
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
        row["detail"] = "amount not filled by script"
        if not row.get("quote"):
            row["quote"] = _flat(text)[:MAX_QUOTE]
        return row, True
    if derived:
        # the amount is a sum, a delta or annual x tenure; the inputs are printed, the figure is derived.
        row["status"] = "unverified"
        row["detail"] = row.get("detail") or "amount derived from printed values (see value_text)"
        row["page"] = _page_of(doc["pages"], row.get("value_text"))
        return row, False
    problem = _locate(row, doc)
    if problem:
        row["status"] = "quarantined"
        row["detail"] = problem
    elif row["entity_scope"] == "parent":
        row["status"] = "unverified"
        row["detail"] = "parent-company release"
    else:
        _gate_status(row)
    return row, False


def event_rows(doc: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """(script event rows, classes whose required number the script could not fill)."""
    title, text = doc.get("title") or "", doc.get("text") or ""
    head = doc.get("head") or text
    filing_date = doc.get("filing_date")
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    classes = classify(title, head, filing_date=filing_date)
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


def _fold_same_order(rows: list[dict[str, Any]], amends: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """B2: the same order filed twice (Reg 30 + press release) is one event at the earlier ``known_at``."""
    kept: list[dict[str, Any]] = []
    dropped: set[int] = set()
    for row in sorted((r for r in rows if r["kind"] == "order_win"),
                      key=lambda r: (str(r.get("known_at") or ""), str(r.get("doc_key") or ""))):
        match = None
        for prior in kept:
            if prior["doc_key"] == row["doc_key"] or prior["symbol"] != row["symbol"] \
                    or not _customer_compatible(prior, row):
                continue
            try:
                gap = abs((date.fromisoformat(str(row["filing_date"]))
                           - date.fromisoformat(str(prior["filing_date"]))).days)
            except (TypeError, ValueError):
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


# ------------------------------------------------------------------ model fallback
def model_prompt(doc: dict[str, Any], kinds: list[str]) -> str:
    text = (doc.get("head") or doc.get("text") or "")[:MAX_MODEL_CHARS]   # brief: the filing's first two pages
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


def parse_model_reply(raw: str) -> list[dict[str, Any]]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9]*\s*|\s*```$", "", text.strip())
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(text[start:end + 1])
    except ValueError:
        return []
    events = payload.get("events") if isinstance(payload, dict) else None
    return [e for e in events or [] if isinstance(e, dict)]


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


def model_rows(doc: dict[str, Any], kinds: list[str], raw: str) -> list[dict[str, Any]]:
    """Validate one model reply against the printed page: one row per filled class, quarantine if unprinted."""
    rows: list[dict[str, Any]] = []
    for event in parse_model_reply(raw):
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
        if kind == "order_win" and row.get("amount_inr_cr") is not None \
                and _ANNUAL_CUE.search(row.get("value_text") or ""):
            row["value_annual"] = row["amount_inr_cr"]
            tenure = _tenure_years(doc.get("text") or "", row.get("execution_months"))
            if tenure:
                row["value_total"] = round(row["value_annual"] * tenure, 4)
                row["amount_inr_cr"] = row["value_total"]
            else:
                row["amount_inr_cr"] = None
        check_doc = {**doc, "pages": {page: text for page, text in doc["pages"].items() if page <= 2}}
        if row.get("value_text"):
            row["page"] = _page_of(check_doc["pages"], row["value_text"])
        required = (row.get("capacity_value") if kind == "capacity_commissioned"
                    else row.get("amount_inr_cr") or row.get("amount_usd_mn") or row.get("value_annual"))
        if not required:
            row["status"] = "unverified"
            row["detail"] = "model filled no amount"
        elif not _model_unit_printed(row) and row.get("value_annual") is None:
            row["status"] = "unverified"
            row["detail"] = "amount unit not printed in the quoted text (model)"
        elif row.get("value_annual") is not None:
            row["status"] = "unverified"
            row["detail"] = ("annual value x printed tenure (model)" if row.get("value_total") is not None
                             else "annual value; tenure not printed, not a total (model)")
        elif _locate(row, check_doc):
            row["status"] = "quarantined"
            row["detail"] = "model value not printed on the first two pages"
        elif row["entity_scope"] == "parent":
            row["status"] = "unverified"
            row["detail"] = "parent-company release"
        else:
            _gate_status(row)
        row["quote"] = row.get("quote") or _flat(doc.get("text"))[:MAX_QUOTE]
        rows.append(row)
    # one row per (filing, class): the best-filled of the model's own repeats
    best: dict[str, dict[str, Any]] = {}
    rank = {"verified": 3, "unverified": 2, "quarantined": 1}
    for row in rows:
        current = best.get(row["kind"])
        if current is None or rank.get(row["status"], 0) > rank.get(current["status"], 0):
            best[row["kind"]] = row
    return list(best.values())


def ask(client: Client, doc: dict[str, Any], kinds: list[str]) -> str:
    """One free-model read of the first two pages: the raw reply ("" when every try failed)."""
    prompt = model_prompt(doc, kinds)
    for attempt in range(MAX_RETRIES):
        code, body, _usage = client.chat(prompt)
        if code == 200:
            return body
        wait = retry_after_of(client)
        if wait > 0:
            time.sleep(min(wait, MAX_RETRY_WAIT_S))
        else:
            time.sleep(2.0 * (attempt + 1))
    return ""


def run_model(pending: list[dict[str, Any]], workers: int,
              cache_path: Path | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One hy4-flash-free read per pending filing; a reply is cached so a rerun never re-spends the quota.

    A 429 is honoured through its Retry-After (the free window was capped twice on 21 Nov): wait, then retry.
    """
    if not pending:
        return [], {"requests": 0, "rows": 0, "cached": 0}
    cache: dict[str, str] = {}
    if cache_path and cache_path.exists():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    client = Client(MODEL, MODEL_BODY, "t231-filing-events")
    out: list[dict[str, Any]] = []
    lock = threading.Lock()
    requests = 0
    cached = 0

    def key_of(doc: dict[str, Any]) -> str:
        return f"{doc['doc_key']}|{','.join(sorted(doc['_missing']))}"

    def one(doc: dict[str, Any]) -> None:
        nonlocal requests, cached
        key = key_of(doc)
        with lock:
            raw = cache.get(key)
        if raw is None:
            raw = ask(client, doc, list(doc["_missing"]))
            with lock:
                requests += 1
                if raw:
                    cache[key] = raw
                    if cache_path:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        else:
            with lock:
                cached += 1
        if raw:
            rows = model_rows(doc, list(doc["_missing"]), raw)
            with lock:
                out.extend(rows)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, pending))
    return out, {"requests": requests, "cached": cached, "rows": len(out)}


# ------------------------------------------------------------------ build + report
def _insert(con: sqlite3.Connection, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
            meta: dict[str, Any] | None = None) -> None:
    con.executemany(
        f"INSERT INTO event ({','.join(COLUMNS)}) VALUES ({','.join('?' * len(COLUMNS))})",
        [tuple(row.get(column) for column in COLUMNS) for row in rows])
    con.executemany(
        "INSERT INTO amend (doc_key, symbol, amends, filing_date, known_at, why) VALUES (?,?,?,?,?,?)",
        [(a["doc_key"], a.get("symbol"), a["amends"], a.get("filing_date"), a.get("known_at"), a.get("why"))
         for a in amends])
    if meta is not None:
        con.executemany("INSERT INTO run_meta (key, value) VALUES (?, ?)",
                        [(key, json.dumps(value)) for key, value in meta.items()])


def write_db(path: Path, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
             meta: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        _insert(con, rows, amends, meta)
        con.commit()
    finally:
        con.close()


def _ensure_event_columns(con: sqlite3.Connection) -> None:
    """A baseline built before a new event column exists: add it before inserting (additive, no rewrite)."""
    have = {row[1] for row in con.execute("PRAGMA table_info(event)")}
    for column in COLUMNS:
        if column not in have:
            con.execute(f"ALTER TABLE event ADD COLUMN {column} TEXT")


def merge_db(path: Path, baseline: Path, rows: list[dict[str, Any]], amends: list[dict[str, Any]],
             meta: dict[str, Any], doc_keys: Iterable[str]) -> None:
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
        _insert(con, rows, amends)
        con.execute("DELETE FROM run_meta WHERE key='scoped_merge'")
        con.execute("INSERT INTO run_meta (key, value) VALUES ('scoped_merge', ?)",
                    (json.dumps({"baseline": str(baseline), "documents": len(keys),
                                 "rows": len(rows), "seconds": meta.get("seconds")}),))
        con.commit()
    finally:
        con.close()


def build(stores: list[str] | None = None, limit: int | None = None, use_model: bool = True,
          workers: int = 4, out: Path = DEFAULT_OUT, cache: Path | None = DEFAULT_CACHE,
          only: Any = None, baseline: Path | str | None = None) -> dict[str, Any]:
    """Scan every store's announcements and write the event DB. Returns the run counts.

    T-233: ``only`` (a selector) limits the stores/documents re-read, and ``baseline`` makes the run
    copy that DB to ``out`` and replace just those filings' rows.
    """
    from reality_engine.research.driver_claims import list_stores

    chosen = stores or list_stores()
    if only is not None:
        chosen = [store for store in chosen if only.store(store)]
    rows: list[dict[str, Any]] = []
    amends: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    by_class: Counter[str] = Counter()
    filings = 0
    docs_seen = 0
    doc_keys: list[str] = []
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
        parsed: list[tuple[dict[str, Any], list[dict[str, Any]], list[str]]] = []
        classified_keys: set[str] = set()
        for doc in subset:
            found, missing = event_rows(doc)
            parsed.append((doc, found, missing))
            if found:
                classified_keys.add(doc["doc_key"])
        amend, skipped = amend_rows(subset, classified_keys)
        amends.extend(amend)
        for doc, found, missing in parsed:
            if doc["doc_key"] in skipped:
                continue
            if found:
                filings += 1
            by_class.update({kind: 1 for kind in {row["kind"] for row in found}})
            rows.extend(found)
            if missing:
                doc["_missing"] = missing
                pending.append(doc)
        if limit is not None and docs_seen >= limit:
            break

    classified = len({(row["doc_key"]) for row in rows}) or filings
    need_share = len(pending) / classified if classified else 0.0
    meta: dict[str, Any] = {
        "stores": len(chosen), "docs": docs_seen, "classified_filings": classified,
        "by_class": dict(by_class), "script_rows": len(rows), "need_model": len(pending),
        "need_model_share": round(need_share, 4), "model_rows": 0, "workers": workers,
        "stopped": None,
    }
    if pending and use_model and need_share > MODEL_STOP_SHARE:
        meta["stopped"] = (f"more than {MODEL_STOP_SHARE:.0%} of classified filings need the model "
                           f"({len(pending)}/{classified})")
    elif pending and use_model:
        modelled, stats = run_model(pending, workers, cache)
        covered = {row["doc_key"] for row in modelled if row["status"] != "unverified"}
        # a model row replaces the script row of the same (doc_key, kind)
        rows = [row for row in rows if not (row["doc_key"] in covered and row["method"] == "script"
                                            and row["detail"] == "amount not filled by script")]
        rows.extend(modelled)
        meta["model_rows"] = stats["rows"]
        meta["model_requests"] = stats["requests"]
    elif pending:
        meta["stopped"] = "model pass disabled (--no-model)"

    rows = _fold_same_order(rows, amends)
    amends = list({item["doc_key"]: item for item in amends}.values())
    _link_amendments(rows)
    _assign_raise_ids(rows)
    rows = _drop_restated_capacity(rows)

    # one event per (filing, class), the best-filled row stands
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
    if rows and quarantined / len(rows) > QUARANTINE_STOP_SHARE:
        meta["stopped"] = (f"more than {QUARANTINE_STOP_SHARE:.0%} of events quarantined "
                           f"({quarantined}/{len(rows)})")
    if baseline is not None:
        merge_db(out, Path(baseline), rows, amends, meta, doc_keys)
    else:
        write_db(out, rows, amends, meta)
    return meta


def _report_lines(db: Path, seed: int = 7) -> list[str]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        meta = {r["key"]: json.loads(r["value"]) for r in con.execute("SELECT key, value FROM run_meta")}
        total = con.execute("SELECT COUNT(*) FROM event").fetchone()[0]
        lines = [f"# T-231 filing events -- {db}", "", f"events: {total}"]
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
