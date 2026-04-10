#!/usr/bin/env python3
"""
Generate showcase GIFs for demonstrations.
Creates professional academic-themed animations.
"""

import sys
sys.path.insert(0, 'src')

import matplotlib
matplotlib.use('Agg')

from pathlib import Path
from cc_mapf.render import render_single_gif, select_record
from cc_mapf.utils import load_json, ensure_dir
from cc_mapf.model import Instance, RenderConfig


def render_showcase_gifs(run_dir: Path, output_dir: Path = None):
    """Generate showcase GIFs with academic theme."""
    
    results = load_json(run_dir / 'results.json')
    records = results['records']
    
    if output_dir is None:
        output_dir = ensure_dir(Path('docs/assets'))
    else:
        output_dir = ensure_dir(output_dir)
    
    print("Generating showcase GIFs...")
    print()
    
    # Find good records for each family
    corridor_rec = select_record(records, family='corridor', min_agents=8)
    formation_rec = select_record(records, family='formation_shift', min_agents=10)
    open_rec = select_record(records, family='open', min_agents=8)
    
    # Academic config with white background
    config = RenderConfig()
    config.theme = 'academic'
    config.palette_preset = 'academic'
    config.dpi = 150
    config.gif_fps = 8
    config.interpolation_steps = 4
    
    # 1. Corridor showcase
    print("1. Corridor showcase...")
    if corridor_rec:
        instance = Instance.from_dict(corridor_rec['instance_data'])
        plan_data = load_json(run_dir / corridor_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'corridor_showcase.gif',
            instance, states, config,
            title="Corridor Navigation",
            show_trails=True
        )
        print("   + corridor_showcase.gif")
    
    # 2. Formation showcase
    print("2. Formation showcase...")
    if formation_rec:
        instance = Instance.from_dict(formation_rec['instance_data'])
        plan_data = load_json(run_dir / formation_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'formation_showcase.gif',
            instance, states, config,
            title="Formation Transition",
            show_trails=True
        )
        print("   + formation_showcase.gif")
    
    # 3. Open space showcase
    print("3. Open space showcase...")
    if open_rec:
        instance = Instance.from_dict(open_rec['instance_data'])
        plan_data = load_json(run_dir / open_rec['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / 'open_space_showcase.gif',
            instance, states, config,
            title="Open Space Navigation",
            show_trails=True
        )
        print("   + open_space_showcase.gif")
    
    print()
    print(f"Complete. Output: {output_dir}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_showcase.py <run_directory> [output_directory]")
        print("Example: python render_showcase.py artifacts/runs/20260409-074900")
        sys.exit(1)
    
    run_dir = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    render_showcase_gifs(run_dir, output_dir)
