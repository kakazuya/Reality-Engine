#!/usr/bin/env python3
"""Entry point for the local dsh-worker MCP stdio server."""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from plugin_server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
