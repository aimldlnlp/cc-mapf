# Connectivity-Constrained MAPF

A research-grade Python toolkit for connectivity-constrained multi-agent path finding on 2D grids.

![Problem Setup](artifacts/runs/20260409-074900_overnight_premium/showcase/fig01_problem_setup.png)

## Overview

`cc_mapf` generates synthetic benchmark instances, solves them with connectivity-aware planners, validates execution traces, and produces publication-quality visualizations.

**Key Results:**
- ✅ **86.7% success rate** (52/60 instances) on challenging benchmark
- ✅ **100% success** on formation_shift family
- ✅ **95% success** on medium-scale instances (24×24, 8 agents)

## Features

- **Discrete synchronous grid MAPF** with 4-neighbor moves plus wait
- **Connectivity constraints** enforced at every timestep
- **Conflict validation:** vertex conflicts, swap conflicts, connectivity violations
- **Synthetic benchmarks:** `open`, `corridor`, `warehouse`, `formation_shift`
- **Planner suite:** greedy, prioritized, CBS, connectivity-aware step planner
- **Rich visualizations:** traffic heatmaps, failure analysis, animated GIFs

## Installation

```bash
python3 -m pip install -e .[dev]
```

## Quick Start

### 1. Run Benchmark Suite

```bash
# Standard benchmark (recommended)
ccmapf batch --config configs/suites/overnight_premium.yaml

# Academic theme with paper-quality figures
ccmapf batch --config configs/suites/overnight_academic.yaml
```

### 2. Generate Advanced Visualizations

```bash
# Traffic heatmaps + failure analysis (run on existing results)
python render_advanced_visualizations.py artifacts/runs/{run_id} visualisasi
```

### 3. Render Showcase

```bash
ccmapf render --run artifacts/runs/{run_id} --preset showcase
```

## Benchmark Results

### Success Rate by Family

| Family | Solved / Total | Success Rate |
|--------|---------------|--------------|
| formation_shift | 15/15 | **100%** |
| corridor | 14/15 | **93.3%** |
| open | 13/15 | **86.7%** |
| warehouse | 10/15 | **66.7%** |

### Success Rate by Scale

| Scale | Solved / Total | Success Rate |
|-------|---------------|--------------|
| 16×16, 4 agents | 20/20 | **100%** |
| 24×24, 8 agents | 19/20 | **95%** |
| 32×32, 12 agents | 13/20 | **65%** |

## Visualizations

### 1. Problem Setup
![Problem Setup](artifacts/runs/20260409-074900_overnight_premium/showcase/fig01_problem_setup.png)

*Initial configuration showing 12 agents (colored circles) with their goals (outlined squares). Obstacles rendered with hatch pattern.*

### 2. Traffic Density Heatmaps

Per-family traffic analysis showing congestion hotspots:

![Failure Analysis](artifacts/runs/20260409-074900_overnight_premium/visualisasi/failure_analysis_dashboard.png)

*Failure analysis dashboard showing success/failure breakdown by family and scale, failure reasons, and runtime distribution.*

### 3. Animated GIFs

Side-by-side planner comparison dengan trail effects:

| GIF | Description |
|-----|-------------|
| `gif01_corridor_compare.gif` | Corridor navigation dengan connectivity constraints |
| `gif02_warehouse_compare.gif` | Warehouse environment challenge |
| `gif03_formation_compare.gif` | Formation shift maneuver |
| `gif04_open_space_connected.gif` | Open space coordinated movement |
| `gif05_cluster_shift_connected.gif` | Cluster repositioning |

## CLI Reference

### Generate Instances

```bash
ccmapf generate --config configs/suites/core.yaml
```

### Solve Single Instance

```bash
ccmapf solve --config configs/instances/example.yaml --planner connected_step
```

### Batch Experiments

```bash
# Run with detached session (survives disconnect)
./run_enhanced_full_detached.sh

# Or directly
ccmapf batch --config configs/suites/overnight_premium.yaml
```

### Render Visualizations

```bash
# Standard showcase (7 PNG + 5 GIF)
ccmapf render --run artifacts/runs/{run_id} --preset showcase

# Advanced analysis
python render_advanced_visualizations.py artifacts/runs/{run_id} visualisasi
```

## Configuration

### Suite Config Structure

```yaml
name: overnight_premium
families:
  - open
  - corridor
  - warehouse
  - formation_shift
scales:
  - width: 32
    height: 32
    agents: 12
seeds: [1, 2, 3, 4, 5]
planners:
  - connected_step
time_limit_s: 180.0
render:
  enabled: true
  theme: academic
  palette_preset: academic
  dpi: 200
```

### Available Themes

| Theme | Description |
|-------|-------------|
| `academic` | Paper-quality, DejaVu Serif, hatch patterns |
| `light` | Clean white background |
| `dark` | Dark mode with glow effects |
| `cyberpunk` | Neon aesthetic |

### Available Palettes

- `academic` - CMYK-friendly muted colors
- `vibrant` - Rainbow colors
- `ocean` - Blues and teals
- `forest` - Greens
- `cyberpunk` - Neon pink/purple/cyan

## Project Structure

```
configs/
├── instances/          # Instance definitions
├── render/             # Theme and palette presets
└── suites/             # Benchmark suite configs

src/cc_mapf/
├── planners/           # MAPF algorithms
│   ├── connected_step.py
│   ├── cbs.py
│   ├── greedy.py
│   └── prioritized.py
├── render.py           # Visualization engine
├── experiments.py      # Batch runner
└── validation.py       # Trace validator

artifacts/
└── runs/               # Experiment outputs
    └── {timestamp}_{suite}/
        ├── showcase/           # 7 PNG + 5 GIF
        ├── visualisasi/        # Advanced analysis
        ├── plans/              # JSON plans
        ├── instances/          # YAML instances
        ├── summary.json        # Aggregated metrics
        └── metrics.csv         # Per-instance data
```

## Key Metrics

The toolkit tracks comprehensive metrics:

- **Success rate** by family and scale
- **Makespan** (timesteps to reach all goals)
- **Sum of costs** (total path lengths)
- **Runtime** per instance
- **Expanded nodes** (search complexity)
- **Connectivity rejections** (constraint enforcement)
- **Recovery successes** (dead-end escapes)

## Citation

If you use this toolkit in your research:

```bibtex
@software{cc_mapf,
  title={Connectivity-Constrained MAPF},
  author={Research Team},
  year={2026},
  url={https://github.com/your-org/cc_mapf}
}
```

## License

MIT License - See LICENSE file for details.
