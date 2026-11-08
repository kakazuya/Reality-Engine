# T-116: harvest questions real investors ask about our test companies (web research, no code)

Ticket: T-116

Goal: for each company below, collect the questions real investors and analysts are asking about it right now, verbatim,
with the source link. Do NOT answer them and do NOT rewrite them. Opus will reframe them later.

Companies (NSE symbol, name): {COMPANIES}

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
   Skip: spam, tips/targets with no question, duplicates (keep the clearest one, add the other link in `also_seen`).
4. Aim for 25-40 questions per company from at least 6 different sources. Fewer is fine if the web has fewer; never
   invent one.
4b. VERIFY EVERY SOURCE: your search tool returns summaries, and links taken from summaries were found invented (a
   'Bajaj Finance' ValuePickr link opened a thread on another company). For each row, fetch the page with run_command
   (`curl -sL -A "Mozilla/5.0" --max-time 20 <url>`) and keep the row only if the page loads and its text contains the
   company name and the question's key words; put the fetched page title in `source_title` and `verified=yes`. A row
   whose page you could not fetch is dropped (count them). Reddit: use the `.json` form of the thread URL.
5. Write one CSV file `.tmp/t116_questions_{PART}.csv` (UTF-8, header row), columns:
   `symbol, question, kind (asked|implied), source_type (youtube|google_article|valuepickr|reddit|forum|x|other),
   source_title, url, source_date (YYYY-MM-DD or blank), also_seen (other urls, ; separated), verified`.
   Quote the question text as it appears (translate Hindi/Hinglish to English and add `[translated]` at the end).
6. Final answer: per company, count of questions and sources; the 5 most common themes per company; any site you could
   not open. Then the CSV path.

Files: only `.tmp/t116_questions_{PART}.csv` (create it). Do not edit any repo file.
Accept: CSV exists, every row has a real url you opened or saw in search results, no invented questions.
Evidence: none needed from the repo; this is web research.
Stop if: no web access (step 1); or a site asks for a login or captcha (skip that site, note it, carry on).
Budget: 200 tool calls, 55 minutes.
Limits: no code changes, no installs, no logins, no paid services, no posting anywhere.
