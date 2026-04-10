#!/bin/bash
# Run fun GIF generation in detached tmux session
# Generates variety of GIFs with different styles and speeds

set -e

# Set up virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Set MPL backend
export MPLBACKEND=Agg

# Use overnight_premium run
RUN_DIR="artifacts/runs/20260409-074900_overnight_premium"

echo "========================================"
echo "FUN GIF GENERATION - Detached Mode"
echo "========================================"
echo "Run: $RUN_DIR"
echo "Output: fun_gifs/"
echo ""

# Create tmux session for fun GIF generation
tmux new-session -d -s mapf-fun

tmux send-keys -t mapf-fun "source .venv/bin/activate" C-m
tmux send-keys -t mapf-fun "export MPLBACKEND=Agg" C-m
tmux send-keys -t mapf-fun "cd $(pwd)" C-m

tmux send-keys -t mapf-fun "echo 'Starting fun GIF generation...'" C-m
tmux send-keys -t mapf-fun "python render_variety_gifs.py $RUN_DIR fun_gifs" C-m

tmux send-keys -t mapf-fun "echo ''" C-m
tmux send-keys -t mapf-fun "echo '========================================'" C-m
tmux send-keys -t mapf-fun "echo 'FUN GIFS COMPLETE!'" C-m
tmux send-keys -t mapf-fun "echo '========================================'" C-m
tmux send-keys -t mapf-fun "echo 'All fun GIFs have been generated!'" C-m
tmux send-keys -t mapf-fun "echo 'Location: $RUN_DIR/fun_gifs/'" C-m
tmux send-keys -t mapf-fun "ls -lh $RUN_DIR/fun_gifs/" C-m

echo "Detached session 'mapf-fun' created!"
echo ""
echo "Monitor progress:"
echo "  tmux attach -t mapf-fun"
echo "  tail -f $RUN_DIR/fun_gifs/*.log 2>/dev/null || echo 'No log file'"
echo ""
echo "GIFs being generated:"
echo "  1. Fast Formation (16 FPS) ⚡"
echo "  2. Slow Corridor (4 FPS) 🐌"
echo "  3. Cyber Warehouse 💜"
echo "  4. Ocean Open Space 🌊"
echo "  5. Side-by-side Battle 🥊"
echo "  6. Sunset Formation 🌅"
echo "  7. High Contrast ⚡"
echo ""
echo "Session will auto-close when done."
