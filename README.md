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

## 🎨 Visualization Gallery

> **Note**: To see actual visualizations, run the experiments and upload images to GitHub (see instructions below).

### Showcase Figures (7 PNG)

#### 1. Problem Setup
Initial configuration showing agents (colored circles), goals (outlined squares), and obstacles (hatched patterns).

```
Location: artifacts/runs/{run_id}/showcase/fig01_problem_setup.png
```

#### 2. Start Configuration
Connected team at timestep 0 with connectivity edges shown.

```
Location: artifacts/runs/{run_id}/showcase/fig02_start_configuration.png
```

#### 3. Corridor Mid-Execution
Agents navigating through corridor with maintained connectivity.

```
Location: artifacts/runs/{run_id}/showcase/fig03_corridor_mid_execution.png
```

#### 4. Formation Transition
Dynamic formation shift maneuver with coordinated movement.

```
Location: artifacts/runs/{run_id}/showcase/fig04_formation_transition.png
```

#### 5. Final Configuration
All agents reached their goals with makespan displayed.

```
Location: artifacts/runs/{run_id}/showcase/fig05_final_configuration.png
```

#### 6. Baseline vs Connected Comparison
Side-by-side comparison showing baseline violations vs connectivity-aware success.

```
Location: artifacts/runs/{run_id}/showcase/fig06_baseline_vs_connected_panel.png
```

#### 7. Benchmark Summary
Aggregated performance metrics: success rate, makespan, runtime.

```
Location: artifacts/runs/{run_id}/showcase/fig07_benchmark_summary.png
```

### Traffic Density Heatmaps (4 PNG)

#### Open Space Family
```
Location: artifacts/runs/{run_id}/visualisasi/heatmap_traffic_open.png
```

#### Corridor Family
```
Location: artifacts/runs/{run_id}/visualisasi/heatmap_traffic_corridor.png
```

#### Warehouse Family
```
Location: artifacts/runs/{run_id}/visualisasi/heatmap_traffic_warehouse.png
```

#### Formation Shift Family
```
Location: artifacts/runs/{run_id}/visualisasi/heatmap_traffic_formation_shift.png
```

### Failure Analysis (2 PNG)

#### Failure Analysis Dashboard
Comprehensive analysis with 4 panels:
- Success vs Failure by Family
- Success vs Failure by Scale  
- Failure Reasons (timeout, stalled, step_cap)
- Runtime Distribution

```
Location: artifacts/runs/{run_id}/visualisasi/failure_analysis_dashboard.png
```

#### Stuck Position Heatmap
Heatmap showing where agents get stuck in failed instances.

```
Location: artifacts/runs/{run_id}/visualisasi/heatmap_failure_positions.png
```

### Animated GIFs (5 GIF)

| GIF | Description | Features |
|-----|-------------|----------|
| `gif01_corridor_compare.gif` | Corridor navigation comparison | Trail effects, timestamps |
| `gif02_warehouse_compare.gif` | Warehouse environment | 8 FPS smooth animation |
| `gif03_formation_compare.gif` | Formation shift maneuver | Side-by-side comparison |
| `gif04_open_space_connected.gif` | Open space navigation | Connectivity visualization |
| `gif05_cluster_shift_connected.gif` | Tight cluster repositioning | Dynamic connectivity edges |

```
Location: artifacts/runs/{run_id}/showcase/*.gif
```

---

## 📸 How to Add Visualizations to This README

### Step 1: Generate Visualizations

```bash
# Run experiments
./run_enhanced_full_detached.sh

# Or generate visualizations from existing run
./run_visualizations_only_detached.sh artifacts/runs/{run_id} visualisasi
```

### Step 2: Download Images

Download generated PNG files from:
- `artifacts/runs/{run_id}/showcase/` (7 PNG + 5 GIF)
- `artifacts/runs/{run_id}/visualisasi/` (6 PNG)

### Step 3: Upload to GitHub

1. Go to https://github.com/aimldlnlp/cc-mapf/issues
2. Click "New Issue"
3. Drag and drop your images into the comment box
4. Wait for upload to complete
5. Copy the generated URL (looks like: `https://user-images.githubusercontent.com/...`)

### Step 4: Update README

Replace the placeholder text in this README with actual image URLs:

```markdown
Before:
```
Location: artifacts/runs/{run_id}/showcase/fig01_problem_setup.png
```

After:
![Problem Setup](https://user-images.githubusercontent.com/1234567/xxxxxx.png)
```

### Step 5: Commit and Push

```bash
git add README.md
git commit -m "docs: Add visualization images"
git push origin main
```

---

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

| Theme | Description | Best For |
|-------|-------------|----------|
| `academic` | DejaVu Serif, hatch patterns, white bg | Papers, publications |
| `light` | Clean white, minimal | Presentations |
| `dark` | Dark bg, subtle glow | Dark mode fans |
| `cyberpunk` | Neon colors, futuristic | Demos, videos |

### Available Palettes

| Palette | Colors | Use Case |
|---------|--------|----------|
| `academic` | Blue, Crimson, Emerald, Amber | CMYK print |
| `vibrant` | Rainbow | Presentations |
| `ocean` | Blues, teals | Calm aesthetic |
| `forest` | Greens | Nature themes |
| `cyberpunk` | Neon pink, purple, cyan | Futuristic |

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
│   ├── heatmap_traffic_open.png
│   ├── heatmap_traffic_corridor.png
│   ├── heatmap_traffic_warehouse.png
│   ├── heatmap_traffic_formation_shift.png
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

**Note**: Large output files (PNG, GIF, logs) are excluded from the repository via `.gitignore`. Run experiments locally to generate visualizations, then upload to GitHub to display in this README.
