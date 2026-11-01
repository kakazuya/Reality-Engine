// Windows App SDK TextRecognizer batch runner for the OCR accuracy bench.
//
// Reads a manifest (one PNG per line: a path, or a JSON object with "id" and
// "path") and writes one JSON row per image: the page text, every detected
// line with its box, line style and style confidence, every word with its
// MatchConfidence and box, the TextAngle, timings, image size and the extent
// of the returned boxes.  The last field pair is how the Python driver sees
// whether the engine internally down-scaled a large image: if max_x is much
// smaller than the image width, the coordinates live in a smaller space.
//
// Runs only as a signed MSIX with package identity (see pkg/AppxManifest.xml);
// launch it from the interactive session, e.g. a scheduled task with /IT.
//
// Build variants:
//   textrec.csproj                 Windows App SDK 1.8 (the baseline build)
//   experimental/textrec20.csproj  Windows App SDK 2.0 experimental; defines
//                                  TEXTREG_OPTIONS so TextRecognizerOptions
//                                  (DetectorOutputGeometryMode + word-level
//                                  confidence) is exercised.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.Graphics.Imaging;
using Microsoft.Windows.AI;
using Microsoft.Windows.AI.Imaging;
using Windows.Graphics.Imaging;
using Windows.Storage;
using Windows.Storage.Streams;

internal static class Program
{
    private static string _logPath;

    private static void Note(string message)
    {
        try { File.AppendAllText(_logPath, $"{DateTime.Now:HH:mm:ss.fff} {message}\n"); }
        catch { /* logging must never kill the run */ }
    }

    private sealed class Item
    {
        public string Id;
        public string Path;
    }

    private static Item ParseItem(string line)
    {
        var text = line.Trim();
        if (text.Length == 0) return null;
        if (text.StartsWith("{"))
        {
            using var doc = JsonDocument.Parse(text);
            var root = doc.RootElement;
            var path = root.GetProperty("path").GetString();
            var id = root.TryGetProperty("id", out var idValue) ? idValue.GetString() : path;
            return new Item { Id = id, Path = path };
        }
        return new Item { Id = text, Path = text };
    }

    private static double[] LineBox(RecognizedTextBoundingBox box) => new[]
    {
        box.TopLeft.X, box.TopLeft.Y, box.BottomRight.X, box.BottomRight.Y,
    };

    private static async Task<int> Main(string[] args)
    {
        var logDir = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "RETextRecBench");
        Directory.CreateDirectory(logDir);
        _logPath = Path.Combine(logDir, "status.log");
        Note("start " + string.Join(" ", args));

        string manifest = null, outPath = null, options = null;
        int scale = 0, timeoutSeconds = 120;
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == "--manifest") manifest = args[i + 1];
            else if (args[i] == "--out") outPath = args[i + 1];
            else if (args[i] == "--scale") int.TryParse(args[i + 1], out scale);
            else if (args[i] == "--options") options = args[i + 1];
            else if (args[i] == "--timeout") int.TryParse(args[i + 1], out timeoutSeconds);
        }

        try
        {
            Note("identity=" + Windows.ApplicationModel.Package.Current.Id.FullName);
        }
        catch (Exception ex)
        {
            Note("identity=NONE " + ex.GetType().Name + ": " + ex.Message);
        }

        AIFeatureReadyState state;
        try
        {
            state = TextRecognizer.GetReadyState();
            Note("ready_state=" + state);
        }
        catch (Exception ex)
        {
            Note("GetReadyState FAILED " + ex.GetType().Name + ": " + ex.Message);
            return 3;
        }
        if (state != AIFeatureReadyState.Ready)
        {
            var started = Stopwatch.StartNew();
            var ready = await TextRecognizer.EnsureReadyAsync();
            Note($"ensure_ready={ready.Status} in {started.Elapsed.TotalSeconds:F1}s");
            Note($"ready_after={TextRecognizer.GetReadyState()}");
        }
        else
        {
            var ready = await TextRecognizer.EnsureReadyAsync();
            Note($"ensure_ready={ready.Status} (already ready)");
            Note($"ready_after={TextRecognizer.GetReadyState()}");
        }

        if (manifest == null || outPath == null)
        {
            Console.Error.WriteLine(
                "usage: textrec --manifest list.txt --out rows.jsonl [--scale N] [--options k=v;...]");
            return 2;
        }

        var items = File.ReadAllLines(manifest)
            .Select(ParseItem)
            .Where(item => item != null)
            .ToList();

        using var recognizer = await TextRecognizer.CreateAsync();

        string scalerNote = null;
        int maxScale = 0;
        ImageScaler scaler = null;
        if (scale > 1)
        {
            try
            {
                scaler = await ImageScaler.CreateAsync();
                maxScale = scaler.MaxSupportedScaleFactor;
                scalerNote = $"requested={scale}x max_supported={maxScale}x";
                if (scale > maxScale)
                {
                    scalerNote += $" capped_to={maxScale}x";
                    scale = maxScale;
                }
            }
            catch (Exception ex)
            {
                scalerNote = "ImageScaler unavailable " + ex.GetType().Name + ": " + ex.Message;
                Note(scalerNote);
                scale = 0;
            }
        }

#if TEXTREG_OPTIONS
        var recognizerOptions = new TextRecognizerOptions();
        if (!string.IsNullOrEmpty(options))
        {
            foreach (var pair in options.Split(';', StringSplitOptions.RemoveEmptyEntries))
            {
                var parts = pair.Split('=', 2);
                if (parts.Length != 2) continue;
                var value = parts[1];
                if (parts[0] == "geometry") recognizerOptions.DetectorOutputGeometryMode = value;
                else if (parts[0] == "wordconf") recognizerOptions.EnableWordLevelConfidence = value == "1";
                else Note("unknown option " + parts[0]);
            }
        }
        Note($"options geometry={recognizerOptions.DetectorOutputGeometryMode ?? "(default)"} "
             + $"wordconf={recognizerOptions.EnableWordLevelConfidence}");
#endif
        Note($"scaler={scalerNote ?? "(off)"} items={items.Count}");

        var modules = Process.GetCurrentProcess().Modules.Cast<ProcessModule>()
            .Select(module => module.ModuleName)
            .Where(name => name.Contains("Qnn", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("Htp", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("Npu", StringComparison.OrdinalIgnoreCase)
                        || name.Contains("Windows.AI", StringComparison.OrdinalIgnoreCase))
            .Distinct().ToArray();
        Note("modules=" + string.Join(",", modules));

        var runStarted = Stopwatch.StartNew();
        var rowCount = 0;
        using (var writer = new StreamWriter(outPath, false, new UTF8Encoding(false)))
        {
            foreach (var item in items)
            {
                var watch = Stopwatch.StartNew();
                var cpu0 = Process.GetCurrentProcess().TotalProcessorTime;
                string text = "";
                string error = null;
                float? angle = null;
                int width = 0, height = 0, scaledWidth = 0, scaledHeight = 0;
                double maxX = 0, maxY = 0;
                var lineRows = new List<Dictionary<string, object>>();
                string scaleError = null;
                try
                {
                    using var stream = await FileRandomAccessStream.OpenAsync(
                        item.Path, FileAccessMode.Read);
                    var decoder = await BitmapDecoder.CreateAsync(stream);
                    using var bitmap = await decoder.GetSoftwareBitmapAsync(
                        BitmapPixelFormat.Bgra8, BitmapAlphaMode.Premultiplied);
                    width = (int)bitmap.PixelWidth;
                    height = (int)bitmap.PixelHeight;

                    SoftwareBitmap input = bitmap;
                    SoftwareBitmap scaled = null;
                    if (scale > 1 && scaler != null)
                    {
                        try
                        {
                            scaled = scaler.ScaleSoftwareBitmap(
                                bitmap, bitmap.PixelWidth * scale, bitmap.PixelHeight * scale);
                            input = scaled;
                            scaledWidth = scaled.PixelWidth;
                            scaledHeight = scaled.PixelHeight;
                        }
                        catch (Exception ex)
                        {
                            scaleError = ex.GetType().Name + ": " + ex.Message;
                            Note("scale failed on " + item.Path + ": " + scaleError);
                        }
                    }

                    try
                    {
                        using var image = ImageBuffer.CreateForSoftwareBitmap(input);
#if TEXTREG_OPTIONS
                        var operation = recognizer.RecognizeTextFromImageAsync(image, recognizerOptions);
#else
                        var operation = recognizer.RecognizeTextFromImageAsync(image);
#endif
                        // The engine occasionally never returns (observed on
                        // ordinary pages).  A hung page must not stop the batch.
                        var pending = operation.AsTask();
                        var winner = await Task.WhenAny(
                            pending, Task.Delay(TimeSpan.FromSeconds(timeoutSeconds)));
                        if (winner != pending)
                        {
                            throw new TimeoutException(
                                $"no result after {timeoutSeconds}s; page skipped");
                        }
                        var result = await pending;
                        angle = result.TextAngle;
                        var lines = new List<string>();
                        foreach (var line in result.Lines)
                        {
                            var box = LineBox(line.BoundingBox);
                            maxX = Math.Max(maxX, box[2]);
                            maxY = Math.Max(maxY, box[3]);
                            lines.Add(line.Text);
                            var words = new List<Dictionary<string, object>>();
                            foreach (var word in line.Words ?? Array.Empty<RecognizedWord>())
                            {
                                var wordBox = LineBox(word.BoundingBox);
                                maxX = Math.Max(maxX, wordBox[2]);
                                maxY = Math.Max(maxY, wordBox[3]);
                                words.Add(new Dictionary<string, object>
                                {
                                    ["text"] = word.Text,
                                    ["confidence"] = Math.Round(word.MatchConfidence, 5),
                                    ["box"] = wordBox,
                                });
                            }
                            lineRows.Add(new Dictionary<string, object>
                            {
                                ["text"] = line.Text,
                                ["box"] = box,
                                ["style"] = line.Style.ToString(),
                                ["style_confidence"] = Math.Round(line.LineStyleConfidence, 5),
                                ["words"] = words,
                            });
                        }
                        text = string.Join("\n", lines);
                    }
                    finally
                    {
                        scaled?.Dispose();
                    }
                }
                catch (Exception ex)
                {
                    error = ex.GetType().Name + ": " + ex.Message;
                    Note("recognize failed on " + item.Path + ": " + error);
                }

                var cpu = Process.GetCurrentProcess().TotalProcessorTime - cpu0;
                writer.WriteLine(JsonSerializer.Serialize(new Dictionary<string, object>
                {
                    ["id"] = item.Id,
                    ["path"] = item.Path,
                    ["text"] = text,
                    ["width"] = width,
                    ["height"] = height,
                    ["scaled_width"] = scaledWidth,
                    ["scaled_height"] = scaledHeight,
                    ["max_box_x"] = Math.Round(maxX, 2),
                    ["max_box_y"] = Math.Round(maxY, 2),
                    ["angle"] = angle.HasValue ? (object)Math.Round(angle.Value, 4) : null,
                    ["line_rows"] = lineRows,
                    ["seconds"] = Math.Round(watch.Elapsed.TotalSeconds, 4),
                    ["cpu_seconds"] = Math.Round(cpu.TotalSeconds, 4),
                    ["modules"] = modules,
                    ["scale_error"] = scaleError,
                    ["error"] = error,
                }));
                writer.Flush();
                rowCount++;
                Console.WriteLine($"{Path.GetFileName(item.Path)} {watch.Elapsed.TotalSeconds:F2}s "
                                  + $"lines={lineRows.Count} chars={text.Length} {error}");
            }
        }

        var done = new Dictionary<string, object>
        {
            ["rows"] = rowCount,
            ["seconds"] = Math.Round(runStarted.Elapsed.TotalSeconds, 3),
            ["ready_state"] = state.ToString(),
            ["modules"] = modules,
            ["scale"] = scale,
            ["scaler"] = scalerNote,
            ["options"] = options,
        };
        File.WriteAllText(outPath + ".done", JsonSerializer.Serialize(done));
        Note("done " + JsonSerializer.Serialize(done));
        return 0;
    }
}
