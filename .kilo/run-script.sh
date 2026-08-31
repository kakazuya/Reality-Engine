#!/usr/bin/env bash
# Agent Manager Run Script (POSIX)
# Launches the Streamlit financial terminal dashboard, or runs the catch-up
# scheduler when invoked with the "catchup" argument (used by cron).
TARGET_DIR="${WORKTREE_PATH:-$(pwd)}"
cd "$TARGET_DIR"

if [ "${1:-}" = "catchup" ]; then
    echo "[Kilo Run] Running Reality Engine missed-days catcher..."
    python -m reality_engine.pipeline.catchup_scheduler
    exit $?
fi

echo "[Kilo Run] Launching Reality Engine Streamlit Terminal..."
python reality_engine/cli.py dashboard --port 8501 --host localhost
