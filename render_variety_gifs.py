#!/usr/bin/env python3
"""
Generate variety of GIF animations with different perspectives and effects.
Fun, eye-catching visualizations for demonstrations.
"""

import sys
sys.path.insert(0, 'src')

import matplotlib
matplotlib.use('Agg')

from pathlib import Path
from cc_mapf.render import (
    render_single_gif, render_compare_gif,
    load_trace, load_compare_trace, choose_midpoint,
    select_record, select_pair
)
from cc_mapf.utils import load_json, ensure_dir
from cc_mapf.model import Instance, RenderConfig


def render_fun_gifs(run_dir: Path, output_name: str = "fun_gifs"):
    """Generate fun, variety GIFs for demonstrations."""
    
    results = load_json(run_dir / 'results.json')
    records = results['records']
    
    output_dir = ensure_dir(run_dir / output_name)
    
    print("🎬 Generating FUN GIFs...")
    print()
    
    # Find interesting records
    formation_record = None
    corridor_record = None
    warehouse_record = None
    open_record = None
    
    for r in records:
        if r.get('solved'):
            if r['family'] == 'formation_shift' and formation_record is None:
                formation_record = r
            elif r['family'] == 'corridor' and corridor_record is None:
                corridor_record = r
            elif r['family'] == 'warehouse' and warehouse_record is None:
                warehouse_record = r
            elif r['family'] == 'open' and open_record is None:
                open_record = r
    
    # Config 1: Fast & Furious (High FPS)
    print("1. Fast mode (16 FPS)...")
    config_fast = RenderConfig()
    config_fast.theme = 'academic'
    config_fast.palette_preset = 'vibrant'  # Bright colors!
    config_fast.dpi = 100
    config_fast.gif_fps = 16  # Fast!
    config_fast.interpolation_steps = 2
    
    if formation_record:
        instance = Instance.from_dict(formation_record['instance_data'])
        plan_data = load_json(run_dir / formation_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '01_fast_formation.gif',
            instance, states, config_fast,
            title="Fast Formation Shift ⚡",
            show_trails=True
        )
        print("   ✓ 01_fast_formation.gif")
    
    # Config 2: Slow Motion (Detailed)
    print("2. Slow motion (4 FPS, high quality)...")
    config_slow = RenderConfig()
    config_slow.theme = 'academic'
    config_slow.palette_preset = 'academic'
    config_slow.dpi = 200  # High res!
    config_slow.gif_fps = 4  # Slow
    config_slow.interpolation_steps = 8  # Super smooth
    
    if corridor_record:
        instance = Instance.from_dict(corridor_record['instance_data'])
        plan_data = load_json(run_dir / corridor_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '02_slow_corridor.gif',
            instance, states, config_slow,
            title="Slow-Mo Corridor 🐌",
            show_trails=True
        )
        print("   ✓ 02_slow_corridor.gif")
    
    # Config 3: Cyberpunk Neon Style
    print("3. Cyberpunk neon mode...")
    config_cyber = RenderConfig()
    config_cyber.theme = 'cyberpunk'
    config_cyber.palette_preset = 'cyberpunk'
    config_cyber.glow_effect = True
    config_cyber.glow_radius = 5
    config_cyber.dpi = 120
    config_cyber.gif_fps = 8
    config_cyber.interpolation_steps = 4
    
    if warehouse_record:
        instance = Instance.from_dict(warehouse_record['instance_data'])
        plan_data = load_json(run_dir / warehouse_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '03_cyber_warehouse.gif',
            instance, states, config_cyber,
            title="Cyber Warehouse 💜",
            show_trails=True
        )
        print("   ✓ 03_cyber_warehouse.gif")
    
    # Config 4: Ocean Vibes
    print("4. Ocean theme...")
    config_ocean = RenderConfig()
    config_ocean.theme = 'ocean_dark'
    config_ocean.palette_preset = 'ocean'
    config_ocean.dpi = 120
    config_ocean.gif_fps = 8
    config_ocean.interpolation_steps = 4
    
    if open_record:
        instance = Instance.from_dict(open_record['instance_data'])
        plan_data = load_json(run_dir / open_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '04_ocean_open.gif',
            instance, states, config_ocean,
            title="Ocean Open Space 🌊",
            show_trails=True
        )
        print("   ✓ 04_ocean_open.gif")
    
    # Config 5: Side-by-side comparison (Baseline vs Connected)
    print("5. Side-by-side comparison...")
    compare_pair = select_pair(records, family='corridor')
    if compare_pair:
        left_rec, right_rec = compare_pair
        left_inst = Instance.from_dict(left_rec['instance_data'])
        right_inst = Instance.from_dict(right_rec['instance_data'])
        
        left_plan = load_json(run_dir / left_rec['plan_file'])
        right_plan = load_json(run_dir / right_rec['plan_file'])
        left_states = [{k: tuple(v) for k, v in s.items()} for s in left_plan['states']]
        right_states = [{k: tuple(v) for k, v in s.items()} for s in right_plan['states']]
        
        config_compare = RenderConfig()
        config_compare.theme = 'academic'
        config_compare.palette_preset = 'vibrant'
        config_compare.dpi = 100
        config_compare.gif_fps = 8
        
        render_compare_gif(
            output_dir / '05_compare_battle.gif',
            left_inst, right_inst,
            left_states, right_states,
            config_compare,
            left_title="😵 Baseline",
            right_title="✅ Connected",
            show_trails=True
        )
        print("   ✓ 05_compare_battle.gif")
    
    # Config 6: Sunset Vibes
    print("6. Sunset theme...")
    config_sunset = RenderConfig()
    config_sunset.theme = 'light'
    config_sunset.palette_preset = 'sunset'
    config_sunset.dpi = 120
    config_sunset.gif_fps = 6
    config_sunset.interpolation_steps = 6
    
    if formation_record:
        instance = Instance.from_dict(formation_record['instance_data'])
        plan_data = load_json(run_dir / formation_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '06_sunset_formation.gif',
            instance, states, config_sunset,
            title="Sunset Formation 🌅",
            show_trails=True
        )
        print("   ✓ 06_sunset_formation.gif")
    
    # Config 7: High Contrast (Accessibility)
    print("7. High contrast mode...")
    config_contrast = RenderConfig()
    config_contrast.theme = 'high_contrast'
    config_contrast.palette_preset = 'high_contrast'
    config_contrast.dpi = 120
    config_contrast.gif_fps = 8
    config_contrast.agent_size = 0.40
    
    if corridor_record:
        instance = Instance.from_dict(corridor_record['instance_data'])
        plan_data = load_json(run_dir / corridor_record['plan_file'])
        states = [{k: tuple(v) for k, v in s.items()} for s in plan_data['states']]
        
        render_single_gif(
            output_dir / '07_high_contrast.gif',
            instance, states, config_contrast,
            title="High Contrast ⚡",
            show_trails=True
        )
        print("   ✓ 07_high_contrast.gif")
    
    print()
    print(f"✅ FUN GIFs complete! Location: {output_dir}")
    print()
    print("Generated:")
    print("  • Fast & Furious (16 FPS)")
    print("  • Slow Motion (4 FPS, high res)")
    print("  • Cyberpunk Neon")
    print("  • Ocean Vibes")
    print("  • Side-by-side Battle")
    print("  • Sunset Formation")
    print("  • High Contrast")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python render_variety_gifs.py <run_directory> [output_folder]")
        print("Example: python render_variety_gifs.py artifacts/runs/20260409-074900_overnight_premium fun_gifs")
        sys.exit(1)
    
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Error: Directory not found: {run_dir}")
        sys.exit(1)
    
    output_name = sys.argv[2] if len(sys.argv) > 2 else "fun_gifs"
    
    render_fun_gifs(run_dir, output_name)
