from __future__ import annotations

from cc_mapf.generator import generate_instance
from cc_mapf.model import GridMap
from cc_mapf.planners import build_planner
from cc_mapf.planners.connected_step import (
    graph_distance_k_neighbors,
    propose_macro_translation,
    team_radius,
)
from cc_mapf.validation import validate_plan


def test_team_radius_and_graph_distance_helpers() -> None:
    state = ((1, 1), (2, 1), (3, 1), (3, 2))
    assert team_radius(state) == 1.5
    assert graph_distance_k_neighbors(state, {2}, 1) == {1, 2, 3}
    assert graph_distance_k_neighbors(state, {2}, 2) == {0, 1, 2, 3}


def test_propose_macro_translation_identifies_blockers_and_support() -> None:
    grid = GridMap(8, 6, {(4, 1)})
    state = ((1, 1), (2, 1), (3, 1), (3, 2))
    goals = ((5, 1), (5, 2), (5, 3), (5, 4))
    goal_maps = tuple({goal: 0} for goal in goals)
    proposal = propose_macro_translation(
        grid=grid,
        state=state,
        goals=goals,
        goal_maps=goal_maps,
        delta=(1, 0),
        max_active_subset=6,
    )
    assert proposal is not None
    assert proposal.blockers == frozenset({0, 1, 2})
    assert 3 in proposal.support_agents
    assert set(proposal.active_subset) == {0, 1, 2, 3}


def test_connected_step_uses_convoy_macro_beam_on_large_instances() -> None:
    instance = generate_instance("formation_shift", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    for key in [
        "reference_source",
        "transport_steps",
        "local_refine_steps",
        "macro_expansions",
        "macro_successes",
        "cycle_break_invocations",
        "escape_move_invocations",
        "recovery_successes",
        "local_dead_end_rescues",
        "source_portfolio_attempts",
        "source_portfolio_successes",
        "basin_restart_source",
        "diversification_bursts",
        "basin_restarts",
        "reference_switch_count",
        "active_subset_mean",
        "best_progress_step",
        "steps_since_last_progress",
        "stall_exit_reason",
    ]:
        assert key in result.metadata
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid


def test_connected_step_solves_representative_large_formation_case() -> None:
    instance = generate_instance("formation_shift", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 12.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    assert result.status == "solved"
    assert result.plan is not None
    assert validate_plan(instance, result.plan).valid
