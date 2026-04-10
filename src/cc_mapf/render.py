from __future__ import annotations

from pathlib import Path
from typing import Any

import imageio.v2 as imageio
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import yaml
from matplotlib.patches import Circle, Rectangle
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

from .environment import manhattan
from .model import Instance, RenderConfig, ShowcaseManifest
from .simulation import simulate_plan
from .utils import dump_json, ensure_dir, load_json, mean, median, serializable_to_plan
from .validation import connectivity_components


# Palette presets
PALETTE_PRESETS = {
    "earthy": ["#4C5B61", "#7D6B57", "#819A91", "#A67C52", "#59788E", "#B26E63", "#8E9AAF", "#7C9885"],
    "vibrant": ["#FF006E", "#FB5607", "#FFBE0B", "#8338EC", "#3A86FF", "#06FFB4", "#FF4365", "#00D9FF",
                "#FF9F1C", "#2EC4B6", "#E71D36", "#662E9B"],
    "ocean": ["#03045E", "#0077B6", "#0096C7", "#00B4D8", "#48CAE4", "#90E0EF", "#ADE8F4", "#CAF0F8"],
    "forest": ["#1B4332", "#2D6A4F", "#40916C", "#52B788", "#74C69D", "#95D5B2", "#B7E4C7", "#D8F3DC"],
    "sunset": ["#6A040F", "#9D0208", "#D00000", "#DC2F02", "#E85D04", "#F48C06", "#FAA307", "#FFBA08"],
    "cyberpunk": ["#F72585", "#B5179E", "#7209B7", "#560BAD", "#480CA8", "#3A0CA3", 
                  "#3F37C9", "#4361EE", "#4895EF", "#4CC9F0", "#00F5D4", "#00BBF9"],
    "pastel": ["#FFB3BA", "#FFDFBA", "#FFFFBA", "#BAFFC9", "#BAE1FF", "#E6B3FF", "#FFB3E6", "#B3FFF0"],
    "high_contrast": ["#FF0000", "#00FF00", "#0000FF", "#FFFF00", "#FF00FF", "#00FFFF",
                      "#FF8000", "#8000FF", "#0080FF", "#80FF00", "#FF0080", "#00FF80"],
    "academic": [  # CMYK-friendly, print-ready, Nature/Science style
        "#2563EB",  # Classic Blue
        "#DC2626",  # Crimson Red
        "#059669",  # Emerald Green
        "#D97706",  # Amber/Gold
        "#4F46E5",  # Indigo
        "#0D9488",  # Teal
        "#475569",  # Slate Gray
        "#E11D48",  # Rose
        "#7C3AED",  # Violet
        "#0891B2",  # Cyan
        "#BE123C",  # Ruby
        "#166534",  # Forest
    ],
}

# Theme presets
THEME_PRESETS = {
    "light": {
        "background_color": "#FFFFFF",
        "grid_color": "#D9D5CF",
        "obstacle_facecolor": "#D7D2C9",
        "obstacle_edgecolor": "#B2ACA2",
        "text_color": "#2C2C2C",
        "axes_edgecolor": "#A9A39A",
        "connectivity_edge_color": "#8A8883",
        "agent_edgecolor": "#55514B",
        "title_color": "#2C2C2C",
        "subtitle_color": "#555555",
        "glow_effect": False,
        "glow_radius": 0,
        "agent_size": 0.32,
    },
    "academic": {
        "background_color": "#FFFFFF",
        "grid_color": "#E5E7EB",  # Very light gray
        "grid_linestyle": ":",  # Dotted
        "obstacle_facecolor": "#F3F4F6",  # Light gray with hatch
        "obstacle_edgecolor": "#9CA3AF",  # Medium gray
        "text_color": "#1F2937",  # Dark gray (not pure black)
        "axes_edgecolor": "#374151",
        "connectivity_edge_color": "#6B7280",  # Gray
        "connectivity_linestyle": "--",  # Dashed
        "agent_edgecolor": "#374151",  # Dark gray border
        "title_color": "#111827",  # Near black
        "subtitle_color": "#4B5563",
        "glow_effect": False,
        "glow_radius": 0,
        "agent_size": 0.30,  # Slightly smaller, elegant
        "obstacle_hatch": "///",  # Diagonal lines
    },
    "dark": {
        "background_color": "#1A1A2E",
        "grid_color": "#16213E",
        "obstacle_facecolor": "#0F3460",
        "obstacle_edgecolor": "#1A4B7A",
        "text_color": "#EAEAEA",
        "axes_edgecolor": "#4A5568",
        "connectivity_edge_color": "#48CAE4",
        "agent_edgecolor": "#FFFFFF",
        "title_color": "#EAEAEA",
        "subtitle_color": "#B0B0B0",
        "glow_effect": True,
        "glow_radius": 3,
        "agent_size": 0.35,
    },
    "cyberpunk": {
        "background_color": "#0D0221",
        "grid_color": "#1A0F3C",
        "obstacle_facecolor": "#261447",
        "obstacle_edgecolor": "#FF3864",
        "text_color": "#F72585",
        "axes_edgecolor": "#7209B7",
        "connectivity_edge_color": "#4CC9F0",
        "agent_edgecolor": "#FFFFFF",
        "title_color": "#F72585",
        "subtitle_color": "#4CC9F0",
        "glow_effect": True,
        "glow_radius": 5,
        "agent_size": 0.38,
    },
    "ocean_dark": {
        "background_color": "#001219",
        "grid_color": "#003344",
        "obstacle_facecolor": "#005F73",
        "obstacle_edgecolor": "#0A9396",
        "text_color": "#E9D8A6",
        "axes_edgecolor": "#94D2BD",
        "connectivity_edge_color": "#CA6702",
        "agent_edgecolor": "#FFFFFF",
        "title_color": "#E9D8A6",
        "subtitle_color": "#94D2BD",
        "glow_effect": True,
        "glow_radius": 3,
        "agent_size": 0.35,
    },
    "high_contrast": {
        "background_color": "#FFFFFF",
        "grid_color": "#000000",
        "obstacle_facecolor": "#808080",
        "obstacle_edgecolor": "#000000",
        "text_color": "#000000",
        "axes_edgecolor": "#000000",
        "connectivity_edge_color": "#000000",
        "agent_edgecolor": "#000000",
        "title_color": "#000000",
        "subtitle_color": "#000000",
        "glow_effect": False,
        "glow_radius": 0,
        "agent_size": 0.40,
    },
}


def load_palette_preset(preset_name: str) -> list[str]:
    """Load a color palette preset."""
    return PALETTE_PRESETS.get(preset_name, PALETTE_PRESETS["earthy"])


def load_theme_preset(theme_name: str) -> dict[str, Any]:
    """Load a theme preset."""
    return THEME_PRESETS.get(theme_name, THEME_PRESETS["light"])


def apply_style(config: RenderConfig) -> None:
    # Apply theme preset if specified
    theme = load_theme_preset(config.theme)
    
    plt.rcParams.update(
        {
            "font.family": config.font_family,
            "font.weight": config.font_weight,
            "axes.titleweight": config.font_weight,
            "axes.labelweight": config.font_weight,
            "figure.titleweight": config.font_weight,
            "text.color": theme.get("text_color", config.text_color),
            "axes.edgecolor": theme.get("axes_edgecolor", config.axes_edgecolor),
            "axes.linewidth": 0.7,
            "xtick.color": theme.get("text_color", config.text_color),
            "ytick.color": theme.get("text_color", config.text_color),
            "grid.color": theme.get("grid_color", config.grid_color),
            "grid.linewidth": 0.4,
            "savefig.bbox": "tight",
            "savefig.pad_inches": 0.05,
            "savefig.facecolor": theme.get("background_color", config.background_color),
            "figure.facecolor": theme.get("background_color", config.background_color),
            "axes.facecolor": theme.get("background_color", config.background_color),
        }
    )


def add_glow_effect(ax, center, radius, color, glow_radius):
    """Add a glow effect around an agent."""
    for i in range(glow_radius, 0, -1):
        alpha = 0.1 + (0.2 * (glow_radius - i) / glow_radius)
        glow_circle = Circle(
            center,
            radius + (i * 0.05),
            facecolor=color,
            edgecolor="none",
            alpha=alpha,
            zorder=2,
        )
        ax.add_patch(glow_circle)


def render_showcase(
    run_dir: str | Path,
    *,
    results_payload: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
    config: RenderConfig | None = None,
) -> Path:
    run_path = Path(run_dir)
    payload = results_payload or load_json(run_path / "results.json")
    records = payload["records"]
    render_config = config or RenderConfig.from_dict(payload.get("render_config"))
    summary_data = summary or planner_summary(records)
    apply_style(render_config)
    showcase_dir = ensure_dir(run_path / "showcase")
    main_record = (
        select_record(records, family="open", planner="connected_step", min_agents=8)
        or select_record(records, planner="connected_step", min_agents=8)
        or select_record(records, family="open", planner="connected_step")
        or select_record(records, planner="connected_step")
        or select_record(records)
    )
    if main_record is None:
        raise ValueError("No renderable records were found in this run.")
    corridor_record = (
        select_record(records, family="corridor", planner="connected_step", min_agents=8)
        or select_record(records, family="corridor", planner="connected_step")
        or main_record
    )
    formation_record = (
        select_record(records, family="formation_shift", planner="connected_step", min_agents=8)
        or select_record(records, family="formation_shift", planner="connected_step")
        or main_record
    )
    open_record = (
        select_record(records, family="open", planner="connected_step", min_agents=8)
        or select_record(records, family="open", planner="connected_step")
        or main_record
    )
    cluster_record = (
        select_record(records, family="formation_shift", planner="connected_step", min_agents=8)
        or select_record(records, family="formation_shift", planner="connected_step")
        or main_record
    )
    compare_corridor = (
        select_pair(records, family="corridor", min_agents=8)
        or select_pair(records, family="corridor")
        or select_pair(records, min_agents=8)
        or select_pair(records)
        or (main_record, corridor_record)
    )
    compare_warehouse = (
        select_pair(records, family="warehouse", min_agents=8)
        or select_pair(records, family="warehouse")
        or compare_corridor
    )
    compare_formation = (
        select_pair(records, family="formation_shift", min_agents=8)
        or select_pair(records, family="formation_shift")
        or compare_corridor
    )

    main_instance, main_states, _ = load_trace(run_path, main_record)
    corridor_instance, corridor_states, _ = load_trace(run_path, corridor_record)
    formation_instance, formation_states, _ = load_trace(run_path, formation_record)
    open_instance, open_states, _ = load_trace(run_path, open_record)
    cluster_instance, cluster_states, _ = load_trace(run_path, cluster_record)
    compare_left_instance, compare_right_instance, compare_states_left, compare_states_right, compare_time = load_compare_trace(run_path, compare_corridor)
    warehouse_left_instance, warehouse_right_instance, warehouse_left, warehouse_right, _ = load_compare_trace(run_path, compare_warehouse)
    formation_left_instance, formation_right_instance, formation_left, formation_right, _ = load_compare_trace(run_path, compare_formation)

    manifest_sources: dict[str, dict[str, Any]] = {}
    mid_corridor = choose_midpoint(corridor_states)
    mid_formation = choose_midpoint(formation_states)
    fig01 = showcase_dir / "fig01_problem_setup.png"
    render_scene_png(
        fig01,
        main_instance,
        main_states[0],
        render_config,
        title="Problem setup",
        subtitle=f"{main_record['instance']} ({main_record['family']})",
        show_goals=True,
        show_connectivity=False,
        legend=True,
    )
    manifest_sources["fig01_problem_setup.png"] = source_entry(main_record, timestep=0)

    fig02 = showcase_dir / "fig02_start_configuration.png"
    render_scene_png(
        fig02,
        main_instance,
        main_states[0],
        render_config,
        title="Start configuration",
        subtitle="Connected team at timestep 0",
        show_goals=True,
        show_connectivity=True,
    )
    manifest_sources["fig02_start_configuration.png"] = source_entry(main_record, timestep=0)

    fig03 = showcase_dir / "fig03_corridor_mid_execution.png"
    render_scene_png(
        fig03,
        corridor_instance,
        corridor_states[mid_corridor],
        render_config,
        title="Corridor execution",
        subtitle=f"Timestep {mid_corridor}",
        show_goals=True,
        show_connectivity=True,
    )
    manifest_sources["fig03_corridor_mid_execution.png"] = source_entry(corridor_record, timestep=mid_corridor)

    fig04 = showcase_dir / "fig04_formation_transition.png"
    render_scene_png(
        fig04,
        formation_instance,
        formation_states[mid_formation],
        render_config,
        title="Formation transition",
        subtitle=f"Timestep {mid_formation}",
        show_goals=True,
        show_connectivity=True,
    )
    manifest_sources["fig04_formation_transition.png"] = source_entry(formation_record, timestep=mid_formation)

    fig05 = showcase_dir / "fig05_final_configuration.png"
    render_scene_png(
        fig05,
        main_instance,
        main_states[-1],
        render_config,
        title="Final configuration",
        subtitle=f"Makespan {len(main_states) - 1}",
        show_goals=True,
        show_connectivity=True,
    )
    manifest_sources["fig05_final_configuration.png"] = source_entry(main_record, timestep=len(main_states) - 1)

    fig06 = showcase_dir / "fig06_baseline_vs_connected_panel.png"
    render_compare_png(
        fig06,
        compare_left_instance,
        compare_right_instance,
        compare_states_left[min(compare_time, len(compare_states_left) - 1)],
        compare_states_right[min(compare_time, len(compare_states_right) - 1)],
        render_config,
        left_title=f"{compare_corridor[0]['planner']} @ t={compare_time}",
        right_title=f"{compare_corridor[1]['planner']} @ t={compare_time}",
        subtitle="Baseline vs connectivity-aware planner",
    )
    manifest_sources["fig06_baseline_vs_connected_panel.png"] = {
        "left": source_entry(compare_corridor[0], timestep=compare_time),
        "right": source_entry(compare_corridor[1], timestep=compare_time),
    }

    fig07 = showcase_dir / "fig07_benchmark_summary.png"
    render_summary_png(fig07, summary_data, render_config)
    manifest_sources["fig07_benchmark_summary.png"] = {"summary": "aggregated_metrics"}

    gif01 = showcase_dir / "gif01_corridor_compare.gif"
    render_compare_gif(
        gif01,
        compare_left_instance,
        compare_right_instance,
        compare_states_left,
        compare_states_right,
        render_config,
        left_title=compare_corridor[0]["planner"],
        right_title=compare_corridor[1]["planner"],
    )
    manifest_sources["gif01_corridor_compare.gif"] = {
        "left": source_entry(compare_corridor[0]),
        "right": source_entry(compare_corridor[1]),
    }

    gif02 = showcase_dir / "gif02_warehouse_compare.gif"
    render_compare_gif(
        gif02,
        warehouse_left_instance,
        warehouse_right_instance,
        warehouse_left,
        warehouse_right,
        render_config,
        left_title=compare_warehouse[0]["planner"],
        right_title=compare_warehouse[1]["planner"],
    )
    manifest_sources["gif02_warehouse_compare.gif"] = {
        "left": source_entry(compare_warehouse[0]),
        "right": source_entry(compare_warehouse[1]),
    }

    gif03 = showcase_dir / "gif03_formation_compare.gif"
    render_compare_gif(
        gif03,
        formation_left_instance,
        formation_right_instance,
        formation_left,
        formation_right,
        render_config,
        left_title=compare_formation[0]["planner"],
        right_title=compare_formation[1]["planner"],
    )
    manifest_sources["gif03_formation_compare.gif"] = {
        "left": source_entry(compare_formation[0]),
        "right": source_entry(compare_formation[1]),
    }

    gif04 = showcase_dir / "gif04_open_space_connected.gif"
    render_single_gif(gif04, open_instance, open_states, render_config, title="Open-space connected execution")
    manifest_sources["gif04_open_space_connected.gif"] = source_entry(open_record)

    gif05 = showcase_dir / "gif05_cluster_shift_connected.gif"
    render_single_gif(gif05, cluster_instance, cluster_states, render_config, title="Cluster-shift connected execution")
    manifest_sources["gif05_cluster_shift_connected.gif"] = source_entry(cluster_record)

    manifest = ShowcaseManifest(run_id=payload["run_id"], sources=manifest_sources)
    dump_json(manifest.to_dict(), showcase_dir / "showcase_manifest.json")
    return showcase_dir


def planner_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {"planners": {}}
    planners = sorted({record["planner"] for record in records})
    for planner in planners:
        subset = [record for record in records if record["planner"] == planner]
        solved = [record for record in subset if record["solved"]]
        makespans = [float(record["makespan"]) for record in solved if record["makespan"] is not None]
        sums = [float(record["sum_of_costs"]) for record in solved if record["sum_of_costs"] is not None]
        runtimes = [float(record["runtime_s"]) for record in subset]
        summary["planners"][planner] = {
            "total": len(subset),
            "solved": len(solved),
            "success_rate": len(solved) / len(subset) if subset else 0.0,
            "mean_makespan": mean(makespans),
            "median_makespan": median(makespans),
            "mean_sum_of_costs": mean(sums),
            "median_sum_of_costs": median(sums),
            "mean_runtime_s": mean(runtimes),
            "total_connectivity_rejections": sum(int(record["connectivity_rejections"]) for record in subset),
        }
    return summary


def source_entry(record: dict[str, Any], timestep: int | None = None) -> dict[str, Any]:
    payload = {
        "instance": record["instance"],
        "planner": record["planner"],
        "family": record["family"],
        "scale": record["scale"],
        "seed": record["seed"],
    }
    if timestep is not None:
        payload["timestep"] = timestep
    return payload


def select_record(
    records: list[dict[str, Any]],
    *,
    family: str | None = None,
    planner: str | None = None,
    min_agents: int = 0,
) -> dict[str, Any] | None:
    filtered = [
        record
        for record in records
        if record["has_plan"]
        and (family is None or record["family"] == family)
        and (planner is None or record["planner"] == planner)
        and record_agent_count(record) >= min_agents
    ]
    if not filtered:
        return None
    filtered.sort(
        key=lambda item: (
            -record_agent_count(item),
            -record_grid_area(item),
            item["family"],
            item["seed"],
            item["instance"],
            item["planner"],
        )
    )
    return filtered[0]


def select_pair(
    records: list[dict[str, Any]],
    *,
    family: str | None = None,
    left_planner: str = "cbs",
    right_planner: str = "connected_step",
    min_agents: int = 0,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    by_instance: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        if family is not None and record["family"] != family:
            continue
        if not record["has_plan"]:
            continue
        if record_agent_count(record) < min_agents:
            continue
        by_instance.setdefault(record["instance"], {})[record["planner"]] = record
    candidates: list[tuple[tuple[float, str, str, int], tuple[dict[str, Any], dict[str, Any]]]] = []
    for instance_name, planners in by_instance.items():
        if left_planner not in planners or right_planner not in planners:
            continue
        left = planners[left_planner]
        right = planners[right_planner]
        gap = abs((left["makespan"] or 0) - (right["makespan"] or 0)) + left["connectivity_failure_count"] * 2
        key = (-float(record_agent_count(right)), -float(record_grid_area(right)), -float(gap), left["family"], left["scale"], int(left["seed"]))
        candidates.append((key, (left, right)))
    if not candidates:
        dense_connected = [
            record
            for record in records
            if record["has_plan"]
            and record["planner"] == right_planner
            and (family is None or record["family"] == family)
            and record_agent_count(record) >= min_agents
        ]
        if len(dense_connected) < 2:
            return None
        dense_connected.sort(
            key=lambda item: (
                -record_agent_count(item),
                -record_grid_area(item),
                item["family"],
                item["scale"],
                item["seed"],
                item["instance"],
            )
        )
        return dense_connected[0], dense_connected[1]
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def load_trace(run_dir: Path, record: dict[str, Any]) -> tuple[Instance, list[dict[str, tuple[int, int]]], dict[str, Any]]:
    instance = Instance.from_dict(record["instance_data"])
    if record["plan_file"] is None:
        trace = simulate_plan(instance, None)
        return instance, trace.states, trace.validation.to_dict()
    payload = load_json(run_dir / record["plan_file"])
    states = [
        {agent_id: tuple(cell) for agent_id, cell in state.items()}
        for state in payload["states"]
    ]
    return instance, states, payload["validation"]


def load_compare_trace(
    run_dir: Path,
    pair: tuple[dict[str, Any], dict[str, Any]],
) -> tuple[Instance, Instance, list[dict[str, tuple[int, int]]], list[dict[str, tuple[int, int]]], int]:
    left_record, right_record = pair
    left_instance, left_states, left_validation = load_trace(run_dir, left_record)
    right_instance, right_states, right_validation = load_trace(run_dir, right_record)
    if left_record["instance"] == right_record["instance"] and left_validation.get("connectivity_failures"):
        compare_time = int(left_validation["connectivity_failures"][0]["time"])
    else:
        compare_time = max(1, min(len(left_states), len(right_states)) // 2)
    return left_instance, right_instance, left_states, right_states, compare_time


def choose_midpoint(states: list[dict[str, tuple[int, int]]]) -> int:
    if len(states) <= 2:
        return 0
    return len(states) // 2


def render_scene_png(
    path: Path,
    instance: Instance,
    positions: dict[str, tuple[float, float]],
    config: RenderConfig,
    *,
    title: str,
    subtitle: str = "",
    show_goals: bool,
    show_connectivity: bool,
    legend: bool = False,
) -> None:
    theme = load_theme_preset(config.theme)
    fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", config.background_color))
    
    draw_scene(ax, instance, positions, config, show_goals=show_goals, show_connectivity=show_connectivity)
    
    title_color = theme.get("title_color", config.title_color)
    subtitle_color = theme.get("subtitle_color", config.subtitle_color)
    text_color = theme.get("text_color", config.text_color)
    
    ax.set_title(title, fontsize=12, pad=8, color=title_color)
    if subtitle:
        fig.text(0.5, 0.965, subtitle, ha="center", va="top", fontsize=9, color=subtitle_color)
    if legend:
        fig.text(0.5, 0.02, "Goals are outlined squares; circles show current agent positions.", 
                ha="center", fontsize=8, color=text_color)
    fig.savefig(path, facecolor=theme.get("background_color", config.background_color))
    plt.close(fig)


def render_compare_png(
    path: Path,
    left_instance: Instance,
    right_instance: Instance,
    left_positions: dict[str, tuple[float, float]],
    right_positions: dict[str, tuple[float, float]],
    config: RenderConfig,
    *,
    left_title: str,
    right_title: str,
    subtitle: str,
) -> None:
    theme = load_theme_preset(config.theme)
    fig, axes = plt.subplots(1, 2, figsize=(config.figsize[0] * 1.85, config.figsize[1]), dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", config.background_color))
    
    draw_scene(axes[0], left_instance, left_positions, config, show_goals=True, show_connectivity=True)
    draw_scene(axes[1], right_instance, right_positions, config, show_goals=True, show_connectivity=True)
    
    title_color = theme.get("title_color", config.title_color)
    subtitle_color = theme.get("subtitle_color", config.subtitle_color)
    
    axes[0].set_title(left_title, fontsize=11, color=title_color)
    axes[1].set_title(right_title, fontsize=11, color=title_color)
    fig.text(0.5, 0.98, subtitle, ha="center", va="top", fontsize=10, color=subtitle_color)
    fig.savefig(path, facecolor=theme.get("background_color", config.background_color))
    plt.close(fig)


def render_summary_png(path: Path, summary: dict[str, Any], config: RenderConfig) -> None:
    theme = load_theme_preset(config.theme)
    palette = load_palette_preset(config.palette_preset) if config.palette_preset != "custom" else config.palette
    
    planners = sorted(summary["planners"])
    success = [summary["planners"][planner]["success_rate"] * 100.0 for planner in planners]
    makespan = [summary["planners"][planner]["mean_makespan"] for planner in planners]
    runtime = [summary["planners"][planner]["mean_runtime_s"] for planner in planners]
    
    fig, axes = plt.subplots(1, 3, figsize=(config.figsize[0] * 2.4, config.figsize[1] * 0.95), dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", "#FFFFFF"))
    
    title_color = theme.get("title_color", "#2C2C2C")
    text_color = theme.get("text_color", "#2C2C2C")
    grid_color = theme.get("grid_color", "#D9D5CF")
    
    metrics = [
        ("Success rate (%)", success),
        ("Mean makespan", makespan),
        ("Mean runtime (s)", runtime),
    ]
    for index, (label, values) in enumerate(metrics):
        color = palette[index % len(palette)]
        axes[index].set_facecolor(theme.get("background_color", "#FFFFFF"))
        axes[index].bar(planners, values, color=color, edgecolor=theme.get("axes_edgecolor", "#8D877E"), linewidth=0.6)
        axes[index].set_title(label, fontsize=11, color=title_color)
        axes[index].tick_params(axis="x", rotation=20, colors=text_color)
        axes[index].tick_params(axis="y", colors=text_color)
        axes[index].grid(True, axis="y", alpha=0.5, color=grid_color)
        for spine in axes[index].spines.values():
            spine.set_color(theme.get("axes_edgecolor", "#A9A39A"))
    
    fig.text(0.5, 0.02, "Aggregated planner comparison over the configured synthetic benchmark suite.", 
             ha="center", fontsize=8, color=text_color)
    fig.savefig(path, facecolor=theme.get("background_color", "#FFFFFF"))
    plt.close(fig)


def draw_scene(
    ax: plt.Axes,
    instance: Instance,
    positions: dict[str, tuple[float, float]],
    config: RenderConfig,
    *,
    show_goals: bool,
    show_connectivity: bool,
) -> None:
    # Load theme and palette
    theme = load_theme_preset(config.theme)
    palette = load_palette_preset(config.palette_preset) if config.palette_preset != "custom" else config.palette
    
    # Theme colors
    bg_color = theme.get("background_color", config.background_color)
    grid_color = theme.get("grid_color", config.grid_color)
    grid_linestyle = theme.get("grid_linestyle", "-")
    obstacle_face = theme.get("obstacle_facecolor", config.obstacle_facecolor)
    obstacle_edge = theme.get("obstacle_edgecolor", config.obstacle_edgecolor)
    obstacle_hatch = theme.get("obstacle_hatch", None)
    conn_color = theme.get("connectivity_edge_color", config.connectivity_edge_color)
    conn_linestyle = theme.get("connectivity_linestyle", "-")
    agent_edge = theme.get("agent_edgecolor", config.agent_edgecolor)
    text_color = theme.get("text_color", config.text_color)
    glow_effect = theme.get("glow_effect", config.glow_effect)
    glow_radius = theme.get("glow_radius", config.glow_radius)
    agent_size = theme.get("agent_size", config.agent_size)
    
    ax.set_xlim(0, instance.grid.width)
    ax.set_ylim(instance.grid.height, 0)
    ax.set_aspect("equal")
    
    # Grid settings - show every tick but with light styling
    ax.set_xticks(np.arange(0, instance.grid.width + 1, 1))
    ax.set_yticks(np.arange(0, instance.grid.height + 1, 1))
    ax.grid(True, color=grid_color, linestyle=grid_linestyle, linewidth=0.4, alpha=0.6)
    ax.tick_params(labelbottom=False, labelleft=False, length=0)
    ax.set_facecolor(bg_color)
    
    # Remove spines for cleaner look in academic mode
    if config.theme == "academic":
        for spine in ax.spines.values():
            spine.set_linewidth(0.5)
            spine.set_color("#9CA3AF")
    
    # Draw obstacles
    for obstacle in instance.grid.obstacles:
        rect = Rectangle(
            obstacle,
            1,
            1,
            facecolor=obstacle_face,
            edgecolor=obstacle_edge,
            linewidth=0.5,
        )
        if obstacle_hatch:
            rect.set_hatch(obstacle_hatch)
            rect.set_facecolor("none")  # Hatch looks better without fill
        ax.add_patch(rect)
    
    # Draw goals
    if show_goals:
        for index, agent in enumerate(instance.agents):
            color = palette[index % len(palette)]
            goal_linewidth = 1.5 if config.theme == "academic" else (1.2 if config.theme != "light" else 0.9)
            goal_linestyle = "-" if config.theme == "academic" else ("-" if config.theme == "cyberpunk" else ":")
            ax.add_patch(
                Rectangle(
                    (agent.goal[0] + 0.15, agent.goal[1] + 0.15),
                    0.7,
                    0.7,
                    fill=False,
                    edgecolor=color,
                    linewidth=goal_linewidth,
                    linestyle=goal_linestyle,
                    alpha=0.9,
                )
            )
    
    # Draw connectivity edges
    if show_connectivity:
        discrete_positions = {agent_id: (round(cell[0]), round(cell[1])) for agent_id, cell in positions.items()}
        for first in instance.agents:
            for second in instance.agents:
                if first.id >= second.id:
                    continue
                if manhattan(discrete_positions[first.id], discrete_positions[second.id]) == 1:
                    # For academic theme, use agent color for edges (tinted)
                    first_idx = instance.agents.index(first)
                    edge_color = palette[first_idx % len(palette)] if config.theme == "academic" else conn_color
                    ax.plot(
                        [positions[first.id][0] + 0.5, positions[second.id][0] + 0.5],
                        [positions[first.id][1] + 0.5, positions[second.id][1] + 0.5],
                        color=edge_color,
                        linewidth=1.0 if config.theme != "light" else 0.7,
                        linestyle=conn_linestyle,
                        zorder=2,
                        alpha=0.7,
                    )
    
    # Draw agents
    for index, agent in enumerate(instance.agents):
        color = palette[index % len(palette)]
        x_pos, y_pos = positions[agent.id]
        center = (x_pos + 0.5, y_pos + 0.5)
        
        # Add glow effect if enabled
        if glow_effect:
            add_glow_effect(ax, center, agent_size, color, glow_radius)
        
        # Draw agent circle
        circle_linewidth = 0.8 if config.theme == "academic" else (1.0 if config.theme != "light" else 0.7)
        ax.add_patch(
            Circle(
                center,
                agent_size,
                facecolor=color,
                edgecolor=agent_edge,
                linewidth=circle_linewidth,
                zorder=3,
                alpha=0.9,
            )
        )
        
        # Draw agent label
        label_color = "#FFFFFF" if config.theme in ["dark", "cyberpunk", "ocean_dark"] else "#FFFFFF"
        if config.theme == "academic":
            label_color = "#FFFFFF"  # White text on colored circles
        label_fontsize = 7
        label_weight = "bold"
        
        ax.text(
            x_pos + 0.5,
            y_pos + 0.52,
            agent.id.replace("r", ""),
            ha="center",
            va="center",
            fontsize=label_fontsize,
            fontweight=label_weight,
            color=label_color,
            zorder=4,
        )


def render_single_gif(
    path: Path,
    instance: Instance,
    states: list[dict[str, tuple[int, int]]],
    config: RenderConfig,
    *,
    title: str,
    show_trails: bool = True,
) -> None:
    interpolated = interpolate_states(states, config.interpolation_steps)
    frames = []
    
    for i, positions in enumerate(interpolated):
        # Calculate actual timestep
        timestep = i // config.interpolation_steps
        
        # Build trail history
        trail_history = None
        if show_trails and i > 0:
            # Get previous positions for trail (sample every N frames)
            trail_start = max(0, i - 8 * config.interpolation_steps)
            trail_history = interpolated[trail_start:i:config.interpolation_steps]
        
        frame = single_frame(
            instance, 
            positions, 
            config, 
            title=title, 
            timestep=timestep,
            trail_history=trail_history
        )
        frames.append(frame)
    
    imageio.mimsave(path, frames, duration=max(1, int(1000 / max(config.gif_fps, 1))))


def render_compare_gif(
    path: Path,
    left_instance: Instance,
    right_instance: Instance,
    left_states: list[dict[str, tuple[int, int]]],
    right_states: list[dict[str, tuple[int, int]]],
    config: RenderConfig,
    *,
    left_title: str,
    right_title: str,
    show_trails: bool = True,
) -> None:
    left_frames = interpolate_states(left_states, config.interpolation_steps)
    right_frames = interpolate_states(right_states, config.interpolation_steps)
    frame_count = max(len(left_frames), len(right_frames))
    if len(left_frames) < frame_count:
        left_frames.extend([left_frames[-1]] * (frame_count - len(left_frames)))
    if len(right_frames) < frame_count:
        right_frames.extend([right_frames[-1]] * (frame_count - len(right_frames)))
    
    frames = []
    for index in range(frame_count):
        # Calculate timestep
        timestep = index // config.interpolation_steps
        
        # Build trail histories
        left_trail = None
        right_trail = None
        if show_trails and index > 0:
            trail_start = max(0, index - 8 * config.interpolation_steps)
            left_trail = left_frames[trail_start:index:config.interpolation_steps]
            right_trail = right_frames[trail_start:index:config.interpolation_steps]
        
        frame = compare_frame(
            left_instance,
            right_instance,
            left_frames[index],
            right_frames[index],
            config,
            left_title=left_title,
            right_title=right_title,
            timestep=timestep,
            left_trail=left_trail,
            right_trail=right_trail,
        )
        frames.append(frame)
    
    imageio.mimsave(path, frames, duration=max(1, int(1000 / max(config.gif_fps, 1))))


def interpolate_states(
    states: list[dict[str, tuple[int, int]]],
    interpolation_steps: int,
) -> list[dict[str, tuple[float, float]]]:
    if not states:
        return []
    interpolated: list[dict[str, tuple[float, float]]] = []
    for index in range(len(states) - 1):
        current = states[index]
        nxt = states[index + 1]
        for step in range(interpolation_steps):
            alpha = step / interpolation_steps
            interpolated.append(
                {
                    agent_id: (
                        current[agent_id][0] * (1 - alpha) + nxt[agent_id][0] * alpha,
                        current[agent_id][1] * (1 - alpha) + nxt[agent_id][1] * alpha,
                    )
                    for agent_id in current
                }
            )
    interpolated.append({agent_id: (float(cell[0]), float(cell[1])) for agent_id, cell in states[-1].items()})
    return interpolated


def single_frame(
    instance: Instance,
    positions: dict[str, tuple[float, float]],
    config: RenderConfig,
    *,
    title: str,
    timestep: int | None = None,
    trail_history: list[dict[str, tuple[float, float]]] | None = None,
) -> np.ndarray:
    theme = load_theme_preset(config.theme)
    palette = load_palette_preset(config.palette_preset) if config.palette_preset != "custom" else config.palette
    fig, ax = plt.subplots(figsize=config.figsize, dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", config.background_color))
    
    # Draw trails if history provided
    if trail_history and len(trail_history) > 1:
        _draw_trails(ax, instance, trail_history, palette, config.theme)
    
    draw_scene(ax, instance, positions, config, show_goals=True, show_connectivity=config.show_connectivity_edges)
    
    # Title with timestep
    title_color = theme.get("title_color", config.title_color)
    if timestep is not None:
        title = f"{title} (t={timestep})"
    ax.set_title(title, fontsize=11, color=title_color, pad=10)
    
    frame = figure_to_array(fig)
    plt.close(fig)
    return frame


def _draw_trails(
    ax: plt.Axes,
    instance: Instance,
    trail_history: list[dict[str, tuple[float, float]]],
    palette: list[str],
    theme_name: str,
) -> None:
    """Draw fading trail paths for agents."""
    if len(trail_history) < 2:
        return
    
    # Number of trail segments to show
    max_trail_segments = min(len(trail_history) - 1, 8)
    
    for index, agent in enumerate(instance.agents):
        color = palette[index % len(palette)]
        
        # Extract path for this agent
        path_x = []
        path_y = []
        for state in trail_history[-max_trail_segments:]:
            if agent.id in state:
                x, y = state[agent.id]
                path_x.append(x + 0.5)
                path_y.append(y + 0.5)
        
        if len(path_x) < 2:
            continue
        
        # Draw trail with fading alpha
        for i in range(len(path_x) - 1):
            alpha = 0.1 + (0.4 * (i / len(path_x)))  # Fade from light to dark
            linewidth = 1.0 + (2.0 * (i / len(path_x)))  # Thicker at end
            ax.plot(
                [path_x[i], path_x[i+1]],
                [path_y[i], path_y[i+1]],
                color=color,
                linewidth=linewidth,
                alpha=alpha,
                zorder=1,
                solid_capstyle='round',
            )


def compare_frame(
    left_instance: Instance,
    right_instance: Instance,
    left_positions: dict[str, tuple[float, float]],
    right_positions: dict[str, tuple[float, float]],
    config: RenderConfig,
    *,
    left_title: str,
    right_title: str,
    timestep: int | None = None,
    left_trail: list[dict[str, tuple[float, float]]] | None = None,
    right_trail: list[dict[str, tuple[float, float]]] | None = None,
) -> np.ndarray:
    theme = load_theme_preset(config.theme)
    palette = load_palette_preset(config.palette_preset) if config.palette_preset != "custom" else config.palette
    fig, axes = plt.subplots(1, 2, figsize=(config.figsize[0] * 1.85, config.figsize[1]), dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", config.background_color))
    
    # Draw trails if provided
    if left_trail and len(left_trail) > 1:
        _draw_trails(axes[0], left_instance, left_trail, palette, config.theme)
    if right_trail and len(right_trail) > 1:
        _draw_trails(axes[1], right_instance, right_trail, palette, config.theme)
    
    draw_scene(axes[0], left_instance, left_positions, config, show_goals=True, show_connectivity=config.show_connectivity_edges)
    draw_scene(axes[1], right_instance, right_positions, config, show_goals=True, show_connectivity=config.show_connectivity_edges)
    
    title_color = theme.get("title_color", config.title_color)
    # Add timestep to titles if provided
    if timestep is not None:
        left_title = f"{left_title} (t={timestep})"
        right_title = f"{right_title} (t={timestep})"
    axes[0].set_title(left_title, fontsize=10, color=title_color)
    axes[1].set_title(right_title, fontsize=10, color=title_color)
    frame = figure_to_array(fig)
    plt.close(fig)
    return frame


def record_agent_count(record: dict[str, Any]) -> int:
    instance_data = record.get("instance_data", {})
    agents = instance_data.get("agents")
    if isinstance(agents, list):
        return len(agents)
    scale = str(record.get("scale", ""))
    try:
        return int(scale.split("_")[1].removesuffix("a"))
    except Exception:
        return 0


def record_grid_area(record: dict[str, Any]) -> int:
    instance_data = record.get("instance_data", {})
    grid = instance_data.get("grid", {})
    if isinstance(grid, dict) and "width" in grid and "height" in grid:
        return int(grid["width"]) * int(grid["height"])
    scale = str(record.get("scale", ""))
    try:
        dims = scale.split("_")[0]
        width, height = dims.split("x")
        return int(width) * int(height)
    except Exception:
        return 0


def figure_to_array(fig: plt.Figure) -> np.ndarray:
    fig.canvas.draw()
    width, height = fig.canvas.get_width_height()
    buffer = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
    return buffer.reshape((height, width, 4))
