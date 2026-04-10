#!/bin/bash
# Run ALL GIF generation in detached tmux session

set -e

RUN_DIR="artifacts/runs/20260409-074900"
ASSETS_DIR="docs/assets"

echo "========================================"
echo "FULL GIF GENERATION - Detached Mode"
echo "========================================"
echo ""

# Kill existing session if present
tmux kill-session -t mapf-all-gifs 2>/dev/null || true
sleep 1

# Create fresh session
tmux new-session -d -s mapf-all-gifs
tmux send-keys -t mapf-all-gifs "source .venv/bin/activate" C-m
tmux send-keys -t mapf-all-gifs "export MPLBACKEND=Agg" C-m
tmux send-keys -t mapf-all-gifs "cd $(pwd)" C-m

tmux send-keys -t mapf-all-gifs "echo 'Starting full GIF generation...'" C-m
tmux send-keys -t mapf-all-gifs "echo ''" C-m

# Showcase GIFs
tmux send-keys -t mapf-all-gifs "echo '=== Step 1: Showcase GIFs ==='" C-m
tmux send-keys -t mapf-all-gifs "python render_enhanced_showcase.py $RUN_DIR showcase_gifs" C-m

# Fun GIFs  
tmux send-keys -t mapf-all-gifs "echo ''" C-m
tmux send-keys -t mapf-all-gifs "echo '=== Step 2: Fun Variety GIFs ==='" C-m
tmux send-keys -t mapf-all-gifs "python render_variety_gifs.py $RUN_DIR fun_gifs" C-m

# Copy to assets
tmux send-keys -t mapf-all-gifs "echo ''" C-m
tmux send-keys -t mapf-all-gifs "echo '=== Step 3: Copying to docs/assets ==='" C-m
tmux send-keys -t mapf-all-gifs "mkdir -p $ASSETS_DIR" C-m
tmux send-keys -t mapf-all-gifs "cp $RUN_DIR/showcase_gifs/*.gif $ASSETS_DIR/ 2>/dev/null || true" C-m
tmux send-keys -t mapf-all-gifs "cp $RUN_DIR/fun_gifs/*.gif $ASSETS_DIR/ 2>/dev/null || true" C-m
tmux send-keys -t mapf-all-gifs "cp $RUN_DIR/showcase/*.gif $ASSETS_DIR/ 2>/dev/null || true" C-m

# Summary
tmux send-keys -t mapf-all-gifs "echo ''" C-m
tmux send-keys -t mapf-all-gifs "echo '========================================'" C-m
tmux send-keys -t mapf-all-gifs "echo 'ALL GIFS COMPLETE! 🎉'" C-m
tmux send-keys -t mapf-all-gifs "echo '========================================'" C-m
tmux send-keys -t mapf-all-gifs "echo 'Location: $ASSETS_DIR'" C-m
tmux send-keys -t mapf-all-gifs "ls -lh $ASSETS_DIR/*.gif" C-m
tmux send-keys -t mapf-all-gifs "echo ''" C-m
tmux send-keys -t mapf-all-gifs "echo 'Ready to commit! Run: git add docs/assets/*.gif'" C-m
tmux send-keys -t mapf-all-gifs "echo ''" C-m
tmux send-keys -t mapf-all-gifs "echo 'Total files:'" C-m
tmux send-keys -t mapf-all-gifs "ls -1 $ASSETS_DIR/*.* | wc -l" C-m

echo "Detached session 'mapf-all-gifs' created!"
echo ""
echo "Monitor: tmux attach -t mapf-all-gifs"
echo ""
echo "This will generate:"
echo "  • 5 showcase GIFs (corridor, warehouse, etc.)"
echo "  • 7 fun GIFs (fast, slow, cyberpunk, ocean, etc.)"
echo ""
echo "ETA: ~15-20 minutes"
