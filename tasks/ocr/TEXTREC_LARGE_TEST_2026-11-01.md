# Windows AI `TextRecognizer` — larger accuracy test with its settings (2026-11-01)

**Answer first.** The most accurate way found on this HP is **300 DPI with a
grayscale conversion**, then `Microsoft.Windows.AI.Imaging.TextRecognizer` at
its defaults: tune rank **0.9680** vs the 200-DPI no-clean-up baseline
**0.9640**, table-number recall **0.9728** (baseline 0.9645), table-number
precision **0.9761** (baseline 0.9766), table-word F1 0.9797 (baseline 0.9786),
and 0.8131 of the scanned filings' XBRL facts found (baseline 0.8103).  It runs
at **126.1 OCR pages/min** (baseline 149.5).  Tiling at 300–400 DPI recovers the
most figures (recall 0.9829–0.9835) but loses 5 points of word accuracy, 2 points
of number precision and 10 tiles fail deterministically, so it is not frozen.
`ImageScaler` upscaling is blocked on this machine (exact error below).
Four of the five clean-up levers made accuracy worse or flat; grayscale is the
only keeper.

The engine **does run here** from a signed MSIX with package identity, launched
in the interactive session by a scheduled task (execution alias): the engine
needs the logged-on user's session, nothing else does.  An unpackaged process
still gets `E_ACCESSDENIED`; that is the earlier doc's result, not this one.
**From the headless fix (Section 14) the helper is a GUI-subsystem `WinExe` and
the task is registered hidden**, so the interactive logon no longer puts a
console window on the screen.

Two settings are frozen (Section 9): the baseline `base200` and the tuned
`gray300`.  The test rows are in `C:\RE\ocr_large\rows\<setting>\`.

## 1. Inputs and method

* Sample: `C:\RE\ocr_large\sample.json` — 1,300 digital page ids (326 `tune`,
  974 `test`) and 150 scanned filings (33 tune / 235 pages, 117 test / 852
  pages).  Tune truth: `truth/<id>.txt` for digital pages and
  `scan_xbrl_truth.json` for scanned filings.  The scorer is
  `C:\RE\ocr_large\score_large.py`, unchanged.
* Render: pypdfium2, `scale = dpi / 72`, highest four worker processes for CPU
  rendering (the limit in the brief).  Every digital tune page at every DPI is
  one row; scanned filings contribute every page, id `<pdf>#<page>`.
* OCR: the packaged helper (`reality_engine/tools/textrec/`) reads a manifest of
  PNGs and writes one JSON row per image.  It is started by
  `Register-ScheduledTask -LogonType Interactive` with the package execution
  alias as the action, from the one helper
  `hp_ocr_large.interactive_task_script()`; the driver waits for `<out>.done`.
  One NPU process at a time.  (From the headless fix, Section 14: the action is
  a GUI-subsystem EXE whose PE header the driver checks first, and the task is
  registered hidden.)
* Batches: 200 images normally (25 for adaptive B&W after the hang described in
  Section 5).  Failed rows are re-run in a fresh process up to 2 times; the
  frozen test batches use the same rule.  A per-image 120 s timeout was added
  after one 13-minute hang (Section 5); the same page succeeded on the next
  process in 2 s, so the stall is transient, not page-specific.
* Scores are `score_large.py tune`.  `rank` is the unweighted mean of the F1 of
  table numbers, table words, table Roman numerals, prose numbers, prose words
  and prose Roman numerals; `R/P` below is recall/precision.
* Pages/min is the helper's own batch seconds (OCR only, rendering excluded),
  matching the earlier HP OCR docs.

## 2. Helper output (what was added)

`Program.cs` now emits per page: `text`, `width`/`height`, `max_box_x`/
`max_box_y` (the extent of the returned boxes, used below), `angle`
(`TextAngle`), `line_rows[]` with `text`, `box`, `style`
(`RecognizedLineStyle`) and `style_confidence`, and per line `words[]` with
`text`, **`confidence`** (`MatchConfidence`) and `box`; plus per-image
`seconds`, `cpu_seconds`, `modules`, `error`.  A `<out>.done` sentinel carries
the batch totals.

Observed on 29,854 lines from the 326 tune pages (300 DPI grayscale):

* `TextAngle` = **0.0 on all 326 pages**.
* `style` = **`Handwritten` on all 29,854 lines**, `style_confidence` constant
  **0.0208**.  The public enum in 1.8/2.6 only defines `Handwritten`, so the
  line-style field carries no useful signal on printed filings; it is recorded
  but not used.
* Word confidences are usable: 13,297 number tokens, 1.51% wrong (Section 6).

## 3. Levers — all tune scores

All runs are the full 326 tune digital pages unless the row says otherwise.
`base200` is the required baseline: all 561 tune pages (326 digital + 235
scanned), 200 DPI, no clean-up.

| setting | pages | OCR pages/min | rank | table num R/P | prose num R/P | table words R/P | Roman R/P | scan XBRL found | failed rows |
|---|---:|---:|---:|---|---|---|---|---:|---:|
| `base200` (baseline) | 561 | 149.5 | 0.9640 | 0.9645/0.9766 | 0.9949/0.9182 | 0.9786/0.9787 | 0.9511/0.9904 | 0.8103 | 0 |
| `dpi150` | 326 | 168.7 | 0.9644 | 0.9549/0.9741 | 0.9975/0.9184 | 0.9701/0.9787 | 0.9327/0.9935 | — | 0 |
| `dpi300` | 326 | 126.6 | 0.9665 | 0.9710/0.9754 | 0.9949/0.9140 | 0.9826/0.9784 | 0.9450/0.9841 | — | 0 |
| `dpi400` | 326 | 104.2 | 0.9599 | 0.9434/0.9727 | 0.9899/0.9136 | 0.9753/0.9759 | 0.9388/0.9808 | — | 8 |
| `c300_gray` | 326 | 126.1 | **0.9680** | 0.9728/0.9761 | 0.9924/0.9138 | 0.9819/0.9776 | 0.9541/0.9936 | — | 0 |
| `c300_contrast` | 326 | 126.7 | 0.9655 | 0.9728/0.9767 | 0.9924/0.9053 | 0.9818/0.9780 | 0.9541/0.9936 | — | 0 |
| `c300_unsharp` | 326 | 127.2 | 0.9636 | 0.9715/0.9747 | 0.9949/0.9118 | 0.9808/0.9779 | 0.9358/0.9839 | — | 0 |
| `c300_bw` (adaptive) | 326 | 126.1 | 0.9577 | 0.9654/0.9702 | 0.9899/0.9072 | 0.9736/0.9742 | 0.9297/0.9870 | — | 0 |
| `c300_deskew` | 326 | 124.6 | 0.9661 | 0.9709/0.9751 | 0.9924/0.9116 | 0.9826/0.9783 | 0.9450/0.9841 | — | 0 |
| `scale150x2` (fallback) | 326 | 161.6 | 0.9644 | 0.9549/0.9741 | 0.9975/0.9184 | 0.9701/0.9787 | 0.9327/0.9935 | — | 0 |
| `scale200x2` (fallback) | 326 | 152.6 | 0.9640 | 0.9645/0.9766 | 0.9949/0.9182 | 0.9786/0.9787 | 0.9511/0.9904 | — | 0 |
| `tile300` | 326 | 72.2 | 0.9130 | 0.9829/0.9576 | 0.9924/0.8809 | 0.9268/0.9043 | 0.8991/0.8647 | — | 10 tiles |
| `tile400` | 326 | 59.7 | 0.9169 | 0.9835/0.9558 | 0.9924/0.8789 | 0.9278/0.9041 | 0.8991/0.8547 | — | 10 tiles |
| `exp20_gray300` (2.0 build) | 326 | 123.4 | 0.9680 | 0.9728/0.9761 | 0.9924/0.9138 | 0.9819/0.9776 | 0.9541/0.9936 | — | 0 |
| `scan300` (scanned only) | 235 | 119.0 | — | — | — | — | — | 0.8140 | 0 |
| `scan300gray` (scanned only) | 235 | 120.1 | — | — | — | — | — | 0.8131 | 0 |

`base200` is the only row scored on both digital and scanned tune pages; the
`—` cells were not run for that lever.  `scale150x2`/`scale200x2` are the
unscaled fallback (the scaler never ran — Section 4); their scores are the
150/200 DPI baselines and are not treated as a scaler result.

### 3.1 DPI

300 DPI wins the rank and table-number recall; 150 DPI is the fastest.  400 DPI
is worse on every metric and **fails on 8 pages**, all 10667×6000 px wide-spread
pages:

```
NullReferenceException: Object reference not set to an instance of an object.
```

Those 8 ids: D00104, D00142, D00144, D00232, D00264, D00400, D00626, D01178.
The same pages at 300 DPI are 8001×4500 and succeed.  So the practical ceiling is
between 24 and 64 megapixels; the engine does not silently downscale these — it
throws.

**Can a downsize be observed?**  Only indirectly.  The returned boxes are in
input pixel coordinates at every DPI (`max_box_x / width` is 0.92–0.93 at 150,
200, 300 and 400 DPI), and no API reports a scale factor.  If the engine
downscales internally it maps boxes back, so the only observable limit is the
24–64 MP failure boundary above.

### 3.2 Clean-up

Grayscale is the only clean-up that helps: rank 0.9680 vs 0.9665 at 300 DPI, and
table-number recall +0.18 pt.  Contrast stretch gives the best number precision
(0.9767) but loses prose precision (0.9053 vs 0.9138 for grayscale); unsharp,
adaptive B&W and deskew all reduce the rank.  Deskew is neutral on digital pages
(they are already straight) and costs 1.5 pages/min.

Adaptive B&W is also a stability outlier: one 200-image batch **hung** (process
alive, 4.6 s CPU, no row for 13 minutes).  Re-run in 25-image batches it
completed 326/326 at the score above.  The hang is recorded as a lever risk, not
as a per-page failure.

### 3.3 Overlapping tiles

4 tiles (2×2, 10% overlap) at 300 and 400 DPI, lines shifted into page
coordinates, duplicate lines suppressed by box IoU/text and seam fragments
joined.  Tiling gives the **best number recall of any setting** (0.9829 at 300,
0.9835 at 400) but the worst words/roman of the non-fallback settings and 10
tiles throw the same `NullReferenceException` (1819×2572–3638×2572 px, not
large).  Two retries do not fix them; the page halves behind those tiles are
missing.  At 400 DPI it is 59.7 pages/min.  Rejected as a frozen setting.

## 4. `ImageScaler` — blocked, exact error

Both requested runs (2× on 150 and 200 DPI) fell back to the unscaled image
because `ImageScaler.CreateAsync()` failed at the package boundary:

```
ImageScaler unavailable COMException: Package dependency criteria could not be resolved.
```

The helper records this in `<out>.done.scaler`, logs it, sets `scale=0` and
continues, so the two rows in Section 3 are the plain 150/200 DPI results.  The
MSIX declares only the 1.8 Windows App Runtime dependency; the AI image-scaler
model/dependency is not resolvable from this package.  This lever is therefore
**not measured**, not "no gain".

## 5. Windows App SDK 2.0 experimental — `TextRecognizerOptions`

A separate build (`experimental/textrec20.csproj`, Windows App SDK
`2.0.0-experimental7`, `TEXTREG_OPTIONS`) was published self-contained (the 2.0
AI native DLLs travel in the package) and installed as `RETextRecBench20`; it
starts, has identity, and reaches `ready_state=Ready`.  `TextRecognizerOptions`
exposes two properties on this build:

| test | result |
|---|---|
| `DetectorOutputGeometryMode` = `BoundingBox` | accepted, no error |
| `= Polygon` | accepted, no error |
| `= Quadrilateral` | accepted, no error |
| `= None` | accepted, no error |
| `= Default` (constructor default) | baseline |
| `EnableWordLevelConfidence = true` (default) | real confidences, 0.541–0.997 |
| `EnableWordLevelConfidence = false` | words still returned, **every MatchConfidence = 0** |

All geometry values produced **identical output** on the same two pages (88
lines, 198 words, same first-line box `[236, 225, 714, 268]`).  The native
imaging DLL contains the diagnostics *"Velocity key for geometry mode
configuration is not enabled"* and *"Velocity key for confidence configuration
is not enabled"*, which fits the no-op: the options are behind a feature flag on
this build.  A full 326-page tune run of the 2.0 build at the winning setting
(`exp20_gray300`, `geometry=BoundingBox;wordconf=1`) scored **exactly** the 1.8
result (rank 0.9680, same R/P, 0 failed rows), so the 2.0 engine itself is not
different on this box.  The API is worth re-testing when the Velocity gate is
open; it is not a lever today.

## 6. Confidence of number tokens (best setting, tune digital pages)

13,297 number tokens extracted, **201 wrong (1.51%)**.  A token is counted wrong
when its comma-normalised value is absent from the page's truth text numbers.

| confidence band | tokens | wrong | share wrong |
|---|---:|---:|---:|
| 0–0.5 | 38 | 17 | 0.4474 |
| 0.5–0.67 | 169 | 49 | 0.2899 |
| 0.67–0.8 | 78 | 10 | 0.1282 |
| 0.8–0.9 | 220 | 19 | 0.0864 |
| 0.9–0.95 | 305 | 20 | 0.0656 |
| 0.95–0.99 | 5,478 | 57 | 0.0104 |
| 0.99–1 | 7,009 | 29 | 0.0041 |

What a cutoff would send for checking, and how much of the error it catches:

| cutoff | share of tokens sent | share of wrong tokens caught |
|---:|---:|---:|
| 0.50 | 0.0029 | 0.0846 |
| 0.67 | 0.0156 | 0.3284 |
| 0.80 | 0.0214 | 0.3781 |
| 0.90 | 0.0380 | 0.4726 |
| 0.95 | 0.0609 | 0.5721 |
| 0.99 | 0.4729 | 0.8557 |

Practical reading: a 0.95 cutoff sends 6% of number tokens and catches 57% of
the errors; going to 0.90 saves 3.8% of tokens but misses half the errors.  The
band 0.95–0.99 still holds 57 wrong tokens, so "above 0.95" is not safe for
blind extraction.

## 7. Flag-only checks (never change `text`)

### 7.1 Letters inside numeric tokens

Tight rule: token of 2–8 chars with a digit and a confusable letter
(`O o I l L S s Z z B b`), excluding fiscal labels (`FY23`, `Q1FY24`, `H1`),
ordinals (`1st`) and unit suffixes (`kg`, `mm`, …).  On the 326 tune pages:

* **31 flags, 3 true errors, 28 false alarms** (9.7% precision).  Examples:
  `235l` (truth `2351`), `0.00l` (truth `0.001`), `S1.`.
* The broad version (any letter + digit, length ≤ 8) flagged 1,830 tokens with
  221 true errors and 1,609 false alarms — 88% noise, dominated by `1st`,
  `Q1FY23`, `FY24`.  Do not deploy the broad rule.

### 7.2 Column totals that do not add up

Heuristic: a line containing "total" with ≥2 numeric columns whose value differs
by >0.5% from the sum of the nearest numeric cell in the preceding ≤6 rows, per
column.  On tune pages:

* **15 flags, 0 true errors, 15 false alarms.**  Every flag was a legitimate
  subtotal/restated row (the OCR total matched the truth), so this check is not
  usable as written.  It needs a table model (columns, subtotal hierarchy), not
  row arithmetic.

## 8. Scanned page: render, not the hidden text layer

Tune page `ANURAS/quarterly_results/b2c2d088-…pdf#0`, rendered at 300 DPI:
image 2480×3509, **6.7% dark pixels** (not blank), OCR 2,172 chars, hidden text
layer 2,268 chars.  The OCR output follows the **visual** order — it reads the
two addresses "To, To, BSE Limited, National Stock Exchange of India Limited,
Phiroze Jeejeebhoy Towers, / 'Exchange Plaza', …" — while the hidden layer is a
single sequential column.  Only the PNG is handed to the helper, so the text
came from the rendered image; the layer is present but unused.

## 9. Frozen settings and reasons

| setting | config | why frozen |
|---|---|---|
| `base200` | 200 DPI, no clean-up | Required baseline; the reference for every lever and the only setting measured on all 561 tune pages including scans. |
| `gray300` | 300 DPI, grayscale, defaults | Best tune rank (0.9680), best table-number recall of the non-tiled settings (0.9728), table-number precision flat (0.9761), best words/roman balance, 126.1 pages/min, 0 failures, 0.8131 scan XBRL. Grayscale is also the cheapest clean-up. |

Rejected: tiling (best figure recall, but −5 points words, −2 points number
precision, 10 dead tiles, half the speed); 400 DPI (8 hard failures); contrast,
unsharp, B&W, deskew (all rank below grayscale); `ImageScaler` (blocked);
2.0 options (no-op).  Only two settings are frozen, not three, because no
second tuned setting improved the rank without a material loss elsewhere.

## 10. Test run

Run once per frozen setting over **every** test page: 974 digital ids and all
852 pages of the 117 test scanned filings (1,826 rows per setting).

| setting | rows | missing ids | failed rows | OCR seconds | OCR pages/min |
|---|---:|---:|---:|---:|---:|
| `base200` | 1,826 | 0 | 0 | 765.7 | 143.1 |
| `gray300` | 1,826 | 0 | 0 | 891.4 | 122.9 |

Outputs:

* `C:\RE\ocr_large\rows\base200\test.jsonl`
* `C:\RE\ocr_large\rows\base200\test_words.jsonl`
* `C:\RE\ocr_large\rows\gray300\test.jsonl`
* `C:\RE\ocr_large\rows\gray300\test_words.jsonl`

`test_words.jsonl` is the sibling confidence file: `{"id": ..., "words":
[{"text", "confidence", "box"}]}`.  The test rows were not scored here (the test
keys are not on this machine) and were not re-run with another setting.

## 11. Rebuild the signed package

Working directory below: the checkout you are editing (the headless run used
`C:\RE\jobs\hp-20261101T172002-15e0f2\repo`).  The .NET 8
SDK is at `C:\RE\dotnet\dotnet.exe`; the Windows SDK build tools are at
`C:\RE\bench\sdkbuildtools\bin\10.0.26100.0\arm64\{makeappx,signtool}.exe`.

```powershell
# 1. build the 1.8 helper
C:\RE\dotnet\dotnet.exe publish reality_engine\tools\textrec\textrec.csproj -c Release `
  -r win-arm64 --self-contained false -p:BaseIntermediateOutputPath=<build>\obj\ `
  -p:BaseOutputPath=<build>\bin\ -o <build>\pkg

# 2. manifest + assets in <build>\pkg (repo holds pkg\AppxManifest.xml and Assets)
Copy-Item reality_engine\tools\textrec\pkg\AppxManifest.xml <build>\pkg\AppxManifest.xml

# 3. self-signed test certificate, trusted machine-wide, then pack + sign
$cert = New-SelfSignedCertificate -Type Custom -Subject "CN=REBench" -KeyUsage DigitalSignature `
  -FriendlyName "RE TextRec Bench" -CertStoreLocation Cert:\CurrentUser\My `
  -TextExtension @("2.5.29.37={text}1.3.6.1.5.5.7.3.3","2.5.29.19={text}")
Export-PfxCertificate -Cert $cert -FilePath <build>\rebench.pfx -Password (ConvertTo-SecureString 'reb-2026' -AsPlainText -Force)
Export-Certificate -Cert $cert -FilePath <build>\rebench.cer
Import-Certificate -FilePath <build>\rebench.cer -CertStoreLocation Cert:\LocalMachine\Root
Import-Certificate -FilePath <build>\rebench.cer -CertStoreLocation Cert:\LocalMachine\TrustedPeople
& makeappx pack /d <build>\pkg /p <build>\textrec.msix /o
& signtool sign /fd SHA256 /a /f <build>\rebench.pfx /p reb-2026 <build>\textrec.msix
Add-AppxPackage -Path <build>\textrec.msix -ForceUpdateFromAnyVersion

**Over SSH, `Add-AppxPackage` fails with `0x80070005`** (in the SSH session and in a hidden S4U task
alike): the AppX Deployment PLM cannot initialize without the interactive session. Since 11 Nov
(T-188) the install is done by a windowless `WinExe` (calls `PackageManager.AddPackageAsync`) started
as a hidden `-LogonType Interactive` task, so nothing appears on the screen; the certificate,
`makeappx` and `signtool` steps above work unchanged over the elevated SSH session. Measured
details: `machines/HP_LAPTOP.md` ("Installing it headless").

# 4. PE-check, then run a batch in the interactive session (the only way the
#    engine answers).  The driver does both; shown here so nobody runs a console
#    build by hand.
python -m reality_engine.scripts.hp_ocr_large run --name smoke --split test `
  --only digital --dpi 300 --variant gray --limit 20
# It resolves the installed package's EXE, refuses a non-GUI one (PE subsystem
# != 2), registers RETextRecBench hidden with the interactive logon the engine
# requires, starts it and waits for <out>.done.  Progress is in
# %LOCALAPPDATA%\RETextRecBench\status.log, because the helper has no console.
```

The 2.0 experimental package uses the same certificate and
`experimental/AppxManifest.xml` (identity `RETextRecBench20`, alias
`textrec20.exe`) and is **self-contained**:

```powershell
C:\RE\dotnet\dotnet.exe publish reality_engine\tools\textrec\experimental\textrec20.csproj `
  -c Release -r win-arm64 --self-contained false -p:WindowsAppSDKSelfContained=true `
  -p:BaseIntermediateOutputPath=<build20>\obj\ -p:BaseOutputPath=<build20>\bin\ -o <build20>\pkg
# then pack/sign/install as above (no PackageDependency in its manifest)
```

**Cleanup when finished** (this run did it, see Section 13):
`Remove-AppxPackage RETextRecBench; Remove-AppxPackage RETextRecBench20`, delete
the PFX/CER and remove the certificate from
`Cert:\LocalMachine\Root` and `Cert:\LocalMachine\TrustedPeople` by thumbprint,
then `Unregister-ScheduledTask RETextRecBench` and `RETextRecBench20`.

The package used for the frozen runs is **1.0.1.0** (the per-image timeout was
added after a 13-minute hang); 1.0.0.9 lacked it.

## 12. Changed code files

* `reality_engine/tools/textrec/Program.cs` — helper: word rows (`MatchConfidence`,
  box), line style/`style_confidence`, `TextAngle`, image/box extent, JSON
  manifest ids, `--scale`, `--options`, per-image timeout, `<out>.done`; now a
  console-free GUI subsystem, so every line it printed goes to `status.log`, and
  `.done` plus a nonzero exit code carry a failure.
* `reality_engine/tools/textrec/textrec.csproj` — 1.8 build, `OutputType=WinExe`.
* `reality_engine/tools/textrec/pkg/AppxManifest.xml` — 1.8 identity/capabilities.
* `reality_engine/tools/textrec/experimental/textrec20.csproj` — 2.0 experimental
  build (`TEXTREG_OPTIONS`).
* `reality_engine/tools/textrec/experimental/AppxManifest.xml` — 2.0
  self-contained identity/capabilities.
* `reality_engine/tools/textrec/README.md` — source layout and run notes.
* `reality_engine/scripts/hp_ocr_large.py` — driver: render/variants/tiles,
  scheduled-task launch, retries/timeout, scoring, confidence and flag reports,
  test publisher; the one interactive-task helper (`interactive_task_script()`,
  hidden settings), the PE subsystem guard, and `.done` error raising.
* `reality_engine/tools/textrec/probe/probe.csproj`,
  `reality_engine/tools/textrec/probe/HeadlessProbe.cs` — windowless evidence
  probe run in session 1 (foreground window, every `WS_VISIBLE` watched window,
  session process table at 100 ms).
* `reality_engine/tools/textrec/probe/summarise.py` — the acceptance counts from
  a probe log.
* `reality_engine/scripts/hp_run.py`, `reality_engine/scripts/hp_worker.py` — the
  WMI detach now passes hidden start-up info (`Win32_ProcessStartup.ShowWindow=0`).
* `plugins/dsh-worker/server/supervisor.py` — same hidden start-up info for the
  detached supervisor.
* `reality_engine/tests/test_hp_headless.py` — the guard: `WinExe` projects, no
  interactive task outside the one helper, hidden `Start-Process`/WMI, and the
  driver's PE check.  No HP and no build needed.

Earlier helper at `C:\RE\bench\textrec\` is left in place for reference; the repo
copy is now the source of truth and the only copy without binaries.

## 13. Cleanup and open problems

* **Headless-run cleanup (1 Nov, Section 14), confirmed by command:**
  `RETextRecBench` uninstalled (0 packages), the `RETextRecBench` and
  `RETextRecProbe` tasks unregistered (0 tasks), the test certificate
  (thumbprint `746E613EDC0129ED897ABCB5DB207ED3D7309EAA`) removed from
  `Cert:\LocalMachine\Root`, `Cert:\LocalMachine\TrustedPeople` and
  `Cert:\CurrentUser\My` (0 in each), PFX/CER deleted and the WindowsApps alias
  gone.  `C:\RE\ocr_large\rows` still holds only `base200` and `gray300`.
* MSIX packages and the test certificate **were removed after the runs**: both
  `RETextRecBench` (1.0.1.0) and `RETextRecBench20` were uninstalled, the PFX/CER
  deleted, and the self-signed certificate (thumbprint
  `E0F9B063D307E16536D7B494A7E8B1C11A4E639A`) removed from
  `Cert:\LocalMachine\Root`, `Cert:\LocalMachine\TrustedPeople` and
  `Cert:\CurrentUser\My`; the two scheduled tasks were unregistered.  The repo
  holds source only (no binaries, PFX/CER or keys).
* `ImageScaler` needs the missing AI model/dependency inside the package — not
  measured.
* Tiling loses content on 10 deterministic tiles; a shifted second grid would
  probably recover them but was not run.
* The engine hangs rarely (one 13-minute stall on an ordinary page and once on a
  B&W batch).  The per-image timeout records a timeout row rather than a result;
  the test batches count those as rows with `error` when they occur.
* The confidence bands are measured on tune digital pages only; scanned pages
  have no per-page truth on this machine, so their confidence is untested.
* The totals flag needs a table model; the current arithmetic check has 0 true
  catches and 15 false alarms.

## 14. Headless fix (Shivam's ruling, 1 Nov 2026): nothing on the screen

**The ruling.** No work may come onto the HP laptop's screen: it distracts the
person using the laptop and takes keyboard focus.  All HP work runs headless.
`textrec.exe` was a console program started in the interactive session by a
scheduled task, so every batch opened a console window.  The same job that
produced this doc built it that way; this section is the fix and its proof.

### 14.1 Audit: every way HP work could reach the interactive session

| launcher | where | session | can it show a window? | fix |
|---|---|---|---|---|
| `interactive_task_script()` — `New-ScheduledTaskAction` (execution alias) + `New-ScheduledTaskPrincipal -LogonType Interactive` + `Register-ScheduledTask` + `Start-ScheduledTask` | `hp_ocr_large.py` | 1 — the engine requires it | **Yes**: the action was a console-subsystem `textrec.exe`, so every batch opened a console window and could take focus | `OutputType=WinExe` in both csproj files; the driver reads the *installed* EXE's PE header and refuses subsystem ≠ 2 before every launch; the task is registered `-Hidden`; this is now the only place that starts an interactive task; all console output moved to `status.log` + `.done` |
| `schtasks /Create /TR <job>\run.cmd /RU SYSTEM` | `hp_run.py` | 0 (SYSTEM) | No: service session, no interactive token; the wrapper writes `job.log` | unchanged; the guard now refuses any `schtasks /Create` that is not `/RU SYSTEM` |
| WMI `Win32_Process.Create "cmd /c run.cmd"` | `hp_run.py`, `hp_worker.py`, `plugins/dsh-worker/server/supervisor.py` | the caller's (0 over SSH; 1 if started from the desktop) | **Yes if the caller is in session 1**: no window hint was passed | hidden start-up info: `Win32_ProcessStartup.ShowWindow = 0` |
| `Start-Process cmd.exe … -WindowStyle Hidden` | `hp_run.py` `--method start` | 0 over SSH | No: already a hidden window style | unchanged; the guard requires `-WindowStyle Hidden` on every `Start-Process` |
| `RE_hpjob_surv_schtasks`, `RE_hpjob_surv_schtasks2`, `RE_hpjob_surv_start`, `RE_hpjob_surv_wmi` (existing tasks) | this machine, made by this project | 0 (SYSTEM `ServiceAccount`) | No: no interactive token, so nothing can appear on the user's desktop | audited, not changed |
| `RETextRecProbe` (evidence only) | this run | 1 | No: `probe.exe` is a `WinExe`, PE subsystem 2 | created for the run, unregistered afterwards |

No task outside `RE*`, and no task not made by this project, was changed or
deleted.  The WindowsApps execution alias is a reparse point, not a PE file, so
the PE check reads the packaged EXE (`(Get-AppxPackage RETextRecBench).InstallLocation\textrec.exe`).

### 14.2 PE header checked before anything entered session 1

```
textrec.exe  subsystem 2 (GUI)  C:\Program Files\WindowsApps\RETextRecBench_1.0.1.0_arm64__yxzf4xjhhje0p\textrec.exe
probe.exe    subsystem 2 (GUI)  C:\RE\ocr_large\probe\pkg\probe.exe
```

`hp_ocr_large.pe_subsystem()` / `assert_gui_subsystem()` do this; `start_batch()`
calls the guard on every chunk, so a build that regressed to a console EXE is
refused instead of launched.  The old (pre-fix) projects fail the same check:
reading the earlier checkout's `reality_engine/tools/textrec` with the guard's
csproj rule returns, for both files,
`OutputType=Exe, want WinExe`.

### 14.3 The 20-page run (gray300 render path)

Command (the package was rebuilt from these sources, signed with a new
self-signed test certificate and installed as 1.0.1.0 first):

```powershell
python -m reality_engine.scripts.hp_ocr_large run --name headless20b `
  --split test --only digital --dpi 300 --variant gray --limit 20
```

20 pages (`D00000`–`D00020`), 20 rows, 9.98 s of OCR, driver exit 0, task
`LastTaskResult` 0.  During the run two independent observers recorded:

| observer | where | result |
|---|---|---|
| `probe.exe` (`WinExe`, no console) | session 1, every 100 ms | **134 samples**, 0.100–0.127 s apart (max gap **127 ms**); **0** samples with a visible window owned by textrec/conhost/cmd/powershell/pwsh/python; **0** focus changes to them; `textrec.exe` pid 15168 seen in the session process table; **no `conhost.exe` at all** in session 1 |
| `Get-CimInstance Win32_Process -Filter "SessionId = 1"` | session 0, ~1 s | 29 polls; `textrec.exe` pid **15168**, parent **4008**, command line the alias with `--manifest … --out …`; **no** `conhost.exe`, `cmd.exe`, `powershell.exe`, `pwsh.exe` or `python.exe` in session 1 |

Text check: the 20 rows compared against `C:\RE\ocr_large\rows\gray300\test.jsonl`
by id — **20 compared, 0 differences** (`text` identical).

**Caveat, stated rather than hidden:** the desktop was locked for the whole run
(`LockApp.exe` in session 1, no foreground window, `visible_count` 0 in every
sample).  "0 visible windows" is therefore measured on a locked desktop, where a
window would also be invisible to a person.  The proof does not rest on that
alone: (a) a GUI-subsystem process cannot allocate a console, (b) no
`conhost.exe` existed in session 1 at any poll, and (c) the probe counts
`WS_VISIBLE` top-level windows *without* the DWM cloak filter, so a console
window created on a locked desktop would still have been counted.  A repeat with
the desktop unlocked was run afterwards; it is 14.7.

### 14.4 The check that keeps it fixed

`python -m pytest reality_engine/tests/test_hp_headless.py -q` → **9 passed**.
It needs no HP and no build, and it fails when:

* any csproj under `reality_engine/tools/textrec` is not `WinExe` (the self-test
  runs it against the old `OutputType=Exe` project and expects the failure);
* HP launcher code (`reality_engine/scripts/hp_*.py`, `reality_engine/tools/`)
  starts an interactive task or uses the interactive-task flag outside
  `hp_ocr_large.interactive_task_script()`, or that helper stops applying the
  hidden settings;
* a `schtasks /Create` is not `/RU SYSTEM`, a `Start-Process` is not hidden, or a
  WMI `Win32_Process.Create` passes no hidden start-up info;
* the driver's PE guard stops rejecting a console EXE.

### 14.5 What changed for the headless fix

`reality_engine/tools/textrec/textrec.csproj`,
`reality_engine/tools/textrec/experimental/textrec20.csproj` (`WinExe`),
`reality_engine/tools/textrec/Program.cs` (console-free: log + `.done` + nonzero
exit), `reality_engine/scripts/hp_ocr_large.py` (one hidden interactive-task
helper, PE guard, `.done` error handling, `--exe`/`--package`),
`reality_engine/tools/textrec/probe/{probe.csproj,HeadlessProbe.cs,summarise.py}`
(new evidence probe), `reality_engine/scripts/hp_run.py`,
`reality_engine/scripts/hp_worker.py`,
`plugins/dsh-worker/server/supervisor.py` (hidden WMI start-up info),
`reality_engine/tests/test_hp_headless.py` (new guard).  Docs:
`reality_engine/tools/textrec/README.md`, this doc, `tasks/STATE.md`.

### 14.6 Unlocked-desktop repeat — not run: the desktop was still locked (1 Nov, 18:15 IST)

Job `hp-20261101T181205-06ed5d` asked for the same proof with the desktop
unlocked.  It stopped before any package work, under the brief's own rule ("if it
is locked, stop and report").  Evidence:

| check | command | result |
|---|---|---|
| session | WTS `WTSEnumerateSessions` (`qwinsta` and `query.exe` are **not present** on this image, so the WTS API is the equivalent) | session 0 Disconnected, **session 1 Active** |
| lock flag | `WTSQuerySessionInformation(..., WTSSessionInfoEx)` for session 1 | `SessionFlags=0` = **WTS_SESSIONSTATE_LOCK** |
| foreground / windows | `probe.exe` (`WinExe`, hidden `RETextRecProbe` task in session 1, 100 ms, 8 s) | `foreground: null` in all **54** samples (max gap 114 ms), `visible_count=0`, `windows=[]` |
| lock-screen processes | session-1 process table from the probe | `LockApp.exe` pid 18572; `PhotoScreensaver.scr` pid 19308, parent `winlogon.exe` 2068 |
| PE pre-check | `hp_ocr_large.pe_subsystem()` | `textrec.exe` **2**, `probe.exe` **2** |

`LogonUI.exe` was not running, but the session flag and the null foreground agree
with the lock-screen processes: the session was locked, not merely idle.
Nothing was signed or installed and no `textrec` task was registered.  The probe
task was unregistered in the same command, then cleanup was confirmed by command:
**0** `RETextRecBench` packages, **0** `RETextRec*` tasks, **0** REBench
certificates in `LocalMachine\Root` / `TrustedPeople` / `CurrentUser\My`, no
`rebench.pfx` / `rebench.cer`, and **0** `textrec.exe` / `conhost.exe` in
session 1.  `C:\RE\ocr_large\rows` is untouched (`base200` 15:46, `gray300`
16:03).

The `headless20b` run in 14.3 remains the locked-desktop proof; the
unlocked-desktop repeat was run on the same evening and is in 14.7.

### 14.7 Unlocked-desktop repeat — desktop stayed unlocked (1 Nov, 20:05–20:10 IST)

Job `hp-20261101T200233-336f17`.  Shivam unlocked the HP at about 20:00 IST and
watched; nothing was allowed on the screen.  The flag is
`WTSQuerySessionInformationW(..., WTSSessionInfoEx)` for console session 1,
`SessionFlags` Int32 at byte offset 16 (method: `machines/HP_LAPTOP.md`).

| check | before | immediately before run | immediately after run | after cleanup |
|---|---|---|---|---|
| `SessionFlags` session 1 | **1** (unlocked) | **1** | **1** | **1** |

It was **never 0** at any point of this run, so this is an unlocked proof.
`LockApp.exe` pid 18572 was present at every check, which proves nothing either
way, as the brief says; the flag and the non-null foreground decide it.

Package: `textrec.msix` repacked from `C:\RE\ocr_large\textrec_build\pkg`, signed
with a new `CN=REBench` certificate (thumbprint
`40C2214BB5599D1C76F1D08D6EA794E563C11605`), installed as
`RETextRecBench_1.0.1.0_arm64__yxzf4xjhhje0p`.  The **installed** EXE's PE
subsystem was checked twice before any launch: driver `pe_subsystem()` **2**,
raw header **2**.

```powershell
python -m reality_engine.scripts.hp_ocr_large run --name headless20c `
  --split test --only digital --dpi 300 --variant gray --limit 20
```

20 pages, **20 rows**, 10.05 s of OCR, driver exit **0**, 14.8 s wall time.  A
hidden `RETextRecProbe` task ran `probe.exe` (`WinExe`) in session 1 from 1.8 s
before the batch until 0.9 s after it:

| probe result | value |
|---|---|
| samples | **164** (0.100–0.128 s apart, max gap **127.9 ms**) |
| foreground non-null | **164 / 164**, owner `explorer` every time (the real desktop; a locked session returns `null`, as 14.6 shows) |
| visible windows owned by textrec/conhost/cmd/powershell/pwsh/python | **0** |
| focus changes to those processes | **0** |
| `conhost.exe` | **none** in the session table at any poll |
| `textrec.exe` | pid **19204**, parent **4008** (Task Scheduler), no watched child |
| other visible window | one `chrome.exe` (pid 9928, Shivam's own YouTube window) at start and end — not a watched process, and focus never moved to one |

Text check: **20 compared, 0 differences** against
`C:\RE\ocr_large\rows\gray300\test.jsonl` by id (identical `text`).

Cleanup, each confirmed by command: package **0** (`Get-AppxPackage
RETextRecBench`), `RETextRec*` tasks **0** (`RETextRecBench` and
`RETextRecProbe` unregistered), certificate `40C2…1605` **0** in
`Cert:\LocalMachine\Root`, `Cert:\LocalMachine\TrustedPeople` and
`Cert:\CurrentUser\My`, `rebench.pfx` / `rebench.cer` **absent**, WindowsApps
alias **absent**, session 1 **0** textrec/conhost/cmd/powershell/pwsh/python.
`WindowsWorkload.TextRecognition.Qnn.1` (**1**) and the four
`RE_hpjob_surv_*` tasks were left in place, no screensaver/lock/power setting
was touched, and `C:\RE\ocr_large\rows` is untouched (`gray300\test.jsonl`
mtime 16:03:28).

**Tool defect found and fixed.**  `probe/summarise.py` compared the session
table's `conhost.exe` / `cmd.exe` names against the bare names in `WATCHED`, so
`conhost_pids_seen` and `watched_children_of_textrec` could never be non-empty:
the "no conhost" claim was unfalsifiable.  It now strips the `.exe` suffix
(`_base()`); re-run on both logs, the 17:37 locked run is unchanged (134
samples, foreground `(none)` in 134/134) and this run passes with
`watched_processes_present: ["textrec"]`.  `python -m pytest
reality_engine/tests/test_hp_headless.py -q` → **9 passed**.
