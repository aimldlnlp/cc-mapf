#!/bin/bash
# Master script to generate ALL GIFs and copy to docs/assets

set -e

RUN_DIR="artifacts/runs/20260409-074900"
ASSETS_DIR="docs/assets"

echo "========================================"
echo "CC-MAPF GIF GENERATION STATION 🎬"
echo "========================================"
echo ""

# Setup
source .venv/bin/activate
export MPLBACKEND=Agg

# Step 1: Generate showcase GIFs (original 5)
echo "Step 1: Generating showcase GIFs..."
echo "------------------------------------"
python render_enhanced_showcase.py "$RUN_DIR" showcase_gifs

# Step 2: Generate fun variety GIFs
echo ""
echo "Step 2: Generating fun GIFs..."
echo "------------------------------------"
python render_variety_gifs.py "$RUN_DIR" fun_gifs

# Step 3: Copy everything to docs/assets
echo ""
echo "Step 3: Copying to docs/assets..."
echo "------------------------------------"
mkdir -p "$ASSETS_DIR"

# Copy showcase GIFs
if [ -d "$RUN_DIR/showcase_gifs" ]; then
    cp -v "$RUN_DIR/showcase_gifs"/*.gif "$ASSETS_DIR/" 2>/dev/null || true
fi

# Copy fun GIFs
if [ -d "$RUN_DIR/fun_gifs" ]; then
    cp -v "$RUN_DIR/fun_gifs"/*.gif "$ASSETS_DIR/" 2>/dev/null || true
fi

# Copy existing showcase GIFs if any
if [ -d "$RUN_DIR/showcase" ]; then
    cp -v "$RUN_DIR/showcase"/*.gif "$ASSETS_DIR/" 2>/dev/null || true
fi

echo ""
echo "========================================"
echo "DONE! 🎉"
echo "========================================"
echo ""
echo "GIFs in $ASSETS_DIR:"
ls -lh "$ASSETS_DIR"/*.gif 2>/dev/null || echo "  (check output directories)"
echo ""
echo "Total assets:"
ls -1 "$ASSETS_DIR"/*.* 2>/dev/null | wc -l | xargs echo "  " files
echo ""
echo "Next step: git add docs/assets/*.gif"
