#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-warehouse-focus"
CONFIG_PATH="configs/suites/benchmark_windowed_cc_warehouse_32_focus.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/windowed_cc_warehouse_focus_${STAMP}.log"
META_FILE="$LOG_DIR/windowed_cc_warehouse_focus_latest.env"

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_windowed_cc_warehouse_focus_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
CONFIG_PATH="$2"
LOG_FILE="$3"
META_FILE="$4"

cd "$ROOT_DIR"
source .venv/bin/activate
export MPLBACKEND=Agg

{
  echo "========================================"
  echo "Windowed CC warehouse_32x32_12a focus"
  echo "Started: $(date)"
  echo "Root: $ROOT_DIR"
  echo "Config: $CONFIG_PATH"
  echo "========================================"
  python -m cc_mapf.cli batch --config "$CONFIG_PATH"
  echo "========================================"
  echo "Finished: $(date)"
  echo "========================================"
} 2>&1 | tee -a "$LOG_FILE"

RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_benchmark_windowed_cc_warehouse_32_focus 2>/dev/null | head -1 || true)"
if [ -n "$RUN_DIR" ]; then
  {
    echo "RUN_DIR=$RUN_DIR"
    echo "LOG_FILE=$LOG_FILE"
    echo "FINISHED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
  } > "$META_FILE"
fi

exec bash
INNER

chmod +x /tmp/run_windowed_cc_warehouse_focus_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_windowed_cc_warehouse_focus_inner.sh '$ROOT_DIR' '$CONFIG_PATH' '$LOG_FILE' '$META_FILE'"

echo "Started detached warehouse focus session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
