from __future__ import annotations

from cc_mapf.environment import neighbors
from cc_mapf.model import AgentSpec, ConnectivitySpec, GridMap, Instance
from cc_mapf.validation import connectivity_components, validate_plan


def test_neighbors_respect_bounds_and_obstacles() -> None:
    grid = GridMap(width=4, height=4, obstacles={(1, 1)})
    result = set(neighbors(grid, (1, 0), include_wait=True))
    assert (1, 1) not in result
    assert (1, 0) in result
    assert (0, 0) in result
    assert (2, 0) in result


def test_connectivity_components_split_disconnected_team() -> None:
    components = connectivity_components({"r1": (1, 1), "r2": (1, 2), "r3": (3, 3)})
    assert sorted(components) == [["r1", "r2"], ["r3"]]


def test_connectivity_components_honor_radius() -> None:
    components = connectivity_components({"r1": (1, 1), "r2": (3, 1), "r3": (6, 1)}, radius=2)
    assert sorted(components) == [["r1", "r2"], ["r3"]]


def test_validate_plan_flags_swap_failure() -> None:
    instance = Instance(
        name="swap_only",
        grid=GridMap(width=5, height=5, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (2, 1)),
            AgentSpec("r2", (2, 1), (1, 1)),
            AgentSpec("r3", (1, 2), (1, 2)),
        ],
        connectivity=ConnectivitySpec(),
    )
    plan = {
        "r1": [(1, 1), (2, 1)],
        "r2": [(2, 1), (1, 1)],
        "r3": [(1, 2), (1, 2)],
    }
    validation = validate_plan(instance, plan)
    assert not validation.valid
    assert len(validation.swap_conflicts) == 1


def test_validate_plan_flags_connectivity_failure() -> None:
    instance = Instance(
        name="disconnect_only",
        grid=GridMap(width=6, height=6, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (1, 1)),
            AgentSpec("r2", (2, 1), (2, 1)),
            AgentSpec("r3", (3, 1), (4, 1)),
        ],
        connectivity=ConnectivitySpec(),
    )
    plan = {
        "r1": [(1, 1), (1, 1)],
        "r2": [(2, 1), (2, 1)],
        "r3": [(3, 1), (4, 1)],
    }
    validation = validate_plan(instance, plan)
    assert not validation.valid
    assert len(validation.connectivity_failures) >= 1


def test_validate_plan_honors_instance_connectivity_radius() -> None:
    instance = Instance(
        name="radius_connected",
        grid=GridMap(width=7, height=7, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (1, 1)),
            AgentSpec("r2", (3, 1), (3, 1)),
        ],
        connectivity=ConnectivitySpec(radius=2),
    )
    plan = {
        "r1": [(1, 1)],
        "r2": [(3, 1)],
    }
    validation = validate_plan(instance, plan)
    assert validation.valid
