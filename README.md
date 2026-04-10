# CC-MAPF: Connectivity-Constrained Multi-Agent Path Finding

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A research-grade Python toolkit for **connectivity-constrained multi-agent path finding** on 2D grids. This tool generates synthetic benchmark instances, solves them with connectivity-aware planners, validates execution traces, and produces publication-quality visualizations.

## 🎯 Key Features

- **Connectivity Constraints**: Maintains team connectivity at every timestep
- **Multiple Planners**: Greedy, Prioritized, CBS, and connectivity-aware step planner
- **Rich Benchmarks**: 4 instance families (open, corridor, warehouse, formation_shift)
- **Publication Visualizations**: Academic-quality figures with heatmaps and animations
- **Validation**: Automated conflict and connectivity validation

## 📊 Results

**Benchmark Performance** (60 instances, 4 families, 3 scales):

| Metric | Value |
|--------|-------|
| **Overall Success Rate** | **86.7%** (52/60) |
| Formation Shift | 100% (15/15) |
| Corridor | 93.3% (14/15) |
| Open Space | 86.7% (13/15) |
| Warehouse | 66.7% (10/15) |

## 🚀 Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/aimldlnlp/cc-mapf.git
cd cc-mapf

# Install dependencies
python3 -m pip install -e .[dev]
```

### Run Benchmark

```bash
# Run standard benchmark
ccmapf batch --config configs/suites/overnight_premium.yaml

# Run with academic theme (paper-quality figures)
ccmapf batch --config configs/suites/overnight_academic.yaml
```

### Generate Visualizations

```bash
# Generate traffic heatmaps and failure analysis
python render_advanced_visualizations.py artifacts/runs/{run_id} visualisasi

# Render showcase (7 PNG + 5 GIF)
ccmapf render --run artifacts/runs/{run_id} --preset showcase
```

## 📁 Project Structure

```
cc-mapf/
├── configs/
│   ├── instances/          # Instance definitions
│   ├── render/             # Theme and palette presets
│   └── suites/             # Benchmark suite configurations
├── src/cc_mapf/
│   ├── planners/           # MAPF algorithms
│   │   ├── connected_step.py
│   │   ├── cbs.py
│   │   ├── greedy.py
│   │   └── prioritized.py
│   ├── render.py           # Visualization engine
│   ├── experiments.py      # Batch runner
│   └── validation.py       # Trace validator
├── artifacts/
│   └── runs/               # Experiment outputs (not in repo)
├── render_advanced_visualizations.py
└── README.md
```

## 🎨 Visualization Examples

### 1. Problem Setup
Shows initial agent positions (colored circles) with goals (outlined squares) and obstacles (hatched patterns).

*Generated with academic theme - DejaVu Serif font, 200 DPI, print-ready*

### 2. Traffic Density Heatmaps
Per-family analysis showing congestion hotspots across all instances.

### 3. Failure Analysis Dashboard
Comprehensive analysis including:
- Success vs Failure by Family
- Success vs Failure by Scale
- Failure Reasons (timeout, stalled, step_cap)
- Runtime Distribution

### 4. Animated GIFs
Side-by-side planner comparisons with trail effects:
- Corridor navigation
- Warehouse environment
- Formation shift
- Open space movement

## ⚙️ Configuration

### Suite Configuration

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
  gif_fps: 8
  interpolation_steps: 4
```

### Available Themes

| Theme | Description |
|-------|-------------|
| `academic` | Paper-quality, DejaVu Serif, hatch patterns |
| `light` | Clean white background |
| `dark` | Dark mode with subtle glow |
| `cyberpunk` | Neon aesthetic |

### Available Palettes

- `academic` - CMYK-friendly muted colors
- `vibrant` - Rainbow colors
- `ocean` - Blues and teals
- `forest` - Greens
- `sunset` - Warm reds/oranges
- `cyberpunk` - Neon pink/purple/cyan
- `pastel` - Soft colors
- `high_contrast` - Accessibility-focused

## 📖 Usage Guide

### 1. Generate Instances

```bash
ccmapf generate --config configs/suites/core.yaml
```

### 2. Solve Single Instance

```bash
ccmapf solve --config configs/instances/example.yaml --planner connected_step
```

### 3. Batch Experiments (Detached)

```bash
# Run in detached tmux session (survives disconnect)
./run_enhanced_full_detached.sh

# Monitor progress
tmux attach -t mapf-enhanced
```

### 4. Advanced Visualizations

```bash
# Generate heatmaps and analysis
./run_visualizations_only_detached.sh artifacts/runs/{run_id} visualisasi
```

## 📊 Output Structure

Each run creates:

```
artifacts/runs/{timestamp}_{suite}/
├── showcase/               # 7 PNG figures + 5 GIF animations
│   ├── fig01_problem_setup.png
│   ├── fig02_start_configuration.png
│   ├── fig03_corridor_mid_execution.png
│   ├── fig04_formation_transition.png
│   ├── fig05_final_configuration.png
│   ├── fig06_baseline_vs_connected_panel.png
│   ├── fig07_benchmark_summary.png
│   ├── gif01_corridor_compare.gif
│   ├── gif02_warehouse_compare.gif
│   ├── gif03_formation_compare.gif
│   ├── gif04_open_space_connected.gif
│   └── gif05_cluster_shift_connected.gif
├── visualisasi/            # Advanced analysis (heatmaps)
│   ├── heatmap_traffic_{family}.png
│   ├── failure_analysis_dashboard.png
│   └── heatmap_failure_positions.png
├── plans/                  # JSON plan files
├── instances/              # YAML instance files
├── summary.json            # Aggregated metrics
└── metrics.csv             # Per-instance data
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/

# Run specific test
pytest tests/test_planners.py -v
```

## 📈 Metrics Tracked

- **Success rate** by family and scale
- **Makespan** (timesteps to reach all goals)
- **Sum of costs** (total path lengths)
- **Runtime** per instance
- **Expanded nodes** (search complexity)
- **Connectivity rejections** (constraint enforcement)
- **Recovery successes** (dead-end escapes)

## 🔬 Algorithm Details

### Connected Step Planner

The main planner uses a **windowed beam search** with:
- Adaptive beam width based on progress
- Localized repair for dead-ends
- Reference trajectory following
- Connectivity validation at each step

Key features:
- **Beam width**: 96 (≤8 agents), 48 (>8 agents)
- **Horizon**: 5 timesteps
- **Repair depth**: 2 steps
- **Timeout**: Configurable (default 180s)

## 📝 Citation

If you use this toolkit in your research:

```bibtex
@software{cc_mapf,
  title={CC-MAPF: Connectivity-Constrained Multi-Agent Path Finding},
  author={Research Team},
  year={2026},
  url={https://github.com/aimldlnlp/cc-mapf}
}
```

## 📄 License

MIT License - See [LICENSE](LICENSE) file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## 📧 Contact

For questions or support, please open an issue on GitHub.

---

**Note**: Large output files (PNG, GIF, logs) are excluded from the repository via `.gitignore`. Run experiments locally to generate visualizations.
