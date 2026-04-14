from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
from rich.console import Console

from .experiments import run_batch
from .model import RenderConfig, ShowcaseManifest
from .render import (
    apply_style,
    load_compare_trace,
    load_palette_preset,
    load_theme_preset,
    load_trace,
    render_connectivity_rejection_heatmap,
    render_compare_gif,
    render_runtime_success_scatter,
    render_single_gif,
)
from .utils import dump_json, dump_yaml, ensure_dir, load_json, load_yaml, mean, median, timestamp_id

PAPER_FAMILIES = ["open", "corridor", "warehouse", "formation_shift"]
PAPER_SCALES = ["16x16_4a", "20x20_6a", "24x24_8a", "28x28_10a"]
PAPER_SCALE_SORT = {scale: index for index, scale in enumerate(PAPER_SCALES)}
PAPER_FAMILY_SORT = {family: index for index, family in enumerate(PAPER_FAMILIES)}
PILOT_TIME_LIMITS = {
    "16x16_4a": 45.0,
    "20x20_6a": 90.0,
    "24x24_8a": 180.0,
    "28x28_10a": 300.0,
}
OFFICIAL_TIME_LIMITS = dict(PILOT_TIME_LIMITS)
RETRY_TIME_LIMITS = {
    "16x16_4a": 45.0,
    "20x20_6a": 90.0,
    "24x24_8a": 240.0,
    "28x28_10a": 420.0,
}
OFFICIAL_THRESHOLDS = {
    "16x16_4a": 1.00,
    "20x20_6a": 0.90,
    "24x24_8a": 0.85,
    "28x28_10a": 0.80,
}
PILOT_CANDIDATES = ["connected_step", "windowed_cc", "enhanced_connected_step"]
DEFAULT_BASELINE = "prioritized_cc"


def write_status(status_path: Path | None, payload: dict[str, Any]) -> None:
    if status_path is None:
        return
    dump_json(payload, status_path)


def normalize_render_config(config: RenderConfig) -> RenderConfig:
    if config.strict_font_family:
        config.font_family = config.strict_font_family
    config.font_weight = "normal"
    config.theme = "academic"
    config.glow_effect = False
    config.glow_radius = 0
    return config


def check_cmu_serif_available() -> dict[str, Any]:
    try:
        fc_match = subprocess.run(
            ["fc-match", "CMU Serif"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise RuntimeError("Unable to verify CMU Serif with fc-match.") from exc
    from matplotlib import font_manager

    matches = sorted({font.name for font in font_manager.fontManager.ttflist if "CMU Serif" in font.name})
    if not matches:
        raise RuntimeError("CMU Serif is not available to matplotlib.")
    return {
        "fc_match": fc_match.stdout.strip(),
        "matplotlib_matches": matches,
    }


def run_preflight_tests(root_dir: Path) -> list[str]:
    commands = [
        [sys.executable, "-m", "pytest", "-q", "tests/test_cli_integration.py", "tests/test_environment_validation.py"],
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_render_style.py",
            "tests/test_render_selection.py",
            "tests/test_generator.py",
        ],
    ]
    executed: list[str] = []
    for command in commands:
        subprocess.run(command, check=True, cwd=root_dir)
        executed.append(" ".join(command))
    return executed


def materialize_suite_config(
    base_config_path: Path,
    output_path: Path,
    *,
    planners: list[str],
    render_enabled: bool,
    time_limit_s_by_scale: dict[str, float],
) -> Path:
    payload = load_yaml(base_config_path)
    payload["planners"] = planners
    payload["time_limit_s_by_scale"] = time_limit_s_by_scale
    payload["time_limit_s"] = max(time_limit_s_by_scale.values())
    render_payload = dict(payload.get("render", {}))
    render_payload["enabled"] = render_enabled
    payload["render"] = render_payload
    dump_yaml(payload, output_path)
    return output_path


def run_suite(config_path: Path) -> Path:
    console = Console()
    return run_batch(config_path, console=console)


def load_run_records(run_dir: Path) -> list[dict[str, Any]]:
    return list(load_json(run_dir / "results.json")["records"])


def planner_scorecard(records: list[dict[str, Any]], planner: str) -> dict[str, Any]:
    subset = [record for record in records if record["planner"] == planner]
    solved = [record for record in subset if record["solved"]]
    solved_runtime = [float(record["runtime_s"]) for record in solved]
    solved_sum_of_costs = [float(record["sum_of_costs"]) for record in solved if record["sum_of_costs"] is not None]
    timeout_count = sum(1 for record in subset if record["planner_status"] == "timeout")
    return {
        "planner": planner,
        "total": len(subset),
        "solved_valid": len(solved),
        "timeout_count": timeout_count,
        "mean_runtime_solved": mean(solved_runtime),
        "mean_sum_of_costs_solved": mean(solved_sum_of_costs),
    }


def select_planner_winner(records: list[dict[str, Any]], candidates: list[str]) -> tuple[str, list[dict[str, Any]]]:
    scorecards = [planner_scorecard(records, planner) for planner in candidates]
    scorecards.sort(
        key=lambda item: (
            -int(item["solved_valid"]),
            int(item["timeout_count"]),
            float(item["mean_runtime_solved"]),
            float(item["mean_sum_of_costs_solved"]),
            str(item["planner"]),
        )
    )
    return str(scorecards[0]["planner"]), scorecards


def evaluate_gate_status(records: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_reported_solved = sum(
        1 for record in records if record["planner_status"] == "solved" and not record["valid"]
    )
    solved_valid = sum(1 for record in records if record["solved"])
    total = len(records)
    by_scale: dict[str, dict[str, Any]] = {}
    for scale in PAPER_SCALES:
        subset = [record for record in records if record["scale"] == scale]
        solved_subset = sum(1 for record in subset if record["solved"])
        rate = solved_subset / len(subset) if subset else 0.0
        threshold = OFFICIAL_THRESHOLDS[scale]
        by_scale[scale] = {
            "solved_valid": solved_subset,
            "total": len(subset),
            "success_rate": rate,
            "threshold": threshold,
            "passed": rate >= threshold,
        }
    overall_success_rate = solved_valid / total if total else 0.0
    passed = invalid_reported_solved == 0 and overall_success_rate >= 0.90 and all(
        item["passed"] for item in by_scale.values()
    )
    return {
        "passed": passed,
        "reported_solved_invalid": invalid_reported_solved,
        "solved_valid": solved_valid,
        "total": total,
        "overall_success_rate": overall_success_rate,
        "by_scale": by_scale,
    }


def should_retry_official(records: list[dict[str, Any]], gate_status: dict[str, Any]) -> bool:
    if gate_status["passed"]:
        return False
    return any(
        record["scale"] in {"24x24_8a", "28x28_10a"} and not record["solved"]
        for record in records
    )


def official_run_quality_key(gate_status: dict[str, Any], records: list[dict[str, Any]]) -> tuple[float, ...]:
    solved = sum(1 for record in records if record["solved"])
    mean_runtime_all = mean([float(record["runtime_s"]) for record in records])
    timeout_count = sum(1 for record in records if record["planner_status"] == "timeout")
    return (
        1.0 if gate_status["passed"] else 0.0,
        float(gate_status["overall_success_rate"]),
        float(solved),
        -float(timeout_count),
        -float(mean_runtime_all),
    )


def select_better_official_run(
    primary_run: Path,
    primary_records: list[dict[str, Any]],
    primary_gate: dict[str, Any],
    retry_run: Path,
    retry_records: list[dict[str, Any]],
    retry_gate: dict[str, Any],
) -> tuple[Path, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    primary_key = official_run_quality_key(primary_gate, primary_records)
    retry_key = official_run_quality_key(retry_gate, retry_records)
    if retry_key > primary_key:
        return retry_run, retry_records, retry_gate, {"source": "retry"}
    return primary_run, primary_records, primary_gate, {"source": "primary"}


def run_official_candidate(
    *,
    planner: str,
    official_config: Path,
    configs_dir: Path,
) -> tuple[Path, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    materialized = materialize_suite_config(
        official_config,
        configs_dir / f"paper_official_{planner}_materialized.yaml",
        planners=[planner],
        render_enabled=False,
        time_limit_s_by_scale=OFFICIAL_TIME_LIMITS,
    )
    primary_run = run_suite(materialized)
    primary_records = load_run_records(primary_run)
    primary_gate = evaluate_gate_status(primary_records)
    retry_metadata: dict[str, Any] = {"attempted": False}

    if should_retry_official(primary_records, primary_gate):
        retry_materialized = materialize_suite_config(
            official_config,
            configs_dir / f"paper_official_{planner}_retry_materialized.yaml",
            planners=[planner],
            render_enabled=False,
            time_limit_s_by_scale=RETRY_TIME_LIMITS,
        )
        retry_run = run_suite(retry_materialized)
        retry_records = load_run_records(retry_run)
        retry_gate = evaluate_gate_status(retry_records)
        final_run, final_records, final_gate, retry_choice = select_better_official_run(
            primary_run,
            primary_records,
            primary_gate,
            retry_run,
            retry_records,
            retry_gate,
        )
        retry_metadata = {
            "attempted": True,
            "retry_run_dir": str(retry_run),
            "retry_gate_status": retry_gate,
            "selected_run": retry_choice["source"],
        }
        return final_run, final_records, final_gate, retry_metadata

    return primary_run, primary_records, primary_gate, retry_metadata


def choose_peak_motion_timestep(states: list[dict[str, tuple[int, int]]]) -> int:
    if len(states) <= 1:
        return 0
    midpoint = (len(states) - 1) / 2.0
    candidates: list[tuple[int, float, int]] = []
    for index, current in enumerate(states):
        if index == len(states) - 1:
            next_state = states[index]
        else:
            next_state = states[index + 1]
        movers = sum(1 for agent_id, cell in current.items() if next_state.get(agent_id) != cell)
        candidates.append((movers, abs(index - midpoint), index))
    best = sorted(candidates, key=lambda item: (-item[0], item[1], item[2]))[0]
    return int(best[2])


def select_hero_records(records: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    heroes: dict[tuple[str, str], dict[str, Any]] = {}
    for family in PAPER_FAMILIES:
        for scale in PAPER_SCALES:
            subset = [
                record
                for record in records
                if record["family"] == family and record["scale"] == scale and record["solved"]
            ]
            if not subset:
                raise ValueError(f"No solved-valid hero record for {family} {scale}.")
            makespans = [float(record["makespan"]) for record in subset if record["makespan"] is not None]
            target = median(makespans)
            subset.sort(
                key=lambda item: (
                    abs(float(item["makespan"]) - target),
                    float(item["runtime_s"]),
                    int(item["seed"]),
                    str(item["instance"]),
                )
            )
            heroes[(family, scale)] = subset[0]
    return heroes


def select_compare_pairs(
    comparison_records: list[dict[str, Any]],
    *,
    winner_planner: str,
    baseline_planner: str,
) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
    pairs: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    reversed_scales = list(reversed(PAPER_SCALES))
    for family in PAPER_FAMILIES:
        chosen_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        for scale in reversed_scales:
            candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for seed in sorted({int(record["seed"]) for record in comparison_records}):
                baseline = next(
                    (
                        record
                        for record in comparison_records
                        if record["family"] == family
                        and record["scale"] == scale
                        and int(record["seed"]) == seed
                        and record["planner"] == baseline_planner
                        and record["solved"]
                    ),
                    None,
                )
                winner = next(
                    (
                        record
                        for record in comparison_records
                        if record["family"] == family
                        and record["scale"] == scale
                        and int(record["seed"]) == seed
                        and record["planner"] == winner_planner
                        and record["solved"]
                    ),
                    None,
                )
                if baseline is not None and winner is not None:
                    candidates.append((baseline, winner))
            if not candidates:
                continue
            candidates.sort(
                key=lambda item: (
                    float(item[1]["runtime_s"]) + float(item[0]["runtime_s"]),
                    int(item[1]["seed"]),
                    str(item[1]["instance"]),
                )
            )
            chosen_pair = candidates[0]
            break
        if chosen_pair is None:
            fallback_winners = [
                record
                for record in comparison_records
                if record["family"] == family and record["planner"] == winner_planner and record["solved"]
            ]
            fallback_winners.sort(
                key=lambda item: (
                    -PAPER_SCALE_SORT.get(str(item["scale"]), -1),
                    float(item["runtime_s"]),
                    int(item["seed"]),
                    str(item["instance"]),
                )
            )
            if len(fallback_winners) >= 2:
                chosen_pair = (fallback_winners[0], fallback_winners[1])
            elif len(fallback_winners) == 1:
                chosen_pair = (fallback_winners[0], fallback_winners[0])
            else:
                raise ValueError(f"No comparison pair available for family {family}.")
        pairs[family] = chosen_pair
    return pairs


def render_success_rate_heatmap(path: Path, records: list[dict[str, Any]], config: RenderConfig) -> None:
    theme = {"background": "#FFFFFF"}
    matrix = np.zeros((len(PAPER_FAMILIES), len(PAPER_SCALES)))
    for row, family in enumerate(PAPER_FAMILIES):
        for col, scale in enumerate(PAPER_SCALES):
            subset = [record for record in records if record["family"] == family and record["scale"] == scale]
            matrix[row, col] = sum(1 for record in subset if record["solved"]) / len(subset) if subset else 0.0
    fig, ax = plt.subplots(figsize=(8.4, 4.8), dpi=config.dpi)
    image = ax.imshow(matrix, cmap="Greens", norm=Normalize(vmin=0.0, vmax=1.0), aspect="auto")
    ax.set_title("Success Rate by Family and Scale")
    ax.set_xticks(np.arange(len(PAPER_SCALES)), labels=PAPER_SCALES, rotation=15, ha="right")
    ax.set_yticks(np.arange(len(PAPER_FAMILIES)), labels=PAPER_FAMILIES)
    for row in range(len(PAPER_FAMILIES)):
        for col in range(len(PAPER_SCALES)):
            ax.text(col, row, f"{matrix[row, col] * 100:.0f}%", ha="center", va="center", fontsize=9)
    cbar = plt.colorbar(image, ax=ax, shrink=0.85)
    cbar.set_label("Success rate")
    fig.savefig(path, facecolor=theme["background"])
    plt.close(fig)


def render_runtime_distribution(path: Path, records: list[dict[str, Any]], config: RenderConfig) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=config.dpi)
    data = [
        [float(record["runtime_s"]) for record in records if record["scale"] == scale]
        for scale in PAPER_SCALES
    ]
    ax.boxplot(data, patch_artist=True, tick_labels=PAPER_SCALES)
    ax.set_title("Runtime Distribution by Scale")
    ax.set_ylabel("Runtime (s)")
    ax.tick_params(axis="x", rotation=15)
    ax.grid(True, axis="y", alpha=0.25)
    fig.savefig(path, facecolor="#FFFFFF")
    plt.close(fig)


def render_makespan_distribution(path: Path, records: list[dict[str, Any]], config: RenderConfig) -> None:
    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=config.dpi)
    data = [
        [
            float(record["makespan"])
            for record in records
            if record["scale"] == scale and record["solved"] and record["makespan"] is not None
        ]
        for scale in PAPER_SCALES
    ]
    ax.boxplot(data, patch_artist=True, tick_labels=PAPER_SCALES)
    ax.set_title("Solved Makespan Distribution by Scale")
    ax.set_ylabel("Makespan")
    ax.tick_params(axis="x", rotation=15)
    ax.grid(True, axis="y", alpha=0.25)
    fig.savefig(path, facecolor="#FFFFFF")
    plt.close(fig)


def render_comparison_summary(
    path: Path,
    comparison_records: list[dict[str, Any]],
    *,
    winner_planner: str,
    baseline_planner: str,
    config: RenderConfig,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(9.2, 6.4), dpi=config.dpi)
    metrics = [
        (
            "Success rate (%)",
            [
                100.0
                * (
                    sum(1 for record in comparison_records if record["planner"] == planner and record["solved"])
                    / max(1, sum(1 for record in comparison_records if record["planner"] == planner))
                )
                for planner in [baseline_planner, winner_planner]
            ],
        ),
        (
            "Mean runtime (s)",
            [
                mean([float(record["runtime_s"]) for record in comparison_records if record["planner"] == planner])
                for planner in [baseline_planner, winner_planner]
            ],
        ),
        (
            "Mean makespan",
            [
                mean(
                    [
                        float(record["makespan"])
                        for record in comparison_records
                        if record["planner"] == planner and record["solved"] and record["makespan"] is not None
                    ]
                )
                for planner in [baseline_planner, winner_planner]
            ],
        ),
        (
            "Mean sum of costs",
            [
                mean(
                    [
                        float(record["sum_of_costs"])
                        for record in comparison_records
                        if record["planner"] == planner and record["solved"] and record["sum_of_costs"] is not None
                    ]
                )
                for planner in [baseline_planner, winner_planner]
            ],
        ),
    ]
    labels = [baseline_planner, winner_planner]
    colors = ["#CBD5E1", "#2563EB"]
    for ax, (title, values) in zip(axes.flatten(), metrics, strict=True):
        ax.bar(labels, values, color=colors, edgecolor="#475569", linewidth=0.7)
        ax.set_title(title)
        ax.grid(True, axis="y", alpha=0.25)
    fig.suptitle("Comparison Subset: Baseline vs Selected Planner", y=0.98)
    fig.savefig(path, facecolor="#FFFFFF")
    plt.close(fig)


def validate_curated_bundle(bundle_dir: Path, *, config: RenderConfig | None = None) -> dict[str, Any]:
    pngs = sorted(bundle_dir.rglob("*.png"))
    gifs = sorted(bundle_dir.rglob("*.gif"))
    duplicate_paths = len({str(path.relative_to(bundle_dir)) for path in pngs + gifs}) != len(pngs) + len(gifs)
    suspicious_assets = [
        str(path.relative_to(bundle_dir))
        for path in pngs + gifs
        if path.name.startswith(("temp", "tmp", "placeholder"))
    ]
    expected_png = int(config.asset_budget_png) if config is not None else 20
    expected_gif = int(config.asset_budget_gif) if config is not None else 20
    passed = len(pngs) == expected_png and len(gifs) == expected_gif and not duplicate_paths and not suspicious_assets
    return {
        "passed": passed,
        "png_count": len(pngs),
        "gif_count": len(gifs),
        "expected_png_count": expected_png,
        "expected_gif_count": expected_gif,
        "duplicate_paths": duplicate_paths,
        "suspicious_assets": suspicious_assets,
    }


def select_hardest_solved_records(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    selections: dict[str, dict[str, Any]] = {}
    reversed_scales = list(reversed(PAPER_SCALES))
    for family in PAPER_FAMILIES:
        chosen_scale: str | None = None
        for scale in reversed_scales:
            if any(record["family"] == family and record["scale"] == scale and record["solved"] for record in records):
                chosen_scale = scale
                break
        if chosen_scale is None:
            raise ValueError(f"No solved record available for atlas family {family}.")
        subset = [
            record
            for record in records
            if record["family"] == family and record["scale"] == chosen_scale and record["solved"]
        ]
        makespans = [float(record["makespan"]) for record in subset if record["makespan"] is not None]
        target = median(makespans)
        subset.sort(
            key=lambda item: (
                abs(float(item["makespan"]) - target),
                float(item["runtime_s"]),
                int(item["seed"]),
                str(item["instance"]),
            )
        )
        selections[family] = subset[0]
    return selections


def compute_density_matrix(instance: Any, states: list[dict[str, tuple[int, int]]]) -> np.ndarray:
    density = np.zeros((instance.grid.height, instance.grid.width), dtype=float)
    for state in states:
        for cell in state.values():
            x_pos = int(round(cell[0]))
            y_pos = int(round(cell[1]))
            if 0 <= x_pos < instance.grid.width and 0 <= y_pos < instance.grid.height:
                density[y_pos, x_pos] += 1.0
    max_density = float(density.max()) if density.size else 0.0
    if max_density > 0.0:
        density /= max_density
    return density


def hotspot_mask(density: np.ndarray, *, percentile: float = 85.0) -> np.ndarray:
    nonzero = density[density > 0.0]
    if nonzero.size == 0:
        return np.zeros_like(density)
    threshold = float(np.percentile(nonzero, percentile))
    mask = np.where(density >= threshold, density, 0.0)
    return mask


def draw_map_overlay(ax: plt.Axes, instance: Any, config: RenderConfig) -> None:
    theme = load_theme_preset(config.theme)
    palette = load_palette_preset(config.palette_preset) if config.palette_preset != "custom" else config.palette
    ax.set_xlim(0, instance.grid.width)
    ax.set_ylim(instance.grid.height, 0)
    ax.set_aspect("equal")
    ax.set_xticks(np.arange(0, instance.grid.width + 1, 1))
    ax.set_yticks(np.arange(0, instance.grid.height + 1, 1))
    ax.grid(True, color=theme.get("grid_color", config.grid_color), linestyle=theme.get("grid_linestyle", ":"), linewidth=0.35, alpha=0.45)
    ax.tick_params(labelbottom=False, labelleft=False, length=0)
    ax.set_facecolor(theme.get("background_color", config.background_color))
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
        spine.set_color("#9CA3AF")
    obstacle_face = theme.get("obstacle_facecolor", config.obstacle_facecolor)
    obstacle_edge = theme.get("obstacle_edgecolor", config.obstacle_edgecolor)
    obstacle_hatch = theme.get("obstacle_hatch", "///")
    for obstacle in instance.grid.obstacles:
        rect = Rectangle(
            obstacle,
            1,
            1,
            facecolor="none" if obstacle_hatch else obstacle_face,
            edgecolor=obstacle_edge,
            linewidth=0.5,
            hatch=obstacle_hatch,
            zorder=3,
        )
        ax.add_patch(rect)
    for index, agent in enumerate(instance.agents):
        color = palette[index % len(palette)]
        goal_box = Rectangle(
            (agent.goal[0] + 0.15, agent.goal[1] + 0.15),
            0.7,
            0.7,
            fill=False,
            edgecolor=color,
            linewidth=1.0,
            linestyle="-",
            alpha=0.95,
            zorder=4,
        )
        ax.add_patch(goal_box)


def render_density_atlas(
    path: Path,
    records: list[dict[str, Any]],
    run_dir: Path,
    config: RenderConfig,
    *,
    title: str,
    hotspot_only: bool,
) -> None:
    theme = load_theme_preset(config.theme)
    selected = select_hardest_solved_records(records)
    cmap_name = "PuBuGn" if not hotspot_only else "Reds"
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 9.2), dpi=config.dpi)
    fig.patch.set_facecolor(theme.get("background_color", "#FFFFFF"))
    for axis, family in zip(axes.flatten(), PAPER_FAMILIES, strict=True):
        record = selected[family]
        instance, states, _ = load_trace(run_dir, record)
        density = compute_density_matrix(instance, states)
        image = hotspot_mask(density) if hotspot_only else density
        axis.imshow(
            image,
            cmap=cmap_name,
            norm=Normalize(vmin=0.0, vmax=1.0),
            interpolation="nearest",
            extent=(0, instance.grid.width, instance.grid.height, 0),
            alpha=0.88,
            zorder=1,
        )
        draw_map_overlay(axis, instance, config)
        axis.set_title(f"{family.replace('_', ' ').title()} | {record['scale']}", fontsize=11, color=theme.get("title_color", "#111827"))
    fig.suptitle(title, y=0.98, color=theme.get("title_color", "#111827"))
    note = "Hotspot cells at or above the 85th percentile of nonzero occupancy density." if hotspot_only else "Normalized occupancy density over the full winner trajectory."
    fig.text(0.5, 0.02, note, ha="center", fontsize=8, color=theme.get("text_color", "#1F2937"))
    fig.tight_layout(rect=(0.02, 0.04, 0.98, 0.96))
    fig.savefig(path, facecolor=theme.get("background_color", "#FFFFFF"))
    plt.close(fig)


def render_curated_bundle(
    official_run_dir: Path,
    comparison_run_dir: Path,
    *,
    output_dir: Path,
    config: RenderConfig,
    selected_planner: str,
    official_gate_status: dict[str, Any],
) -> tuple[Path, ShowcaseManifest, dict[str, Any]]:
    config = normalize_render_config(config)
    apply_style(config)
    output_dir = ensure_dir(output_dir)
    png_dir = ensure_dir(output_dir / "png")
    gif_dir = ensure_dir(output_dir / "gif")

    official_records = load_run_records(official_run_dir)
    comparison_records = load_run_records(comparison_run_dir)
    heroes = select_hero_records(official_records)
    compare_pairs = select_compare_pairs(
        comparison_records,
        winner_planner=selected_planner,
        baseline_planner=config.compare_baseline_planner or DEFAULT_BASELINE,
    )

    manifest_sources: dict[str, dict[str, Any]] = {}
    asset_listing = {"png": [], "gif": []}

    for family in PAPER_FAMILIES:
        for scale in PAPER_SCALES:
            record = heroes[(family, scale)]
            instance, states, _ = load_trace(official_run_dir, record)
            gif_path = gif_dir / f"hero__{family}__{scale}.gif"
            render_single_gif(
                gif_path,
                instance,
                states,
                config,
                title=f"{family.replace('_', ' ').title()} | {scale}",
                show_trails=True,
            )
            manifest_sources[str(gif_path.relative_to(output_dir))] = {
                "kind": "hero_gif",
                "family": family,
                "scale": scale,
                "seed": record["seed"],
                "planner": record["planner"],
                "instance": record["instance"],
            }
            asset_listing["gif"].append(str(gif_path.relative_to(output_dir)))

    analysis_pngs = [
        ("success-rate-heatmap.png", lambda path: render_success_rate_heatmap(path, official_records, config), "analysis_png"),
        ("runtime-distribution.png", lambda path: render_runtime_distribution(path, official_records, config), "analysis_png"),
        ("makespan-distribution.png", lambda path: render_makespan_distribution(path, official_records, config), "analysis_png"),
        (
            "comparison-summary.png",
            lambda path: render_comparison_summary(
                path,
                comparison_records,
                winner_planner=selected_planner,
                baseline_planner=config.compare_baseline_planner or DEFAULT_BASELINE,
                config=config,
            ),
            "analysis_png",
        ),
        ("connectivity-rejection-heatmap.png", lambda path: render_connectivity_rejection_heatmap(path, official_records, config), "analysis_png"),
        ("runtime-success-scatter.png", lambda path: render_runtime_success_scatter(path, official_records, config), "analysis_png"),
        (
            "flow-atlas.png",
            lambda path: render_density_atlas(
                path,
                official_records,
                official_run_dir,
                config,
                title="Flow Atlas by Family",
                hotspot_only=False,
            ),
            "map_analysis_png",
        ),
        (
            "bottleneck-atlas.png",
            lambda path: render_density_atlas(
                path,
                official_records,
                official_run_dir,
                config,
                title="Bottleneck Atlas by Family",
                hotspot_only=True,
            ),
            "map_analysis_png",
        ),
    ]
    for filename, render_fn, kind in analysis_pngs:
        path = png_dir / filename
        render_fn(path)
        manifest_sources[str(path.relative_to(output_dir))] = {"kind": kind, "name": filename}
        asset_listing["png"].append(str(path.relative_to(output_dir)))

    for family in PAPER_FAMILIES:
        baseline_record, winner_record = compare_pairs[family]
        left_instance, right_instance, left_states, right_states, _ = load_compare_trace(
            comparison_run_dir,
            (baseline_record, winner_record),
        )
        path = gif_dir / f"compare__{family}.gif"
        render_compare_gif(
            path,
            left_instance,
            right_instance,
            left_states,
            right_states,
            config,
            left_title=baseline_record["planner"],
            right_title=winner_record["planner"],
            show_trails=True,
        )
        manifest_sources[str(path.relative_to(output_dir))] = {
            "kind": "compare_gif",
            "family": family,
            "scale": winner_record["scale"],
            "seed": winner_record["seed"],
            "baseline_planner": baseline_record["planner"],
            "winner_planner": winner_record["planner"],
            "instance": winner_record["instance"],
        }
        asset_listing["gif"].append(str(path.relative_to(output_dir)))

    manifest = ShowcaseManifest(
        run_id=output_dir.name,
        sources=manifest_sources,
        metadata={
            "official_run": str(official_run_dir),
            "comparison_run": str(comparison_run_dir),
            "selected_planner": selected_planner,
            "gate_status": official_gate_status,
            "assets": asset_listing,
            "render_config": config.to_dict(),
        },
    )
    dump_json(manifest.to_dict(), output_dir / "paper_bundle_manifest.json")
    validation = validate_curated_bundle(output_dir, config=config)
    dump_json(validation, output_dir / "paper_bundle_validation.json")
    if not validation["passed"]:
        raise ValueError(f"Curated paper bundle validation failed: {validation}")
    return output_dir, manifest, validation


def run_rollout(
    *,
    root_dir: Path,
    rollout_dir: Path,
    pilot_config: Path,
    official_config: Path,
    comparison_config: Path,
    render_config_path: Path,
    status_file: Path | None = None,
) -> dict[str, Any]:
    rollout_dir = ensure_dir(rollout_dir)
    configs_dir = ensure_dir(rollout_dir / "configs")
    bundle_dir = ensure_dir(rollout_dir / "bundle")
    status: dict[str, Any] = {"stage": "starting", "rollout_dir": str(rollout_dir)}
    write_status(status_file, status)
    summary: dict[str, Any] = {"rollout_dir": str(rollout_dir)}
    try:
        font_check = check_cmu_serif_available()
        preflight_tests = run_preflight_tests(root_dir)
        status.update({"stage": "preflight_complete", "font_check": font_check, "preflight_tests": preflight_tests})
        write_status(status_file, status)

        pilot_materialized = materialize_suite_config(
            pilot_config,
            configs_dir / "paper_pilot_materialized.yaml",
            planners=PILOT_CANDIDATES,
            render_enabled=False,
            time_limit_s_by_scale=PILOT_TIME_LIMITS,
        )
        pilot_run_dir = run_suite(pilot_materialized)
        pilot_records = load_run_records(pilot_run_dir)
        pilot_selected_planner, pilot_scorecards = select_planner_winner(pilot_records, PILOT_CANDIDATES)
        ordered_candidates = [str(item["planner"]) for item in pilot_scorecards]
        status.update(
            {
                "stage": "pilot_complete",
                "pilot_run_dir": str(pilot_run_dir),
                "pilot_scorecards": pilot_scorecards,
                "pilot_selected_planner": pilot_selected_planner,
                "selected_planner": pilot_selected_planner,
            }
        )
        write_status(status_file, status)

        candidate_runs: list[dict[str, Any]] = []
        best_candidate: dict[str, Any] | None = None
        for planner in ordered_candidates:
            official_run_dir, official_records, gate_status, retry_metadata = run_official_candidate(
                planner=planner,
                official_config=official_config,
                configs_dir=configs_dir,
            )
            candidate_payload = {
                "planner": planner,
                "official_run_dir": str(official_run_dir),
                "official_gate_status": gate_status,
                "official_retry": retry_metadata,
                "records": official_records,
            }
            candidate_runs.append(candidate_payload)
            if best_candidate is None or official_run_quality_key(
                gate_status, official_records
            ) > official_run_quality_key(best_candidate["official_gate_status"], best_candidate["records"]):
                best_candidate = candidate_payload
            if gate_status["passed"]:
                break

        assert best_candidate is not None
        selected_planner = str(best_candidate["planner"])
        final_official_run = Path(best_candidate["official_run_dir"])
        final_official_records = list(best_candidate["records"])
        final_gate_status = dict(best_candidate["official_gate_status"])
        retry_metadata = dict(best_candidate["official_retry"])

        status.update(
            {
                "stage": "official_complete",
                "official_run_dir": str(final_official_run),
                "official_gate_status": final_gate_status,
                "official_retry": retry_metadata,
                "official_candidates": [
                    {
                        "planner": candidate["planner"],
                        "official_run_dir": candidate["official_run_dir"],
                        "official_gate_status": candidate["official_gate_status"],
                        "official_retry": candidate["official_retry"],
                    }
                    for candidate in candidate_runs
                ],
                "selected_planner": selected_planner,
            }
        )
        write_status(status_file, status)

        comparison_materialized = materialize_suite_config(
            comparison_config,
            configs_dir / "paper_comparison_materialized.yaml",
            planners=[DEFAULT_BASELINE, selected_planner],
            render_enabled=False,
            time_limit_s_by_scale=OFFICIAL_TIME_LIMITS,
        )
        comparison_run_dir = run_suite(comparison_materialized)
        status.update({"stage": "comparison_complete", "comparison_run_dir": str(comparison_run_dir)})
        write_status(status_file, status)

        render_config = normalize_render_config(RenderConfig.from_dict(load_yaml(render_config_path)))
        bundle_output_dir, manifest, bundle_validation = render_curated_bundle(
            final_official_run,
            comparison_run_dir,
            output_dir=bundle_dir,
            config=render_config,
            selected_planner=selected_planner,
            official_gate_status=final_gate_status,
        )

        summary = {
            "rollout_dir": str(rollout_dir),
            "pilot_run_dir": str(pilot_run_dir),
            "official_run_dir": str(final_official_run),
            "comparison_run_dir": str(comparison_run_dir),
            "bundle_dir": str(bundle_output_dir),
            "pilot_selected_planner": pilot_selected_planner,
            "selected_planner": selected_planner,
            "preflight": {
                "font_check": font_check,
                "tests": preflight_tests,
            },
            "pilot_scorecards": pilot_scorecards,
            "official_gate_status": final_gate_status,
            "official_retry": retry_metadata,
            "official_candidates": [
                {
                    "planner": candidate["planner"],
                    "official_run_dir": candidate["official_run_dir"],
                    "official_gate_status": candidate["official_gate_status"],
                    "official_retry": candidate["official_retry"],
                }
                for candidate in candidate_runs
            ],
            "bundle_validation": bundle_validation,
            "manifest_path": str(bundle_output_dir / "paper_bundle_manifest.json"),
        }
        dump_json(summary, rollout_dir / "paper_rollout_summary.json")
        status.update(
            {
                "stage": "completed",
                "bundle_dir": str(bundle_output_dir),
                "bundle_validation": bundle_validation,
                "manifest_path": str(bundle_output_dir / "paper_bundle_manifest.json"),
            }
        )
        write_status(status_file, status)
        return summary
    except Exception as exc:
        summary["error"] = {"type": type(exc).__name__, "message": str(exc)}
        dump_json(summary, rollout_dir / "paper_rollout_summary.json")
        status.update({"stage": "failed", "error": summary["error"]})
        write_status(status_file, status)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the detached paper rollout for 4/6/8/10 robots.")
    parser.add_argument("--root-dir", default=".", help="Repository root")
    parser.add_argument("--rollout-dir", required=True, help="Output directory for rollout metadata and curated bundle")
    parser.add_argument("--pilot-config", default="configs/suites/paper_pilot_4_6_8_10.yaml")
    parser.add_argument("--official-config", default="configs/suites/paper_best_4_6_8_10.yaml")
    parser.add_argument("--comparison-config", default="configs/suites/paper_comparison_4_6_8_10.yaml")
    parser.add_argument("--render-config", default="configs/render/paper_4_6_8_10.yaml")
    parser.add_argument("--status-file", help="Optional JSON status file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_rollout(
        root_dir=Path(args.root_dir).resolve(),
        rollout_dir=Path(args.rollout_dir).resolve(),
        pilot_config=Path(args.pilot_config).resolve(),
        official_config=Path(args.official_config).resolve(),
        comparison_config=Path(args.comparison_config).resolve(),
        render_config_path=Path(args.render_config).resolve(),
        status_file=Path(args.status_file).resolve() if args.status_file else None,
    )
    print(f"Paper rollout complete: {summary['rollout_dir']}")
    print(f"Selected planner: {summary['selected_planner']}")
    print(f"Official run: {summary['official_run_dir']}")
    print(f"Comparison run: {summary['comparison_run_dir']}")
    print(f"Curated bundle: {summary['bundle_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
