#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-paper-rerender"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/paper_rerender_analysis_${STAMP}.log"
META_FILE="$LOG_DIR/paper_rerender_analysis_latest.env"
ROLLOUT_DIR="$ROOT_DIR/artifacts/paper-rollouts/20260414-160417-paper-4-6-8-10"
OFFICIAL_RUN="$ROOT_DIR/artifacts/runs/20260414-110118_paper_best_4_6_8_10_official_rerun"
COMPARISON_CONFIG="$ROOT_DIR/configs/suites/paper_comparison_4_6_8_10.yaml"
RENDER_CONFIG="$ROOT_DIR/configs/render/paper_4_6_8_10.yaml"

if [ ! -d "$ROLLOUT_DIR" ] && [ -d "$ROOT_DIR/artifacts/paper_rollouts/20260414-160417_paper_4_6_8_10" ]; then
  ROLLOUT_DIR="$ROOT_DIR/artifacts/paper_rollouts/20260414-160417_paper_4_6_8_10"
fi

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_paper_rerender_analysis_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
ROLLOUT_DIR="$2"
OFFICIAL_RUN="$3"
COMPARISON_CONFIG="$4"
RENDER_CONFIG="$5"
LOG_FILE="$6"
META_FILE="$7"
SESSION_NAME="$8"

cd "$ROOT_DIR"
if [ -f ".venv/bin/activate" ]; then
  source .venv/bin/activate
fi
export MPLBACKEND=Agg

COMPARISON_RUN=""
BUNDLE_DIR="$ROLLOUT_DIR/bundle"
ROLLOUT_STATUS="running"
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
FINISHED_AT=""

write_meta() {
  cat > "$META_FILE" <<EOF
SESSION_NAME=$SESSION_NAME
LOG_FILE=$LOG_FILE
ROLLOUT_DIR=$ROLLOUT_DIR
OFFICIAL_RUN=$OFFICIAL_RUN
COMPARISON_RUN=$COMPARISON_RUN
BUNDLE_DIR=$BUNDLE_DIR
ROLLOUT_STATUS=$ROLLOUT_STATUS
STARTED_AT=$STARTED_AT
FINISHED_AT=$FINISHED_AT
EOF
}

write_meta
PIPE_STATUS=0

{
  echo "========================================"
  echo "Paper analysis deck rerender"
  echo "Started: $STARTED_AT"
  echo "Rollout dir: $ROLLOUT_DIR"
  echo "Official run: $OFFICIAL_RUN"
  echo "========================================"
  echo

  python -m pytest -q tests/test_paper_rollout.py tests/test_render_style.py
  python -m cc_mapf.cli batch --config "$COMPARISON_CONFIG"
  COMPARISON_RUN="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_paper_comparison_4_6_8_10 2>/dev/null | head -1 || true)"
  if [ -z "$COMPARISON_RUN" ] || [ ! -f "$COMPARISON_RUN/results.json" ]; then
    echo "Comparison run did not produce results.json"
    ROLLOUT_STATUS="failed"
    exit 1
  fi
  write_meta

  python - "$ROLLOUT_DIR" "$OFFICIAL_RUN" "$COMPARISON_RUN" "$RENDER_CONFIG" <<'PY'
import json
import shutil
import sys
from pathlib import Path

from cc_mapf.model import RenderConfig
from cc_mapf.paper_rollout import render_curated_bundle
from cc_mapf.utils import load_yaml

rollout_dir = Path(sys.argv[1])
official_run = Path(sys.argv[2])
comparison_run = Path(sys.argv[3])
render_config = RenderConfig.from_dict(load_yaml(sys.argv[4]))
bundle_dir = rollout_dir / "bundle"

summary_path = rollout_dir / "paper_rollout_summary.json"
status_path = rollout_dir / "paper_rollout_status.json"
summary = json.loads(summary_path.read_text(encoding="utf-8"))
status = json.loads(status_path.read_text(encoding="utf-8"))

for path in [bundle_dir / "png", bundle_dir / "gif"]:
    if path.exists():
        shutil.rmtree(path)
for path in [bundle_dir / "paper_bundle_manifest.json", bundle_dir / "paper_bundle_validation.json"]:
    if path.exists():
        path.unlink()

bundle_output_dir, _, bundle_validation = render_curated_bundle(
    official_run,
    comparison_run,
    output_dir=bundle_dir,
    config=render_config,
    selected_planner=summary["selected_planner"],
    official_gate_status=summary["official_gate_status"],
)

summary["bundle_dir"] = str(bundle_output_dir)
summary["bundle_validation"] = bundle_validation
summary["manifest_path"] = str(bundle_output_dir / "paper_bundle_manifest.json")
summary["comparison_run_dir"] = None
summary["comparison_run_note"] = "Comparison subset was regenerated for analysis deck rerender and then cleaned up."

status["bundle_dir"] = str(bundle_output_dir)
status["bundle_validation"] = bundle_validation
status["manifest_path"] = str(bundle_output_dir / "paper_bundle_manifest.json")
status["comparison_run_dir"] = None
status["comparison_run_note"] = "Comparison subset was regenerated for analysis deck rerender and then cleaned up."

manifest_path = bundle_output_dir / "paper_bundle_manifest.json"
manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
manifest_payload["metadata"]["comparison_run"] = None
manifest_payload["metadata"]["comparison_run_note"] = "Comparison subset was regenerated for analysis deck rerender and then cleaned up."

summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

print(bundle_validation)
print(bundle_output_dir)
PY

  rm -rf "$COMPARISON_RUN"
  COMPARISON_RUN=""
  ROLLOUT_STATUS="completed"
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  write_meta
  echo
  echo "========================================"
  echo "Analysis deck rerender complete"
  echo "Bundle: $BUNDLE_DIR"
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

chmod +x /tmp/run_paper_rerender_analysis_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "ROLLOUT_DIR=$ROLLOUT_DIR"
  echo "OFFICIAL_RUN=$OFFICIAL_RUN"
  echo "BUNDLE_DIR=$ROLLOUT_DIR/bundle"
  echo "ROLLOUT_STATUS=starting"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_paper_rerender_analysis_inner.sh '$ROOT_DIR' '$ROLLOUT_DIR' '$OFFICIAL_RUN' '$COMPARISON_CONFIG' '$RENDER_CONFIG' '$LOG_FILE' '$META_FILE' '$SESSION_NAME'"

echo "Started detached analysis deck rerender session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
