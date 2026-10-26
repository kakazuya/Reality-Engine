"""Name-level overlap between research copies (Docs re-exported to docx get new bytes, so sha256 misses them)."""
import os
import sys

LP = "\\\\?\\"


def names(p):
    s = set()
    for d, _, fs in os.walk(LP + os.path.abspath(p)):
        for f in fs:
            if f.lower().endswith((".docx", ".xlsx", ".pdf", ".pptx")):
                s.add(os.path.splitext(f)[0].strip().lower())
    return s


a, b, c = (names(p) for p in sys.argv[1:4])
print("CPU/Research", len(a), "Research", len(b), "rclone", len(c))
print("a&b", len(a & b), "a&c", len(a & c), "b&c", len(b & c), "in all 3", len(a & b & c), "union", len(a | b | c))
