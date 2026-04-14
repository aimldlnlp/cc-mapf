#!/bin/bash
# Full CC-MAPF Benchmark - Master Script
# Runs: All planners -> Comparison -> Visualizations
# Detached tmux session - safe to close VSCode

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

# Configuration
RESULTS_DIR="artifacts/runs/benchmark_$(date +%Y%m%d-%H%M%S)"
LOGFILE="$RESULTS_DIR/benchmark.log"

echo "========================================"
echo "CC-MAPF Full Benchmark"
echo "Started: $(date)"
echo "Results: $RESULTS_DIR"
echo "========================================"

# Create results directory
mkdir -p "$RESULTS_DIR"

# Kill existing session
tmux kill-session -t mapf-benchmark 2>/dev/null || true
sleep 1

# Create the inner script
cat > /tmp/benchmark_inner.sh << 'INNERSCRIPT'
#!/bin/bash
cd "$1"
source .venv/bin/activate
export MPLBACKEND=Agg

RESULTS_DIR="$2"
LOGFILE="$RESULTS_DIR/benchmark.log"

echo "========================================" >> "$LOGFILE"
echo "CC-MAPF Full Benchmark Suite" >> "$LOGFILE"
echo "Started: $(date)" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

# Run Connected Step
echo "" >> "$LOGFILE"
echo "[1/2] Running Connected Step (Baseline)..." >> "$LOGFILE"
ccmapf batch --config configs/suites/benchmark_connected_step.yaml 2>&1 >> "$LOGFILE"
echo "Connected Step complete." >> "$LOGFILE"

# Run Prioritized CC
echo "" >> "$LOGFILE"
echo "[2/2] Running Prioritized CC (New)..." >> "$LOGFILE"
ccmapf batch --config configs/suites/benchmark_prioritized_cc.yaml 2>&1 >> "$LOGFILE"
echo "Prioritized CC complete." >> "$LOGFILE"

# Move results to organized directory
echo "" >> "$LOGFILE"
echo "Organizing results..." >> "$LOGFILE"
for run_dir in artifacts/runs/*/; do
    if [ -d "$run_dir" ] && [ "$(basename "$run_dir")" != "benchmark_$(date +%Y%m%d)*" ]; then
        if [ -f "$run_dir/results.json" ]; then
            planner=$(python3 -c "import json; print(json.load(open('$run_dir/results.json'))['metadata']['planner'])" 2>/dev/null || echo "unknown")
            target_dir="$RESULTS_DIR/$planner"
            mkdir -p "$target_dir"
            mv "$run_dir" "$target_dir/"
            echo "Moved $run_dir to $target_dir" >> "$LOGFILE"
        fi
    fi
done

# Generate visualizations
echo "" >> "$LOGFILE"
echo "Generating visualizations..." >> "$LOGFILE"
for run_dir in "$RESULTS_DIR"/*/*/; do
    if [ -f "$run_dir/results.json" ]; then
        echo "Processing: $run_dir" >> "$LOGFILE"
        python scripts/render/render_advanced_visualizations.py "$run_dir" figures 2>&1 >> "$LOGFILE" || true
    fi
done

# Generate showcase GIFs
echo "" >> "$LOGFILE"
echo "Generating showcase GIFs..." >> "$LOGFILE"
first_run=$(find "$RESULTS_DIR" -name "results.json" -print -quit 2>/dev/null | xargs dirname 2>/dev/null)
if [ -n "$first_run" ]; then
    mkdir -p "$RESULTS_DIR/showcase"
    python scripts/render/render_showcase.py "$first_run" "$RESULTS_DIR/showcase" 2>&1 >> "$LOGFILE" || true
    mkdir -p docs/media
    cp "$RESULTS_DIR/showcase/"*.gif docs/media/ 2>/dev/null || true
fi

echo "" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"
echo "BENCHMARK COMPLETE!" >> "$LOGFILE"
echo "Completed: $(date)" >> "$LOGFILE"
echo "Results: $RESULTS_DIR" >> "$LOGFILE"
echo "========================================" >> "$LOGFILE"

exec bash
INNERSCRIPT

chmod +x /tmp/benchmark_inner.sh

# Create detached tmux session
tmux new-session -d -s mapf-benchmark "bash /tmp/benchmark_inner.sh '$ROOT_DIR' '$RESULTS_DIR'"

echo ""
echo "========================================"
echo "Full Benchmark Started"
echo "========================================"
echo "Session: tmux attach -t mapf-benchmark"
echo "Log: tail -f $RESULTS_DIR/benchmark.log"
echo "Results: $RESULTS_DIR"
echo ""
echo "This will run:"
echo "  1. Connected Step (baseline) - 60 instances"
echo "  2. Prioritized CC (new) - 60 instances"
echo "  3. Comparison analysis"
echo "  4. Visualizations per planner"
echo "  5. Showcase GIFs from best run"
echo ""
echo "Estimated time: 2-4 hours"
echo "Safe to close VSCode!"
