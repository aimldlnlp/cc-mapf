#!/bin/bash
# Advanced Visualizations Only - DETACHED
# Generate heatmaps and failure analysis for existing run
# This will survive VPN/VSCode disconnections!

set -e

cd /home/aimldl/mapf

# Default run directory (latest)
RUN_DIR="${1:-$(ls -1dt artifacts/runs/*_overnight_* 2>/dev/null | head -1)}"
OUTPUT_NAME="${2:-visualisasi_advanced}"

if [ -z "$RUN_DIR" ]; then
    echo "Error: No run directory found"
    echo "Usage: ./run_visualizations_only_detached.sh [run_directory] [output_name]"
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
    cd /home/aimldl/mapf
    
    echo '╔══════════════════════════════════════════════════════════════╗'
    echo '║     ADVANCED VISUALIZATIONS ONLY                             ║'
    echo '╠══════════════════════════════════════════════════════════════╣'
    echo '║ Started: '\$(date)'                              ║'
    echo '║ Run: $RUN_DIR'
    echo '║ Output: $OUTPUT_NAME'
    echo '╠══════════════════════════════════════════════════════════════╣'
    echo '║ Generating:                                                  ║'
    echo '║   • Traffic heatmap per family (4 families)                  ║'
    echo '║   • Failure analysis dashboard                               ║'
    echo '║   • Agent stuck position heatmap                             ║'
    echo '╚══════════════════════════════════════════════════════════════╝'
    echo ''
    
    .venv/bin/python render_advanced_visualizations.py '$RUN_DIR' '$OUTPUT_NAME'
    
    echo ''
    echo '╔══════════════════════════════════════════════════════════════╗'
    echo '║ COMPLETE                                                     ║'
    echo '╠══════════════════════════════════════════════════════════════╣'
    echo '║ Output: $RUN_DIR/$OUTPUT_NAME/' | tee -a $LOGFILE
    echo '╚══════════════════════════════════════════════════════════════╝'
    
    exec bash
"

echo ""
echo "✅ VISUALIZATIONS started in detached tmux session 'mapf-viz'"
echo ""
echo "📁 Target: $RUN_DIR"
echo "📂 Output: $OUTPUT_NAME"
echo ""
echo "📊 Output:"
echo "   • heatmap_traffic_open.png"
echo "   • heatmap_traffic_corridor.png"
echo "   • heatmap_traffic_warehouse.png"
echo "   • heatmap_traffic_formation_shift.png"
echo "   • failure_analysis_dashboard.png"
echo "   • heatmap_failure_positions.png"
echo ""
echo "🔧 Commands:"
echo "   tmux attach -t mapf-viz          # View progress"
echo "   tmux detach                      # Detach (Ctrl+B then D)"
echo ""
echo "⏱️  Estimasi: 5-10 menit"
