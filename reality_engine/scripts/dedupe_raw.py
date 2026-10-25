"""Store identical raw files once: every duplicate becomes a hard link to the oldest copy.

Companies file the same results PDF twice (standalone/consolidated, revisions) and re-file
decks under new names; results PDFs alone could reach ~130-300 GB. Files under the raw
roots are grouped by size, then by sha256; the oldest file of a group stays the canonical
copy and every other copy is replaced by a hard link to it (same volume only — a hard link
cannot cross volumes). Every path that existed still opens.

Dry run by default: it prints what it would link and writes the JSON report without
touching a single file. ``--apply`` makes the links.

Usage:
    python -m reality_engine.scripts.dedupe_raw                       # dry run, D roots
    python -m reality_engine.scripts.dedupe_raw --root X --root Y     # explicit roots
    python -m reality_engine.scripts.dedupe_raw --apply               # make the links
    python -m reality_engine.scripts.dedupe_raw --report R.json       # elsewhere than RAW_ROOT
"""

from __future__ import annotations

import argparse
import errno
import json
from datetime import datetime
from pathlib import Path

from reality_engine.config import DATA_DIR, PDFS_DIR, RAW_ROOT
from reality_engine.raw_store import link_file, same_file, sha256_file

MIN_SIZE = 1024                                # smaller files save nothing worth a link
STATE_DIR = "_dedupe"                          # index + reports live here, never deduped
SKIP_SUFFIXES = (".part", ".lnk-tmp")


def default_roots() -> list[Path]:
    """RAW_ROOT and PDFS_DIR, existing ones only, without duplicates."""
    roots: list[Path] = []
    for root in (RAW_ROOT, PDFS_DIR):
        try:
            resolved = Path(root).resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return roots


def files_under(root: Path) -> list[Path]:
    """Every raw file under ``root``, minus partial downloads and our own state folder."""
    out = []
    for path in sorted(Path(root).rglob("*")):
        try:
            if not path.is_file():
                continue
            if STATE_DIR in path.relative_to(root).parts:
                continue
        except OSError:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES or ".lnk-tmp" in path.name:
            continue
        out.append(path)
    return out


def plan(roots: list[Path]) -> dict:
    """Group identical files; the oldest file of a group is the canonical copy.

    Only files whose size another file already has are hashed, so a raw pile of unique
    PDFs costs one directory walk and no reads.
    """
    files: list[tuple[int, int, float, Path]] = []
    folders = {str(root): {"files": 0, "small_skipped": 0} for root in roots}
    skipped: list[dict] = []
    for root in roots:
        for path in files_under(root):
            try:
                stat = path.stat()
            except OSError as exc:
                skipped.append({"path": str(path), "reason": f"stat_failed: {type(exc).__name__}"})
                continue
            folders[str(root)]["files"] += 1
            if stat.st_size < MIN_SIZE:
                folders[str(root)]["small_skipped"] += 1
                continue
            files.append((stat.st_dev, stat.st_size, stat.st_mtime, path))

    by_size: dict[tuple[int, int], list[tuple[float, Path]]] = {}
    for dev, size, mtime, path in files:
        by_size.setdefault((dev, size), []).append((mtime, path))

    groups: list[dict] = []
    hashed = 0
    for (_, size), entries in sorted(by_size.items()):
        if len(entries) < 2:
            continue
        by_sha: dict[str, list[tuple[float, Path]]] = {}
        for mtime, path in entries:
            try:
                sha = sha256_file(path)
            except OSError as exc:
                skipped.append({"path": str(path), "reason": f"hash_failed: {type(exc).__name__}"})
                continue
            hashed += 1
            by_sha.setdefault(sha, []).append((mtime, path))
        for sha, members in by_sha.items():
            if len(members) < 2:
                continue
            members.sort(key=lambda item: (item[0], str(item[1])))
            groups.append({
                "sha256": sha,
                "size": size,
                "canonical": str(members[0][1]),
                "duplicates": [str(path) for _, path in members[1:]],
            })
    return {"roots": [str(root) for root in roots], "folders": folders,
            "groups": groups, "skipped": skipped, "hashed": hashed}


def _verify_duplicate(dup: Path, canonical: Path, sha: str, size: int) -> str | None:
    """Why ``dup`` must not be replaced (None when linking it is safe).

    Both files are re-read just before the replace: a file that changed after the scan
    or a canonical copy that no longer holds the bytes must never cost the duplicate.
    """
    try:
        if dup.stat().st_size != size or sha256_file(dup) != sha:
            return "changed_since_scan"
        if canonical.stat().st_size != size or sha256_file(canonical) != sha:
            return "canonical_changed"
        cross_volume = dup.stat().st_dev != canonical.stat().st_dev
    except OSError as exc:
        return f"unreadable: {type(exc).__name__}"
    if cross_volume:
        return "cross_volume"
    if same_file(dup, canonical):
        return "already_linked"
    return None


def apply_plan(planned: dict) -> None:
    """Replace every duplicate with a hard link, or record why it stayed as it is."""
    for group in planned["groups"]:
        sha, size = group["sha256"], group["size"]
        canonical = Path(group["canonical"])
        group["links_made"] = 0
        group["bytes_saved"] = 0
        group["not_linked"] = []
        for dup_path in group["duplicates"]:
            dup = Path(dup_path)
            reason = _verify_duplicate(dup, canonical, sha, size)
            if reason is None:
                try:
                    link_file(canonical, dup)
                except OSError as exc:
                    reason = (
                        "cross_volume" if exc.errno == errno.EXDEV
                        else "locked_or_open" if isinstance(exc, PermissionError)
                        else f"link_failed: {type(exc).__name__}"
                    )
            if reason:
                group["not_linked"].append({"path": str(dup), "reason": reason})
                planned["skipped"].append({"path": str(dup), "reason": reason})
                continue
            group["links_made"] += 1
            group["bytes_saved"] += size


def _folder(path: str, roots: list[Path]) -> str:
    """The raw root a path belongs to (for the per-folder numbers)."""
    for root in roots:
        try:
            Path(path).relative_to(root)
            return str(root)
        except ValueError:
            continue
    return str(Path(path).parent)


def summarise(planned: dict, applied: bool) -> dict:
    """Per-folder and total counts; ``links_made``/``bytes_saved`` are what actually happened."""
    def empty() -> dict:
        return {"files": 0, "small_skipped": 0, "duplicate_groups": 0,
                "duplicate_files": 0, "links_made": 0, "bytes_saved": 0}

    roots = [Path(root) for root in planned["roots"]]
    folders = {root: {**empty(), "files": stats["files"],
                      "small_skipped": stats["small_skipped"]}
               for root, stats in planned["folders"].items()}
    for group in planned["groups"]:
        folders.setdefault(_folder(group["canonical"], roots), empty())["duplicate_groups"] += 1
        stayed = {item["path"] for item in group.get("not_linked", [])}
        for dup_path in group["duplicates"]:
            bucket = folders.setdefault(_folder(dup_path, roots), empty())
            bucket["duplicate_files"] += 1
            if dup_path not in stayed:
                bucket["links_made"] += 1
                bucket["bytes_saved"] += group["size"]
    totals = {key: sum(folder[key] for folder in folders.values()) for key in empty()}
    return {"applied": applied, "roots": planned["roots"], "hashed": planned["hashed"],
            "folders": folders, "totals": totals,
            "groups": planned["groups"], "skipped": planned["skipped"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", action="append", default=[],
                        help="raw root to dedupe (repeatable; default RAW_ROOT and PDFS_DIR)")
    parser.add_argument("--apply", action="store_true", help="make the links (default: dry run)")
    parser.add_argument("--report", default=None,
                        help="report path (default RAW_ROOT/_dedupe/<date>.json)")
    args = parser.parse_args(argv)

    roots = ([Path(root).resolve() for root in args.root] if args.root
             else default_roots())
    roots = [root for root in roots if root.is_dir()]
    if not roots:
        print(f"no raw root to scan (RAW_ROOT={RAW_ROOT} PDFS_DIR={PDFS_DIR})")
        return 1

    planned = plan(roots)
    if args.apply:
        apply_plan(planned)
    report = summarise(planned, args.apply)
    report["date"] = datetime.now().date().isoformat()

    path = Path(args.report) if args.report else RAW_ROOT / STATE_DIR / f"{report['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2)
    path.write_text(text, encoding="utf-8")
    if args.apply:
        # jobs.yaml only reads files inside the repo, so an applied run mirrors the report
        # where the freshness check can see it.
        mirror = DATA_DIR / "logs" / "dedupe_raw.json"
        mirror.parent.mkdir(parents=True, exist_ok=True)
        mirror.write_text(text, encoding="utf-8")

    totals = report["totals"]
    print(f"{'APPLIED' if args.apply else 'DRY RUN'}: {totals['files']} files, "
          f"{totals['duplicate_groups']} duplicate groups, "
          f"{totals['duplicate_files']} duplicates, {totals['links_made']} links made, "
          f"{totals['bytes_saved'] / 1e9:.2f} GB saved")
    for root, stats in report["folders"].items():
        print(f"  {root}: {stats['files']} files, {stats['duplicate_groups']} groups, "
              f"{stats['links_made']} linked, {stats['bytes_saved'] / 1e9:.2f} GB")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
