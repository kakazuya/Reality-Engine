# TextRecognizer helper (Windows AI Imaging)

Source of the batch runner used by the large OCR accuracy test on the HP
OmniBook.  The engine is `Microsoft.Windows.AI.Imaging.TextRecognizer`; it only
answers from a **packaged, signed** process with package identity and the
`systemAIModels` capability, launched in the interactive user session.

| file | purpose |
|---|---|
| `Program.cs` | manifest in, one JSON row per PNG out (text, lines, line style, words with `MatchConfidence`, `TextAngle`, timings, box extent) |
| `textrec.csproj` | baseline build on Windows App SDK 1.8.260921001 |
| `experimental/textrec20.csproj` | separate build on Windows App SDK 2.0.0-experimental7, defines `TEXTREG_OPTIONS` to exercise `TextRecognizerOptions` |
| `pkg/AppxManifest.xml` | 1.8 package manifest (identity, `runFullTrust`, `systemAIModels`, execution alias) |

No binaries, certificates or keys live in the repo.  Build output, the signing
certificate and the test MSIX stay outside it.  Rebuild steps (plus the
experimental manifest override) are in
`tasks/ocr/TEXTREC_LARGE_TEST_2026-11-01.md`.

Manifest line format: a PNG path, or `{"id": "...", "path": "..."}`.  The
driver writes one JSON row per line, and `<out>.done` when the batch ends.
