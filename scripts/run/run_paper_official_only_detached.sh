#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-paper-official-only"
CONFIG_PATH="configs/suites/paper_best_4_6_8_10_official_rerun.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/paper_official_only_${STAMP}.log"
META_FILE="$LOG_DIR/paper_official_only_latest.env"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_paper_official_only_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
CONFIG_PATH="$2"
LOG_FILE="$3"
META_FILE="$4"

cd "$ROOT_DIR"
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi
export MPLBACKEND=Agg

SESSION_NAME="cc-paper-official-only"
RUN_DIR=""
SOLVED_VALID=0
TOTAL=0
OVERALL_RATE=0
SCALE_4=0
SCALE_6=0
SCALE_8=0
SCALE_10=0
GATE_STATUS="running"
ROLLOUT_STATUS="running"
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
FINISHED_AT=""

write_meta() {
  cat > "$META_FILE" <<EOF
SESSION_NAME=$SESSION_NAME
LOG_FILE=$LOG_FILE
CONFIG_PATH=$CONFIG_PATH
RUN_DIR=$RUN_DIR
SOLVED_VALID=$SOLVED_VALID
TOTAL=$TOTAL
OVERALL_RATE=$OVERALL_RATE
SCALE_4=$SCALE_4
SCALE_6=$SCALE_6
SCALE_8=$SCALE_8
SCALE_10=$SCALE_10
GATE_STATUS=$GATE_STATUS
ROLLOUT_STATUS=$ROLLOUT_STATUS
STARTED_AT=$STARTED_AT
FINISHED_AT=$FINISHED_AT
EOF
}

write_meta
PIPE_STATUS=0

{
  echo "========================================"
  echo "Paper official-only rerun"
  echo "Started: $STARTED_AT"
  echo "Config: $CONFIG_PATH"
  echo "========================================"
  echo

  python -m pytest -q tests/test_connected_step_performance.py tests/test_connected_step_large_scale.py
  python -m cc_mapf.cli batch --config "$CONFIG_PATH"

  RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_paper_best_4_6_8_10_official_rerun 2>/dev/null | head -1 || true)"
  if [ -z "$RUN_DIR" ] || [ ! -f "$RUN_DIR/results.json" ]; then
    echo "Official rerun did not produce a run directory"
    ROLLOUT_STATUS="failed"
    GATE_STATUS="failed"
    exit 1
  fi

  eval "$(
    python - "$RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run = Path(sys.argv[1])
records = json.loads((run / "results.json").read_text(encoding="utf-8"))["records"]
solved = sum(1 for r in records if r["solved"])
total = len(records)
def rate(scale):
    subset = [r for r in records if r["scale"] == scale]
    solved_subset = sum(1 for r in subset if r["solved"])
    return solved_subset / len(subset) if subset else 0.0
overall = solved / total if total else 0.0
gate = int(
    overall >= 0.90
    and rate("16x16_4a") >= 1.0
    and rate("20x20_6a") >= 0.90
    and rate("24x24_8a") >= 0.85
    and rate("28x28_10a") >= 0.80
)
print(f"SOLVED_VALID={solved}")
print(f"TOTAL={total}")
print(f"OVERALL_RATE={overall:.6f}")
print(f"SCALE_4={rate('16x16_4a'):.6f}")
print(f"SCALE_6={rate('20x20_6a'):.6f}")
print(f"SCALE_8={rate('24x24_8a'):.6f}")
print(f"SCALE_10={rate('28x28_10a'):.6f}")
print(f"GATE_STATUS={'passed' if gate else 'failed'}")
print(f"ROLLOUT_STATUS=completed")
PY
  )"

  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  write_meta
  echo
  echo "========================================"
  echo "Official-only rerun complete"
  echo "Run: $RUN_DIR"
  echo "Solved-valid: $SOLVED_VALID / $TOTAL"
  echo "Overall rate: $OVERALL_RATE"
  echo "28x28_10a rate: $SCALE_10"
  echo "Gate: $GATE_STATUS"
  echo "========================================"
} 2>&1 | tee -a "$LOG_FILE" || PIPE_STATUS=$?

if [ -z "$FINISHED_AT" ]; then
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  if [ "$PIPE_STATUS" -ne 0 ] && [ "$ROLLOUT_STATUS" = "running" ]; then
    ROLLOUT_STATUS="failed"
    GATE_STATUS="failed"
  fi
  write_meta
fi

echo "Pipeline exit status: $PIPE_STATUS" | tee -a "$LOG_FILE"
exec bash
INNER

chmod +x /tmp/run_paper_official_only_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "CONFIG_PATH=$CONFIG_PATH"
  echo "ROLLOUT_STATUS=starting"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_paper_official_only_inner.sh '$ROOT_DIR' '$CONFIG_PATH' '$LOG_FILE' '$META_FILE'"

echo "Started detached official-only rerun session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
