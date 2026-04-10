#!/usr/bin/env python3
"""
Advanced Visualizations for MAPF Analysis:
- Traffic density heatmap per family
- Failure analysis for all instances
- Multi-planner comparison
"""

import sys
sys.path.insert(0, 'src')

import matplotlib
matplotlib.use('Agg')

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from pathlib import Path
from collections import defaultdict

from cc_mapf.utils import load_json, ensure_dir
from cc_mapf.model import Instance


def render_traffic_heatmap_per_family(run_dir: Path, output_dir: Path):
    """Render traffic density heatmap untuk setiap family."""
    
    results = load_json(run_dir / 'results.json')
    records = results['records']
    
    # Group records by family
    families = defaultdict(list)
    for record in records:
        family = record.get('family', 'unknown')
        families[family].append(record)
    
    print("🗺️  Rendering traffic heatmaps per family...")
    
    for family, family_records in families.items():
        if not family_records:
            continue
        
        # Aggregate all paths untuk family ini
        grid_width = 32  # Default, akan diupdate
        grid_height = 32
        traffic_grid = None
        
        for record in family_records:
            if not record.get('has_plan'):
                continue
            
            # Load instance untuk dapetin grid size
            instance_data = record.get('instance_data', {})
            grid = instance_data.get('grid', {})
            width = grid.get('width', 32)
            height = grid.get('height', 32)
            
            if traffic_grid is None or width > traffic_grid.shape[1]:
                traffic_grid = np.zeros((height, width))
                grid_width = width
                grid_height = height
            
            # Load plan
            plan_file = run_dir / record['plan_file']
            if not plan_file.exists():
                continue
            
            plan_data = load_json(plan_file)
            
            # Count visits per cell
            for state in plan_data.get('states', []):
                for agent_id, cell in state.items():
                    x, y = int(cell[0]), int(cell[1])
                    if 0 <= x < grid_width and 0 <= y < grid_height:
                        traffic_grid[y, x] += 1
        
        if traffic_grid is None or np.max(traffic_grid) == 0:
            continue
        
        # Render heatmap
        fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
        
        # Normalize
        traffic_normalized = traffic_grid / np.max(traffic_grid)
        
        # Create heatmap dengan custom colormap (white -> yellow -> orange -> red)
        im = ax.imshow(traffic_normalized, cmap='YlOrRd', origin='upper', 
                       vmin=0, vmax=1, interpolation='nearest')
        
        # Add obstacles
        for record in family_records:
            if not record.get('has_plan'):
                continue
            instance_data = record.get('instance_data', {})
            grid = instance_data.get('grid', {})
            obstacles = grid.get('obstacles', [])
            
            for obs in obstacles:
                x, y = obs
                rect = Rectangle((x-0.5, y-0.5), 1, 1, 
                                facecolor='gray', edgecolor='black', alpha=0.3)
                ax.add_patch(rect)
        
        ax.set_title(f'Traffic Density Heatmap - {family.capitalize()} Family', 
                    fontsize=14, pad=20)
        ax.set_xlabel('X coordinate', fontsize=12)
        ax.set_ylabel('Y coordinate', fontsize=12)
        
        # Colorbar
        cbar = plt.colorbar(im, ax=ax, shrink=0.8)
        cbar.set_label('Traffic Density (normalized)', fontsize=10)
        
        # Grid
        ax.set_xticks(np.arange(0, grid_width, 5))
        ax.set_yticks(np.arange(0, grid_height, 5))
        ax.grid(True, alpha=0.3, linestyle=':')
        
        plt.tight_layout()
        
        output_path = output_dir / f'heatmap_traffic_{family}.png'
        fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        
        print(f"  ✓ heatmap_traffic_{family}.png")
    
    print()


def render_failure_analysis(run_dir: Path, output_dir: Path):
    """Render failure analysis untuk semua instances."""
    
    results = load_json(run_dir / 'results.json')
    records = results['records']
    
    # Separate solved vs failed
    solved = [r for r in records if r.get('solved')]
    failed = [r for r in records if not r.get('solved')]
    
    print(f"📊 Rendering failure analysis ({len(failed)} failed, {len(solved)} solved)...")
    
    if not failed:
        print("  No failures to analyze!")
        return
    
    # 1. Failure by Family Bar Chart
    fig, axes = plt.subplots(2, 2, figsize=(14, 10), dpi=150)
    fig.suptitle('Failure Analysis Dashboard', fontsize=16)
    
    # Chart 1: Failures by family
    family_stats = defaultdict(lambda: {'total': 0, 'failed': 0})
    for record in records:
        family = record.get('family', 'unknown')
        family_stats[family]['total'] += 1
        if not record.get('solved'):
            family_stats[family]['failed'] += 1
    
    families = list(family_stats.keys())
    total_counts = [family_stats[f]['total'] for f in families]
    failed_counts = [family_stats[f]['failed'] for f in families]
    success_counts = [family_stats[f]['total'] - family_stats[f]['failed'] for f in families]
    
    x = np.arange(len(families))
    width = 0.6
    
    axes[0, 0].bar(x, success_counts, width, label='Solved', color='#10B981')
    axes[0, 0].bar(x, failed_counts, width, bottom=success_counts, label='Failed', color='#EF4444')
    axes[0, 0].set_xlabel('Family')
    axes[0, 0].set_ylabel('Count')
    axes[0, 0].set_title('Success vs Failure by Family')
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(families, rotation=45)
    axes[0, 0].legend()
    axes[0, 0].grid(axis='y', alpha=0.3)
    
    # Chart 2: Failures by scale
    scale_stats = defaultdict(lambda: {'total': 0, 'failed': 0})
    for record in records:
        scale = record.get('scale', 'unknown')
        scale_stats[scale]['total'] += 1
        if not record.get('solved'):
            scale_stats[scale]['failed'] += 1
    
    scales = sorted(scale_stats.keys())
    scale_failed = [scale_stats[s]['failed'] for s in scales]
    scale_success = [scale_stats[s]['total'] - scale_stats[s]['failed'] for s in scales]
    
    x = np.arange(len(scales))
    axes[0, 1].bar(x, scale_success, width, label='Solved', color='#10B981')
    axes[0, 1].bar(x, scale_failed, width, bottom=scale_success, label='Failed', color='#EF4444')
    axes[0, 1].set_xlabel('Scale')
    axes[0, 1].set_ylabel('Count')
    axes[0, 1].set_title('Success vs Failure by Scale')
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(scales, rotation=45)
    axes[0, 1].legend()
    axes[0, 1].grid(axis='y', alpha=0.3)
    
    # Chart 3: Failure reasons
    failure_reasons = defaultdict(int)
    for record in failed:
        reason = record.get('failure_reason', 'unknown')
        if reason in ['', 'None', None]:
            reason = record.get('planner_status', 'unknown')
        failure_reasons[reason] += 1
    
    reasons = list(failure_reasons.keys())
    counts = list(failure_reasons.values())
    
    axes[1, 0].barh(reasons, counts, color='#F59E0B')
    axes[1, 0].set_xlabel('Count')
    axes[1, 0].set_title('Failure Reasons')
    axes[1, 0].grid(axis='x', alpha=0.3)
    
    # Chart 4: Runtime distribution (solved vs failed)
    solved_runtimes = [r['runtime_s'] for r in solved]
    failed_runtimes = [r['runtime_s'] for r in failed]
    
    axes[1, 1].hist(solved_runtimes, bins=20, alpha=0.7, label='Solved', color='#10B981')
    axes[1, 1].hist(failed_runtimes, bins=20, alpha=0.7, label='Failed', color='#EF4444')
    axes[1, 1].set_xlabel('Runtime (s)')
    axes[1, 1].set_ylabel('Count')
    axes[1, 1].set_title('Runtime Distribution')
    axes[1, 1].legend()
    axes[1, 1].grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    
    output_path = output_dir / 'failure_analysis_dashboard.png'
    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    
    print(f"  ✓ failure_analysis_dashboard.png")
    
    # 2. Detailed failure positions heatmap
    render_failure_position_heatmap(run_dir, failed, output_dir)
    
    print()


def render_failure_position_heatmap(run_dir, failed_records, output_dir):
    """Render heatmap showing where agents get stuck."""
    
    if not failed_records:
        return
    
    # Aggregate stuck positions
    max_width = 32
    max_height = 32
    stuck_grid = np.zeros((max_height, max_width))
    
    for record in failed_records:
        if not record.get('plan_file'):
            continue
        
        plan_file = run_dir / record['plan_file']
        if not plan_file.exists():
            continue
        
        plan_data = load_json(plan_file)
        states = plan_data.get('states', [])
        
        if not states:
            continue
        
        # Get last state (where agents got stuck)
        last_state = states[-1]
        
        for agent_id, cell in last_state.items():
            x, y = int(cell[0]), int(cell[1])
            if 0 <= x < max_width and 0 <= y < max_height:
                stuck_grid[y, x] += 1
    
    if np.max(stuck_grid) == 0:
        return
    
    # Render
    fig, ax = plt.subplots(figsize=(10, 10), dpi=150)
    
    stuck_normalized = stuck_grid / np.max(stuck_grid)
    
    im = ax.imshow(stuck_normalized, cmap='Reds', origin='upper',
                   vmin=0, vmax=1, interpolation='nearest')
    
    ax.set_title('Agent Stuck Position Heatmap (Failed Instances)', 
                fontsize=14, pad=20)
    ax.set_xlabel('X coordinate', fontsize=12)
    ax.set_ylabel('Y coordinate', fontsize=12)
    
    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label('Frequency of Stuck Agents (normalized)', fontsize=10)
    
    ax.grid(True, alpha=0.3, linestyle=':')
    
    plt.tight_layout()
    
    output_path = output_dir / 'heatmap_failure_positions.png'
    fig.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    
    print(f"  ✓ heatmap_failure_positions.png")


def render_advanced_showcase(run_dir: Path, output_name: str = "analysis"):
    """Render all advanced visualizations."""
    
    run_dir = Path(run_dir)
    output_dir = ensure_dir(run_dir / output_name)
    
    print("=" * 60)
    print("🎨 ADVANCED VISUALIZATIONS")
    print("=" * 60)
    print(f"Run: {run_dir}")
    print(f"Output: {output_dir}")
    print()
    
    # 1. Traffic heatmaps per family
    render_traffic_heatmap_per_family(run_dir, output_dir)
    
    # 2. Failure analysis
    render_failure_analysis(run_dir, output_dir)
    
    print("=" * 60)
    print("✅ ADVANCED VISUALIZATIONS COMPLETE!")
    print(f"   Location: {output_dir}")
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_advanced_visualizations.py <run_directory> [output_folder]")
        print("Example: python render_advanced_visualizations.py artifacts/runs/20260409-074900_benchmark_premium analysis")
        sys.exit(1)
    
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Error: Directory not found: {run_dir}")
        sys.exit(1)
    
    output_name = sys.argv[2] if len(sys.argv) > 2 else "analysis"
    
    render_advanced_showcase(run_dir, output_name)
