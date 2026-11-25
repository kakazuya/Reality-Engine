"""PreToolUse hook: Shivam's "Never" rulings enforced before a tool runs, not only stated in prompts (T-242, 25 Nov).

Claude Code pipes the pending tool call as JSON on stdin ({"tool_name": ..., "tool_input": {...}}). A breach prints
the rule to stderr and exits 2, which blocks the call and shows Claude why; anything else exits 0. A guard that
crashes exits 0 (never blocks work on its own bug) and says so on stderr.

Rules (RULINGS.md "Never" + "Data and machines"):
  private      D:\\Shivam_Private\\Manual Dumps: never read or send anywhere.
  telegram     Downloads\\Telegram Desktop (his brother's): never touch.
  secrets      never print or copy keys: no reading credential/auth/.env files, no echo/printenv of *KEY*/*TOKEN*.
  push         no git push without Shivam's OK (merged main was approved 3 Nov; any other branch is blocked).
  paid_model   free models only: a model argument naming a paid route (DeepInfra, Zen MiMo/hy4, Kilo/OpenRouter
               Anthropic/OpenAI/Google paid ids) is blocked unless its id carries ":free"/"-free" and is not in PAID_FREE.
DB-on-HDD, hy4 double writers, heartbeat and quota stay in ops_gate (Stop hook): they are states, not single calls.

    python -m reality_engine.scripts.rule_guard < call.json      # hook entry
    python -m reality_engine.scripts.rule_guard --explain        # list the rules
"""
from __future__ import annotations

import json
import re
import sys

PRIVATE_RE = re.compile(r"shivam_private[\\/]+manual[ _]dumps", re.I)
TELEGRAM_RE = re.compile(r"downloads[\\/]+telegram desktop", re.I)
SECRET_FILE_RE = re.compile(r"(\.credentials\.json|(^|[\\/])auth\.json|(^|[\\/])\.env(\.|$|\b)|api[_-]?keys?\.(txt|json))", re.I)
SECRET_PRINT_RE = re.compile(
    r"(\becho\b[^|;&\n]*\$\{?\w*(KEY|TOKEN|SECRET)\w*|\bprintenv\b|\benv\s*\|\s*(sort|cat|head|tail|less)\b|"
    r"\benv\s*\|\s*grep\b(?![^|;&\n]*\s-\w*[cql])[^|;&\n]*(KEY|TOKEN|SECRET|PASS)|"
    r"Get-ChildItem\s+env:|\$env:\w*(KEY|TOKEN|SECRET)\w*\s*($|[|;)]))", re.I)
# Only a git push in command position (start, or after ; && || | ( or a newline), so notes text that mentions
# "git push" inside a heredoc or quoted string does not count.
PUSH_RE = re.compile(r"(?:^|[;&|(\n])\s*git\b(?:\s+-C\s+\S+)?\s+push\b(?P<rest>[^;&|\n]*)", re.I)
REDIRECT_RE = re.compile(r"\s\d?>&?\d?\S*|\s\d?>>?\s*\S+")
MODEL_ARG_RE = re.compile(r"(?:\s-m\s+|--model[=\s]+|\"model\"\s*:\s*\")(?P<m>[\w./:~@-]+)", re.I)
PAID_PREFIX_RE = re.compile(r"^(deepinfra/|kilo/~?(anthropic|openai|google|x-ai|moonshotai|deepseek)/|"
                            r"openrouter/(anthropic|openai|google)/|opencode/(claude|gpt|gemini|kimi|muse))", re.I)
# Ids that say "free" but are billed on Zen (Shivam 25 Nov).
PAID_FREE = {"opencode/mimo-v2.6-flash-free", "opencode/hy4-flash-free"}
# Killing by image name takes down every worker, reader, MCP server and loop of BOTH accounts (25 Nov 21:14:
# a helper's `taskkill /IM python.exe` killed 3 dsh workers, the MCP servers and all uploaders). Kill by PID only.
MASS_KILL_RE = re.compile(r"(\btaskkill\b[^;&|\n]*/IM\s+\"?(python|node|bash|claude|pythonw|py)(\.exe)?\b|"
                          r"\b(Stop-Process|spps|kill)\b[^;&|\n]*-Name\s+\"?(python|node|bash|claude)\b|"
                          r"\b(pkill|killall)\b[^;&|\n]*\b(python|node|bash|claude)\b)", re.I)

RULES = {
    "private": "D:\\Shivam_Private\\Manual Dumps is never read or sent anywhere (RULINGS: Never).",
    "telegram": "Downloads\\Telegram Desktop is his brother's: never touch it (RULINGS: Data and machines).",
    "secrets": "Never print or copy keys or credential files (RULINGS: Never).",
    "push": "No git push without Shivam's OK; only merged main is pre-approved (3 Nov).",
    "paid_model": "Free models only: this model id is paid (DeepInfra / Zen MiMo or hy4 / paid Kilo-OpenRouter routes).",
    "mass_kill": "Never kill processes by name (python/node/bash/claude): it kills both accounts' workers, readers and MCP "
                 "servers. Find the PID (Get-CimInstance Win32_Process with its CommandLine) and stop that PID only.",
}


# A heredoc fed to cat/tee only writes text (docs, notes): its body is data, not an access. Heredocs fed to an
# interpreter (python - <<'E') stay scanned, since that code can open the paths it names.
TEXT_HEREDOC_RE = re.compile(r"\b(?:cat|tee)\b[^\n]*?<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\2[ \t]*(?=\n|$)", re.S)


def _texts(tool: str, inp: dict) -> tuple[str, str]:
    """(command text, path-ish text) of one tool call."""
    cmd = str(inp.get("command") or "") if tool in ("Bash", "PowerShell") else ""
    cmd = TEXT_HEREDOC_RE.sub(lambda m: m.group(0).split("\n", 1)[0], cmd)
    paths = " ".join(str(inp.get(k) or "") for k in ("file_path", "path", "pattern", "glob", "notebook_path"))
    return cmd, paths


def breaches(call: dict) -> list[str]:
    tool = str(call.get("tool_name") or "")
    inp = call.get("tool_input") or {}
    if not isinstance(inp, dict):
        return []
    cmd, paths = _texts(tool, inp)
    hay = f"{cmd} {paths}"
    out: list[str] = []
    if PRIVATE_RE.search(hay):
        out.append("private")
    if TELEGRAM_RE.search(hay):
        out.append("telegram")
    if (tool in ("Read", "Grep", "Glob") and SECRET_FILE_RE.search(paths)) or \
            (cmd and re.search(r"\b(cat|type|Get-Content|head|tail|less|more|cp|copy|scp|rclone)\b[^;&|\n]*"
                               + SECRET_FILE_RE.pattern, cmd, re.I)) or (cmd and SECRET_PRINT_RE.search(cmd)):
        out.append("secrets")
    for m in PUSH_RE.finditer(cmd):
        rest = REDIRECT_RE.sub(" ", " " + m.group("rest"))
        if "--dry-run" in rest or re.search(r"(^|\s)-n(\s|$)", rest):
            continue
        targets = [t for t in rest.split() if not t.startswith("-")]
        # `git push` (current branch) or `git push origin main` is the approved merged-main push only when on main;
        # the hook cannot see the branch, so anything other than an explicit main ref is blocked.
        if not (len(targets) >= 2 and targets[-1] in ("main", "main:main", "HEAD:main")):
            out.append("push")
    for m in MODEL_ARG_RE.finditer(cmd):
        mid = m.group("m").strip("\"'").lower()
        if mid in PAID_FREE or (PAID_PREFIX_RE.search(mid) and not re.search(r"(:free|-free)$", mid)):
            out.append("paid_model")
            break
    if MASS_KILL_RE.search(cmd):
        out.append("mass_kill")
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--explain" in argv:
        for k, v in RULES.items():
            print(f"{k}: {v}")
        return 0
    try:
        call = json.loads(sys.stdin.read() or "{}")
        hits = breaches(call)
    except Exception as exc:  # noqa: BLE001 - a guard bug must never block work
        print(f"rule_guard: check failed ({type(exc).__name__}: {exc}); call allowed", file=sys.stderr)
        return 0
    if not hits:
        return 0
    print("Blocked by Shivam's standing rules (reality_engine/scripts/rule_guard.py):", file=sys.stderr)
    for h in hits:
        print(f"  RULE {h}: {RULES[h]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
