# T-143 (pilot20 new 10): harvest investor questions for unseen companies, company-specific AND sector-standard/conceptual (web research, no code)

Ticket: T-143

Goal: for each company below, collect the questions real investors and analysts are asking about it right now, verbatim,
with the source link. Do NOT answer them and do NOT rewrite them. Opus will reframe them later.

Companies (NSE symbol, name): APOLLOTYRE Apollo Tyres Ltd (tyre maker; India and Europe via Apollo Vredestein)

Steps:
1. First, check that you can search the web (Google search tool or browser). Search once for
   "<first company name> share analysis questions". If you have no web access at all, stop at once and say so in one
   line: "NO WEB ACCESS: <what you tried>".
2. For each company, search at least these, newest first (2025-2026 preferred):
   - Google: "<name> share analysis", "<name> stock should I buy", "<name> concall questions", "<name> investor concerns",
     "<name> valuepickr", "<name> reddit IndianStockMarket", "<symbol> share news".
   - YouTube: "<name> share analysis", "<name> stock latest news", "<name> results analysis". Use video titles,
     descriptions, chapter titles and visible top comments (comments often hold the sharpest questions).
   - Forums: ValuePickr threads, Reddit (r/IndianStockMarket, r/IndiaInvestments, r/IndianStreetBets), Moneycontrol and
     Trendlyne message boards, X/Twitter posts if visible.
3. Keep a question when it is something an investor wants to know about THIS company (business, numbers, management,
   valuation, risks, sector, competition, policy effects, shareholding, price moves). A statement that implies a question
   ("margins will fall because of X") may be kept as the question it implies, marked `implied`.
   Skip: spam, broker target prices and buy/sell ratings, 'should I buy' posts, video titles that ask nothing, tips/targets with no question, duplicates (keep the clearest one, add the other link in `also_seen`).
4. Aim for 20-30 asked/implied questions per company from at least 6 different sources. Fewer is fine if the web has fewer; never
   invent one.
4b. VERIFY EVERY SOURCE: your search tool returns summaries, and links taken from summaries were found invented (a
   'Bajaj Finance' ValuePickr link opened a thread on another company). For each row, fetch the page with run_command
   (`curl -sL -A "Mozilla/5.0" --max-time 20 <url>`) and keep the row only if the page loads and its text contains the
   company name and the question's key words; put the fetched page title in `source_title` and `verified=yes`. A row
   whose page you could not fetch is dropped (count them). Reddit: use the `.json` form of the thread URL.
6b. SECOND KIND, standard and conceptual questions (after step 4, same CSV): for each company, find what sell-side
   analysts and experienced investors ask EVERY quarter about a company of this sector, and the conceptual questions
   about how its business works. Sources: earnings-call Q&A summaries and transcripts on the web (company site,
   Trendlyne/Screener concall notes, news write-ups of the call: "<name> concall Q&A", "<name> analyst call questions",
   "<name> Q2 FY27 earnings call highlights"), broker result notes' "key questions"/"what to watch", sector primers
   ("<sector> key metrics to track India", "how to analyse a <sector> company"). Examples of the kind (do not copy
   them, find the company's own): cement - EBITDA per tonne, realisation per tonne, capacity utilisation, fuel cost
   per tonne; retail - revenue per sq ft, like-for-like growth, store additions; NBFC - AUM growth by product, credit
   cost, Stage 2/3, cost of funds; airline - RASK/CASK ex fuel, load factor, grounded fleet; IT services - constant
   currency growth, deal wins TCV, utilisation, attrition; pharma - US generics price erosion, R&D % of sales,
   specialty pipeline; defence - order book to sales, execution, indigenisation; FMCG - volume vs price growth, gross
   margin, rural vs urban.
   Put each such row in the same CSV with kind `standard` (a metric/check analysts track for the sector, phrased for
   THIS company, e.g. "What was UltraTech's EBITDA per tonne in Q2 FY27 and how did it move?") or `conceptual` (how the
   business works or what drives it, e.g. "How much of Trent's growth comes from new stores vs existing ones?").
   Aim for 15-25 per company; each needs a source you fetched that shows the metric or question for this company or
   sector (same verification as 4b; a sector primer counts for `standard`). Never invent a figure.
5. Write one CSV file `.tmp/t143_questions_apollo.csv` (UTF-8, header row), columns:
   `symbol, question, kind (asked|implied|standard|conceptual), source_type (youtube|google_article|valuepickr|reddit|forum|x|other),
   source_title, url, source_date (YYYY-MM-DD or blank), also_seen (other urls, ; separated), verified`.
   Quote the question text as it appears (translate Hindi/Hinglish to English and add `[translated]` at the end).
6. Final answer: per company, count of questions and sources; the 5 most common themes per company; any site you could
   not open. Then the CSV path.

Files: only `.tmp/t143_questions_apollo.csv` (create it). Do not edit any repo file.
Accept: CSV exists, every row has a real url you opened or saw in search results, no invented questions.
Evidence: none needed from the repo; this is web research.
Stop if: no web access (step 1); or a site asks for a login or captcha (skip that site, note it, carry on).
Budget: 120 tool calls, 50 minutes.
Limits: no code changes, no installs, no logins, no paid services, no posting anywhere.
