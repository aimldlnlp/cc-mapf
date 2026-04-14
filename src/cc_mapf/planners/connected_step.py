from __future__ import annotations

import heapq
from collections import deque
from dataclasses import dataclass
from itertools import count
from time import perf_counter
from typing import Callable

from ..environment import DIRECTIONS4, add_cell, bfs_shortest_path, in_bounds, is_free, manhattan, neighbors
from ..model import AgentSpec, Cell, Instance, PlannerResult
from .prioritized import PrioritizedPlanner

JointState = tuple[Cell, ...]
BIG_DISTANCE = 10**9
REFERENCE_MODES = ("prioritized", "individual_shortest_paths", "replanned_shortest_paths")


@dataclass(frozen=True)
class PlanningContext:
    agent_ids: list[str]
    start_state: JointState
    goals: JointState
    goal_maps: tuple[dict[Cell, int], ...]
    warm_paths: tuple[tuple[Cell, ...], ...] | None
    warm_start_status: str | None
    reference_source: str
    reference_makespan: int


@dataclass(frozen=True)
class BeamNode:
    state: JointState
    prefix: tuple[JointState, ...]
    agents_at_goal: int
    total_goal_distance: int
    non_progress_total: int
    repeat_total: int
    shape_repeat_total: int
    adjacency_total: int
    mobility_total: int
    reference_deviation_total: int
    wait_total: int


@dataclass
class SearchResult:
    first_state: JointState | None
    prefix: tuple[JointState, ...]
    expanded_nodes: int = 0
    candidate_prunes: int = 0
    disconnected_state_prunes: int = 0


@dataclass(frozen=True)
class WindowRestartCandidate:
    context: PlanningContext
    prefix: tuple[JointState, ...]
    score: tuple[int, ...]
    expanded_nodes: int
    candidate_prunes: int
    disconnected_state_prunes: int


@dataclass(frozen=True)
class MacroProposal:
    delta: Cell
    blockers: frozenset[int]
    support_agents: frozenset[int]
    frozen_targets: tuple[Cell | None, ...]
    active_subset: tuple[int, ...]
    centroid_distance_after: float
    total_goal_distance_after: int


@dataclass
class MacroStepResult:
    next_state: JointState | None
    chosen_delta: Cell | None = None
    expanded_nodes: int = 0
    candidate_prunes: int = 0
    disconnected_state_prunes: int = 0
    macro_expansions: int = 0
    macro_successes: int = 0
    active_subset_total: int = 0
    active_subset_samples: int = 0


@dataclass
class ConvoyRescueResult:
    context: PlanningContext | None
    next_state: JointState | None
    expanded_nodes: int = 0
    candidate_prunes: int = 0
    disconnected_state_prunes: int = 0
    macro_expansions: int = 0
    macro_successes: int = 0
    active_subset_total: int = 0
    active_subset_samples: int = 0
    used_transport: bool = False
    source_attempts: int = 0
    source_successes: int = 0


class ConnectedStepPlanner:
    name = "connected_step"

    def __init__(
        self,
        *,
        initial_reference_mode: str | None = None,
        initial_warm_path_policy: str = "auto",
    ) -> None:
        self.initial_reference_mode = initial_reference_mode
        self.initial_warm_path_policy = initial_warm_path_policy

    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        exact_budget = min(time_limit_s, 10.0)
        if len(instance.agents) <= 4 and instance.grid.width * instance.grid.height <= 256:
            exact_result = connected_joint_a_star(instance, exact_budget)
            populate_default_metadata(exact_result.metadata, mode="exact_joint_astar")
            if exact_result.status == "solved" or exact_result.runtime_s >= time_limit_s:
                return exact_result
            remaining = max(0.1, time_limit_s - exact_result.runtime_s)
            fallback = windowed_beam_solve(
                instance,
                remaining,
                initial_reference_mode=self.initial_reference_mode,
                initial_warm_path_policy=self.initial_warm_path_policy,
            )
            fallback.runtime_s += exact_result.runtime_s
            fallback.expanded_nodes = (fallback.expanded_nodes or 0) + (exact_result.expanded_nodes or 0)
            fallback.connectivity_rejections += exact_result.connectivity_rejections
            fallback.metadata["warm_start_status"] = exact_result.status
            return fallback
        if len(instance.agents) >= 10:
            return convoy_macro_beam_solve(
                instance,
                time_limit_s,
                initial_reference_mode=self.initial_reference_mode,
                initial_warm_path_policy=self.initial_warm_path_policy,
            )
        return windowed_beam_solve(
            instance,
            time_limit_s,
            initial_reference_mode=self.initial_reference_mode,
            initial_warm_path_policy=self.initial_warm_path_policy,
        )


def windowed_beam_solve(
    instance: Instance,
    time_limit_s: float,
    *,
    initial_reference_mode: str | None = None,
    initial_warm_path_policy: str = "auto",
) -> PlannerResult:
    start_time = perf_counter()
    deadline = start_time + time_limit_s
    context = build_planning_context(
        instance,
        time_limit_s,
        large_mode=False,
        preferred_reference_mode=initial_reference_mode,
        warm_path_policy=initial_warm_path_policy,
    )
    active_context = context
    beam_horizon = 5 if len(context.agent_ids) <= 8 else 3
    beam_width = 96 if len(context.agent_ids) <= 8 else 48
    candidate_cap = 3 if len(context.agent_ids) <= 8 else 2
    partial_limit = 64 if len(context.agent_ids) <= 8 else 24
    repair_depth = 2 if len(context.agent_ids) <= 8 else 1
    repair_width = 24 if len(context.agent_ids) <= 8 else 12
    repair_invocations = 0
    restart_invocations = 0
    plateau_restart_invocations = 0
    recovery_successes = 0
    diversification_bursts = 0
    reference_switch_count = 0
    candidate_prunes = 0
    disconnected_state_prunes = 0
    expanded_nodes = 0
    wait_streak = 0
    current_state = context.start_state
    max_steps = (
        2 * (instance.grid.width + instance.grid.height) + 6 * len(context.agent_ids) + context.reference_makespan
        if context.warm_paths is not None
        else 2 * instance.grid.width + 2 * instance.grid.height + 8 * len(context.agent_ids)
    )
    progress_extension = max(beam_horizon * 2, instance.grid.width + instance.grid.height)
    max_extensions = 2
    extensions_used = 0
    restart_step_offset = 0
    states: list[JointState] = [current_state]
    best_total_goal_distance_seen = total_goal_distance(current_state, context.goals, context.goal_maps)
    best_agents_at_goal = count_agents_at_goal(current_state, context.goals)
    best_progress_step = 0
    best_state_index = 0
    plateau_window = max(beam_horizon * 4, len(context.agent_ids) + 6)
    hard_plateau_cap = plateau_window + max(beam_horizon * 4, 12) + density_scaled_plateau_bonus(instance)
    attempted_restart_sources: set[str] = {active_context.reference_source}
    stall_exit_reason = ""
    while len(states) - 1 < max_steps:
        steps_since_last_progress = (len(states) - 1) - best_progress_step
        if perf_counter() - start_time > time_limit_s:
            return build_result(
                status="timeout",
                agent_ids=active_context.agent_ids,
                states=None,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
                repair_invocations=repair_invocations,
                restart_invocations=restart_invocations,
                plateau_restart_invocations=plateau_restart_invocations,
                warm_start_used=active_context.warm_paths is not None,
                warm_start_status=active_context.warm_start_status,
                beam_width=beam_width,
                beam_horizon=beam_horizon,
                mode="windowed_beam",
                reference_source=active_context.reference_source,
                recovery_successes=recovery_successes,
                diversification_bursts=diversification_bursts,
                basin_restarts=0,
                reference_switch_count=reference_switch_count,
                best_progress_step=best_progress_step,
                steps_since_last_progress=steps_since_last_progress,
                stall_exit_reason="deadline",
            )
        if current_state == context.goals:
            return build_result(
                status="solved",
                agent_ids=active_context.agent_ids,
                states=states,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
                repair_invocations=repair_invocations,
                restart_invocations=restart_invocations,
                plateau_restart_invocations=plateau_restart_invocations,
                warm_start_used=active_context.warm_paths is not None,
                warm_start_status=active_context.warm_start_status,
                beam_width=beam_width,
                beam_horizon=beam_horizon,
                mode="windowed_beam",
                reference_source=active_context.reference_source,
                recovery_successes=recovery_successes,
                diversification_bursts=diversification_bursts,
                basin_restarts=0,
                reference_switch_count=reference_switch_count,
                best_progress_step=best_progress_step,
                steps_since_last_progress=steps_since_last_progress,
                stall_exit_reason="",
            )
        current_step = len(states) - 1
        reference_trajectory = build_reference_trajectory(
            grid=instance.grid,
            current_state=current_state,
            goals=context.goals,
            goal_maps=context.goal_maps,
            warm_paths=active_context.warm_paths,
            global_step=max(0, current_step - restart_step_offset),
            horizon=beam_horizon,
            prefer_group_bias=True,
        )
        reference_next = reference_trajectory[1]
        used_reference_fast_path = False
        next_state: JointState | None = None
        if (
            reference_next != current_state
            and total_goal_distance(reference_next, context.goals, context.goal_maps)
            <= total_goal_distance(current_state, context.goals, context.goal_maps)
            and is_valid_joint_transition(instance, current_state, reference_next)
            and is_connected_positions(reference_next)
        ):
            next_state = reference_next
            used_reference_fast_path = True
        else:
            search = search_window(
                instance=instance,
                current_state=current_state,
                goals=context.goals,
                goal_maps=context.goal_maps,
                reference_trajectory=reference_trajectory,
                beam_horizon=beam_horizon,
                beam_width=beam_width,
                candidate_cap=candidate_cap,
                partial_limit=partial_limit,
                deadline=deadline,
                support_agents=None,
            )
            expanded_nodes += search.expanded_nodes
            candidate_prunes += search.candidate_prunes
            disconnected_state_prunes += search.disconnected_state_prunes
            next_state = search.first_state
            if next_state is None:
                repair_invocations += 1
                recent_progress = current_step - best_progress_step <= max(beam_horizon * 2, 6)
                adaptive_repair_depth = repair_depth + int(recent_progress)
                adaptive_repair_width = repair_width + (12 if recent_progress else 0)
                repair = localized_connector_repair(
                    instance=instance,
                    current_state=current_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    reference_trajectory=reference_trajectory,
                    beam_width=adaptive_repair_width,
                    candidate_cap=candidate_cap,
                    depth=adaptive_repair_depth,
                    deadline=deadline,
                )
                expanded_nodes += repair.expanded_nodes
                candidate_prunes += repair.candidate_prunes
                disconnected_state_prunes += repair.disconnected_state_prunes
                next_state = repair.first_state
        if next_state is None:
            if wait_streak < 2 and is_connected_positions(current_state):
                next_state = current_state
                wait_streak += 1
            else:
                return build_result(
                    status="failed",
                    agent_ids=active_context.agent_ids,
                    states=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    candidate_prunes=candidate_prunes,
                    disconnected_state_prunes=disconnected_state_prunes,
                    repair_invocations=repair_invocations,
                    restart_invocations=restart_invocations,
                    plateau_restart_invocations=plateau_restart_invocations,
                    warm_start_used=active_context.warm_paths is not None,
                    warm_start_status=active_context.warm_start_status,
                    beam_width=beam_width,
                    beam_horizon=beam_horizon,
                    mode="windowed_beam",
                    reference_source=active_context.reference_source,
                    recovery_successes=recovery_successes,
                    diversification_bursts=diversification_bursts,
                    basin_restarts=0,
                    reference_switch_count=reference_switch_count,
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=steps_since_last_progress,
                    stall_exit_reason="dead_end",
                    reason="stalled",
                )
        if not used_reference_fast_path and next_state == current_state:
            wait_streak += 1
        elif next_state != current_state:
            wait_streak = 0
        states.append(next_state)
        current_state = next_state
        current_total_goal_distance = total_goal_distance(current_state, context.goals, context.goal_maps)
        current_agents_at_goal = count_agents_at_goal(current_state, context.goals)
        if current_total_goal_distance < best_total_goal_distance_seen or current_agents_at_goal > best_agents_at_goal:
            best_total_goal_distance_seen = min(best_total_goal_distance_seen, current_total_goal_distance)
            best_agents_at_goal = max(best_agents_at_goal, current_agents_at_goal)
            best_progress_step = len(states) - 1
            best_state_index = len(states) - 1
            attempted_restart_sources = {active_context.reference_source}
            if max_steps - (len(states) - 1) <= beam_horizon + 1 and extensions_used < max_extensions:
                max_steps += progress_extension
                extensions_used += 1
        steps_since_last_progress = (len(states) - 1) - best_progress_step
        remaining_time = max(0.0, deadline - perf_counter())
        plateau_detected = steps_since_last_progress >= plateau_window
        if plateau_detected and remaining_time > 0.2:
            restart_anchor_index = best_state_index if best_state_index < len(states) - 1 else len(states) - 1
            anchor_state = states[restart_anchor_index]
            if plateau_restart_invocations < 3:
                candidate = choose_window_restart_candidate(
                    instance=instance,
                    anchor_state=anchor_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    agent_ids=context.agent_ids,
                    active_source=active_context.reference_source,
                    attempted_sources=attempted_restart_sources,
                    time_limit_s=remaining_time,
                    deadline=deadline,
                    beam_horizon=beam_horizon,
                    beam_width=beam_width,
                    candidate_cap=candidate_cap,
                    partial_limit=partial_limit,
                    diversify=False,
                )
                if candidate is not None:
                    previous_source = active_context.reference_source
                    states = states[: restart_anchor_index + 1] + list(candidate.prefix)
                    current_state = states[-1]
                    active_context = candidate.context
                    expanded_nodes += candidate.expanded_nodes
                    candidate_prunes += candidate.candidate_prunes
                    disconnected_state_prunes += candidate.disconnected_state_prunes
                    restart_step_offset = len(states) - len(candidate.prefix) - 1
                    restart_invocations += 1
                    plateau_restart_invocations += 1
                    recovery_successes += 1
                    reference_switch_count += int(active_context.reference_source != previous_source)
                    attempted_restart_sources.add(active_context.reference_source)
                    if extensions_used < max_extensions:
                        max_steps = max(max_steps, len(states) - 1 + progress_extension)
                        extensions_used += 1
                    wait_streak = 0
                    continue
            if steps_since_last_progress >= hard_plateau_cap - beam_horizon and diversification_bursts < 2:
                candidate = choose_window_restart_candidate(
                    instance=instance,
                    anchor_state=anchor_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    agent_ids=context.agent_ids,
                    active_source=active_context.reference_source,
                    attempted_sources=set(),
                    time_limit_s=remaining_time,
                    deadline=deadline,
                    beam_horizon=beam_horizon + 1,
                    beam_width=beam_width + 32,
                    candidate_cap=min(candidate_cap + 1, 4),
                    partial_limit=partial_limit + 32,
                    diversify=True,
                )
                if candidate is not None:
                    previous_source = active_context.reference_source
                    states = states[: restart_anchor_index + 1] + list(candidate.prefix)
                    current_state = states[-1]
                    active_context = candidate.context
                    expanded_nodes += candidate.expanded_nodes
                    candidate_prunes += candidate.candidate_prunes
                    disconnected_state_prunes += candidate.disconnected_state_prunes
                    restart_step_offset = len(states) - len(candidate.prefix) - 1
                    diversification_bursts += 1
                    recovery_successes += 1
                    reference_switch_count += int(active_context.reference_source != previous_source)
                    attempted_restart_sources = {active_context.reference_source}
                    wait_streak = 0
                    continue
        if steps_since_last_progress >= hard_plateau_cap:
            stall_exit_reason = "plateau_limit"
            return build_result(
                status="failed",
                agent_ids=active_context.agent_ids,
                states=None,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
                repair_invocations=repair_invocations,
                restart_invocations=restart_invocations,
                plateau_restart_invocations=plateau_restart_invocations,
                warm_start_used=active_context.warm_paths is not None,
                warm_start_status=active_context.warm_start_status,
                beam_width=beam_width,
                beam_horizon=beam_horizon,
                mode="windowed_beam",
                reference_source=active_context.reference_source,
                recovery_successes=recovery_successes,
                diversification_bursts=diversification_bursts,
                basin_restarts=0,
                reference_switch_count=reference_switch_count,
                best_progress_step=best_progress_step,
                steps_since_last_progress=steps_since_last_progress,
                stall_exit_reason=stall_exit_reason,
                reason="stalled",
            )
    return build_result(
        status="failed",
        agent_ids=active_context.agent_ids,
        states=None,
        runtime_s=perf_counter() - start_time,
        expanded_nodes=expanded_nodes,
        candidate_prunes=candidate_prunes,
        disconnected_state_prunes=disconnected_state_prunes,
        repair_invocations=repair_invocations,
        restart_invocations=restart_invocations,
        plateau_restart_invocations=plateau_restart_invocations,
        warm_start_used=active_context.warm_paths is not None,
        warm_start_status=active_context.warm_start_status,
        beam_width=beam_width,
        beam_horizon=beam_horizon,
        mode="windowed_beam",
        reference_source=active_context.reference_source,
        recovery_successes=recovery_successes,
        diversification_bursts=diversification_bursts,
        basin_restarts=0,
        reference_switch_count=reference_switch_count,
        best_progress_step=best_progress_step,
        steps_since_last_progress=(len(states) - 1) - best_progress_step,
        stall_exit_reason="step_cap",
        reason="step_cap",
    )


def convoy_macro_beam_solve(
    instance: Instance,
    time_limit_s: float,
    *,
    initial_reference_mode: str | None = None,
    initial_warm_path_policy: str = "auto",
) -> PlannerResult:
    start_time = perf_counter()
    deadline = start_time + time_limit_s
    context = build_planning_context(
        instance,
        time_limit_s,
        large_mode=True,
        preferred_reference_mode=initial_reference_mode,
        warm_path_policy=initial_warm_path_policy,
    )
    source_portfolio_attempts = 0
    source_portfolio_successes = 0
    active_context = context
    current_state = context.start_state
    states: list[JointState] = [current_state]
    expanded_nodes = 0
    candidate_prunes = 0
    disconnected_state_prunes = 0
    repair_invocations = 0
    transport_steps = 0
    local_refine_steps = 0
    macro_expansions = 0
    macro_successes = 0
    cycle_break_invocations = 0
    escape_move_invocations = 0
    recovery_successes = 0
    local_dead_end_rescues = 0
    basin_restarts = 0
    basin_restart_source = ""
    reference_switch_count = 0
    active_subset_total = 0
    active_subset_samples = 0
    last_transport_delta: Cell | None = None
    wait_streak = 0
    best_total_goal_distance_seen = total_goal_distance(current_state, context.goals, context.goal_maps)
    best_centroid_distance_seen = centroid_distance(current_state, context.goals)
    best_agents_at_goal = count_agents_at_goal(current_state, context.goals)
    best_progress_step = 0
    best_state_index = 0
    no_progress_streak = 0
    local_refine_burst_remaining = 0
    recovery_attempts_in_basin = 0
    consecutive_failed_recoveries = 0
    stall_exit_reason = ""
    ten_agent_recovery = len(context.agent_ids) == 10
    ten_agent_focus = ten_agent_recovery
    max_basin_restarts = 5 if ten_agent_focus else 3
    max_steps = max(
        440 if ten_agent_focus else 320,
        context.reference_makespan
        + (5 if ten_agent_focus else 4) * (instance.grid.width + instance.grid.height)
        + (8 if ten_agent_focus else 6) * len(context.agent_ids),
    )
    while len(states) - 1 < max_steps:
        steps_since_last_progress = (len(states) - 1) - best_progress_step
        if perf_counter() > deadline:
            return build_result(
                status="timeout",
                agent_ids=active_context.agent_ids,
                states=None,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
                repair_invocations=repair_invocations,
                restart_invocations=0,
                plateau_restart_invocations=0,
                warm_start_used=active_context.warm_paths is not None,
                warm_start_status=active_context.warm_start_status,
                beam_width=96,
                beam_horizon=5,
                mode="convoy_macro_beam",
                reference_source=active_context.reference_source,
                transport_steps=transport_steps,
                local_refine_steps=local_refine_steps,
                macro_expansions=macro_expansions,
                macro_successes=macro_successes,
                cycle_break_invocations=cycle_break_invocations,
                escape_move_invocations=escape_move_invocations,
                recovery_successes=recovery_successes,
                local_dead_end_rescues=local_dead_end_rescues,
                source_portfolio_attempts=source_portfolio_attempts,
                source_portfolio_successes=source_portfolio_successes,
                basin_restart_source=basin_restart_source,
                diversification_bursts=0,
                basin_restarts=basin_restarts,
                reference_switch_count=reference_switch_count,
                active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
                best_progress_step=best_progress_step,
                steps_since_last_progress=steps_since_last_progress,
                stall_exit_reason="deadline",
            )
        if current_state == context.goals:
            return build_result(
                status="solved",
                agent_ids=active_context.agent_ids,
                states=states,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
                repair_invocations=repair_invocations,
                restart_invocations=0,
                plateau_restart_invocations=0,
                warm_start_used=active_context.warm_paths is not None,
                warm_start_status=active_context.warm_start_status,
                beam_width=96,
                beam_horizon=5,
                mode="convoy_macro_beam",
                reference_source=active_context.reference_source,
                transport_steps=transport_steps,
                local_refine_steps=local_refine_steps,
                macro_expansions=macro_expansions,
                macro_successes=macro_successes,
                cycle_break_invocations=cycle_break_invocations,
                escape_move_invocations=escape_move_invocations,
                recovery_successes=recovery_successes,
                local_dead_end_rescues=local_dead_end_rescues,
                source_portfolio_attempts=source_portfolio_attempts,
                source_portfolio_successes=source_portfolio_successes,
                basin_restart_source=basin_restart_source,
                diversification_bursts=0,
                basin_restarts=basin_restarts,
                reference_switch_count=reference_switch_count,
                active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
                best_progress_step=best_progress_step,
                steps_since_last_progress=steps_since_last_progress,
                stall_exit_reason="",
            )
        reference_trajectory = build_reference_trajectory(
            grid=instance.grid,
            current_state=current_state,
            goals=active_context.goals,
            goal_maps=active_context.goal_maps,
            warm_paths=active_context.warm_paths,
            global_step=len(states) - 1,
            horizon=5,
            prefer_group_bias=False,
        )
        force_cycle_break = no_progress_streak >= (6 if ten_agent_focus else 8) or consecutive_failed_recoveries >= (
            1 if ten_agent_focus else 2
        )
        force_local_refine = should_force_ten_agent_local_refine(
            ten_agent_recovery=ten_agent_recovery,
            local_refine_burst_remaining=local_refine_burst_remaining,
            transport_steps=transport_steps,
            no_progress_streak=no_progress_streak,
        )
        use_transport = (
            not force_local_refine
            and
            local_refine_burst_remaining == 0
            and (centroid_distance(current_state, active_context.goals) > team_radius(current_state) + 2 or force_cycle_break)
        )
        used_local_refine = False
        if use_transport:
            transport = transport_macro_step(
                instance=instance,
                current_state=current_state,
                goals=context.goals,
                goal_maps=context.goal_maps,
                reference_trajectory=reference_trajectory,
                deadline=deadline,
                force_cycle_break=force_cycle_break,
                last_delta=last_transport_delta,
            )
            if force_cycle_break:
                cycle_break_invocations += 1
            expanded_nodes += transport.expanded_nodes
            candidate_prunes += transport.candidate_prunes
            disconnected_state_prunes += transport.disconnected_state_prunes
            macro_expansions += transport.macro_expansions
            macro_successes += transport.macro_successes
            active_subset_total += transport.active_subset_total
            active_subset_samples += transport.active_subset_samples
            next_state = transport.next_state
            if next_state is None and not force_cycle_break:
                cycle_break_invocations += 1
                transport = transport_macro_step(
                    instance=instance,
                    current_state=current_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    reference_trajectory=reference_trajectory,
                    deadline=deadline,
                    force_cycle_break=True,
                    last_delta=last_transport_delta,
                )
                expanded_nodes += transport.expanded_nodes
                candidate_prunes += transport.candidate_prunes
                disconnected_state_prunes += transport.disconnected_state_prunes
                macro_expansions += transport.macro_expansions
                macro_successes += transport.macro_successes
                active_subset_total += transport.active_subset_total
                active_subset_samples += transport.active_subset_samples
                next_state = transport.next_state
            if next_state is None:
                if wait_streak < 2 and is_connected_positions(current_state):
                    next_state = current_state
                    wait_streak += 1
                else:
                    rescue = attempt_convoy_local_dead_end_rescue(
                        instance=instance,
                        current_state=current_state,
                        goals=context.goals,
                        goal_maps=context.goal_maps,
                        agent_ids=context.agent_ids,
                        active_context=active_context,
                        deadline=deadline,
                        aggressive=ten_agent_focus,
                    )
                    source_portfolio_attempts += rescue.source_attempts
                    source_portfolio_successes += rescue.source_successes
                    expanded_nodes += rescue.expanded_nodes
                    candidate_prunes += rescue.candidate_prunes
                    disconnected_state_prunes += rescue.disconnected_state_prunes
                    macro_expansions += rescue.macro_expansions
                    macro_successes += rescue.macro_successes
                    active_subset_total += rescue.active_subset_total
                    active_subset_samples += rescue.active_subset_samples
                    if rescue.next_state is not None and rescue.context is not None:
                        previous_source = active_context.reference_source
                        active_context = rescue.context
                        basin_restart_source = active_context.reference_source
                        basin_restarts += 1
                        reference_switch_count += int(active_context.reference_source != previous_source)
                        local_dead_end_rescues += 1
                        recovery_successes += 1
                        no_progress_streak = 0
                        recovery_attempts_in_basin = 0
                        consecutive_failed_recoveries = 0
                        wait_streak = 0
                        local_refine_burst_remaining = max(local_refine_burst_remaining, 6)
                        states.append(rescue.next_state)
                        current_state = rescue.next_state
                        if rescue.used_transport:
                            transport_steps += 1
                        else:
                            local_refine_steps += 1
                            last_transport_delta = None
                        continue
                    if (
                        ten_agent_focus
                        and best_state_index < len(states) - 1
                        and basin_restarts < max_basin_restarts
                        and deadline - perf_counter() > 1.0
                    ):
                        anchor_rescue = attempt_convoy_anchor_rollback_recovery(
                            instance=instance,
                            anchor_state=states[best_state_index],
                            goals=context.goals,
                            goal_maps=context.goal_maps,
                            agent_ids=context.agent_ids,
                            active_context=active_context,
                            deadline=deadline,
                            aggressive=True,
                        )
                        source_portfolio_attempts += anchor_rescue.source_attempts
                        source_portfolio_successes += anchor_rescue.source_successes
                        expanded_nodes += anchor_rescue.expanded_nodes
                        candidate_prunes += anchor_rescue.candidate_prunes
                        disconnected_state_prunes += anchor_rescue.disconnected_state_prunes
                        macro_expansions += anchor_rescue.macro_expansions
                        macro_successes += anchor_rescue.macro_successes
                        active_subset_total += anchor_rescue.active_subset_total
                        active_subset_samples += anchor_rescue.active_subset_samples
                        if anchor_rescue.next_state is not None and anchor_rescue.context is not None:
                            previous_source = active_context.reference_source
                            active_context = anchor_rescue.context
                            basin_restart_source = active_context.reference_source
                            basin_restarts += 1
                            reference_switch_count += int(active_context.reference_source != previous_source)
                            recovery_successes += 1
                            wait_streak = 0
                            no_progress_streak = 0
                            recovery_attempts_in_basin = 0
                            consecutive_failed_recoveries = 0
                            local_refine_burst_remaining = max(local_refine_burst_remaining, 10)
                            states = states[: best_state_index + 1]
                            states.append(anchor_rescue.next_state)
                            current_state = anchor_rescue.next_state
                            if anchor_rescue.used_transport:
                                transport_steps += 1
                            else:
                                local_refine_steps += 1
                                last_transport_delta = None
                            continue
                    if (
                        ten_agent_focus
                        and basin_restarts < max_basin_restarts
                        and best_state_index < len(states) - 1
                        and deadline - perf_counter() > 1.0
                    ):
                        anchor_index = best_state_index
                        previous_source = active_context.reference_source
                        restart_portfolio = build_reference_portfolio(
                            instance=instance,
                            current_state=states[anchor_index],
                            goals=context.goals,
                            goal_maps=context.goal_maps,
                            agent_ids=context.agent_ids,
                            time_limit_s=max(0.5, deadline - perf_counter()),
                            preferred_first=choose_reference_mode(
                                active_context.reference_source,
                                offset=basin_restarts + 1,
                            ),
                        )
                        source_portfolio_attempts += len(restart_portfolio)
                        active_context = min(
                            restart_portfolio,
                            key=lambda item: (
                                item.reference_source == active_context.reference_source,
                                score_planning_context(
                                    instance=instance,
                                    current_state=states[anchor_index],
                                    goals=context.goals,
                                    goal_maps=context.goal_maps,
                                    context=item,
                                ),
                            ),
                        )
                        source_portfolio_successes += int(active_context.reference_source != previous_source)
                        states = states[: anchor_index + 1]
                        current_state = states[-1]
                        wait_streak = 0
                        no_progress_streak = 0
                        recovery_attempts_in_basin = 0
                        consecutive_failed_recoveries = 0
                        local_refine_burst_remaining = max(local_refine_burst_remaining, 8)
                        last_transport_delta = None
                        basin_restarts += 1
                        basin_restart_source = active_context.reference_source
                        reference_switch_count += int(active_context.reference_source != previous_source)
                        continue
                    return build_result(
                        status="failed",
                        agent_ids=active_context.agent_ids,
                        states=None,
                        runtime_s=perf_counter() - start_time,
                        expanded_nodes=expanded_nodes,
                        candidate_prunes=candidate_prunes,
                        disconnected_state_prunes=disconnected_state_prunes,
                        repair_invocations=repair_invocations,
                        restart_invocations=0,
                        plateau_restart_invocations=0,
                        warm_start_used=active_context.warm_paths is not None,
                        warm_start_status=active_context.warm_start_status,
                        beam_width=96,
                        beam_horizon=5,
                        mode="convoy_macro_beam",
                        reference_source=active_context.reference_source,
                        transport_steps=transport_steps,
                        local_refine_steps=local_refine_steps,
                        macro_expansions=macro_expansions,
                        macro_successes=macro_successes,
                        cycle_break_invocations=cycle_break_invocations,
                        escape_move_invocations=escape_move_invocations,
                        recovery_successes=recovery_successes,
                        local_dead_end_rescues=local_dead_end_rescues,
                        source_portfolio_attempts=source_portfolio_attempts,
                        source_portfolio_successes=source_portfolio_successes,
                        basin_restart_source=basin_restart_source,
                        diversification_bursts=0,
                        basin_restarts=basin_restarts,
                        reference_switch_count=reference_switch_count,
                        active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
                        best_progress_step=best_progress_step,
                        steps_since_last_progress=steps_since_last_progress,
                        stall_exit_reason="transport_dead_end",
                        reason="stalled",
                    )
            else:
                transport_steps += 1
                last_transport_delta = transport.chosen_delta
                if force_cycle_break:
                    local_refine_burst_remaining = max(local_refine_burst_remaining, 3)
        else:
            used_local_refine = True
            adaptive_refine = no_progress_streak >= (4 if ten_agent_focus else 6)
            search = search_window(
                instance=instance,
                current_state=current_state,
                goals=context.goals,
                goal_maps=context.goal_maps,
                reference_trajectory=reference_trajectory,
                beam_horizon=7 if ten_agent_focus and (adaptive_refine or local_refine_burst_remaining > 0) else (6 if (adaptive_refine or local_refine_burst_remaining > 0) else 5),
                beam_width=160 if ten_agent_focus and (adaptive_refine or local_refine_burst_remaining > 0) else (128 if (adaptive_refine or local_refine_burst_remaining > 0) else 96),
                candidate_cap=5 if ten_agent_focus and (adaptive_refine or local_refine_burst_remaining > 0) else (4 if (adaptive_refine or local_refine_burst_remaining > 0) else 3),
                partial_limit=128 if ten_agent_focus and (adaptive_refine or local_refine_burst_remaining > 0) else (96 if (adaptive_refine or local_refine_burst_remaining > 0) else 64),
                deadline=deadline,
                support_agents=None,
                diversify=ten_agent_focus and adaptive_refine,
            )
            expanded_nodes += search.expanded_nodes
            candidate_prunes += search.candidate_prunes
            disconnected_state_prunes += search.disconnected_state_prunes
            next_state = search.first_state
            if next_state is None:
                repair_invocations += 1
                repair = localized_connector_repair(
                    instance=instance,
                    current_state=current_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    reference_trajectory=reference_trajectory,
                    beam_width=56 if ten_agent_focus and adaptive_refine else (40 if adaptive_refine else 24),
                    candidate_cap=5 if ten_agent_focus and adaptive_refine else (4 if adaptive_refine else 3),
                    depth=4 if ten_agent_focus and adaptive_refine else (3 if adaptive_refine else 2),
                    deadline=deadline,
                    support_limit=10 if ten_agent_focus and adaptive_refine else (8 if adaptive_refine else 6),
                    diversify=ten_agent_focus and adaptive_refine,
                )
                expanded_nodes += repair.expanded_nodes
                candidate_prunes += repair.candidate_prunes
                disconnected_state_prunes += repair.disconnected_state_prunes
                next_state = repair.first_state
            if next_state is None:
                if wait_streak < 2 and is_connected_positions(current_state):
                    next_state = current_state
                    wait_streak += 1
                else:
                    rescue = attempt_convoy_local_dead_end_rescue(
                        instance=instance,
                        current_state=current_state,
                        goals=context.goals,
                        goal_maps=context.goal_maps,
                        agent_ids=context.agent_ids,
                        active_context=active_context,
                        deadline=deadline,
                        aggressive=ten_agent_focus,
                    )
                    source_portfolio_attempts += rescue.source_attempts
                    source_portfolio_successes += rescue.source_successes
                    expanded_nodes += rescue.expanded_nodes
                    candidate_prunes += rescue.candidate_prunes
                    disconnected_state_prunes += rescue.disconnected_state_prunes
                    macro_expansions += rescue.macro_expansions
                    macro_successes += rescue.macro_successes
                    active_subset_total += rescue.active_subset_total
                    active_subset_samples += rescue.active_subset_samples
                    if rescue.next_state is not None and rescue.context is not None:
                        previous_source = active_context.reference_source
                        active_context = rescue.context
                        basin_restart_source = active_context.reference_source
                        basin_restarts += 1
                        reference_switch_count += int(active_context.reference_source != previous_source)
                        local_dead_end_rescues += 1
                        recovery_successes += 1
                        no_progress_streak = 0
                        recovery_attempts_in_basin = 0
                        consecutive_failed_recoveries = 0
                        wait_streak = 0
                        local_refine_burst_remaining = max(local_refine_burst_remaining, 6)
                        states.append(rescue.next_state)
                        current_state = rescue.next_state
                        if rescue.used_transport:
                            transport_steps += 1
                        else:
                            local_refine_steps += 1
                            last_transport_delta = None
                        continue
                    if (
                        ten_agent_focus
                        and best_state_index < len(states) - 1
                        and basin_restarts < max_basin_restarts
                        and deadline - perf_counter() > 1.0
                    ):
                        anchor_rescue = attempt_convoy_anchor_rollback_recovery(
                            instance=instance,
                            anchor_state=states[best_state_index],
                            goals=context.goals,
                            goal_maps=context.goal_maps,
                            agent_ids=context.agent_ids,
                            active_context=active_context,
                            deadline=deadline,
                            aggressive=True,
                        )
                        source_portfolio_attempts += anchor_rescue.source_attempts
                        source_portfolio_successes += anchor_rescue.source_successes
                        expanded_nodes += anchor_rescue.expanded_nodes
                        candidate_prunes += anchor_rescue.candidate_prunes
                        disconnected_state_prunes += anchor_rescue.disconnected_state_prunes
                        macro_expansions += anchor_rescue.macro_expansions
                        macro_successes += anchor_rescue.macro_successes
                        active_subset_total += anchor_rescue.active_subset_total
                        active_subset_samples += anchor_rescue.active_subset_samples
                        if anchor_rescue.next_state is not None and anchor_rescue.context is not None:
                            previous_source = active_context.reference_source
                            active_context = anchor_rescue.context
                            basin_restart_source = active_context.reference_source
                            basin_restarts += 1
                            reference_switch_count += int(active_context.reference_source != previous_source)
                            recovery_successes += 1
                            wait_streak = 0
                            no_progress_streak = 0
                            recovery_attempts_in_basin = 0
                            consecutive_failed_recoveries = 0
                            local_refine_burst_remaining = max(local_refine_burst_remaining, 10)
                            states = states[: best_state_index + 1]
                            states.append(anchor_rescue.next_state)
                            current_state = anchor_rescue.next_state
                            if anchor_rescue.used_transport:
                                transport_steps += 1
                            else:
                                local_refine_steps += 1
                                last_transport_delta = None
                            continue
                    if (
                        ten_agent_focus
                        and basin_restarts < max_basin_restarts
                        and best_state_index < len(states) - 1
                        and deadline - perf_counter() > 1.0
                    ):
                        anchor_index = best_state_index
                        previous_source = active_context.reference_source
                        restart_portfolio = build_reference_portfolio(
                            instance=instance,
                            current_state=states[anchor_index],
                            goals=context.goals,
                            goal_maps=context.goal_maps,
                            agent_ids=context.agent_ids,
                            time_limit_s=max(0.5, deadline - perf_counter()),
                            preferred_first=choose_reference_mode(
                                active_context.reference_source,
                                offset=basin_restarts + 1,
                            ),
                        )
                        source_portfolio_attempts += len(restart_portfolio)
                        active_context = min(
                            restart_portfolio,
                            key=lambda item: (
                                item.reference_source == active_context.reference_source,
                                score_planning_context(
                                    instance=instance,
                                    current_state=states[anchor_index],
                                    goals=context.goals,
                                    goal_maps=context.goal_maps,
                                    context=item,
                                ),
                            ),
                        )
                        source_portfolio_successes += int(active_context.reference_source != previous_source)
                        states = states[: anchor_index + 1]
                        current_state = states[-1]
                        wait_streak = 0
                        no_progress_streak = 0
                        recovery_attempts_in_basin = 0
                        consecutive_failed_recoveries = 0
                        local_refine_burst_remaining = max(local_refine_burst_remaining, 8)
                        last_transport_delta = None
                        basin_restarts += 1
                        basin_restart_source = active_context.reference_source
                        reference_switch_count += int(active_context.reference_source != previous_source)
                        continue
                    return build_result(
                        status="failed",
                        agent_ids=active_context.agent_ids,
                        states=None,
                        runtime_s=perf_counter() - start_time,
                        expanded_nodes=expanded_nodes,
                        candidate_prunes=candidate_prunes,
                        disconnected_state_prunes=disconnected_state_prunes,
                        repair_invocations=repair_invocations,
                        restart_invocations=0,
                        plateau_restart_invocations=0,
                        warm_start_used=active_context.warm_paths is not None,
                        warm_start_status=active_context.warm_start_status,
                        beam_width=96,
                        beam_horizon=5,
                        mode="convoy_macro_beam",
                        reference_source=active_context.reference_source,
                        transport_steps=transport_steps,
                        local_refine_steps=local_refine_steps,
                        macro_expansions=macro_expansions,
                        macro_successes=macro_successes,
                        cycle_break_invocations=cycle_break_invocations,
                        escape_move_invocations=escape_move_invocations,
                        recovery_successes=recovery_successes,
                        local_dead_end_rescues=local_dead_end_rescues,
                        source_portfolio_attempts=source_portfolio_attempts,
                        source_portfolio_successes=source_portfolio_successes,
                        basin_restart_source=basin_restart_source,
                        diversification_bursts=0,
                        basin_restarts=basin_restarts,
                        reference_switch_count=reference_switch_count,
                        active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
                        best_progress_step=best_progress_step,
                        steps_since_last_progress=steps_since_last_progress,
                        stall_exit_reason="local_dead_end",
                        reason="stalled",
                    )
            else:
                local_refine_steps += 1
                last_transport_delta = None
        if used_local_refine and local_refine_burst_remaining > 0:
            local_refine_burst_remaining -= 1
        if next_state == current_state:
            wait_streak += 1
        else:
            wait_streak = 0
        states.append(next_state)
        current_state = next_state
        current_total_goal_distance = total_goal_distance(current_state, context.goals, context.goal_maps)
        current_centroid_distance = centroid_distance(current_state, context.goals)
        current_agents_at_goal = count_agents_at_goal(current_state, context.goals)
        improved = (
            current_total_goal_distance < best_total_goal_distance_seen
            or current_centroid_distance < best_centroid_distance_seen
            or current_agents_at_goal > best_agents_at_goal
        )
        if improved:
            best_total_goal_distance_seen = min(best_total_goal_distance_seen, current_total_goal_distance)
            best_centroid_distance_seen = min(best_centroid_distance_seen, current_centroid_distance)
            best_agents_at_goal = max(best_agents_at_goal, current_agents_at_goal)
            best_progress_step = len(states) - 1
            best_state_index = len(states) - 1
            no_progress_streak = 0
            recovery_attempts_in_basin = 0
            consecutive_failed_recoveries = 0
        else:
            no_progress_streak += 1
            time_remaining = deadline - perf_counter()
            early_stalled = no_progress_streak >= 8 and best_progress_step > 0 and steps_since_last_progress <= 12
            recovery_budget_exhausted = recovery_attempts_in_basin >= (4 if ten_agent_focus else 3) or (
                recovery_attempts_in_basin >= (3 if ten_agent_focus else 2) and time_remaining < max(4.0, time_limit_s * 0.15)
            )
            if (
                (early_stalled or recovery_budget_exhausted or consecutive_failed_recoveries >= 2)
                and basin_restarts < max_basin_restarts
                and best_state_index < len(states) - 1
                and time_remaining > 0.75
            ):
                anchor_index = best_state_index
                previous_source = active_context.reference_source
                restart_portfolio = build_reference_portfolio(
                    instance=instance,
                    current_state=states[anchor_index],
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    agent_ids=context.agent_ids,
                    time_limit_s=time_remaining,
                    preferred_first=choose_reference_mode(active_context.reference_source, offset=basin_restarts + 1),
                )
                source_portfolio_attempts += len(restart_portfolio)
                active_context = min(
                    restart_portfolio,
                    key=lambda item: (
                        item.reference_source == active_context.reference_source,
                        score_planning_context(
                            instance=instance,
                            current_state=states[anchor_index],
                            goals=context.goals,
                            goal_maps=context.goal_maps,
                            context=item,
                        ),
                    ),
                )
                source_portfolio_successes += int(active_context.reference_source != previous_source)
                states = states[: anchor_index + 1]
                current_state = states[-1]
                wait_streak = 0
                no_progress_streak = 0
                last_transport_delta = None
                local_refine_burst_remaining = max(local_refine_burst_remaining, 7 if ten_agent_focus else 5)
                recovery_attempts_in_basin = 0
                consecutive_failed_recoveries = 0
                basin_restarts += 1
                basin_restart_source = active_context.reference_source
                reference_switch_count += int(active_context.reference_source != previous_source)
                continue
            if no_progress_streak >= (8 if ten_agent_focus else 10) and best_state_index < len(states) - 1 and time_remaining > 0.75:
                recovery_attempts_in_basin += 1
                escape_move_invocations += 1
                anchor_state = states[best_state_index]
                recovery_trajectory = build_reference_trajectory(
                    grid=instance.grid,
                    current_state=anchor_state,
                    goals=active_context.goals,
                    goal_maps=active_context.goal_maps,
                    warm_paths=active_context.warm_paths,
                    global_step=best_state_index,
                    horizon=6,
                    prefer_group_bias=True,
                )
                aggressive_recovery = ten_agent_focus or deadline - perf_counter() > 2.0
                recovery = search_window(
                    instance=instance,
                    current_state=anchor_state,
                    goals=context.goals,
                    goal_maps=context.goal_maps,
                    reference_trajectory=recovery_trajectory,
                    beam_horizon=6 if aggressive_recovery else 4,
                    beam_width=128 if aggressive_recovery else 96,
                    candidate_cap=4 if aggressive_recovery else 3,
                    partial_limit=96 if aggressive_recovery else 64,
                    deadline=deadline,
                    support_agents=None,
                    diversify=ten_agent_focus,
                )
                expanded_nodes += recovery.expanded_nodes
                candidate_prunes += recovery.candidate_prunes
                disconnected_state_prunes += recovery.disconnected_state_prunes
                recovered_state = recovery.first_state
                recovered_by_transport = False
                if recovered_state is None:
                    repair_invocations += 1
                    repair = localized_connector_repair(
                        instance=instance,
                        current_state=anchor_state,
                        goals=context.goals,
                        goal_maps=context.goal_maps,
                        reference_trajectory=recovery_trajectory,
                        beam_width=40 if aggressive_recovery else 28,
                        candidate_cap=4 if aggressive_recovery else 3,
                        depth=3 if aggressive_recovery else 2,
                        deadline=deadline,
                        support_limit=8 if aggressive_recovery else 6,
                        diversify=ten_agent_focus,
                    )
                    expanded_nodes += repair.expanded_nodes
                    candidate_prunes += repair.candidate_prunes
                    disconnected_state_prunes += repair.disconnected_state_prunes
                    recovered_state = repair.first_state
                if recovered_state is None:
                    cycle_break_invocations += 1
                    transport = transport_macro_step(
                        instance=instance,
                        current_state=anchor_state,
                        goals=context.goals,
                        goal_maps=context.goal_maps,
                        reference_trajectory=recovery_trajectory,
                        deadline=deadline,
                        force_cycle_break=True,
                        last_delta=None,
                    )
                    expanded_nodes += transport.expanded_nodes
                    candidate_prunes += transport.candidate_prunes
                    disconnected_state_prunes += transport.disconnected_state_prunes
                    macro_expansions += transport.macro_expansions
                    macro_successes += transport.macro_successes
                    active_subset_total += transport.active_subset_total
                    active_subset_samples += transport.active_subset_samples
                    recovered_state = transport.next_state
                    recovered_by_transport = recovered_state is not None
                    if recovered_by_transport:
                        last_transport_delta = transport.chosen_delta
                if recovered_state is not None and recovered_state != anchor_state:
                    states = states[: best_state_index + 1]
                    states.append(recovered_state)
                    current_state = recovered_state
                    wait_streak = 0
                    no_progress_streak = 0
                    recovery_successes += 1
                    local_refine_burst_remaining = max(local_refine_burst_remaining, 8 if ten_agent_focus else 6)
                    consecutive_failed_recoveries = 0
                    if recovered_by_transport:
                        transport_steps += 1
                    else:
                        local_refine_steps += 1
                    continue
                consecutive_failed_recoveries += 1
            if no_progress_streak >= (24 if ten_agent_focus else 18):
                stall_exit_reason = "basin_stalled" if best_progress_step > 0 else "early_stall"
                return build_result(
                    status="failed",
                    agent_ids=active_context.agent_ids,
                    states=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    candidate_prunes=candidate_prunes,
                    disconnected_state_prunes=disconnected_state_prunes,
                    repair_invocations=repair_invocations,
                    restart_invocations=0,
                    plateau_restart_invocations=0,
                    warm_start_used=active_context.warm_paths is not None,
                    warm_start_status=active_context.warm_start_status,
                    beam_width=96,
                    beam_horizon=5,
                    mode="convoy_macro_beam",
                    reference_source=active_context.reference_source,
                    transport_steps=transport_steps,
                    local_refine_steps=local_refine_steps,
                    macro_expansions=macro_expansions,
                    macro_successes=macro_successes,
                    cycle_break_invocations=cycle_break_invocations,
                    escape_move_invocations=escape_move_invocations,
                    recovery_successes=recovery_successes,
                    local_dead_end_rescues=local_dead_end_rescues,
                    source_portfolio_attempts=source_portfolio_attempts,
                    source_portfolio_successes=source_portfolio_successes,
                    basin_restart_source=basin_restart_source,
                    diversification_bursts=0,
                    basin_restarts=basin_restarts,
                    reference_switch_count=reference_switch_count,
                    active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=no_progress_streak,
                    stall_exit_reason=stall_exit_reason,
                    reason="stalled",
                )
        if (
            ten_agent_focus
            and len(states) - 1 >= max_steps - 1
            and best_state_index < len(states) - 1
            and basin_restarts < max_basin_restarts
            and deadline - perf_counter() > 1.0
        ):
            anchor_rescue = attempt_convoy_anchor_rollback_recovery(
                instance=instance,
                anchor_state=states[best_state_index],
                goals=context.goals,
                goal_maps=context.goal_maps,
                agent_ids=context.agent_ids,
                active_context=active_context,
                deadline=deadline,
                aggressive=True,
            )
            source_portfolio_attempts += anchor_rescue.source_attempts
            source_portfolio_successes += anchor_rescue.source_successes
            expanded_nodes += anchor_rescue.expanded_nodes
            candidate_prunes += anchor_rescue.candidate_prunes
            disconnected_state_prunes += anchor_rescue.disconnected_state_prunes
            macro_expansions += anchor_rescue.macro_expansions
            macro_successes += anchor_rescue.macro_successes
            active_subset_total += anchor_rescue.active_subset_total
            active_subset_samples += anchor_rescue.active_subset_samples
            if anchor_rescue.next_state is not None and anchor_rescue.context is not None:
                previous_source = active_context.reference_source
                active_context = anchor_rescue.context
                basin_restart_source = active_context.reference_source
                basin_restarts += 1
                reference_switch_count += int(active_context.reference_source != previous_source)
                recovery_successes += 1
                wait_streak = 0
                no_progress_streak = 0
                recovery_attempts_in_basin = 0
                consecutive_failed_recoveries = 0
                local_refine_burst_remaining = max(local_refine_burst_remaining, 10)
                states = states[: best_state_index + 1]
                states.append(anchor_rescue.next_state)
                current_state = anchor_rescue.next_state
                max_steps += 96
                if anchor_rescue.used_transport:
                    transport_steps += 1
                else:
                    local_refine_steps += 1
                    last_transport_delta = None
                continue
    return build_result(
        status="failed",
        agent_ids=active_context.agent_ids,
        states=None,
        runtime_s=perf_counter() - start_time,
        expanded_nodes=expanded_nodes,
        candidate_prunes=candidate_prunes,
        disconnected_state_prunes=disconnected_state_prunes,
        repair_invocations=repair_invocations,
        restart_invocations=0,
        plateau_restart_invocations=0,
        warm_start_used=active_context.warm_paths is not None,
        warm_start_status=active_context.warm_start_status,
        beam_width=96,
        beam_horizon=5,
        mode="convoy_macro_beam",
        reference_source=active_context.reference_source,
        transport_steps=transport_steps,
        local_refine_steps=local_refine_steps,
        macro_expansions=macro_expansions,
        macro_successes=macro_successes,
        cycle_break_invocations=cycle_break_invocations,
        escape_move_invocations=escape_move_invocations,
        recovery_successes=recovery_successes,
        local_dead_end_rescues=local_dead_end_rescues,
        source_portfolio_attempts=source_portfolio_attempts,
        source_portfolio_successes=source_portfolio_successes,
        basin_restart_source=basin_restart_source,
        diversification_bursts=0,
        basin_restarts=basin_restarts,
        reference_switch_count=reference_switch_count,
        active_subset_mean=safe_mean(active_subset_total, active_subset_samples),
        best_progress_step=best_progress_step,
        steps_since_last_progress=(len(states) - 1) - best_progress_step,
        stall_exit_reason="step_cap",
        reason="step_cap",
    )


def build_planning_context(
    instance: Instance,
    time_limit_s: float,
    *,
    large_mode: bool,
    preferred_reference_mode: str | None = None,
    warm_path_policy: str = "auto",
) -> PlanningContext:
    agents = sorted(instance.agents, key=lambda item: (-manhattan(item.start, item.goal), item.id))
    agent_ids = [agent.id for agent in agents]
    goals = tuple(agent.goal for agent in agents)
    goal_maps = tuple(reverse_distance_map(instance.grid, goal) for goal in goals)
    warm_budget = min(1.5 if large_mode else 2.5, max(1.0, time_limit_s * 0.1))
    if preferred_reference_mode is not None or warm_path_policy != "auto":
        return build_restart_context(
            instance=instance,
            current_state=tuple(agent.start for agent in agents),
            goals=goals,
            goal_maps=goal_maps,
            agent_ids=agent_ids,
            reference_mode=preferred_reference_mode or "prioritized",
            time_limit_s=warm_budget,
            warm_path_policy=warm_path_policy,
        )
    warm_start = PrioritizedPlanner().solve(instance, warm_budget)
    warm_paths: tuple[tuple[Cell, ...], ...] | None = None
    reference_makespan = 0
    if warm_start.plan is not None:
        warm_paths = tuple(
            tuple(tuple(cell) for cell in warm_start.plan.get(agent.id, [agent.start]))
            for agent in agents
        )
        reference_makespan = max((len(path) - 1 for path in warm_paths), default=0)
    return PlanningContext(
        agent_ids=agent_ids,
        start_state=tuple(agent.start for agent in agents),
        goals=goals,
        goal_maps=goal_maps,
        warm_paths=warm_paths,
        warm_start_status=warm_start.status,
        reference_source="prioritized" if warm_paths is not None else "individual_shortest_paths",
        reference_makespan=reference_makespan,
    )


def build_restart_context(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    agent_ids: list[str],
    reference_mode: str,
    time_limit_s: float,
    warm_path_policy: str = "auto",
) -> PlanningContext:
    warm_paths: tuple[tuple[Cell, ...], ...] | None = None
    warm_start_status: str | None = None
    reference_source = "individual_shortest_paths"
    reference_makespan = 0
    policy = warm_path_policy if warm_path_policy in {"auto", "prioritized_only", "replanned_only", "disabled"} else "auto"
    allow_prioritized = reference_mode == "prioritized" and policy in {"auto", "prioritized_only"}
    allow_replanned = reference_mode in {"replanned_shortest_paths", "prioritized"} and policy in {"auto", "replanned_only"}
    if allow_prioritized:
        restart_instance = Instance(
            name=f"{instance.name}_restart",
            grid=instance.grid,
            agents=[
                AgentSpec(id=agent_id, start=current_state[index], goal=goals[index])
                for index, agent_id in enumerate(agent_ids)
            ],
            connectivity=instance.connectivity,
            metadata=dict(instance.metadata),
        )
        warm_budget = min(0.75 if len(agent_ids) <= 8 else 0.5, max(0.2, time_limit_s * 0.2))
        warm_start = PrioritizedPlanner().solve(restart_instance, warm_budget)
        warm_start_status = warm_start.status
        if warm_start.plan is not None:
            warm_paths = tuple(
                tuple(tuple(cell) for cell in warm_start.plan.get(agent_id, [current_state[index]]))
                for index, agent_id in enumerate(agent_ids)
            )
            reference_makespan = max((len(path) - 1 for path in warm_paths), default=0)
            reference_source = "prioritized"
    if warm_paths is None and allow_replanned:
        replanned_paths = build_individual_shortest_reference_paths(instance, current_state, goals)
        if replanned_paths is not None:
            warm_paths = replanned_paths
            reference_makespan = max((len(path) - 1 for path in warm_paths), default=0)
            reference_source = "replanned_shortest_paths"
    return PlanningContext(
        agent_ids=agent_ids,
        start_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        warm_paths=warm_paths,
        warm_start_status=warm_start_status,
        reference_source=reference_source,
        reference_makespan=reference_makespan,
    )


def choose_window_restart_mode(reference_source: str) -> str:
    return choose_reference_mode(reference_source)


def choose_reference_mode(reference_source: str, *, offset: int = 1) -> str:
    try:
        index = REFERENCE_MODES.index(reference_source)
    except ValueError:
        index = 0
    return REFERENCE_MODES[(index + offset) % len(REFERENCE_MODES)]


def build_reference_portfolio(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    agent_ids: list[str],
    time_limit_s: float,
    preferred_first: str | None = None,
) -> list[PlanningContext]:
    contexts: list[PlanningContext] = []
    modes = list(REFERENCE_MODES)
    if preferred_first in modes:
        modes.remove(preferred_first)
        modes.insert(0, preferred_first)
    for mode in modes:
        contexts.append(
            build_restart_context(
                instance=instance,
                current_state=current_state,
                goals=goals,
                goal_maps=goal_maps,
                agent_ids=agent_ids,
                reference_mode=mode,
                time_limit_s=time_limit_s,
            )
        )
    return contexts


def score_planning_context(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    context: PlanningContext,
) -> tuple[int, int, int, int]:
    trajectory = build_reference_trajectory(
        grid=instance.grid,
        current_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        warm_paths=context.warm_paths,
        global_step=0,
        horizon=2,
        prefer_group_bias=False,
    )
    next_state = trajectory[min(1, len(trajectory) - 1)]
    return (
        total_goal_distance(next_state, goals, goal_maps),
        -count_agents_at_goal(next_state, goals),
        -mobility_score(instance.grid, next_state),
        context.reference_makespan,
    )


def should_force_ten_agent_local_refine(
    *,
    ten_agent_recovery: bool,
    local_refine_burst_remaining: int,
    transport_steps: int,
    no_progress_streak: int,
) -> bool:
    if not ten_agent_recovery or local_refine_burst_remaining > 0:
        return False
    if transport_steps > 0 and transport_steps % 4 == 0:
        return True
    return transport_steps >= 2 and no_progress_streak >= 2


def attempt_convoy_anchor_rollback_recovery(
    *,
    instance: Instance,
    anchor_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    agent_ids: list[str],
    active_context: PlanningContext,
    deadline: float,
    aggressive: bool = False,
) -> ConvoyRescueResult:
    rescue = attempt_convoy_local_dead_end_rescue(
        instance=instance,
        current_state=anchor_state,
        goals=goals,
        goal_maps=goal_maps,
        agent_ids=agent_ids,
        active_context=active_context,
        deadline=deadline,
        aggressive=aggressive,
    )
    if rescue.next_state is None or rescue.context is None or rescue.next_state == anchor_state:
        return ConvoyRescueResult(
            context=None,
            next_state=None,
            expanded_nodes=rescue.expanded_nodes,
            candidate_prunes=rescue.candidate_prunes,
            disconnected_state_prunes=rescue.disconnected_state_prunes,
            macro_expansions=rescue.macro_expansions,
            macro_successes=rescue.macro_successes,
            active_subset_total=rescue.active_subset_total,
            active_subset_samples=rescue.active_subset_samples,
            used_transport=rescue.used_transport,
            source_attempts=rescue.source_attempts,
            source_successes=rescue.source_successes,
        )
    return rescue


def attempt_convoy_local_dead_end_rescue(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    agent_ids: list[str],
    active_context: PlanningContext,
    deadline: float,
    aggressive: bool = False,
) -> ConvoyRescueResult:
    time_remaining = max(0.0, deadline - perf_counter())
    if time_remaining <= 0.3:
        return ConvoyRescueResult(context=None, next_state=None)
    preferred_first = choose_reference_mode(active_context.reference_source)
    if aggressive and active_context.reference_source == "replanned_shortest_paths":
        preferred_first = "individual_shortest_paths"
    portfolio = build_reference_portfolio(
        instance=instance,
        current_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        agent_ids=agent_ids,
        time_limit_s=time_remaining,
        preferred_first=preferred_first,
    )
    source_attempts = len(portfolio)
    ranked_contexts = sorted(
        portfolio,
        key=lambda item: (
            item.reference_source == active_context.reference_source,
            score_planning_context(
                instance=instance,
                current_state=current_state,
                goals=goals,
                goal_maps=goal_maps,
                context=item,
            ),
        ),
    )
    for context in ranked_contexts:
        reference_trajectory = build_reference_trajectory(
            grid=instance.grid,
            current_state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            warm_paths=context.warm_paths,
            global_step=0,
            horizon=6,
            prefer_group_bias=False,
        )
        transport = transport_macro_step(
            instance=instance,
            current_state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            reference_trajectory=reference_trajectory,
            deadline=deadline,
            force_cycle_break=True,
            last_delta=None,
        )
        if transport.next_state is not None and transport.next_state != current_state:
            return ConvoyRescueResult(
                context=context,
                next_state=transport.next_state,
                expanded_nodes=transport.expanded_nodes,
                candidate_prunes=transport.candidate_prunes,
                disconnected_state_prunes=transport.disconnected_state_prunes,
                macro_expansions=transport.macro_expansions,
                macro_successes=transport.macro_successes,
                active_subset_total=transport.active_subset_total,
                active_subset_samples=transport.active_subset_samples,
                used_transport=True,
                source_attempts=source_attempts,
                source_successes=1,
            )
        search = search_window(
            instance=instance,
            current_state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            reference_trajectory=reference_trajectory,
            beam_horizon=7 if aggressive else 6,
            beam_width=160 if aggressive else 128,
            candidate_cap=5 if aggressive else 4,
            partial_limit=128 if aggressive else 96,
            deadline=deadline,
            support_agents=None,
            diversify=True,
        )
        if search.first_state is not None and search.first_state != current_state:
            return ConvoyRescueResult(
                context=context,
                next_state=search.first_state,
                expanded_nodes=search.expanded_nodes + transport.expanded_nodes,
                candidate_prunes=search.candidate_prunes + transport.candidate_prunes,
                disconnected_state_prunes=search.disconnected_state_prunes + transport.disconnected_state_prunes,
                macro_expansions=transport.macro_expansions,
                macro_successes=transport.macro_successes,
                active_subset_total=transport.active_subset_total,
                active_subset_samples=transport.active_subset_samples,
                used_transport=False,
                source_attempts=source_attempts,
                source_successes=1,
            )
        repair = localized_connector_repair(
            instance=instance,
            current_state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            reference_trajectory=reference_trajectory,
            beam_width=56 if aggressive else 40,
            candidate_cap=5 if aggressive else 4,
            depth=4 if aggressive else 3,
            deadline=deadline,
            support_limit=10 if aggressive else 8,
            diversify=True,
        )
        if repair.first_state is not None and repair.first_state != current_state:
            return ConvoyRescueResult(
                context=context,
                next_state=repair.first_state,
                expanded_nodes=transport.expanded_nodes + search.expanded_nodes + repair.expanded_nodes,
                candidate_prunes=transport.candidate_prunes + search.candidate_prunes + repair.candidate_prunes,
                disconnected_state_prunes=(
                    transport.disconnected_state_prunes
                    + search.disconnected_state_prunes
                    + repair.disconnected_state_prunes
                ),
                macro_expansions=transport.macro_expansions,
                macro_successes=transport.macro_successes,
                active_subset_total=transport.active_subset_total,
                active_subset_samples=transport.active_subset_samples,
                used_transport=False,
                source_attempts=source_attempts,
                source_successes=1,
            )
    return ConvoyRescueResult(context=None, next_state=None, source_attempts=source_attempts, source_successes=0)


def density_scaled_plateau_bonus(instance: Instance) -> int:
    obstacle_ratio = len(instance.grid.obstacles) / max(1, instance.grid.width * instance.grid.height)
    return max(2, int(round(obstacle_ratio * (instance.grid.width + instance.grid.height))))


def choose_window_restart_candidate(
    *,
    instance: Instance,
    anchor_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    agent_ids: list[str],
    active_source: str,
    attempted_sources: set[str],
    time_limit_s: float,
    deadline: float,
    beam_horizon: int,
    beam_width: int,
    candidate_cap: int,
    partial_limit: int,
    diversify: bool,
) -> WindowRestartCandidate | None:
    candidate_sources = [source for source in REFERENCE_MODES if diversify or source not in attempted_sources]
    if not candidate_sources:
        candidate_sources = [source for source in REFERENCE_MODES if source != active_source]
    ranked_sources = sorted(candidate_sources, key=lambda source: (source == active_source, source))
    best_candidate: WindowRestartCandidate | None = None
    for source in ranked_sources:
        if perf_counter() > deadline:
            break
        restart_context = build_restart_context(
            instance=instance,
            current_state=anchor_state,
            goals=goals,
            goal_maps=goal_maps,
            agent_ids=agent_ids,
            reference_mode=source,
            time_limit_s=time_limit_s,
        )
        reference_trajectory = build_reference_trajectory(
            grid=instance.grid,
            current_state=anchor_state,
            goals=goals,
            goal_maps=goal_maps,
            warm_paths=restart_context.warm_paths,
            global_step=0,
            horizon=beam_horizon,
            prefer_group_bias=not diversify,
        )
        support_agents = None
        if diversify:
            support_agents = select_support_agents(
                anchor_state,
                goals,
                reference_trajectory[min(1, len(reference_trajectory) - 1)],
                goal_maps,
                support_limit=min(len(anchor_state), 8),
            )
        search = search_window(
            instance=instance,
            current_state=anchor_state,
            goals=goals,
            goal_maps=goal_maps,
            reference_trajectory=reference_trajectory,
            beam_horizon=beam_horizon,
            beam_width=beam_width,
            candidate_cap=candidate_cap,
            partial_limit=partial_limit,
            deadline=deadline,
            support_agents=support_agents,
            diversify=diversify,
        )
        prefix = search.prefix
        expanded_nodes = search.expanded_nodes
        candidate_prunes = search.candidate_prunes
        disconnected_state_prunes = search.disconnected_state_prunes
        if not prefix:
            repair = localized_connector_repair(
                instance=instance,
                current_state=anchor_state,
                goals=goals,
                goal_maps=goal_maps,
                reference_trajectory=reference_trajectory,
                beam_width=max(24, beam_width // 2),
                candidate_cap=candidate_cap,
                depth=min(3, beam_horizon),
                deadline=deadline,
                support_limit=min(len(anchor_state), 8) if diversify else None,
                diversify=diversify,
            )
            expanded_nodes += repair.expanded_nodes
            candidate_prunes += repair.candidate_prunes
            disconnected_state_prunes += repair.disconnected_state_prunes
            prefix = repair.prefix
        if not prefix or prefix[-1] == anchor_state:
            continue
        score = window_restart_score(
            grid=instance.grid,
            anchor_state=anchor_state,
            prefix=prefix,
            goals=goals,
            goal_maps=goal_maps,
            source=restart_context.reference_source,
            active_source=active_source,
            diversify=diversify,
        )
        candidate = WindowRestartCandidate(
            context=restart_context,
            prefix=prefix,
            score=score,
            expanded_nodes=expanded_nodes,
            candidate_prunes=candidate_prunes,
            disconnected_state_prunes=disconnected_state_prunes,
        )
        if best_candidate is None or candidate.score < best_candidate.score:
            best_candidate = candidate
    return best_candidate


def window_restart_score(
    *,
    grid: object,
    anchor_state: JointState,
    prefix: tuple[JointState, ...],
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    source: str,
    active_source: str,
    diversify: bool,
) -> tuple[int, ...]:
    final_state = prefix[-1]
    moved_agents = sum(int(before != after) for before, after in zip(anchor_state, final_state, strict=True))
    return (
        total_goal_distance(final_state, goals, goal_maps),
        -count_agents_at_goal(final_state, goals),
        -mobility_score(grid, final_state),
        shape_signature(final_state) == shape_signature(anchor_state),
        source == active_source and not diversify,
        -moved_agents,
        len(prefix),
    )


def build_individual_shortest_reference_paths(
    instance: Instance,
    current_state: JointState,
    goals: JointState,
) -> tuple[tuple[Cell, ...], ...] | None:
    paths: list[tuple[Cell, ...]] = []
    for start, goal in zip(current_state, goals, strict=True):
        path = bfs_shortest_path(instance.grid, start, goal)
        if path is None:
            return None
        paths.append(tuple(path))
    return tuple(paths)


def populate_default_metadata(metadata: dict[str, object], *, mode: str) -> None:
    metadata.setdefault("planner", "connected_step")
    metadata.setdefault("mode", mode)
    metadata.setdefault("warm_start_used", False)
    metadata.setdefault("warm_start_status", None)
    metadata.setdefault("beam_width", 0)
    metadata.setdefault("beam_horizon", 0)
    metadata.setdefault("repair_invocations", 0)
    metadata.setdefault("restart_invocations", 0)
    metadata.setdefault("plateau_restart_invocations", 0)
    metadata.setdefault("candidate_prunes", 0)
    metadata.setdefault("disconnected_state_prunes", 0)
    metadata.setdefault("reference_source", "individual_shortest_paths")
    metadata.setdefault("transport_steps", 0)
    metadata.setdefault("local_refine_steps", 0)
    metadata.setdefault("macro_expansions", 0)
    metadata.setdefault("macro_successes", 0)
    metadata.setdefault("cycle_break_invocations", 0)
    metadata.setdefault("escape_move_invocations", 0)
    metadata.setdefault("active_subset_mean", 0.0)
    metadata.setdefault("best_progress_step", 0)
    metadata.setdefault("steps_since_last_progress", 0)
    metadata.setdefault("recovery_successes", 0)
    metadata.setdefault("local_dead_end_rescues", 0)
    metadata.setdefault("source_portfolio_attempts", 0)
    metadata.setdefault("source_portfolio_successes", 0)
    metadata.setdefault("basin_restart_source", "")
    metadata.setdefault("diversification_bursts", 0)
    metadata.setdefault("basin_restarts", 0)
    metadata.setdefault("reference_switch_count", 0)
    metadata.setdefault("stall_exit_reason", "")


def build_result(
    *,
    status: str,
    agent_ids: list[str],
    states: list[JointState] | None,
    runtime_s: float,
    expanded_nodes: int,
    candidate_prunes: int,
    disconnected_state_prunes: int,
    repair_invocations: int,
    restart_invocations: int,
    plateau_restart_invocations: int,
    warm_start_used: bool,
    warm_start_status: str | None,
    beam_width: int,
    beam_horizon: int,
    mode: str,
    reference_source: str,
    transport_steps: int = 0,
    local_refine_steps: int = 0,
    macro_expansions: int = 0,
    macro_successes: int = 0,
    cycle_break_invocations: int = 0,
    escape_move_invocations: int = 0,
    recovery_successes: int = 0,
    local_dead_end_rescues: int = 0,
    source_portfolio_attempts: int = 0,
    source_portfolio_successes: int = 0,
    basin_restart_source: str = "",
    diversification_bursts: int = 0,
    basin_restarts: int = 0,
    reference_switch_count: int = 0,
    active_subset_mean: float = 0.0,
    best_progress_step: int = 0,
    steps_since_last_progress: int = 0,
    stall_exit_reason: str = "",
    reason: str | None = None,
) -> PlannerResult:
    plan = states_to_plan(agent_ids, states) if states is not None else None
    metadata = {
        "planner": "connected_step",
        "mode": mode,
        "warm_start_used": warm_start_used,
        "warm_start_status": warm_start_status,
        "beam_width": beam_width,
        "beam_horizon": beam_horizon,
        "repair_invocations": repair_invocations,
        "restart_invocations": restart_invocations,
        "plateau_restart_invocations": plateau_restart_invocations,
        "candidate_prunes": candidate_prunes,
        "disconnected_state_prunes": disconnected_state_prunes,
        "reference_source": reference_source,
        "transport_steps": transport_steps,
        "local_refine_steps": local_refine_steps,
        "macro_expansions": macro_expansions,
        "macro_successes": macro_successes,
        "cycle_break_invocations": cycle_break_invocations,
        "escape_move_invocations": escape_move_invocations,
        "recovery_successes": recovery_successes,
        "local_dead_end_rescues": local_dead_end_rescues,
        "source_portfolio_attempts": source_portfolio_attempts,
        "source_portfolio_successes": source_portfolio_successes,
        "basin_restart_source": basin_restart_source,
        "diversification_bursts": diversification_bursts,
        "basin_restarts": basin_restarts,
        "reference_switch_count": reference_switch_count,
        "active_subset_mean": active_subset_mean,
        "best_progress_step": best_progress_step,
        "steps_since_last_progress": steps_since_last_progress,
        "stall_exit_reason": stall_exit_reason,
    }
    if reason is not None:
        metadata["reason"] = reason
    return PlannerResult(
        status=status,
        plan=plan,
        runtime_s=runtime_s,
        expanded_nodes=expanded_nodes,
        connectivity_rejections=disconnected_state_prunes,
        metadata=metadata,
    )


def transport_macro_step(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_trajectory: tuple[JointState, ...],
    deadline: float,
    force_cycle_break: bool,
    last_delta: Cell | None,
) -> MacroStepResult:
    beam_width = 48 if force_cycle_break else 32
    active_cap = 8 if force_cycle_break else 6
    deltas = macro_directions(current_state, goals, rotate=force_cycle_break)
    candidates: list[tuple[JointState, MacroProposal]] = []
    step_result = MacroStepResult(next_state=None)
    for delta in deltas:
        proposal = propose_macro_translation(
            grid=instance.grid,
            state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            delta=delta,
            max_active_subset=active_cap,
        )
        step_result.macro_expansions += 1
        if proposal is None:
            continue
        step_result.active_subset_total += len(proposal.active_subset)
        step_result.active_subset_samples += 1
        search = resolve_macro_with_active_subset(
            instance=instance,
            state=current_state,
            goals=goals,
            goal_maps=goal_maps,
            reference_trajectory=reference_trajectory,
            proposal=proposal,
            beam_horizon=3,
            beam_width=beam_width,
            candidate_cap=3,
            deadline=deadline,
        )
        step_result.expanded_nodes += search.expanded_nodes
        step_result.candidate_prunes += search.candidate_prunes
        step_result.disconnected_state_prunes += search.disconnected_state_prunes
        if search.first_state is not None:
            step_result.macro_successes += 1
            candidates.append((search.first_state, proposal))
    if not candidates:
        return step_result
    reference_next = reference_trajectory[1]
    best_state, _ = min(
        candidates,
        key=lambda item: transport_successor_rank(
            current_state=current_state,
            successor=item[0],
            goals=goals,
            goal_maps=goal_maps,
            reference_next=reference_next,
            active_subset_size=len(item[1].active_subset),
            reversal_penalty=is_reverse_delta(item[1].delta, last_delta),
        ),
    )
    if best_state == current_state:
        moving_candidates = [item for item in candidates if item[0] != current_state]
        if moving_candidates:
            best_state, _ = min(
                moving_candidates,
                key=lambda item: transport_escape_rank(
                    current_state=current_state,
                    successor=item[0],
                    goals=goals,
                    goal_maps=goal_maps,
                    reference_next=reference_next,
                    active_subset_size=len(item[1].active_subset),
                    reversal_penalty=is_reverse_delta(item[1].delta, last_delta),
                ),
            )
    chosen = next((proposal.delta for successor, proposal in candidates if successor == best_state), None)
    step_result.next_state = best_state
    step_result.chosen_delta = chosen
    return step_result


def transport_successor_rank(
    *,
    current_state: JointState,
    successor: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_next: JointState,
    active_subset_size: int,
    reversal_penalty: int,
) -> tuple[int, float, int, int, int, int, int, int]:
    return (
        reversal_penalty,
        centroid_distance(successor, goals),
        -count_agents_at_goal(successor, goals),
        total_goal_distance(successor, goals, goal_maps),
        -adjacency_score(successor),
        reference_deviation(successor, reference_next),
        active_subset_size,
        sum(int(current == nxt) for current, nxt in zip(current_state, successor, strict=True)),
    )


def transport_escape_rank(
    *,
    current_state: JointState,
    successor: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_next: JointState,
    active_subset_size: int,
    reversal_penalty: int,
) -> tuple[int, int, float, int, int, int, int, int]:
    return (
        reversal_penalty,
        total_goal_distance(successor, goals, goal_maps),
        centroid_distance(successor, goals),
        -count_agents_at_goal(successor, goals),
        reference_deviation(successor, reference_next),
        active_subset_size,
        -adjacency_score(successor),
        sum(int(current == nxt) for current, nxt in zip(current_state, successor, strict=True)),
    )


def is_reverse_delta(delta: Cell, last_delta: Cell | None) -> int:
    if last_delta is None:
        return 0
    return int(delta == (-last_delta[0], -last_delta[1]))


def search_window(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_trajectory: tuple[JointState, ...],
    beam_horizon: int,
    beam_width: int,
    candidate_cap: int,
    partial_limit: int,
    deadline: float,
    support_agents: set[int] | None,
    diversify: bool = False,
) -> SearchResult:
    nodes = [
        BeamNode(
            state=current_state,
            prefix=(),
            agents_at_goal=count_agents_at_goal(current_state, goals),
            total_goal_distance=total_goal_distance(current_state, goals, goal_maps),
            non_progress_total=0,
            repeat_total=0,
            shape_repeat_total=0,
            adjacency_total=adjacency_score(current_state),
            mobility_total=mobility_score(instance.grid, current_state),
            reference_deviation_total=0,
            wait_total=0,
        )
    ]
    start_agents_at_goal = nodes[0].agents_at_goal
    start_distance = nodes[0].total_goal_distance
    expanded_nodes = 0
    candidate_prunes = 0
    disconnected_state_prunes = 0
    frontier = nodes
    for depth in range(beam_horizon):
        if perf_counter() > deadline:
            return SearchResult(
                first_state=None,
                prefix=(),
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
            )
        reference_next = reference_trajectory[min(depth + 1, len(reference_trajectory) - 1)]
        next_nodes: list[BeamNode] = []
        for node in frontier:
            successors, prunes, disconnects = expand_joint_successors(
                instance=instance,
                state=node.state,
                goals=goals,
                goal_maps=goal_maps,
                reference_next=reference_next,
                candidate_cap=candidate_cap,
                partial_limit=partial_limit,
                support_agents=support_agents,
            )
            candidate_prunes += prunes
            disconnected_state_prunes += disconnects
            for successor, wait_count, ref_deviation in successors:
                expanded_nodes += 1
                successor_distance = total_goal_distance(successor, goals, goal_maps)
                successor_agents_at_goal = count_agents_at_goal(successor, goals)
                next_nodes.append(
                    BeamNode(
                        state=successor,
                        prefix=node.prefix + (successor,),
                        agents_at_goal=successor_agents_at_goal,
                        total_goal_distance=successor_distance,
                        non_progress_total=node.non_progress_total
                        + int(
                            successor_distance >= node.total_goal_distance
                            and successor_agents_at_goal <= node.agents_at_goal
                        ),
                        repeat_total=node.repeat_total + int(successor == current_state or successor in node.prefix),
                        shape_repeat_total=node.shape_repeat_total
                        + int(shape_signature(successor) == shape_signature(node.state)),
                        adjacency_total=node.adjacency_total + adjacency_score(successor),
                        mobility_total=node.mobility_total + mobility_score(instance.grid, successor),
                        reference_deviation_total=node.reference_deviation_total + ref_deviation,
                        wait_total=node.wait_total + wait_count,
                    )
                )
        if not next_nodes:
            break
        frontier = top_ranked_nodes(next_nodes, beam_width, lambda item: node_rank(item, diversify=diversify))
        completed = [node for node in frontier if node.state == goals]
        if completed:
            best = min(completed, key=lambda item: node_rank(item, diversify=diversify))
            return SearchResult(
                first_state=best.prefix[0],
                prefix=best.prefix,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
            )
    improving = [
        node
        for node in frontier
        if node.prefix
        and (
            node.agents_at_goal > start_agents_at_goal
            or node.total_goal_distance < start_distance
            or node.state != current_state
        )
    ]
    if not improving:
        return SearchResult(
            first_state=None,
            prefix=(),
            expanded_nodes=expanded_nodes,
            candidate_prunes=candidate_prunes,
            disconnected_state_prunes=disconnected_state_prunes,
        )
    best = min(improving, key=lambda item: node_rank(item, diversify=diversify))
    return SearchResult(
        first_state=best.prefix[0],
        prefix=best.prefix,
        expanded_nodes=expanded_nodes,
        candidate_prunes=candidate_prunes,
        disconnected_state_prunes=disconnected_state_prunes,
    )


def localized_connector_repair(
    *,
    instance: Instance,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_trajectory: tuple[JointState, ...],
    beam_width: int,
    candidate_cap: int,
    depth: int,
    deadline: float,
    support_limit: int | None = None,
    diversify: bool = False,
) -> SearchResult:
    support_agents = select_support_agents(
        current_state,
        goals,
        reference_trajectory[1],
        goal_maps,
        support_limit=support_limit,
    )
    partial_limit = max(8, beam_width)
    return search_window(
        instance=instance,
        current_state=current_state,
        goals=goals,
        goal_maps=goal_maps,
        reference_trajectory=reference_trajectory[: depth + 1],
        beam_horizon=depth,
        beam_width=beam_width,
        candidate_cap=candidate_cap,
        partial_limit=partial_limit,
        deadline=deadline,
        support_agents=support_agents,
        diversify=diversify,
    )


def resolve_macro_with_active_subset(
    *,
    instance: Instance,
    state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_trajectory: tuple[JointState, ...],
    proposal: MacroProposal,
    beam_horizon: int,
    beam_width: int,
    candidate_cap: int,
    deadline: float,
) -> SearchResult:
    if not proposal.active_subset:
        successor = tuple(target if target is not None else state[index] for index, target in enumerate(proposal.frozen_targets))
        if is_valid_joint_transition(instance, state, successor) and is_connected_positions(successor):
            return SearchResult(first_state=successor, prefix=(successor,), expanded_nodes=1)
        return SearchResult(first_state=None, prefix=(), disconnected_state_prunes=1)
    nodes = [
        BeamNode(
            state=state,
            prefix=(),
            agents_at_goal=count_agents_at_goal(state, goals),
            total_goal_distance=total_goal_distance(state, goals, goal_maps),
            non_progress_total=0,
            repeat_total=0,
            shape_repeat_total=0,
            adjacency_total=adjacency_score(state),
            mobility_total=mobility_score(instance.grid, state),
            reference_deviation_total=0,
            wait_total=0,
        )
    ]
    start_agents_at_goal = nodes[0].agents_at_goal
    start_distance = nodes[0].total_goal_distance
    start_centroid_distance = centroid_distance(state, goals)
    expanded_nodes = 0
    candidate_prunes = 0
    disconnected_state_prunes = 0
    frontier = nodes
    for depth in range(beam_horizon):
        if perf_counter() > deadline:
            return SearchResult(
                first_state=None,
                prefix=(),
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
            )
        reference_next = reference_trajectory[min(depth + 1, len(reference_trajectory) - 1)]
        next_nodes: list[BeamNode] = []
        for node in frontier:
            successors, prunes, disconnects = expand_transport_successors(
                instance=instance,
                state=node.state,
                goals=goals,
                goal_maps=goal_maps,
                reference_next=reference_next,
                delta=proposal.delta,
                active_subset=set(proposal.active_subset),
                candidate_cap=candidate_cap,
            )
            candidate_prunes += prunes
            disconnected_state_prunes += disconnects
            for successor, wait_count, ref_deviation in successors:
                expanded_nodes += 1
                successor_distance = total_goal_distance(successor, goals, goal_maps)
                successor_agents_at_goal = count_agents_at_goal(successor, goals)
                next_nodes.append(
                    BeamNode(
                        state=successor,
                        prefix=node.prefix + (successor,),
                        agents_at_goal=successor_agents_at_goal,
                        total_goal_distance=successor_distance,
                        non_progress_total=node.non_progress_total
                        + int(
                            successor_distance >= node.total_goal_distance
                            and successor_agents_at_goal <= node.agents_at_goal
                        ),
                        repeat_total=node.repeat_total + int(successor == state or successor in node.prefix),
                        shape_repeat_total=node.shape_repeat_total
                        + int(shape_signature(successor) == shape_signature(node.state)),
                        adjacency_total=node.adjacency_total + adjacency_score(successor),
                        mobility_total=node.mobility_total + mobility_score(instance.grid, successor),
                        reference_deviation_total=node.reference_deviation_total + ref_deviation,
                        wait_total=node.wait_total + wait_count,
                    )
                )
        if not next_nodes:
            break
        frontier = top_ranked_nodes(next_nodes, beam_width, lambda item: transport_node_rank(item, goals))
        completed = [node for node in frontier if node.state == goals]
        if completed:
            best = min(completed, key=lambda item: transport_node_rank(item, goals))
            return SearchResult(
                first_state=best.prefix[0],
                prefix=best.prefix,
                expanded_nodes=expanded_nodes,
                candidate_prunes=candidate_prunes,
                disconnected_state_prunes=disconnected_state_prunes,
            )
    improving = [
        node
        for node in frontier
        if node.prefix
        and (
            node.agents_at_goal > start_agents_at_goal
            or node.total_goal_distance < start_distance
            or centroid_distance(node.state, goals) < start_centroid_distance
            or node.state != state
        )
    ]
    if not improving:
        return SearchResult(
            first_state=None,
            prefix=(),
            expanded_nodes=expanded_nodes,
            candidate_prunes=candidate_prunes,
            disconnected_state_prunes=disconnected_state_prunes,
        )
    best = min(improving, key=lambda item: transport_node_rank(item, goals))
    return SearchResult(
        first_state=best.prefix[0],
        prefix=best.prefix,
        expanded_nodes=expanded_nodes,
        candidate_prunes=candidate_prunes,
        disconnected_state_prunes=disconnected_state_prunes,
    )


def select_support_agents(
    state: JointState,
    goals: JointState,
    reference_next: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    *,
    support_limit: int | None = None,
) -> set[int]:
    limit = support_limit if support_limit is not None else (4 if len(state) <= 8 else 3)
    selected = articulation_agents(state)
    selected |= reference_conflict_agents(state, reference_next)
    ranked = sorted(
        range(len(state)),
        key=lambda index: (
            index in selected,
            goal_distance(goal_maps[index], state[index]),
            manhattan(state[index], goals[index]),
        ),
        reverse=True,
    )
    for index in ranked:
        if len(selected) >= limit:
            break
        if state[index] != goals[index]:
            selected.add(index)
    if selected and len(selected) < limit:
        anchor = next(iter(selected))
        nearest = sorted(
            [index for index in range(len(state)) if index not in selected],
            key=lambda index: manhattan(state[index], state[anchor]),
        )
        for index in nearest:
            selected.add(index)
            if len(selected) >= limit:
                break
    if not selected:
        selected.add(max(range(len(state)), key=lambda index: goal_distance(goal_maps[index], state[index])))
    return selected


def reference_conflict_agents(state: JointState, reference_next: JointState) -> set[int]:
    selected: set[int] = set()
    by_cell: dict[Cell, list[int]] = {}
    for index, cell in enumerate(reference_next):
        by_cell.setdefault(cell, []).append(index)
    for agents_here in by_cell.values():
        if len(agents_here) > 1:
            selected.update(agents_here)
    for left in range(len(state)):
        for right in range(left + 1, len(state)):
            if reference_next[left] == state[right] and reference_next[right] == state[left] and state[left] != state[right]:
                selected.add(left)
                selected.add(right)
    return selected


def top_ranked_nodes(
    nodes: list[BeamNode],
    beam_width: int,
    ranker: Callable[[BeamNode], tuple[object, ...]],
) -> list[BeamNode]:
    best_by_state: dict[JointState, BeamNode] = {}
    for node in nodes:
        existing = best_by_state.get(node.state)
        if existing is None or ranker(node) < ranker(existing):
            best_by_state[node.state] = node
    ordered = sorted(best_by_state.values(), key=ranker)
    return ordered[:beam_width]


def node_rank(node: BeamNode, *, diversify: bool = False) -> tuple[int, int, int, int, int, int, int, int]:
    if diversify:
        return (
            node.total_goal_distance,
            -node.agents_at_goal,
            node.shape_repeat_total,
            node.non_progress_total,
            node.repeat_total,
            -node.mobility_total,
            node.wait_total,
            node.reference_deviation_total,
        )
    return (
        -node.agents_at_goal,
        node.total_goal_distance,
        node.non_progress_total,
        node.shape_repeat_total,
        node.repeat_total,
        node.wait_total,
        node.reference_deviation_total,
        -node.mobility_total - node.adjacency_total,
    )


def transport_node_rank(node: BeamNode, goals: JointState) -> tuple[float, int, int, int, int, int, int, int]:
    return (
        centroid_distance(node.state, goals),
        -node.agents_at_goal,
        node.total_goal_distance,
        node.non_progress_total,
        node.repeat_total,
        node.wait_total,
        -node.adjacency_total,
        node.reference_deviation_total,
    )


def expand_joint_successors(
    *,
    instance: Instance,
    state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_next: JointState,
    candidate_cap: int,
    partial_limit: int,
    support_agents: set[int] | None,
) -> tuple[list[tuple[JointState, int, int]], int, int]:
    candidate_lists = [
        build_candidate_moves(
            grid=instance.grid,
            state=state,
            agent_index=index,
            goals=goals,
            goal_map=goal_maps[index],
            reference_target=reference_next[index],
            candidate_cap=candidate_cap,
            restricted=(support_agents is not None and index not in support_agents),
        )
        for index in range(len(state))
    ]
    expansion_order = sorted(
        range(len(state)),
        key=lambda index: (
            len(candidate_lists[index]),
            -goal_distance(goal_maps[index], state[index]),
            support_agents is not None and index not in support_agents,
        ),
    )
    partials: list[tuple[dict[int, Cell], set[Cell], int, int, int, int]] = [(dict(), set(), 0, 0, 0, 0)]
    candidate_prunes = 0
    disconnected_state_prunes = 0
    for agent_index in expansion_order:
        current = state[agent_index]
        next_partials: list[tuple[dict[int, Cell], set[Cell], int, int, int, int]] = []
        for assigned, used_cells, wait_count, ref_dev, goal_dist, adj_support in partials:
            for candidate in candidate_lists[agent_index]:
                if candidate in used_cells:
                    candidate_prunes += 1
                    continue
                if any(
                    state[other_index] == candidate and assigned.get(other_index) == current
                    for other_index in assigned
                ):
                    candidate_prunes += 1
                    continue
                next_assigned = dict(assigned)
                next_assigned[agent_index] = candidate
                next_used = set(used_cells)
                next_used.add(candidate)
                next_wait = wait_count + int(candidate == current)
                next_ref_dev = ref_dev + manhattan(candidate, reference_next[agent_index])
                next_goal_dist = goal_dist + goal_distance(goal_maps[agent_index], candidate)
                next_adj_support = adj_support + sum(
                    1
                    for other_cell in next_assigned.values()
                    if other_cell != candidate and manhattan(candidate, other_cell) == 1
                )
                next_partials.append(
                    (next_assigned, next_used, next_wait, next_ref_dev, next_goal_dist, next_adj_support)
                )
        if not next_partials:
            return [], candidate_prunes, disconnected_state_prunes
        next_partials.sort(key=partial_rank)
        partials = next_partials[:partial_limit]
    successors: list[tuple[JointState, int, int]] = []
    for assigned, _, wait_count, ref_dev, _, _ in partials:
        successor = tuple(assigned[index] for index in range(len(state)))
        if not is_connected_positions(successor):
            disconnected_state_prunes += 1
            continue
        successors.append((successor, wait_count, ref_dev))
    successors.sort(
        key=lambda item: (
            -count_agents_at_goal(item[0], goals),
            total_goal_distance(item[0], goals, goal_maps),
            -adjacency_score(item[0]),
            item[2],
            item[1],
        )
    )
    return successors[:partial_limit], candidate_prunes, disconnected_state_prunes


def expand_transport_successors(
    *,
    instance: Instance,
    state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    reference_next: JointState,
    delta: Cell,
    active_subset: set[int],
    candidate_cap: int,
) -> tuple[list[tuple[JointState, int, int]], int, int]:
    frozen_targets = build_frozen_targets(instance, state, delta, active_subset)
    if frozen_targets is None:
        return [], 0, 0
    used_cells = {cell for cell in frozen_targets if cell is not None}
    assigned_base: dict[int, Cell] = {
        index: cell for index, cell in enumerate(frozen_targets) if cell is not None
    }
    wait_base = sum(int(cell == state[index]) for index, cell in assigned_base.items())
    ref_dev_base = sum(manhattan(cell, reference_next[index]) for index, cell in assigned_base.items())
    goal_dist_base = sum(goal_distance(goal_maps[index], cell) for index, cell in assigned_base.items())
    adj_support_base = 0
    candidate_lists = {
        index: build_transport_candidate_moves(
            grid=instance.grid,
            state=state,
            agent_index=index,
            goals=goals,
            goal_map=goal_maps[index],
            reference_target=reference_next[index],
            delta=delta,
            candidate_cap=candidate_cap,
        )
        for index in active_subset
    }
    expansion_order = sorted(
        active_subset,
        key=lambda index: (
            len(candidate_lists[index]),
            -goal_distance(goal_maps[index], state[index]),
        ),
    )
    partials: list[tuple[dict[int, Cell], set[Cell], int, int, int, int]] = [
        (assigned_base, used_cells, wait_base, ref_dev_base, goal_dist_base, adj_support_base)
    ]
    candidate_prunes = 0
    disconnected_state_prunes = 0
    partial_limit = max(16, 4 * max(1, len(active_subset)))
    for agent_index in expansion_order:
        current = state[agent_index]
        next_partials: list[tuple[dict[int, Cell], set[Cell], int, int, int, int]] = []
        for assigned, used, wait_count, ref_dev, goal_dist, adj_support in partials:
            for candidate in candidate_lists[agent_index]:
                if candidate in used:
                    candidate_prunes += 1
                    continue
                if any(
                    state[other_index] == candidate and assigned.get(other_index) == current and state[other_index] != assigned.get(other_index)
                    for other_index in assigned
                ):
                    candidate_prunes += 1
                    continue
                next_assigned = dict(assigned)
                next_assigned[agent_index] = candidate
                next_used = set(used)
                next_used.add(candidate)
                next_wait = wait_count + int(candidate == current)
                next_ref_dev = ref_dev + manhattan(candidate, reference_next[agent_index])
                next_goal_dist = goal_dist + goal_distance(goal_maps[agent_index], candidate)
                next_adj_support = adj_support + sum(
                    1
                    for other_cell in next_assigned.values()
                    if other_cell != candidate and manhattan(candidate, other_cell) == 1
                )
                next_partials.append(
                    (next_assigned, next_used, next_wait, next_ref_dev, next_goal_dist, next_adj_support)
                )
        if not next_partials:
            return [], candidate_prunes, disconnected_state_prunes
        next_partials.sort(key=partial_rank)
        partials = next_partials[:partial_limit]
    successors: list[tuple[JointState, int, int]] = []
    for assigned, _, wait_count, ref_dev, _, _ in partials:
        successor = tuple(assigned[index] for index in range(len(state)))
        if not is_valid_joint_transition(instance, state, successor):
            candidate_prunes += 1
            continue
        if not is_connected_positions(successor):
            disconnected_state_prunes += 1
            continue
        successors.append((successor, wait_count, ref_dev))
    successors.sort(
        key=lambda item: (
            centroid_distance(item[0], goals),
            -count_agents_at_goal(item[0], goals),
            total_goal_distance(item[0], goals, goal_maps),
            -adjacency_score(item[0]),
            item[2],
            item[1],
        )
    )
    return successors[:partial_limit], candidate_prunes, disconnected_state_prunes


def build_frozen_targets(
    instance: Instance,
    state: JointState,
    delta: Cell,
    active_subset: set[int],
) -> tuple[Cell | None, ...] | None:
    frozen: list[Cell | None] = [None] * len(state)
    used_cells: set[Cell] = set()
    for index, cell in enumerate(state):
        if index in active_subset:
            continue
        desired = add_cell(cell, delta)
        target = desired if in_bounds(instance.grid, desired) and is_free(instance.grid, desired) else cell
        if target in used_cells:
            return None
        frozen[index] = target
        used_cells.add(target)
    return tuple(frozen)


def partial_rank(partial: tuple[dict[int, Cell], set[Cell], int, int, int, int]) -> tuple[int, int, int, int]:
    _, _, wait_count, ref_dev, goal_dist, adj_support = partial
    return (goal_dist, -adj_support, ref_dev, wait_count)


def shape_signature(state: JointState) -> tuple[Cell, ...]:
    min_x = min(cell[0] for cell in state)
    min_y = min(cell[1] for cell in state)
    return tuple(sorted((cell[0] - min_x, cell[1] - min_y) for cell in state))


def mobility_score(grid: object, state: JointState) -> int:
    occupied = set(state)
    total = 0
    for cell in state:
        for neighbor_cell in neighbors(grid, cell, include_wait=False):  # type: ignore[arg-type]
            if neighbor_cell not in occupied:
                total += 1
    return total


def build_candidate_moves(
    *,
    grid: object,
    state: JointState,
    agent_index: int,
    goals: JointState,
    goal_map: dict[Cell, int],
    reference_target: Cell,
    candidate_cap: int,
    restricted: bool,
) -> list[Cell]:
    current = state[agent_index]
    legal = neighbors(grid, current, include_wait=True)  # type: ignore[arg-type]
    move_scores = sorted(
        legal,
        key=lambda candidate: move_priority(
            candidate=candidate,
            current=current,
            state=state,
            agent_index=agent_index,
            goal=goals[agent_index],
            goal_map=goal_map,
            reference_target=reference_target,
        ),
    )
    ordered: list[Cell] = []
    reference_move = move_scores[0]
    ordered.append(reference_move)
    if current not in ordered:
        ordered.append(current)
    for candidate in move_scores[1:]:
        if candidate not in ordered:
            ordered.append(candidate)
        if restricted and len(ordered) >= 2:
            break
        if len(ordered) >= candidate_cap:
            break
    return ordered


def build_transport_candidate_moves(
    *,
    grid: object,
    state: JointState,
    agent_index: int,
    goals: JointState,
    goal_map: dict[Cell, int],
    reference_target: Cell,
    delta: Cell,
    candidate_cap: int,
) -> list[Cell]:
    current = state[agent_index]
    desired = add_cell(current, delta)
    legal = neighbors(grid, current, include_wait=True)  # type: ignore[arg-type]
    ordered: list[Cell] = []
    if desired in legal:
        ordered.append(desired)
    if current not in ordered:
        ordered.append(current)
    side_steps = [candidate for candidate in legal if candidate not in ordered]
    side_steps.sort(
        key=lambda candidate: transport_move_priority(
            candidate=candidate,
            current=current,
            desired=desired,
            state=state,
            agent_index=agent_index,
            goal=goals[agent_index],
            goal_map=goal_map,
            reference_target=reference_target,
        ),
    )
    for candidate in side_steps:
        ordered.append(candidate)
        if len(ordered) >= candidate_cap:
            break
    return ordered[:candidate_cap]


def move_priority(
    *,
    candidate: Cell,
    current: Cell,
    state: JointState,
    agent_index: int,
    goal: Cell,
    goal_map: dict[Cell, int],
    reference_target: Cell,
) -> tuple[int, int, int, int]:
    adjacency_keep = -sum(
        1 for index, other in enumerate(state) if index != agent_index and manhattan(candidate, other) == 1
    )
    goal_dist = goal_distance(goal_map, candidate)
    ref_dist = manhattan(candidate, reference_target)
    frontier_penalty = sum(
        1
        for index, other in enumerate(state)
        if index != agent_index and candidate != other and manhattan(candidate, other) <= 1
    )
    wait_penalty = int(candidate == current)
    return (adjacency_keep, goal_dist, ref_dist, frontier_penalty + wait_penalty)


def transport_move_priority(
    *,
    candidate: Cell,
    current: Cell,
    desired: Cell,
    state: JointState,
    agent_index: int,
    goal: Cell,
    goal_map: dict[Cell, int],
    reference_target: Cell,
) -> tuple[int, int, int, int, int]:
    desired_penalty = int(candidate != desired)
    adjacency_keep = -sum(
        1 for index, other in enumerate(state) if index != agent_index and manhattan(candidate, other) == 1
    )
    goal_dist = goal_distance(goal_map, candidate)
    ref_dist = manhattan(candidate, reference_target)
    wait_penalty = int(candidate == current)
    return (desired_penalty, adjacency_keep, goal_dist, ref_dist, wait_penalty)


def build_reference_trajectory(
    *,
    grid: object,
    current_state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    warm_paths: tuple[tuple[Cell, ...], ...] | None,
    global_step: int,
    horizon: int,
    prefer_group_bias: bool,
) -> tuple[JointState, ...]:
    trajectory: list[JointState] = [current_state]
    for depth in range(1, horizon + 1):
        previous = trajectory[-1]
        group_state = None
        if prefer_group_bias:
            group_delta = choose_group_delta(previous, goals)
            if group_delta is not None:
                group_state = apply_group_delta(grid, previous, group_delta)
                if group_state is None:
                    for alternate in alternate_deltas(group_delta):
                        group_state = apply_group_delta(grid, previous, alternate)
                        if group_state is not None:
                            break
        next_cells: list[Cell] = []
        for index, previous_cell in enumerate(previous):
            warm_target: Cell | None = None
            if warm_paths is not None:
                warm_path = warm_paths[index]
                if global_step + depth < len(warm_path):
                    warm_target = warm_path[global_step + depth]
            if warm_target is not None and is_one_step_move(previous_cell, warm_target) and is_free(grid, warm_target):  # type: ignore[arg-type]
                next_cells.append(warm_target)
                continue
            if group_state is not None:
                next_cells.append(group_state[index])
                continue
            next_cells.append(greedy_goal_step(grid, previous_cell, goals[index], goal_maps[index]))  # type: ignore[arg-type]
        trajectory.append(tuple(next_cells))
    return tuple(trajectory)


def greedy_goal_step(grid: object, current: Cell, goal: Cell, goal_map: dict[Cell, int]) -> Cell:
    legal = neighbors(grid, current, include_wait=True)  # type: ignore[arg-type]
    return min(legal, key=lambda candidate: (goal_distance(goal_map, candidate), manhattan(candidate, goal), candidate))


def choose_group_delta(state: JointState, goals: JointState) -> Cell | None:
    current_centroid = centroid(state)
    goal_centroid = centroid(goals)
    dx = goal_centroid[0] - current_centroid[0]
    dy = goal_centroid[1] - current_centroid[1]
    if abs(dx) < 0.5 and abs(dy) < 0.5:
        return None
    if abs(dx) >= abs(dy):
        return (1 if dx > 0 else -1, 0)
    return (0, 1 if dy > 0 else -1)


def alternate_deltas(primary: Cell) -> list[Cell]:
    if primary[0] != 0:
        return [(0, 1), (0, -1)]
    return [(1, 0), (-1, 0)]


def macro_directions(state: JointState, goals: JointState, *, rotate: bool) -> list[Cell]:
    current_centroid = centroid(state)
    goal_centroid = centroid(goals)
    dx = goal_centroid[0] - current_centroid[0]
    dy = goal_centroid[1] - current_centroid[1]
    primary: Cell
    secondary: Cell
    if abs(dx) >= abs(dy):
        primary = (sign(dx), 0) if abs(dx) > 0.1 else (0, sign(dy))
        secondary = (0, sign(dy)) if abs(dy) > 0.1 else primary
        orthogonals = [(0, 1), (0, -1)]
    else:
        primary = (0, sign(dy)) if abs(dy) > 0.1 else (sign(dx), 0)
        secondary = (sign(dx), 0) if abs(dx) > 0.1 else primary
        orthogonals = [(1, 0), (-1, 0)]
    ordered: list[Cell] = []
    for delta in [primary, secondary, *orthogonals, (0, 0)]:
        if delta not in ordered:
            ordered.append(delta)
    if rotate and len(ordered) > 2:
        motion = ordered[:-1]
        motion = motion[1:] + motion[:1]
        return motion + [(0, 0)]
    return ordered


def propose_macro_translation(
    *,
    grid: object,
    state: JointState,
    goals: JointState,
    goal_maps: tuple[dict[Cell, int], ...],
    delta: Cell,
    max_active_subset: int,
) -> MacroProposal | None:
    if delta == (0, 0):
        frozen = tuple(state)
        return MacroProposal(
            delta=delta,
            blockers=frozenset(),
            support_agents=frozenset(),
            frozen_targets=tuple(frozen),
            active_subset=(),
            centroid_distance_after=centroid_distance(state, goals),
            total_goal_distance_after=total_goal_distance(state, goals, goal_maps),
        )
    translated = tuple(add_cell(cell, delta) for cell in state)
    blockers = {
        index
        for index, target in enumerate(translated)
        if not in_bounds(grid, target) or not is_free(grid, target)  # type: ignore[arg-type]
    }
    blocker_cells = {state[index] for index in blockers}
    changed = True
    while changed:
        changed = False
        for index, target in enumerate(translated):
            if index in blockers:
                continue
            if target in blocker_cells:
                blockers.add(index)
                blocker_cells.add(state[index])
                changed = True
    if len(blockers) > max_active_subset:
        return None
    support_candidates = graph_distance_k_neighbors(state, blockers, 2) - blockers
    active = set(blockers)
    if blockers:
        blocker_list = sorted(blockers)
        ordered_support = sorted(
            support_candidates,
            key=lambda index: (
                min(manhattan(state[index], state[blocker]) for blocker in blocker_list),
                goal_distance(goal_maps[index], state[index]),
                index,
            ),
        )
        for index in ordered_support:
            if len(active) >= max_active_subset:
                break
            active.add(index)
    frozen_targets: list[Cell | None] = [None] * len(state)
    approx_state = list(state)
    for index in range(len(state)):
        if index in active:
            continue
        frozen_targets[index] = translated[index]
        approx_state[index] = translated[index]
    for index in active:
        approx_state[index] = translated[index] if in_bounds(grid, translated[index]) and is_free(grid, translated[index]) else state[index]  # type: ignore[arg-type]
    return MacroProposal(
        delta=delta,
        blockers=frozenset(blockers),
        support_agents=frozenset(active - blockers),
        frozen_targets=tuple(frozen_targets),
        active_subset=tuple(sorted(active)),
        centroid_distance_after=centroid_distance(tuple(approx_state), goals),
        total_goal_distance_after=total_goal_distance(tuple(approx_state), goals, goal_maps),
    )


def apply_group_delta(grid: object, state: JointState, delta: Cell) -> JointState | None:
    moved = tuple((cell[0] + delta[0], cell[1] + delta[1]) for cell in state)
    if len(set(moved)) != len(moved):
        return None
    if not all(in_bounds(grid, cell) and is_free(grid, cell) for cell in moved):  # type: ignore[arg-type]
        return None
    return moved


def centroid(state: JointState) -> tuple[float, float]:
    return (
        sum(cell[0] for cell in state) / len(state),
        sum(cell[1] for cell in state) / len(state),
    )


def centroid_distance(state: JointState, goals: JointState) -> float:
    current = centroid(state)
    goal = centroid(goals)
    return abs(current[0] - goal[0]) + abs(current[1] - goal[1])


def team_radius(state: JointState) -> float:
    center = centroid(state)
    return max((abs(cell[0] - center[0]) + abs(cell[1] - center[1]) for cell in state), default=0)


def sign(value: float) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def goal_distance(goal_map: dict[Cell, int], cell: Cell) -> int:
    return goal_map.get(cell, BIG_DISTANCE)


def reverse_distance_map(grid: object, goal: Cell) -> dict[Cell, int]:
    if not is_free(grid, goal):  # type: ignore[arg-type]
        return {}
    queue = deque([goal])
    distances = {goal: 0}
    while queue:
        current = queue.popleft()
        current_dist = distances[current]
        for dx, dy in DIRECTIONS4:
            previous = (current[0] + dx, current[1] + dy)
            if previous in distances or not is_free(grid, previous):  # type: ignore[arg-type]
                continue
            distances[previous] = current_dist + 1
            queue.append(previous)
    return distances


def total_goal_distance(state: JointState, goals: JointState, goal_maps: tuple[dict[Cell, int], ...]) -> int:
    return sum(goal_distance(goal_maps[index], cell) for index, cell in enumerate(state))


def count_agents_at_goal(state: JointState, goals: JointState) -> int:
    return sum(1 for current, goal in zip(state, goals, strict=True) if current == goal)


def adjacency_graph(positions: JointState) -> list[list[int]]:
    graph = [[] for _ in range(len(positions))]
    for left in range(len(positions)):
        for right in range(left + 1, len(positions)):
            if manhattan(positions[left], positions[right]) == 1:
                graph[left].append(right)
                graph[right].append(left)
    return graph


def graph_distance_k_neighbors(state: JointState, seeds: set[int], k: int) -> set[int]:
    if not seeds:
        return set()
    graph = adjacency_graph(state)
    queue = deque((seed, 0) for seed in seeds)
    seen = set(seeds)
    while queue:
        current, distance = queue.popleft()
        if distance == k:
            continue
        for nxt in graph[current]:
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append((nxt, distance + 1))
    return seen


def is_connected_positions(positions: JointState) -> bool:
    if len(positions) <= 1:
        return True
    graph = adjacency_graph(positions)
    seen = {0}
    queue = deque([0])
    while queue:
        current = queue.popleft()
        for nxt in graph[current]:
            if nxt in seen:
                continue
            seen.add(nxt)
            if len(seen) == len(positions):
                return True
            queue.append(nxt)
    return len(seen) == len(positions)


def adjacency_score(positions: JointState) -> int:
    score = 0
    for left in range(len(positions)):
        for right in range(left + 1, len(positions)):
            if manhattan(positions[left], positions[right]) == 1:
                score += 1
    return score


def articulation_agents(state: JointState) -> set[int]:
    if len(state) <= 2:
        return set()
    graph = adjacency_graph(state)
    articulation: set[int] = set()
    for removed in range(len(state)):
        remaining = [index for index in range(len(state)) if index != removed]
        if not remaining:
            continue
        seen = {remaining[0]}
        queue = deque([remaining[0]])
        while queue:
            current = queue.popleft()
            for nxt in graph[current]:
                if nxt == removed or nxt in seen:
                    continue
                seen.add(nxt)
                queue.append(nxt)
        if len(seen) != len(remaining):
            articulation.add(removed)
    return articulation


def reference_deviation(state: JointState, reference_state: JointState) -> int:
    return sum(manhattan(current, target) for current, target in zip(state, reference_state, strict=True))


def states_to_plan(agent_ids: list[str], states: list[JointState] | None) -> dict[str, list[Cell]] | None:
    if states is None:
        return None
    plan = {agent_id: [] for agent_id in agent_ids}
    for state in states:
        for index, agent_id in enumerate(agent_ids):
            plan[agent_id].append(state[index])
    return plan


def is_one_step_move(previous: Cell, current: Cell) -> bool:
    return previous == current or any((previous[0] + dx, previous[1] + dy) == current for dx, dy in DIRECTIONS4)


def is_valid_joint_transition(instance: Instance, previous: JointState, current: JointState) -> bool:
    if len(set(current)) != len(current):
        return False
    for previous_cell, current_cell in zip(previous, current, strict=True):
        if not is_one_step_move(previous_cell, current_cell):
            return False
        if not in_bounds(instance.grid, current_cell) or not is_free(instance.grid, current_cell):
            return False
    for left in range(len(previous)):
        for right in range(left + 1, len(previous)):
            if previous[left] == current[right] and previous[right] == current[left] and previous[left] != previous[right]:
                return False
    return True


def safe_mean(total: int, count_items: int) -> float:
    if count_items == 0:
        return 0.0
    return total / count_items


def connected_joint_a_star(instance: Instance, time_limit_s: float) -> PlannerResult:
    start_time = perf_counter()
    agent_ids = [agent.id for agent in instance.agents]
    starts = tuple(agent.start for agent in instance.agents)
    goals = tuple(agent.goal for agent in instance.agents)
    ticket = count()
    queue: list[tuple[int, int, int, JointState]] = []
    parents: dict[JointState, JointState | None] = {starts: None}
    cost_so_far: dict[JointState, int] = {starts: 0}
    heapq.heappush(queue, (heuristic(starts, goals), 0, next(ticket), starts))
    expanded_nodes = 0
    connectivity_rejections = 0
    while queue:
        if perf_counter() - start_time > time_limit_s:
            result = PlannerResult(
                status="timeout",
                plan=None,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                metadata={},
            )
            populate_default_metadata(result.metadata, mode="exact_joint_astar")
            result.metadata["disconnected_state_prunes"] = connectivity_rejections
            return result
        _, g_cost, _, state = heapq.heappop(queue)
        if cost_so_far.get(state, g_cost) != g_cost:
            continue
        expanded_nodes += 1
        if state == goals:
            ordered_states = reconstruct_states(parents, state)
            result = PlannerResult(
                status="solved",
                plan=states_to_plan(agent_ids, ordered_states),
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                metadata={},
            )
            populate_default_metadata(result.metadata, mode="exact_joint_astar")
            result.metadata["disconnected_state_prunes"] = connectivity_rejections
            return result
        for next_state in enumerate_successors(instance, state):
            if not is_connected_positions(next_state):
                connectivity_rejections += 1
                continue
            next_cost = g_cost + 1
            if next_cost >= cost_so_far.get(next_state, BIG_DISTANCE):
                continue
            cost_so_far[next_state] = next_cost
            parents[next_state] = state
            heapq.heappush(queue, (next_cost + heuristic(next_state, goals), next_cost, next(ticket), next_state))
    result = PlannerResult(
        status="failed",
        plan=None,
        runtime_s=perf_counter() - start_time,
        expanded_nodes=expanded_nodes,
        connectivity_rejections=connectivity_rejections,
        metadata={},
    )
    populate_default_metadata(result.metadata, mode="exact_joint_astar")
    result.metadata["disconnected_state_prunes"] = connectivity_rejections
    return result


def heuristic(state: JointState, goals: JointState) -> int:
    return max((manhattan(cell, goal) for cell, goal in zip(state, goals, strict=True)), default=0)


def enumerate_successors(instance: Instance, state: JointState) -> list[JointState]:
    move_sets = [neighbors(instance.grid, cell, include_wait=True) for cell in state]
    results: list[JointState] = []
    assigned: list[Cell] = []
    used_cells: set[Cell] = set()

    def backtrack(index: int) -> None:
        if index == len(move_sets):
            results.append(tuple(assigned))
            return
        current = state[index]
        for candidate in move_sets[index]:
            if candidate in used_cells:
                continue
            if any(state[other] == candidate and assigned[other] == current for other in range(len(assigned))):
                continue
            assigned.append(candidate)
            used_cells.add(candidate)
            backtrack(index + 1)
            used_cells.remove(candidate)
            assigned.pop()

    backtrack(0)
    return results


def reconstruct_states(parents: dict[JointState, JointState | None], goal_state: JointState) -> list[JointState]:
    ordered_states = [goal_state]
    current = goal_state
    while parents[current] is not None:
        current = parents[current]  # type: ignore[assignment]
        ordered_states.append(current)
    ordered_states.reverse()
    return ordered_states
