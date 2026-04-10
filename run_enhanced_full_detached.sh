#!/bin/bash
# Enhanced MAPF Run + Advanced Visualizations - DETACHED
# 1. Run with enhanced planner (adaptive + portfolio)
# 2. Generate advanced visualizations (heatmaps + failure analysis)
# This will survive VPN/VSCode disconnections!

set -e

cd /home/aimldl/mapf

# Kill any existing session
tmux kill-session -t mapf-enhanced 2>/dev/null || true

# Create new detached tmux session
tmux new-session -d -s mapf-enhanced '
    cd /home/aimldl/mapf
    
    LOGFILE="overnight_enhanced_full.log"
    
    echo "╔══════════════════════════════════════════════════════════════╗" | tee $LOGFILE
    echo "║     ENHANCED MAPF + ADVANCED VISUALIZATIONS                  ║" | tee -a $LOGFILE
    echo "╠══════════════════════════════════════════════════════════════╣" | tee -a $LOGFILE
    echo "║ Started: "$(date)"                              ║" | tee -a $LOGFILE
    echo "╠══════════════════════════════════════════════════════════════╣" | tee -a $LOGFILE
    echo "║ PHASE 1: Enhanced Solver                                     ║" | tee -a $LOGFILE
    echo "║   • Adaptive beam width                                      ║" | tee -a $LOGFILE
    echo "║   • Portfolio strategy (3 attempts)                          ║" | tee -a $LOGFILE
    echo "║   • Warehouse optimization                                   ║" | tee -a $LOGFILE
    echo "║   • Target: 56-57/60 (93-95%) vs 52/60 (86.7%)              ║" | tee -a $LOGFILE
    echo "╠══════════════════════════════════════════════════════════════╣" | tee -a $LOGFILE
    echo "║ PHASE 2: Advanced Visualizations                             ║" | tee -a $LOGFILE
    echo "║   • Traffic heatmap per family                               ║" | tee -a $LOGFILE
    echo "║   • Failure analysis dashboard                               ║" | tee -a $LOGFILE
    echo "║   • Stuck position heatmap                                   ║" | tee -a $LOGFILE
    echo "╚══════════════════════════════════════════════════════════════╝" | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # PHASE 1: Run enhanced solver
    echo "🚀 PHASE 1: Running Enhanced Solver..." | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    .venv/bin/python -m cc_mapf.cli batch --config configs/suites/overnight_enhanced.yaml 2>&1 | tee -a $LOGFILE
    
    RUN_DIR=$(ls -1dt artifacts/runs/*_overnight_enhanced | head -1)
    
    echo "" | tee -a $LOGFILE
    echo "✅ PHASE 1 Complete!" | tee -a $LOGFILE
    echo "   Results: $RUN_DIR" | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # PHASE 2: Advanced visualizations
    echo "🎨 PHASE 2: Generating Advanced Visualizations..." | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    .venv/bin/python render_advanced_visualizations.py "$RUN_DIR" visualisasi_advanced 2>&1 | tee -a $LOGFILE
    
    echo "" | tee -a $LOGFILE
    echo "✅ PHASE 2 Complete!" | tee -a $LOGFILE
    echo "   Visualizations: $RUN_DIR/visualisasi_advanced/" | tee -a $LOGFILE
    echo "" | tee -a $LOGFILE
    
    # Summary
    echo "╔══════════════════════════════════════════════════════════════╗" | tee -a $LOGFILE
    echo "║ ALL TASKS COMPLETE                                           ║" | tee -a $LOGFILE
    echo "╠══════════════════════════════════════════════════════════════╣" | tee -a $LOGFILE
    echo "║ Completed: "$(date)"                            ║" | tee -a $LOGFILE
    echo "║ Run: $RUN_DIR"
    echo "║ Results: summary.json" | tee -a $LOGFILE
    echo "║ Figures: showcase/" | tee -a $LOGFILE
    echo "║ Advanced: visualisasi_advanced/" | tee -a $LOGFILE
    echo "╚══════════════════════════════════════════════════════════════╝" | tee -a $LOGFILE
    
    exec bash
'

echo ""
echo "✅ ENHANCED FULL RUN started in detached tmux session 'mapf-enhanced'"
echo ""
echo "📋 Plan:"
echo "   Phase 1: Enhanced solver (adaptive beam + portfolio)"
echo "   Phase 2: Advanced visualizations (heatmaps + analysis)"
echo ""
echo "🔧 Commands:"
echo "   tmux attach -t mapf-enhanced     # View progress"
echo "   tmux detach                      # Detach (Ctrl+B then D)"
echo "   tail -f overnight_enhanced_full.log  # View log"
echo ""
echo "⏱️  Estimasi: 2-3 jam (bisa ditinggal!)"
echo "🌙 Close VSCode aman, session tetap jalan!"
