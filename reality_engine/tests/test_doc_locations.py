"""T-101: a catalog row is found on disk, on Drive by path, drifted date prefix or sha name, or reported not held."""
import json

from reality_engine.scripts.doc_locations import load_listing, locate

SHA = "a" * 64


def _listing(tmp_path):
    (tmp_path / "listing_D_pdfs.json").write_text(json.dumps([
        {"Path": "KEC/ANNUAL_REPORT/20261024_22fed564_AnnPdfOpen.aspx.pdf", "Size": 10}]), encoding="utf-8")
    (tmp_path / "listing_results_pdfs.json").write_text(json.dumps([
        {"Path": f"2026-09-30/{SHA}.pdf", "Size": 20}]), encoding="utf-8")
    return load_listing(tmp_path)


def test_drive_match_by_drifted_date_prefix(tmp_path):
    files, by_suffix, by_sha = _listing(tmp_path)
    stored = r"D:\RealityEngine\pdfs\KEC\ANNUAL_REPORT\20260923_22fed564_AnnPdfOpen.aspx.pdf"
    kind, disk, drive, how = locate(stored, None, {}, files, by_suffix, by_sha)
    assert (kind, drive, how) == ("drive", "D_pdfs/KEC/ANNUAL_REPORT/20261024_22fed564_AnnPdfOpen.aspx.pdf",
                                  "hash_suffix")


def test_drive_match_by_sha_name_and_disk_first(tmp_path):
    files, by_suffix, by_sha = _listing(tmp_path)
    assert locate(None, SHA.upper(), {}, files, by_suffix, by_sha)[2] == f"results_pdfs/2026-09-30/{SHA}.pdf"
    local = tmp_path / "x.pdf"
    local.write_bytes(b"%PDF")
    kind, disk, drive, _ = locate(None, SHA, {SHA: local}, files, by_suffix, by_sha)
    assert kind == "disk+drive" and disk == str(local)


def test_not_held_kinds(tmp_path):
    files, by_suffix, by_sha = _listing(tmp_path)
    assert locate(None, None, {}, files, by_suffix, by_sha)[0] == "not_held_no_file_ref"
    assert locate(None, "b" * 64, {}, files, by_suffix, by_sha)[0] == "not_held"
