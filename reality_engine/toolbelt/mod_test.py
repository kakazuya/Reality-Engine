"""Run a Claude Code mod's checks the way this sandbox actually allows.

``claude plugin validate`` validates the manifest, ``tsc`` type-checks the hooks
from a tsconfig *outside* the mod (so the mod stays a clean submission), and each
``hooks/*.test.ts*`` runs alone via ``claude plugin test --file`` (the multi-file
runner hits the sandbox's EPERM spawn).  The per-file
``claude-plugin-test-report`` JSON lines are merged into one summary.

Examples:
    python -m reality_engine.toolbelt.mod_test plugins/dsh-workers-pane
    python -m reality_engine.toolbelt.mod_test plugins/dsh-workers-pane --skip-tsc

    from reality_engine.toolbelt.mod_test import run
    result = run("plugins/dsh-workers-pane")
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from ._common import REPO_ROOT, add_format, main_guard, print_result

MARKER = "claude-plugin-test-report"
TS_CONFIGS = REPO_ROOT / ".tools"
NPM_CACHE = REPO_ROOT / ".tmp" / "npm-cache"
TS_VERSION = "typescript@5.9.3"


def parse_report_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    """Extract ``claude-plugin-test-report {json}`` lines from one test run."""
    reports = []
    for line in lines:
        line = line.strip()
        if not line.startswith(MARKER):
            continue
        try:
            payload = json.loads(line[len(MARKER):].strip())
        except ValueError:
            continue
        if isinstance(payload, dict):
            reports.append(payload)
    return reports


def aggregate_reports(reports: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Merge per-file reports into files/tests/failures plus the failed cases."""
    tests = 0
    total_ms = 0.0
    failures: list[dict[str, Any]] = []
    for report in reports:
        for result in report.get("results") or []:
            tests += 1
            try:
                total_ms += float(result.get("ms") or 0.0)
            except (TypeError, ValueError):
                pass
            if result.get("failure"):
                failures.append({"file": report.get("file"), "title": result.get("title"),
                                 "failure": str(result.get("failure"))[:1000]})
    return {"files": len(reports), "tests": tests, "failures": len(failures),
            "ms": round(total_ms, 1), "failed": failures}


def _run(cmd: Sequence[str], timeout: float, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(list(cmd), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env=env)


def _which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidate = Path.home() / ".local" / "bin" / name
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_bin(explicit: str | None, name: str) -> str | None:
    """An explicit path/command wins, but only if it actually exists."""
    if explicit:
        return explicit if Path(explicit).exists() or shutil.which(explicit) else None
    return _which(name)


def _find_dts() -> str | None:
    """Locate the bundled ``claude-code.d.ts`` the mod types import."""
    bases = {Path(tempfile.gettempdir()), Path(os.environ.get("TEMP") or ""),
             Path(os.environ.get("TMP") or ""), Path.home() / "AppData" / "Local" / "Temp"}
    hits: list[Path] = []
    for base in bases:
        if not base or not base.exists():
            continue
        hits.extend(Path(p) for p in glob.glob(
            str(base / "claude" / "bundled-skills" / "*" / "*" / "plugin-authoring" / "types" / "claude-code.d.ts")))
    if not hits:
        return None
    return str(max(hits, key=lambda p: p.stat().st_mtime).resolve()).replace("\\", "/")


def _default_tsconfig(mod: Path) -> Path:
    """Use the repo's external tsconfig when one exists, else generate one in .tmp."""
    existing = TS_CONFIGS / mod.name / "tsconfig.json"
    if existing.exists():
        return existing
    out = REPO_ROOT / ".tmp" / "mod_test" / mod.name / "tsconfig.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    include = []
    dts = _find_dts()
    if dts:
        include.append(dts)
    include.append(str((mod / "hooks").resolve()).replace("\\", "/"))
    if (mod / "types").exists():
        include.append(str((mod / "types").resolve()).replace("\\", "/"))
    config = {
        "compilerOptions": {
            "target": "es2023", "lib": ["es2023"], "types": [], "module": "esnext",
            "moduleResolution": "bundler", "strict": True,
            "noUncheckedIndexedAccess": True, "noEmit": True, "skipLibCheck": True,
            "jsx": "react", "jsxFactory": "h", "jsxFragmentFactory": "Fragment",
        },
        "include": include,
    }
    out.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return out


def _tail(text: str, limit: int = 3000) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else "…" + text[-limit:]


def run(mod: str | Path, *, tsconfig: str | Path | None = None, skip_validate: bool = False,
        skip_tsc: bool = False, claude: str | None = None, npx: str | None = None,
        timeout: float = 600.0) -> dict[str, Any]:
    """Validate, type-check and run each hook test; returns one merged summary."""
    mod_dir = Path(mod).resolve()
    if not mod_dir.is_dir():
        raise FileNotFoundError(f"mod directory not found: {mod_dir}")
    claude_bin = _resolve_bin(claude, "claude")
    result: dict[str, Any] = {"mod": str(mod_dir)}

    if skip_validate:
        result["validate"] = {"ok": None, "skipped": True}
    elif not claude_bin:
        result["validate"] = {"ok": None, "skipped": "claude CLI not found"}
    else:
        proc = _run([claude_bin, "plugin", "validate", str(mod_dir)], timeout)
        result["validate"] = {"ok": proc.returncode == 0, "output": _tail(proc.stdout + proc.stderr)}

    if skip_tsc:
        result["tsc"] = {"ok": None, "skipped": True}
    else:
        npx_bin = _resolve_bin(npx, "npx")
        config = Path(tsconfig).resolve() if tsconfig else _default_tsconfig(mod_dir)
        if not npx_bin:
            result["tsc"] = {"ok": None, "skipped": "npx not found", "tsconfig": str(config)}
        else:
            NPM_CACHE.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ)
            env.update({"npm_config_cache": str(NPM_CACHE), "TMP": str(REPO_ROOT / ".tmp"),
                        "TEMP": str(REPO_ROOT / ".tmp")})
            proc = _run([npx_bin, "--yes", "-p", TS_VERSION, "tsc", "-p", str(config)],
                        timeout, env)
            result["tsc"] = {"ok": proc.returncode == 0, "tsconfig": str(config),
                             "output": _tail(proc.stdout + proc.stderr)}

    reports: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if not claude_bin:
        result["tests"] = {"files": 0, "tests": 0, "failures": 0, "failed": [],
                           "skipped": "claude CLI not found"}
    else:
        tests = sorted(list((mod_dir / "hooks").glob("*.test.ts")) +
                       list((mod_dir / "hooks").glob("*.test.tsx")))
        for test_file in tests:
            proc = _run([claude_bin, "plugin", "test", "--file", str(test_file.resolve()),
                         str(mod_dir)], timeout)
            parsed = parse_report_lines(proc.stdout.splitlines())
            reports.extend(parsed)
            if proc.returncode != 0 and not parsed:
                errors.append({"file": str(test_file), "returncode": proc.returncode,
                               "output": _tail(proc.stdout + proc.stderr)})
        summary = aggregate_reports(reports)
        summary["errors"] = errors
        result["tests"] = summary

    checks = ("validate", "tsc", "tests")
    skipped = [name for name in checks if (result.get(name) or {}).get("skipped")]
    result["skipped"] = skipped
    result["ok"] = (len(skipped) < len(checks)
                    and result.get("validate", {}).get("ok") is not False
                    and result.get("tsc", {}).get("ok") is not False
                    and result.get("tests", {}).get("failures", 0) == 0
                    and not result.get("tests", {}).get("errors"))
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.mod_test",
        description="Validate + tsc + per-file claude plugin test, one merged summary.")
    ap.add_argument("mod", help="mod directory (contains .claude-plugin/plugin.json and hooks/)")
    ap.add_argument("--tsconfig", help="external tsconfig (default: .tools/<mod>/tsconfig.json or generated)")
    ap.add_argument("--skip-validate", action="store_true")
    ap.add_argument("--skip-tsc", action="store_true")
    ap.add_argument("--claude", help="claude executable")
    ap.add_argument("--npx", help="npx executable")
    ap.add_argument("--timeout", type=float, default=600.0, help="seconds per command")
    add_format(ap)
    args = ap.parse_args(argv)
    result = run(args.mod, tsconfig=args.tsconfig, skip_validate=args.skip_validate,
                 skip_tsc=args.skip_tsc, claude=args.claude, npx=args.npx,
                 timeout=args.timeout)
    print_result(result, args.format)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    main_guard(main)
