"""BSEClient.fetch_corporate_announcements reads every 50-row page (T-157 follow-up, 9 Nov 2026)."""
import importlib

bse_mod = importlib.import_module("reality_engine.ingestion.bse_client")


def _fake_pages(total: int, page_size: int = 50):
    calls = []

    def fake_json(url, params=None, **_):
        calls.append(dict(params or {}))
        page = int(params["pageno"])
        start = (page - 1) * page_size
        rows = [{"NEWSID": str(i), "NEWSSUB": f"row {i}"} for i in range(start, min(start + page_size, total))]
        return {"Table": rows, "Table1": [{"ROWCNT": total}]}

    return fake_json, calls


def _client(monkeypatch, total):
    fake, calls = _fake_pages(total)
    monkeypatch.setattr(bse_mod, "bse_json", fake)
    client = bse_mod.BSEClient()
    monkeypatch.setattr(client, "_warmup_session", lambda: None)
    return client, calls


def test_reads_every_page_up_to_rowcnt(monkeypatch):
    client, calls = _client(monkeypatch, 145)
    rows = client.fetch_corporate_announcements("500114", category="-1", from_date="20251201", to_date="20261109")
    assert len(rows) == 145
    assert [c["pageno"] for c in calls] == [1, 2, 3]
    assert len({r["NEWSID"] for r in rows}) == 145


def test_single_page_stops_after_one_call(monkeypatch):
    client, calls = _client(monkeypatch, 12)
    rows = client.fetch_corporate_announcements("533278", category="-1", from_date="20251201", to_date="20261109")
    assert len(rows) == 12 and len(calls) == 1


def test_no_data_returns_empty(monkeypatch):
    monkeypatch.setattr(bse_mod, "bse_json", lambda url, params=None, **_: None)
    client = bse_mod.BSEClient()
    monkeypatch.setattr(client, "_warmup_session", lambda: None)
    assert client.fetch_corporate_announcements("1", from_date="20251201", to_date="20261109") == []
