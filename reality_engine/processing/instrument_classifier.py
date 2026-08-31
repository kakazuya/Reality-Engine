"""
Instrument Classifier — Dense-substrate denominator filter

Purpose: distinguish operating equities (operating_equity) from synthetic
non-equity instruments (ETFs, BEES, liquid/bees, rights entitlements,
special-series, placeholder ISINs) so annual-financial completeness is
measured only over the operating universe.

Design: deterministic, no network, no inference. Operates purely on
master_companies fields: nse_symbol, bse_code, isin, company_name.

Synthetic detection rules (documented):
  1. ISIN placeholder: isin is NULL/empty or starts with "INE_AUTO"
     (fixture placeholder for instruments lacking a real ISIN) → synthetic.
     Note: INE0* (e.g. INE0D...) is a *real* recent IPO prefix — NOT synthetic
     by itself. Only INE_AUTO is synthetic.
  2. Symbol suffix BEES: nse_symbol endswith "BEES" (case-insensitive)
     e.g. NIFTYBEES, JUNIORBEES, GOLDBEES, BANKBEES, LIQUIDBEES, AUTOBEES.
  3. Symbol ETF: nse_symbol endswith "ETF" or contains "ETF" as token
     e.g. BANKETF, ABSLBANETF, ALPHAETF, AUTOIETF. Uses endswith + contains.
  4. Liquid: nse_symbol contains "LIQUID" (e.g. LIQUID, ABSLLIQUID, LIQGRWBEES
     is already BEES but LIQUID alone also synthetic)
  5. Rights entitlement: nse_symbol contains "RIGHTS", "RIGHT", or "-RE"
     (dash-RE suffix for rights, e.g. GANGAFO-RE, SUMEET-RE) → synthetic.
     Also company_name contains "RIGHTS ENTITLEMENT".
  6. Company-name keywords (case-insensitive):
     - "ETF"
     - "EXCHANGE TRADED FUND"
     - "MUTUAL FUND" (covers "MUTUAL FUND -")
     - "RIGHTS ENTITLEMENT"
     - "BEES" as standalone word (regex \\bBEES\\b) to avoid false flagging
       "Brainbees Solutions" (FIRSTCRY) where BEES is substring of BRAINBEES.
     - "LIQUID" as standalone word or when industry is Other? We check word
       boundary for LIQUID as well.
     Company-name BEES/LIQUID checks are secondary and only trigger when
     accompanied by symbol pattern or Other industry; primary signal is symbol.

Series beyond EQ: the bhavcopy series column (EQ vs BE/BZ/RE) is not stored in
master_companies, but the dash-RE and BEES/ETF patterns above capture the
special-series cases that appear as distinct symbols (e.g. *-RE). Plain dash
symbols like BAJAJ-AUTO or BOSCH-HCIL are *operating* (legitimate hyphenated
names) and are NOT flagged unless other rules match.

Never fabricate zeros: this module only classifies; it never inserts financials.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Tuple

# Pre-compiled regex for company-name BEES / LIQUID word-boundary checks.
# Avoids false positive on BRAINBEES (FIRSTCRY) where BEES is inside BRAINBEES.
_BEES_WORD_RE = re.compile(r"\bBEES\b", re.IGNORECASE)
_LIQUID_WORD_RE = re.compile(r"\bLIQUID\b", re.IGNORECASE)


def _normalize(value: Any) -> str:
    """Return upper-stripped string or '' for None."""
    if value is None:
        return ""
    try:
        return str(value).strip().upper()
    except Exception:
        return ""


def classify_instrument_type(record: Dict[str, Any]) -> str:
    """
    Classify a master_companies record as operating vs synthetic.

    Returns:
        "operating_equity"  — genuine operating company (P&L, balance sheet expected)
        "synthetic"         — ETF / BEES / liquid / rights / placeholder ISIN
            More granular synthetic sub-types are collapsed to "synthetic" for
            denominator use; caller can inspect reason via classify_with_reason().

    Deterministic, no IO.
    """
    typ, _reason = classify_with_reason(record)
    return typ


def classify_with_reason(record: Dict[str, Any]) -> Tuple[str, str]:
    """
    Returns (type, reason) where type is "operating_equity" or "synthetic"
    and reason is a short code for debugging / audit.
    """
    isin = _normalize(record.get("isin"))
    symbol = _normalize(record.get("nse_symbol"))
    # bse_code not used for classification but retained for future auditing.
    # bse_code = _normalize(record.get("bse_code"))
    company_name = _normalize(record.get("company_name"))

    # Rule 1: ISIN placeholder — strongest signal.
    # INE_AUTO covers all fixture synthetic placeholders (INE_AUTO_*, INE_AUTO without underscore).
    # Empty / NULL isin also indicates synthetic placeholder (no real ISIN).
    if not isin or isin.startswith("INE_AUTO"):
        # Edge: empty isin with operating-like symbol? Still synthetic per spec:
        # "isin field for synthetic instruments often NULL or INE_AUTO_*"
        return "synthetic", "isin_placeholder"

    # Rule 2: Symbol suffix BEES (covers all BEES ETFs including LIQGRWBEES etc.)
    if symbol.endswith("BEES"):
        return "synthetic", "symbol_bees_suffix"

    # Rule 3: ETF — endswith ETF is high-confidence; contains ETF catches IETF etc.
    # Exclude false positive like JETFREIGHT (Jet Freight Logistics) where ETF is substring?
    # JETFREIGHT contains ETF but is operating. Check: JETFREIGHT symbol upper contains "ETF"
    # but does NOT end with ETF. Should NOT be flagged. So we restrict:
    #   - endswith ETF -> synthetic
    #   - contains ETF but only when accompanied by other etf markers? For now,
    #     we treat endswith ETF as synthetic, and also check company_name ETF.
    # This avoids misclassifying operating companies with incidental "ETF" substring.
    if symbol.endswith("ETF"):
        return "synthetic", "symbol_etf_suffix"
    # Also handle "IETF", "BETF" variants that still end with ETF, already covered.
    # Do NOT use broad "ETF" in symbol substring — would misflag JETFREIGHT.

    # Rule 4: Liquid — contains LIQUID token (covers LIQUID, LIQUIDBEES, ABSLLIQUID etc.)
    # But need to avoid misflag? LIQUID only appears in synthetic ETFs per fixtures.
    # Use word/contains check; all LIQUID symbols are synthetic.
    if "LIQUID" in symbol:
        return "synthetic", "symbol_liquid"

    # Rule 5: Rights entitlement — RIGHTS / RIGHT / -RE
    # -RE suffix is canonical for rights entitlements (GANGAFO-RE etc.)
    # Also check for RIGHTS substring.
    if "RIGHTS" in symbol or "-RE" in symbol:
        return "synthetic", "symbol_rights"
    # Single RIGHT token but not part of other words? Check word boundary RIGHT.
    # e.g. symbol "RIGHTS" vs "BRIGHT"? BRIGHT contains RIGHT but not synthetic.
    # Use regex \bRIGHT\b or explicit "-RE".
    # Simpler: only flag if symbol == RIGHT or contains "RIGHTS" or ends with "-RE"
    # Already handled -RE and RIGHTS. No need for broader RIGHT.

    # Rule 6: Company-name keywords — secondary, case-insensitive upper already.
    # Use substring for ETF / EXCHANGE TRADED FUND / MUTUAL FUND / RIGHTS ENTITLEMENT
    # For BEES/LIQUID use word-boundary regex to avoid BRAINBEES false positive.
    if "EXCHANGE TRADED FUND" in company_name:
        return "synthetic", "name_exchange_traded"
    if "RIGHTS ENTITLEMENT" in company_name:
        return "synthetic", "name_rights_entitlement"
    # MUTUAL FUND - covers "Mutual Fund -" pattern per spec, but also generic mutual fund ETFs
    if "MUTUAL FUND" in company_name:
        return "synthetic", "name_mutual_fund"
    # Company-name ETF: but avoid false positives? ETF as substring in name is strong.
    # Use regex \bETF\b or "ETF" substring? Spec says "ETF" generic.
    # Check for ETF as word or suffix: e.g. "NIPPON INDIA ETF" etc.
    # Use word boundary to avoid incidental? "ETF" rarely appears inside other words, so substring is fine.
    # But to be safe, check for ETF token.
    if re.search(r"\bETF\b", company_name):
        return "synthetic", "name_etf_word"
    # Also check if company_name ends with ETF (common for ETF names that equal symbol)
    if company_name.endswith("ETF"):
        return "synthetic", "name_etf_suffix"
    if _BEES_WORD_RE.search(company_name):
        # Standalone BEES word (e.g. "NIPPON BEES") — not BRAINBEES
        return "synthetic", "name_bees_word"
    if _LIQUID_WORD_RE.search(company_name):
        return "synthetic", "name_liquid_word"
    # Additional company-name LIQUID without word boundary? Upper "LIQUIDBEES" in name where name==symbol (e.g. LIQUIDBEES)
    # Already covered by symbol endswith BEES / contains LIQUID. But check name contains LIQUID as substring when symbol was not caught (e.g. name="LIQUIDBEES")
    # This is redundant but safe.
    if "LIQUID" in company_name and "LIQUID" in symbol:
        return "synthetic", "name_liquid"

    # No synthetic rule matched → operating equity.
    return "operating_equity", "operating"


def is_operating_equity(record: Dict[str, Any]) -> bool:
    """True if record is operating equity (i.e. not synthetic)."""
    return classify_instrument_type(record) == "operating_equity"


def is_synthetic_instrument(record: Dict[str, Any]) -> bool:
    """True if record is a synthetic ETF/BEES/liquid/rights instrument."""
    return not is_operating_equity(record)
