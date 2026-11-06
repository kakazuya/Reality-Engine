"""T-102: a local raw file is deleted only when the same md5 and size are on Drive; databases are never touched."""
import hashlib
import json

from reality_engine.scripts import raw_to_drive as r


def test_compare_then_delete_only_files_on_drive(tmp_path):
    root = tmp_path / "raw"
    (root / "a").mkdir(parents=True)
    on, off, db = root / "a" / "on.pdf", root / "a" / "off.pdf", root / "a" / "x.db"
    on.write_bytes(b"on drive")
    off.write_bytes(b"not on drive")
    db.write_bytes(b"database")
    listing = tmp_path / "lst"
    listing.mkdir()
    (listing / "listing_pdfs.json").write_text(json.dumps([
        {"Path": "K/on.pdf", "Size": 8, "Hashes": {"md5": hashlib.md5(b"on drive").hexdigest()}}]), encoding="utf-8")
    con = r.open_manifest(str(tmp_path / "m.db"))
    r.step_hash(con, [str(root)])
    r.step_compare(con, listing)
    r.step_delete(con, really=False)
    assert on.exists()
    r.step_delete(con, really=True)
    assert not on.exists() and off.exists() and db.exists()
    assert con.execute("SELECT drive_path FROM local_file WHERE rel='a/on.pdf'").fetchone()[0] == "pdfs/K/on.pdf"
