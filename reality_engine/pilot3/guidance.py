"""Rule-based forward-guidance extractor -> table ``guidance`` (T-049). No model, no OCR, no network.

CLI: ``python -m reality_engine.pilot3.guidance --out <db> [--symbols KEC,BAJFINANCE,HINDALCO] [--limit-docs N]``

One row per forward-looking numeric target stated in a held transcript, deck, results file or press release:
metric (revenue_growth, ebitda_margin, order_intake, nim, credit_cost, aum_growth, capex, project_capital_cost,
project_capital_spent, cost_of_production, interest_cost, ebitda_per_tonne, other), target period, low/high, unit,
direction, the exact sentence, the speaker (a transcript), the filing date and ``known_at``, and ``revision_of`` =
the previous row of the same metric+period, so a "what did they guide and did it change" question answers from one
table.

A project's spend to date ("$3.2 billion capital expenditures spent through end of FY26") is a true fact beside the
project's total cost: family E blanks it out of the range parser, so it is stored as its own row,
``project_capital_spent`` = the amount with the period the sentence names (T-056 family D).

Input is this database's own ``doc_page`` (transcripts read through ``transcript_statement`` so only management
sentences are stored, with their role and call period; decks/results/press releases are split into sentences and
keep the exact page slice).  A sentence is kept only when it carries a guidance cue, a number, a metric word and a
target period (explicit, or the call/result year, with a Q4 call's unlabelled "for the year" read as the next fiscal
year), and only when the metric is the number's grammatical subject (``subject_ok``, T-049 review 4 Nov 2026): a
share of a total ("60% of our supply", "25% of turnover") is never a margin or a level, a sentence that names a
metric keeps that metric, and an answer that names none must have its metric in the question, be a forward
statement itself and not make another subject (net debt, order book, a rate of change) the number's owner.  Macro
forecasts (GDP, inflation, IMF, repo), a metric level that cannot be right for that metric, and sentences whose only
cue is a past measurement (achieved, stood at, grew by, last year) are dropped, so ``pilot3_guidance`` returns
targets, not commentary.

A target said in words is a row too (T-058): "high single-digit consolidated top line growth for FY27", "the
provision coverage will be in the 70s, mid-70s or higher", "the margins to remain flattish", "full year '27 will
be ahead of full year '26".  Such a row has ``low`` and ``high`` NULL and no invented number: the direction and
the exact quote carry the magnitude, and "high single-digit" is never turned into 7%.  The worded path needs a
guidance cue, a metric word in the sentence itself (never only in the question), a magnitude or comparison word
(ahead of, better than, flattish, in the 70s, high single-digit ...) and a period, and it refuses any sentence
with a reporting verb or an actual's shape, so a result ("EBITDA margin at 23.7%, coming in at the higher end of
our guidance") stays a result.

Only the company's own target is a row (T-166).  A sentence (or the bare sentence before it) that attributes the
number to a rating agency, research house, industry body or "the industry" -- "ICRA expects AUM of AHFCs to rise
by 19-21%", "CRISIL estimates ...", "as per Ind-Ra ...", "the sector is expected to ...", "NBFCs likely to grow"
-- is that body's forecast and is dropped, because a Cholamandalam deck's ICRA housing-finance outlook was served
as Cholamandalam's own AUM guidance.  On a transcript only a management-role statement produces a row: an
analyst's question ("you guided 25-31%?") is never a target, and a line with no identifiable management speaker
is skipped rather than trusted.  Two noise shapes go to review instead of the table: a plain margin range wider
than five points and an order-intake value below 1% of the company's own order-intake scale or annual revenue
("INR120-plus million" read as 120 crore, far below BEL's five-figure-crore order book).  A wide margin band the
company itself calls a band of variability is a target, not noise ("we have variability of 25% to 31% EBITDA
margins", T-187).  A number a sentence governs with "gross margin" is never the EBITDA margin (T-187): ``guidance``
holds no ``gross_margin`` metric, so the number is dropped rather than re-keyed under another metric.

An outside source only removes the number in its own clause (T-166 r4): a sentence that prints a rating
affirmation and then the company's guidance table is still the company's table, so "India Ratings ... reaffirmed
... FY26 guidance ... Revenue 36,000-38,000 Cr" keeps the revenue target, while "ICRA expects AUM ... to rise by
19-21%" still drops.  A guidance table is read as a table only when it is one: a Revenue/EBITDA/Capex label sits
beside its own amount (nothing but punctuation, a currency mark or a footnote digit in between), at least two
labels carry such an amount, the block says guidance/target/parameter, and the sentence names its period.  Prose
that merely mentions two of those words stays on the single-number path, so "Revenue and EBITDA guidance at
₹36,000-38,000 Cr and ₹21,000-22,000 Cr" is not a table.  A past movement is never a target ("improved to Rs.
5,400 from Rs. 4,200", "we have spent Rs 4,200 crores in H1", "achieved 75% of our revised guidance", "used to be
around Rs 20,000 crores"), and a value stated against a target keeps only the target ("capex of Rs 18,619 crore
against target of Rs 16,500 crore" stores 16,500).  A past phrase that restates the company's own guidance is not
a measurement (T-187): "trending at a higher end of what we had guided earlier, which was a range of 23% to 24%"
restates the guided band, "we have guided in the press release that ... we have spent ... INR 1,100 crores"
restates the guided capex, and "our annual CapEx has used to be ... INR 1,200-1,300 crores" states the annual
run-rate of the metric.  A speaker is read only from a transcript; a slide title ("International Ports", "Solid
future outlook", "Capex") is never a speaker.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from . import profile
from .schema import TABLES, GUIDANCE_INDEXES
from .transcripts import split_sentences, _same_person

COLS = ("symbol isin metric target_period low high unit direction said_on doc_key page quote speaker "
        "known_at known_at_source revision_of extractor_rule").split()

DOC_TYPES = ("transcript", "deck", "results", "press_release")
MAX_ROWS_PER_PAGE = 6
BEFORE = 700
AFTER = 250

# --- sentences --------------------------------------------------------------------------------------
_CUE_V1 = (
    r"\b(guidan\w*|guided|guide|corridor|target(?:s|ing|ed)?|estimates?|estimated|expect(?:s|ed|ing)?|"
    r"anticipate[sd]?|foresee|should be|would be|will be|going forward|outlook|we believe|"
    r"is expected to|are expected to|going to see|going to be|talking about|"
    # T-058: "the 5-6% margin that we are saying we will get to" is a forward target
    r"(?:will|would|could|should) get to)\b")
# T-105: the commitments the Q2 FY27 calls made that the v1 cue list did not see -- "we are well on track to
# deliver between 60 million to 62 million new loans", "we are clear about adding 18 MM to 20 MM customers",
# "we remain comfortable … to deliver a 25 to 40 basis point improvement", "we'll lower the corridor … to"
_CUE_V2 = (
    r"\b(?:(?:on track|confident|comfortable|clear)[^.;]{0,40}?\bto\s+(?:deliver|achieve|reach|add)|"
    r"should\s+deliver|(?:are|is)\s+clear\s+about|"
    r"(?:we|i)(?:['’]ll|\s+will)\s+(?:lower|raise|cut|increase|reduce|narrow|widen))\b")
CUE = re.compile(_CUE_V1 + "|" + _CUE_V2, re.I)
CUE_V1 = re.compile(_CUE_V1, re.I)
PAST_ONLY = re.compile(r"\b(achieved|stood at|reported|last year|lask year|previous year|prior year|year ago|"
                       r"grew by|improved by|rose by|was at|were at|was around|were around|increased by|"
                       r"already at|had estimated|we did|they had|run rate|"
                       r"declined by|margin of \d|up \d+% (?:yoy|year-on-year|y-o-y)|"
                       # T-049, 4 Nov 2026: a reported quarter's cost ("was impacted by ... $54 million",
                       # "Adjusted EBITDA down 9% YoY", "came in at $506") was stored as a forward target
                       r"down \d+(?:\.\d+)?\s*%\s*(?:yoy|year-on-year|y-o-y|q[1-4])|impacted by|came in at|"
                       # T-056 review: a habitual spend ("have been spending") is an actual, not a target;
                       # "have been talking about 12-15%" is still guidance.  "in the Q2 level" is NOT added here:
                       # two graded checkpages entries on one metals deck page are found only by that row, and the
                       # fixture's recorded baseline needs both (reported, not settled)
                       r"(?:have|has|had) been (?:spending|investing|incurring|committing)|remained at|"
                       # T-058: "the guidance … we have been able to maintain that at the middle range" is the
                       # level achieved, not the target
                       r"(?:have|has|had) been able to (?:maintain|deliver|achieve)|"
                       # T-062: a present-perfect movement is a measurement ("yield on assets have come down …
                       # 30 basis points"), not a target
                       r"(?:have|has|had)\s+(?:come|gone|fallen|risen|declined|grown|increased|decreased|moved|"
                       r"eased|hardened|dropped|improved))\b", re.I)
# a percentage that is the rate OF something else ("232 aluminium tariffs at 50%", "a duty of 10%") is not a
# company target (T-049, 4 Nov 2026: a tariff rate was stored as an FY26 EBITDA margin)
RATE_OF = re.compile(r"\b(?:tariffs?|duty|customs duty|levy|surcharge|tax rate|repo rate)\b[^.%]{0,40}"
                     r"\d+(?:\.\d+)?\s*%", re.I)
FACT_SHAPE = re.compile(r"\b(today|currently|as of|as at|current level|stands? at|backlog)\b", re.I)
OWN_PERIOD = re.compile(r"\b(?:(?:next|this|current|following)\s+(?:fiscal|financial year|year)|for the (?:full )?year|"
                        r"full year|FY\s*'?\s*\d|fiscal\s*'?\s*\d|Q[1-4]\s*FY)\b", re.I)
FORWARD = re.compile(r"\b(expect\w*|anticipat\w*|will be|should be|would be|target\w*|estimat\w*|guidance|"
                     r"going forward|going to|foresee|outlook|corridor|talking about)\b", re.I)
MACRO = re.compile(r"\b(gdp|inflation|economy|economic growth|imf|world bank|repo rate|rbi projects|"
                   r"global growth|global|ex-china|headline inflation|consumer price|cy\s?\d{2})\b", re.I)
# a guidance sentence that reports the quarter/full-year RESULT and quotes the guided range (T-056 family C)
GUIDED_ACTUAL = re.compile(r"\b(?:within|midpoint of)\b[^.]{0,60}?\bguid", re.I)
# "this is really how we will report going forward": a reporting basis, not a target (T-056 family C)
REPORT_BASIS = re.compile(r"\bthis is (?:really )?(?:how we|the way we) (?:will |would )?(?:report|book)\b", re.I)
# an effect on a metric is not that metric's level (T-056 review: "the impact of X on operating margin will be 0.7%")
IMPACT_OF_ON = re.compile(r"\bimpacts?\s+of\b[^.]{0,120}?\bon\b", re.I)
# a hedge names no target ("whether it will be 25 or 50 basis points, difficult to quantify")
HEDGE = re.compile(r"\b(?:difficult|hard|impossible|not possible|unable|too early) to "
                   r"(?:quantify|predict|say|estimate|comment|commit|give)\b", re.I)
# "EBITDA per tonne remains at ~$500/t" with no future word before the number is the actual, not a target; a
# guidance word before it ("the AUM growth estimates … remain at 24 to 25%") keeps the row (T-056 review)
REMAINS_AT = re.compile(r"\bremains? at\b", re.I)
# --- whose target is it: the company's, not an outside forecaster's (T-166) ---------------------------
# A number attributed to a rating agency, research house, industry body or "the industry" is that body's forecast,
# not the company's own target.  Chola's deck prints ICRA's 19-21% housing-finance AUM growth on a "Sector
# Outlook / Industry outlook" slide; the row was served as Cholamandalam's AUM guidance while management guided
# 22-23%.  A named source in the sentence always rejects the candidate; a source in the sentence before it rejects
# only a sentence that names no company actor ("we", "our", "the company"), so a rating-affirmation boilerplate
# before "we expect 15% growth" keeps the company's own target.
INDUSTRY_WORDS = r"industry|sector|markets?|HFCs?|NBFCs?|AHFCs?"
EXTERNAL_SOURCE = re.compile(
    r"\b(?:ICRA|CRISIL|India Ratings|Ind-Ra|Moody'?s|S&P|Fitch|IBEF|Brickwork|Acuit[ey]|Infomerics|"
    r"rating agenc(?:y|ies)|research house|brokerages?)\b", re.I)
# "CARE" is the one agency whose name is also an everyday word, so it is matched in its printed case only
CARE_RATINGS = re.compile(r"\bCARE(?:\s+(?:Ratings|EDGE))?\b")
INDUSTRY_FORECAST = re.compile(
    r"\b(?:" + INDUSTRY_WORDS + r")\b[^.;]{0,80}?\b(?:is|are|will be|would be|should be)\s+"
    r"(?:expected|anticipated|forecast|projected|likely|poised)\b|"
    r"\b(?:" + INDUSTRY_WORDS + r")\b[^.;]{0,50}?\b(?:expected|anticipated|forecast|projected|likely|poised)"
    r"\s+to\s+(?:grow|expand|rise|increase|decline|decrease|moderate|ease|improve|slow|register|remain)\b", re.I)
AS_PER_EXTERNAL = re.compile(
    r"\b(?:as per|according to)\b\s+(?!(?:our|we|the company)\b)(?:the\s+)?(?:" + INDUSTRY_WORDS +
    r"|ICRA|CRISIL|CARE|India Ratings|Ind-Ra|Moody'?s|S&P|Fitch|IBEF)\b", re.I)
COMPANY_ACTOR = re.compile(r"\b(?:we|our|us|we['’]re|we['’]ll|we['’]ve|company|management|board)\b", re.I)
# T-166 r4: the clause, not the whole sentence, owns a number.  A guidance table printed after a rating
# affirmation in the same page blob is still the company's own table (ADANIPORTS prints India Ratings, then the
# FY26 table, in one blob); the agency's own clause ("ICRA expects AUM of AHFCs to rise by 19-21%") still drops.
CLAUSE_BREAK = re.compile(r"[.;|•▪❑●]")
# a table starts a new clause even without punctuation: "… as IND A1+   FY26 guidance   Parameter   Revenue …"
CLAUSE_START = re.compile(r"(?=\bFY\s*'?\d{2,4}\s+guidance\b|\bParameter\b)")
# T-166 r4: a real guidance table has a label beside its own amount, not two labels mentioned in prose
TABLE_LABELS = (("revenue", re.compile(r"\bRevenue\b", re.I)),
                ("ebitda", re.compile(r"\bEBITDA\b", re.I)),
                ("capex", re.compile(r"\bCapex\b", re.I)))
TABLE_CUE = re.compile(r"\b(?:guidance|guided|target|parameter)\b", re.I)
# "Net debt / EBITDA" names the ratio's denominator, never a table row of its own
NET_DEBT_RATIO = re.compile(r"\bnet\s+debt\s*(?:/|to)\s*$", re.I)
# what may sit between a row label and its amount: punctuation, a currency/unit parenthesis, a footnote digit
TABLE_GAP = re.compile(r"^\s*(?:\(\s*(?:₹|Rs\.?|INR|US\$)?\s*"
                       r"(?:Cr|crores?|Mn|Bn|million|billion)\s*\))?\s*(?:\d{1,2}\s*)?$", re.I)
TABLE_AMOUNT = re.compile(
    r"(?P<pre>₹|Rs\.?|INR|US\$|\$)?\s*(?<![\d.,])(?P<lo>\d[\d,]*(?:\.\d+)?)"
    r"(?:\s*(?:to|-|–|—)\s*(?P<pre2>₹|Rs\.?|INR|US\$|\$)?\s*(?P<hi>\d[\d,]*(?:\.\d+)?))?"
    r"\s*(?P<unit>crores?|cr|lakhs?|million|mn|billion|bn)?(?![A-Za-z])", re.I)
TABLE_MONEY = re.compile(r"₹|\bRs\.?|\bINR|US\$|(?<![A-Za-z])\$|\(₹\s*Cr\)|\bCr\b|crores?\b", re.I)
# T-166 r4: past figures are not targets.  A number right after a movement verb ("improved to Rs. 5,400",
# "from Rs. 4,200"), after "had targeted"/"used to be", or inside "achieved 75% of our guidance" is a
# measurement; a value stated against a target keeps only the target.
PAST_MOVE_VERB = re.compile(r"\b(?:improved|increased|rose|grew|grown|declined|decreased|dropped|fell|fallen|"
                            r"reduced|expanded|stepped|climbed)\s+(?:to|from)\b", re.I)
PAST_MOVE_PRE = re.compile(r"\b(?:improved|increased|rose|grew|grown|declined|decreased|dropped|fell|fallen|"
                           r"reduced|expanded|stepped|climbed)\s+(?:to|from)\s+"
                           r"(?:₹|Rs\.?|INR|US\$|\$)?\s*$", re.I)
FROM_BASE_PRE = re.compile(r"\bfrom\s+(?:₹|Rs\.?|INR|US\$|\$)?\s*$", re.I)
HAD_TARGET_PRE = re.compile(r"\b(?:had\s+(?:targeted|guided|estimated|expected|planned)|used\s+to\s+be|"
                            r"(?:have|has|had)\s+(?:spent|invested|incurred)|spent)\b[^.;]{0,30}"
                            r"(?:₹|Rs\.?|INR|US\$|\$)?\s*$", re.I)
# T-187: a past phrase that restates the company's own guidance is not a measurement.  "what we had guided
# earlier, which was a range of 23% to 24%" restates the guided band; "we have guided in the press release that
# ... we have spent ... INR 1,100 crores" restates the guided capex; "our annual CapEx has used to be ... INR
# 1,200-1,300 crores" states the annual run-rate of the metric, which is the level the metric is guided at.
RESTATED_RANGE_PRE = re.compile(r"\b(?:range|corridor)\s+of\b[^.;]{0,12}$", re.I)
GUIDE_WORD = re.compile(r"\b(?:guidan\w*|guided|guide)\b", re.I)
SPENT_PRE = re.compile(r"\b(?:have|has|had)\s+(?:spent|invested|incurred)\b[^.;]{0,30}"
                       r"(?:₹|Rs\.?|INR|US\$|\$)?\s*$", re.I)
USED_TO_BE_PRE = re.compile(r"\bused\s+to\s+be\b[^.;]{0,30}(?:₹|Rs\.?|INR|US\$|\$)?\s*$", re.I)
ANNUAL_LEVEL = re.compile(r"\b(?:annual(?:ly)?|per annum|run[- ]rate|every year)\b", re.I)
# T-187: a plain wide margin range is still a band, not a target, but the company's own band of variability is
# one ("we have variability of 25% to 31% EBITDA margins based on the product mix").
VARIABILITY = re.compile(r"\b(?:variability|variation)\b", re.I)
# T-187: the number a sentence governs with "gross margin" is not the EBITDA margin.  The last margin phrase
# before the number decides its subject; a number with no margin phrase before it may be governed by one right
# after it ("5% to 10% better gross margin").  ``guidance`` has no ``gross_margin`` metric, so the number is
# dropped rather than stored under another metric.
MARGIN_PHRASE = re.compile(r"\bgross\s+margins?\b|"
                           r"\b(?:(?:ebitda|operating|op\.?|core|net|profit|combined)\s+)?margins?\b", re.I)
GROSS_MARGIN = re.compile(r"\bgross\s+margins?\b", re.I)
# "5% to 10% better gross margin": the number is a change in the gross margin, printed right before its name
GROSS_MARGIN_AFTER = re.compile(r"^\s*(?:,\s*)?(?:better|higher|lower|improved?|of|at|around|about|:|-|–|—)?\s*"
                                r"gross\s+margins?\b", re.I)
# "a gross margin of 42%" / "42% gross margin": the amount printed as a gross margin, so a bare number of the same
# value just before or after it is that gross margin's ("So that mix determines the gross margin. So, going
# forward at the full year, we should have around 42%.")
GROSS_LEVEL = re.compile(
    r"\bgross\s+margins?\b[^.;%]{0,25}?(?P<after>\d[\d,]*(?:\.\d+)?)\s*%|"
    r"(?<![\d.,])(?P<before>\d[\d,]*(?:\.\d+)?)\s*%\s*(?:of\s+)?gross\s+margins?\b", re.I)
ACHIEVED_OF_GUIDANCE = re.compile(r"\b(?:achieved|attained|clocked|delivered)\s+\d+(?:\.\d+)?\s*%?\s+of\b"
                                  r"[^.;]{0,40}\b(?:guidance|guided)\b", re.I)
AGAINST_TARGET = re.compile(r"^\s*(?:crores?|cr|lakhs?|million|mn|billion|bn)?\s*(?:,\s*)?"
                            r"(?:against|versus|vs\.?|compared\s+with)\s+(?:our|the|its)?\s*"
                            r"(?:target|guidance|plan)", re.I)
# "10% points lower than what it used to be" is the size of a change, not a level of the metric
DELTA_POINTS = re.compile(r"^\s*%\s*points?\s+(?:lower|higher|below|above)\b", re.I)
# "yet your gross margin is at 44%, which is nearly 10% points lower than what it used to be" is the size of a
# move, not a target level.
DELTA_POINTS = re.compile(r"\b\d*\s*%?\s*points?\s+(?:lower|higher|below|above)\b", re.I)
# a rating-affirmation/industry-outlook block that carries no company actor: the sentence after it is that
# outside view's number unless the company itself speaks ("Growth is expected to ease to 13%-15%…" after
# "ICRA Rating highlighted that NBFC are …")
NON_MGMT_ROLES = frozenset({"analyst", "moderator", "unknown"})
# `other` is kept only with a guidance word in the same clause as the number (T-056 family F): a level of the
# order book, L1 position or debtors is a fact about the business, not a target.
OTHER_CUE = re.compile(r"\b(?:target\w*|expect\w*|guidanc\w*|guide\w*|aim\w*|would be|will be|should be)\b", re.I)
# T-062: a number read as `other` needs a real target wording, not just a forward tense -- "salaried is about 40%,
# business would be about 34%" is a customer mix.  A worded target ("in the 70s") keeps the looser cue.
OTHER_TARGET = re.compile(r"\b(?:target\w*|expect\w*|guidanc\w*|guid(?:e|ed|es|ing)|aim\w*|plan\w*|project\w*|"
                          r"forecast\w*|intend\w*|outlook|going forward|steady[- ]state|get to|going to)\b", re.I)
# a list of example values is not a target ("there are some 25 basis points, some 100 basis points") -- T-058
EXAMPLE_LIST = re.compile(r"\bsome\s+\d[^.;]{0,25}?\bsome\s+\d", re.I)
# a sentence that declines to guide names no target ("we do not give forward guidance", "we're not going to give
# any guidance beyond that", "we don't guide by segment") -- T-058
NO_GUIDANCE = re.compile(r"\bnot\b[^.;]{0,25}?\b(?:guidanc\w*|guiding|guide)\b|\bwon'?t\s+guid\w*|"
                         r"\bdon'?t\s+guid\w*", re.I)
# the quarter a sentence is looking back at: "Q1 results", "Q2 performance", "in the Q3 level" (T-056 family A)
PAST_Q = re.compile(r"[ \t]*(?:results?|revenues?|performance|earnings|numbers?|level|update|review|profit|sales)\b",
                    re.I)
PAST_VERB = re.compile(r"\b(?:delivered|reported|posted|recorded|achieved|grew|declined|rose|fell|came in|stood at)\b",
                       re.I)
UP = re.compile(r"\b(increas\w*|rise|rising|grow\w*|improv\w*|expand\w*|higher|\bup\b|accelerat\w*|inflation|"
                r"get to)\b", re.I)
DOWN = re.compile(r"\b(decreas\w*|declin\w*|lower\w*|\bcut\b|moderat\w*|reduc\w*|come down|coming down|"
                  r"fall\w*|drop\w*|soften\w*|down\b)\b", re.I)
FLAT = re.compile(r"\b(maintain\w*|unchanged|intact|flat|steady|stable|remain\w*|same)\b", re.I)

# --- a target said in words (T-058) -------------------------------------------------------------------
# low/high stay NULL for these: ``direction`` and the exact quote carry the magnitude, and "high single-digit"
# is never turned into a number.
WORDED_MOVE = re.compile(
    r"\b(?:high|mid|low|upper|lower)[- ](?:single|double)[- ]?digits?\b|"      # high single-digit
    r"\b(?:single|double)[- ]digit\b|"                                          # double digit
    r"\b(?:low|mid|high)[- ]teens\b|\bteens\b|"                                 # mid-teens
    r"\b(?:low|mid|high)[- ]\d0s\b|\b\d0s\b|"                                   # in the 70s, mid-70s
    # a comparison is a target only against a period, never "ahead of schedule" or "lower than our expected
    # revenue" (T-058)
    r"\b(?:ahead of|better than|higher than|lower than)\s+(?:the\s+)?"
    r"(?:full|fiscal|financial|last|prior|previous)\s+year|"
    r"\b(?:ahead of|better than|higher than|lower than)\s+(?:FY|Q[1-4]FY)|"
    r"\bor (?:higher|lower|better|worse|above|below)\b|"                        # mid-70s or higher
    r"\b(?:flattish|flat|stable|steady|unchanged|in line|in the guided range)\b", re.I)
WORDED_UP = re.compile(r"\b(?:ahead of|better than|higher than|or higher|above|improve\w*|stronger|grow\w*|"
                       r"growth)\b", re.I)
WORDED_DOWN = re.compile(r"\b(?:lower than|or lower|below|weaker|declin\w*|soften\w*)\b", re.I)

# metric -> (sentence pattern, plausibility low, plausibility high); priority order matters
METRICS = (
    ("nim", re.compile(r"\bnim\b|net interest margin", re.I), 0.0, 20.0),
    ("credit_cost", re.compile(r"credit cost|loan loss", re.I), 0.0, 20.0),
    ("aum_growth", re.compile(r"\baum\b|assets under management", re.I), 0.0, 60.0),
    ("ebitda_per_tonne", re.compile(r"ebitda\s*(?:per|/)\s*(?:ton|tonne|t)\b|(?:downstream|upstream)\s+ebitda\b|"
                                    r"\bdownstream\b", re.I), 1.0, 5000.0),
    ("order_intake", re.compile(r"order intake|order inflow|order booking|order win", re.I), 50.0, 500000.0),
    # a project's whole capital cost is not one year's capex (T-056 family E)
    ("project_capital_cost", re.compile(r"total (?:project )?capital cost|project capital cost|total capital cost",
                                        re.I), 1.0, 5000000.0),
    # the spend so far on that project is its own true fact, emitted beside the total (T-056 family D); it is never
    # a candidate read from a sentence pattern, so it can never pass as a year's capex
    ("project_capital_spent", re.compile(r"capital expenditures?\s+spent|spent\s+through", re.I), 1.0, 5000000.0),
    ("capex", re.compile(r"\bcapex\b|capital expenditure|capital cost", re.I), 1.0, 5000000.0),
    ("interest_cost", re.compile(r"interest cost|interest expense|interest as %|finance cost", re.I), 0.0, 5000.0),
    ("cost_of_production", re.compile(r"cost of production|cash cost|cost inflation|inflation in cost|"
                                      r"input cost|energy cost|costs? (?:went|going|to) up", re.I), -20.0, 60.0),
    ("revenue_growth", re.compile(r"\brevenue\b|top ?line|net sales|\bsales\b|"
                                   # T-058: "the guidance of 60% CAGR" is a top-line growth target
                                   # T-062: an insurer's IRP/APE is its top line
                                   r"\bcagr\b|\bIRP\b|\bAPE\b", re.I), -20.0, 60.0),
    ("ebitda_margin", re.compile(r"ebitda margin|\bmargin\b|\bmargins\b", re.I), 0.0, 50.0),
    # T-105: the count and opex targets of a lender's call ("60 million to 62 million new loans", "18 MM to
    # 20 MM customers", "a 25 to 40 basis point improvement … on opex-to-NTI"); ranked after the long-standing
    # metrics so a sentence that already had a metric keeps it
    ("new_loans", re.compile(r"\bnew loans?\b", re.I), 0.0, 100000.0),
    ("new_customers", re.compile(r"\bnew customers?\b|\bcustomers?\s+to\s+the\s+franchise\b|"
                                 r"\badding\b[^.;]{0,60}\bcustomers?\b", re.I), 0.0, 100000.0),
    ("opex_to_nti", re.compile(r"\bopex\b", re.I), 0.0, 50.0),
    ("other", re.compile(r"order book|fixed|variable|volume|shipment|capacity|utilization|utilisation|"
                         r"customer|market share|pass[- ]through|price variation|"
                         # T-058: the store-level and balance-sheet KPIs stated as targets
                         r"provision coverage|net order value|\bNOV\b|per (?:day )?per (?:dark )?store|"
                         r"per store (?:per )?day", re.I), -1e9, 1e9),
)
# --- numbers ----------------------------------------------------------------------------------------
MONEY = r"(?:rs\.?|inr|₹|usd|\$)"
AMT = r"(\d[\d,]*(?:\.\d+)?)"
UNITWORD = r"(crores?|\bcr\b|lakhs?|million|mn|billion|bn|kilotonnes?|kt\b|tonnes?|/t\b|per ton|per tonne|a ton)?"
# a number spent to date is an actual, not a year's capex; masked before the range parser pairs it with the total
ACTUAL_SPEND = re.compile(MONEY + r"\s*" + AMT + r"\s*" + UNITWORD + r"\s*(?:(?:of\s+)?(?:capex|capital "
                          r"(?:expenditures?|expenditure))\s+)?(?:spent|incurred|invested)\b", re.I)
R_PCT_RANGE = re.compile(r"(?<![\d.])" + AMT + r"\s*%\s*(?:to|-|–|—)\s*" + AMT + r"\s*%")
R_PCT_RANGE2 = re.compile(r"(?<![\d.])" + AMT + r"\s*(?:to|-|–|—)\s*" + AMT + r"\s*%")
R_BPS_RANGE = re.compile(AMT + r"\s*(?:to|-|–|—)\s*" + AMT + r"\s*(?:bps|basis points?)", re.I)
# T-105: a count said as a range in millions with no currency ("60 million to 62 million new loans",
# "18 MM to 20 MM customers"); both numbers must carry the word, so "grew 11% to 13.5 million" is not a range
R_MN_RANGE = re.compile(r"(?<![\d.])" + AMT + r"\s*(?:million|mn|mm)\s*(?:to|-|–|—)\s*" + AMT +
                        r"\s*(?:million|mn|mm)\b", re.I)
R_MONEY_RANGE = re.compile(MONEY + r"\s*" + AMT + r"\s*" + UNITWORD + r"\s*(?:to|-|–|—)\s*" + MONEY + r"?\s*" + AMT +
                           r"\s*" + UNITWORD, re.I)
R_MONEY = re.compile(MONEY + r"\s*" + AMT + r"\s*" + UNITWORD, re.I)
# "INR20 crores, INR25 crores" / "5%, 6%": a range said as a pair, only next to a hedging word
R_PAIR = re.compile(r"(?<![\d.])" + AMT + r"\s*(%|crores?|\bcr\b)\s*,\s*(?:and\s+)?" + MONEY + r"?\s*" + AMT +
                    r"\s*(%|crores?|\bcr\b)", re.I)
PAIR_CUE = re.compile(r"\b(maybe|around|about|between|anywhere|roughly|approximately|another|reach\w*)\b", re.I)
R_PCT_SINGLE = re.compile(r"(?<![\d.])" + AMT + r"\s*%")
R_BPS_SINGLE = re.compile(AMT + r"\s*(?:bps|basis points)", re.I)
R_PER_TON = re.compile(MONEY + r"?\s*" + AMT + r"\s*(?:/t\b|per ton|per tonne|a ton)", re.I)
BULLETS = re.compile(r"[▪•❑●]")
# a running header/footer printed into the page text ("… Limited August 11, 2026 Page 14 of 23")
HEADER_TAIL = re.compile(r"^.{0,120}?\bPage \d+ of \d+[ \t]+", re.I)


def _num(text: str) -> float | None:
    try:
        return float(text.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def _money_unit(word: str | None, raw: str = "") -> str:
    word = (word or "").lower()
    if "crore" in word or word.strip() == "cr":
        return "inr_cr"
    if "lakh" in word:
        return "inr_lakh"
    if "million" in word or word == "mn":
        return "usd_mn"
    if "billion" in word or word == "bn":
        return "usd_bn"
    if word in ("/t", "per ton", "per tonne", "a ton"):
        return "usd_per_t"
    return "usd" if re.search(r"(?:usd|\$)", raw, re.I) else "inr"


def _per_ton_unit(raw: str) -> str:
    return "inr_per_t" if re.search(r"(?:rs\.?|inr|₹)", raw, re.I) else "usd_per_t"


def numbers(text: str) -> list[dict]:
    """Every numeric target in a sentence: {start, end, low, high, unit}. Ranges first, then single values."""
    out: list[dict] = []
    taken: list[tuple[int, int]] = []
    if ACTUAL_SPEND.search(text):
        # "…$2.7 billion capital expenditures spent": an actual, blanked so no range pairs it with the total
        chars = list(text)
        for m in ACTUAL_SPEND.finditer(text):
            for i in range(m.start(), m.end()):
                chars[i] = " "
        text = "".join(chars)

    def free(a: int, b: int) -> bool:
        return all(b <= x or a >= y for x, y in taken)

    def add(a: int, b: int, low: float, high: float, unit: str) -> None:
        if free(a, b):
            taken.append((a, b))
            out.append({"start": a, "end": b, "low": low, "high": high, "unit": unit})

    for m in R_MN_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "mn")
    for m in R_PCT_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "pct")
    for m in R_PCT_RANGE2.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "pct")
    for m in R_BPS_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(2))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), "bps")
    for m in R_MONEY_RANGE.finditer(text):
        low, high = _num(m.group(1)), _num(m.group(3))
        if low is not None and high is not None:
            add(m.start(), m.end(), min(low, high), max(low, high), _money_unit(m.group(2) or m.group(4), m.group(0)))
    for m in R_PAIR.finditer(text):
        if not PAIR_CUE.search(text[max(0, m.start() - 30):m.start() + 5]):
            continue
        low, high = _num(m.group(1)), _num(m.group(3))
        u1, u2 = m.group(2), m.group(4)
        if low is None or high is None or (u1 == "%") != (u2 == "%"):
            continue
        add(m.start(), m.end(), min(low, high), max(low, high), "pct" if u1 == "%" else _money_unit(u1, m.group(0)))
    for m in R_PCT_SINGLE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, "pct")
    for m in R_BPS_SINGLE.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, "bps")
    for m in R_MONEY.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            add(m.start(), m.end(), v, v, _money_unit(m.group(2), m.group(0)))
    for m in R_PER_TON.finditer(text):
        v = _num(m.group(1))
        if v is not None and v >= 1:
            add(m.start(), m.end(), v, v, _per_ton_unit(m.group(0)))
    return out


def spends(text: str) -> list[dict]:
    """Amounts spent to date ("$3.2 billion capital expenditures spent through end of FY26"): the numbers
    ``numbers`` blanks so they cannot pair with a project's total, kept as their own true fact (T-056 family D)."""
    out: list[dict] = []
    for m in ACTUAL_SPEND.finditer(text):
        v = _num(m.group(1))
        if v is not None:
            out.append({"start": m.start(), "end": m.end(), "low": v, "high": v,
                        "unit": _money_unit(m.group(2), m.group(0))})
    return out


# --- periods ----------------------------------------------------------------------------------------
Q_FY = re.compile(r"\bQ\s*([1-4])\s*[- ]?\s*FY\s*'?\s*(\d{2,4})", re.I)
H_FY = re.compile(r"\bH\s*([12])\s*[- ]?\s*FY\s*'?\s*(\d{2,4})", re.I)
FY_RANGE = re.compile(r"\bFY\s*'?\s*(\d{2})\s*[-/]\s*(\d{2,4})", re.I)
FY = re.compile(r"\b(?:FY|fiscal(?: year)?)\s*'?\s*(\d{2,4})", re.I)
# T-058: "full year '27 will be ahead of full year '26" names its period without FY or fiscal
FULL_YEAR = re.compile(r"\bfull\s+year\s*'?\s*(\d{2,4})", re.I)
NEXT = re.compile(r"\b(next|following|coming)\s+(?:fiscal|financial year|year|fiscal)\b", re.I)
THIS = re.compile(r"\b(this|current)\s+(?:fiscal|financial year|year)\b|\bfor the (?:full )?year\b|\bfull year\b|"
                  r"\bannually\b|\bannual(?:ly)? basis\b", re.I)
BARE_Q = re.compile(r"(?<![\w.])(?:in\s+|from\s+|to\s+)?Q\s*([1-4])(?!\s*[- ]?FY)(?![\d])", re.I)
# T-062: "…about 90% in the next quarter" is the quarter after the call's own, and "the cost of production in the
# Q2 level" is that quarter of the filing's fiscal year (the quarter the call reports)
NEXT_Q = re.compile(r"\b(?:next|coming|following)\s+quarter\b", re.I)
Q_LEVEL = re.compile(r"\b(?:in|at)\s+the\s+Q\s*([1-4])\s+level\b", re.I)
# T-105: "medium term" / "longer-term" is a horizon, not a fiscal year: the Q2 FY27 call gives FY27 26-27%, a
# medium-term 20-25% corridor and a longer-term 23-25% one, and the horizons must not overwrite the FY27 target
HORIZON = re.compile(r"\b(medium|longer|long)[- ]term\b", re.I)


def _yy(text: str) -> str:
    return f"{int(text) % 100:02d}"


def doc_period(filing_date: str | None, known_at: str | None) -> tuple[int, str] | None:
    """(fiscal year number, quarter) of the period a filing reports: Apr-Jun files Q4 of that year, Jul-Sep Q1
    of the next, Oct-Dec Q2, Jan-Mar Q3."""
    day = (filing_date or (known_at or "")[:10] or "")[:10]
    m = re.match(r"(\d{4})-(\d{2})", day)
    if not m:
        return None
    year, month = int(m.group(1)), int(m.group(2))
    if 4 <= month <= 6:
        return year % 100, "Q4"
    if 7 <= month <= 9:
        return (year + 1) % 100, "Q1"
    if 10 <= month <= 12:
        return (year + 1) % 100, "Q2"
    return year % 100, "Q3"


def split_period(label: str | None) -> tuple[int | None, str | None]:
    """'Q4FY26' -> (26, 'Q4'); 'FY26' -> (26, None)."""
    if not label:
        return None, None
    m = re.fullmatch(r"(?:Q([1-4])|H([12]))?FY(\d{2})", label.upper())
    if not m:
        return None, None
    return int(m.group(3)), ("Q" + m.group(1) if m.group(1) else None)


def base_forward(call_period: str | None, doc: tuple[int, str] | None) -> int | None:
    """The fiscal year a guidance sentence in this document is about when it names none: the call/result year, and
    for a Q4 filing the year after (a Q4 earnings call guides the year ahead)."""
    fy, q = split_period(call_period)
    if fy is not None:
        return fy + 1 if q == "Q4" else fy
    if doc:
        return doc[0] + 1 if doc[1] == "Q4" else doc[0]
    return None


def _explicit_period(text: str, pos: int | None = None) -> str | None:
    """The period label in text: the first Q_FY, H_FY, FY range or FY hit; with ``pos``, the label nearest that
    offset, so a sentence's own "FY26" beats a quarter heading printed farther away (T-056 family A)."""
    labels: list[tuple[int, int, str]] = []
    for rx, make in ((Q_FY, lambda m: f"Q{m.group(1)}FY{_yy(m.group(2))}"),
                     (H_FY, lambda m: f"H{m.group(1)}FY{_yy(m.group(2))}"),
                     (FY_RANGE, lambda m: f"FY{_yy(m.group(2))}"),
                     (FULL_YEAR, lambda m: f"FY{_yy(m.group(1))}"),
                     (FY, lambda m: f"FY{_yy(m.group(1))}")):
        for m in rx.finditer(text):
            labels.append((m.start(), m.end(), make(m)))
    if not labels:
        return None
    if pos is None:
        return labels[0][2]

    def dist(t: tuple[int, int, str]) -> int:
        return 0 if t[0] <= pos <= t[1] else (t[0] - pos if t[0] > pos else pos - t[1])

    return min(labels, key=lambda t: (dist(t), t[0]))[2]


def target_period(sentence: str, before: str, after: str, call_period: str | None,
                  doc: tuple[int, str] | None, pos: int | None = None) -> str | None:
    """The period a target is about: explicit label in the sentence, else the nearest one before it (the question),
    else the call/result year rule; a bare "Q2" is the next quarter with that number after the call, and the bare
    quarter nearest the target number wins ("5%, 6% Q2 to Q1" names Q2).  "next year" is the year after the call's
    own, but a bare quarter in a backward-looking phrase ("Q1 results", "Q2 performance") is not the target
    (T-056 families A and B)."""
    # T-062: "…about 90% in the next quarter" is the quarter after the call's own; a period label before the number
    # ("in Q2FY26 about 80% of the NOV … expected to go to … in the next quarter") describes the current state
    nq = NEXT_Q.search(sentence)
    next_q = bool(nq and pos is not None and nq.start() >= pos
                  and not any(rx.search(sentence, pos) for rx in (Q_FY, H_FY, FY_RANGE, FULL_YEAR, FY)))
    label = _explicit_period(sentence, pos)
    if label and not next_q:
        return label
    hz = HORIZON.search(sentence)
    if hz:
        return "long_term" if hz.group(1).lower().startswith("long") else "medium_term"
    base = base_forward(call_period, doc)
    if next_q and nq:
        fy, call_q = split_period(call_period)
        if fy is None and doc:
            fy, call_q = doc[0], doc[1]
        if fy is not None and call_q:
            n = int(call_q[1]) + 1
            return f"Q{n}FY{fy:02d}" if n <= 4 else f"Q1FY{fy + 1:02d}"
    lvl = Q_LEVEL.search(sentence)
    if lvl:
        fy, _q = split_period(call_period)
        if fy is None and doc:
            fy = doc[0]
        if fy is not None:
            return f"Q{lvl.group(1)}FY{fy:02d}"
    if base is None:
        return None
    moves = [(m.start(), "next") for m in NEXT.finditer(sentence)] + \
            [(m.start(), "this") for m in THIS.finditer(sentence)]
    if moves:
        cue = (min(moves, key=lambda t: (abs(t[0] - pos), t[0])) if pos is not None else moves[0])[1]
        return f"FY{base + (1 if cue == 'next' else 0):02d}"
    qs = list(BARE_Q.finditer(sentence))
    if qs:
        # the quarter the sentence is about: nearest one after the target number, but never a comparison base
        # ("versus Q4", "from Q3") and never the quarter a result is reported for ("Q1 results", "Q2 performance")
        kept = [m for m in qs
                if not PAST_Q.match(sentence, m.end())
                and not PAST_VERB.search(sentence[max(0, m.start() - 45):m.start()])
                and not re.search(r"\b(?:versus|vs\.?|from|than|against|compared with)\s*$",
                                  sentence[max(0, m.start() - 14):m.start()], re.I)]
        if pos is None:
            q = kept[0] if kept else None
        else:
            after_q = [m for m in kept if m.start() >= pos]
            before_q = [m for m in kept if m.start() < pos]
            q = (min(after_q, key=lambda m: m.start()) if after_q else
                 (max(before_q, key=lambda m: m.start()) if before_q else None))
        if q is not None:
            fy, call_q = split_period(call_period)
            n = int(q.group(1))
            if fy is None and doc:
                fy, call_q = doc[0], doc[1]
            if fy is not None and call_q:
                return f"Q{n}FY{fy + (1 if n <= int(call_q[1]) else 0):02d}"
            if fy is not None:
                return f"Q{n}FY{fy:02d}"
    for text, is_before in ((before[-500:], True), (after, False)):
        label = _explicit_period(text)
        if label:
            fy, _q = split_period(label)
            if is_before and fy is not None and fy < base:
                continue                # the question's period is already over: not a target period (T-056)
            return label
    return f"FY{base:02d}"


# --- classification ---------------------------------------------------------------------------------
METRIC_UNITS = {
    "nim": {"pct", "bps"},
    "credit_cost": {"pct", "bps"},
    "aum_growth": {"pct"},
    "revenue_growth": {"pct"},
    "ebitda_margin": {"pct"},
    "cost_of_production": {"pct"},
    "interest_cost": {"pct", "inr_cr", "inr", "inr_lakh"},
    "order_intake": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn", "count"},
    "project_capital_cost": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    "project_capital_spent": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    # T-166 r4: the absolute revenue and EBITDA levels of a guidance table (the metric word is the row label)
    "revenue": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    "ebitda": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    "capex": {"inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn"},
    # a per-tonne target is often said as a bare "$250", converted to usd_per_t / inr_per_t below
    "ebitda_per_tonne": {"usd_per_t", "inr_per_t", "usd", "inr"},
    # T-105: a count stated in millions ("60 million to 62 million new loans") and a lender's opex ratio
    "new_loans": {"mn", "count"},
    "new_customers": {"mn", "count"},
    "opex_to_nti": {"pct", "bps"},
    "other": {"pct", "bps", "inr_cr", "inr", "inr_lakh", "usd", "usd_mn", "usd_bn", "count", "usd_per_t", "inr_per_t"},
}


# T-105: the metrics the v1 rules never produced (a count in millions, a lender's opex ratio)
NEW_METRICS = frozenset({"new_loans", "new_customers", "opex_to_nti"})


def _bank_metric_ok(symbol: str) -> bool:
    """nim/credit_cost belong to a lender whose profile sector is nbfc or bank (T-056 family F: an insurer's
    growth was stored as NIM).  Without a profile the present behaviour is kept."""
    prof = profile.active()
    if prof is None:
        return True
    try:
        c = prof.company(symbol)
    except KeyError:
        return True
    return c.lender and c.sector.strip().lower() in ("nbfc", "bank", "banking")


LENDER_GROWTH = re.compile(r"\bgrowth\b", re.I)
# a growth of a line we do not hold as a metric ("fee income growth", "ROA growth", "profit growth") is not the
# company's overall growth, and a lender's unqualified "growth" must not take that reading (T-105)
OTHER_GROWTH = re.compile(
    r"\b(?:fee|fees|commission|income|profit|earnings|pat|eps|roa|roe|return on (?:assets|equity)|"
    r"margin|margins|deposits?|book value)\b[^.;]{0,30}\bgrowth\b", re.I)
# "this number should be in the range of 17%-20% growth": the measure was named earlier (the fee-income line of
# the question), so the sentence itself does not own the growth word (T-105)
PRONOUN_NUMBER = re.compile(r"\b(?:this|that|the)\s+number\b", re.I)


def _lender_growth(symbol: str, sentence: str, prev: str = "", before: str = "") -> bool:
    """True when a lender is speaking of "growth" without naming the measure (T-105): for an NBFC that is its AUM
    growth ("26%, 27% growth we should deliver", "the longer-term growth guidance of 23% to 25%").  A growth of a
    named line we do not hold as a metric (fee income, ROA) is left out, and so is a "this number" that borrows its
    subject from an earlier paragraph."""
    if not profile.is_lender(symbol) or PRONOUN_NUMBER.search(sentence) \
            or OTHER_GROWTH.search(" ".join((sentence, prev, before[-700:]))):
        return False
    if LENDER_GROWTH.search(sentence):
        return True
    # the previous statement supplies the word only when it is itself a forward guidance statement
    return bool(prev and CUE.search(prev) and not PAST_ONLY.search(prev) and LENDER_GROWTH.search(prev))


def metric_candidates(symbol: str, sentence: str, before: str, after: str, prev: str = "") -> list[str]:
    """Metric names in priority order: the sentence first, then the question before it, then the text after.
    ``other`` (a share or structural statement) ranks last whatever text it came from.

    ``prev`` is the previous management statement on the page (T-105): a sentence that names no metric may take
    it from the statement before it -- the Q2 FY27 call says "26%, 27% growth we should deliver" and then "we
    maintain a guidance of 20% to 25%", where only the first sentence carries the word ``growth``."""
    seen: list[str] = []
    sentence_names = 0
    for index, text in enumerate((sentence, before[-300:], after[:150])):
        for name, rx, _lo, _hi in METRICS:
            if name in ("other", "project_capital_spent") or not rx.search(text) or name in seen:
                continue
            if name == "ebitda_margin" and profile.is_lender(symbol) and not re.search(r"ebitda", text, re.I) \
                    and _bank_metric_ok(symbol):
                name = "nim"          # a bank's or NBFC's "margin" is its NIM; an insurer's margin is a margin
                                      # and its growth is not NIM (T-058: SBILIFE was losing every margin row)
            if name in ("nim", "credit_cost") and not _bank_metric_ok(symbol):
                continue
            if name not in seen:
                seen.append(name)
        if index == 0:
            sentence_names = len(seen)
    # T-105: a lender's unqualified "growth" said as guidance is its AUM growth ("between 26%, 27% growth we
    # should deliver now on a full year basis", "the longer-term growth guidance of 23% to 25%").  A named revenue
    # growth keeps its own metric; the growth word may sit in the sentence or in the previous statement, never in
    # a wider page window (which would pull in an unrelated growth sentence).
    if "aum_growth" not in seen and "revenue_growth" not in seen and _lender_growth(symbol, sentence, prev, before):
        seen.insert(sentence_names, "aum_growth")
    if any(rx.search(text) for text in (sentence, before[-300:], after[:150])
           for nm, rx, _lo, _hi in METRICS if nm == "other"):
        seen.append("other")
    return seen


def plausible(metric: str, low: float, high: float, unit: str) -> bool:
    """A unit the metric can be stated in and a level that can be right for it."""
    if unit not in METRIC_UNITS.get(metric, set()):
        return False
    for name, _rx, lo, hi in METRICS:
        if name == metric:
            break
    else:
        return False
    if unit == "bps":
        return 0 < high <= 2000
    if metric == "interest_cost":       # a percentage well above 15 is a market rate, not the company's target
        return 0 <= low <= high <= 15 if unit == "pct" else high > 0
    if unit == "pct":
        return lo <= low <= high <= hi
    if metric in ("revenue_growth", "aum_growth", "ebitda_margin", "cost_of_production", "nim", "credit_cost"):
        return False
    return lo <= low <= high <= hi and high > 0


def gross_margin_owns(sentence: str, chosen: dict, after: str = "") -> bool:
    """True when the number is a gross margin's level, never the EBITDA margin's (T-187).

    The last margin phrase before the number decides its subject, so "Gross margin ... 42% and EBITDA margins ...
    23%" gives 42 to the gross margin and 23 to the EBITDA margin; a number with no margin phrase before it may
    be governed by one right after it ("5% to 10% better gross margin") or be the gross margin restated just
    around it ("So that mix determines the gross margin. So, going forward at the full year, we should have
    around 42%", "we gave around 42% gross margin").  ``guidance`` has no ``gross_margin`` metric, so these
    numbers are dropped, not re-keyed."""
    left = sentence[max(0, chosen["start"] - 150):chosen["start"]]
    marks = list(MARGIN_PHRASE.finditer(left))
    if marks:
        return bool(GROSS_MARGIN.fullmatch(marks[-1].group(0)))
    if GROSS_MARGIN_AFTER.match(sentence[chosen["end"]:chosen["end"] + 40]):
        return True
    levels = set()
    for text in (sentence, after):
        for m in GROSS_LEVEL.finditer(text):
            for group in ("after", "before"):
                value = _num(m.group(group))
                if value is not None:
                    levels.add(value)
    return chosen["low"] in levels or chosen["high"] in levels


# --- the metric must be the target's subject (T-049 review, 4 Nov 2026) -------------------------------
GROWTH_METRICS = {"revenue_growth", "aum_growth"}
GROWTH_NEAR = re.compile(r"\b(growth|grew|grow\w*|increase[sd]?|decrease[sd]?|declin\w*|rise[s]?|expansion)\b", re.I)
# the market's growth is not the company's target (T-056 review: "China is a large, growing market … 5-7%+ growth")
MARKET_OWNS = re.compile(r"\bmarkets?\b[^.;]{0,60}$", re.I)
# a place's share of a split total ("INR1,000 crores in Orissa and INR600 crores would be in MP")
PLACE_IN = re.compile(r"\bin\s+[A-Z][A-Za-z]{1,20}\b")
# a share of a total ("60% of our supply", "25% of turnover", "13% share") is not a margin, a level or a rate
SHARE_NOUN = re.compile(r"^\s*(?:share|of\s+share)\b"
                        r"|\b(?:share|proportion)\s+of\b"
                        r"|\bof\s+(?:an?)\b"
                        r"|\bof\s+(?:our|the|my|its)\s+(?:overall\s+|total\s+)?"
                        r"(?:[\w-]+\s+){0,2}(?:supply|sourcing|requirement|costs?|turnover|revenue|sales|income|profit)\b",
                        re.I)
# another quantity that owns the number: the answer is about it, not about the question's metric
SUBJECT_NOUN = re.compile(r"\b(exposure|debtors?|net debt|debt|borrowings?|working capital|receivables?|order book|"
                          r"backlog|turnover|top ?line|profit|margins?|shipments?|volumes?|supply|sourc\w*|"
                          r"utilisation|utilization|capacity|tonnes?|inflation|costs?)\b", re.I)
# a percent that is a change ("a 10% reduction in the interest cost", "3-4% revenue impact", "a 1% point margin
# accretion") is not a level
PCT_CHANGE = re.compile(r"\s*%?\s*(?:points?\b[^.;]{0,20}?)?(?:reduction|increase|decrease|impact|improvement|"
                        r"savings?|accretion|expansion|drag)\b", re.I)
# the change a number is part of, named before it ("Reduction of 0.75% to 1% due to …") -- T-062
DELTA_NOUN = re.compile(r"\b(?:reduction|increase|decrease|savings?|impact|improvement)\b", re.I)
# T-062: a number taken out of a stated total is a slice, not the total target ("out of INR30,000 crores … INR20,000
# crores"); the whole is already its own row
SLICE_OF = re.compile(r"\b(out of|of which|of that|of these|of the total)\b", re.I)
# "the EBITDA CAGR is 13%" / "store CAGR" is not the top line's CAGR (T-058)
NON_REVENUE_CAGR = re.compile(r"\b(?:ebitda|margin|margins|profit|pat|eps|volume|volumes|store|stores|aum|"
                              r"order|orders|dividend|headcount)\s*[-/ ]?\s*cagr\b", re.I)
METRIC_RX = {name: rx for name, rx, _lo, _hi in METRICS}


def subject_ok(metric: str, sentence: str, chosen: dict, before: str, symbol: str = "",
               prev: str = "") -> bool:
    """True when ``metric`` is the grammatical subject of the number ``chosen``.

    A rule-based reader used to take the metric from the question and any plausible number from the answer, so
    "18% to 20% of interest cost" was stored as an EBITDA-margin target (the question said margin), "10% growth next
    year" for the same reason, and "our net debt ... within our targeted average borrowing levels of 2,500 crore" as
    an interest-cost target.  The rules now:
      * a share of a total ("60% of our supply", "25% of turnover", "13% share") is never a margin or a level,
        only ``other`` (a market share), and neither is a place's share of a split total ("INR1,000 crores in
        Orissa and INR600 crores in MP") nor a market's growth ("China is a large, growing market … 5-7% growth");
      * a rate of change is not a level: "a 10% reduction" is not an interest-cost level of 10%, and "we grow at
        15%" is not a margin of 15% (a growth metric is the one class where the rate *is* the target);
      * when the sentence names a metric, the chosen metric must be one of them (the number is already required to
        sit near its word);
      * when the sentence names none -- the answer to "what about interest cost?" -- the sentence must itself be a
        forward statement, the question before it must name the metric, and the number must not have another
        subject of its own (net debt, order book, supply, turnover, a cost) on either side."""
    if metric != "other" and SHARE_NOUN.search(sentence[chosen["end"]:chosen["end"] + 32]):
        return False
    if metric != "other" and PLACE_IN.search(sentence[chosen["end"]:chosen["end"] + 45]) \
            and re.search(MONEY + r"\s*\d", sentence[:chosen["start"]], re.I):
        return False                    # a place's share of a total split across places (T-056 review)
    if metric in GROWTH_METRICS and MARKET_OWNS.search(sentence[max(0, chosen["start"] - 70):chosen["start"]]):
        return False                    # the market's growth, not the company's (T-056 review)
    if metric == "revenue_growth" and NON_REVENUE_CAGR.search(sentence):
        return False                    # "the EBITDA CAGR is 13%" is not the top line's CAGR (T-058)
    left = sentence[max(0, chosen["start"] - 70):chosen["start"]]
    right = sentence[chosen["end"]:chosen["end"] + 30]
    # T-062: a growth verb governs the whole clause, so "we'll be growing for the year at 14% to 15%" cannot take a
    # margin metric from the question -- the second "14% to 15%" sits 200 characters past "growing"
    own = METRIC_RX.get(metric)
    window = left + " " + right if own and own.search(sentence) else sentence
    if metric not in GROWTH_METRICS and GROWTH_NEAR.search(window):
        return False
    if chosen["unit"] == "pct" and DELTA_NOUN.search(left) \
            and not re.search(r"\b(?:to|at)\s+$", left):
        return False                    # the number is the size of a change ("Reduction of 0.75% to 1%")
    if metric != "other" and SLICE_OF.search(left):
        return False                    # a slice of a stated total is not the total target (T-062)
    if chosen["unit"] == "pct" and PCT_CHANGE.match(sentence[chosen["end"]:chosen["end"] + 32]):
        return False                    # a percent change is not a percent level
    named = [name for name, rx, _lo, _hi in METRICS if rx.search(sentence)]
    if not named and _lender_growth(symbol, sentence, prev, before):
        named = ["aum_growth"]          # T-105: a lender's unqualified "growth" is its AUM growth
    if named:
        return metric in named
    question = before.rsplit("?", 1)[0][-250:] if "?" in before else ""   # the question this answer answers
    if not (FORWARD.search(sentence) and metric in metric_candidates(symbol, "", question, "")):
        return False
    for window in (left, right):
        other = SUBJECT_NOUN.search(window)
        if other and not METRIC_RX[metric].search(other.group(0)):
            return False
    return True


def direction_of(sentence: str, metric: str) -> str:
    if DOWN.search(sentence):
        return "down"
    if FLAT.search(sentence):
        return "flat"
    if UP.search(sentence):
        return "up"
    return "up" if metric in ("revenue_growth", "aum_growth") else "flat"


def pick_number(sentence: str, nums: list[dict]) -> dict | None:
    """The number the guidance verb points at: the first one after the nearest cue, else the nearest to it.  A
    number that is a comparison base ("against INR5,000 crores, which we got this year") is not the target
    (T-056 family H: the prior year's order intake was read as this year's)."""
    nums = [n for n in nums
            if not re.search(r"\b(?:against|versus|vs\.?|compared with|than|up from|down from)\s+$",
                             sentence[max(0, n["start"] - 16):n["start"]], re.I)
            and not re.match(r"\s*(?:last|previous|prior|year[- ]ago)", sentence[n["end"]:n["end"] + 22], re.I)]
    if not nums:
        return None
    cues = [m.start() for m in CUE.finditer(sentence)]
    if not cues:
        return nums[0] if nums else None
    after = [(n["start"] - max(c for c in cues if c <= n["start"]), n) for n in nums if any(c <= n["start"] for c in cues)]
    if after:
        return min(after, key=lambda t: t[0])[1]
    return min(nums, key=lambda n: min(abs(n["start"] - c) for c in cues))


# --- reading the database ---------------------------------------------------------------------------
_DIMS: list | None = None


def dimensions() -> list:
    """The segment/geography words of ``lexicon/dimensions.yaml``, through the kpi reader (T-056 family F)."""
    global _DIMS
    if _DIMS is None:
        from .kpi import load_lexicon
        _DIMS = load_lexicon()[1]
    return _DIMS


def segment_subject(sentence: str, chosen: dict, symbol: str) -> bool:
    """True when a segment or business of the company owns the number: the dimension word sits within 140
    characters before it (T-056 family F: a segment's margin was stored as the company's)."""
    lo = max(0, chosen["start"] - 140)
    window = sentence[lo:chosen["start"]]
    for d in dimensions():
        if d.companies and symbol not in d.companies:
            continue
        if any(rx.search(window) for rx in d.patterns):
            return True
    return False


def other_cued(sentence: str, chosen: dict) -> bool:
    """``other`` needs a guidance word in the number's own clause, and no other noun owning the number
    (T-056 family F: an L1 position, an order-book exposure or gross debtors are not targets)."""
    left = sentence[max(0, chosen["start"] - 70):chosen["start"]]
    for m in SUBJECT_NOUN.finditer(left):
        if not METRIC_RX["other"].search(m.group(0)):
            return False
    for m in OTHER_CUE.finditer(sentence):
        if abs(m.start() - chosen["start"]) > 80:
            continue
        a, b = (m.end(), chosen["start"]) if m.end() <= chosen["start"] else (chosen["end"], m.start())
        if a <= b and "," not in sentence[a:b]:
            return True
    return False


def worded_direction(sentence: str, metric: str, pos: int | None = None) -> str:
    """The direction of a worded target: "ahead of" / "better than" / "or higher" is up, "flattish" / "in the
    guided range" is flat, and a growth metric keeps up when it names no size word.  With ``pos`` only the words
    around the size word count, so a growth elsewhere in the sentence does not turn "margin … remaining flat" up
    (T-062)."""
    window = sentence[max(0, pos - 60):pos + 60] if pos is not None else sentence
    if WORDED_DOWN.search(window):
        return "down"
    if WORDED_UP.search(window) or metric in GROWTH_METRICS:
        return "up"
    return "flat"


def _row_rule(sentence: str, metric: str, unit: str, symbol: str, v1_found: bool) -> str:
    """The rule that produced the row (T-105): ``guidance_cue_v2`` when a v2-only cue, one of the new count/opex
    metrics or the million-range parser was needed; ``guidance_cue_v2_context`` when the metric is not named in
    the sentence and came from the page context (a lender's generic "growth", the question before it, the previous
    statement); ``guidance_cue_v1`` for a row the old rules would have found as they were (``v1_found``)."""
    if metric in NEW_METRICS or unit == "mn":
        return "guidance_cue_v2" if METRIC_RX[metric].search(sentence) else "guidance_cue_v2_context"
    if metric == "aum_growth" and not METRIC_RX["aum_growth"].search(sentence) and profile.is_lender(symbol):
        return "guidance_cue_v2_context"
    return "guidance_cue_v1" if v1_found else "guidance_cue_v2"


def worded_row(symbol: str, doc: sqlite3.Row, page: int, sentence: str, quote: str, speaker: str | None,
               before: str, call_period: str | None, docper: tuple[int, str] | None, stats: dict) -> tuple | None:
    """A forward target said in words with no figure (T-058): the metric and the period are read as usual and the
    row keeps ``low``/``high`` NULL, with ``direction`` and the exact quote carrying the magnitude.

    The metric must be named in the sentence itself -- a bare answer ("the guidance of 14% to 15%") belongs to
    the numeric path, which reads its metric from the question -- and a reporting verb, an actual's shape, a
    hedge, a macro forecast or a metric that is not stated in percent keeps the sentence out."""
    if PAST_VERB.search(sentence) or PAST_ONLY.search(sentence) or NO_GUIDANCE.search(sentence):
        stats["worded_past"] += 1
        return None
    move = WORDED_MOVE.search(sentence)
    if not move:
        return None
    if FACT_SHAPE.search(sentence) or HEDGE.search(sentence):
        stats["worded_fact"] += 1
        return None
    if MACRO.search(sentence) and not re.search(
            r"ebitda|revenue|margin|aum|nim|order intake|credit|inflation in cost|cost inflation|cost of production",
            sentence, re.I):
        stats["macro"] += 1
        return None
    named = metric_candidates(symbol, sentence, "", "")
    if not named or "pct" not in METRIC_UNITS.get(named[0], set()) \
            or not METRIC_RX[named[0]].search(sentence):
        stats["worded_no_metric"] += 1
        return None                 # a metric read from context alone is too thin for a row with no number (T-105)
    metric = named[0]
    chosen = {"start": move.start(), "end": move.end(), "low": None, "high": None, "unit": "pct"}
    if not subject_ok(metric, sentence, chosen, "", symbol):
        stats["no_subject"] += 1
        return None
    if metric == "other" and not other_cued(sentence, chosen):
        stats["other_fact"] += 1
        return None
    if metric != "other" and segment_subject(sentence, chosen, symbol):
        stats["other_segment"] += 1
        return None
    period = target_period(sentence, before, "", call_period, docper, move.start())
    if not period:
        stats["no_period"] += 1
        return None
    return (symbol, doc["isin"], metric, period, None, None, "pct", worded_direction(sentence, metric, move.start()),
            (doc["filing_date"] or (doc["known_at"] or "")[:10]), doc["doc_key"], page, quote, speaker,
            doc["known_at"], "doc.known_at", None, _row_rule(sentence, metric, "pct", symbol,
                                                             bool(CUE_V1.search(sentence))))


def _docs(con: sqlite3.Connection, symbol: str):
    return con.execute(
        "SELECT doc_key, doc_type, isin, title, filing_date, known_at FROM doc WHERE symbol=? AND doc_type IN "
        f"({','.join('?' * len(DOC_TYPES))}) ORDER BY COALESCE(known_at, filing_date)", (symbol, *DOC_TYPES)).fetchall()


def _transcript_statements(con: sqlite3.Connection, symbol: str) -> dict[str, list[sqlite3.Row]]:
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='transcript_statement'").fetchone():
        return {}
    out: dict[str, list[sqlite3.Row]] = {}
    for row in con.execute("SELECT doc_key, page, call_period, speaker, role, statement, quote FROM "
                           "transcript_statement WHERE symbol=? ORDER BY doc_key, page, seq", (symbol,)):
        out.setdefault(row["doc_key"], []).append(row)
    return out


def _kpi_crore(value: float | None, unit: str | None) -> float | None:
    """A kpi_series amount in crore (T-166)."""
    if value is None:
        return None
    v = float(value)
    if unit in ("inr_cr", "cr", "crore", "crores"):
        return v
    if unit in ("inr_bn", "bn"):
        return v * 100.0
    if unit == "inr":
        return v / 1e7
    return None


def company_scale_cr(con: sqlite3.Connection, symbol: str) -> float | None:
    """The scale an order-intake target is checked against, in crore (T-166).

    The company's own order-intake KPI series is read first (a target far below the largest intake the company
    ever recorded is a unit slip, never a corridor); without it the annual revenue is used, from the quarterly
    XBRL lines (largest quarter x 4) and then the annual lines.  ``None`` when the store holds no scale, in which
    case the check cannot run and the row is kept."""
    try:
        vals = [_kpi_crore(r[0], r[1]) for r in con.execute(
            "SELECT value, unit FROM kpi_series WHERE symbol=? AND metric='order_intake'", (symbol,))]
        vals = [v for v in vals if v and v > 0]
        if vals:
            return max(vals)
    except sqlite3.Error:
        pass
    try:
        row = con.execute("SELECT MAX(value) FROM fin_quarter_xbrl WHERE symbol=? AND "
                          "line_item='revenue_from_operations' AND unit='inr'", (symbol,)).fetchone()
        if row and row[0]:
            return float(row[0]) * 4 / 1e7
        row = con.execute("SELECT MAX(value) FROM fin_annual_line WHERE symbol=? AND statement='PL' AND "
                          "line_item='revenue_from_operations' AND unit='inr'", (symbol,)).fetchone()
        if row and row[0]:
            return float(row[0]) / 1e7
    except sqlite3.Error:
        pass
    return None


# a participant's "Name:" label on its own line in a transcript page (T-166)
SPEAKER_LABEL = re.compile(r"(?m)^[ \t]*([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,4}):[ \t]*$")
# a sentence that opens with its speaker ("Manoj Jain: Presently, we have guided …"): the splitter kept the
# label on the same line as the text, so the nearest standalone label belongs to the question before it
INLINE_SPEAKER = re.compile(r"^\s*(?:•\s*)?([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,4}):\s*")
# the moderator's introduction of a questioner ("The next question is from the line of Umesh Raut from Nomura"):
# the one reliable analyst mark on a call whose participant block is missing or names everyone "Management".
# The name stops before "from <firm>", so the firm is never part of the person.
ANALYST_INTRO = re.compile(r"\b(?:question (?:is )?(?:comes )?from the line of|line of)\s+"
                           r"([A-Z][A-Za-z.'’\-]+(?: [A-Za-z.'’\-]+){0,2}?)(?=\s+from\b|[.,;:)]|$)", re.I)


def analyst_speakers(texts: list[str]) -> tuple[str, ...]:
    """The speakers the document itself introduces as questioners (T-166)."""
    names: list[str] = []
    for text in texts:
        names.extend(m.group(1) for m in ANALYST_INTRO.finditer(text or ""))
    return tuple(names)


def previous_sentence(before: str) -> str:
    """The sentence immediately before the one being read, from the page text before it (T-166)."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+|•", (before or "").strip()) if p.strip()]
    return parts[-1] if parts else ""


def _clause(text: str, pos: int) -> str:
    """The clause that owns offset ``pos`` (T-166 r4): sentence/bullet separators and a table's own start
    ("FY26 guidance", "Parameter") bound it, so a rating affirmation printed earlier in the same blob does not
    swallow the company's guidance table that follows."""
    starts = [0] + [m.end() for m in CLAUSE_BREAK.finditer(text, 0, pos)] + \
             [m.start() for m in CLAUSE_START.finditer(text, 0, pos)]
    ends = [m.start() for m in CLAUSE_BREAK.finditer(text, pos)] + \
           [m.start() for m in CLAUSE_START.finditer(text, pos)]
    return text[max(starts):min(ends) if ends else len(text)]


def external_forecast(sentence: str, previous: str = "", pos: int | None = None) -> bool:
    """True when the sentence, or ``pos``'s own clause, attributes the number to an outside forecaster.

    A named agency/research house in the same clause always rejects the candidate.  With ``pos`` only that
    number's clause counts (T-166 r4: a rating affirmation earlier on the same page blob is not the number's
    source).  The sentence before it counts only when the candidate's own clause names no company actor and does
    not itself read as a guidance table, so an industry outlook ("ICRA Rating highlighted that NBFC … Growth is
    expected to ease to 13%-15%") is rejected while a rating-affirmation boilerplate followed by the company's
    own "FY26 guidance … Revenue 36,000-38,000 Cr" keeps the target."""
    scope = _clause(sentence, pos) if pos is not None else sentence
    if EXTERNAL_SOURCE.search(scope) or CARE_RATINGS.search(scope) or AS_PER_EXTERNAL.search(scope):
        return True
    if INDUSTRY_FORECAST.search(sentence):
        return True                    # an industry/market forecast owns the sentence's numbers (T-166 r4)
    return not COMPANY_ACTOR.search(scope) and not TABLE_CUE.search(scope) \
        and bool(previous and EXTERNAL_SOURCE.search(previous))


def first_table_amount(cell: str, sentence: str) -> dict | None:
    """The amount a table row label introduces (T-166 r4), or None when the label opens prose instead.

    The amount must sit right beside the label ("Revenue ₹36,000-38,000 Cr", "Capex 12,000 - 14,000", "EBITDA
    (₹ Cr) 25,000 – 26,000"), so "Revenue and EBITDA guidance at ₹36,000-38,000 Cr" yields no row: the words
    between label and amount are not a table cell."""
    for m in TABLE_AMOUNT.finditer(cell):
        gap = cell[:m.start()]
        if not TABLE_GAP.match(gap):
            continue
        lo = _num(m.group("lo"))
        hi = _num(m.group("hi")) if m.group("hi") else lo
        if lo is None or hi is None:
            continue
        unit_word = (m.group("unit") or "").lower()
        pre = m.group("pre") or m.group("pre2") or ""
        has_money = bool(pre or unit_word)
        if not has_money and not TABLE_MONEY.search(sentence):
            continue
        if not has_money and not ("," in m.group("lo") or len(m.group("lo")) >= 5):
            continue                    # a footnote digit or a page number, not an amount
        if not unit_word and pre and TABLE_MONEY.search(sentence):
            unit_word = "crore" if re.search(r"\bCr\b|crores?|\(₹\s*Cr\)", sentence, re.I) else ""
        unit = _money_unit(unit_word, pre)
        if unit in ("inr", "usd") and not pre and not unit_word:
            continue
        low, high = min(lo, hi), max(lo, hi)
        if low <= 0 or high / low > 20:
            continue                    # OCR "18.800-18,900": not a corridor
        return {"start": m.start(), "end": m.end(), "low": low, "high": high, "unit": unit}
    return None


def table_targets(sentence: str) -> list[dict]:
    """Rows of a real guidance table, each number keyed by its own row label (T-166 r4).

    Only a block where at least two of Revenue/EBITDA/Capex each sit beside their own amount, the block names
    guidance/target/parameter, and the sentence names a period is a table.  Prose that merely mentions two of
    those words is not one, and once a sentence is read as a table it is not re-read as a single prose target."""
    marks: list[tuple[int, int, str]] = []
    for name, rx in TABLE_LABELS:
        for m in rx.finditer(sentence):
            if NET_DEBT_RATIO.search(sentence[max(0, m.start() - 24):m.start()]):
                continue
            marks.append((m.start(), m.end(), name))
    marks.sort()
    if len({name for _a, _b, name in marks}) < 2 or not TABLE_CUE.search(sentence):
        return []
    header = re.search(r"\bFY\s*'?\s*(\d{2,4})\s+guidance\b", sentence, re.I)
    if not header:
        return []                      # the block does not name the fiscal year it guides: not a table
    period = f"FY{_yy(header.group(1))}"
    out: list[dict] = []
    for index, (_a, b, name) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(sentence)
        num = first_table_amount(sentence[b:stop], sentence)
        if num is None:
            continue
        out.append({"metric": name, "period": period,
                    "num": {**num, "start": b + num["start"], "end": b + num["end"]}})
    if len(out) < 2 or len({r["metric"] for r in out}) < 2:
        return []
    return out


def past_figure(sentence: str, chosen: dict, speaker: str | None = None,
                analysts: tuple[str, ...] = ()) -> bool:
    """True when the number is a past measurement, not a target (T-166 r4).

    "improved to Rs. 5,400 from Rs. 4,200", "we have spent Rs. 4,200 crores in H1", "had targeted 7,500", "used
    to be around Rs. 20,000", an "achieved 75% of our revised guidance", and the measured value in "capex of Rs
    18,619 crore against target of Rs 16,500 crore" (the target after "against target" is the row) are all
    measurements; none of them removes a target stated in another clause."""
    left = sentence[max(0, chosen["start"] - 70):chosen["start"]]
    window = sentence[chosen["end"]:chosen["end"] + 60]
    if PAST_MOVE_PRE.search(left):
        return True
    if FROM_BASE_PRE.search(left) and PAST_MOVE_VERB.search(sentence[:chosen["start"]]):
        return True
    if HAD_TARGET_PRE.search(left) and not restated_guidance(sentence, chosen, left, speaker, analysts):
        return True
    if AGAINST_TARGET.search(window):
        return True
    move = ACHIEVED_OF_GUIDANCE.search(sentence)
    if move and move.start() <= chosen["start"] <= move.end():
        return True
    if DELTA_POINTS.search(window):
        return True                    # "nearly 10% points lower than …": the size of a move
    return False


def restated_guidance(sentence: str, chosen: dict, left: str, speaker: str | None = None,
                      analysts: tuple[str, ...] = ()) -> bool:
    """True when the past phrase ``left`` restates the company's own guidance, so the number is its target (T-187).

    "EBITDA margin for the full year is trending at a higher end of what we had guided earlier, which was a range
    of 23% to 24%" restates the guided band; "we have guided in the press release that ... we have spent ...
    INR 1,100 crores" restates the guided capex; and "our annual CapEx has used to be for India, INR 1,200-1,300
    crores" states the annual run-rate of the metric.  "2022, we used to be around Rs. 20,000, Rs. 22,000 crores
    of capex" and "we have spent Rs. 4,200 crores in H1" carry no such restatement and stay measurements.

    Tightened (T-187 r2): an analyst turn never qualifies, and the cue must sit in the same clause as the number, so a
    guidance word printed earlier in the page/blob cannot rescue a number in a later clause."""
    if speaker is not None and any(_same_person(speaker, a) for a in (analysts or ())):
        return False
    clause = _clause(sentence, chosen["start"])
    if USED_TO_BE_PRE.search(left):
        return bool(ANNUAL_LEVEL.search(clause))
    if SPENT_PRE.search(left):
        return bool(GUIDE_WORD.search(clause))
    if RESTATED_RANGE_PRE.search(left):
        return bool(GUIDE_WORD.search(clause))
    return False


def page_sentences(raw: str) -> list[tuple[int, int]]:
    """Sentence spans of a page, broken again at bullet markers so a deck's bullets are separate sentences."""
    out: list[tuple[int, int]] = []
    for a, b in split_sentences(raw, 0):
        seg = raw[a:b]
        marks = [m.start() for m in BULLETS.finditer(seg)] + [len(seg)]
        for start, end in zip([0] + marks, marks):
            if seg[start:end].strip():
                out.append((a + start, a + end))
    return out


def extract_sentences(symbol: str, doc: sqlite3.Row, page: int, raw: str, statements: list[sqlite3.Row],
                      stats: dict, mgmt_speakers: tuple[str, ...] = (), doc_has_statements: bool = False,
                      revenue_cr: float | None = None, analysts: tuple[str, ...] = ()) -> list[tuple]:
    """Guidance rows (without revision_of) from one page: transcript statements when held, else split sentences.
    On a transcript page without statements a sentence is kept only when its speaker is not one the document
    itself introduced as a questioner (T-166): an analyst's words are never a company target."""
    collapsed = " ".join(raw.split())
    items: list[tuple[str, str, str | None]] = []      # (sentence, quote, speaker)
    if statements:
        for st in statements:
            if (st["role"] or "").lower() in NON_MGMT_ROLES:
                stats["not_management"] += 1
                continue
            stmt = " ".join((st["statement"] or "").split())
            if stmt:
                items.append((stmt, " ".join((st["quote"] or stmt).split()), st["speaker"]))
    else:
        # T-166 r4: a speaker belongs to a transcript; a deck's slide title ("International Ports", "Solid future
        # outlook", "Capex") sits on its own line with a colon exactly like a speaker label, so it is never read
        # as one.
        is_transcript = (doc["doc_type"] or "") == "transcript"
        last_end, speaker = 0, None
        for a, b in page_sentences(raw):
            s = HEADER_TAIL.sub("", " ".join(raw[a:b].split()))
            if not s:
                last_end = b
                continue
            inline = INLINE_SPEAKER.match(s) if is_transcript else None
            if inline and (len(inline.group(1).split()) >= 2
                           or any(_same_person(inline.group(1), m) for m in mgmt_speakers)):
                speaker, s = inline.group(1), s[inline.end():]
            else:
                # a "Name:" label printed between the previous sentence and this one belongs to this one
                labels = [m.group(1) for m in SPEAKER_LABEL.finditer(raw[last_end:a])] if is_transcript else []
                if labels:
                    speaker = labels[-1]
            last_end = b
            if speaker and any(_same_person(speaker, x) for x in analysts):
                stats["not_management"] += 1
                continue                # the moderator introduced this speaker as a questioner, never management
            items.append((s, s, speaker))
    call_period = statements[0]["call_period"] if statements else None
    docper = doc_period(doc["filing_date"], doc["known_at"])
    # a project spend to date is a true fact beside the total (T-056 family D): the range parser blanks it so it
    # cannot pair with the total, and it gets its own row with the period the sentence names ("end of FY26" -> FY26,
    # "end of Q1FY27" -> Q1FY27, "end of Q3FY26" -> Q3FY26)
    rows = []
    seen_spend: set[tuple] = set()
    for sentence, quote, speaker in items:
        if not 20 < len(sentence) < 500:
            continue
        if EXTERNAL_SOURCE.search(sentence):
            stats["external_forecast"] += 1
            continue                    # a spend sentence naming an outside source is not the company's row (T-166)
        for sp in spends(sentence):
            period = _explicit_period(sentence, sp["start"])
            key = (period, sp["low"], sp["high"], sp["unit"])
            if not period or key in seen_spend:
                continue
            seen_spend.add(key)
            rows.append((symbol, doc["isin"], "project_capital_spent", period, sp["low"], sp["high"], sp["unit"],
                         direction_of(sentence, "project_capital_spent"),
                         (doc["filing_date"] or (doc["known_at"] or "")[:10]), doc["doc_key"], page, quote,
                         speaker, doc["known_at"], "doc.known_at", None, "guidance_cue_v1"))
    for index, (sentence, quote, speaker) in enumerate(items):
        # T-105: the previous management statement supplies a bare metric (transcript statements only: on a deck
        # page the previous block is an unrelated bullet)
        prev = items[index - 1][0] if index and statements else ""
        if len(sentence) < 30 or len(sentence) > 400:
            continue
        if re.search(r"\?[\"'”’)]*$", sentence) and not re.search(
                r"\b(?:okay|ok|right|no|correct|fine)\?[\"'”’)]*$", sentence, re.I):
            stats["question"] += 1
            continue                    # a question is never a target (T-056 family G; "…INR400 crores, okay?" is)
        if GUIDED_ACTUAL.search(sentence) or REPORT_BASIS.search(sentence) or IMPACT_OF_ON.search(sentence):
            stats["guided_actual"] += 1
            continue                    # the result quoted against the guided range, a reporting basis or an
                                        # effect on the metric, never its level (T-056 families C and the review)
        nums = numbers(sentence)
        pos = collapsed.find(sentence)
        before = collapsed[max(0, pos - BEFORE):pos] if pos >= 0 else ""
        after = collapsed[pos + len(sentence):pos + len(sentence) + AFTER] if pos >= 0 else ""
        previous = previous_sentence(before)
        if not nums:
            # a target said in words has no number to read: it gets a row with low/high NULL (T-058)
            if CUE.search(sentence) and not external_forecast(sentence, previous):
                row = worded_row(symbol, doc, page, sentence, quote, speaker, before, call_period, docper, stats)
                if row:
                    rows.append(row)
                    if len(rows) >= MAX_ROWS_PER_PAGE:
                        break
            continue
        # T-166 r4: a real guidance table gives one row per labelled line (revenue 36,000-38,000, EBITDA
        # 21,000-22,000, capex 11,000-12,000); once read as a table the sentence is not re-read as one prose target
        table = table_targets(sentence)
        if table:
            for cell in table:
                if external_forecast(sentence, previous, cell["num"]["start"]):
                    stats["external_forecast"] += 1
                    continue
                period = cell["period"] or target_period(sentence, before, after, call_period, docper,
                                                         cell["num"]["start"])
                if not period:
                    continue
                rows.append((symbol, doc["isin"], cell["metric"], period, cell["num"]["low"], cell["num"]["high"],
                             cell["num"]["unit"], direction_of(sentence, cell["metric"]),
                             (doc["filing_date"] or (doc["known_at"] or "")[:10]), doc["doc_key"], page, quote,
                             speaker, doc["known_at"], "doc.known_at", None, "guidance_table"))
                if len(rows) >= MAX_ROWS_PER_PAGE:
                    break
            continue
        kept = []
        for n in nums:
            if external_forecast(sentence, previous, n["start"]):
                stats["external_forecast"] += 1
                continue            # the number's own clause is an outside forecaster's, not the company's target
            if past_figure(sentence, n, speaker, analysts):
                stats["past_only"] += 1
                continue            # a movement/spend/actual, not a target (T-166 r4)
            kept.append(n)
        nums = kept
        if not nums:
            continue
        if len(nums) > 5:      # a chart axis or a table line laid out as text, not a sentence
            stats["chart_blob"] += 1
            continue
        if EXAMPLE_LIST.search(sentence):     # "some 25 basis points, some 100": examples, not a target (T-058)
            stats["examples"] += 1
            continue
        strong = bool(CUE.search(sentence))
        if not strong:
            # a range answer to a guidance question asked in the 300 characters before it
            question = before[-300:]
            if not (any(n["high"] > n["low"] for n in nums) and CUE.search(question)
                    and metric_candidates(symbol, "", question, "")):
                stats["no_cue"] += 1
                continue
        # would the v1 rules have produced this row? (its cue in the sentence, or the range answer to a guidance
        # question before it) -- T-105 keeps those rows labelled guidance_cue_v1
        v1_found = bool(CUE_V1.search(sentence)) or (any(n["high"] > n["low"] for n in nums)
                                                     and bool(CUE_V1.search(before[-300:]))
                                                     and bool(metric_candidates(symbol, "", before[-300:], "")))
        if PAST_ONLY.search(sentence) and not FORWARD.search(sentence):
            stats["past_only"] += 1
            continue
        if MACRO.search(sentence) and not re.search(
                r"ebitda|revenue|margin|aum|nim|order intake|credit|inflation in cost|cost inflation|cost of production",
                sentence, re.I):
            stats["macro"] += 1
            continue
        chosen = metric = None
        rx_by_name = {name: rx for name, rx, _lo, _hi in METRICS}
        for name in metric_candidates(symbol, sentence, before, after, prev):
            if name == "other" and (not strong or FACT_SHAPE.search(sentence)):
                continue
            if name == "credit_cost" and re.search(r"gnpa|nnpa|\bnpa\b", sentence, re.I) \
                    and not re.search(r"credit cost|loan loss", sentence, re.I):
                continue                    # asset-quality actuals are not the credit-cost target
            options = [n for n in nums if plausible(name, n["low"], n["high"], n["unit"])]
            if name == "ebitda_margin":
                options = [n for n in options if not gross_margin_owns(sentence, n, after)]   # T-187
            marks = [m.start() for m in rx_by_name[name].finditer(sentence)]
            if marks:
                # the metric word is in this sentence: the target is the number it introduces, not a chart blob's
                # (distance from the number's own end, so "a 25 to 40 basis point improvement … on opex-to-NTI"
                # keeps its metric word, T-105)
                near = [n for n in options
                        if any((p <= n["start"] and n["start"] - p <= 150) or (n["start"] < p and p - n["end"] <= 40)
                               for p in marks)]
                if not near:
                    continue
                options = near
            if options:
                metric, chosen = name, pick_number(sentence, options)
                break
        if not chosen:
            stats["no_metric" if not metric_candidates(symbol, sentence, before, after, prev) else "implausible"] += 1
            continue
        rate = RATE_OF.search(sentence)
        if rate and rate.start() <= chosen["start"] <= rate.end():
            stats["rate_not_target"] += 1
            continue                        # the number is the rate of a tariff/duty, not a target
        if HEDGE.search(sentence[chosen["start"]:chosen["start"] + 90]):
            stats["hedge"] += 1
            continue                        # "whether it will be 25 or 50 basis points, difficult to quantify"
        if not subject_ok(metric or "other", sentence, chosen, before, symbol, prev):
            stats["no_subject"] += 1
            continue                        # the metric is not the target's subject (a share, net debt, growth)
        cues = [m.start() for m in CUE.finditer(sentence)]
        if (PAST_ONLY.search(sentence) or REMAINS_AT.search(sentence)) and cues \
                and chosen["start"] < min(cues):
            stats["past_only"] += 1
            continue                        # the number is the measurement, the forward part has no number
        if PAST_ONLY.search(sentence) and not OWN_PERIOD.search(sentence):
            stats["past_only"] += 1
            continue                        # "last year would be 7.5%": a measurement, not a target period
        if metric == "credit_cost" and re.search(r"\b(?:g|n)npa\b", sentence[max(0, chosen["start"] - 40):chosen["start"]],
                                                 re.I):
            stats["asset_quality"] += 1
            continue                    # "GNPA came in at 1.01%" is an actual, not the credit-cost target
        if metric == "other" and (FACT_SHAPE.search(sentence) or "market share" in sentence.lower()
                                  or not other_cued(sentence, chosen)
                                  # T-062: a list of labelled percentages is a customer/business mix, not a target
                                  # ("salaried is about 40%, business would be about 34%, self-employed about 20%"),
                                  # while a target stated in words ("in the 70s") or a single number is kept
                                  or (not OTHER_TARGET.search(sentence)
                                      and sum(1 for n in nums if n["unit"] == "pct") >= 2)):
            stats["other_fact"] += 1
            continue
        if metric != "other" and segment_subject(sentence, chosen, symbol):
            stats["other_segment"] += 1
            continue                    # a segment's or business's number is not the company's metric
        if chosen["unit"] == "inr" and metric in ("order_intake", "capex", "project_capital_cost", "interest_cost") \
                and chosen["high"] >= 100:
            chosen = {**chosen, "unit": "inr_cr"}   # "INR9,000-INR10,000" in a crore-scale business is crore
        if metric == "ebitda_margin" and chosen["high"] - chosen["low"] > 5:
            clause = _clause(sentence, chosen["start"])
            mgmt_subject = bool(re.search(r"\b(?:we|our|the company)\b", clause, re.I))
            mgmt_speaker = speaker is None or not any(_same_person(speaker, a) for a in (analysts or ()))
            if not (VARIABILITY.search(sentence) and mgmt_subject and mgmt_speaker):
                stats["wide_margin"] += 1
                continue            # a plain wide margin range is a band, not a target (T-166); a band of variability
                                    # the company states itself is its target band (T-187)
        if metric == "order_intake" and revenue_cr:
            in_crore = chosen["high"] if chosen["unit"] == "inr_cr" else \
                chosen["high"] / 1e7 if chosen["unit"] == "inr" else None
            if in_crore is not None and in_crore < 0.01 * revenue_cr:
                stats["order_intake_scale"] += 1
                continue                # "INR120-plus million" read as 120 crore: far below its own order book (T-166)
        period = target_period(sentence, before, after, call_period, docper, chosen["start"])
        if not period:
            stats["no_period"] += 1
            continue
        if metric == "ebitda_per_tonne" and chosen["unit"] in ("usd", "inr"):
            chosen = {**chosen, "unit": "usd_per_t" if chosen["unit"] == "usd" else "inr_per_t"}
        rows.append((symbol, doc["isin"], metric, period, chosen["low"], chosen["high"], chosen["unit"],
                     direction_of(sentence, metric or "other"), (doc["filing_date"] or (doc["known_at"] or "")[:10]),
                     doc["doc_key"], page, quote, speaker, doc["known_at"], "doc.known_at",
                     None, _row_rule(sentence, metric or "other", chosen["unit"], symbol, v1_found)))
        if len(rows) >= MAX_ROWS_PER_PAGE:
            break
    return rows


def run(out: str, symbols: list[str], limit_docs: int | None = None) -> dict:
    t0 = time.time()
    con = sqlite3.connect(out)
    con.row_factory = sqlite3.Row
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='guidance'").fetchone():
        con.execute(TABLES["guidance"])
    con.executescript(";".join(GUIDANCE_INDEXES))
    stats_all: dict = {}
    ins = f"INSERT INTO guidance({','.join(COLS)}) VALUES({','.join('?' * len(COLS))})"
    for symbol in symbols:
        con.execute("DELETE FROM guidance WHERE symbol=?", (symbol,))
        st = stats_all[symbol] = Counter()
        statements = _transcript_statements(con, symbol)
        revenue_cr = company_scale_cr(con, symbol)
        # one row per (metric, period, value, unit, said_on) for the whole run: the BSE/NSE copies and the several
        # pages of one document collapse onto the first one (documents are read in known_at order, pages ascending,
        # so that is the earliest knowledge and the lowest page); a later call has its own said_on, so a
        # restatement is kept for `revisions` (T-056 family I).  A duplicate from a statement row names its
        # speaker ("Management", the MD), so it fills a speaker the first copy could not identify (T-166 r4).
        seen: dict[tuple, int] = {}
        for index, doc in enumerate(_docs(con, symbol)):
            if limit_docs is not None and index >= limit_docs:
                break
            doc_rows = statements.get(doc["doc_key"], [])
            by_page: dict[int, list[sqlite3.Row]] = {}
            for row in doc_rows:
                by_page.setdefault(row["page"], []).append(row)
            mgmt_speakers = tuple({r["speaker"] for r in doc_rows
                                   if (r["role"] or "").lower() not in NON_MGMT_ROLES})
            pages = con.execute("SELECT page, text FROM doc_page WHERE doc_key=? ORDER BY page",
                                (doc["doc_key"],)).fetchall()
            analysts = analyst_speakers([text for _page, text in pages])
            for page, text in pages:
                if not (text or "").strip():
                    continue
                st["pages"] += 1
                for row in extract_sentences(symbol, doc, page, text, by_page.get(page, []), st,
                                             mgmt_speakers, bool(doc_rows), revenue_cr, analysts):
                    sig = (row[0], row[2], row[3], row[4], row[5], row[6], row[8])
                    if sig in seen:
                        st["duplicate"] += 1
                        if row[12]:
                            kept = con.execute("SELECT speaker FROM guidance WHERE id=?", (seen[sig],)).fetchone()
                            if kept and not kept[0]:
                                con.execute("UPDATE guidance SET speaker=? WHERE id=?", (row[12], seen[sig]))
                                st["speaker_recovered"] += 1
                        continue
                    cur = con.execute(ins, row)
                    seen[sig] = int(cur.lastrowid or 0)
                    st["rows"] += 1
                    st[row[2]] += 1
        con.commit()
        revs = revisions(con, symbol)
        st["revisions"] = revs
        stats_all[symbol] = {k: v for k, v in st.items() if not isinstance(v, Counter)}
    stats_all["seconds"] = round(time.time() - t0, 1)
    stats_all["rows"] = dict(con.execute("SELECT symbol, COUNT(*) FROM guidance GROUP BY symbol"))
    con.close()
    return stats_all


def revisions(con: sqlite3.Connection, symbol: str) -> int:
    """Link every row to the previous row of the same metric+period from an earlier document."""
    rows = con.execute("SELECT id, metric, target_period, doc_key FROM guidance WHERE symbol=? "
                       "ORDER BY COALESCE(known_at, said_on), said_on, id", (symbol,)).fetchall()
    prev: dict[tuple, tuple[int, str]] = {}
    linked = 0
    for row in rows:
        key = (row[1], row[2])
        old = prev.get(key)
        if old and old[1] != row[3]:
            con.execute("UPDATE guidance SET revision_of=? WHERE id=?", (old[0], row[0]))
            linked += 1
        prev[key] = (row[0], row[3])
    con.commit()
    return linked


def current_rows(rows: list[dict]) -> list[dict]:
    """The rows still current per (metric, target_period) (T-105).

    A row is superseded when another row of the same metric and target period comes from a different document
    whose ``known_at`` (or filing day) is later; the caller passes rows already cut at ``as_of`` and ordered
    newest first, so a row the decision day could not know never supersedes anything.  Every row of the newest
    document is kept (a call can give two targets for the same metric and period), and each kept row carries
    ``superseded_rows`` = how many older rows this view drops."""
    def when(r: dict) -> str:
        return r.get("known_at") or r.get("said_on") or ""

    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["metric"], r["target_period"]), []).append(r)
    newest = {key: max(when(r) for r in group) for key, group in groups.items()}
    dropped = {key: sum(1 for r in group if when(r) != newest[key]) for key, group in groups.items()}
    out: list[dict] = []
    for r in rows:
        key = (r["metric"], r["target_period"])
        if when(r) == newest[key]:
            r["superseded_rows"] = dropped[key]
            out.append(r)
    return out


def print_sample(db: str, n: int, seed: int = 7) -> list[sqlite3.Row]:
    """A random sample of the stored rows with the sentence each was read from, for a hand check."""
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM guidance ORDER BY id").fetchall()
    finally:
        con.close()
    picked = random.Random(seed).sample(rows, min(n, len(rows)))
    for i, r in enumerate(picked, 1):
        print(f"{i:2d}. {r['symbol']:11s} {r['metric']:18s} {r['target_period'] or '-':7s} "
              f"{r['low']:g}-{r['high']:g} {r['unit']:10s} {r['said_on'] or '-':10s} {r['doc_key']} p{r['page']}")
        print(f"    {r['quote']}")
    print(f"\n{len(picked)} of {len(rows)} guidance rows, seed {seed}")
    return picked


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None, help="default: every company of the profile, else every pilot3 company")
    ap.add_argument("--profile", default=None, help="build profile JSON (T-056): companies, pages db, raw root, output")
    ap.add_argument("--limit-docs", type=int, default=None)
    ap.add_argument("--sample", type=int, default=0, help="print N random rows with their sentence and stop")
    ap.add_argument("--seed", type=int, default=7)
    a = ap.parse_args(argv)
    if a.sample:
        print_sample(a.out, a.sample, a.seed)
        return 0
    if a.profile:
        profile.activate(profile.load(a.profile))
    symbols = [s.strip().upper() for s in (a.symbols or ",".join(profile.symbols())).split(",") if s.strip()]
    stats = run(a.out, symbols, a.limit_docs)
    print(json.dumps(stats, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
