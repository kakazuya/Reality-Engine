#!/usr/bin/env bash
# Probes every passed Zen model (zen_models.json) every 20 min with a one-line call; logs each result to
# reality_engine/data/logs/zen_quota_probe.log and prints a line the first time any model answers again.
cd "$(dirname "$0")/../.."
LOG=reality_engine/data/logs/zen_quota_probe.log
models=$(python -c "import json; r=json.load(open('reality_engine/scripts/zen_models.json')); print(' '.join(m for m,v in r.items() if isinstance(v,dict) and v.get('status')=='passed'))")
announced=0
for i in $(seq 1 36); do
  for m in $models; do
    out=$(timeout 120 opencode run -m "opencode/$m" --title "zen quota probe" "Reply with exactly: ok" < /dev/null 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | grep -v '^> ' | tr '\n' ' ' | cut -c1-150)
    if echo "$out" | grep -qiE '(^| )ok( |$)'; then res=OK; else res="REFUSED: $out"; fi
    echo "$(date '+%F %T') $m $res" >> "$LOG"
    if [ "$res" = OK ] && [ $announced = 0 ]; then echo "Zen answering again: $m at $(date +%H:%M)"; announced=1; fi
  done
  [ $announced = 1 ] && exit 0
  sleep 1200
done
