#!/bin/bash
# Generate visualizations for existing run (detached mode)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

# Default run directory (latest)
RUN_DIR="${1:-$(ls -1dt artifacts/runs/* 2>/dev/null | head -1)}"
OUTPUT_NAME="${2:-visualizations}"

if [ -z "$RUN_DIR" ]; then
    echo "Error: No run directory found"
    echo "Usage: bash scripts/run/run_visualizations.sh [run_directory] [output_name]"
    exit 1
fi

if [ ! -d "$RUN_DIR" ]; then
    echo "Error: Directory not found: $RUN_DIR"
    exit 1
fi

echo "Target: $RUN_DIR"
echo "Output: $OUTPUT_NAME"

# Kill any existing session
tmux kill-session -t mapf-viz 2>/dev/null || true

# Create new detached tmux session
tmux new-session -d -s mapf-viz "
    cd '$ROOT_DIR'
    
    echo '========================================'
    echo 'Generating Visualizations'
    echo 'Started: \$(date)'
    echo 'Run: $RUN_DIR'
    echo 'Output: $OUTPUT_NAME'
    echo '========================================'
    echo ''
    
    .venv/bin/python scripts/render/render_advanced_visualizations.py '$RUN_DIR' '$OUTPUT_NAME'
    
    echo ''
    echo '========================================'
    echo 'Complete'
    echo 'Output: $RUN_DIR/$OUTPUT_NAME/'
    echo '========================================'
    
    exec bash
"

echo ""
echo "Visualizations started in detached tmux session 'mapf-viz'"
echo ""
echo "Run: $RUN_DIR"
echo "Output: $OUTPUT_NAME"
echo ""
echo "Commands:"
echo "  tmux attach -t mapf-viz  # View progress"
