#!/bin/bash
# Copy all GIF files to docs/assets for GitHub README display

set -e

RUN_DIR="artifacts/runs/20260409-074900"
SOURCE_DIR="$RUN_DIR"
DEST_DIR="docs/assets"

echo "========================================"
echo "Copying GIFs to docs/assets/"
echo "========================================"
echo ""

# Ensure docs/assets exists
mkdir -p "$DEST_DIR"

# Copy existing GIFs from showcase directory
if [ -d "$SOURCE_DIR/showcase" ]; then
    echo "Copying from showcase/..."
    cp -v "$SOURCE_DIR/showcase"/*.gif "$DEST_DIR/" 2>/dev/null || echo "  (no GIFs in showcase yet)"
fi

# Copy from gif_outputs if exists
if [ -d "$SOURCE_DIR/gif_outputs" ]; then
    echo "Copying from gif_outputs/..."
    cp -v "$SOURCE_DIR/gif_outputs"/*.gif "$DEST_DIR/" 2>/dev/null || echo "  (no GIFs in gif_outputs yet)"
fi

# Copy from fun_gifs if exists
if [ -d "$SOURCE_DIR/fun_gifs" ]; then
    echo "Copying from fun_gifs/..."
    cp -v "$SOURCE_DIR/fun_gifs"/*.gif "$DEST_DIR/" 2>/dev/null || echo "  (no GIFs in fun_gifs yet)"
fi

echo ""
echo "========================================"
echo "GIFs in docs/assets/:"
echo "========================================"
ls -lh "$DEST_DIR"/*.gif 2>/dev/null || echo "  (no GIFs yet - run render scripts first)"
echo ""

echo "Total files in docs/assets/:"
ls -1 "$DEST_DIR"/*.* 2>/dev/null | wc -l | xargs echo "  " files
echo ""
echo "Done! Commit these for GitHub display."
