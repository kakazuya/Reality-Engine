import os
import importlib.util


def test_server_no_sql_env():
    os.environ["REALITY_DATA_NO_PILOT3_SQL"] = "1"
    os.environ.setdefault("REALITY_PILOT3_DB", "x.db")
    spec = importlib.util.spec_from_file_location("server_no_sql", "plugins/reality-data/server/server.py")
    # adjust path
    import sys
    sys.path.insert(0, "plugins/reality-data/server")
    # remove cached
    sys.modules.pop("server", None)
    import server
    assert not hasattr(server, "pilot3_sql")
    assert "pilot3_sql" not in server.INSTRUCTIONS
    # default (unset) not tested here


def test_server_default_has_sql():
    os.environ.pop("REALITY_DATA_NO_PILOT3_SQL", None)
    os.environ.setdefault("REALITY_PILOT3_DB", "x.db")
    import sys
    sys.path.insert(0, "plugins/reality-data/server")
    sys.modules.pop("server", None)
    import server
    assert hasattr(server, "pilot3_sql")
    assert "pilot3_sql" in server.INSTRUCTIONS