from __future__ import annotations

import json
from pathlib import Path

from cc_mapf.model import RenderConfig
from cc_mapf.render import render_paper_gallery, select_hero_records
from cc_mapf.utils import dump_json, load_yaml


def make_record(
    *,
    instance: str,
    family: str,
    planner: str,
    scale: str,
    seed: int,
    solved: bool = True,
) -> dict:
    width, height = scale.split("_")[0].split("x")
    agent_count = int(scale.split("_")[1].replace("a", ""))
    return {
        "instance": instance,
        "family": family,
        "planner": planner,
        "scale": scale,
        "seed": seed,
        "planner_status": "solved" if solved else "failed",
        "valid": solved,
        "solved": solved,
        "has_plan": True,
        "makespan": 8,
        "sum_of_costs": 32,
        "runtime_s": 0.5,
        "expanded_nodes": 10,
        "connectivity_rejections": 2,
        "failure_reason": "" if solved else "timeout",
        "plan_file": f"plans/{planner}__{instance}.json",
        "validation_file": f"validation/{planner}__{instance}.json",
        "instance_file": f"instances/{instance}.yaml",
        "instance_data": {
            "name": instance,
            "grid": {"width": int(width), "height": int(height), "obstacles": []},
            "agents": [
                {"id": f"r{i:02d}", "start": [i, 0], "goal": [i, 2]}
                for i in range(1, agent_count + 1)
            ],
            "connectivity": {"mode": "adjacency", "radius": 1},
            "metadata": {"family": family, "seed": seed, "scale": scale},
        },
        "reference_source": "connected_step",
        "reference_portfolio_source": "connected_step",
        "reference_budget_s": 0.5,
        "reference_attempt_sequence": [],
        "reference_rebuilds": 0,
        "reference_execution_policy": "connected_fallback",
        "window_mode": "local_window",
        "window_failures": 0,
        "reference_prefix_steps": 0,
        "local_success_windows": 0,
        "fallback_windows": 0,
        "fallback_progress_resets": 0,
        "guide_bridge_attempts": 0,
        "guide_bridge_successes": 0,
        "guide_bridge_max_offset": 0,
        "guide_bridge_progress_resets": 0,
        "guide_frontier_shrinks": 0,
        "guide_abandonments": 0,
        "executable_recovery_attempts": 1 if planner == "windowed_cc" else 0,
        "executable_recovery_successes": 1 if planner == "windowed_cc" else 0,
        "executable_recovery_source": "connected_step" if planner == "windowed_cc" else "",
        "stall_recovery_uses": 0,
        "stall_exit_reason": "",
        "fallback_progress_mode": "none",
    }


def write_plan_payload(run_dir: Path, record: dict) -> None:
    agent_ids = [agent["id"] for agent in record["instance_data"]["agents"]]
    states = []
    for t in range(3):
        states.append({agent_id: [idx, t] for idx, agent_id in enumerate(agent_ids, start=1)})
    payload = {
        "planner": record["planner"],
        "instance": record["instance"],
        "status": record["planner_status"],
        "plan": {agent_id: [[idx, step] for step in range(3)] for idx, agent_id in enumerate(agent_ids, start=1)},
        "states": states,
        "validation": {"valid": True, "makespan": 2, "sum_of_costs": 12, "vertex_conflicts": [], "swap_conflicts": [], "connectivity_failures": [], "move_failures": [], "missing_paths": []},
        "planner_result": {"metadata": {"progress_timeline": [], "executable_recovery_successes": record["executable_recovery_successes"]}},
    }
    target = run_dir / record["plan_file"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    validation_target = run_dir / record["validation_file"]
    validation_target.parent.mkdir(parents=True, exist_ok=True)
    validation_target.write_text(json.dumps(payload["validation"]), encoding="utf-8")


def test_visual_suite_config_supports_4_6_8_10_12() -> None:
    suite = load_yaml("configs/suites/visual_paper_gallery.yaml")
    scales = [scale["agents"] for scale in suite["scales"]]
    assert scales == [4, 6, 8, 10, 12]


def test_paper_gallery_render_config_parses_clean_academic_defaults() -> None:
    config = RenderConfig.from_dict(load_yaml("configs/render/paper_gallery.yaml"))
    assert config.font_family == "CMU Serif"
    assert config.theme == "academic"
    assert config.palette_preset == "academic"
    assert config.dpi == 220
    assert config.gif_fps == 6


def test_select_hero_records_preserves_one_per_family() -> None:
    records = [
        make_record(instance="open_a", family="open", planner="connected_step", scale="24x24_8a", seed=1),
        make_record(instance="open_b", family="open", planner="windowed_cc", scale="20x20_6a", seed=1),
        make_record(instance="warehouse_a", family="warehouse", planner="connected_step", scale="32x32_12a", seed=1),
    ]
    heroes = select_hero_records(records)
    assert set(heroes) == {"open", "warehouse"}
    assert heroes["open"]["planner"] == "connected_step"


def test_render_paper_gallery_creates_structured_outputs_and_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    records = [
        make_record(instance="open_16x16_4a_s01", family="open", planner="connected_step", scale="16x16_4a", seed=1),
        make_record(instance="open_16x16_4a_s01", family="open", planner="prioritized_cc", scale="16x16_4a", seed=1),
        make_record(instance="warehouse_20x20_6a_s01", family="warehouse", planner="windowed_cc", scale="20x20_6a", seed=1),
    ]
    for record in records:
        write_plan_payload(run_dir, record)
    results = {
        "run_id": "demo_run",
        "records": records,
        "render_config": RenderConfig(theme="academic", palette_preset="academic").to_dict(),
    }
    dump_json(results, run_dir / "results.json")

    gallery_dir, manifest = render_paper_gallery(run_dir)

    assert (gallery_dir / "analysis" / "runtime-success-scatter.png").exists()
    assert (gallery_dir / "analysis" / "makespan-boxplot.png").exists()
    assert (gallery_dir / "analysis" / "connectivity-rejection-heatmap.png").exists()
    assert (gallery_dir / "analysis" / "solved-count-heatmap.png").exists()
    assert (gallery_dir / "contact_sheets" / "open__16x16-4a.png").exists()
    assert (gallery_dir / "png" / "open" / "16x16-4a" / "connected-step" / "open-16x16-4a-s01__start.png").exists()
    assert (gallery_dir / "gif" / "open" / "16x16-4a" / "connected-step" / "open-16x16-4a-s01.gif").exists()
    assert (gallery_dir / "gif" / "open" / "16x16-4a" / "seed-01__compare.gif").exists()
    manifest_path = gallery_dir / "paper_gallery_manifest.json"
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "demo_run"
    assert payload["metadata"]["hero_records"]
    assert manifest.sources
