# Deck page reading — instructions for helper agents

Your folder holds pairs `NNNNN_image.jpg` (a slide) and `NNNNN_prompt.txt` (the exact task, with the page's PDF text layer).
For every pair, read the prompt, look at the image, and write the answer to `NNNNN.txt` in the same folder.
The file holds only the answer lines (`TITLE | ...` then `metric | period | number | unit`), nothing else.

Rules on top of the prompt:
- The image wins when its digits differ from the text layer (text layers are sometimes wrong). When the number is the
  same, keep the text layer's exact decimals and formatting.
- Figures shown with a down arrow (▼), in red as a decline, or labelled as a fall/decrease: write them as negative
  (e.g. ▼ 12% → -12%). Keep brackets as printed, e.g. (1.44).
- Skip product/model/certification codes, axis tick labels, page numbers, footnote markers, phone numbers, addresses,
  registration numbers and years used only as labels.
- metric must be the specific label (with the segment/product it belongs to); never the word "metric".
- Every image must get a `.txt` file, even if it holds only the TITLE line.
- A chart WITHOUT printed values (bars/lines/pies with only axis ticks): do not guess numbers. Add one line per chart:
  `CHART | <chart title or measure> | <periods or categories on the axis, e.g. FY19-FY24> | <rising/falling/flat/mixed, plus
  the largest and smallest category if clear>` (e.g. `CHART | Plastic consumption, KTA | 1990-2018 | rising, fastest
  after 2010`). These record the trend without inventing figures.

When finished, reply with one line: how many files you wrote.
