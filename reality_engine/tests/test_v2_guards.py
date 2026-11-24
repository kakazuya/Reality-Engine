"""T-241: the five v2 transcript number guards (Wolf's fy27_v2 ckpt_0001 grade) and --reparse from page_reply."""
from __future__ import annotations

import sqlite3

from reality_engine.v2 import observations as obs

DOC = "D:/x/concall_transcript/abc.pdf"


def _rows(page_text, reply, page=4, v2=True):
    return obs.build_observations(symbol="BESTAGRO", doc_key=DOC, page=page, known_at="2026-08-10T10:00:00",
                                  page_text=page_text, reply_rows=reply, transcript_v2=v2)


def test_guard1_negative_in_words_negates_a_level():
    text = "EBITDA for the quarter stood at negative Rs27 crore against Rs40 crore last year."
    rows = _rows(text, [{"type": "number", "measure": "ebitda", "printed_label": "EBITDA for the quarter stood at",
                         "value_text": "Rs27 crore", "unit": "crore", "period": "Q1 FY27"}])
    assert rows[0]["value"] == -27.0
    pos = _rows("PAT stood at Rs40 crore.", [{"type": "number", "measure": "pat", "printed_label": "PAT stood at",
                                             "value_text": "Rs40 crore", "unit": "crore", "period": "Q1 FY27"}])
    assert pos[0]["value"] == 40.0


def test_guard2_a_period_label_is_never_a_value():
    text = "We expect to break even by H1FY28 and revenue of Rs 500 crore in FY27."
    rows = _rows(text, [
        {"type": "number", "measure": "revenue_from_operations", "printed_label": "break even by",
         "value_text": "H1FY28", "unit": ""},
        {"type": "guidance", "measure": "NEW:breakeven", "low": "H1FY28", "unit": "", "period": "H1 FY28",
         "text": "We expect to break even by H1FY28 and revenue of Rs 500 crore in FY27.",
         "new_definition": "x", "new_driver_node": "none"}])
    assert rows == [] or all(r["value_text"] != "H1FY28" for r in rows)
    assert obs.PERIOD_VALUE_RE.match("Q2") and obs.PERIOD_VALUE_RE.match("FY27") and not obs.PERIOD_VALUE_RE.match("27")


def test_guard3_a_cover_letter_page_gives_no_rows():
    text = ("Scrip Code: 532921 Sub: Transcript of the earnings call. Dear Sir/Madam, please find enclosed the "
            "transcript of the call held on 5 August 2026 for the quarter ended 30 June 2026.")
    reply = [{"type": "statement", "measure": "NEW:filing", "text": "Please find enclosed the transcript of the call.",
              "speaker": ""},
             {"type": "number", "measure": "NEW:scrip", "printed_label": "Scrip Code:", "value_text": "532921"}]
    assert _rows(text, reply, page=1) == []
    assert _rows(text, reply, page=1, v2=False) != []          # v1 rows are unchanged


def test_guard3b_bse_scrip_cover_letter_and_one_mark_title_page():
    # UNOMINDA's 27 May 2025 transcript cover: "BSE Scrip: 532539" without the word "Code"
    cover = ("Ref. No. Z-IV/R-39/D-2/NSE/207\nDate: May 27, 2025\nNSE Symbol: UNOMINDA\nBSE Scrip: 532539\n"
             "Sub: - Transcript of the Earnings Call held on Wednesday, May 21, 2025\nDear Sirs,\n"
             "Pursuant to Regulation 30 ..., please find enclosed the transcript of the Earnings Call.")
    assert obs.is_cover_letter(cover, 1)
    reply = [{"type": "statement", "measure": "NEW:filing", "text": "please find enclosed the "
              "transcript of the Earnings Call.", "speaker": "Tarun Kumar Srivastava"}]
    assert _rows(cover, reply, page=1) == []
    # one mark alone ("Sub:" in a title page) never drops the page
    title = "Title: Uno Minda Q4 Earnings Call\nSunil Bohra: Revenue grew 20%."
    assert not obs.is_cover_letter(title, 1)
    assert _rows(title, [{"type": "statement", "measure": "NEW:x", "text": "Revenue grew 20%.",
                          "speaker": "Sunil Bohra"}], page=1)
    # Kamat Hotels' 14 Aug 2026 cover: "Listing Department" + "Code:" + "Sub.:" + "Dear Sir / Madam"
    kamat = ("To, Listing Department BSE Limited. Code: 526668 ISIN: INE967C01018. Symbol: KAMATHOTEL\n"
             "Sub.: Submission of Transcript of Q1-FY27 Earnings Conference Call held on August 12, 2026\n"
             "Dear Sir / Madam,\nIn accordance with the provisions of Regulation 30 of the SEBI Regulations.")
    assert obs.is_cover_letter(kamat, 1)
    assert _rows(kamat, [{"type": "statement", "measure": "NEW:filing",
                          "text": "In accordance with the provisions of Regulation 30 of the SEBI Regulations.",
                          "speaker": "Kamat Hotels (India) Limited"}], page=1) == []


def test_guard4_and_5_ranges():
    text = "Margins should be 20% or 10% lower. We target $23 billion to $25 billion and 60% to 65% utilisation."
    rows = _rows(text, [
        {"type": "number", "measure": "NEW:margin_target", "printed_label": "Margins should be",
         "value_text": "20%", "high_text": "10%", "unit": "%", "new_definition": "x", "new_driver_node": "none"},
        {"type": "number", "measure": "NEW:market_size", "printed_label": "We target", "value_text": "$23 billion",
         "unit": "USD billion", "new_definition": "x", "new_driver_node": "none"},
        {"type": "number", "measure": "capacity.utilisation", "printed_label": "and", "value_text": "60%",
         "unit": "%"}])
    got = {r["value_text"]: r["value_high"] for r in rows}
    assert got["20%"] is None and got["$23 billion"] == 25.0 and got["60%"] == 65.0


def test_reparse_rebuilds_rows_from_page_reply(tmp_path, monkeypatch):
    out = tmp_path / "o.db"
    con = obs.create_db(out)
    v2_fp = __import__("hashlib").sha256(f"{obs.OBS_READER}\n{obs.PROMPT_TRANSCRIPT_V2}".encode()).hexdigest()[:12]
    raw = ('{"type": "number", "measure": "ebitda", "printed_label": "EBITDA stood at", '
           '"value_text": "Rs27 crore", "unit": "crore", "period": "Q1 FY27"}')
    con.execute("INSERT INTO page_reply VALUES (?,?,?,?,?)", (DOC, 4, f"transcript:{v2_fp}", raw, "t"))
    con.commit()
    store = tmp_path / "c1.db"
    s = sqlite3.connect(store)
    s.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, doc_type TEXT, known_at TEXT)")
    s.execute("INSERT INTO doc VALUES (?,?,?,?)", (DOC, "BESTAGRO", "transcript", "2026-08-10"))
    s.commit()
    s.close()
    monkeypatch.setattr(obs, "company_index", lambda dbs: {})
    monkeypatch.setattr(obs, "page_meta", lambda db, key: {"symbol": "BESTAGRO", "doc_type": "transcript",
                                                           "known_at": "2026-08-10"})
    monkeypatch.setattr(obs, "page_text_of", lambda db, key, page: "EBITDA stood at negative Rs27 crore.")
    stats = obs.reparse_db(con, [str(store)])
    assert stats["pages"] == 1 and stats["v2_pages"] == 1
    rows = con.execute("SELECT value FROM observation WHERE doc_key=?", (DOC,)).fetchall()
    assert rows == [(-27.0,)]
    assert con.execute("SELECT outcome, rows FROM page_read").fetchall() == [("rows", 1)]
    con.close()


def test_guard5_both_ends_share_a_unit():
    f = obs.printed_range_high
    assert f("PAT rose by 11% to INR34.5 crores.", "11%", 11.0) is None      # a growth then a level
    assert f("not more than 3% to 4%.", "3%", 3.0) == 4.0
    assert f("about INR310-325 crores", "INR310", 310.0) == 325.0
    assert f("Rs. 58 to Rs. 60, that", "Rs. 58", 58.0) == 60.0
    assert f("60 to 65% utilisation", "60", 60.0) == 65.0


def test_guards_6_to_9_inner_range_fraction_bare_label_cost_of_funds():
    text = ("We are borrowing at 6.3% now. 1/3 of revenue is exports. Margin 40%-45%. "
            "Guidance INR310 to INR320 crore.")
    rows = _rows(text, [
        {"type": "number", "measure": "nim", "printed_label": "We are borrowing at", "value_text": "6.3%", "unit": "%"},
        {"type": "number", "measure": "mix.share", "printed_label": "of revenue", "value_text": "1/3",
         "segment": "exports"},
        {"type": "number", "measure": "ebitda_margin", "printed_label": "Margin", "value_text": "40%-45%", "unit": "%"},
        {"type": "number", "measure": "ebitda", "printed_label": "to", "value_text": "INR320", "unit": "crore"}])
    got = [(r["measure"], r["value"], r["value_high"], r["unit"]) for r in rows]
    assert ("cost_of_funds", 6.3, None, "%") in got
    assert ("mix.share", 33.33, None, "%") in got
    assert ("ebitda_margin", 40.0, 45.0, "%") in got
    assert not [g for g in got if g[1] == 320.0]
    assert obs.inner_range("2024-25") is None and obs.inner_range("12%") is None


def test_guards_10_11_word_fraction_range_negation_ratio_unit():
    text = ("Margin it is about 14 and a half percent. We are expecting close to 25 to 30 bps reduction "
            "in cost of funds. EBITDA margin was 7.1 this quarter.")
    rows = _rows(text, [
        {"type": "number", "measure": "ebitda_margin", "printed_label": "it is about",
         "value_text": "14 and a half percent", "unit": "%"},
        {"type": "number", "measure": "cost_of_funds", "printed_label": "expecting close to", "value_text": "25",
         "unit": "bps", "sign": "-"},
        {"type": "number", "measure": "ebitda_margin", "printed_label": "EBITDA margin was", "value_text": "7.1"}])
    got = {r["value_text"]: r for r in rows}
    assert got["14 and a half percent"]["value"] == 14.5
    assert (got["25"]["value"], got["25"]["value_high"]) == (-30.0, -25.0)
    assert got["7.1"]["status"] == "unverified" and "no_unit: a ratio" in got["7.1"]["status_reason"]
    assert obs.word_fraction("12%") == 0.0


def test_guard12_forward_number_converted_to_guidance_and_past_actuals_kept():
    # 1. ZENTEC full sentence: future range becomes guidance/unverified, past actual on same sentence stays number
    zentec = _rows(
        "we said the full year will be between Rs.1200 Crores to 1300 Crores we have done Rs.485 Crores in the first half",
        [
            {"type": "number", "measure": "revenue.value", "printed_label": "the full year will be between",
             "value_text": "Rs.1200", "unit": "Crores", "period": "FY27",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "revenue.value", "printed_label": "we have done",
             "value_text": "Rs.485", "unit": "Crores", "period": "H1 FY27", "claim_type": "company_actual",
             "entity_scope": "company"},
        ],
    )
    z_by = {r["value_text"]: r for r in zentec}
    assert z_by["Rs.1200"]["record_type"] == "guidance"
    assert z_by["Rs.1200"]["status"] == "unverified"
    assert "forward_number:" in z_by["Rs.1200"]["status_reason"]
    assert (z_by["Rs.1200"]["value"], z_by["Rs.1200"]["value_high"]) == (1200.0, 1300.0)
    assert z_by["Rs.485"]["record_type"] == "number"
    assert z_by["Rs.485"]["status"] == "verified"
    assert (z_by["Rs.485"]["value"], z_by["Rs.485"]["value_high"]) == (485.0, None)

    # 2. TARACHAND: cue in clause before value, not in printed_label
    tarachand = _rows(
        "we would try to push them also to match the specialized services range of about 18% to 20%",
        [{"type": "number", "measure": "ebitda_margin", "printed_label": "specialized services range of about",
          "value_text": "18%", "unit": "%", "period": "FY27", "claim_type": "company_actual",
          "entity_scope": "company"}],
    )
    assert tarachand[0]["record_type"] == "guidance"
    assert tarachand[0]["status"] == "unverified"
    assert (tarachand[0]["value"], tarachand[0]["value_high"]) == (18.0, 20.0)

    # 3. KPIGREEN: "it will be in that range..."
    kpigreen = _rows(
        "if we get into more utility scale, it will be in that range or a little bit lower from 18% to 20%",
        [{"type": "number", "measure": "ebitda_margin",
          "printed_label": "it will be in that range or a little bit lower from",
          "value_text": "18%", "unit": "%", "period": "FY27", "claim_type": "company_actual",
          "entity_scope": "company"}],
    )
    assert kpigreen[0]["record_type"] == "guidance"
    assert kpigreen[0]["status"] == "unverified"
    assert (kpigreen[0]["value"], kpigreen[0]["value_high"]) == (18.0, 20.0)

    # 4. IDFCFIRSTB: "12% has to move to" -> 14%
    idfc_roe = _rows(
        "10% has to move to 12%, 12% has to move to 14%",
        [{"type": "number", "measure": "roe", "printed_label": "12% has to move to",
          "value_text": "14%", "unit": "%", "period": "FY27", "claim_type": "company_actual",
          "entity_scope": "company"}],
    )
    assert idfc_roe[0]["record_type"] == "guidance"
    assert idfc_roe[0]["status"] == "unverified"
    assert (idfc_roe[0]["value"], idfc_roe[0]["value_high"]) == (14.0, None)

    # 5. IDFCFIRSTB full sentence: "in due course ... this cost-income ratio will touch 50%"
    idfc_cir = _rows(
        "in due course ... this cost-income ratio will touch 50%",
        [{"type": "number", "measure": "NEW:cost_income_ratio",
          "printed_label": "this cost-income ratio will touch", "value_text": "50%", "unit": "%",
          "period": "FY27", "new_definition": "cost to income ratio", "new_driver_node": "cost",
          "claim_type": "company_actual", "entity_scope": "company"}],
    )
    assert idfc_cir[0]["record_type"] == "guidance"
    assert idfc_cir[0]["status"] == "unverified"
    assert (idfc_cir[0]["value"], idfc_cir[0]["value_high"]) == (50.0, None)

    # third_party forward number stays record_type='number' and is marked unverified
    tp = _rows(
        "NHAI will reach Rs.40000 crores of awards in FY27",
        [{"type": "number", "measure": "order.intake", "printed_label": "NHAI will reach",
          "value_text": "Rs.40000", "unit": "crores", "period": "FY27", "claim_type": "third_party"}],
    )
    assert tp[0]["record_type"] == "number"
    assert tp[0]["status"] == "unverified"
    assert "forward_number:" in tp[0]["status_reason"]
    assert (tp[0]["value"], tp[0]["value_high"]) == (40000.0, None)

    # Counter-examples: past actuals and cues in an earlier sentence stay plain number rows
    ce = _rows(
        "revenue grew by 6% to INR286.8 crores. it was 16% last year. "
        "We expect margins will expand. Revenue stood at Rs.500 crores in Q1 FY27.",
        [
            {"type": "number", "measure": "revenue_growth_yoy", "printed_label": "revenue grew by",
             "value_text": "6%", "unit": "%", "period": "Q1 FY27", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "it was",
             "value_text": "16%", "unit": "%", "period": "FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "revenue.value", "printed_label": "Revenue stood at",
             "value_text": "Rs.500", "unit": "crores", "period": "Q1 FY27", "claim_type": "company_actual",
             "entity_scope": "company"},
        ],
    )
    ce_by = {r["value_text"]: r for r in ce}
    assert ce_by["6%"]["record_type"] == "number" and ce_by["6%"]["status"] == "verified"
    assert (ce_by["6%"]["value"], ce_by["6%"]["value_high"]) == (6.0, None)
    assert ce_by["16%"]["record_type"] == "number" and ce_by["16%"]["status"] == "verified"
    assert (ce_by["16%"]["value"], ce_by["16%"]["value_high"]) == (16.0, None)
    assert ce_by["Rs.500"]["record_type"] == "number" and ce_by["Rs.500"]["status"] == "verified"
    assert (ce_by["Rs.500"]["value"], ce_by["Rs.500"]["value_high"]) == (500.0, None)


def test_guard13_industry_figures_and_our_market_share():
    # AWFIS: office stock, vacancy, supply in India are industry figures even if model marks verified
    awfis = _rows(
        "Let me give you a little color on the industry landscape: India's Grade A office stock across the "
        "top 7 cities now stands at 887 million square feet. Vacancy still fell by 42 basis points to 15.9%.",
        [
            {"type": "number", "measure": "NEW:industry_grade_a_office_stock",
             "printed_label": "India's Grade A office stock across the top 7 cities now stands at",
             "value_text": "887", "unit": "million sq ft", "period": "Q2 FY27",
             "new_definition": "Grade A office stock", "new_driver_node": "none",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "NEW:office_vacancy",
             "printed_label": "Vacancy still fell by 42 basis points to",
             "value_text": "15.9%", "unit": "%", "period": "Q2 FY27",
             "new_definition": "Office vacancy rate", "new_driver_node": "none",
             "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    assert all(r["entity_scope"] == "industry" and r["status"] == "unverified"
               and "industry_figure:" in r["status_reason"] for r in awfis)

    # NOCIL: China 1.9% from IRSG / NEW:market_ measure
    nocil = _rows(
        "According to IRSG data, China has grown up by almost 1.9% in the last year.",
        [{"type": "number", "measure": "volume_growth_yoy", "printed_label": "has grown up by almost",
          "value_text": "1.9%", "unit": "%", "period": "FY25",
          "claim_type": "company_actual", "entity_scope": "company"}],
    )
    assert nocil[0]["entity_scope"] == "industry"
    assert nocil[0]["status"] == "unverified"
    assert "industry_figure:" in nocil[0]["status_reason"]

    # Counter-example: "our market share" and "our share of the market" stay company facts
    ours = _rows(
        "Our market share is 18% in FY26 and our share of the market in south India is 22%.",
        [
            {"type": "number", "measure": "market.share", "printed_label": "Our market share is",
             "value_text": "18%", "unit": "%", "period": "FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "market.share", "printed_label": "our share of the market in south India is",
             "value_text": "22%", "unit": "%", "period": "FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    assert all(r["entity_scope"] == "company" and r["status"] == "verified" for r in ours)


def test_guard14_analyst_speaker_never_verified():
    # SYRMA: analyst Deepak Krishnan asked 3.6%, management J.S. Gujral corrected to 4.6%
    text = (
        "Moderator: Thank you very much. The first question we have is from the line of Deepak Krishnan "
        "from Kotak Institutional Equity. Please go ahead. "
        "Deepak Krishnan: I just wanted to understand why the margins come to about 3.6%. "
        "J.S. Gujral: For the quarter the margin is 4.6%."
    )
    rows = _rows(text, [
        {"type": "number", "measure": "ebitda_margin", "printed_label": "the margins come to about",
         "value_text": "3.6%", "unit": "%", "period": "Q1 FY25", "speaker": "Deepak Krishnan",
         "claim_type": "company_actual", "entity_scope": "company"},
        {"type": "number", "measure": "ebitda_margin", "printed_label": "the margin is",
         "value_text": "4.6%", "unit": "%", "period": "Q1 FY25", "speaker": "J.S. Gujral",
         "claim_type": "company_actual", "entity_scope": "company"},
    ])
    by_val = {r["value_text"]: r for r in rows}
    assert by_val["3.6%"]["status"] == "unverified"
    assert "not_management:" in by_val["3.6%"]["status_reason"]
    assert by_val["4.6%"]["status"] == "verified"

    # Explicit speaker_role != 'management' also triggers not_management
    role_rows = _rows(
        "The next question is from Amit Shah from XYZ. Margins were 12%.",
        [{"type": "number", "measure": "ebitda_margin", "printed_label": "Margins were",
          "value_text": "12%", "unit": "%", "period": "Q1 FY25", "speaker": "Some Speaker",
          "speaker_role": "analyst", "claim_type": "company_actual", "entity_scope": "company"}],
    )
    assert role_rows[0]["status"] == "unverified" and "not_management:" in role_rows[0]["status_reason"]


def test_guard15_one_sentence_many_rows_dedups_and_flags_measure_conflict():
    # Same sentence, same value mapped to cost_of_funds (3x) and nim (2x) -> keep 1 per measure, both unverified
    text = (
        "Now, end of the day, the Bank is borrowing money at 6.3% and we are getting a NIM of 6.3% in Q2 FY25. "
        "Separately, our deposit cost stood at 6.3% in Q2 FY25."
    )
    rows = _rows(text, [
        {"type": "number", "measure": "cost_of_funds", "printed_label": "the Bank is borrowing money at",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
        {"type": "number", "measure": "cost_of_funds", "printed_label": "at",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
        {"type": "number", "measure": "cost_of_funds", "printed_label": "borrowing money at",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
        {"type": "number", "measure": "nim", "printed_label": "we are getting a NIM of",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
        {"type": "number", "measure": "nim", "printed_label": "NIM of",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
        {"type": "number", "measure": "cost_of_funds", "printed_label": "our deposit cost stood at",
         "value_text": "6.3%", "unit": "%", "period": "Q2 FY25", "claim_type": "company_actual",
         "entity_scope": "company"},
    ])
    # First sentence has 2 rows (1 cost_of_funds + 1 nim), both unverified with measure_conflict;
    # second sentence has 1 cost_of_funds row, verified.
    assert len(rows) == 3
    sent1 = [r for r in rows if r["printed_label"] != "our deposit cost stood at"]
    sent2 = [r for r in rows if r["printed_label"] == "our deposit cost stood at"]
    assert {r["measure"] for r in sent1} == {"cost_of_funds", "nim"}
    assert all(r["status"] == "unverified" and "measure_conflict:" in r["status_reason"] for r in sent1)
    assert len(sent2) == 1 and sent2[0]["status"] == "verified"


def test_guard16_range_tail_with_unit_word():
    f = obs.printed_range_high
    assert f("Rs.1200 Crores to 1300 Crores", "Rs.1200", 1200.0) == 1300.0
    assert f("18 percent to 20 percent", "18", 18.0) == 20.0
    assert f("5 million to 6 million", "5", 5.0) == 6.0
    assert f("PAT rose by 11 percent to 34.5 crores", "11", 11.0) is None
    assert f("18 million to 20%", "18", 18.0) is None


def test_transcript_numbers_never_verified_by_page_check_alone():
    from reality_engine.v2 import observations as o
    rows = [{"record_type": "number", "status": "verified", "status_reason": ""},
            {"record_type": "guidance", "status": "verified", "status_reason": "x"},
            {"record_type": "number", "status": "quarantined", "status_reason": "bad"},
            {"record_type": "statement", "status": "verified", "status_reason": ""}]
    o.apply_transcript_number_gate(rows)
    assert [r["status"] for r in rows] == ["unverified", "unverified", "quarantined", "verified"]
    assert "transcript_number" in rows[1]["status_reason"] and rows[1]["status_reason"].startswith("x; ")

def test_guard17_bounds_set_value_kind_and_mark_unverified():
    # Real ACMESOLAR sentences: "more than 9% interest cost" and "sufficient liquidity of more than 3,000 crores"
    acme = _rows(
        "So, three projects are yet to be refinanced. So, they are still running at more than 9% interest cost. "
        "We have sufficient liquidity of more than 3,000 crores.",
        [
            {"type": "number", "measure": "NEW:interest_cost", "printed_label": "more than",
             "value_text": "9%", "unit": "%", "period": "Q1 FY26", "new_definition": "interest cost",
             "new_driver_node": "cost", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "cash_and_cash_equivalents",
             "printed_label": "sufficient liquidity of more than", "value_text": "3,000",
             "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    assert all(r["value_kind"] == "lower_bound" and r["status"] == "unverified"
               and "lower_bound:" in r["status_reason"] for r in acme)

    # Lower and upper bound cues
    bounds = _rows(
        "Capex over 500 crores, margin at least 15%, revenue upwards of 100 crores, debt in excess of 50 crores. "
        "Attrition less than 5%, margin below 10%, stake up to 25%, capex at most 40 crores, "
        "cost not more than 12%, maximum of 8 plants.",
        [
            {"type": "number", "measure": "capex", "printed_label": "Capex over", "value_text": "500",
             "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "margin at least", "value_text": "15%",
             "unit": "%", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "revenue_from_operations", "printed_label": "revenue upwards of",
             "value_text": "100", "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "borrowings", "printed_label": "debt in excess of", "value_text": "50",
             "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "NEW:attrition", "printed_label": "Attrition less than", "value_text": "5%",
             "unit": "%", "period": "Q1 FY26", "new_definition": "attrition rate", "new_driver_node": "cost",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "margin below", "value_text": "10%",
             "unit": "%", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "mix.share", "printed_label": "stake up to", "value_text": "25%",
             "unit": "%", "segment": "jv", "period": "Q1 FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "capex", "printed_label": "capex at most", "value_text": "40",
             "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "NEW:cost_ratio", "printed_label": "cost not more than", "value_text": "12%",
             "unit": "%", "period": "Q1 FY26", "new_definition": "cost ratio", "new_driver_node": "cost",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "count.plants", "printed_label": "maximum of", "value_text": "8",
             "unit": "plants", "period": "Q1 FY26", "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    by_vt = {r["value_text"]: r for r in bounds}
    for vt in ("500", "15%", "100", "50"):
        assert by_vt[vt]["value_kind"] == "lower_bound" and by_vt[vt]["status"] == "unverified"
    for vt in ("5%", "10%", "25%", "40", "12%", "8"):
        assert by_vt[vt]["value_kind"] == "upper_bound" and by_vt[vt]["status"] == "unverified"
        assert "upper_bound:" in by_vt[vt]["status_reason"]

    # Counter-tests: point followed by bound, and comparative "less than last year's 12%"
    ce = _rows(
        "Revenue grew 20% to more than INR500 crores. Margin is less than last year's 12%.",
        [
            {"type": "number", "measure": "revenue_growth_yoy", "printed_label": "Revenue grew",
             "value_text": "20%", "unit": "%", "period": "Q1 FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "revenue_from_operations", "printed_label": "to more than",
             "value_text": "INR500", "unit": "crores", "period": "Q1 FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "Margin is less than last year's",
             "value_text": "12%", "unit": "%", "period": "FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
        ],
    )
    ce_by = {r["value_text"]: r for r in ce}
    assert ce_by["20%"]["value_kind"] == "" and ce_by["20%"]["status"] == "verified"
    assert ce_by["INR500"]["value_kind"] == "lower_bound" and ce_by["INR500"]["status"] == "unverified"
    assert ce_by["12%"]["value_kind"] == "" and ce_by["12%"]["status"] == "verified"


def test_guard18_quarterly_increase_and_addition_become_change():
    # Real CANBK sentence ("increased by around 9,000-10,000 crores") + quarterly additions
    canbk = _rows(
        "Now, our AFS book is also increased by around 9,000-10,000 crores even in this quarter also.",
        [{"type": "number", "measure": "NEW:afs_book",
          "printed_label": "our AFS book is also increased by around",
          "value_text": "9,000", "unit": "crores", "period": "Q4 FY24",
          "new_definition": "AFS book", "new_driver_node": "none",
          "claim_type": "company_actual", "entity_scope": "company"}],
    )
    assert canbk[0]["measure"] == "NEW:afs_book_change"
    assert (canbk[0]["value"], canbk[0]["value_high"]) == (9000.0, 10000.0)
    assert canbk[0]["direction"] == "up"

    q_adds = _rows(
        "Deposits increased by 120 crores during the quarter. "
        "We had net additions of 2 lakh customers in Q2 and incremental 20 branches sequentially.",
        [
            {"type": "number", "measure": "NEW:deposits", "printed_label": "Deposits increased by",
             "value_text": "120", "unit": "crores", "period": "Q2 FY26", "new_definition": "deposits",
             "new_driver_node": "none", "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "count.customers", "printed_label": "net additions of",
             "value_text": "2 lakh", "unit": "lakh customers", "period": "Q2 FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "count.outlets", "printed_label": "incremental",
             "value_text": "20", "unit": "branches", "period": "Q2 FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    by_vt = {r["value_text"]: r for r in q_adds}
    assert by_vt["120"]["measure"] == "NEW:deposits_change" and by_vt["120"]["direction"] == "up"
    assert by_vt["2 lakh"]["measure"] == "NEW:count.customers_change" and by_vt["2 lakh"]["direction"] == "up"
    assert by_vt["20"]["measure"] == "NEW:count.outlets_change" and by_vt["20"]["direction"] == "up"
    assert all(r["status"] == "verified" for r in q_adds)

    # Counter-test: "we have 450 stores, having added 15 this quarter" -> 450 stays level, 15 becomes change
    ce = _rows(
        "we have 450 stores, having added 15 this quarter",
        [
            {"type": "number", "measure": "count.outlets", "printed_label": "we have",
             "value_text": "450", "unit": "stores", "period": "Q2 FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "count.outlets", "printed_label": "having added",
             "value_text": "15", "unit": "stores", "period": "Q2 FY26",
             "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    ce_by = {r["value_text"]: r for r in ce}
    assert ce_by["450"]["measure"] == "count.outlets" and ce_by["450"]["status"] == "verified"
    assert ce_by["15"]["measure"] == "NEW:count.outlets_change" and ce_by["15"]["direction"] == "up"
    assert ce_by["15"]["status"] == "verified"


def test_guard19_adjusted_basis_flagged_in_clause_only():
    # Real SYRMA sentence: "if we exclude the unutilized IPO proceeds" comes AFTER the value
    syrma = _rows(
        "Our ROCE for the quarter is 11% if we exclude the unutilized IPO proceeds and goodwill from the capital employed.",
        [{"type": "number", "measure": "roce", "printed_label": "Our ROCE for the quarter is",
          "value_text": "11%", "unit": "%", "period": "Q1 FY25",
          "claim_type": "company_actual", "entity_scope": "company"}],
    )
    assert syrma[0]["adjusted"] == 1 and syrma[0]["status"] == "unverified"
    assert "adjusted/hypothetical figure, not the reported measure" in syrma[0]["status_reason"]

    # All adjusted-basis cues in clause/label
    cues = _rows(
        "ROCE excluding IPO proceeds is 22%. EBITDA margin ex-other income is 18%. "
        "Adjusted PAT stood at INR42 crores. Pre-Ind AS 116 EBITDA margin was 14%. "
        "Like-for-like revenue growth was 9%. On a comparable basis, margin was 12%. "
        "Pro forma revenue was INR500 crores.",
        [
            {"type": "number", "measure": "roce", "printed_label": "ROCE excluding IPO proceeds is",
             "value_text": "22%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "EBITDA margin ex-other income is",
             "value_text": "18%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "pat", "printed_label": "Adjusted PAT stood at",
             "value_text": "INR42", "unit": "crores", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "Pre-Ind AS 116 EBITDA margin was",
             "value_text": "14%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "revenue_growth_yoy", "printed_label": "Like-for-like revenue growth was",
             "value_text": "9%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "ebitda_margin", "printed_label": "margin was",
             "value_text": "12%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "revenue_from_operations", "printed_label": "Pro forma revenue was",
             "value_text": "INR500", "unit": "crores", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
        ],
    )
    assert all(r["adjusted"] == 1 and r["status"] == "unverified"
               and "adjusted/hypothetical figure, not the reported measure" in r["status_reason"] for r in cues)

    # Counter-tests: "excluding" in another sentence, another comma clause, and delivery term "ex-factory" do not fire
    ce = _rows(
        "ROCE excluding IPO proceeds is 22%. EBITDA margin for the quarter stood at 17%. "
        "We are selling refined sugar at Rs3990 per quintal ex-factory. "
        "Revenue was INR28,840 crores, up 77% year-on-year, supported by zinc cost, excluding royalty, 776 per ton.",
        [
            {"type": "number", "measure": "ebitda_margin", "printed_label": "EBITDA margin for the quarter stood at",
             "value_text": "17%", "unit": "%", "period": "Q1 FY25", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "NEW:sugar_realisation", "printed_label": "selling refined sugar at",
             "value_text": "Rs3990", "unit": "Rs per quintal", "period": "Q1 FY25",
             "new_definition": "sugar realisation", "new_driver_node": "revenue",
             "claim_type": "company_actual", "entity_scope": "company"},
            {"type": "number", "measure": "revenue_growth_yoy", "printed_label": "up",
             "value_text": "77%", "unit": "%", "period": "H1 FY26", "claim_type": "company_actual",
             "entity_scope": "company"},
            {"type": "number", "measure": "NEW:zinc_cost_per_ton", "printed_label": "excluding royalty,",
             "value_text": "776", "unit": "$ per ton", "period": "H1 FY26",
             "new_definition": "zinc cost per ton", "new_driver_node": "cost",
             "claim_type": "company_actual", "entity_scope": "company"},
        ],
    )
    ce_by = {r["value_text"]: r for r in ce}
    assert all(ce_by[vt]["adjusted"] == 0 and ce_by[vt]["status"] == "verified" for vt in ("17%", "Rs3990", "77%"))
    assert ce_by["776"]["adjusted"] == 1 and ce_by["776"]["status"] == "unverified"
