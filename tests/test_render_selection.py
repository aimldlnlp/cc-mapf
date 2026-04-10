from __future__ import annotations

from cc_mapf.render import select_pair, select_record


def make_record(
    *,
    instance: str,
    family: str,
    planner: str,
    scale: str,
    seed: int,
    agents: int,
) -> dict[str, object]:
    width, height = scale.split("_")[0].split("x")
    return {
        "instance": instance,
        "family": family,
        "planner": planner,
        "scale": scale,
        "seed": seed,
        "has_plan": True,
        "makespan": 20,
        "connectivity_failure_count": 0,
        "instance_data": {
            "name": instance,
            "grid": {"width": int(width), "height": int(height), "obstacles": []},
            "agents": [
                {"id": f"r{i}", "start": [i, 0], "goal": [i, 1]}
                for i in range(agents)
            ],
        },
    }


def test_select_record_prefers_dense_solved_record() -> None:
    records = [
        make_record(instance="open_small", family="open", planner="connected_step", scale="16x16_4a", seed=1, agents=4),
        make_record(instance="open_medium", family="open", planner="connected_step", scale="24x24_8a", seed=1, agents=8),
        make_record(instance="open_large", family="open", planner="connected_step", scale="32x32_12a", seed=1, agents=12),
    ]
    selected = select_record(records, family="open", planner="connected_step", min_agents=8)
    assert selected is not None
    assert selected["instance"] == "open_large"


def test_select_pair_falls_back_to_dense_connected_pair_without_baseline() -> None:
    records = [
        make_record(instance="warehouse_large_a", family="warehouse", planner="connected_step", scale="32x32_12a", seed=1, agents=12),
        make_record(instance="warehouse_large_b", family="warehouse", planner="connected_step", scale="32x32_12a", seed=2, agents=12),
        make_record(instance="warehouse_medium", family="warehouse", planner="connected_step", scale="24x24_8a", seed=3, agents=8),
    ]
    pair = select_pair(records, family="warehouse", min_agents=8)
    assert pair is not None
    left, right = pair
    assert left["planner"] == "connected_step"
    assert right["planner"] == "connected_step"
    assert left["scale"] == "32x32_12a"
    assert right["scale"] == "32x32_12a"
