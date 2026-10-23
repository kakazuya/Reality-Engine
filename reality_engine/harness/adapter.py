"""Schema-checked adapter for the sole authorized dated snapshot.

Only SELECTs are executed. All large transformations remain in memory.
Quarter values are validated against quarter/OneD facts. No latest-row
selection, active-name filter, or filing.isin join is permitted here.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
import numpy as np
import pandas as pd

from .data import Calendar, as_date
from .costs_tax import TaxRules
from .cards.h01_pead import parse_period_end, pit_trigger, quarter_back, select_basis
from .benchmark import INDEX_NAMES


REQUIRED = {
    "results_key": {"file", "period_start", "period_end", "consolidated", "taxonomy",
                    "ProfitLossForPeriod", "RevenueFromOperations", "InterestEarned"},
    "results_filings": {"file", "trading_isin", "known_at_utc", "same_issuer", "status"},
    "results_facts": {"file", "concept", "context", "period_kind", "value", "unit"},
    "bse_ann": {"SCRIP_CD", "NEWSSUB", "DissemDT", "SUBCATNAME"},
    "security_master": {"isin", "issuer", "bse_code", "bse_status", "segment"},
    "px_daily": {"date", "entity_id", "isin", "exch", "value_inr", "adj_open",
                 "adj_close", "cum_div_factor", "tr_close"},
    "px_nse": {"date", "entity_id", "isin", "close"},
    "px_bse": {"date", "entity_id", "isin", "close"},
    "index_tri": {"index_name", "date", "tri", "method"},
    "tax_rules": {"rule", "value", "effective_from", "effective_to"},
    "symbol_isin_history": {"exchange", "symbol", "isin", "first_date", "last_date"},
    "snapshot_meta": {"snapshot_date"}, "truth_report": {"report_json"},
    "unexplained_jumps": {"entity_id", "date", "clean_ratio"},
}


def inspect(connection):
    schemas = {}
    for table, required in REQUIRED.items():
        rows = connection.execute(f'DESCRIBE "{table}"').fetchall()
        schemas[table] = {r[0]: r[1] for r in rows}
        missing = required - schemas[table].keys()
        if missing:
            raise ValueError(f"{table}: missing required columns {sorted(missing)}")
    return schemas


def load_tax(connection):
    rows = connection.execute("SELECT rule, value, effective_from, effective_to FROM tax_rules").fetchall()
    intervals = [{"rule": "ltcg_exempt" if name == "ltcg_exemption_inr" else name,
                  "value": value, "start": start, "end": end}
                 for name, value, start, end in rows]
    return TaxRules(intervals)


def load_indexes(connection):
    aliases = {n.upper(): n for n in INDEX_NAMES}
    series = {name: {} for name in INDEX_NAMES}
    for name, day, tri, method in connection.execute(
            "SELECT index_name,date,tri,method FROM index_tri WHERE date<='2025-12-31'").fetchall():
        if name.upper() in aliases:
            series[aliases[name.upper()]][as_date(day)] = (tri, method)
    return series


class Panel:
    """Dense session x issuer matrices, retaining actual ISINs at every date.

    As in the diffusion study, liquidity is lagged and missing cells remain
    NaN. The universe and holding history are never today's survivor list.
    """
    def __init__(self, connection, threshold=5_000_000.):
        self.threshold = threshold
        dates = [r[0] for r in connection.execute("""
            SELECT DISTINCT cast(date AS DATE) FROM index_tri
            WHERE index_name='NIFTY 50' AND date BETWEEN '2019-01-01' AND '2025-12-31'
            ORDER BY 1""").fetchall()]
        self.calendar = Calendar.normal_sessions(dates)
        excluded_sessions = sorted(set(map(as_date, dates)) - set(self.calendar.days))
        self.days = np.array(self.calendar.days, dtype='datetime64[D]')
        self.entities = [r[0] for r in connection.execute("""
            SELECT DISTINCT p.entity_id FROM px_daily p JOIN security_master s ON p.isin=s.isin
            WHERE p.date BETWEEN '2019-01-01' AND '2025-12-31' ORDER BY 1""").fetchall()]
        self.col = {e: j for j, e in enumerate(self.entities)}
        frame = connection.execute("""
            WITH raw AS (
              SELECT 'NSE' AS exch,entity_id,isin,date,close FROM px_nse
              WHERE date BETWEEN '2019-01-01' AND '2025-12-31'
              UNION ALL
              SELECT 'BSE',entity_id,isin,date,close FROM px_bse
              WHERE date BETWEEN '2019-01-01' AND '2025-12-31'
            ), unique_raw AS (
              SELECT exch,entity_id,isin,date,
                     CASE WHEN count(*)=1 THEN min(close) END AS raw_close
              FROM raw GROUP BY ALL
            )
            SELECT p.entity_id,p.date,p.isin,p.value_inr,
                   p.adj_open*p.cum_div_factor AS tr_open,p.tr_close,r.raw_close,
                   p.adj_open AS adj_open,
                   p.adj_close/NULLIF(p.close,0) AS price_factor
            FROM px_daily p JOIN security_master s ON p.isin=s.isin
            LEFT JOIN unique_raw r ON p.exch=r.exch AND p.entity_id=r.entity_id
              AND p.isin=r.isin AND p.date=r.date
            WHERE p.date BETWEEN '2019-01-01' AND '2025-12-31'
            ORDER BY p.entity_id,p.date
        """).df()
        if frame.duplicated(['entity_id', 'date']).any():
            raise ValueError('Ambiguous primary issuer/session price')
        ti = pd.Index(self.days).get_indexer(frame.date.to_numpy(dtype='datetime64[D]'))
        sj = frame.entity_id.map(self.col).to_numpy()
        keep = ti >= 0
        ti, sj, frame = ti[keep], sj[keep], frame.loc[keep]
        shape = (len(self.days), len(self.entities))
        def matrix(column):
            out = np.full(shape, np.nan)
            out[ti, sj] = frame[column].to_numpy()
            return out
        self.open = matrix('tr_open')
        self.close = matrix('tr_close')
        self.raw = matrix('raw_close')
        self.adj_open = matrix('adj_open')
        self.price_factor = matrix('price_factor')
        values = matrix('value_inr')
        self.median20 = pd.DataFrame(values).rolling(20, min_periods=20).median().shift(1).to_numpy()
        self.adtv20 = pd.DataFrame(values).rolling(20, min_periods=20).mean().shift(1).to_numpy()
        self.isins = sorted(frame['isin'].unique())
        codes = {s: i for i, s in enumerate(self.isins)}
        self.isin_code = np.full(shape, -1, dtype=np.int16)
        self.isin_code[ti, sj] = frame['isin'].map(codes).to_numpy(dtype=np.int16)
        tables = {r[0] for r in connection.execute('SHOW TABLES').fetchall()}
        self.quarantine = set()
        if 'substrate_quarantine' in tables:
            cols = {r[0] for r in connection.execute('DESCRIBE substrate_quarantine').fetchall()}
            if 'isin' not in cols:
                raise ValueError('Quarantine exists but cannot resolve its keys safely')
            self.quarantine = {r[0] for r in connection.execute('SELECT isin FROM substrate_quarantine').fetchall()}
        self.u1 = np.isfinite(self.raw) & (self.raw >= 10) & (self.median20 >= threshold)
        if self.quarantine:
            bad = np.array([isin in self.quarantine for isin in self.isins])
            self.u1 &= ~bad[np.maximum(self.isin_code, 0)]
        self.jump = np.zeros(shape, dtype=np.int16)
        for e, day in connection.execute(
                "SELECT entity_id,cast(date AS DATE) FROM unexplained_jumps WHERE date<'2026-01-01'").fetchall():
            i = np.searchsorted(self.days, np.datetime64(day))
            if e in self.col and i < len(self.days) and self.days[i] == np.datetime64(day):
                self.jump[i, self.col[e]] = 1
        self.jump_prefix = np.vstack([np.zeros((1, shape[1]), dtype=np.int16),
                                      np.cumsum(self.jump, axis=0, dtype=np.int16)])
        self.audit = {'price_rows': len(frame), 'issuer_count': len(self.entities),
                      'raw_missing_or_ambiguous': int(np.isnan(self.raw[ti, sj]).sum()),
                      'quarantine_table_present': 'substrate_quarantine' in tables,
                      'quarantine_keys': len(self.quarantine), 'has_open': True,
                      'calendar_method': 'Nifty 50 dates, weekdays only; special weekend sessions omitted',
                      'excluded_special_sessions': excluded_sessions}

    def signal_indices(self, triggers):
        stamps = np.array(triggers, dtype='datetime64[us]')
        day = stamps.astype('datetime64[D]')
        # Raw same-day close is not yet public before 15:30 IST.
        before_close = (stamps - day).astype('timedelta64[s]').astype(np.int64) < 15*3600+30*60
        i = np.searchsorted(self.days, day, side='right') - 1
        exact = self.days[np.clip(i, 0, len(self.days)-1)] == day
        return i - (before_close & exact)

    def entry_indices(self, triggers):
        return np.searchsorted(self.days, np.array(triggers, dtype='datetime64[D]'), side='right')

    def actual_isin(self, i, j):
        code = self.isin_code[i, j]
        return self.isins[code] if code >= 0 else None


class Quotes:
    def __init__(self, panel):
        self.panel = panel

    def get(self, key, default=None):
        entity, day = key
        p = self.panel
        if entity not in p.col:
            return default
        i = np.searchsorted(p.days, np.datetime64(day))
        if i >= len(p.days) or p.days[i] != np.datetime64(day):
            return default
        j = p.col[entity]
        return {'open': p.open[i,j], 'close': p.close[i,j]}


class ADTV:
    def __init__(self, panel):
        self.panel = panel

    def get(self, key, default=0.):
        entity, day = key
        p = self.panel
        if entity not in p.col:
            return default
        i = np.searchsorted(p.days, np.datetime64(day))
        if i >= len(p.days) or p.days[i] != np.datetime64(day):
            return default
        v = p.adtv20[i,p.col[entity]]
        return float(v) if np.isfinite(v) else default


def load_filings(connection):
    """First XBRL per issuer/period/basis, never a later revised file.

    Warm-up/history can use an XBRL's own dissemination when BSE is absent.
    A trade itself ALWAYS requires a BSE Financial Results trigger. Data
    availability is the later of its BSE trigger and its actual XBRL time.
    """
    audit = Counter()
    master = connection.execute('SELECT isin,issuer,bse_code FROM security_master').fetchall()
    isin_issuer = {i: e for i,e,_ in master}
    codes = defaultdict(set)
    for _, e, code in master:
        if code:
            codes[str(code)].add(e)
    ann = defaultdict(list)
    for code, subject, stamp in connection.execute("""
            SELECT SCRIP_CD,NEWSSUB,DissemDT FROM bse_ann
            WHERE SUBCATNAME='Financial Results' AND DissemDT IS NOT NULL
            AND DissemDT<'2026-01-01'""").fetchall():
        mapped = codes.get(str(code), set())
        if len(mapped) != 1:
            audit['ann_ambiguous_or_unmapped_code'] += 1
            continue
        try:
            stamp = datetime.fromisoformat(stamp).replace(tzinfo=None)
        except (ValueError, TypeError):
            audit['ann_timestamp_unparsed'] += 1
            continue
        ann[next(iter(mapped))].append({'subcategory': 'Financial Results',
                                       'subject': subject, 'disseminated_at': stamp})
    # DESCRIBE was completed before these joins were authored/executed.
    frame = connection.execute("""
        WITH facts AS (
          SELECT file,
            max(CASE WHEN concept='ProfitLossForPeriod' THEN value END) AS pat_fact,
            count(*) FILTER(WHERE concept='ProfitLossForPeriod') AS pat_count,
            max(CASE WHEN concept='RevenueFromOperations' THEN value END) AS rev_fact,
            count(*) FILTER(WHERE concept='RevenueFromOperations') AS rev_count,
            max(CASE WHEN concept='InterestEarned' THEN value END) AS interest_fact,
            count(*) FILTER(WHERE concept='InterestEarned') AS interest_count
          FROM results_facts WHERE context='OneD' AND period_kind='quarter' AND unit='INR'
            AND concept IN ('ProfitLossForPeriod','RevenueFromOperations','InterestEarned')
          GROUP BY file
        )
        SELECT k.file,f.trading_isin,k.symbol,k.taxonomy,k.consolidated,
          k.period_start,k.period_end,k.ProfitLossForPeriod,k.RevenueFromOperations,
          k.InterestEarned,f.known_at_utc,x.pat_fact,x.pat_count,x.rev_fact,x.rev_count,
          x.interest_fact,x.interest_count
        FROM results_key k JOIN results_filings f ON k.file=f.file
        LEFT JOIN facts x ON k.file=x.file
        WHERE k.period_end BETWEEN '2019-01-01' AND '2025-12-31'
          AND f.known_at_utc<'2026-01-01' AND f.same_issuer=1 AND f.status='ok'
        ORDER BY f.known_at_utc,k.file
    """).fetchall()
    selected = {}
    bank_seen = set()
    for (file, isin, symbol, taxonomy, basis, start, end, pat, revenue, interest,
         known, pf, pc, rf, rc, inf, inc) in frame:
        audit['joined_quarter_candidates'] += 1
        if isin not in isin_issuer:
            audit['unmapped_filing_isin'] += 1
            continue
        entity = isin_issuer[isin]
        if taxonomy == 'BANKING':
            bank_seen.add(entity)
        q = as_date(end)
        if quarter_back(q,0) is None or not start or not 80 <= (q-as_date(start)).days <= 100:
            audit['non_quarter_duration'] += 1
            continue
        if pat is None or pc != 1 or pf != pat or not math.isfinite(pat):
            audit['missing_or_unvalidated_pat'] += 1
            pat = None
        key = entity,q,basis
        if key in selected:
            audit['later_duplicate_or_revision_discarded'] += 1
            continue
        is_bank = entity in bank_seen
        if is_bank and taxonomy != 'BANKING':
            audit['bank_classification_carried_from_prior_filing'] += 1
        rev_metric = 'InterestEarned' if is_bank else 'RevenueFromOperations'
        rev, fact, count = (interest,inf,inc) if is_bank else (revenue,rf,rc)
        if rev is None or count != 1 or fact != rev or not math.isfinite(rev):
            rev = None
        known_ist = known + timedelta(hours=5, minutes=30)
        selected[key] = {'entity': entity, 'period_end': q, 'basis': basis,
                         'basis_family': 'Consolidated' if basis == 'Consolidated' else 'Standalone',
                         'PAT': pat, 'revenue': rev, 'revenue_metric': rev_metric,
                         'file': file, 'trading_isin': isin, 'symbol': symbol,
                         'xbrl_at': known_ist}
    periods = defaultdict(list)
    for row in selected.values():
        periods[row['entity'],row['period_end']].append(row)
    rows = []
    for (entity,q), candidates in sorted(periods.items()):
        preferred = select_basis(candidates)
        if len(preferred) != 1:
            audit['ambiguous_basis'] += 1
            continue
        row = dict(preferred[0])
        trigger, method = pit_trigger(q, ann.get(entity, []))
        row['trade_trigger'] = trigger
        row['trigger'] = trigger or row['xbrl_at']  # history-only if BSE absent
        row['trigger_method'] = method
        row['available_at'] = max(row['trigger'], row['xbrl_at'])
        audit['basis_'+row['basis']] += 1
        audit['trigger_'+method] += 1
        rows.append(row)
    audit['normalized_periods'] = len(rows)
    return rows, dict(audit)
