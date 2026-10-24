"""Install the packages dsh workers repeatedly need into the main Python.

Usage::

    python reality_engine/scripts/setup_worker_env.py --dry-run
    python reality_engine/scripts/setup_worker_env.py

Installs into the user site (``--user``) so no administrator rights are needed
and the repository stays untouched.  Idempotent: a package already importable
through ``importlib.metadata`` is skipped and reported as unchanged.

``--dry-run`` never installs: it asks PyPI for each package's newest release
and reports whether a cp314 Windows wheel (or a pure-Python wheel) exists, so a
missing wheel is known before pip spends minutes timing out.

The pip/uv timeout used here matches the supervisor's worker environment
(``PIP_DEFAULT_TIMEOUT=120``, ``PIP_RETRIES=5``, ``UV_HTTP_TIMEOUT=120``); this
network's 15 s default read timeout fails on large wheels.

Per-task virtualenv (for a task that needs conflicting pins)::

    python -m venv .venv-task
    .venv-task\\Scripts\\python -m pip install -r requirements-worker.txt

``.venv-*/`` is gitignored.  A venv is opt-in per task; the shared user site is
the default so a worker never rebuilds the same environment.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / "requirements-worker.txt"
PIP_TIMEOUT = "120"
PIP_RETRIES = "5"
PYPI_TIMEOUT = 30
WINDOWS_TAGS = ("win_amd64", "win32", "win_arm64")


def parse_requirements(path: Path = REQUIREMENTS) -> list[tuple[str, str]]:
    """Return ``(distribution name, original requirement line)`` pairs."""
    if not path.is_file():
        raise SystemExit(f"requirements file not found: {path}")
    entries: list[tuple[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        spec = line.split(";", 1)[0].strip()
        name = spec
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "[", " "):
            name = name.split(separator, 1)[0]
        if name:
            entries.append((name.strip(), spec))
    return entries


def installed_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _wheel_rank(filename: str) -> int:
    """0 = best (standard cp314 win_amd64), 1 = abi3, 2 = pure, -1 = unusable.

    ``cp314t`` is the free-threaded build and is NOT compatible with the
    standard 3.14 interpreter, so it never counts.  An ``abi3`` wheel built for
    cp3x (x <= 14) is forward-compatible and does count.
    """
    if not filename.endswith(".whl"):
        return -1
    if "win_amd64" in filename and "-cp314-cp314-" in filename:
        return 0
    abi3 = re.search(r"-cp3(\d+)-abi3-win_amd64\.whl$", filename)
    if abi3 and int(abi3.group(1)) <= 14:
        return 1
    if "py3-none-any" in filename or "py2.py3-none-any" in filename:
        return 2
    return -1


def wheel_status(name: str) -> tuple[str | None, str | None, str | None]:
    """Return ``(latest_version, best_wheel_filename, error)`` for one package."""
    url = f"https://pypi.org/pypi/{name}/json"
    try:
        with urllib.request.urlopen(url, timeout=PYPI_TIMEOUT) as response:
            data = json.load(response)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return None, None, f"pypi_error:{type(exc).__name__}"
    version = str((data.get("info") or {}).get("version") or "")
    files = data.get("urls") or (data.get("releases") or {}).get(version) or []
    wheels = [str(entry.get("filename") or "") for entry in files]
    usable = sorted((wheel for wheel in wheels if _wheel_rank(wheel) >= 0), key=_wheel_rank)
    return version or None, (usable[0] if usable else None), None


def pip_install(requirement: str) -> int:
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--user",
        "--disable-pip-version-check",
        "--timeout",
        PIP_TIMEOUT,
        "--retries",
        PIP_RETRIES,
        requirement,
    ]
    print(f"installing: {' '.join(command[3:])}", flush=True)
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list packages and wheel availability; install nothing",
    )
    args = parser.parse_args(argv)
    entries = parse_requirements()
    print(f"python: {sys.version.split()[0]} ({sys.executable})")
    print(f"requirements: {REQUIREMENTS}")
    missing: list[tuple[str, str]] = []
    failures = 0
    for name, requirement in entries:
        current = installed_version(name)
        if args.dry_run:
            latest, wheel, error = wheel_status(name)
            state = current or "-"
            wheel_text = wheel or (error or "NO cp314 WINDOWS WHEEL")
            print(f"  {name:<14} installed={state:<12} latest={latest or '?':<12} {wheel_text}")
            if wheel is None:
                failures += 1
            continue
        if current is not None:
            print(f"  {name:<14} unchanged ({current})")
            continue
        code = pip_install(requirement)
        after = installed_version(name)
        if code != 0 or after is None:
            print(f"  {name:<14} FAILED (pip exit {code})")
            failures += 1
        else:
            print(f"  {name:<14} installed ({after})")
            missing.append((name, after))
    if args.dry_run:
        print(
            f"\n{len(entries)} packages checked; {failures} without a usable cp314 "
            "Windows or pure-Python wheel."
        )
        return 0
    print(f"\n{len(missing)} package(s) installed this run; {len(entries)} in total.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
