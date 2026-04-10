#!/bin/bash
# Full CC-MAPF Benchmark - Master Script
# Runs: All planners -> Comparison -> Visualizations
# Detached tmux session - safe to close VSCode

set -e

cd /home/aimldl/mapf

# Configuration
RESULTS_DIR="artifacts/runs/benchmark_$(date +%Y%m%d-%H%M%S)"
LOGFILE="full_benchmark.log"

echo "========================================"
echo "CC-MAPF Full Benchmark"
echo "Started: $(date)"
echo "Results: $RESULTS_DIR"
echo "========================================"

# Create results directory
mkdir -p "$RESULTS_DIR"

# Kill existing session
tmux kill-session -t mapf-full 2>/dev/null || true
sleep 1

# Create detached tmux session
tmux new-session -d -s mapf-full "
    cd /home/aimldl/mapf
    
    echo '========================================' | tee $LOGFILE
    echo 'CC-MAPF Full Benchmark Suite' | tee -a $LOGFILE
    echo 'Started: \$(date)' | tee -a $LOGFILE
    echo '========================================' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    # Activate environment
    source .venv/bin/activate
    export MPLBACKEND=Agg
    
    # ========================================
    # PHASE 1: Run all planners
    # ========================================
    echo 'PHASE 1: Running all planners...' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    PLANNERS=(
        'connected_step:Connected Step'
        'cc_cbs:CC-CBS (New)'
        'prioritized_cc:Prioritized CC (New)'
        'windowed_cc:Windowed CC (New)'
    )
    
    for planner_info in '\${PLANNERS[@]}'; do
        IFS=':' read -r planner_name planner_desc <<< '\$planner_info'
        
        echo \"Running: \$planner_desc (\$planner_name)\" | tee -a $LOGFILE
        
        planner_dir=\"$RESULTS_DIR/\$planner_name\"
        mkdir -p \"\$planner_dir\"
        
        # Run benchmark suite
        python -m cc_mapf.cli batch \\
            --config configs/suites/benchmark_premium.yaml \\
            --planner "\$planner_name" \\
            --output-dir "\$planner_dir" \\
            2>&1 | tee -a \"\$planner_dir/run.log\"
        
        # Find the run directory
        run_dir=\$(ls -1dt "\$planner_dir"/*/ 2>/dev/null | head -1 || echo '')
        if [ -n "\$run_dir" ]; then
            echo \"  Results: \$run_dir\" | tee -a $LOGFILE
        fi
        echo '' | tee -a $LOGFILE
    done
    
    echo 'PHASE 1 complete.' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    # ========================================
    # PHASE 2: Generate comparison analysis
    # ========================================
    echo 'PHASE 2: Generating comparison analysis...' | tee -a $LOGFILE
    
    python -c \"
import sys
sys.path.insert(0, 'src')
import json
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

results_dir = Path('$RESULTS_DIR')
analysis_dir = results_dir / 'analysis'
analysis_dir.mkdir(exist_ok=True)

# Collect all results
all_results = []

for planner_dir in results_dir.glob('*'):
    if not planner_dir.is_dir() or planner_dir.name == 'analysis':
        continue
    
    planner_name = planner_dir.name
    
    # Find results.json files
    for results_file in planner_dir.rglob('results.json'):
        with open(results_file) as f:
            data = json.load(f)
        
        for record in data.get('records', []):
            all_results.append({
                'planner': planner_name,
                'instance': record.get('instance', ''),
                'family': record.get('family', ''),
                'agents': len(record.get('instance_data', {}).get('agents', [])),
                'solved': record.get('solved', False),
                'makespan': record.get('makespan', None),
                'sum_costs': record.get('sum_costs', None),
                'runtime': record.get('runtime', None),
                'nodes_expanded': record.get('nodes_expanded', None),
            })

if all_results:
    df = pd.DataFrame(all_results)
    
    # Save raw data
    df.to_csv(analysis_dir / 'all_results.csv', index=False)
    
    # Summary statistics
    summary = df.groupby('planner').agg({
        'solved': ['count', 'sum', 'mean'],
        'makespan': 'mean',
        'sum_costs': 'mean',
        'runtime': 'mean',
        'nodes_expanded': 'mean',
    }).round(2)
    
    summary.to_csv(analysis_dir / 'summary.csv')
    print(f'Analysis saved to {analysis_dir}')
    print(summary)
else:
    print('No results found')
\" 2>&1 | tee -a $LOGFILE
    
    echo 'PHASE 2 complete.' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    # ========================================
    # PHASE 3: Generate visualizations
    # ========================================
    echo 'PHASE 3: Generating visualizations...' | tee -a $LOGFILE
    
    # Run visualizations untuk setiap planner
    for planner_dir in $RESULTS_DIR/*/; do
        if [ -d "\$planner_dir" ] && [ "\$(basename \$planner_dir)" != "analysis" ]; then
            run_dir=\$(ls -1dt "\$planner_dir"/*/ 2>/dev/null | head -1 || echo '')
            if [ -n "\$run_dir" ] && [ -f "\$run_dir/results.json" ]; then
                echo \"Visualizing: \$run_dir\" | tee -a $LOGFILE
                python render_advanced_visualizations.py "\$run_dir" figures 2>&1 | tee -a $LOGFILE || true
            fi
        fi
    done
    
    echo 'PHASE 3 complete.' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    # ========================================
    # PHASE 4: Generate showcase GIFs (best run)
    # ========================================
    echo 'PHASE 4: Generating showcase GIFs...' | tee -a $LOGFILE
    
    # Find best run (highest success rate)
    best_run=\$(python -c \"
import json
import sys
from pathlib import Path

results_dir = Path('$RESULTS_DIR')
best = None
best_rate = -1

for results_file in results_dir.rglob('results.json'):
    with open(results_file) as f:
        data = json.load(f)
    
    records = data.get('records', [])
    if not records:
        continue
    
    solved = sum(1 for r in records if r.get('solved'))
    rate = solved / len(records)
    
    if rate > best_rate:
        best_rate = rate
        best = results_file.parent

if best:
    print(best)
\" 2>/dev/null)
    
    if [ -n "\$best_run" ]; then
        echo \"Best run: \$best_run (generating showcase GIFs)\" | tee -a $LOGFILE
        python render_showcase.py "\$best_run" "$RESULTS_DIR/showcase" 2>&1 | tee -a $LOGFILE || true
        
        # Copy to docs/assets
        if [ -d "$RESULTS_DIR/showcase" ]; then
            cp "$RESULTS_DIR/showcase/"*.gif docs/assets/ 2>/dev/null || true
            echo 'GIFs copied to docs/assets/' | tee -a $LOGFILE
        fi
    fi
    
    echo 'PHASE 4 complete.' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    
    # ========================================
    # Summary
    # ========================================
    echo '========================================' | tee -a $LOGFILE
    echo 'BENCHMARK COMPLETE' | tee -a $LOGFILE
    echo 'Completed: '\$(date) | tee -a $LOGFILE
    echo '========================================' | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    echo 'Results:' | tee -a $LOGFILE
    echo "  Directory: $RESULTS_DIR" | tee -a $LOGFILE
    echo '  Structure:' | tee -a $LOGFILE
    ls -la "$RESULTS_DIR" | tee -a $LOGFILE
    echo '' | tee -a $LOGFILE
    echo 'Next steps:' | tee -a $LOGFILE
    echo '  1. Check analysis/summary.csv for comparison' | tee -a $LOGFILE
    echo '  2. Check */figures/ for visualizations' | tee -a $LOGFILE
    echo '  3. Check showcase/ for GIFs' | tee -a $LOGFILE
    
    exec bash
"

echo ""
echo "========================================"
echo "Full Benchmark Started"
echo "========================================"
echo "Session: tmux attach -t mapf-full"
echo "Log: tail -f full_benchmark.log"
echo "Results: $RESULTS_DIR"
echo ""
echo "This will run:"
echo "  1. All 4 planners (connected_step, cc_cbs, prioritized_cc, windowed_cc)"
echo "  2. Comparison analysis"
echo "  3. Visualizations per planner"
echo "  4. Showcase GIFs from best run"
echo ""
echo "Estimated time: 2-4 hours"
echo "Safe to close VSCode!"
