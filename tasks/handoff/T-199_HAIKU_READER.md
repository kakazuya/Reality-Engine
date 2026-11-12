# T-199 Haiku page reader: session instructions (one session = one batch folder of 8 pages)

Used verbatim as the prompt of each Haiku subagent session (Claude Code, Pro subscription, medium effort, under 100k
context). Replace `<BATCH>` with the batch folder. Tested 13 Nov on 8 deck pages (prototype `bluestar/proto/b000`);
the rules under "Page rules" fix what that test got wrong (KPI tiles skipped, invented column names, a comparative
figure written with its label inside the cell, legend names dropped).

---
You transcribe printed figures from 8 company filing pages. Folder: <BATCH>

For each file `<stem>.prompt.txt` in that folder:
1. Read `<stem>.prompt.txt` (instructions + the page's text laid out as printed) with the Read tool.
2. Read `<stem>.jpg` (the page image) with the Read tool.
3. Follow the prompt file's instructions using BOTH the image and the laid-out text, plus the page rules below.
4. Write only the TABLE/UNIT/COLUMNS/row lines to `<stem>.reply.txt` in the same folder with the Write tool
   (an empty file when the page prints no figures).

Page rules:
- Every printed figure counts: tables, KPI tiles/cards, chart labels, pie slices, bar labels, numbers in boxes. A page
  of tiles is one TABLE whose title is the page heading.
- Copy only what is printed. Never write a column header, label, period or unit the page does not print. A column
  with no printed header gets an empty header (`COLUMNS:  | Q2FY26` means the first column has none).
- One figure per cell. A comparative printed beside a figure ("Q2FY26: ₹1,664.21 cr") goes in its own column headed
  by the printed period ("Q2FY26"), cell "₹1,664.21 cr". A change marker ("▲ 16.3%", "up by 6%", "190 bps") goes in
  its own column with an empty header unless a header is printed.
- A label defined elsewhere on the page (a legend "Segment 1: EMP & Commercial Air Conditioning Systems", a footnote
  marker) is written as printed followed by the definition in brackets: `Segment 1 (EMP & Commercial Air Conditioning
  Systems)`.
- A chart or tile panel's printed title IS the row label of its figures ("Net Cash Position (₹ cr)" | 640 | 175).
- One figure per cell, never a sentence: a tile "4,120 Channel Partners (As at March 31, 2024)" becomes the row
  `Channel Partners (As at March 31, 2024) | 4,120`; "3 Year Revenue CAGR 16.9%" becomes `3 Year Revenue CAGR | 16.9%`.
  A tile without any figure is left out.
- A figure with no printed label anywhere near it (not even a panel title): leave the label empty; never make one up.
- When unsure of a digit, leave the cell empty. Never compute, convert, round or total.

Do one page at a time. Do not open any other folder. Do not use Bash. When all 8 reply files are written, answer
with one line per page: stem, number of tables, number of row lines, and any page you were unsure about.
