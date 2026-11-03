"""Tests for the code-tools MCP server and CLI (outline/typecheck, run-and-exit).

Run from the repo root:
    python -m pytest plugins/code-tools/tests -q
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
REPO = PLUGIN_ROOT.parents[1]
SERVER = PLUGIN_ROOT / "server.py"
CT = PLUGIN_ROOT / "ct.py"
TOOLS = PLUGIN_ROOT / "tools.py"
sys.path.insert(0, str(PLUGIN_ROOT))

import tools  # noqa: E402


def payload(result):
    data = getattr(result, "structured_content", None)
    if data is None:
        data = getattr(result, "structuredContent", None)
    if data is None:
        for block in result.content:
            if getattr(block, "type", None) == "text":
                data = json.loads(block.text)
                break
    if data is None:
        raise AssertionError(f"tool returned no JSON payload: {result!r}")
    return data


FIXTURE = REPO / ".tmp" / "code_tools_outline_fixture.py"


class OutlineTests(unittest.TestCase):
    def test_outline_own_module(self):
        started = time.perf_counter()
        symbols = tools.outline(TOOLS)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 1.0, "outline of one module must stay under 1 s")
        names = {s["name"] for s in symbols}
        for expected in ("outline", "typecheck", "_basedpyright", "_kill_tree", "_relative"):
            self.assertIn(expected, names)
        for symbol in symbols:
            self.assertEqual({"name", "kind", "line", "end_line", "parent", "doc"},
                             set(symbol))
            self.assertIn(symbol["kind"], {"class", "function", "method"})
            self.assertLessEqual(symbol["line"], symbol["end_line"])
        lines = [s["line"] for s in symbols]
        self.assertEqual(lines, sorted(lines))

    def test_outline_method_parent(self):
        FIXTURE.parent.mkdir(exist_ok=True)
        FIXTURE.write_text(
            '"""Fixture."""\n\n\n'
            "class Outer:\n"
            '    """A class."""\n\n'
            "    def method(self):\n"
            "        pass\n\n\n"
            "def free_function():\n"
            "    pass\n",
            encoding="utf-8",
        )
        try:
            symbols = {s["name"]: s for s in tools.outline(FIXTURE)}
        finally:
            FIXTURE.unlink()
        self.assertEqual(symbols["Outer"]["kind"], "class")
        self.assertEqual(symbols["method"]["kind"], "method")
        self.assertEqual(symbols["method"]["parent"], "Outer")
        self.assertEqual(symbols["free_function"]["kind"], "function")
        self.assertEqual(symbols["free_function"]["parent"], "")
        self.assertEqual(symbols["Outer"]["doc"], "A class.")

    def test_outline_syntax_error_raises(self):
        broken = REPO / ".tmp" / "code_tools_syntax_error.py"
        broken.parent.mkdir(exist_ok=True)
        broken.write_text("def broken(:\n", encoding="utf-8")
        try:
            with self.assertRaises(SyntaxError):
                tools.outline(broken)
        finally:
            broken.unlink()


class TypecheckTests(unittest.TestCase):
    def test_typecheck_returns_the_documented_shape(self):
        result = tools.typecheck([str(TOOLS)], root=REPO)
        self.assertEqual({"errors", "error_count", "seconds"}, set(result))
        self.assertIsInstance(result["error_count"], int)
        self.assertIsInstance(result["seconds"], float)
        self.assertLess(result["seconds"], 120)
        for error in result["errors"]:
            self.assertEqual({"file", "line", "message"}, set(error))
            self.assertGreater(error["line"], 0)

    def test_typecheck_finds_a_real_error(self):
        # Its own project: basedpyright finds the repo's pyrightconfig.json by
        # walking up, and that config excludes .tmp.
        project = REPO / ".tmp" / "code_tools_typecheck_project"
        project.mkdir(parents=True, exist_ok=True)
        config = project / "pyrightconfig.json"
        config.write_text('{"include": ["."], "typeCheckingMode": "basic"}',
                          encoding="utf-8")
        fixture = project / "fixture.py"
        fixture.write_text("value: int = 'not an int'\n", encoding="utf-8")
        try:
            result = tools.typecheck([fixture.name], root=project)
        finally:
            fixture.unlink()
            config.unlink()
        self.assertGreaterEqual(result["error_count"], 1, result)
        self.assertTrue(any(error["line"] == 1 for error in result["errors"]), result)


class CliTests(unittest.TestCase):
    def test_cli_outline_prints_json(self):
        done = subprocess.run([sys.executable, str(CT), "outline", str(TOOLS)],
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=60, cwd=str(REPO))
        self.assertEqual(done.returncode, 0, done.stderr)
        data = json.loads(done.stdout)
        self.assertTrue(data["ok"], data)
        self.assertIn("outline", {s["name"] for s in data["symbols"]})


class McpStdioTests(unittest.TestCase):
    def test_tools_list_and_outline_over_stdio(self):
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(SERVER)],
            env={**os.environ, "CODE_TOOLS_ROOT": str(REPO), "PYTHONUTF8": "1"},
        )

        async def scenario():
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {tool.name for tool in listed.tools}
                    result = await session.call_tool(
                        "outline", {"file": "plugins/code-tools/tools.py"},
                        read_timeout_seconds=60,
                    )
                    return names, payload(result)

        try:
            names, data = asyncio.run(asyncio.wait_for(scenario(), 180))
        except (OSError, PermissionError) as exc:  # the sandbox can block pipe stdio
            self.skipTest(f"stdio pipes unavailable in this sandbox: {exc}")
        self.assertEqual({"outline", "typecheck"}, names)
        self.assertTrue(data["ok"], data)
        self.assertEqual(data["file"], "plugins/code-tools/tools.py")
        self.assertIn("typecheck", {s["name"] for s in data["symbols"]})


if __name__ == "__main__":
    unittest.main()
