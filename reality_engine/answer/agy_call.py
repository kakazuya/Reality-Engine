"""One headless agy run (T-205 round 13): a prompt in, the final text, tool calls and tokens out.

``run_agy`` is the single door the T-205 arms use for another model: the pack arm (``answer_step --answer-model
agy:gemini-4-hydrogen-high``), the seeded tool arm (``seeded_run``), the plan step (``pack_recall --plan-model``) and
the blind grader (``blind_grade``). It spawns ``agy -p <prompt> --model <id> --output-format stream-json
--dangerously-skip-permissions`` with no shell and a hidden window (MSI rule), and parses the event log with
``plugins/agy-worker/server/agy_core.parse_events`` -- the one parser, not a second one.

Two rules the round-13 brief fixes:

* **argv size.** ``agy -p`` takes the prompt as a command-line argument and Windows caps a command line at 32767
  characters, while a pack reading copy is ~75,000. A prompt over ``MAX_PROMPT_CHARS`` is therefore written to
  ``<cwd>/.tmp/agy_prompts/<stamp>.txt`` and the argv carries a one-line pointer telling the model to read it first.
  The model's own tool log records that read (``view_file``), never a store lookup.
* **retry.** ONE retry on a transport error (no final response in the log, the process failed to start, a non-zero
  exit with no answer). A run that produced a final text is never retried, not even when the answer is bad: a model
  answer is data, not a transport fault.

``client_for`` turns a model into the ``(system, user, key) -> {"content", ...}`` callable ``answer_step`` and
``plan_model`` already take, so those prompts stay byte-for-byte the round-12 ones; only the transport changes.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
AGY_SERVER = REPO_ROOT / "plugins" / "agy-worker" / "server"
CREATE_NO_WINDOW = 0x08000000
PREFIX = "agy:"
MAX_PROMPT_CHARS = 24000          # below the 32767 Windows command-line cap, with room for the other flags
DEFAULT_TIMEOUT = 900
DATA_TOOLS = {"pilot3_fact", "pilot3_fin", "pilot3_kpi", "pilot3_ratio", "pilot3_guidance", "pilot3_holding",
              "pilot3_statements", "pilot3_topic", "pilot3_cells", "pilot3_docs", "pilot3_search", "pilot3_semantic",
              "pilot3_sql", "pilot3_calc", "facts", "docs", "search_docs", "price", "holding", "delivery",
              "price_extreme", "universe", "sql"}


def model_id(name: str) -> str:
    """``agy:gemini-4-hydrogen-high`` -> ``gemini-4-hydrogen-high`` (a bare id is returned as given)."""
    text = str(name or "").strip()
    return text[len(PREFIX):] if text.startswith(PREFIX) else text


def is_agy_model(name: str) -> bool:
    return str(name or "").strip().startswith(PREFIX)


def agy_bin() -> Path:
    return Path(os.environ.get("AGY_BIN") or (Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"))


def _parser():
    """``agy_core.parse_events``: the agy-worker's own stream-json reader (one parser in the repo)."""
    if str(AGY_SERVER) not in sys.path:
        sys.path.insert(0, str(AGY_SERVER))
    import agy_core
    return agy_core.parse_events


def _tool_name(raw: str) -> str:
    """One normal tool name: ``mcp:reality-data/pilot3_fact`` and ``mcp_reality-data_pilot3_fact`` both give
    ``pilot3_fact``; an ordinary tool (view_file) is unchanged."""
    name = str(raw or "?")
    if name.startswith("mcp:"):
        return name.split("/")[-1]
    if name.startswith("mcp_"):
        server, _, tool = name[4:].partition("_")
        return tool or name
    return name


def _fit_prompt(prompt: str, cwd: Path) -> str:
    """The argv carries the prompt; over MAX_PROMPT_CHARS the body goes to a file and the argv points at it."""
    if len(prompt) <= MAX_PROMPT_CHARS:
        return prompt
    d = cwd / ".tmp" / "agy_prompts"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"prompt_{time.strftime('%Y%m%dT%H%M%S', time.gmtime())}_{len(prompt)}.txt"
    path.write_text(prompt, encoding="utf-8")
    return (f"Your complete instructions and evidence are in this file:\n{path}\n"
            "Read that file first with view_file (it is the whole task), then follow it exactly. "
            "Do not answer before you have read it.")


def _argv(agy: str | Path | list[str] | tuple[str, ...], prompt: str, model: str, timeout: int) -> list[str]:
    head = list(agy) if isinstance(agy, (list, tuple)) else [str(agy)]
    return [*head, "-p", prompt, "--model", model, "--mode", "accept-edits", "--output-format", "stream-json",
            "--print-timeout", f"{int(timeout)}s", "--disable-slash-commands", "--dangerously-skip-permissions"]


def _one_run(prompt: str, model: str, cwd: Path, timeout: int, log_path: Path,
             agy: str | Path | list[str] | tuple[str, ...]) -> dict:
    """One agy process; its stdout is the stream-json log, its stderr a sibling ``.err`` file."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    err_path = log_path.with_suffix(".err")
    t0 = time.time()
    with open(log_path, "w", encoding="utf-8") as out, open(err_path, "w", encoding="utf-8") as err:
        p = subprocess.Popen(_argv(agy, prompt, model, timeout), cwd=str(cwd), stdout=out, stderr=err,
                             stdin=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW)
        try:
            rc = p.wait(timeout=timeout + 120)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            rc = -9
    events: dict[str, Any] = {}
    try:
        events = _parser()(log_path)
    except Exception as exc:  # a broken log is a transport fault, never a model answer
        events = {"error": f"event log unreadable: {exc}"[:300]}
    text = str(events.get("response") or "")
    tools: dict[str, int] = {}
    for raw, n in (events.get("tool_calls_by_tool") or {}).items():
        name = _tool_name(raw)
        tools[name] = tools.get(name, 0) + int(n)
    error = ""
    if not text:
        tail = err_path.read_text(encoding="utf-8", errors="replace")[-400:] if err_path.is_file() else ""
        error = events.get("error") or (f"agy exited {rc} with no final response" if rc else
                                        "no final response in the event log")
        if rc == -9:
            error = f"timeout after {timeout}s"
        elif tail.strip() and "no final response" in error:
            error = f"{error}: {tail.strip().splitlines()[-1][:200]}"
    return {"ok": bool(text), "text": text, "model": model, "status": events.get("final_status"),
            "tool_calls": int(events.get("tool_calls") or 0), "tool_calls_by_tool": events.get("tool_calls_by_tool") or {},
            "tools": tools, "data_tool_calls": sum(n for t, n in tools.items() if t in DATA_TOOLS),
            "tokens": events.get("tokens") or {}, "seconds": round(time.time() - t0, 2),
            "error": error, "log": str(log_path), "conversation_id": events.get("conversation_id")}


def run_agy(prompt: str, model: str, *, cwd: str | Path | None = None, timeout: int = DEFAULT_TIMEOUT,
            log_path: str | Path | None = None, agy: str | Path | list[str] | tuple[str, ...] | None = None) -> dict:
    """Run one headless agy prompt and return the final text, the tools it called, tokens and seconds.

    ``model`` is the bare id (``gemini-4-hydrogen-high``; an ``agy:`` prefix is stripped). ``log_path`` keeps the
    event log; omitted, a temporary file is used and its path is returned. One retry on a transport error, never on
    a final answer. ``agy`` may be an argv list (the tests pass ``[sys.executable, fake.py]``).
    """
    workdir = Path(cwd or REPO_ROOT)
    binary = agy if agy is not None else agy_bin()
    if isinstance(binary, (str, Path)) and not Path(binary).exists():
        return {"ok": False, "text": "", "model": model, "tools": {}, "tool_calls": 0, "data_tool_calls": 0,
                "tokens": {}, "seconds": 0.0, "error": f"agy not found at {binary}", "attempts": 0, "log": ""}
    prompt = _fit_prompt(prompt, workdir)
    if log_path:
        log = Path(log_path)
    else:
        fd, tmp = tempfile.mkstemp(suffix=".jsonl", prefix="agy_call_")
        os.close(fd)
        log = Path(tmp)
    first: dict[str, Any] = {}
    for attempt in (1, 2):
        try:
            out = _one_run(prompt, model_id(model), workdir, timeout, log, binary)
        except OSError as exc:
            out = {"ok": False, "text": "", "model": model, "tools": {}, "tool_calls": 0, "data_tool_calls": 0,
                   "tokens": {}, "seconds": 0.0, "error": f"agy could not start: {exc}"[:300], "log": str(log)}
        out["attempts"] = attempt
        if attempt == 1:
            first = out
        if out["ok"] or out.get("error", "").startswith("timeout"):
            return out                       # a final answer is never retried; a timeout would only cost again
        if attempt == 1 and not out["ok"]:
            time.sleep(2)
    return {**first, "attempts": 2, "error": first.get("error") or "agy produced no final response"}


def client_for(model: str, *, cwd: str | Path | None = None, log_dir: str | Path | None = None,
               timeout: int = DEFAULT_TIMEOUT,
               runner: Callable[..., dict] | None = None) -> Callable[..., dict]:
    """The ``(system, user, key)`` client ``answer_step`` / ``plan_model`` call, backed by ``run_agy``.

    The returned callable carries ``.tools`` (every tool called, merged over its calls) and ``.data_tool_calls``
    (the store lookups only), so an answer file can state whether the model left the pack. A transport failure
    raises ``RuntimeError`` after the retry, which both callers already treat as a model error.
    """
    run = runner or run_agy
    counter: dict[str, int] = {}
    seen = {"data": 0}

    def client(system: str, user: str, key: str = "") -> dict:  # noqa: ARG001 - the shared client signature
        reply = run(f"{system}\n\n{user}" if system else user, model, cwd=cwd,
                    timeout=timeout, log_path=(Path(log_dir) / f"call_{len(counter) + 1:02d}.jsonl" if log_dir else None))
        for name, n in (reply.get("tools") or {}).items():
            counter[name] = counter.get(name, 0) + int(n)
        seen["data"] += int(reply.get("data_tool_calls") or 0)
        if not reply.get("ok"):
            raise RuntimeError(str(reply.get("error") or "agy produced no final response"))
        tokens = reply.get("tokens") or {}
        return {"content": reply.get("text") or "",
                "in_tok": int(tokens.get("input_tokens") or 0),
                "out_tok": int(tokens.get("output_tokens") or 0),
                "finish": reply.get("status") or ""}

    client.tools = counter          # type: ignore[attr-defined]
    client.data_tool_calls = seen   # type: ignore[attr-defined]
    return client


def run_json(prompt: str, model: str, **kwargs: Any) -> tuple[dict | None, dict]:
    """``run_agy`` plus the last JSON object of the final text (the answer / grade / plan protocols)."""
    reply = run_agy(prompt, model, **kwargs)
    return last_json(reply.get("text") or ""), reply


def last_json(text: str) -> dict | None:
    """The last top-level JSON object in a reply (a model that narrates first still parses); ``None`` when none."""
    depth, start = 0, -1
    best: dict | None = None
    in_str, esc = False, False
    for i, ch in enumerate(text or ""):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    obj = json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    best = obj
    return best
