from __future__ import annotations

from cc_mapf.model import AgentSpec, ConnectivitySpec, GridMap, Instance
from cc_mapf.planners import build_planner
from cc_mapf.validation import validate_plan


def trivial_shift_instance() -> Instance:
    return Instance(
        name="trivial_shift",
        grid=GridMap(6, 6, set()),
        agents=[
            AgentSpec("r1", (1, 1), (2, 1)),
            AgentSpec("r2", (1, 2), (2, 2)),
        ],
        connectivity=ConnectivitySpec(),
    )


def block_shift_instance() -> Instance:
    return Instance(
        name="block_shift",
        grid=GridMap(8, 8, set()),
        agents=[
            AgentSpec("r01", (1, 1), (3, 1)),
            AgentSpec("r02", (1, 2), (3, 2)),
            AgentSpec("r03", (2, 1), (4, 1)),
            AgentSpec("r04", (2, 2), (4, 2)),
        ],
        connectivity=ConnectivitySpec(),
    )


def connectivity_challenge_instance() -> Instance:
    return Instance(
        name="challenge",
        grid=GridMap(
            10,
            10,
            {
                (2, 2),
                (2, 6),
                (3, 4),
                (3, 5),
                (4, 3),
                (5, 4),
                (8, 1),
            },
        ),
        agents=[
            AgentSpec("r01", (1, 8), (6, 4)),
            AgentSpec("r02", (2, 7), (6, 5)),
            AgentSpec("r03", (2, 8), (6, 6)),
            AgentSpec("r04", (2, 9), (7, 5)),
        ],
        connectivity=ConnectivitySpec(),
    )


def test_greedy_solves_trivial_shift_instance() -> None:
    result = build_planner("greedy").solve(trivial_shift_instance(), 5.0)
    validation = validate_plan(trivial_shift_instance(), result.plan)
    assert result.status == "solved"
    assert validation.valid
    assert validation.makespan == 1


def test_prioritized_and_cbs_reach_optimal_makespan_on_block_shift() -> None:
    instance = block_shift_instance()
    for planner_name in ["prioritized", "cbs"]:
        result = build_planner(planner_name).solve(instance, 5.0)
        validation = validate_plan(instance, result.plan)
        assert result.status == "solved"
        assert validation.valid
        assert validation.makespan == 2


def test_connected_step_solves_case_where_cbs_breaks_connectivity() -> None:
    instance = connectivity_challenge_instance()
    cbs_result = build_planner("cbs").solve(instance, 5.0)
    cbs_validation = validate_plan(instance, cbs_result.plan)
    connected_result = build_planner("connected_step").solve(instance, 5.0)
    connected_validation = validate_plan(instance, connected_result.plan)
    assert cbs_result.status == "solved"
    assert not cbs_validation.valid
    assert len(cbs_validation.connectivity_failures) > 0
    assert connected_result.status == "solved"
    assert connected_validation.valid
