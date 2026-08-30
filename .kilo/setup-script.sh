#!/usr/bin/env bash
# Agent Manager Worktree Setup Script (POSIX)
set -euo pipefail

TARGET_DIR="${WORKTREE_PATH:-$(pwd)}"
cd "$TARGET_DIR"

echo "[Kilo Setup] Initializing Reality Engine worktree at: $TARGET_DIR"

# 1. Create runtime directories
mkdir -p reality_engine/data/{bhavcopy,pdfs,reports,browser_profile,lancedb}
mkdir -p reality_engine/data/inbox/{images,pdfs,text,processed,failed}

# 2. Dependency installation is opt-in. Worktree creation must not trigger
#    large downloads implicitly.
if [ "${KILO_INSTALL_DEPS:-0}" = "1" ] && [ -f "requirements.txt" ]; then
    python -m pip install -r requirements.txt
else
    echo "[Kilo Setup] Dependencies not installed. Set KILO_INSTALL_DEPS=1 to opt in."
fi

# 3. Keep setup side-effect-light; use /bootstrap explicitly for fixture data.
echo "[Kilo Setup] Runtime directories prepared. Run /bootstrap when fixture data is needed."

# 4. Register the twice-daily Missed-Days Catcher via cron (POSIX/WSL fallback).
#    Runs at 16:00 (pre-close) and 23:00 (post-close) IST, Mon-Fri. The schedule
#    is expressed in the system local time -- ensure the host clock is set to IST
#    (or translate 16:00/23:00 IST to local cron times accordingly).
#    Idempotent: existing catchup_scheduler cron lines are removed first.
LOG_FILE="$TARGET_DIR/reality_engine/data/logs/catchup_cron.log"
mkdir -p "$(dirname "$LOG_FILE")"
CRON_4PM="0 16 * * 1-5 cd \"$TARGET_DIR\" && python -m reality_engine.pipeline.catchup_scheduler --mode pre-close >> \"$LOG_FILE\" 2>&1"
CRON_11PM="0 23 * * 1-5 cd \"$TARGET_DIR\" && python -m reality_engine.pipeline.catchup_scheduler --mode post-close >> \"$LOG_FILE\" 2>&1"
( crontab -l 2>/dev/null | grep -v "catchup_scheduler"; echo "$CRON_4PM"; echo "$CRON_11PM" ) | crontab -
echo "[Kilo Setup] Cron entries registered (16:00 + 23:00 IST, Mon-Fri)."

echo "[Kilo Setup] Worktree initialized successfully."
