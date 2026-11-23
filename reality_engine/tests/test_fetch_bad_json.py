"""BSE sometimes answers 200 with an HTML error page: http_get retries it, api_rows splits the window, and one
refused window never stops the metadata pass for the other companies (23 Nov 2026, 394-company fetch)."""
from __future__ import annotations

from datetime import date

import pytest

from reality_engine.scripts import fetch_pilot60_history as f


class _Resp:
    def __init__(self, body: bytes, status: int = 200):
        self.content, self.status_code = body, status


class _Session:
    def __init__(self, bodies):
        self.bodies = list(bodies)

    def get(self, url, headers=None, timeout=None):
        return self.bodies.pop(0)


class _Pacer:
    def wait(self):
        pass

    def block(self, s):
        pass


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(f.time, "sleep", lambda s: None)


def test_bad_json_is_retried():
    s = _Session([_Resp(b"\r\n\r\n<html>"), _Resp(b'{"Table": []}')])
    payload, status, attempts, err = f.http_get(s, "u", _Pacer(), want_json=True)
    assert payload == {"Table": []} and attempts == 2 and err is None


def test_bad_json_every_try_splits_window(monkeypatch):
    calls = []

    def fake_get(session, url, pacer, want_json=False, **kw):
        calls.append(url)
        if len(calls) == 1:
            return None, 200, 4, "bad json: Expecting value"
        return {"Table": []}, 200, 1, None

    monkeypatch.setattr(f, "http_get", fake_get)
    assert f.api_rows(None, _Pacer(), "532149", date(2026, 1, 1), date(2026, 11, 22)) == []
    assert len(calls) == 3          # the refused page, then the two halves
