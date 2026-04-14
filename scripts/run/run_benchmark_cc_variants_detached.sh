#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-variants"
CONFIG_PATH="configs/suites/benchmark_cc_variants.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/benchmark_cc_variants_${STAMP}.log"
META_FILE="$LOG_DIR/benchmark_cc_variants_latest.env"

mkdir -p "$LOG_DIR"

cd "$ROOT_DIR"

tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_benchmark_cc_variants_inner.sh <<'INNER'
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
  echo "CC-MAPF benchmark_cc_variants"
  echo "Started: $(date)"
  echo "Root: $ROOT_DIR"
  echo "Config: $CONFIG_PATH"
  echo "========================================"
  python -m cc_mapf.cli batch --config "$CONFIG_PATH"
  echo "========================================"
  echo "Finished: $(date)"
  echo "========================================"
} 2>&1 | tee -a "$LOG_FILE"

RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_benchmark_cc_variants 2>/dev/null | head -1 || true)"
if [ -n "$RUN_DIR" ]; then
  {
    echo "RUN_DIR=$RUN_DIR"
    echo "LOG_FILE=$LOG_FILE"
    echo "FINISHED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
  } > "$META_FILE"
fi

exec bash
INNER

chmod +x /tmp/run_benchmark_cc_variants_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_benchmark_cc_variants_inner.sh '$ROOT_DIR' '$CONFIG_PATH' '$LOG_FILE' '$META_FILE'"

echo "Started detached benchmark session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
