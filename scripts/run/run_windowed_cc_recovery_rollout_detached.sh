#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-windowed-recovery-rollout"
FOCUS_CONFIG="configs/suites/benchmark_windowed_cc_warehouse_32_focus.yaml"
FULL_CONFIG="configs/suites/benchmark_cc_variants.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/windowed_cc_recovery_rollout_${STAMP}.log"
META_FILE="$LOG_DIR/windowed_cc_recovery_rollout_latest.env"

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_windowed_cc_recovery_rollout_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
FOCUS_CONFIG="$2"
FULL_CONFIG="$3"
LOG_FILE="$4"
META_FILE="$5"

cd "$ROOT_DIR"
source .venv/bin/activate
export MPLBACKEND=Agg

SESSION_NAME="cc-windowed-recovery-rollout"
FOCUS_RUN_DIR=""
FULL_RUN_DIR=""
VIZ_DIR=""
FOCUS_SOLVED=0
FOCUS_TOTAL=0
FULL_WINDOWED_CC_SOLVED=0
FULL_WINDOWED_CC_TOTAL=0
FULL_REFERENCE_EXEC_INVALID=0
FULL_CORRIDOR_S03_SOLVED=0
FULL_SMALL_SCALE_UNSOLVED=0
FOCUS_GATE_PASSED=0
FULL_GATE_PASSED=0
ROLL_OUT_STATUS="running"

write_meta() {
  cat > "$META_FILE" <<EOF
SESSION_NAME=$SESSION_NAME
LOG_FILE=$LOG_FILE
FOCUS_RUN_DIR=$FOCUS_RUN_DIR
FULL_RUN_DIR=$FULL_RUN_DIR
VIZ_DIR=$VIZ_DIR
FOCUS_SOLVED=$FOCUS_SOLVED
FOCUS_TOTAL=$FOCUS_TOTAL
FULL_WINDOWED_CC_SOLVED=$FULL_WINDOWED_CC_SOLVED
FULL_WINDOWED_CC_TOTAL=$FULL_WINDOWED_CC_TOTAL
FULL_REFERENCE_EXEC_INVALID=$FULL_REFERENCE_EXEC_INVALID
FULL_CORRIDOR_S03_SOLVED=$FULL_CORRIDOR_S03_SOLVED
FULL_SMALL_SCALE_UNSOLVED=$FULL_SMALL_SCALE_UNSOLVED
FOCUS_GATE_PASSED=$FOCUS_GATE_PASSED
FULL_GATE_PASSED=$FULL_GATE_PASSED
ROLLOUT_STATUS=$ROLL_OUT_STATUS
STARTED_AT=${STARTED_AT:-}
FINISHED_AT=${FINISHED_AT:-}
EOF
}

STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
write_meta

PIPE_STATUS=0

{
  echo "========================================"
  echo "Windowed CC executable recovery rollout"
  echo "Started: $STARTED_AT"
  echo "Root: $ROOT_DIR"
  echo "Focus config: $FOCUS_CONFIG"
  echo "Full config: $FULL_CONFIG"
  echo "========================================"
  echo

  echo "[1/4] Running regression tests"
  pytest -q tests/test_planner_variants.py
  pytest -q tests/test_cli_integration.py tests/test_environment_validation.py tests/test_render_style.py
  echo

  echo "[2/4] Running warehouse focus benchmark"
  python -m cc_mapf.cli batch --config "$FOCUS_CONFIG"
  FOCUS_RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_benchmark_windowed_cc_warehouse_32_focus 2>/dev/null | head -1 || true)"
  if [ -z "$FOCUS_RUN_DIR" ]; then
    echo "Focus benchmark did not produce a run directory"
    ROLL_OUT_STATUS="focus_run_missing"
    write_meta
    exit 1
  fi
  eval "$(
    python - "$FOCUS_RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
records = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["records"]
windowed = [record for record in records if record["planner"] == "windowed_cc"]
solved = sum(1 for record in windowed if record["solved"])
print(f"FOCUS_SOLVED={solved}")
print(f"FOCUS_TOTAL={len(windowed)}")
print(f"FOCUS_GATE_PASSED={1 if solved >= 1 else 0}")
PY
  )"
  write_meta
  echo "Focus result: $FOCUS_SOLVED/$FOCUS_TOTAL solved"
  if [ "$FOCUS_GATE_PASSED" -ne 1 ]; then
    echo "Focus gate failed: warehouse_32x32_12a stayed below 1/5"
    ROLL_OUT_STATUS="focus_gate_failed"
    FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
    write_meta
    exit 1
  fi
  echo

  echo "[3/4] Running full benchmark"
  python -m cc_mapf.cli batch --config "$FULL_CONFIG"
  FULL_RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_benchmark_cc_variants 2>/dev/null | head -1 || true)"
  if [ -z "$FULL_RUN_DIR" ]; then
    echo "Full benchmark did not produce a run directory"
    ROLL_OUT_STATUS="full_run_missing"
    FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
    write_meta
    exit 1
  fi
  eval "$(
    python - "$FULL_RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
records = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["records"]
windowed = [record for record in records if record["planner"] == "windowed_cc"]
solved = sum(1 for record in windowed if record["solved"])
reference_invalid = sum(
    1
    for record in windowed
    if record.get("reference_execution_policy") == "guide_only"
    and record.get("stall_exit_reason") == "reference_execution_invalid"
)
corridor_s03 = next(
    (
        record
        for record in windowed
        if record["instance"] == "corridor_32x32_12a_s03"
    ),
    None,
)
small_scale_unsolved = sum(
    1
    for record in windowed
    if record.get("scale") == "16x16_4a" and not record["solved"]
)
gate_passed = int(
    solved >= 52
    and reference_invalid == 0
    and corridor_s03 is not None
    and corridor_s03["solved"]
    and small_scale_unsolved == 0
)
print(f"FULL_WINDOWED_CC_SOLVED={solved}")
print(f"FULL_WINDOWED_CC_TOTAL={len(windowed)}")
print(f"FULL_REFERENCE_EXEC_INVALID={reference_invalid}")
print(f"FULL_CORRIDOR_S03_SOLVED={1 if corridor_s03 is not None and corridor_s03['solved'] else 0}")
print(f"FULL_SMALL_SCALE_UNSOLVED={small_scale_unsolved}")
print(f"FULL_GATE_PASSED={gate_passed}")
PY
  )"
  write_meta
  echo "Full benchmark result: $FULL_WINDOWED_CC_SOLVED/$FULL_WINDOWED_CC_TOTAL solved"
  echo "Guide-only reference_execution_invalid count: $FULL_REFERENCE_EXEC_INVALID"
  echo "corridor_32x32_12a_s03 solved: $FULL_CORRIDOR_S03_SOLVED"
  echo "Unsolved 16x16_4a cases: $FULL_SMALL_SCALE_UNSOLVED"
  echo

  echo "[4/4] Generating visualizations"
  VIZ_DIR="$FULL_RUN_DIR/analysis"
  .venv/bin/python scripts/render/render_advanced_visualizations.py "$FULL_RUN_DIR" analysis
  write_meta

  if [ "$FULL_GATE_PASSED" -eq 1 ]; then
    ROLL_OUT_STATUS="completed"
  else
    ROLL_OUT_STATUS="completed_but_gate_failed"
  fi
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  write_meta

  echo "========================================"
  echo "Rollout finished"
  echo "Focus run: $FOCUS_RUN_DIR"
  echo "Full run: $FULL_RUN_DIR"
  echo "Visualizations: $VIZ_DIR"
  echo "Rollout status: $ROLL_OUT_STATUS"
  echo "Finished: $FINISHED_AT"
  echo "========================================"
} 2>&1 | tee -a "$LOG_FILE" || PIPE_STATUS=$?

if [ -z "${FINISHED_AT:-}" ]; then
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  if [ "$PIPE_STATUS" -ne 0 ] && [ "$ROLL_OUT_STATUS" = "running" ]; then
    ROLL_OUT_STATUS="failed"
  fi
  write_meta
fi

echo "Pipeline exit status: $PIPE_STATUS" | tee -a "$LOG_FILE"

exec bash
INNER

chmod +x /tmp/run_windowed_cc_recovery_rollout_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "ROLLOUT_STATUS=starting"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_windowed_cc_recovery_rollout_inner.sh '$ROOT_DIR' '$FOCUS_CONFIG' '$FULL_CONFIG' '$LOG_FILE' '$META_FILE'"

echo "Started detached rollout session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
