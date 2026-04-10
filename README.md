# CC-MAPF: Connectivity-Constrained Multi-Agent Path Finding

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

A research-grade Python toolkit for **connectivity-constrained multi-agent path finding** on 2D grids.

## 📊 Results

**86.7% Success Rate** (52/60 instances)

| Family | Success Rate |
|--------|-------------|
| Formation Shift | 100% |
| Corridor | 93.3% |
| Open Space | 86.7% |
| Warehouse | 66.7% |

## 🎨 Visualizations

### Problem Setup
![Problem Setup](docs/assets/fig01_problem_setup.png)
*Initial configuration: agents (circles), goals (squares), obstacles (hatched)*

### Start Configuration
![Start](docs/assets/fig02_start_configuration.png)
*Connected team at timestep 0*

### Corridor Execution
![Corridor](docs/assets/fig03_corridor_mid_execution.png)
*Mid-execution in corridor environment*

### Formation Transition
![Formation](docs/assets/fig04_formation_transition.png)
*Dynamic formation shift maneuver*

### Final Configuration
![Final](docs/assets/fig05_final_configuration.png)
*All goals reached*

### Baseline Comparison
![Comparison](docs/assets/fig06_baseline_vs_connected_panel.png)
*Baseline (left) vs Connected step (right)*

### Benchmark Summary
![Summary](docs/assets/fig07_benchmark_summary.png)
*Performance metrics*

## 🗺️ Traffic Heatmaps

### Open Space
![Open Traffic](docs/assets/heatmap_traffic_open.png)

### Corridor
![Corridor Traffic](docs/assets/heatmap_traffic_corridor.png)

### Warehouse
![Warehouse Traffic](docs/assets/heatmap_traffic_warehouse.png)

### Formation Shift
![Formation Traffic](docs/assets/heatmap_traffic_formation_shift.png)

## 📈 Failure Analysis

![Failure Analysis](docs/assets/failure_analysis_dashboard.png)
*Success/failure breakdown by family, scale, and runtime*

## 🚀 Quick Start

```bash
# Install
python3 -m pip install -e .[dev]

# Run benchmark
ccmapf batch --config configs/suites/overnight_premium.yaml

# Generate visualizations
python render_advanced_visualizations.py artifacts/runs/{run_id} visualisasi
```

## 📁 Project Structure

```
cc-mapf/
├── configs/          # Configurations
├── src/cc_mapf/      # Source code
├── docs/assets/      # Visualization images
└── README.md
```

## 📝 Citation

```bibtex
@software{cc_mapf,
  title={CC-MAPF: Connectivity-Constrained Multi-Agent Path Finding},
  author={Research Team},
  year={2026},
  url={https://github.com/aimldlnlp/cc-mapf}
}
```

## 📄 License

MIT License
