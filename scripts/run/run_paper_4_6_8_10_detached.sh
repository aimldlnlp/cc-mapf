#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-paper-4-6-8-10"
STAMP="$(date +%Y%m%d-%H%M%S)"
ROLLOUT_DIR="$ROOT_DIR/artifacts/paper-rollouts/${STAMP}-paper-4-6-8-10"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/paper_4_6_8_10_${STAMP}.log"
META_FILE="$LOG_DIR/paper_4_6_8_10_latest.env"
STATUS_FILE="$ROLLOUT_DIR/paper_rollout_status.json"
SUMMARY_FILE="$ROLLOUT_DIR/paper_rollout_summary.json"

mkdir -p "$LOG_DIR" "$ROLLOUT_DIR"
cd "$ROOT_DIR"
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_paper_4_6_8_10_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
ROLLOUT_DIR="$2"
LOG_FILE="$3"
META_FILE="$4"
STATUS_FILE="$5"
SUMMARY_FILE="$6"
SESSION_NAME="$7"

cd "$ROOT_DIR"
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi
export MPLBACKEND=Agg

PILOT_RUN_DIR=""
OFFICIAL_RUN_DIR=""
COMPARISON_RUN_DIR=""
BUNDLE_DIR=""
SELECTED_PLANNER=""
GATE_STATUS=""
ROLLOUT_STATUS="running"
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
FINISHED_AT=""

write_meta() {
  cat > "$META_FILE" <<EOF
SESSION_NAME=$SESSION_NAME
LOG_FILE=$LOG_FILE
ROLLOUT_DIR=$ROLLOUT_DIR
STATUS_FILE=$STATUS_FILE
SUMMARY_FILE=$SUMMARY_FILE
PILOT_RUN_DIR=$PILOT_RUN_DIR
OFFICIAL_RUN_DIR=$OFFICIAL_RUN_DIR
COMPARISON_RUN_DIR=$COMPARISON_RUN_DIR
BUNDLE_DIR=$BUNDLE_DIR
SELECTED_PLANNER=$SELECTED_PLANNER
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
  echo "Paper rollout 4/6/8/10"
  echo "Started: $STARTED_AT"
  echo "Root: $ROOT_DIR"
  echo "Rollout dir: $ROLLOUT_DIR"
  echo "========================================"
  echo

  python -m cc_mapf.paper_rollout \
    --root-dir "$ROOT_DIR" \
    --rollout-dir "$ROLLOUT_DIR" \
    --status-file "$STATUS_FILE"

  eval "$(
    python - "$SUMMARY_FILE" <<'PY'
import json
import sys
from pathlib import Path

summary = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if "error" in summary:
    print("ROLLOUT_STATUS=failed")
    print("GATE_STATUS=failed")
    raise SystemExit(1)
gate = summary["official_gate_status"]
gate_status = "passed" if gate["passed"] else "failed"
print(f"PILOT_RUN_DIR={summary.get('pilot_run_dir', '')}")
print(f"OFFICIAL_RUN_DIR={summary.get('official_run_dir', '')}")
print(f"COMPARISON_RUN_DIR={summary.get('comparison_run_dir', '')}")
print(f"BUNDLE_DIR={summary.get('bundle_dir', '')}")
print(f"SELECTED_PLANNER={summary.get('selected_planner', '')}")
print(f"GATE_STATUS={gate_status}")
print(f"ROLLOUT_STATUS={'completed' if summary['bundle_validation']['passed'] else 'completed_with_bundle_failure'}")
PY
  )"

  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  write_meta
  echo
  echo "========================================"
  echo "Paper rollout complete"
  echo "Pilot run: $PILOT_RUN_DIR"
  echo "Official run: $OFFICIAL_RUN_DIR"
  echo "Comparison run: $COMPARISON_RUN_DIR"
  echo "Bundle: $BUNDLE_DIR"
  echo "Selected planner: $SELECTED_PLANNER"
  echo "Gate status: $GATE_STATUS"
  echo "========================================"
} 2>&1 | tee -a "$LOG_FILE" || PIPE_STATUS=$?

if [ -z "$FINISHED_AT" ]; then
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  if [ "$PIPE_STATUS" -ne 0 ] && [ "$ROLLOUT_STATUS" = "running" ]; then
    ROLLOUT_STATUS="failed"
  fi
  write_meta
fi

echo "Pipeline exit status: $PIPE_STATUS" | tee -a "$LOG_FILE"
exec bash
INNER

chmod +x /tmp/run_paper_4_6_8_10_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "ROLLOUT_DIR=$ROLLOUT_DIR"
  echo "STATUS_FILE=$STATUS_FILE"
  echo "SUMMARY_FILE=$SUMMARY_FILE"
  echo "ROLLOUT_STATUS=starting"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_paper_4_6_8_10_inner.sh '$ROOT_DIR' '$ROLLOUT_DIR' '$LOG_FILE' '$META_FILE' '$STATUS_FILE' '$SUMMARY_FILE' '$SESSION_NAME'"

echo "Started detached paper rollout session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Rollout dir: $ROLLOUT_DIR"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
