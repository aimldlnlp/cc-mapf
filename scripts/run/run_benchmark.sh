#!/bin/bash
# Run CC-MAPF benchmark suite with visualizations (detached mode)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$ROOT_DIR"

# Kill any existing session
tmux kill-session -t mapf-benchmark 2>/dev/null || true

# Create new detached tmux session
tmux new-session -d -s mapf-benchmark '
    cd '"$ROOT_DIR"'
    
    LOGFILE="benchmark.log"
    
    echo "========================================" | tee $LOGFILE
    echo "CC-MAPF Benchmark Suite" | tee -a $LOGFILE
    echo "Started: $(date)" | tee -a $LOGFILE
    echo "========================================" | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # Phase 1: Run benchmark
    echo "Phase 1: Running benchmark..." | tee -a $LOGFILE
    .venv/bin/python -m cc_mapf.cli batch --config configs/suites/benchmark_premium.yaml 2>&1 | tee -a $LOGFILE
    
    RUN_DIR=$(ls -1dt artifacts/runs/* | head -1)
    
    echo "" | tee -a $LOGFILE
    echo "Phase 1 complete." | tee -a $LOGFILE
    echo "Results: $RUN_DIR" | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # Phase 2: Generate visualizations
    echo "Phase 2: Generating visualizations..." | tee -a $LOGFILE
    .venv/bin/python scripts/render/render_advanced_visualizations.py "$RUN_DIR" visualizations 2>&1 | tee -a $LOGFILE
    
    echo "" | tee -a $LOGFILE
    echo "Phase 2 complete." | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # Summary
    echo "========================================" | tee -a $LOGFILE
    echo "Benchmark complete: $(date)" | tee -a $LOGFILE
    echo "Run directory: $RUN_DIR" | tee -a $LOGFILE
    echo "========================================" | tee -a $LOGFILE
    
    exec bash
'

echo ""
echo "Benchmark started in detached tmux session 'mapf-benchmark'"
echo ""
echo "Commands:"
echo "  tmux attach -t mapf-benchmark  # View progress"
echo "  tail -f benchmark.log          # View log"
echo ""
echo "Estimated time: 1-2 hours"
