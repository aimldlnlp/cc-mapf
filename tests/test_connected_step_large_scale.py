from __future__ import annotations

from time import perf_counter

import pytest

from cc_mapf.generator import generate_instance
from cc_mapf.model import AgentSpec, ConnectivitySpec, GridMap, Instance
from cc_mapf.planners import build_planner
from cc_mapf.planners.connected_step import (
    ConvoyRescueResult,
    PlanningContext,
    attempt_convoy_anchor_rollback_recovery,
    attempt_convoy_local_dead_end_rescue,
    graph_distance_k_neighbors,
    propose_macro_translation,
    should_force_ten_agent_local_refine,
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


def test_convoy_local_dead_end_rescue_aggressive_prefers_individual_shortest_after_replanned_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = Instance(
        name="ten_agent_focus",
        grid=GridMap(8, 8, set()),
        agents=[
            AgentSpec(f"r{i:02d}", (i, 1), (i, 3))
            for i in range(1, 4)
        ],
        connectivity=ConnectivitySpec(radius=1),
    )
    current_state = tuple(agent.start for agent in instance.agents)
    goals = tuple(agent.goal for agent in instance.agents)
    goal_maps = tuple({goal: 0} for goal in goals)
    context = PlanningContext(
        agent_ids=[agent.id for agent in instance.agents],
        start_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        warm_paths=None,
        warm_start_status=None,
        reference_source="replanned_shortest_paths",
        reference_makespan=4,
    )
    seen: dict[str, str | None] = {"preferred_first": None}

    def fake_portfolio(**kwargs):
        seen["preferred_first"] = kwargs.get("preferred_first")
        return []

    monkeypatch.setattr(
        "cc_mapf.planners.connected_step.build_reference_portfolio",
        fake_portfolio,
    )

    rescue = attempt_convoy_local_dead_end_rescue(
        instance=instance,
        current_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        agent_ids=context.agent_ids,
        active_context=context,
        deadline=perf_counter() + 2.0,
        aggressive=True,
    )

    assert rescue.next_state is None
    assert seen["preferred_first"] == "individual_shortest_paths"


def test_anchor_rollback_recovery_returns_progress_when_anchor_rescue_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = Instance(
        name="anchor_recovery",
        grid=GridMap(8, 8, set()),
        agents=[
            AgentSpec(f"r{i:02d}", (i, 1), (i, 3))
            for i in range(1, 4)
        ],
        connectivity=ConnectivitySpec(radius=1),
    )
    anchor_state = tuple(agent.start for agent in instance.agents)
    next_state = tuple((cell[0], cell[1] + 1) for cell in anchor_state)
    goals = tuple(agent.goal for agent in instance.agents)
    goal_maps = tuple({goal: 0} for goal in goals)
    context = PlanningContext(
        agent_ids=[agent.id for agent in instance.agents],
        start_state=anchor_state,
        goals=goals,
        goal_maps=goal_maps,
        warm_paths=None,
        warm_start_status=None,
        reference_source="replanned_shortest_paths",
        reference_makespan=4,
    )

    def fake_rescue(**kwargs):
        return ConvoyRescueResult(
            context=context,
            next_state=next_state,
            source_attempts=3,
            source_successes=1,
        )

    monkeypatch.setattr(
        "cc_mapf.planners.connected_step.attempt_convoy_local_dead_end_rescue",
        fake_rescue,
    )

    rescue = attempt_convoy_anchor_rollback_recovery(
        instance=instance,
        anchor_state=anchor_state,
        goals=goals,
        goal_maps=goal_maps,
        agent_ids=context.agent_ids,
        active_context=context,
        deadline=perf_counter() + 2.0,
        aggressive=True,
    )

    assert rescue.context is context
    assert rescue.next_state == next_state


def test_ten_agent_recovery_forces_local_refine_after_transport_streak() -> None:
    assert should_force_ten_agent_local_refine(
        ten_agent_recovery=True,
        local_refine_burst_remaining=0,
        transport_steps=4,
        no_progress_streak=0,
    )
    assert should_force_ten_agent_local_refine(
        ten_agent_recovery=True,
        local_refine_burst_remaining=0,
        transport_steps=3,
        no_progress_streak=2,
    )
    assert not should_force_ten_agent_local_refine(
        ten_agent_recovery=True,
        local_refine_burst_remaining=1,
        transport_steps=4,
        no_progress_streak=2,
    )
    assert not should_force_ten_agent_local_refine(
        ten_agent_recovery=False,
        local_refine_burst_remaining=0,
        transport_steps=4,
        no_progress_streak=2,
    )
