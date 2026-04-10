#!/usr/bin/env python3
"""
Generate enhanced showcase GIFs for the main demonstrations.
Uses the premium run data with nice effects.
"""

import sys
sys.path.insert(0, 'src')

import matplotlib
matplotlib.use('Agg')

from pathlib import Path
from cc_mapf.render import render_single_gif, load_compare_trace, choose_midpoint, select_record
from cc_mapf.utils import load_json, ensure_dir
from cc_mapf.model import Instance, RenderConfig


def render_showcase_gifs(run_dir: Path, output_name: str = "showcase_gifs"):
    """Generate the 5 main showcase GIFs."""
    
    results = load_json(run_dir / 'results.json')
    records = results['records']
    
    output_dir = ensure_dir(run_dir / output_name)
    
    print("🎬 Generating SHOWCASE GIFs...")
    print()
    
    # Find good records for each family
    corridor_rec = select_record(records, family='corridor', min_agents=8)
    warehouse_rec = select_record(records, family='warehouse', min_agents=10)
    formation_rec = select_record(records, family='formation_shift', min_agents=10)
    open_rec = select_record(records, family='open', min_agents=8)
    cluster_rec = select_record(records, family='cluster_shift', min_agents=8)
    
    # Standard config for showcase
    config = RenderConfig()
    config.theme = 'academic'
    config.palette_preset = 'vibrant'
    config.dpi = 150
    config.gif_fps = 8
    config.interpolation_steps = 4
    
    # 1. Corridor - Tight squeeze
    print("1. Corridor squeeze...")
    if corridor_rec:
        instance = Instance.from_dict(corridor_rec['instance_data'])
        plan_data = load_json(run_dir / corridor_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'showcase_corridor.gif',
            instance, states, config,
            title="Corridor Challenge 🚧",
            show_trails=True
        )
        print("   ✓ showcase_corridor.gif")
    
    # 2. Warehouse - Obstacle maze
    print("2. Warehouse maze...")
    if warehouse_rec:
        instance = Instance.from_dict(warehouse_rec['instance_data'])
        plan_data = load_json(run_dir / warehouse_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'showcase_warehouse.gif',
            instance, states, config,
            title="Warehouse Navigation 📦",
            show_trails=True
        )
        print("   ✓ showcase_warehouse.gif")
    
    # 3. Formation shift - Shape changing
    print("3. Formation dance...")
    if formation_rec:
        instance = Instance.from_dict(formation_rec['instance_data'])
        plan_data = load_json(run_dir / formation_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'showcase_formation.gif',
            instance, states, config,
            title="Formation Shift 🎭",
            show_trails=True
        )
        print("   ✓ showcase_formation.gif")
    
    # 4. Open space - Freedom
    print("4. Open space...")
    if open_rec:
        instance = Instance.from_dict(open_rec['instance_data'])
        plan_data = load_json(run_dir / open_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'showcase_open.gif',
            instance, states, config,
            title="Open Field 🌅",
            show_trails=True
        )
        print("   ✓ showcase_open.gif")
    
    # 5. Cluster shift - Tight repositioning
    print("5. Cluster shuffle...")
    if cluster_rec:
        instance = Instance.from_dict(cluster_rec['instance_data'])
        plan_data = load_json(run_dir / cluster_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'showcase_cluster.gif',
            instance, states, config,
            title="Cluster Shuffle 🔄",
            show_trails=True
        )
        print("   ✓ showcase_cluster.gif")
    
    print()
    print(f"✅ Showcase GIFs complete! Location: {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_enhanced_showcase.py <run_directory> [output_folder]")
        sys.exit(1)
    
    run_dir = Path(sys.argv[1])
    output_name = sys.argv[2] if len(sys.argv) > 2 else "showcase_gifs"
    
    render_showcase_gifs(run_dir, output_name)
