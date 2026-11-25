# T-242: non-call documents, moderator speakers, short content-free remarks - measurement

Surprise audit of 60 verified statements from the whole-universe transcript run (`C:/RealityEngine/t242/tx_fy27_surprise1/`, 45 R / 9 P / 2 W / 4 J, W+J 10%). Rules in `reality_engine/v2/obs_speaker.py` and the transcript page selection in `reality_engine/v2/observations.py`; no prompt change (v3 fp 2fae7ddac53e, v2 fp e95108f16e65).

Measured in-process over every `record_type='statement'` row of the two copy baselines (read-only; the same method as `tasks/t242_closing_measure.md`), plus a scoped `--reparse` of the six evidence documents. A full-copy `--reparse` runs at about 1 page/s on this laptop (2,557 of 6,000 fy27 pages in 44 min, 339 of 11,192 tx394 pages in 5 min), so it was stopped; the rule counts below are exact over every row.

| DB | statements | verified | touched | touched % | docs flagged (<3 labels) |
|---|---:|---:|---:|---:|---:|
| fy27 | 27,951 | 15,446 | 234 | 0.837% | 29/389 (7.455%) |
| tx394 | 55,219 | 30,758 | 272 | 0.493% | 25/907 (2.756%) |

Touched = rows the rule drops or newly unverifies. Both DBs are far under the 1.5% ceiling.

## Statements and documents each rule touches

| DB | rule | statements | docs | newly unverified / dropped |
|---|---|---:|---:|---:|
| fy27 | `not_a_call` | 8 | 3 | 2 unverified |
| fy27 | `speaker_moderator` | 52 | 26 | 12 unverified |
| fy27 | `speaker_not_a_person` | 194 | 10 | 73 unverified |
| fy27 | short remarks (short_generic 2, short_pointer 5, short_refer_back 140) | 147 | 81 | 147 dropped |
| tx394 | `not_a_call` | 7 | 1 | 0 unverified |
| tx394 | `speaker_moderator` | 7 | 7 | 0 unverified |
| tx394 | `speaker_not_a_person` | 0 | 0 | 0 unverified |
| tx394 | short remarks (short_pointer 5, short_refer_back 267) | 272 | 156 | 272 dropped |

`not_a_call` fires on the 3 documents that print 8 statements (BRIPORT AGM minutes, two BRPL investor presentations); the other flagged documents hold no statement rows at all.

## Doc check: the 3% stop report

fy27 flags 29/389 (7.455%), over the 3% bar, so the list is reported here before continuing; tx394 flags 25/907 (2.756%). Every flagged document is a cover letter, a one-page exchange filing, an empty-text scan (RailTel pages have no text layer) or a material filing: **none is a call**. The 358 fy27 documents that actually hold statements flag 3 (0.84%).

First 20 flagged fy27 documents (labels / pages / head):

1. `0` labels, 1p - 38e8fe81-3e88-4210-be71-5fbdb86cf40e.pdf - May 15, 2026 BSE Limited National Stock Exchange of India Limited Sir Phiroze Jeejeebhoy Towers Exchange Plaza
2. `0` labels, 1p - 5c7874c4-c6c4-4320-a818-480217100a14.pdf - November 07, 2026 BSE Limited National Stock Exchange of India Limited Sir Phiroze Jeejeebhoy Towers Exchange 
3. `0` labels, 1p - 1cf9db7b-9cbc-45a3-8579-288ac12c561a.pdf - Ref: No. ABCL/SD/MUM/2026-27/MAY/18 08 May 2026 BSE Limited Phiroze Jeejeebhoy Towers, Dalal Street, Mumbai 40
4. `0` labels, 1p - 23e4bbbb-ae70-4989-b843-372042a67411.pdf - Ref: No. ABCL/SD/MUM/2026-27/NOVEMBER/114 04 November 2026 BSE Limited Phiroze Jeejeebhoy Towers, Dalal Street
5. `0` labels, 1p - a20e7214-b2f6-45ea-9399-a8d18b373082.pdf - Ref: No. ABCL/SD/MUM/2026-27/AUGUST/70 06 August 2026 BSE Limited Phiroze Jeejeebhoy Towers, Dalal Street, Mum
6. `0` labels, 1p - 37f13249-9550-4de0-8a19-ad781c5df7a7.pdf - Ajanta Pharma Limited Ajanta Tower, 54-A, M Vasanji Road, Chakala, Andheri (E), Mumbai 400 093, India Corporat
7. `0` labels, 1p - b46e1d2f-d685-4428-bdfc-7e69f2bf6634.pdf - Ajanta Pharma Limited Ajanta Tower, 54-A, M Vasanji Road, Chakala, Andheri (E), Mumbai 400 093, India Corporat
8. `0` labels, 1p - eef95dcd-bda9-43c0-be83-0889f2356365.pdf - Ajanta Pharma Limited Ajanta Tower, 54-A, M Vasanji Road, Chakala, Andheri (E), Mumbai 400 093, India Corporat
9. `2` labels, 1p - 59e38213-822e-4f91-a187-edac43316fa0.pdf - Aptus Value Housing Finance India Ltd. 8B, Doshi Towers, 205, Poonamallee High Road, Kilpauk, Chennai-600 010.
10. `2` labels, 1p - 6211b209-a8bf-4fc2-bb6c-de90adcc4cf6.pdf - Aptus Value Housing Finance India Ltd. 8B, Doshi Towers, 205, Poonamallee High Road, Kilpauk, Chennai-600 010.
11. `2` labels, 1p - 85e40b95-152d-43f2-b46f-767c47ab173e.pdf - Aptus Value Housing Finance India Ltd. 8B, Doshi Towers, 205, Poonamallee High Road, Kilpauk, Chennai-600 010.
12. `1` labels, 1p - 02e80c93-3b86-4c1e-a6d6-0174aff3ae65.pdf - 18th August, 2026 To BSE Limited P J Towers Dalal Street Mumbai – 400 001 Scrip Code: 532830 To National Stock
13. `1` labels, 1p - 149550e3-5a38-486e-ac20-34ab849e82c5.pdf - 01st July 2026 To BSE Limited Phiroze Jeejeebhoy Towers Dalal Street Mumbai – 400 001 Scrip Code: 532830 To Na
14. `1` labels, 1p - 296614c4-0d41-4eb6-a39f-fd2c957c379b.pdf - 25th May 2026 To BSE Limited Phiroze Jeejeebhoy Towers Dalal Street Mumbai – 400 001 Scrip Code: 532830 To Nat
15. `1` labels, 1p - 9324f8da-f7e9-4a27-8d52-fcb111b14078.pdf - 11th November, 2026 To BSE Limited Phiroze Jeejeebhoy Towers Dalal Street, Fort, Mumbai – 400 001 Scrip Code: 
16. `0` labels, 1p - 76428715-ba08-4401-ab49-087fb9274de3.pdf - To: To: Dear Sir/Madam, Sub: Transcript of the Earnings Call for the Quarter and Year Ended March 31, 2026. Th
17. `0` labels, 1p - 8f24ec03-8934-4dce-92d1-082d59871a93.pdf - To: To: Dear Sir/Madam, Sub: Transcript of the Earnings Call for the Quarter Ended June 30, 2026. This is with
18. `0` labels, 1p - be7d2588-3b83-46ed-ab68-659373fcaf4c.pdf - To: To: Dear Sir/Madam, Sub: Transcript of the Earnings Call for the Quarter and Half Year Ended September 30,
19. `1` labels, 1p - 47ab17b3-8970-457b-8694-7b5f1c38bb60.pdf - AXIS/CO/CS/53/2026-27 April 30, 2026 National Stock Exchange of India Limited Exchange Plaza, 5th Floor Plot N
20. `1` labels, 1p - bf702dc4-b1a5-4793-9aa6-4b1aa7b4c3a4.pdf - CIN NO.: L27109GJ1991PLC016200 Date: 13th August, 2026 To, The Manager Department of Corporate Services BSE Lt

First 20 flagged tx394 documents:

1. `0` labels, 1p - a3aadb03-9b55-4918-829b-7a61a98673a2.pdf - Adani Enterprises Limited “Adani Corporate House”, Shantigram, Near Vaishno Devi Circle, S. G. Highway, Khodiy
2. `1` labels, 1p - 2b62e959-20da-48c3-9f7b-8b5d430ebbaf.pdf - ASTRA MICROWAVE PRODUCTS LIMITED Regd. Office: ASTRA Towers, Survey No. 12(P), Kothaguda Post, Kondapur, HITEC
3. `2` labels, 3p - 32355eb5-3f32-49d7-9c94-ca5961f6f294.pdf - Brahmaputra Infrastructure Ltd. Registered Office: Brahmaputra House, A-7, Mahipalpur (NH 8-Mahipalpur Crossin
4. `2` labels, 1p - 173a9842-c9c8-4742-86c9-9a07b252188b.pdf - Coforge Limited Registered office: www.coforge.com Special Economic Zone, Plot No. TZ-2& 2A Plot No. 13, Udyog
5. `2` labels, 1p - 337dca3c-c321-4d74-8610-38cdfe2bda4c.pdf - Coforge Limited Registered office: www.coforge.com Special Economic Zone, Plot No. TZ-2& 2A Plot No. 13, Udyog
6. `2` labels, 1p - 93ca1f03-7c63-446a-a873-ee7dafe52002.pdf - Coforge Limited Registered office: www.coforge.com Special Economic Zone, Plot No. TZ-2& 2A Plot No. 13, Udyog
7. `1` labels, 1p - aaf5bc0d-6c28-4622-b9be-5c136fd09719.pdf - Coforge Limited Registered office: www.coforge.com Special Economic Zone, Plot No. TZ-2& 2A 8, Balajl Estate, 
8. `1` labels, 1p - 24b0e93d-87dc-47f8-b887-a88243ea9210.pdf - Lr. No. Secy/Reg.30/2024 Date: 12.11.2024 To National Stock Exchange of India Ltd. Plot No. C/1, G Block, Band
9. `1` labels, 1p - 9e567bf9-4fab-4e3e-add7-f5659ca386ea.pdf - Lr. No. Secy/Reg.30/2024 Date: 21.08.2024 To National Stock Exchange of India Ltd. Plot No. C/1, G Block, Band
10. `1` labels, 1p - b5374f10-5a99-4bd7-80a8-f66bdfbc9f36.pdf - Lr. No. Secy/Reg.30/2025 Date: 20.08.2025 To National Stock Exchange of India Ltd. Plot No. C/1, G Block, Band
11. `1` labels, 1p - c2858d40-ed3b-452e-b169-2042afc4e44c.pdf - NLC India Limited (‘Navratna’ - Government of India Enterprise) Registered Office: No.135, EVR Periyar High Ro
12. `0` labels, 15p - 372344c8-b881-4591-b2de-f6d0e6ecd00a.pdf - RailTel/Sectt/21/SE/S-16 Date: July 29, 2024 ͧ लिèटंग ͪ वभाग, नेशनल èटॉक एÈसचɅज ऑफ इंͫ डया ͧ लͧ मटेड, 'एÈसचɅज 
13. `0` labels, 12p - 5f30c904-d545-4395-afb3-bf9fcb71728d.pdf - A Navratna PSU Ref: RailTel/Sectt/21/SE/S-16 Date: June 30, 2025 ͧ लिèटंग ͪ वभाग, नेशनल èटॉक एÈसचɅज ऑफ इंͫ डया
14. `0` labels, 10p - 8fa559bb-e58f-4af4-abc3-80c7860f841c.pdf - RailTel/Sectt/21/SE/S-16 Date: November 3, 2026 ͧ लिèटंग ͪ वभाग, नेशनल èटॉक एÈसचɅज ऑफ इंͫ डया ͧ लͧ मटेड, 'एÈसच
15. `0` labels, 16p - ae7f8406-1061-45ac-8afc-cb63e93c9542.pdf - RailTel/Sectt/21/SE/S-16 Date: August 8, 2024 ͧ लिèटंग ͪ वभाग, नेशनल èटॉक एÈसचɅज ऑफ इंͫ डयाͧ लͧ मटेड, 'एÈसचɅज 
16. `2` labels, 1p - 3ff9f903-5c3c-4bad-aa21-a91266307d0e.pdf - CIN: L27320WB1997PLC084819 Registered Office: Poddar Point, 10th Floor, 113 Park Street, Kolkata – 700016, WB,
17. `2` labels, 1p - 7a11b70a-d346-4dbe-841f-541721b4af99.pdf - CIN: L27320WB1997PLC084819 Registered Office: Poddar Point, 10th Floor, 113 Park Street, Kolkata 700016, India
18. `2` labels, 1p - 8a84019e-8651-40ae-b0c3-0c71d6fb9523.pdf - CIN: L27320WB1997PLC084819 Registered Office: Poddar Point, 10th Floor, 113 Park Street, Kolkata 700016, India
19. `2` labels, 1p - 8ac6365e-b000-474c-9726-2938b4c0958f.pdf - CIN: L27320WB1997PLC084819 Registered Office: Poddar Point, 10th Floor, 113 Park Street, Kolkata 700016, India
20. `0` labels, 1p - ee0acc0d-8762-438e-934e-3a219cf6a426.pdf - CIN: L27320WB1997PLC084819 Registered Office: Poddar Point, 10th Floor, 113 Park Street, Kolkata 700016, India

## 20 sampled per rule (quoted)

### fy27

**not_a_call** - 8 statements, 3 docs

- `BRIPORT` p2 [Company Secretary] There was no query during Question & Answer sessions.
- `BRIPORT` p2 [Company Secretary] The Shareholders were informed that the Company has appointed Mr. Ravi Jain, Managing Director as Chairperson of the Company.
- `BRIPORT` p3 [Chairperson] As there were no qualifications in the Statutory Auditors’ Report, and the Secretarial Audit Report, they were also taken as read.
- `BRIPORT` p3 [Chairperson] It was then informed to the Members that the combined results of the e-voting on the resolutions, along with the Scrutinizer's Report, would be intimated to the BSE Limit
- `BRIPORT` p4 [Ashish] This document does not constitute minutes of the proceedings of the Annual General Meeting of the Company.
- `BRPL` p2 [Bansal Roofing Products Limited] Discussions will be based on publicly available information. No unpublished price sensitive information (UPSI) is intended to be discussed during the interactions. Also, 
- `BRPL` p3 [Bansal Roofing Products Limited] Bansal Roofing Products Limited is pleased to invite you to the Q1 FY27 Post Earnings Conference Call Thursday, 13th August 2026 02:00 PM - 03:00 PM IST The management te
- `BRPL` p2 [Bansal Roofing Products Limited] Discussions will be based on publicly available information. No unpublished price sensitive information (UPSI) is intended to be discussed during the interactions. Also, 

**speaker_moderator** - 52 statements, 26 docs

- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] Today's interaction is being conducted primarityto discuss thefinancial performance of Aartech Sotonics Limited foi tne quartei ended 30 June 2026.
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] This. witt be fottowed by a question_and_answer session, where participants witt have an opportunity to interact with the management and seek ctarifications on the quarte
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] As there is no separate investor presentation being circutated fortoday,s interaction, the discussion witt primarity Oe Oas-eO on the Company,s financial. results for the
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] Before we proceed, I woutd tike to introduce the management representatives who are joining us today.
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] We have with us: 1. Mrs. Arati Nath, CEO and Director ofthe Company, 2. Mysetf, CS K R Tanui Reddy, Company Secretary and Comptiance Off icer, 3. Mr. Pradeep Narkhede, CF
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] We are pteased to have the management team with us today and thank them for,oining this interaction.
- `AARTECH` p2 [CS K R Tanuj Reddy (Moderator)] Before we begin, tet me brief ty exptain the format of today,s i The m witt have two
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] The management may atso provide retevant commentaryon thefactors that have contributed to the quarterty performance and the broad outtook for the business.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Fottowing this, we wilt move to the euestion-and-Answer session.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Participants witt be abte to ask questions directty to the management during the e&A.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Since this interaction is being conducted through Googte Meet, I woutd request att participants to keep their microphones iruteJ wnite tne management is making its openin
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] During the Q&A session, participants may use the Raise Hand option.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Once lcatt your name, ptease unmute yoursetf, briefty introduce yoursetf and then proceed with your question.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] After asking the question, I woutd request you to kindty mute yoursetf aga in.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] lf you have muttipte questions, I woutd request you to first raise the most important question.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Depending on the time avail.abLe, we can take up additionaI questions subsequentty.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Before we proceed, I woutd tike to ptace the customary disctaimer on record.
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] Good morning, ladies and gentlemen. On behalf of Aartech Solonics Limited, I warmly welcome all investors, analysts, shareholders, and participants to the company's first
- `AARTECH` p3 [CS K R Tanuj Reddy (Moderator)] It is now my pleasure to introduce the members of the senior management participating in today's call: 1. We have with us Mr. Amit Raje, Chairman and Managing Director, 2
- `ABB` p20 [Moderator] Thank you, members of the management. Ladies and gentlemen, on behalf of ABB India Limited, that concludes this conference. We thank you for joining us, and you may now d

**speaker_not_a_person** - 194 statements, 10 docs

- `AFFORDABLE` p27 [Profit After Tax] Other Income for FY26 stood at Rs.329 Lakhs (vs Rs.99 Lakhs in FY25), comprising interest accrued on ODI Loan (Rs.130 Lakhs), GST provision reversal on a favorable appell
- `AFFORDABLE` p27 [Profit After Tax] EBITDA turned around from a loss of Rs.233 Lakhs to a profit of Rs.1,716 Lakhs — a swing of ~Rs.1,950 Lakhs.
- `AFFORDABLE` p27 [Profit After Tax] EBITDA Margin at ~14.2% — achieved through decisive cost actions across all group entities.
- `AFFORDABLE` p27 [Profit After Tax] PBT turned positive at Rs.988 Lakhs (vs loss of Rs.942 Lakhs) and PAT turned positive at Rs.697 Lakhs (vs loss of Rs.1,165 Lakhs in FY25).
- `AFFORDABLE` p27 [Profit After Tax] Improved operating leverage visible as lower costs translated directly into higher margins
- `AFFORDABLE` p27 [Profit After Tax] Total Expenses well-managed at Rs.9,491 Lakhs — materials, employee and overhead costs all optimized in line with operations.
- `AFFORDABLE` p27 [Profit After Tax] Demonstrates successful restructuring, tighter cost control, and improved execution, setting a stronger base for future growth
- `AFFORDABLE` p27 [Profit After Tax] New customer acquisition - As on 31st May 2026, our confirmed order book stands at approximately Rs.12,716 Lakhs.
- `AFFORDABLE` p27 [Profit After Tax] Out of this the new bookings of Rs 1,955 Lakh is added in this quarter
- `AFFORDABLE` p27 [Profit After Tax] ARAPL RAAS has signed a strategic investment of ₹48 Crore to build a world-class autonomous robotics business under the Humro brand.
- `AFFORDABLE` p27 [Profit After Tax] Humro has secured early deployments with multiple Fortune 50 companies, with commercial engagements currently underway.
- `AFFORDABLE` p27 [Profit After Tax] These initial successes are expected to drive large-scale rollouts across their warehouse networks, creating a significant revenue opportunity for the Company.
- `AFFORDABLE` p27 [Profit After Tax] Humro is also in advanced discussions for a strategic partnership in the United States, expected to accelerate growth in one of the world’s largest robotics markets.
- `AFFORDABLE` p27 [Profit After Tax] The partnership would enable local inventory stocking in the US, reducing delivery lead times from ~4 months to ~15 days, strengthening customer acquisition and service c
- `AFFORDABLE` p27 [Profit After Tax] Order Book of Rs.36 Crore is there which is in lease model and executed in 3 years,.
- `AFFORDABLE` p27 [Profit After Tax] Order in Pipeline for Rs.60 Crore in outright sales.
- `AFFORDABLE` p29 [Profit After Tax] Statements in this document relating to future status, events, or circumstances, including but not limited to statements about plans and objectives, the progress and resu
- `ARSSBL` p2 [Anand Rathi Share and Stock Brokers Limited] This is in continuation to our letter dated October 14, 2026, wherein we had informed regarding the audio link of the earnings call with analysts/investors for the second
- `ARSSBL` p2 [Anand Rathi Share and Stock Brokers Limited] In this regard, we are enclosing herewith copy of the earnings conference call transcript for the second quarter and half year ended September 30, 2026, held on October 1
- `AURUM` p13 [ASHISH DEORA (FOUNDER & CEO, AURUM VENTURES & NON-EXECUTIVE CHAIRMAN, AURUM PROPTECH LIMITED)] This is Ashish here. Just to add to what Onkar said. Look, we, we bought PropTiger in last July, exactly one year ago. And since then, we have been looking at Housing. Ho

**short remarks** - 147 statements, 81 docs, by kind {'short_refer_back': 140, 'short_pointer': 5, 'short_generic': 2}

- `360ONE` p17 [Mr. Karan Bhagat - MD and CEO, 360 ONE WAM] That's the desire, yes.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `AADHARHFC` p15 [Rishi Anand] Yes, that is right.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `AAVAS` p7 [Manu Singh] The answer to your question, not currently.  _(short_pointer: a pointer to another speaker or question, not an answer)_
- `AAVAS` p10 [Manu Singh] So that is the second piece.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABDL` p9 [Amar Sinha] So that's one.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABDL` p9 [Amar Sinha] That is now behind all of us.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABDL` p9 [Alok Gupta] So that's third one.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABDL` p14 [Alok Gupta] It's neither conservative.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p8 [Sangeeta Tanwani] It's not very large.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p14 [Ashish Dikshit] It's very large.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p14 [Ashish Dikshit] It's a fragmented market.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p14 [Ashish Dikshit] It's too early.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p15 [Ashish Dikshit] Yes, that's right.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABFRL` p15 [Ashish Dikshit] It's a pipeline which takes time to build.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABSLAMC` p10 [A. Balasubramanian] That's something which we'll do.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABSLAMC` p13 [A. Balasubramanian] And that's something we are encouraging.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ABSLAMC` p13 [A. Balasubramanian] It's quite large.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACC` p26 [Vinod Bahety] That is part of the other operating income.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACC` p31 [Karan Adani] Yes, that's right.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACC` p19 [Vinod Bahety] Yes, that is true.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_

### tx394

**not_a_call** - 7 statements, 1 docs

- `BRAHMINFRA` p2 [Brahmaputra Infrastructure Limited] Please note that no unpublished price sensitive information will be shared during the conference call.
- `BRAHMINFRA` p2 [Brahmaputra Infrastructure Limited] The schedule is subject to change due to exigencies on the part of the investors / analysts or the Company.
- `BRAHMINFRA` p2 [Brahmaputra Infrastructure Limited] We request you to kindly take the above information on record.
- `BRAHMINFRA` p3 [Management of Brahmaputra Infra Ltd.] Management of Brahmaputra Infra Ltd. Invites you to the Q2 & H1 FY27 Earnings Conference Call To discuss the performance for the Quarter ended September 30, 2026 Day/Date
- `BRAHMINFRA` p3 [Management of Brahmaputra Infra Ltd.] The call access details will be sent to your registered email.
- `BRAHMINFRA` p3 [Management of Brahmaputra Infra Ltd.] On the day of the call, kindly log in using the link provided.
- `BRAHMINFRA` p3 [Management of Brahmaputra Infra Ltd.] Please note that pre- registration is mandatory to receive the call login details.

**speaker_moderator** - 7 statements, 7 docs

- `CAPACITE` p2 [Moderator] Ladies and gentlemen, good day, and welcome to Capacit'e Infraprojects Limited Q1 FY '25 Earnings Conference Call.
- `GPTINFRA` p14 [Moderator] Thank you. On behalf of GPT Infraprojects Limited, that concludes this conference. Thank you for joining us, and you may now disconnect your lines. Thank you.
- `GREENPLY` p16 [Moderator] On behalf of Asian Market Securities Private Limited, that concludes this conference.
- `KNRCON` p2 [Moderator] This conference call may contain forward-looking statements about
- `MAHABANK` p3 [Moderator] I am CFO – Vijay Srivastava, Bank of Maharashtra, together with me our GMs are there.
- `STARHEALTH` p2 [Moderator] Ladies and gentlemen, good day and welcome to Star Health and Allied Insurance Company Limited Q2 & H1 FY2025 Earnings Conference Call.
- `VINCOFE` p20 [Moderator] Overall, the performance during the quarter and the 9-month period reflects steady exeeution across operations and continued progress on our strategic priorities. While t

**speaker_not_a_person** - 0 statements, 0 docs


**short remarks** - 272 statements, 156 docs, by kind {'short_refer_back': 267, 'short_pointer': 5}

- `ACMESOLAR` p18 [Nikhil Dhingra] This is anybody's guess in terms of that.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p18 [Manoj Upadhyay] So that's a formula.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p20 [Nikhil Dhingra] This is on a generic overall portfolio level.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p20 [Nikhil Dhingra] And that's how you defer the capex.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p7 [Nikhil Dhingra] So that's how it is working.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p8 [Nikhil Dhingra] So that's how it will work.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p9 [Nikhil Dhingra] So that's another thing.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p9 [Nikhil Dhingra] So that is what is left.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p10 [Nikhil Dhingra] So that is there.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ACMESOLAR` p18 [Manoj Kumar Upadhyay] That is not factored into this merchant sale.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ADANIPOWER` p6 [S. B. Khyalia] So, it is still under bidding.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ADANIPOWER` p9 [Nishit Dave] So, it's not a very large number.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ALLCARGO` p13 [Deepak Pareek] Yes, that's right.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ALLCARGO` p7 [Ravi Jakhar] That is one aspect.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `APARINDS` p14 [Ramesh Iyer] So, that's where it's likely to land.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ASHIANA` p4 [Varun Gupta] Well, that is a matter of relative perspectives.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ASHIANA` p5 [Varun Gupta] This is just about online lead generation.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ASHIANA` p5 [Vikash Dugar] So that's how it has to be read.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ASHIANA` p9 [Varun Gupta] So, that's that.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_
- `ASHIANA` p13 [Varun Gupta] That's the general expectations right now.  _(short_refer_back: a sentence that only refers back, with no referent stored with it)_

## Graded R rows that change (target 0)

Pack rows evaluated against the rule functions; `regrade_fy27_r3`, `tx394_ckpt6` and `audit_tx394` also against `grades.csv`, `tx_fy27_surprise1` against its two part CSVs. `regrade_tx394_r4`, `tx394_ckpt7` and `tx394_ckpt8` have no per-row grades file on this laptop; the new rules change **no row at all** in those three packs, so no R row can change there.

| pack | graded rows | R rows | R changed | other changed (P/W/J) |
|---|---:|---:|---:|---:|
| regrade_fy27_r3 | 60 | 48 | 0 | 2 |
| regrade_tx394_r4 | no grades file | 0 | 0 | 0 |
| tx394_ckpt6 | 60 | 48 | 0 | 0 |
| tx394_ckpt7 | no grades file | 0 | 0 | 0 |
| tx394_ckpt8 | no grades file | 0 | 0 | 0 |
| audit_tx394 | 60 | 49 | 0 | 0 |
| tx_fy27_surprise1 | 60 | 45 | 0 | 7 |

Changed non-R rows (all intended: they are the cited J/W/P shapes):

- regrade_fy27_r3 n=24 grade=J `AUBANK` speaker_moderator - Thank you. On behalf of AU Small Finance Bank, that concludes this conference. Thank you for joining us and you may now disconnect your line
- regrade_fy27_r3 n=28 grade=W `AMTECH` speaker_moderator - We reached 40.7 crores of revenue in financial year 26, and in September 2026, we listed on the BSE SME platform.
- tx_fy27_surprise1 n=2 grade=P `ABSLAMC` short_refer_back - It's quite large.
- tx_fy27_surprise1 n=5 grade=J `BANDHANBNK` short_generic - We have done well.
- tx_fy27_surprise1 n=16 grade=J `BRIPORT` not_a_call - The Shareholders were informed that the Company has appointed Mr. Ravi Jain, Managing Director as Chairperson of the Company.
- tx_fy27_surprise1 n=24 grade=J `BIOCON` short_pointer - Kedar, I think his question was on products.
- tx_fy27_surprise1 n=25 grade=W `AFFORDABLE` speaker_not_a_person - New customer acquisition - As on 31st May 2026, our confirmed order book stands at approximately Rs.12,716 Lakhs.
- tx_fy27_surprise1 n=54 grade=W `AMTECH` speaker_moderator - Good afternoon, everyone, and thank you for joining us. This is our first earnings call since listing, and I am glad to have you with us. Fo
- tx_fy27_surprise1 n=56 grade=J `AMAGI` short_refer_back - So that's a meaningful swing.

## The six surprise-audit evidence rows

Scoped `--reparse` of the six documents into `.tmp/t242/fy27_evidence.db` (108 pages; stats: {"pages": 108, "rows_before": 1262, "rows_after": 1250, "speaker_resolved": 34, "speaker_empty": 24, "speaker_unverified": 119, "speaker_not_a_call": 5, "speaker_moderator": 11, "speaker_not_a_person": 0, "short_remarks": 12, "transcript_docs": 6, "not_call_docs": 1}):

| evidence | id | before | after |
|---|---:|---|---|
| BANDHANBNK p10 | 97335 | verified, Partha Pratim Sengupta | **dropped** (short_generic: 'We have done well.') |
| BRIPORT p2 | 113183 | verified, Company Secretary | **unverified** (not_a_call + speaker_generic) |
| BIOCON p20 | 107577 | verified, Shreehas Tambe | **dropped** (short_pointer: 'Kedar, I think his question...') |
| AFFORDABLE p27 | 71075 | verified, 'Profit After Tax' | **unverified**, speaker empty (the heading is no longer a speaker; speaker_unresolved) |
| AMTECH p3 | 77067 | verified, Moderator | **unverified** (speaker_moderator) |
| AMAGI p8 | 75286 | verified, Vijay NP | **dropped** (short_refer_back: "So that's a meaningful swing.") |

All six are dropped or unverified; 3 dropped, 3 unverified.

## Commands

```
python .tmp/t242/scan_rules.py            # in-process rule scan over both copy baselines
python .tmp/t242/check_r_rows.py          # graded packs against the rule functions
python .tmp/t242/run_reparse_only.py C:/RealityEngine/t242/reparse/fy27_v3_r3.db .tmp/t242/fy27_evidence.db C:/RealityEngine/tg_build/universe_fy27 .tmp/t242/evidence_sel.json
python -m pytest reality_engine/tests/test_obs_speaker.py reality_engine/tests/test_observations.py -q
python -m pytest reality_engine/tests/test_v2_guards.py -q
python -m reality_engine.v2.read_gate status   # transcript page prompt 12e603811501; v3 window 2fae7ddac53e
```
