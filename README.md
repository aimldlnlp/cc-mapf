# CC-MAPF: Robot Swarm Pathfinding 🎮🤖

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Your robot squad's personal GPS!** 📡

Ever seen a swarm of robots get stuck in a doorway because they forgot to talk to each other? 
Yeah, that doesn't happen here. We make sure your robot buddies stay connected while doing their thing!

![Problem Setup](docs/assets/fig01_problem_setup.png)
*The challenge: get everyone to their goals without breaking the wifi connection!*

## 🤔 What's This All About?

Picture this: You're managing a team of delivery robots. They need to:
- 🎯 Deliver packages to different spots
- 📶 Keep their wifi connection alive (teamwork!)
- 🚧 Not crash into each other (obviously)
- 🏢 Navigate through real-world spaces

**And we actually got 86.7% of them there!** Not bad for herding digital cats! 😸

## 🎬 The Movie Premiere

### Scene 1: Start Position - The Gathering
![Start](docs/assets/fig02_start_configuration.png)
*Everyone's here, fully charged, wifi signal strong! 💪*

### Scene 2: Corridor Chaos - Tight Squeeze!
![Corridor](docs/assets/fig03_corridor_mid_execution.png)
*Narrow hallway + 12 robots = organized chaos. Look at them squeeze through!*

### Scene 3: Formation Dance - Shape Shifting!
![Formation](docs/assets/fig04_formation_transition.png)
*Transforming from "blob" to "line formation" like a synchronized swimming team! 🏊*

### Scene 4: Mission Accomplished! 🎉
![Final](docs/assets/fig05_final_configuration.png)
*Goals reached! Connectivity maintained! High fives all around!* ✋

## 📊 The Scoreboard

| Challenge | Success Rate | The Tea ☕ |
|-----------|-------------|-----------|
| **Formation Shift** | 100% ✅ | Easy peasy! They're dancers! |
| **Corridors** | 93.3% | Narrow but manageable |
| **Open Space** | 86.7% | Room to breathe |
| **Warehouse** | 66.7% | Oof. Shelves everywhere! 🏢 |

**The warehouse is brutal.** It's like navigating a maze while playing Twister with 11 friends!

## 🗺️ Heat Maps - Where The Magic Happens

### Open Space - Freedom!
![Open Traffic](docs/assets/heatmap_traffic_open.png)
*Wide open spaces = happy robots*

### Corridors - The Bottleneck!
![Corridor Traffic](docs/assets/heatmap_traffic_corridor.png)
*Everyone wants through the door at once... relatable.*

### Warehouse - Traffic Jam City!
![Warehouse Traffic](docs/assets/heatmap_traffic_warehouse.png)
*Red zones = robot parties (and potential collisions)*

### Formation Shift - Coordinated Chaos!
![Formation Traffic](docs/assets/heatmap_traffic_formation_shift.png)
*Watch them dance through the grid*

## 🎥 Animated Stories - Grab Some Popcorn!

### The Main Show - 5 Scenarios!

| Animation | Story |
|-----------|-------|
| ![Corridor Compare](docs/assets/gif01_corridor_compare.gif) | **Corridor Battle:** Baseline vs Connected - spot the difference! |
| ![Warehouse Compare](docs/assets/gif02_warehouse_compare.gif) | **Warehouse Maze:** Navigating through obstacle city |
| ![Formation Compare](docs/assets/gif03_formation_compare.gif) | **Formation Dance:** Shape-shifting in action |
| ![Open Space](docs/assets/gif04_open_space_connected.gif) | **Open Field:** Freedom to roam (but stay connected!) |
| ![Cluster Shift](docs/assets/gif05_cluster_shift_connected.gif) | **Cluster Shuffle:** Tight squeeze repositioning |

### Bonus Features - 7 Different Styles!

| Style | Vibe |
|-------|------|
| ![Fast Formation](docs/assets/01_fast_formation.gif) | **Fast Mode (16 FPS)** - Don't blink! ⚡ |
| ![Slow Corridor](docs/assets/02_slow_corridor.gif) | **Slow Motion** - Every move calculated. Pure elegance. 🐌 |
| ![Cyber Warehouse](docs/assets/03_cyber_warehouse.gif) | **Cyberpunk** - Neon lights, dark vibes 💜 |
| ![Ocean Open](docs/assets/04_ocean_open.gif) | **Ocean** - Deep blue, very zen 🌊 |
| ![Compare Battle](docs/assets/05_compare_battle.gif) | **Side-by-Side** - See the difference! 🥊 |
| ![Sunset Formation](docs/assets/06_sunset_formation.gif) | **Sunset** - Warm colors, good vibes 🌅 |
| ![High Contrast](docs/assets/07_high_contrast.gif) | **High Contrast** - Bold and accessible ⚡ |

### The Showcase Collection

| GIF | Description |
|-----|-------------|
| ![Showcase Corridor](docs/assets/showcase_corridor.gif) | **Corridor Challenge** - Tight squeeze through narrow passages |
| ![Showcase Formation](docs/assets/showcase_formation.gif) | **Formation Shift** - Elegant shape transformation |
| ![Showcase Open](docs/assets/showcase_open.gif) | **Open Space** - Freedom with connectivity |

## 🚀 Let's Play!

```bash
# Clone the fun
git clone https://github.com/aimldlnlp/cc-mapf.git
cd cc-mapf

# Install the goods
python3 -m pip install -e .

# Run the demo
ccmapf batch --config configs/suites/overnight_premium.yaml

# Make pretty pictures
python render_advanced_visualizations.py artifacts/runs/{run_id} visualisasi

# Generate MORE GIFs!
python render_variety_gifs.py artifacts/runs/{run_id} fun_gifs
```

## 🎨 Themes Galore

Pick your vibe:
- 🔬 **Academic** - Clean, professional, publication-ready
- 🌙 **Cyberpunk** - Neon purples and blues. Very blade-runner.
- 🌊 **Ocean** - Deep blues, calm vibes
- 🌅 **Sunset** - Warm oranges and reds
- ⚡ **High Contrast** - Bold and accessible

## 🎯 Real-World Use Cases

Where this actually matters:
- 🤖 **Amazon warehouses** - Robots need to stay connected
- 🚁 **Drone shows** - Formation flying without losing communication
- 🎭 **Concert lighting** - Coordinated spotlights
- 🎮 **Game AI** - Squad movement that looks realistic

## 📁 Project Structure

```
cc-mapf/
├── configs/          # Scenario configs
├── src/cc_mapf/      # The brain
├── docs/assets/      # All the pretty pictures! (15 GIFs!)
├── render_*.py       # Make GIFs and PNGs
└── README.md         # You are here! 👋
```

## 📝 Citation

If this helped you out:

```bibtex
@software{cc_mapf,
  title={CC-MAPF: Connected Robot Swarms},
  author={Research Team},
  year={2026},
  url={https://github.com/aimldlnlp/cc-mapf}
}
```

## 📄 License

MIT - Go wild! Just give credit where it's due 😉

---

**Found a bug?** Open an issue! 
**Want to chat?** Hit us up!

*Made with ☕ and lots of trial-and-error* 🤖
