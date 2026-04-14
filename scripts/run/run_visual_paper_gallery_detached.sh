#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SESSION_NAME="cc-paper-gallery"
CONFIG_PATH="configs/suites/visual_paper_gallery.yaml"
RENDER_CONFIG="configs/render/paper_gallery.yaml"
STAMP="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$ROOT_DIR/artifacts/logs"
LOG_FILE="$LOG_DIR/visual_paper_gallery_${STAMP}.log"
META_FILE="$LOG_DIR/visual_paper_gallery_latest.env"

mkdir -p "$LOG_DIR"
cd "$ROOT_DIR"
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

cat > /tmp/run_visual_paper_gallery_inner.sh <<'INNER'
#!/bin/bash
set -euo pipefail

ROOT_DIR="$1"
CONFIG_PATH="$2"
RENDER_CONFIG="$3"
LOG_FILE="$4"
META_FILE="$5"

cd "$ROOT_DIR"
source .venv/bin/activate
export MPLBACKEND=Agg

SESSION_NAME="cc-paper-gallery"
RUN_DIR=""
ANALYSIS_DIR=""
SHOWCASE_DIR=""
GALLERY_DIR=""
TOTAL_PNG=0
TOTAL_GIF=0
SOLVED_RECORDS=0
TOTAL_RECORDS=0
ROLLOUT_STATUS="running"
STARTED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
FINISHED_AT=""

write_meta() {
  cat > "$META_FILE" <<EOF
SESSION_NAME=$SESSION_NAME
LOG_FILE=$LOG_FILE
RUN_DIR=$RUN_DIR
ANALYSIS_DIR=$ANALYSIS_DIR
SHOWCASE_DIR=$SHOWCASE_DIR
GALLERY_DIR=$GALLERY_DIR
TOTAL_PNG=$TOTAL_PNG
TOTAL_GIF=$TOTAL_GIF
SOLVED_RECORDS=$SOLVED_RECORDS
TOTAL_RECORDS=$TOTAL_RECORDS
ROLLOUT_STATUS=$ROLLOUT_STATUS
STARTED_AT=$STARTED_AT
FINISHED_AT=$FINISHED_AT
EOF
}

write_meta

PIPE_STATUS=0
{
  echo "========================================"
  echo "Paper-style visual harvest"
  echo "Started: $STARTED_AT"
  echo "Root: $ROOT_DIR"
  echo "Suite: $CONFIG_PATH"
  echo "Render config: $RENDER_CONFIG"
  echo "========================================"
  echo

  echo "[1/5] Running regression tests"
  pytest -q tests/test_cli_integration.py tests/test_environment_validation.py tests/test_render_style.py tests/test_render_selection.py
  echo

  echo "[2/5] Running visual harvest suite"
  if ! python -m cc_mapf.cli batch --config "$CONFIG_PATH"; then
    echo "Visual harvest suite failed"
    ROLLOUT_STATUS="batch_failed"
    exit 1
  fi
  RUN_DIR="$(ls -1dt "$ROOT_DIR"/artifacts/runs/*_visual_paper_gallery 2>/dev/null | head -1 || true)"
  if [ -z "$RUN_DIR" ] || [ ! -f "$RUN_DIR/results.json" ]; then
    echo "Visual suite did not produce a run directory"
    ROLLOUT_STATUS="run_missing"
    exit 1
  fi

  echo "[3/5] Rendering analysis"
  ANALYSIS_DIR="$RUN_DIR/analysis"
  if ! .venv/bin/python scripts/render/render_advanced_visualizations.py "$RUN_DIR" analysis; then
    echo "Analysis rendering failed"
    ROLLOUT_STATUS="analysis_failed"
    exit 1
  fi

  echo "[4/5] Rendering showcase"
  SHOWCASE_DIR="$RUN_DIR/showcase"
  if ! .venv/bin/python scripts/render/render_showcase.py "$RUN_DIR" "$SHOWCASE_DIR"; then
    echo "Showcase rendering failed"
    ROLLOUT_STATUS="showcase_failed"
    exit 1
  fi

  echo "[5/5] Rendering paper gallery"
  GALLERY_DIR="$RUN_DIR/gallery"
  if ! .venv/bin/python scripts/render/render_paper_gallery.py "$RUN_DIR" "$GALLERY_DIR" "$RENDER_CONFIG"; then
    echo "Paper gallery rendering failed"
    ROLLOUT_STATUS="gallery_failed"
    exit 1
  fi

  eval "$(
    python - "$RUN_DIR" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
records = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))["records"]
solved = sum(1 for record in records if record["solved"])
analysis_dir = run_dir / "analysis"
showcase_dir = run_dir / "showcase"
gallery_dir = run_dir / "gallery"
png_count = len(list(run_dir.rglob("*.png")))
gif_count = len(list(run_dir.rglob("*.gif")))
def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "item"

contact_sheet_keys = {(record["family"], record["scale"]) for record in records}
contact_sheet_ok = all(
    (gallery_dir / "contact_sheets" / f"{slugify(family)}__{slugify(scale)}.png").exists()
    for family, scale in contact_sheet_keys
)
required = [
    analysis_dir / "planner-success-matrix.png",
    analysis_dir / "failure-reason-breakdown.png",
    analysis_dir / "windowed-cc-reference-portfolio.png",
    analysis_dir / "windowed-cc-progress-timeline.png",
    gallery_dir / "analysis" / "runtime-success-scatter.png",
    gallery_dir / "analysis" / "makespan-boxplot.png",
    gallery_dir / "analysis" / "connectivity-rejection-heatmap.png",
    gallery_dir / "analysis" / "solved-count-heatmap.png",
    gallery_dir / "paper_gallery_manifest.json",
]
required_ok = all(path.exists() for path in required)
min_png_ok = png_count >= 3 * len(records)
print(f"TOTAL_PNG={png_count}")
print(f"TOTAL_GIF={gif_count}")
print(f"SOLVED_RECORDS={solved}")
print(f"TOTAL_RECORDS={len(records)}")
print(f"REQUIRED_OK={1 if required_ok else 0}")
print(f"MIN_PNG_OK={1 if min_png_ok else 0}")
print(f"CONTACT_SHEET_OK={1 if contact_sheet_ok else 0}")
print(f"SHOWCASE_DIR={showcase_dir}")
print(f"ANALYSIS_DIR={analysis_dir}")
print(f"GALLERY_DIR={gallery_dir}")
PY
  )"
  write_meta

  if [ "${REQUIRED_OK:-0}" -ne 1 ] || [ "${MIN_PNG_OK:-0}" -ne 1 ] || [ "${CONTACT_SHEET_OK:-0}" -ne 1 ]; then
    echo "Output validation failed"
    ROLLOUT_STATUS="validation_failed"
    exit 1
  fi

  ROLLOUT_STATUS="completed"
  FINISHED_AT="$(date '+%Y-%m-%d %H:%M:%S')"
  write_meta
  echo "========================================"
  echo "Paper visual harvest complete"
  echo "Run: $RUN_DIR"
  echo "Analysis: $ANALYSIS_DIR"
  echo "Showcase: $SHOWCASE_DIR"
  echo "Gallery: $GALLERY_DIR"
  echo "PNGs: $TOTAL_PNG"
  echo "GIFs: $TOTAL_GIF"
  echo "Solved records: $SOLVED_RECORDS / $TOTAL_RECORDS"
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

chmod +x /tmp/run_visual_paper_gallery_inner.sh

{
  echo "SESSION_NAME=$SESSION_NAME"
  echo "LOG_FILE=$LOG_FILE"
  echo "ROLLOUT_STATUS=starting"
  echo "STARTED_AT=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$META_FILE"

tmux new-session -d -s "$SESSION_NAME" "bash /tmp/run_visual_paper_gallery_inner.sh '$ROOT_DIR' '$CONFIG_PATH' '$RENDER_CONFIG' '$LOG_FILE' '$META_FILE'"

echo "Started detached paper gallery session."
echo "Session: $SESSION_NAME"
echo "Log: $LOG_FILE"
echo "Meta: $META_FILE"
echo "Attach: tmux attach -t $SESSION_NAME"
echo "Tail log: tail -f $LOG_FILE"
