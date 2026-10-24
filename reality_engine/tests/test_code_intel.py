"""Tests for the code-intel MCP server (plugins/code-intel/server).

The outline/module-map tools read files with ``ast`` and always run.  Everything
else needs a language server; those tests skip when no ``basedpyright`` /
``pyright`` binary or package is installed, and pass on a machine that has one
(``python -m pip install basedpyright --timeout 120 --retries 5``).

Run from the repo root:
    python -m unittest reality_engine.tests.test_code_intel -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "plugins" / "code-intel" / "server"
SERVER = SERVER_DIR / "server.py"
FIXTURE = REPO_ROOT / ".tmp" / "code_intel_fixture"
LIFECYCLE = SERVER_DIR / ".cache" / "lifecycle.log"
PROTOCOL_VERSION = "2026-07-28"
sys.path.insert(0, str(SERVER_DIR))

import core  # noqa: E402

LANG_SERVER = core.langserver_command()
LSP_SKIP = "no basedpyright-langserver/pyright-langserver found; " + core.INSTALL_HINT

UTIL_PY = '''"""Small helpers used by the fixture app."""


def helper(value: int) -> int:
    """Return twice the value."""
    return value * 2


def connect_ro(path: str) -> str:
    """Open a path read-only."""
    return f"ro:{path}"


class Store:
    """A tiny store."""

    def open(self) -> str:
        """Open the store."""
        return "open"
'''

MAIN_PY = '''"""Fixture entry point."""
from pkg.util import connect_ro


def run() -> str:
    """Call the helper."""
    return connect_ro("db")


def broken() -> int:
    return "not an int"
'''


def build_fixture() -> Path:
    """A tiny package under ./.tmp: two functions, one call site, one type error.

    ``mkdir``/``write_text`` are used instead of ``tempfile`` on purpose: the DSH
    sandbox grants write access by ACL inheritance, and mkdtemp's mode 0o700 drops it.
    """
    pkg = FIXTURE / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('"""Fixture package for code-intel tests."""\n', encoding="utf-8")
    (pkg / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (pkg / "main.py").write_text(MAIN_PY, encoding="utf-8")
    (FIXTURE / "pyrightconfig.json").write_text(json.dumps({
        "include": ["pkg"], "pythonVersion": "3.14", "typeCheckingMode": "basic",
        "extraPaths": ["."], "reportMissingImports": "warning",
    }, indent=2), encoding="utf-8")
    # .tmp/ is not gitignored in this repo; a self-ignoring fixture keeps the worktree clean.
    (FIXTURE / ".gitignore").write_text("*\n", encoding="utf-8")
    return FIXTURE


def line_of(path: Path, needle: str) -> int:
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in text:
            return number
    raise AssertionError(f"{needle!r} not found in {path}")


def payload(result) -> dict:
    data = (result or {}).get("structuredContent") or (result or {}).get("structured_content")
    if data is None:
        for block in (result or {}).get("content") or []:
            if block.get("type") == "text":
                data = json.loads(block["text"])
                break
    if data is None:
        raise AssertionError(f"tool returned no JSON payload: {result!r}")
    return data


class RawStdio:
    """MCP over stdio with newline-delimited JSON.

    ``mcp.client.stdio`` is not usable here: anyio opens overlapped (named) pipes
    and the DSH sandbox denies those, so the test speaks the wire protocol with a
    plain Popen pair instead.
    """

    def __init__(self, root: Path, env_extra: dict | None = None) -> None:
        env = dict(os.environ, CODE_INTEL_REPO_ROOT=str(root), PYTHONUTF8="1")
        env.pop("CODE_INTEL_LANG_SERVER", None)
        env.update(env_extra or {})
        self.proc = subprocess.Popen([sys.executable, str(SERVER)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     cwd=str(root), env=env)
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError('code-intel server has no stdio pipes')
        self._stdin = self.proc.stdin
        self._stdout = self.proc.stdout
        self._id = 0

    def _send(self, message: dict) -> None:
        self._stdin.write(json.dumps(message).encode() + b"\n")
        self._stdin.flush()

    def _recv(self, timeout: float = 120.0) -> dict:
        timer = threading.Timer(timeout, self.proc.kill)
        timer.start()
        try:
            line = self._stdout.readline()
        finally:
            timer.cancel()
        if not line:
            raise AssertionError("code-intel server closed stdout")
        return json.loads(line)

    def request(self, method: str, params: dict, timeout: float = 120.0) -> dict:
        self._id += 1
        request_id = self._id
        self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            message = self._recv(timeout=max(0.1, deadline - time.monotonic()))
            if message.get("id") != request_id:      # server notifications
                continue
            if "error" in message:
                raise AssertionError(f"JSON-RPC error: {message['error']}")
            return message.get("result") or {}
        raise AssertionError(f"no reply to {method}")

    def initialize(self) -> dict:
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "code-intel-test", "version": "0"},
        }, timeout=60)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return result

    def call_tool(self, name: str, arguments: dict, timeout: float = 180.0) -> dict:
        return payload(self.request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout))

    def close(self) -> None:
        try:
            self._stdin.close()          # stdin close => graceful exit => langserver stopped
            self.proc.wait(timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
        finally:
            self._stdout.close()


class FixtureMixin:
    @classmethod
    def setUpClass(cls):
        cls._saved_root = core.REPO_ROOT
        core.REPO_ROOT = build_fixture()
        core.close()
        cls.util_py = core.REPO_ROOT / "pkg" / "util.py"
        cls.main_py = core.REPO_ROOT / "pkg" / "main.py"
        cls.def_line = line_of(cls.util_py, "def connect_ro")

    @classmethod
    def tearDownClass(cls):
        core.close()
        core.REPO_ROOT = cls._saved_root


class OutlineTests(FixtureMixin, unittest.TestCase):
    """ast-backed tools: no language server needed."""

    def test_symbols_outline(self):
        out = core.symbols(file="pkg/util.py")
        self.assertTrue(out["ok"])
        self.assertEqual(out["file"], "pkg/util.py")
        self.assertEqual(out["module_doc"], "Small helpers used by the fixture app.")
        names = {symbol["name"]: symbol for symbol in out["symbols"]}
        self.assertEqual(set(names), {"helper", "connect_ro", "Store", "open"})
        self.assertEqual(names["connect_ro"]["kind"], "function")
        self.assertEqual(names["connect_ro"]["line"], self.def_line)
        self.assertEqual(names["connect_ro"]["doc"], "Open a path read-only.")
        self.assertEqual(names["helper"]["doc"], "Return twice the value.")
        # methods keep their bare name and name their class as the container
        self.assertEqual(names["open"]["kind"], "method")
        self.assertEqual(names["open"]["container"], "Store")
        self.assertEqual(names["Store"]["kind"], "class")

    def test_symbols_bounded(self):
        out = core.symbols(file="pkg/util.py", limit=1)
        self.assertEqual(len(out["symbols"]), 1)
        self.assertTrue(out["truncated"])

    def test_module_map(self):
        out = core.module_map("pkg")
        self.assertTrue(out["ok"])
        purposes = {module["file"]: module["purpose"] for module in out["modules"]}
        self.assertEqual(purposes["pkg/util.py"], "Small helpers used by the fixture app.")
        self.assertEqual(purposes["pkg/main.py"], "Fixture entry point.")
        self.assertEqual(purposes["pkg/__init__.py"], "Fixture package for code-intel tests.")
        self.assertEqual(core.module_map("pkg", limit=1)["count"], 1)

    def test_errors_are_data_not_exceptions(self):
        with self.assertRaises(core.CodeIntelError) as raised:
            core.symbols(file="pkg/missing.py")
        self.assertEqual(raised.exception.code, "not_found")
        with self.assertRaises(core.CodeIntelError):
            core.symbols()


@unittest.skipUnless(LANG_SERVER, LSP_SKIP)
class LspToolTests(FixtureMixin, unittest.TestCase):
    def test_definition_by_symbol(self):
        out = core.definition(symbol="connect_ro")
        self.assertTrue(out["ok"])
        self.assertEqual(out["count"], 1)
        first = out["definitions"][0]
        self.assertEqual(first["file"], "pkg/util.py")
        self.assertEqual(first["line"], self.def_line)
        self.assertTrue(any("connect_ro" in line for line in first["snippet"]))
        self.assertLessEqual(len(first["snippet"]), core.SNIPPET_LINES + 1)

    def test_definition_by_position(self):
        call_line = line_of(self.main_py, 'connect_ro("db")')
        text = self.main_py.read_text(encoding="utf-8").splitlines()[call_line - 1]
        col = text.index("connect_ro") + 1
        out = core.definition(file="pkg/main.py", line=call_line, col=col)
        self.assertTrue(out["ok"])
        self.assertEqual(out["definitions"][0]["file"], "pkg/util.py")

    def test_references_and_callers(self):
        out = core.references(symbol="connect_ro")
        self.assertTrue(out["ok"])
        self.assertGreaterEqual(out["count"], 1)
        files = {hit["file"] for hit in out["references"]}
        self.assertIn("pkg/main.py", files)
        self.assertTrue(any("connect_ro(" in hit["text"] for hit in out["references"]
                            if hit["file"] == "pkg/main.py"))
        callers = core.callers("connect_ro")
        self.assertTrue(all("connect_ro(" in site["text"] for site in callers["callers"]))
        self.assertEqual(callers["count"], len(callers["callers"]))
        self.assertTrue(callers["count"] >= 1)

    def test_references_bounded(self):
        out = core.references(symbol="connect_ro", limit=1)
        self.assertLessEqual(len(out["references"]), 1)

    def test_hover(self):
        text = self.util_py.read_text(encoding="utf-8").splitlines()[self.def_line - 1]
        col = text.index("connect_ro") + 1
        out = core.hover("pkg/util.py", self.def_line, col)
        self.assertTrue(out["ok"])
        self.assertIn("connect_ro", out["hover"])
        self.assertLessEqual(len(out["hover"]), core.MAX_HOVER_CHARS)

    def test_diagnostics_reports_the_deliberate_error(self):
        out = core.diagnostics(files=["pkg/main.py"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["files"][0]["file"], "pkg/main.py")
        self.assertGreaterEqual(out["error_count"], 1)
        broken_line = line_of(self.main_py, 'return "not an int"')
        self.assertTrue(any(d["line"] == broken_line for d in out["files"][0]["diagnostics"]),
                        out["files"][0]["diagnostics"])
        for entry in out["files"][0]["diagnostics"]:
            self.assertIn(entry["severity"], {"error", "warning", "info", "hint"})
            self.assertLessEqual(len(entry["message"]), 500)

    def test_workspace_symbol_search(self):
        out = core.symbols(query="connect_ro")
        self.assertTrue(out["ok"])
        self.assertTrue(any(symbol["name"] == "connect_ro" for symbol in out["symbols"]))
        self.assertTrue(all(symbol["file"] for symbol in out["symbols"]))


class HandshakeTests(unittest.TestCase):
    def test_handshake_answers_before_warmup_completes(self):
        rpc = RawStdio(REPO_ROOT)
        self.addCleanup(rpc.close)
        started = time.monotonic()
        init = rpc.initialize()
        elapsed = time.monotonic() - started
        tools = rpc.request("tools/list", {})
        # 1.9 s of a cold start is `import mcp.server` alone (pydantic + anyio); reality-data
        # measures 2.4-3.2 s the same way on this box.  What this test really pins is that the
        # reply does not wait for the language-server warm-up (asserted below via the log).
        self.assertLess(elapsed, 5.0, f"initialize took {elapsed:.2f}s")
        self.assertEqual(init["serverInfo"]["name"], "code-intel")
        self.assertEqual({tool["name"] for tool in tools["tools"]},
                         {"definition", "references", "callers", "symbols", "hover",
                          "diagnostics", "module_map"})
        tail = LIFECYCLE.read_text(encoding="utf-8").split(" start")[-1] if LIFECYCLE.exists() else ""
        self.assertNotIn("warm done", tail, "handshake waited for the language-server warm-up")


class MissingLangServerTests(FixtureMixin, unittest.TestCase):
    def test_clear_error_and_no_crash(self):
        rpc = RawStdio(FIXTURE, {"CODE_INTEL_LANG_SERVER": str(FIXTURE / "not-a-language-server")})
        self.addCleanup(rpc.close)
        rpc.initialize()
        broken = rpc.call_tool("definition", {"symbol": "connect_ro"}, timeout=90)
        self.assertFalse(broken["ok"])
        self.assertEqual(broken["error"]["code"], "lsp_missing")
        self.assertIn("pip install basedpyright", broken["error"]["install"])
        # the ast-backed tool still answers, and the server is still alive
        outline = rpc.call_tool("symbols", {"file": "pkg/util.py"})
        self.assertTrue(outline["ok"])
        self.assertEqual(outline["count"], 4)


if __name__ == "__main__":
    unittest.main()
