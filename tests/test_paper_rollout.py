from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from cc_mapf.model import RenderConfig
from cc_mapf.paper_rollout import (
    choose_peak_motion_timestep,
    compute_density_matrix,
    hotspot_mask,
    render_curated_bundle,
    select_compare_pairs,
    select_hardest_solved_records,
    select_hero_records,
    select_planner_winner,
    validate_curated_bundle,
)
from cc_mapf.utils import dump_json, load_yaml


def make_record(
    *,
    instance: str,
    family: str,
    planner: str,
    scale: str,
    seed: int,
    makespan: int = 12,
    runtime_s: float = 1.0,
    solved: bool = True,
) -> dict[str, object]:
    width, height = scale.split("_")[0].split("x")
    agent_count = int(scale.split("_")[1].replace("a", ""))
    return {
        "instance": instance,
        "family": family,
        "planner": planner,
        "scale": scale,
        "seed": seed,
        "planner_status": "solved" if solved else "timeout",
        "valid": solved,
        "solved": solved,
        "has_plan": True,
        "makespan": makespan,
        "sum_of_costs": makespan * agent_count,
        "runtime_s": runtime_s,
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
    }


def write_plan_payload(run_dir: Path, record: dict[str, object]) -> None:
    agent_ids = [agent["id"] for agent in record["instance_data"]["agents"]]  # type: ignore[index]
    states = []
    for step in range(4):
        states.append({agent_id: [idx, step] for idx, agent_id in enumerate(agent_ids, start=1)})
    payload = {
        "planner": record["planner"],
        "instance": record["instance"],
        "status": record["planner_status"],
        "plan": {agent_id: [[idx, step] for step in range(4)] for idx, agent_id in enumerate(agent_ids, start=1)},
        "states": states,
        "validation": {
            "valid": True,
            "makespan": 3,
            "sum_of_costs": 16,
            "vertex_conflicts": [],
            "swap_conflicts": [],
            "connectivity_failures": [],
            "move_failures": [],
            "missing_paths": [],
        },
        "planner_result": {"metadata": {}},
    }
    target = run_dir / str(record["plan_file"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload), encoding="utf-8")
    validation_target = run_dir / str(record["validation_file"])
    validation_target.parent.mkdir(parents=True, exist_ok=True)
    validation_target.write_text(json.dumps(payload["validation"]), encoding="utf-8")


def test_paper_render_config_parses_strict_budgeted_defaults() -> None:
    config = RenderConfig.from_dict(load_yaml("configs/render/paper_4_6_8_10.yaml"))
    assert config.effective_font_family() == "CMU Serif"
    assert config.theme == "academic"
    assert config.asset_budget_png == 8
    assert config.asset_budget_gif == 20
    assert config.png_bundle_mode == "analysis_deck"
    assert config.final_export_only is True


def test_select_planner_winner_uses_success_then_timeout_then_runtime_then_cost() -> None:
    records = [
        make_record(instance="a1", family="open", planner="connected_step", scale="16x16_4a", seed=1, runtime_s=5.0),
        make_record(instance="a2", family="open", planner="connected_step", scale="20x20_6a", seed=1, solved=False),
        make_record(instance="b1", family="open", planner="windowed_cc", scale="16x16_4a", seed=1, runtime_s=3.0),
        make_record(instance="b2", family="open", planner="windowed_cc", scale="20x20_6a", seed=1, runtime_s=4.0),
        make_record(instance="c1", family="open", planner="enhanced_connected_step", scale="16x16_4a", seed=1, runtime_s=2.0),
        make_record(instance="c2", family="open", planner="enhanced_connected_step", scale="20x20_6a", seed=1, runtime_s=2.5),
    ]
    winner, scorecards = select_planner_winner(records, ["connected_step", "windowed_cc", "enhanced_connected_step"])
    assert winner == "enhanced_connected_step"
    assert scorecards[0]["planner"] == "enhanced_connected_step"


def test_select_hero_records_prefers_median_makespan_then_runtime_then_seed() -> None:
    records = [
        make_record(instance="open_s1", family="open", planner="connected_step", scale="16x16_4a", seed=1, makespan=10, runtime_s=2.0),
        make_record(instance="open_s2", family="open", planner="connected_step", scale="16x16_4a", seed=2, makespan=12, runtime_s=3.0),
        make_record(instance="open_s3", family="open", planner="connected_step", scale="16x16_4a", seed=3, makespan=12, runtime_s=1.5),
    ]
    for family in ["corridor", "warehouse", "formation_shift"]:
        for scale in ["16x16_4a", "20x20_6a", "24x24_8a", "28x28_10a"]:
            records.append(make_record(instance=f"{family}_{scale}", family=family, planner="connected_step", scale=scale, seed=1))
    for scale in ["20x20_6a", "24x24_8a", "28x28_10a"]:
        records.append(make_record(instance=f"open_{scale}", family="open", planner="connected_step", scale=scale, seed=1))
    heroes = select_hero_records(records)
    assert heroes[("open", "16x16_4a")]["instance"] == "open_s3"


def test_select_compare_pairs_falls_back_from_hardest_scale() -> None:
    records = [
        make_record(instance="open_8a_b", family="open", planner="prioritized_cc", scale="24x24_8a", seed=1),
        make_record(instance="open_8a_w", family="open", planner="connected_step", scale="24x24_8a", seed=1),
    ]
    for family in ["corridor", "warehouse", "formation_shift"]:
        records.extend(
            [
                make_record(instance=f"{family}_10a_b", family=family, planner="prioritized_cc", scale="28x28_10a", seed=1),
                make_record(instance=f"{family}_10a_w", family=family, planner="connected_step", scale="28x28_10a", seed=1),
            ]
        )
    pairs = select_compare_pairs(records, winner_planner="connected_step", baseline_planner="prioritized_cc")
    assert pairs["open"][1]["scale"] == "24x24_8a"
    assert pairs["warehouse"][1]["scale"] == "28x28_10a"


def test_choose_peak_motion_timestep_prefers_high_motion_then_midpoint() -> None:
    states = [
        {"r1": (0, 0), "r2": (1, 0)},
        {"r1": (1, 0), "r2": (2, 0)},
        {"r1": (1, 0), "r2": (2, 0)},
        {"r1": (2, 0), "r2": (2, 0)},
    ]
    assert choose_peak_motion_timestep(states) == 0


def test_validate_curated_bundle_requires_budgeted_png_and_gif_counts(tmp_path: Path) -> None:
    config = RenderConfig.from_dict(load_yaml("configs/render/paper_4_6_8_10.yaml"))
    for index in range(config.asset_budget_png):
        (tmp_path / f"asset_{index}.png").write_text("x", encoding="utf-8")
    for index in range(config.asset_budget_gif):
        (tmp_path / f"asset_{index}.gif").write_text("x", encoding="utf-8")
    validation = validate_curated_bundle(tmp_path, config=config)
    assert validation["passed"] is True
    (tmp_path / "extra.png").write_text("x", encoding="utf-8")
    validation = validate_curated_bundle(tmp_path, config=config)
    assert validation["passed"] is False


def test_compute_density_and_hotspot_mask_are_stable_for_sparse_tracks() -> None:
    states = [
        {"r01": (1, 0), "r02": (2, 0), "r03": (3, 0), "r04": (4, 0)},
        {"r01": (1, 1), "r02": (2, 1), "r03": (3, 1), "r04": (4, 1)},
        {"r01": (1, 2), "r02": (2, 2), "r03": (3, 2), "r04": (4, 2)},
        {"r01": (1, 2), "r02": (2, 2), "r03": (3, 2), "r04": (4, 2)},
    ]
    record = make_record(instance="open_16x16_4a_s01", family="open", planner="connected_step", scale="16x16_4a", seed=1)
    from cc_mapf.model import Instance

    density = compute_density_matrix(Instance.from_dict(record["instance_data"]), states)  # type: ignore[arg-type]
    mask = hotspot_mask(density, percentile=85.0)
    assert density.shape == (16, 16)
    assert float(density.max()) == 1.0
    assert mask.shape == density.shape
    assert np.count_nonzero(mask) > 0


def test_select_hardest_solved_records_prefers_hardest_available_scale_then_median_tiebreak() -> None:
    records = [
        make_record(instance="open_24_s1", family="open", planner="connected_step", scale="24x24_8a", seed=1, makespan=12, runtime_s=3.0),
        make_record(instance="open_24_s2", family="open", planner="connected_step", scale="24x24_8a", seed=2, makespan=10, runtime_s=2.0),
        make_record(instance="open_20_s1", family="open", planner="connected_step", scale="20x20_6a", seed=1, makespan=8, runtime_s=1.0),
    ]
    for family in ["corridor", "warehouse", "formation_shift"]:
        records.append(make_record(instance=f"{family}_28", family=family, planner="connected_step", scale="28x28_10a", seed=1))
    selected = select_hardest_solved_records(records)
    assert selected["open"]["scale"] == "24x24_8a"
    assert selected["open"]["instance"] == "open_24_s2"


def test_render_curated_bundle_creates_exact_asset_budget_and_manifest(tmp_path: Path) -> None:
    official_run = tmp_path / "official_run"
    comparison_run = tmp_path / "comparison_run"
    official_run.mkdir()
    comparison_run.mkdir()

    official_records = []
    for family in ["open", "corridor", "warehouse", "formation_shift"]:
        for scale in ["16x16_4a", "20x20_6a", "24x24_8a", "28x28_10a"]:
            record = make_record(
                instance=f"{family}_{scale}_s01",
                family=family,
                planner="connected_step",
                scale=scale,
                seed=1,
            )
            official_records.append(record)
            write_plan_payload(official_run, record)
    dump_json(
        {
            "run_id": "official_run",
            "records": official_records,
            "render_config": RenderConfig().to_dict(),
        },
        official_run / "results.json",
    )

    comparison_records = []
    for family in ["open", "corridor", "warehouse", "formation_shift"]:
        for planner in ["prioritized_cc", "connected_step"]:
            record = make_record(
                instance=f"{family}_28x28_10a_{planner}",
                family=family,
                planner=planner,
                scale="28x28_10a",
                seed=1,
                runtime_s=2.0 if planner == "connected_step" else 1.0,
            )
            comparison_records.append(record)
            write_plan_payload(comparison_run, record)
    dump_json(
        {
            "run_id": "comparison_run",
            "records": comparison_records,
            "render_config": RenderConfig().to_dict(),
        },
        comparison_run / "results.json",
    )

    bundle_dir, manifest, validation = render_curated_bundle(
        official_run,
        comparison_run,
        output_dir=tmp_path / "bundle",
        config=RenderConfig.from_dict(load_yaml("configs/render/paper_4_6_8_10.yaml")),
        selected_planner="connected_step",
        official_gate_status={"passed": True},
    )

    assert validation["passed"] is True
    assert len(list(bundle_dir.rglob("*.png"))) == 8
    assert len(list(bundle_dir.rglob("*.gif"))) == 20
    manifest_payload = json.loads((bundle_dir / "paper_bundle_manifest.json").read_text(encoding="utf-8"))
    assert manifest_payload["metadata"]["selected_planner"] == "connected_step"
    assert "png/hero__open__16x16_4a.png" not in manifest_payload["sources"]
    assert manifest_payload["sources"]["png/flow-atlas.png"]["kind"] == "map_analysis_png"
    assert manifest_payload["sources"]["png/bottleneck-atlas.png"]["kind"] == "map_analysis_png"
    assert manifest_payload["metadata"]["assets"]["png"] == [
        "png/success-rate-heatmap.png",
        "png/runtime-distribution.png",
        "png/makespan-distribution.png",
        "png/comparison-summary.png",
        "png/connectivity-rejection-heatmap.png",
        "png/runtime-success-scatter.png",
        "png/flow-atlas.png",
        "png/bottleneck-atlas.png",
    ]
    assert manifest.sources


def test_detached_script_exposes_expected_meta_contract() -> None:
    for script_name in [
        "scripts/run/run_paper_4_6_8_10_detached.sh",
        "scripts/run/run_paper_rerender_analysis_deck_detached.sh",
    ]:
        script = Path(script_name).read_text(encoding="utf-8")
        assert "tmux new-session" in script
        for field in ["BUNDLE_DIR", "ROLLOUT_STATUS"]:
            assert field in script
