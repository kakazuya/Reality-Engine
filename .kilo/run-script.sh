#!/usr/bin/env bash
# Agent Manager Run Script (POSIX)
TARGET_DIR="${WORKTREE_PATH:-$(pwd)}"
cd "$TARGET_DIR"

echo "[Kilo Run] Launching Reality Engine Streamlit Terminal..."
python reality_engine/cli.py dashboard --port 8501 --host localhost
