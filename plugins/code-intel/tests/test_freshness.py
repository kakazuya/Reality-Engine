"""Freshness tests: an answer must follow the disk, not the text a server first saw.

The 2026-10-30 defect: after ``router.py`` changed on disk (a git merge), the
language server kept the text it was first given, so ``definition`` pointed nine
lines short and ``references`` answered with docstring lines.  These tests copy a
small module to a temporary include path, query a symbol, insert nine lines above
it **on disk with no editor event**, query again, and assert the new line.  The
same is done for ``references`` and workspace symbols, plus the ast index the
worker CLI uses.

Run from the repo root (both runners work):

    python -m unittest discover -s plugins/code-intel/tests -p "test_*.py" -v
    python -m pytest plugins/code-intel/tests -q          # if pytest is installed
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugins" / "code-intel"
SERVER_DIR = PLUGIN_DIR / "server"
CLI = PLUGIN_DIR / "ci.py"
FIXTURE_ROOT = REPO_ROOT / ".tmp" / "code_intel_freshness"
PAD = "".join(f"# pad {number}\n" for number in range(1, 10))     # exactly 9 lines
PAD_LINES = 9

sys.path.insert(0, str(PLUGIN_DIR))
import astindex  # noqa: E402


def _load_server_module(stem: str):
    """Load ``plugins/code-intel/server/<stem>.py`` without clashing with dsh-worker's ``core``."""
    name = f"code_intel_freshness_{stem}"
    spec = importlib.util.spec_from_file_location(name, SERVER_DIR / f"{stem}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


core = _load_server_module("core")
LANG_SERVER = core.langserver_command()
LSP_SKIP = "no basedpyright-langserver/pyright-langserver found; " + core.INSTALL_HINT

UTIL_PY = '''"""Fixture helpers for the code-intel freshness tests."""


def marker_bounds(case: dict) -> tuple[str, str]:
    """Return the two bounds."""
    return "a", "b"


def helper(value: int) -> int:
    """Return twice the value."""
    return value * 2
'''

MAIN_PY = '''"""Fixture entry point."""
from pkg.util import marker_bounds


def run() -> tuple[str, str]:
    """Call the fixture helper."""
    return marker_bounds({})
'''


def build_fixture(base: Path) -> Path:
    """A two-module package under ``.tmp`` with its own pyrightconfig.json.

    ``mkdir``/``write_text`` instead of ``tempfile``: the DSH sandbox grants
    write access by ACL inheritance and mkdtemp's mode 0o700 drops it.
    """
    pkg = base / "pkg"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text('"""Fixture package."""\n', encoding="utf-8")
    (pkg / "util.py").write_text(UTIL_PY, encoding="utf-8")
    (pkg / "main.py").write_text(MAIN_PY, encoding="utf-8")
    (base / "pyrightconfig.json").write_text(json.dumps({
        "include": ["pkg"], "pythonVersion": "3.14", "typeCheckingMode": "basic",
        "extraPaths": ["."], "reportMissingImports": "warning",
    }, indent=2), encoding="utf-8")
    (base / ".gitignore").write_text("*\n", encoding="utf-8")   # keep the worktree clean
    return base


def line_of(path: Path, needle: str) -> int:
    for number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if needle in text:
            return number
    raise AssertionError(f"{needle!r} not found in {path}")


def pad_above(path: Path) -> None:
    """Insert nine lines at the top: every line below shifts down by nine."""
    path.write_text(PAD + path.read_text(encoding="utf-8"), encoding="utf-8")


@unittest.skipUnless(LANG_SERVER, LSP_SKIP)
class LanguageServerFreshnessTests(unittest.TestCase):
    """A disk edit with no didOpen/didChange from the client must still be seen."""

    @classmethod
    def setUpClass(cls):
        cls._saved_root = core.REPO_ROOT
        cls.fixture = build_fixture(FIXTURE_ROOT)
        core.REPO_ROOT = cls.fixture
        core.close()
        cls.util_py = cls.fixture / "pkg" / "util.py"
        cls.main_py = cls.fixture / "pkg" / "main.py"
        cls.def_line = line_of(cls.util_py, "def marker_bounds")
        cls.call_line = line_of(cls.main_py, "marker_bounds({})")

    @classmethod
    def tearDownClass(cls):
        core.close()
        core.REPO_ROOT = cls._saved_root

    def setUp(self):
        # pristine text for every test; the mutation each test makes differs
        (self.util_py).write_text(UTIL_PY, encoding="utf-8")
        self.main_py.write_text(MAIN_PY, encoding="utf-8")

    def test_definition_follows_disk_edit(self):
        first = core.definition(symbol="marker_bounds")
        self.assertEqual(first["definitions"][0]["line"], self.def_line)
        self.assertEqual(first["definitions"][0]["file"], "pkg/util.py")
        # the language server must have accepted the fresh text, not just the fallback
        self.assertEqual(first.get("source"), "lsp", "definition answered from the ast index")

        pad_above(self.util_py)                       # +9 lines, no editor event
        second = core.definition(symbol="marker_bounds")
        self.assertEqual(second["definitions"][0]["line"], self.def_line + PAD_LINES,
                         f"stale line, source={second.get('source')}")
        self.assertIn("def marker_bounds", second["definitions"][0]["text"])
        self.assertEqual(second.get("source"), "lsp")

    def test_references_follow_disk_edit(self):
        first = core.references(symbol="marker_bounds")
        self.assertIn((self.call_line, "pkg/main.py"),
                      {(hit["line"], hit["file"]) for hit in first["references"]})
        total = first["count"]

        pad_above(self.main_py)                       # the call site moves down
        second = core.references(symbol="marker_bounds")
        self.assertEqual(second.get("source"), "lsp", "references answered from the ast index")
        sites = {(hit["file"], hit["line"]): hit["text"] for hit in second["references"]}
        self.assertIn(("pkg/main.py", self.call_line + PAD_LINES), sites)
        self.assertNotIn(("pkg/main.py", self.call_line), sites)
        self.assertIn("marker_bounds(", sites[("pkg/main.py", self.call_line + PAD_LINES)])
        self.assertGreaterEqual(second["count"], total)

    def test_workspace_symbols_follow_disk_edit(self):
        first = core.symbols(query="marker_bounds")
        self.assertEqual({symbol["name"] for symbol in first["symbols"]}, {"marker_bounds"})
        self.assertEqual(first["symbols"][0]["line"], self.def_line)
        self.assertEqual(first.get("source"), "lsp")

        pad_above(self.util_py)
        second = core.symbols(query="marker_bounds")
        self.assertEqual(second["symbols"][0]["line"], self.def_line + PAD_LINES,
                         f"stale line, source={second.get('source')}")
        self.assertEqual(second.get("source"), "lsp")


class AstIndexFreshnessTests(unittest.TestCase):
    """The worker CLI's index: same disk edit, no language server at all."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = build_fixture(FIXTURE_ROOT / "ast")
        cls.util_py = cls.fixture / "pkg" / "util.py"
        cls.main_py = cls.fixture / "pkg" / "main.py"
        cls.def_line = line_of(cls.util_py, "def marker_bounds")
        cls.call_line = line_of(cls.main_py, "marker_bounds({})")

    def setUp(self):
        self.util_py.write_text(UTIL_PY, encoding="utf-8")
        self.main_py.write_text(MAIN_PY, encoding="utf-8")

    def test_definition_and_references_follow_disk_edit(self):
        index = astindex.load(self.fixture)
        self.assertEqual(astindex.definitions(index, "marker_bounds")[0]["line"], self.def_line)
        hits, _ = astindex.references(index, "marker_bounds")
        self.assertIn(("pkg/main.py", self.call_line), {(hit["file"], hit["line"]) for hit in hits})

        pad_above(self.util_py)
        pad_above(self.main_py)
        index = astindex.load(self.fixture)          # mtime invalidation, no restart
        self.assertEqual(index["reparsed"], 2, "both edited files should be re-parsed")
        self.assertEqual(astindex.definitions(index, "marker_bounds")[0]["line"],
                         self.def_line + PAD_LINES)
        self.assertIn("def marker_bounds",
                      astindex.definitions(index, "marker_bounds")[0]["text"])
        hits, _ = astindex.references(index, "marker_bounds")
        self.assertIn(("pkg/main.py", self.call_line + PAD_LINES),
                      {(hit["file"], hit["line"]): hit["text"] for hit in hits})
        again = astindex.load(self.fixture)
        self.assertEqual(again["reparsed"], 0, "a second load must not re-parse anything")

    def test_unchanged_file_is_not_reparsed(self):
        astindex.load(self.fixture, force=True)
        again = astindex.load(self.fixture)
        self.assertEqual(again["reparsed"], 0)


class CliTests(unittest.TestCase):
    """The CLI a dsh worker runs from its worktree (JSON on stdout, no language server)."""

    @classmethod
    def setUpClass(cls):
        cls.fixture = build_fixture(FIXTURE_ROOT / "cli")
        cls.util_py = cls.fixture / "pkg" / "util.py"
        cls.def_line = line_of(cls.util_py, "def marker_bounds")

    def setUp(self):
        self.util_py.write_text(UTIL_PY, encoding="utf-8")

    def run_cli(self, *args: str) -> dict:
        env = dict(os.environ, PYTHONUTF8="1")
        env.pop("CODE_INTEL_REPO_ROOT", None)
        done = subprocess.run([sys.executable, str(CLI), "--root", str(self.fixture), *args],
                              capture_output=True, text=True, timeout=180,
                              cwd=str(self.fixture), env=env)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_definition_after_disk_edit(self):
        first = self.run_cli("definition", "marker_bounds")
        self.assertEqual(first["definitions"][0]["file"], "pkg/util.py")
        self.assertEqual(first["definitions"][0]["line"], self.def_line)
        self.assertEqual(first["source"], "ast")

        pad_above(self.util_py)
        second = self.run_cli("definition", "marker_bounds")
        self.assertEqual(second["definitions"][0]["line"], self.def_line + PAD_LINES)

    def test_references_and_outline_and_module_map(self):
        refs = self.run_cli("references", "marker_bounds")
        self.assertEqual({hit["file"] for hit in refs["references"]}, {"pkg/util.py", "pkg/main.py"})
        outline = self.run_cli("outline", "pkg/util.py")
        self.assertEqual({symbol["name"] for symbol in outline["symbols"]},
                         {"marker_bounds", "helper"})
        modules = self.run_cli("module_map", "pkg")
        self.assertEqual({module["file"] for module in modules["modules"]},
                         {"pkg/__init__.py", "pkg/util.py", "pkg/main.py"})

    def test_missing_symbol_is_an_error_payload(self):
        env = dict(os.environ, PYTHONUTF8="1")
        env.pop("CODE_INTEL_REPO_ROOT", None)
        done = subprocess.run([sys.executable, str(CLI), "--root", str(self.fixture),
                               "definition", "no_such_symbol_anywhere"],
                              capture_output=True, text=True, timeout=180, env=env)
        self.assertEqual(done.returncode, 1)
        payload = json.loads(done.stdout)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
