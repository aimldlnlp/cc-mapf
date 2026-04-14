from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from ..connectivity import cells_are_connected, is_team_connected, resolve_connectivity_rule
from ..environment import manhattan
from ..model import AgentSpec, Instance, Planner, PlannerResult
from ..validation import is_legal_move, validate_plan
from .connected_step import ConnectedStepPlanner
from .connected_step import build_individual_shortest_reference_paths
from .enhanced_connected_step import EnhancedConnectedStepPlanner
from .prioritized import PrioritizedPlanner
from .prioritized_cc import PrioritizedCCPlanner


@dataclass(frozen=True)
class ReferenceAttemptSpec:
    portfolio_source: str
    budget_fraction: float
    min_budget_s: float
    reference_mode: str | None = None
    warm_path_policy: str = "auto"


@dataclass(frozen=True)
class ReferencePortfolioResult:
    result: PlannerResult
    reference_source: str
    portfolio_source: str
    attempts: int
    successes: int
    budget_s: float
    attempt_sequence: list[dict[str, Any]]
    failure_reason: str
    usable_as_partial: bool
    allow_reference_execution: bool


@dataclass(frozen=True)
class ProgressSnapshot:
    agents_at_goal: int
    first_arrival_count: int
    remaining_distance: int
    reference_frontier: int


@dataclass(frozen=True)
class GuidedBridgeResult:
    result: PlannerResult | None
    offset: int
    attempts: int
    max_offset: int
    shrinks: int


class WindowedCCPlanner(Planner):
    name: str = "windowed_cc"

    def __init__(
        self,
        window_size: int = 10,
        replan_interval: int = 1,
        connectivity_range: float | None = None,
        priority_order: str = "goal_distance",
        stall_limit: int = 3,
        max_window_failures: int = 4,
        max_reference_only_windows: int = 64,
        max_reference_deviation: int = 2,
    ):
        self.window_size = max(1, window_size)
        self.replan_interval = max(1, replan_interval)
        self.connectivity_range = connectivity_range
        self.priority_order = priority_order
        self.stall_limit = max(1, stall_limit)
        self.max_window_failures = max(1, max_window_failures)
        self.max_reference_only_windows = max(1, max_reference_only_windows)
        self.max_reference_deviation = max(0, max_reference_deviation)

    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        start_time = perf_counter()
        agents = list(instance.agents)
        current_positions = {agent.id: agent.start for agent in agents}
        complete_paths = {agent.id: [agent.start] for agent in agents}
        arrived_agents = {agent.id for agent in agents if agent.start == agent.goal}
        replans = 0
        expanded_nodes = 0
        connectivity_rejections = 0
        window_failures = 0
        local_success_windows = 0
        fallback_windows = 0
        reference_prefix_steps = 0
        fallback_progress_resets = 0
        stall_recovery_uses = 0
        guide_bridge_attempts = 0
        guide_bridge_successes = 0
        guide_bridge_max_offset = 0
        guide_bridge_progress_resets = 0
        guide_frontier_shrinks = 0
        guide_abandonments = 0
        executable_recovery_attempts = 0
        executable_recovery_successes = 0
        executable_recovery_source = ""
        consecutive_window_failures = 0
        consecutive_stalled_windows = 0
        best_progress_step = 0
        best_reference_frontier = 0
        fallback_progress_modes_seen: list[str] = []
        progress_timeline: list[dict[str, Any]] = []
        stall_recovery_available = True
        pending_post_recovery_check = False
        reference_rebuilds = 0
        guide_bridge_locked_out = False
        reference_attempts_total = 0
        reference_successes_total = 0
        reference_budget_total = 0.0
        reference_attempt_sequence: list[dict[str, Any]] = []
        mode, radius = resolve_connectivity_rule(instance.connectivity, radius=self.connectivity_range)

        best_snapshot = self._progress_snapshot(current_positions, agents, arrived_agents, reference_frontier=0)
        reference_instance = instance
        reference_info = self._build_reference_plan(reference_instance, time_limit_s, start_time, stage_index=0)
        reference_result = reference_info.result
        reference_source = reference_info.reference_source
        reference_category = self._reference_category(reference_info.allow_reference_execution)
        reference_execution_policy = self._reference_execution_policy(reference_info.allow_reference_execution)
        reference_attempts_total += reference_info.attempts
        reference_successes_total += reference_info.successes
        reference_budget_total += reference_info.budget_s
        reference_attempt_sequence.extend(reference_info.attempt_sequence)
        expanded_nodes += reference_result.expanded_nodes or 0
        connectivity_rejections += reference_result.connectivity_rejections

        def emit_result(**kwargs: Any) -> PlannerResult:
            return self._result(
                reference_rebuilds=reference_rebuilds,
                reference_execution_policy=reference_execution_policy,
                guide_bridge_attempts=guide_bridge_attempts,
                guide_bridge_successes=guide_bridge_successes,
                guide_bridge_max_offset=guide_bridge_max_offset,
                guide_bridge_progress_resets=guide_bridge_progress_resets,
                guide_frontier_shrinks=guide_frontier_shrinks,
                guide_abandonments=guide_abandonments,
                executable_recovery_attempts=executable_recovery_attempts,
                executable_recovery_successes=executable_recovery_successes,
                executable_recovery_source=executable_recovery_source,
                **kwargs,
            )

        def rebuild_reference_from_current_positions() -> PlannerResult | None:
            nonlocal reference_instance
            nonlocal reference_info
            nonlocal reference_result
            nonlocal reference_source
            nonlocal reference_category
            nonlocal reference_execution_policy
            nonlocal reference_attempts_total
            nonlocal reference_successes_total
            nonlocal reference_budget_total
            nonlocal reference_attempt_sequence
            nonlocal expanded_nodes
            nonlocal connectivity_rejections
            nonlocal guide_bridge_locked_out
            nonlocal reference_plan
            nonlocal reference_start_step
            nonlocal reference_horizon

            reference_instance = self._instance_from_positions(instance, current_positions)
            reference_info = self._build_reference_plan(
                reference_instance,
                time_limit_s,
                start_time,
                stage_index=reference_rebuilds,
            )
            reference_result = reference_info.result
            reference_source = reference_info.reference_source
            reference_category = self._reference_category(reference_info.allow_reference_execution)
            reference_execution_policy = self._reference_execution_policy(reference_info.allow_reference_execution)
            reference_attempts_total += reference_info.attempts
            reference_successes_total += reference_info.successes
            reference_budget_total += reference_info.budget_s
            reference_attempt_sequence.extend(reference_info.attempt_sequence)
            expanded_nodes += reference_result.expanded_nodes or 0
            connectivity_rejections += reference_result.connectivity_rejections
            if reference_result.plan is None or (
                reference_result.status != "solved" and not reference_info.usable_as_partial
            ):
                failure_reason = reference_info.failure_reason or "reference_plan_failed"
                return emit_result(
                    status="timeout" if failure_reason == "deadline_exhausted_during_reference" else "failed",
                    instance=instance,
                    plan=complete_paths,
                    start_time=start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    reference_source=reference_source,
                    reference_portfolio_source=reference_info.portfolio_source,
                    reference_attempts=reference_attempts_total,
                    reference_budget_s=reference_budget_total,
                    reference_attempt_sequence=reference_attempt_sequence,
                    source_portfolio_successes=reference_successes_total,
                    window_failures=window_failures,
                    reference_prefix_steps=reference_prefix_steps,
                    local_success_windows=local_success_windows,
                    fallback_windows=fallback_windows,
                    fallback_progress_resets=fallback_progress_resets,
                    stall_recovery_uses=stall_recovery_uses,
                    replans=replans,
                    window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=max(0, replans - best_progress_step),
                    stall_exit_reason=failure_reason,
                    fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                    progress_timeline=progress_timeline,
                    reason=failure_reason,
                )
            reference_plan = reference_result.plan
            reference_start_step = len(next(iter(complete_paths.values()))) - 1
            reference_horizon = max((len(path) for path in reference_plan.values()), default=1)
            guide_bridge_locked_out = False
            return None

        if reference_result.plan is None or (
            reference_result.status != "solved" and not reference_info.usable_as_partial
        ):
            failure_reason = reference_info.failure_reason or "reference_plan_failed"
            return emit_result(
                status="timeout" if failure_reason == "deadline_exhausted_during_reference" else "failed",
                instance=instance,
                plan=None,
                start_time=start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                reference_source=reference_source,
                reference_portfolio_source=reference_info.portfolio_source,
                reference_attempts=reference_attempts_total,
                reference_budget_s=reference_budget_total,
                reference_attempt_sequence=reference_attempt_sequence,
                source_portfolio_successes=reference_successes_total,
                window_failures=window_failures,
                reference_prefix_steps=reference_prefix_steps,
                local_success_windows=local_success_windows,
                fallback_windows=fallback_windows,
                fallback_progress_resets=fallback_progress_resets,
                stall_recovery_uses=stall_recovery_uses,
                replans=replans,
                window_mode="reference_prefix_fallback",
                best_progress_step=best_progress_step,
                steps_since_last_progress=0,
                stall_exit_reason=failure_reason,
                fallback_progress_mode="none",
                progress_timeline=progress_timeline,
                reason=failure_reason,
            )

        reference_plan = reference_result.plan
        reference_start_step = 0
        reference_horizon = max((len(path) for path in reference_plan.values()), default=1)
        max_cycles = max(reference_horizon + self._reference_only_limit(instance, reference_horizon) + 2, 16)

        while not self._all_at_goals(current_positions, agents) and replans < max_cycles:
            elapsed = perf_counter() - start_time
            if elapsed >= time_limit_s:
                return emit_result(
                    status="timeout",
                    instance=instance,
                    plan=None,
                    start_time=start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    reference_source=reference_source,
                    reference_portfolio_source=reference_info.portfolio_source,
                    reference_attempts=reference_attempts_total,
                    reference_budget_s=reference_budget_total,
                    reference_attempt_sequence=reference_attempt_sequence,
                    source_portfolio_successes=reference_successes_total,
                    window_failures=window_failures,
                    reference_prefix_steps=reference_prefix_steps,
                    local_success_windows=local_success_windows,
                    fallback_windows=fallback_windows,
                    fallback_progress_resets=fallback_progress_resets,
                    stall_recovery_uses=stall_recovery_uses,
                    replans=replans,
                    window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=max(0, replans - best_progress_step),
                    stall_exit_reason="deadline",
                    fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                    progress_timeline=progress_timeline,
                )

            global_step = len(next(iter(complete_paths.values()))) - 1
            reference_step = max(0, global_step - reference_start_step)
            reference_remaining_steps = max(0, reference_horizon - 1 - reference_step)
            if reference_remaining_steps <= 0:
                reference_rebuilds += 1
                rebuild_failure = rebuild_reference_from_current_positions()
                if rebuild_failure is not None:
                    return rebuild_failure
                reference_step = 0
                reference_remaining_steps = max(0, reference_horizon - 1)
                if reference_remaining_steps <= 0:
                    break

            steps_to_execute = min(self.replan_interval, reference_remaining_steps)
            progress_before = self._progress_snapshot(
                current_positions,
                agents,
                arrived_agents,
                reference_frontier=self._reference_frontier_index(
                    current_positions,
                    reference_plan,
                    strict_reference_alignment=reference_info.allow_reference_execution,
                ),
            )

            local_instance = self._window_instance(instance, current_positions, reference_plan, reference_step)
            skip_guide_local_window = reference_category == "guide_only_reference" and guide_bridge_locked_out
            if skip_guide_local_window:
                local_result = PlannerResult(
                    status="failed",
                    plan=None,
                    runtime_s=0.0,
                    expanded_nodes=0,
                    connectivity_rejections=0,
                    metadata={"planner": self.name, "reason": "guide_locked_out"},
                )
            else:
                local_budget = self._local_budget(instance, time_limit_s, start_time)
                local_result = self._solve_local_window(local_instance, local_budget)
                expanded_nodes += local_result.expanded_nodes or 0
                connectivity_rejections += local_result.connectivity_rejections
            replans += 1

            used_fallback = False
            window_failed = False
            timeline_mode = "local_window"
            executable_recovery_used = False
            execution_start_positions = dict(current_positions)
            execution_start_arrived = set(arrived_agents)
            executed_target_instance: Instance | None = None
            executed_progress_mode: str | None = None
            guide_local_progress = (
                self._guide_candidate_progress_metrics(
                    current_positions=current_positions,
                    plan=local_result.plan,
                    agents=agents,
                    arrived_agents=arrived_agents,
                    reference_plan=reference_plan,
                    steps_to_execute=steps_to_execute,
                    target_instance=local_instance,
                )
                if reference_category == "guide_only_reference"
                else []
            )
            local_window_acceptable = self._can_execute_local_window(
                local_instance,
                reference_plan,
                reference_step,
                steps_to_execute,
                local_result,
                strict_reference_alignment=reference_info.allow_reference_execution,
            ) and (reference_category == "connected_executable_reference" or bool(guide_local_progress))
            if local_window_acceptable:
                ok, executed_steps = self._execute_plan_prefix(
                    instance,
                    agents,
                    current_positions,
                    complete_paths,
                    local_result.plan,
                    start_index=0,
                    steps_to_execute=steps_to_execute,
                    mode=mode,
                    radius=radius,
                )
                if not ok or executed_steps == 0:
                    return emit_result(
                        status="failed",
                        instance=instance,
                        plan=complete_paths,
                        start_time=start_time,
                        expanded_nodes=expanded_nodes,
                        connectivity_rejections=connectivity_rejections,
                        reference_source=reference_source,
                        reference_portfolio_source=reference_info.portfolio_source,
                        reference_attempts=reference_attempts_total,
                        reference_budget_s=reference_budget_total,
                        reference_attempt_sequence=reference_attempt_sequence,
                        source_portfolio_successes=reference_successes_total,
                        window_failures=window_failures,
                        reference_prefix_steps=reference_prefix_steps,
                        local_success_windows=local_success_windows,
                        fallback_windows=fallback_windows,
                        fallback_progress_resets=fallback_progress_resets,
                        stall_recovery_uses=stall_recovery_uses,
                        replans=replans,
                        window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                        best_progress_step=best_progress_step,
                        steps_since_last_progress=max(0, replans - best_progress_step),
                        stall_exit_reason="local_execution_invalid",
                        fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                        progress_timeline=progress_timeline,
                        reason="local_execution_invalid",
                    )
                local_success_windows += 1
                consecutive_window_failures = 0
                if reference_category == "guide_only_reference":
                    executed_target_instance = local_instance
                    executed_progress_mode = "guide"
            else:
                bridge_info = GuidedBridgeResult(result=None, offset=0, attempts=0, max_offset=0, shrinks=0)
                bridge_instance: Instance | None = None
                executable_recovery_result: PlannerResult | None = None
                executable_recovery_instance: Instance | None = None
                executable_recovery_accepted = False
                executable_recovery_acceptance_horizon = steps_to_execute
                if reference_category == "guide_only_reference" and not guide_bridge_locked_out:
                    bridge_info = self._solve_guided_bridge(
                        instance,
                        current_positions,
                        reference_plan,
                        reference_step,
                        time_limit_s,
                        start_time,
                        arrived_agents=arrived_agents,
                    )
                    guide_bridge_attempts += bridge_info.attempts
                    guide_bridge_max_offset = max(guide_bridge_max_offset, bridge_info.max_offset)
                    guide_frontier_shrinks += bridge_info.shrinks
                    if bridge_info.result is not None and bridge_info.offset > 0:
                        bridge_instance = self._window_instance(
                            instance,
                            current_positions,
                            reference_plan,
                            reference_step,
                            bridge_info.offset,
                        )
                if bridge_info.result is not None and bridge_instance is not None and self._can_execute_local_window(
                    bridge_instance,
                    reference_plan,
                    reference_step,
                    min(steps_to_execute, bridge_info.offset),
                    bridge_info.result,
                    strict_reference_alignment=False,
                ):
                    ok, executed_steps = self._execute_plan_prefix(
                        instance,
                        agents,
                        current_positions,
                        complete_paths,
                        bridge_info.result.plan,
                        start_index=0,
                        steps_to_execute=min(steps_to_execute, bridge_info.offset),
                        mode=mode,
                        radius=radius,
                    )
                    if not ok or executed_steps == 0:
                        return emit_result(
                            status="failed",
                            instance=instance,
                            plan=complete_paths,
                            start_time=start_time,
                            expanded_nodes=expanded_nodes,
                            connectivity_rejections=connectivity_rejections,
                            reference_source=reference_source,
                            reference_portfolio_source=reference_info.portfolio_source,
                            reference_attempts=reference_attempts_total,
                            reference_budget_s=reference_budget_total,
                            reference_attempt_sequence=reference_attempt_sequence,
                            source_portfolio_successes=reference_successes_total,
                            window_failures=window_failures,
                            reference_prefix_steps=reference_prefix_steps,
                            local_success_windows=local_success_windows,
                            fallback_windows=fallback_windows,
                            fallback_progress_resets=fallback_progress_resets,
                            stall_recovery_uses=stall_recovery_uses,
                            replans=replans,
                            window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                            best_progress_step=best_progress_step,
                            steps_since_last_progress=max(0, replans - best_progress_step),
                            stall_exit_reason="guide_bridge_invalid",
                            fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                            progress_timeline=progress_timeline,
                            reason="guide_bridge_invalid",
                        )
                    local_success_windows += 1
                    consecutive_window_failures = 0
                    guide_bridge_successes += 1
                    guide_bridge_locked_out = False
                    timeline_mode = "guided_bridge"
                    executed_target_instance = bridge_instance
                    executed_progress_mode = "guide"
                elif reference_category == "guide_only_reference":
                    if bridge_info.attempts > 0 and self._prefer_executable_recovery_after_bridge_miss(instance):
                        guide_bridge_locked_out = True
                    guide_abandonments += 1
                    executable_recovery_instance = self._instance_from_positions(instance, current_positions)
                    executable_recovery_result = self._solve_executable_recovery(
                        executable_recovery_instance,
                        time_limit_s,
                        start_time,
                    )
                    executable_recovery_attempts += max(
                        1,
                        int(executable_recovery_result.metadata.get("executable_recovery_attempts", 1))
                        if executable_recovery_result.metadata
                        else 1,
                    )
                    expanded_nodes += executable_recovery_result.expanded_nodes or 0
                    connectivity_rejections += executable_recovery_result.connectivity_rejections
                    recovery_source = str(
                        (executable_recovery_result.metadata or {}).get("executable_recovery_source", "")
                    )
                    if recovery_source:
                        executable_recovery_source = recovery_source
                    executable_recovery_acceptance_horizon = self._executable_recovery_acceptance_horizon(
                        executable_recovery_instance,
                        steps_to_execute,
                    )
                    executable_recovery_accepted = (
                        self._can_execute_connected_plan(executable_recovery_instance, executable_recovery_result)
                        and self._goal_progress_candidate_metrics(
                            current_positions=current_positions,
                            plan=executable_recovery_result.plan,
                            agents=agents,
                            arrived_agents=arrived_agents,
                            steps_to_execute=executable_recovery_acceptance_horizon,
                        )
                    )
                    if executable_recovery_accepted:
                        ok, executed_steps = self._execute_plan_prefix(
                            instance,
                            agents,
                            current_positions,
                            complete_paths,
                            executable_recovery_result.plan,
                            start_index=0,
                            steps_to_execute=steps_to_execute,
                            mode=mode,
                            radius=radius,
                        )
                        if not ok or executed_steps == 0:
                            return emit_result(
                                status="failed",
                                instance=instance,
                                plan=complete_paths,
                                start_time=start_time,
                                expanded_nodes=expanded_nodes,
                                connectivity_rejections=connectivity_rejections,
                                reference_source=reference_source,
                                reference_portfolio_source=reference_info.portfolio_source,
                                reference_attempts=reference_attempts_total,
                                reference_budget_s=reference_budget_total,
                                reference_attempt_sequence=reference_attempt_sequence,
                                source_portfolio_successes=reference_successes_total,
                                window_failures=window_failures,
                                reference_prefix_steps=reference_prefix_steps,
                                local_success_windows=local_success_windows,
                                fallback_windows=fallback_windows,
                                fallback_progress_resets=fallback_progress_resets,
                                stall_recovery_uses=stall_recovery_uses,
                                replans=replans,
                                window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                                best_progress_step=best_progress_step,
                                steps_since_last_progress=max(0, replans - best_progress_step),
                                stall_exit_reason="local_execution_invalid",
                                fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                                progress_timeline=progress_timeline,
                                reason="local_execution_invalid",
                            )
                        local_success_windows += 1
                        consecutive_window_failures = 0
                        executable_recovery_successes += 1
                        executable_recovery_used = True
                        timeline_mode = "executable_recovery"
                        executed_progress_mode = "actual_goal"
                    else:
                        window_failures += 1
                        window_failed = True
                        consecutive_window_failures += 1
                        timeline_mode = "executable_recovery_miss"
                else:
                    window_failures += 1
                    window_failed = True
                    consecutive_window_failures += 1
                    if reference_category == "connected_executable_reference":
                        used_fallback = True
                        timeline_mode = "reference_prefix_fallback"
                        ok, executed_steps = self._execute_plan_prefix(
                            instance,
                            agents,
                            current_positions,
                            complete_paths,
                            reference_plan,
                            start_index=reference_step,
                            steps_to_execute=steps_to_execute,
                            mode=mode,
                            radius=radius,
                        )
                        if not ok or executed_steps == 0:
                            return emit_result(
                                status="failed",
                                instance=instance,
                                plan=complete_paths,
                                start_time=start_time,
                                expanded_nodes=expanded_nodes,
                                connectivity_rejections=connectivity_rejections,
                                reference_source=reference_source,
                                reference_portfolio_source=reference_info.portfolio_source,
                                reference_attempts=reference_attempts_total,
                                reference_budget_s=reference_budget_total,
                                reference_attempt_sequence=reference_attempt_sequence,
                                source_portfolio_successes=reference_successes_total,
                                window_failures=window_failures,
                                reference_prefix_steps=reference_prefix_steps,
                                local_success_windows=local_success_windows,
                                fallback_windows=fallback_windows,
                                fallback_progress_resets=fallback_progress_resets,
                                stall_recovery_uses=stall_recovery_uses,
                                replans=replans,
                                window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                                best_progress_step=best_progress_step,
                                steps_since_last_progress=max(0, replans - best_progress_step),
                                stall_exit_reason="reference_execution_invalid",
                                fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                                progress_timeline=progress_timeline,
                                reason="reference_execution_invalid",
                            )
                        fallback_windows += 1
                        reference_prefix_steps += executed_steps
                    else:
                        window_failures += 1
                        window_failed = True
                        consecutive_window_failures += 1
                        timeline_mode = "guide_bridge_miss"

            self._update_arrived_agents(arrived_agents, current_positions, agents)
            frontier_after = len(next(iter(complete_paths.values()))) - 1
            progress_after = self._progress_snapshot(
                current_positions,
                agents,
                arrived_agents,
                reference_frontier=self._reference_frontier_index(
                    current_positions,
                    reference_plan,
                    strict_reference_alignment=reference_info.allow_reference_execution,
                ),
            )
            progress_metrics = self._progress_metrics(progress_before, progress_after)
            if executed_progress_mode == "actual_goal":
                progress_metrics = self._goal_progress_execution_metrics(
                    previous_positions=execution_start_positions,
                    current_positions=current_positions,
                    agents=agents,
                    arrived_agents=execution_start_arrived,
                )
            elif executed_target_instance is not None:
                progress_metrics = self._guide_execution_progress_metrics(
                    previous_positions=execution_start_positions,
                    current_positions=current_positions,
                    agents=agents,
                    arrived_agents=execution_start_arrived,
                    reference_plan=reference_plan,
                    target_instance=executed_target_instance,
                )
            best_reference_frontier = max(best_reference_frontier, progress_after.reference_frontier)

            if self._progress_snapshot_improved(progress_after, best_snapshot):
                best_snapshot = progress_after
                best_progress_step = replans

            if progress_metrics:
                consecutive_stalled_windows = 0
                pending_post_recovery_check = False
            else:
                consecutive_stalled_windows += 1

            if used_fallback and progress_metrics:
                fallback_progress_resets += 1
                fallback_progress_modes_seen = self._merge_progress_modes(
                    fallback_progress_modes_seen,
                    progress_metrics,
                )
                consecutive_window_failures = 0

            if timeline_mode == "guided_bridge" and progress_metrics:
                guide_bridge_progress_resets += 1

            progress_timeline.append(
                self._timeline_entry(
                    step_index=replans,
                    mode=timeline_mode,
                    progress=progress_after,
                    progress_metrics=progress_metrics,
                    window_failed=window_failed,
                    stall_recovery=False,
                )
            )

            guide_reference_refresh_needed = (
                reference_category == "guide_only_reference"
                and not self._all_at_goals(current_positions, agents)
                and (
                    timeline_mode in {"local_window", "guided_bridge"}
                    and executed_target_instance is not None
                )
            )

            if reference_category == "guide_only_reference" and executable_recovery_used and progress_metrics:
                reference_rebuilds += 1
                rebuild_failure = rebuild_reference_from_current_positions()
                if rebuild_failure is not None:
                    return rebuild_failure
                continue

            if pending_post_recovery_check and not progress_metrics:
                return emit_result(
                    status="failed",
                    instance=instance,
                    plan=complete_paths,
                    start_time=start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    reference_source=reference_source,
                    reference_portfolio_source=reference_info.portfolio_source,
                    reference_attempts=reference_attempts_total,
                    reference_budget_s=reference_budget_total,
                    reference_attempt_sequence=reference_attempt_sequence,
                    source_portfolio_successes=reference_successes_total,
                    window_failures=window_failures,
                    reference_prefix_steps=reference_prefix_steps,
                    local_success_windows=local_success_windows,
                    fallback_windows=fallback_windows,
                    fallback_progress_resets=fallback_progress_resets,
                    stall_recovery_uses=stall_recovery_uses,
                    replans=replans,
                    window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=max(0, replans - best_progress_step),
                    stall_exit_reason="stall_after_recovery",
                    fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                    progress_timeline=progress_timeline,
                    reason="stall_after_recovery",
                )

            if consecutive_stalled_windows > self.stall_limit:
                recovery_steps = min(
                    max(self.window_size * 2, self.replan_interval * 4, 4),
                    max(0, reference_horizon - 1 - frontier_after),
                )
                if stall_recovery_available and recovery_steps > 0:
                    recovery_before = progress_after
                    recovery_start_positions = dict(current_positions)
                    recovery_start_arrived = set(arrived_agents)
                    recovery_target_instance: Instance | None = None
                    recovery_mode = "stall_escape"
                    if reference_category == "connected_executable_reference":
                        ok, executed_steps = self._execute_plan_prefix(
                            instance,
                            agents,
                            current_positions,
                            complete_paths,
                            reference_plan,
                            start_index=max(0, frontier_after - reference_start_step),
                            steps_to_execute=recovery_steps,
                            mode=mode,
                            radius=radius,
                        )
                    else:
                        if guide_bridge_locked_out:
                            ok, executed_steps = False, 0
                        else:
                            recovery_bridge = self._solve_guided_bridge(
                                instance,
                                current_positions,
                                reference_plan,
                                max(0, frontier_after - reference_start_step),
                                time_limit_s,
                                start_time,
                                arrived_agents=arrived_agents,
                                preferred_offset=recovery_steps,
                            )
                            guide_bridge_attempts += recovery_bridge.attempts
                            guide_bridge_max_offset = max(guide_bridge_max_offset, recovery_bridge.max_offset)
                            guide_frontier_shrinks += recovery_bridge.shrinks
                            bridge_recovery_instance = self._window_instance(
                                instance,
                                current_positions,
                                reference_plan,
                                max(0, frontier_after - reference_start_step),
                                recovery_bridge.offset,
                            )
                            if recovery_bridge.result is not None and self._can_execute_local_window(
                                bridge_recovery_instance,
                                reference_plan,
                                max(0, frontier_after - reference_start_step),
                                min(recovery_steps, recovery_bridge.offset),
                                recovery_bridge.result,
                                strict_reference_alignment=False,
                            ):
                                ok, executed_steps = self._execute_plan_prefix(
                                    instance,
                                    agents,
                                    current_positions,
                                    complete_paths,
                                    recovery_bridge.result.plan,
                                    start_index=0,
                                    steps_to_execute=min(recovery_steps, recovery_bridge.offset),
                                    mode=mode,
                                    radius=radius,
                                )
                                if not ok or executed_steps == 0:
                                    return emit_result(
                                        status="failed",
                                        instance=instance,
                                        plan=complete_paths,
                                        start_time=start_time,
                                        expanded_nodes=expanded_nodes,
                                        connectivity_rejections=connectivity_rejections,
                                        reference_source=reference_source,
                                        reference_portfolio_source=reference_info.portfolio_source,
                                        reference_attempts=reference_attempts_total,
                                        reference_budget_s=reference_budget_total,
                                        reference_attempt_sequence=reference_attempt_sequence,
                                        source_portfolio_successes=reference_successes_total,
                                        window_failures=window_failures,
                                        reference_prefix_steps=reference_prefix_steps,
                                        local_success_windows=local_success_windows,
                                        fallback_windows=fallback_windows,
                                        fallback_progress_resets=fallback_progress_resets,
                                        stall_recovery_uses=stall_recovery_uses,
                                        replans=replans,
                                        window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                                        best_progress_step=best_progress_step,
                                        steps_since_last_progress=max(0, replans - best_progress_step),
                                        stall_exit_reason="guide_bridge_invalid",
                                        fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                                        progress_timeline=progress_timeline,
                                        reason="guide_bridge_invalid",
                                    )
                                guide_bridge_successes += 1
                                recovery_mode = "guided_stall_escape"
                                recovery_target_instance = bridge_recovery_instance
                            else:
                                ok, executed_steps = False, 0
                    if ok and executed_steps > 0:
                        fallback_windows += 1
                        reference_prefix_steps += executed_steps
                        stall_recovery_uses += 1
                        stall_recovery_available = False
                        self._update_arrived_agents(arrived_agents, current_positions, agents)
                        recovery_after = self._progress_snapshot(
                            current_positions,
                            agents,
                            arrived_agents,
                            reference_frontier=self._reference_frontier_index(
                                current_positions,
                                reference_plan,
                                strict_reference_alignment=reference_info.allow_reference_execution,
                            ),
                        )
                        recovery_metrics = self._progress_metrics(recovery_before, recovery_after)
                        if recovery_mode == "guided_stall_escape" and recovery_target_instance is not None:
                            recovery_metrics = self._guide_execution_progress_metrics(
                                previous_positions=recovery_start_positions,
                                current_positions=current_positions,
                                agents=agents,
                                arrived_agents=recovery_start_arrived,
                                reference_plan=reference_plan,
                                target_instance=recovery_target_instance,
                            )
                        best_reference_frontier = max(best_reference_frontier, recovery_after.reference_frontier)
                        if self._progress_snapshot_improved(recovery_after, best_snapshot):
                            best_snapshot = recovery_after
                            best_progress_step = replans
                        if recovery_metrics:
                            fallback_progress_resets += 1
                            fallback_progress_modes_seen = self._merge_progress_modes(
                                fallback_progress_modes_seen,
                                recovery_metrics,
                            )
                            if recovery_mode == "guided_stall_escape":
                                guide_bridge_progress_resets += 1
                            consecutive_window_failures = 0
                            consecutive_stalled_windows = 0
                            pending_post_recovery_check = False
                        else:
                            consecutive_stalled_windows = 0
                            pending_post_recovery_check = True
                        progress_timeline.append(
                            self._timeline_entry(
                                step_index=replans,
                                mode=recovery_mode,
                                progress=recovery_after,
                                progress_metrics=recovery_metrics,
                                window_failed=True,
                                stall_recovery=True,
                            )
                        )
                        continue
                failure_reason = "stall_after_recovery" if stall_recovery_uses > 0 else "window_failure_limit"
                return emit_result(
                    status="failed",
                    instance=instance,
                    plan=complete_paths,
                    start_time=start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    reference_source=reference_source,
                    reference_portfolio_source=reference_info.portfolio_source,
                    reference_attempts=reference_attempts_total,
                    reference_budget_s=reference_budget_total,
                    reference_attempt_sequence=reference_attempt_sequence,
                    source_portfolio_successes=reference_successes_total,
                    window_failures=window_failures,
                    reference_prefix_steps=reference_prefix_steps,
                    local_success_windows=local_success_windows,
                    fallback_windows=fallback_windows,
                    fallback_progress_resets=fallback_progress_resets,
                    stall_recovery_uses=stall_recovery_uses,
                    replans=replans,
                    window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=max(0, replans - best_progress_step),
                    stall_exit_reason=failure_reason,
                    fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                    progress_timeline=progress_timeline,
                    reason=failure_reason,
                )

            if guide_reference_refresh_needed:
                reference_rebuilds += 1
                rebuild_failure = rebuild_reference_from_current_positions()
                if rebuild_failure is not None:
                    return rebuild_failure

            if (
                not self._all_at_goals(current_positions, agents)
                and consecutive_window_failures > self.max_window_failures
                and consecutive_stalled_windows > 0
            ):
                return emit_result(
                    status="failed",
                    instance=instance,
                    plan=complete_paths,
                    start_time=start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    reference_source=reference_source,
                    reference_portfolio_source=reference_info.portfolio_source,
                    reference_attempts=reference_attempts_total,
                    reference_budget_s=reference_budget_total,
                    reference_attempt_sequence=reference_attempt_sequence,
                    source_portfolio_successes=reference_successes_total,
                    window_failures=window_failures,
                    reference_prefix_steps=reference_prefix_steps,
                    local_success_windows=local_success_windows,
                    fallback_windows=fallback_windows,
                    fallback_progress_resets=fallback_progress_resets,
                    stall_recovery_uses=stall_recovery_uses,
                    replans=replans,
                    window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                    best_progress_step=best_progress_step,
                    steps_since_last_progress=max(0, replans - best_progress_step),
                    stall_exit_reason="window_failure_limit",
                    fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                    progress_timeline=progress_timeline,
                    reason="window_failure_limit",
                )

        validation = validate_plan(instance, complete_paths)
        if validation.valid and self._all_at_goals(current_positions, agents):
            return emit_result(
                status="solved",
                instance=instance,
                plan=complete_paths,
                start_time=start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                reference_source=reference_source,
                reference_portfolio_source=reference_info.portfolio_source,
                reference_attempts=reference_attempts_total,
                reference_budget_s=reference_budget_total,
                reference_attempt_sequence=reference_attempt_sequence,
                source_portfolio_successes=reference_successes_total,
                window_failures=window_failures,
                reference_prefix_steps=reference_prefix_steps,
                local_success_windows=local_success_windows,
                fallback_windows=fallback_windows,
                fallback_progress_resets=fallback_progress_resets,
                stall_recovery_uses=stall_recovery_uses,
                replans=replans,
                window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
                best_progress_step=best_progress_step,
                steps_since_last_progress=max(0, replans - best_progress_step),
                stall_exit_reason="",
                fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
                progress_timeline=progress_timeline,
            )

        failure_reason = "stall_after_recovery" if stall_recovery_uses > 0 or pending_post_recovery_check else "window_failure_limit"
        return emit_result(
            status="failed",
            instance=instance,
            plan=complete_paths,
            start_time=start_time,
            expanded_nodes=expanded_nodes,
            connectivity_rejections=connectivity_rejections,
            reference_source=reference_source,
            reference_portfolio_source=reference_info.portfolio_source,
            reference_attempts=reference_attempts_total,
            reference_budget_s=reference_budget_total,
            reference_attempt_sequence=reference_attempt_sequence,
            source_portfolio_successes=reference_successes_total,
            window_failures=window_failures,
            reference_prefix_steps=reference_prefix_steps,
            local_success_windows=local_success_windows,
            fallback_windows=fallback_windows,
            fallback_progress_resets=fallback_progress_resets,
            stall_recovery_uses=stall_recovery_uses,
            replans=replans,
            window_mode=self._overall_window_mode(local_success_windows, fallback_windows),
            best_progress_step=best_progress_step,
            steps_since_last_progress=max(0, replans - best_progress_step),
            stall_exit_reason=failure_reason,
            fallback_progress_mode=self._format_progress_mode(fallback_progress_modes_seen),
            progress_timeline=progress_timeline,
            reason=failure_reason,
        )

    def _build_reference_plan(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
        *,
        stage_index: int,
    ) -> ReferencePortfolioResult:
        reference_budget_s = self._reference_budget(instance, time_limit_s, start_time)
        attempts = 0
        successes = 0
        attempt_sequence: list[dict[str, Any]] = []
        last_result = PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": self.name, "reason": "reference_plan_failed"},
        )
        last_source = "prioritized_cc"
        last_portfolio_source = "prioritized_cc"
        failure_reason = "reference_plan_failed"
        deadline_shortfall = False
        for spec in self._reference_attempt_specs(instance):
            time_remaining = max(0.0, time_limit_s - (perf_counter() - start_time))
            attempt_budget = max(0.0, reference_budget_s * spec.budget_fraction)
            if time_remaining < max(0.05, spec.min_budget_s) or attempt_budget <= 0.0:
                attempt_sequence.append(
                    {
                        "stage_index": stage_index,
                        "portfolio_source": spec.portfolio_source,
                        "source": self._normalize_reference_source(spec.portfolio_source),
                        "budget_s": round(min(time_remaining, attempt_budget), 3),
                        "reference_mode": spec.reference_mode or "",
                        "warm_path_policy": spec.warm_path_policy,
                        "status": "skipped_deadline",
                        "usable": False,
                    }
                )
                deadline_shortfall = True
                failure_reason = "deadline_exhausted_during_reference"
                break
            attempts += 1
            allotted_budget = min(attempt_budget, time_remaining)
            result = self._run_reference_attempt(spec, instance, allotted_budget)
            last_result = result
            last_portfolio_source = spec.portfolio_source
            last_source = self._normalize_reference_source(spec.portfolio_source)
            usable = self._is_usable_reference(instance, result)
            usable_as_partial = not usable and self._reference_prefix_length(instance, result.plan) > 1
            attempt_sequence.append(
                {
                    "stage_index": stage_index,
                    "portfolio_source": spec.portfolio_source,
                    "source": last_source,
                    "budget_s": round(allotted_budget, 3),
                    "reference_mode": spec.reference_mode or "",
                    "warm_path_policy": spec.warm_path_policy,
                    "status": result.status,
                    "usable": usable,
                    "usable_as_partial": usable_as_partial,
                }
            )
            if result.status == "solved" or usable_as_partial:
                successes += 1
            if usable or usable_as_partial:
                return ReferencePortfolioResult(
                    result=result,
                    reference_source=last_source,
                    portfolio_source=spec.portfolio_source,
                    attempts=attempts,
                    successes=successes,
                    budget_s=reference_budget_s,
                    attempt_sequence=attempt_sequence,
                    failure_reason="",
                    usable_as_partial=usable_as_partial,
                    allow_reference_execution=True,
                )
        guide_result = self._build_guide_reference(instance, reference_budget_s)
        if guide_result is not None:
            last_result, last_source, last_portfolio_source, guide_sequence = guide_result
            attempts += len(guide_sequence)
            successes += 1
            attempt_sequence.extend(
                [
                    {
                        "stage_index": stage_index,
                        **entry,
                    }
                    for entry in guide_sequence
                ]
            )
            return ReferencePortfolioResult(
                result=last_result,
                reference_source=last_source,
                portfolio_source=last_portfolio_source,
                attempts=attempts,
                successes=successes,
                budget_s=reference_budget_s,
                attempt_sequence=attempt_sequence,
                failure_reason="",
                usable_as_partial=False,
                allow_reference_execution=False,
            )
        if not deadline_shortfall:
            failure_reason = "reference_plan_failed"
        return ReferencePortfolioResult(
            result=last_result,
            reference_source=last_source,
            portfolio_source=last_portfolio_source,
            attempts=attempts,
            successes=successes,
            budget_s=reference_budget_s,
            attempt_sequence=attempt_sequence,
            failure_reason=failure_reason,
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def _reference_attempt_specs(self, instance: Instance) -> list[ReferenceAttemptSpec]:
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        if scale == "32x32_12a":
            specs = [
                ReferenceAttemptSpec("prioritized_cc", 0.03, 0.35),
                ReferenceAttemptSpec("connected_step", 0.24, 0.9, reference_mode="prioritized", warm_path_policy="auto"),
                ReferenceAttemptSpec("enhanced_connected_step", 0.27, 1.1),
                ReferenceAttemptSpec(
                    "connected_step_retry_replanned",
                    0.18,
                    1.0,
                    reference_mode="replanned_shortest_paths",
                    warm_path_policy="replanned_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_prioritized_only",
                    0.15,
                    0.9,
                    reference_mode="prioritized",
                    warm_path_policy="prioritized_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_unwarmed",
                    0.13,
                    0.8,
                    reference_mode="individual_shortest_paths",
                    warm_path_policy="disabled",
                ),
            ]
        elif scale == "24x24_8a":
            specs = [
                ReferenceAttemptSpec("prioritized_cc", 0.05, 0.2),
                ReferenceAttemptSpec("connected_step", 0.28, 0.55, reference_mode="prioritized", warm_path_policy="auto"),
                ReferenceAttemptSpec("enhanced_connected_step", 0.24, 0.7),
                ReferenceAttemptSpec(
                    "connected_step_retry_replanned",
                    0.18,
                    0.6,
                    reference_mode="replanned_shortest_paths",
                    warm_path_policy="replanned_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_prioritized_only",
                    0.13,
                    0.45,
                    reference_mode="prioritized",
                    warm_path_policy="prioritized_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_unwarmed",
                    0.12,
                    0.4,
                    reference_mode="individual_shortest_paths",
                    warm_path_policy="disabled",
                ),
            ]
        else:
            specs = [
                ReferenceAttemptSpec("prioritized_cc", 0.12, 0.08),
                ReferenceAttemptSpec("connected_step", 0.30, 0.2, reference_mode="prioritized", warm_path_policy="auto"),
                ReferenceAttemptSpec("enhanced_connected_step", 0.22, 0.25),
                ReferenceAttemptSpec(
                    "connected_step_retry_replanned",
                    0.18,
                    0.2,
                    reference_mode="replanned_shortest_paths",
                    warm_path_policy="replanned_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_prioritized_only",
                    0.12,
                    0.15,
                    reference_mode="prioritized",
                    warm_path_policy="prioritized_only",
                ),
                ReferenceAttemptSpec(
                    "connected_step_retry_unwarmed",
                    0.10,
                    0.12,
                    reference_mode="individual_shortest_paths",
                    warm_path_policy="disabled",
                ),
            ]
        if family in {"warehouse", "open"} and scale in {"24x24_8a", "32x32_12a"}:
            boosted: list[ReferenceAttemptSpec] = []
            for spec in specs:
                if spec.portfolio_source == "prioritized_cc":
                    boosted.append(
                        ReferenceAttemptSpec(
                            spec.portfolio_source,
                            max(0.03, spec.budget_fraction - 0.02),
                            spec.min_budget_s,
                            spec.reference_mode,
                            spec.warm_path_policy,
                        )
                    )
                elif spec.portfolio_source == "enhanced_connected_step":
                    boosted.append(
                        ReferenceAttemptSpec(
                            spec.portfolio_source,
                            spec.budget_fraction + 0.03,
                            spec.min_budget_s + 0.15,
                            spec.reference_mode,
                            spec.warm_path_policy,
                        )
                    )
                elif spec.portfolio_source.startswith("connected_step_retry"):
                    boosted.append(
                        ReferenceAttemptSpec(
                            spec.portfolio_source,
                            spec.budget_fraction + 0.01,
                            spec.min_budget_s + 0.1,
                            spec.reference_mode,
                            spec.warm_path_policy,
                        )
                    )
                else:
                    boosted.append(spec)
            specs = boosted
        return specs

    def _run_reference_attempt(self, spec: ReferenceAttemptSpec, instance: Instance, budget_s: float) -> PlannerResult:
        if spec.portfolio_source == "prioritized_cc":
            return PrioritizedCCPlanner(
                connectivity_range=self.connectivity_range,
                priority_order=self.priority_order,
            ).solve(instance, budget_s)
        if spec.portfolio_source == "enhanced_connected_step":
            return EnhancedConnectedStepPlanner().solve(instance, budget_s)
        return ConnectedStepPlanner(
            initial_reference_mode=spec.reference_mode,
            initial_warm_path_policy=spec.warm_path_policy,
        ).solve(instance, budget_s)

    def _normalize_reference_source(self, portfolio_source: str) -> str:
        if portfolio_source.startswith("connected_step_retry"):
            return "connected_step"
        return portfolio_source

    def _instance_from_positions(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
    ) -> Instance:
        return Instance(
            name=f"{instance.name}_reference_rebuild",
            grid=instance.grid,
            agents=[
                AgentSpec(agent.id, current_positions[agent.id], agent.goal)
                for agent in instance.agents
            ],
            connectivity=instance.connectivity,
            metadata=dict(instance.metadata),
        )

    def _build_guide_reference(
        self,
        instance: Instance,
        reference_budget_s: float,
    ) -> tuple[PlannerResult, str, str, list[dict[str, Any]]] | None:
        guide_sequence: list[dict[str, Any]] = []
        prioritized_budget = min(max(0.2, reference_budget_s * 0.08), 6.0)
        prioritized_result = PrioritizedPlanner().solve(instance, prioritized_budget)
        if prioritized_result.plan is not None:
            guide_sequence.append(
                {
                    "portfolio_source": "prioritized_guide",
                    "source": "prioritized_guide",
                    "budget_s": round(prioritized_budget, 3),
                    "reference_mode": "",
                    "warm_path_policy": "guide_only",
                    "status": prioritized_result.status,
                    "usable": True,
                    "usable_as_partial": False,
                }
            )
            return prioritized_result, "prioritized_guide", "prioritized_guide", guide_sequence
        guide_sequence.append(
            {
                "portfolio_source": "prioritized_guide",
                "source": "prioritized_guide",
                "budget_s": round(prioritized_budget, 3),
                "reference_mode": "",
                "warm_path_policy": "guide_only",
                "status": prioritized_result.status,
                "usable": False,
                "usable_as_partial": False,
            }
        )
        current_state = tuple(agent.start for agent in instance.agents)
        goals = tuple(agent.goal for agent in instance.agents)
        shortest_paths = build_individual_shortest_reference_paths(instance, current_state, goals)
        if shortest_paths is None:
            return None
        plan = {
            agent.id: list(shortest_paths[index])
            for index, agent in enumerate(instance.agents)
        }
        guide_sequence.append(
            {
                "portfolio_source": "individual_shortest_guide",
                "source": "individual_shortest_guide",
                "budget_s": 0.0,
                "reference_mode": "individual_shortest_paths",
                "warm_path_policy": "guide_only",
                "status": "guide_reference",
                "usable": True,
                "usable_as_partial": False,
            }
        )
        return (
            PlannerResult(
                status="solved",
                plan=plan,
                runtime_s=0.0,
                expanded_nodes=prioritized_result.expanded_nodes or 0,
                connectivity_rejections=0,
                metadata={"planner": self.name, "mode": "guide_reference"},
            ),
            "individual_shortest_guide",
            "individual_shortest_guide",
            guide_sequence,
        )

    def _solve_local_window(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        return PrioritizedCCPlanner(
            connectivity_range=self.connectivity_range,
            priority_order=self.priority_order,
        ).solve(instance, time_limit_s)

    def _solve_goal_progress_window(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        return PrioritizedCCPlanner(
            connectivity_range=self.connectivity_range,
            priority_order=self.priority_order,
        ).solve(instance, time_limit_s)

    def _solve_executable_recovery(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
    ) -> PlannerResult:
        attempts = 0
        source = ""
        for planner_name, requested_budget_s in self._executable_recovery_attempts(instance, time_limit_s, start_time):
            time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
            budget_s = min(requested_budget_s, time_remaining)
            if budget_s <= 0.0:
                continue
            attempts += 1
            if planner_name == "connected_step":
                result = ConnectedStepPlanner(
                    initial_reference_mode="replanned_shortest_paths",
                    initial_warm_path_policy="replanned_only",
                ).solve(instance, budget_s)
            elif planner_name == "enhanced_connected_step":
                result = EnhancedConnectedStepPlanner().solve(instance, budget_s)
            else:
                result = PrioritizedCCPlanner(
                    connectivity_range=self.connectivity_range,
                    priority_order=self.priority_order,
                ).solve(instance, budget_s)
            source = planner_name
            metadata = dict(result.metadata)
            metadata["executable_recovery_attempts"] = attempts
            metadata["executable_recovery_source"] = planner_name
            result.metadata = metadata
            if result.status == "solved" and result.plan is not None and validate_plan(instance, result.plan).valid:
                return result
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={
                "planner": self.name,
                "reason": "executable_recovery_failed",
                "executable_recovery_attempts": attempts,
                "executable_recovery_source": source,
            },
        )

    def _solve_subset_bridge(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        return ConnectedStepPlanner(
            initial_reference_mode="replanned_shortest_paths",
            initial_warm_path_policy="replanned_only",
        ).solve(instance, time_limit_s)

    def _subset_bridge_instance(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
        reference_plan: dict[str, list[tuple[int, int]]],
        reference_step: int,
        steps_to_execute: int,
    ) -> Instance:
        target_step = self._subset_bridge_target_step(
            current_positions,
            reference_plan,
            reference_step,
            steps_to_execute,
        )
        target_cells = {
            agent.id: reference_plan[agent.id][min(target_step, len(reference_plan[agent.id]) - 1)]
            for agent in instance.agents
        }
        movable_agents = self._select_subset_bridge_agents(
            instance,
            current_positions,
            target_cells,
        )
        return Instance(
            name=f"{instance.name}_subset_bridge",
            grid=instance.grid,
            agents=[
                AgentSpec(
                    agent.id,
                    current_positions[agent.id],
                    target_cells[agent.id] if agent.id in movable_agents else current_positions[agent.id],
                )
                for agent in instance.agents
            ],
            connectivity=instance.connectivity,
            metadata=dict(instance.metadata),
        )

    def _goal_progress_instance(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
    ) -> Instance:
        return Instance(
            name=f"{instance.name}_goal_progress",
            grid=instance.grid,
            agents=[
                AgentSpec(agent.id, current_positions[agent.id], agent.goal)
                for agent in instance.agents
            ],
            connectivity=instance.connectivity,
            metadata=dict(instance.metadata),
        )

    def _subset_bridge_target_step(
        self,
        current_positions: dict[str, tuple[int, int]],
        reference_plan: dict[str, list[tuple[int, int]]],
        reference_step: int,
        steps_to_execute: int,
    ) -> int:
        current_frontier = self._reference_frontier_index(
            current_positions,
            reference_plan,
            strict_reference_alignment=False,
        )
        base_step = max(reference_step, current_frontier)
        max_reference_step = max((len(path) for path in reference_plan.values()), default=1) - 1
        offset = min(max_reference_step - base_step, self._subset_bridge_offset(steps_to_execute))
        return min(max_reference_step, base_step + max(1, offset))

    def _subset_bridge_offset(self, steps_to_execute: int) -> int:
        return max(1, min(2, steps_to_execute + 1))

    def _subset_bridge_active_limit(self, instance: Instance) -> int:
        if str(instance.metadata.get("scale", "")) == "32x32_12a":
            return 4
        return 3

    def _subset_bridge_support_limit(self, instance: Instance) -> int:
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        if family == "warehouse" and scale == "32x32_12a":
            return 3
        return 2

    def _select_subset_bridge_agents(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
        target_cells: dict[str, tuple[int, int]],
    ) -> set[str]:
        score_rows: list[tuple[tuple[int, int, int, str], str]] = []
        for agent in instance.agents:
            current = current_positions[agent.id]
            target = target_cells[agent.id]
            current_goal_distance = manhattan(current, agent.goal)
            target_goal_distance = manhattan(target, agent.goal)
            guide_delta = manhattan(current, target)
            score_rows.append(
                (
                    (
                        0 if target != current else 1,
                        -(current_goal_distance - target_goal_distance),
                        -guide_delta,
                        agent.id,
                    ),
                    agent.id,
                )
            )
        ordered = [agent_id for _, agent_id in sorted(score_rows)]
        active_limit = self._subset_bridge_active_limit(instance)
        active = {
            agent_id
            for agent_id in ordered
            if target_cells[agent_id] != current_positions[agent_id]
        }
        if len(active) > active_limit:
            active = set(ordered[:active_limit])
        elif len(active) < active_limit:
            for agent_id in ordered:
                active.add(agent_id)
                if len(active) >= active_limit:
                    break
        movable = set(active)
        occupied_by = {cell: agent_id for agent_id, cell in current_positions.items()}
        movable_cap = active_limit + self._subset_bridge_support_limit(instance)
        for agent_id in list(ordered):
            if len(movable) >= movable_cap:
                break
            if agent_id in movable:
                continue
            if any(
                cells_are_connected(
                    current_positions[agent_id],
                    current_positions[chosen_id],
                    spec=instance.connectivity,
                )
                for chosen_id in movable
            ):
                movable.add(agent_id)
        blockers = {
            occupied_by[target_cells[agent_id]]
            for agent_id in list(movable)
            if target_cells[agent_id] in occupied_by
        }
        for blocker_id in ordered:
            if len(movable) >= movable_cap:
                break
            if blocker_id in blockers:
                movable.add(blocker_id)
        return movable

    def _window_instance(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
        reference_plan: dict[str, list[tuple[int, int]]],
        global_step: int,
        horizon: int | None = None,
    ) -> Instance:
        frontier_step = global_step + (horizon if horizon is not None else self.window_size)
        agents = [
            AgentSpec(
                id=agent.id,
                start=current_positions[agent.id],
                goal=reference_plan[agent.id][min(frontier_step, len(reference_plan[agent.id]) - 1)],
            )
            for agent in instance.agents
        ]
        return Instance(
            name=f"{instance.name}_window",
            grid=instance.grid,
            agents=agents,
            connectivity=instance.connectivity,
            metadata=dict(instance.metadata),
        )

    def _can_execute_local_window(
        self,
        instance: Instance,
        reference_plan: dict[str, list[tuple[int, int]]],
        global_step: int,
        steps_to_execute: int,
        local_result: PlannerResult,
        *,
        strict_reference_alignment: bool,
    ) -> bool:
        if local_result.status != "solved" or local_result.plan is None or steps_to_execute <= 0:
            return False
        if not validate_plan(instance, local_result.plan).valid:
            return False
        if not strict_reference_alignment:
            return True
        for agent in instance.agents:
            path = local_result.plan.get(agent.id)
            if not path:
                return False
            end_cell = path[min(steps_to_execute, len(path) - 1)]
            reference_end = reference_plan[agent.id][min(global_step + steps_to_execute, len(reference_plan[agent.id]) - 1)]
            if end_cell != reference_end:
                return False
            for step in range(1, steps_to_execute + 1):
                local_cell = path[min(step, len(path) - 1)]
                reference_cell = reference_plan[agent.id][min(global_step + step, len(reference_plan[agent.id]) - 1)]
                if manhattan(local_cell, reference_cell) > self.max_reference_deviation:
                    return False
        return True

    def _solve_guided_bridge(
        self,
        instance: Instance,
        current_positions: dict[str, tuple[int, int]],
        reference_plan: dict[str, list[tuple[int, int]]],
        reference_step: int,
        time_limit_s: float,
        start_time: float,
        *,
        arrived_agents: set[str] | None = None,
        preferred_offset: int | None = None,
    ) -> GuidedBridgeResult:
        reference_remaining = max((len(path) - 1 - reference_step) for path in reference_plan.values())
        if reference_remaining <= 0:
            return GuidedBridgeResult(result=None, offset=0, attempts=0, max_offset=0, shrinks=0)
        unique_offsets = self._guide_bridge_offsets(instance, reference_remaining, preferred_offset=preferred_offset)
        if not unique_offsets:
            return GuidedBridgeResult(result=None, offset=0, attempts=0, max_offset=0, shrinks=0)
        total_budget = self._guide_bridge_budget(instance, time_limit_s, start_time, attempts=len(unique_offsets))
        per_attempt_budget = max(0.15, total_budget / len(unique_offsets))
        attempts = 0
        already_arrived = (
            set(arrived_agents)
            if arrived_agents is not None
            else {agent.id for agent in instance.agents if current_positions[agent.id] == agent.goal}
        )
        for offset in unique_offsets:
            attempts += 1
            bridge_instance = self._window_instance(instance, current_positions, reference_plan, reference_step, offset)
            bridge_result = self._solve_local_window(bridge_instance, per_attempt_budget)
            if bridge_result.status != "solved" or bridge_result.plan is None:
                continue
            if not validate_plan(bridge_instance, bridge_result.plan).valid:
                continue
            if not self._guide_candidate_progress_metrics(
                current_positions,
                bridge_result.plan,
                list(instance.agents),
                already_arrived,
                reference_plan,
                min(self.replan_interval, offset),
                bridge_instance,
            ):
                continue
            return GuidedBridgeResult(
                result=bridge_result,
                offset=offset,
                attempts=attempts,
                max_offset=max(unique_offsets),
                shrinks=max(0, attempts - 1),
            )
        return GuidedBridgeResult(
            result=None,
            offset=0,
            attempts=attempts,
            max_offset=max(unique_offsets),
            shrinks=max(0, attempts - 1),
        )

    def _predicted_positions_after_prefix(
        self,
        plan: dict[str, list[tuple[int, int]]],
        agents: list[AgentSpec],
        steps_to_execute: int,
    ) -> dict[str, tuple[int, int]] | None:
        predicted_positions: dict[str, tuple[int, int]] = {}
        for agent in agents:
            path = plan.get(agent.id)
            if not path:
                return None
            predicted_positions[agent.id] = path[min(steps_to_execute, len(path) - 1)]
        return predicted_positions

    def _target_distance(
        self,
        positions: dict[str, tuple[int, int]],
        target_instance: Instance,
    ) -> int:
        return sum(manhattan(positions[agent.id], agent.goal) for agent in target_instance.agents)

    def _within_target_deviation(
        self,
        previous_positions: dict[str, tuple[int, int]],
        current_positions: dict[str, tuple[int, int]],
        target_instance: Instance,
    ) -> bool:
        deviation_limit = self._guide_target_deviation_limit(target_instance)
        for agent in target_instance.agents:
            previous_distance = manhattan(previous_positions[agent.id], agent.goal)
            current_distance = manhattan(current_positions[agent.id], agent.goal)
            if current_distance > previous_distance + deviation_limit:
                return False
        return True

    def _guide_candidate_progress_metrics(
        self,
        current_positions: dict[str, tuple[int, int]],
        plan: dict[str, list[tuple[int, int]]] | None,
        agents: list[AgentSpec],
        arrived_agents: set[str],
        reference_plan: dict[str, list[tuple[int, int]]],
        steps_to_execute: int,
        target_instance: Instance,
    ) -> list[str]:
        if plan is None or steps_to_execute <= 0:
            return []
        predicted_positions = self._predicted_positions_after_prefix(
            plan,
            agents,
            steps_to_execute,
        )
        if predicted_positions is None:
            return []
        if not self._within_target_deviation(current_positions, predicted_positions, target_instance):
            return []
        return self._guide_execution_progress_metrics(
            previous_positions=current_positions,
            current_positions=predicted_positions,
            agents=agents,
            arrived_agents=arrived_agents,
            reference_plan=reference_plan,
            target_instance=target_instance,
        )

    def _guide_execution_progress_metrics(
        self,
        *,
        previous_positions: dict[str, tuple[int, int]],
        current_positions: dict[str, tuple[int, int]],
        agents: list[AgentSpec],
        arrived_agents: set[str],
        reference_plan: dict[str, list[tuple[int, int]]],
        target_instance: Instance,
    ) -> list[str]:
        current_arrivals = set(arrived_agents)
        self._update_arrived_agents(current_arrivals, current_positions, agents)
        previous_progress = self._progress_snapshot(
            previous_positions,
            agents,
            arrived_agents,
            reference_frontier=self._reference_frontier_index(
                previous_positions,
                reference_plan,
                strict_reference_alignment=False,
            ),
        )
        current_progress = self._progress_snapshot(
            current_positions,
            agents,
            current_arrivals,
            reference_frontier=self._reference_frontier_index(
                current_positions,
                reference_plan,
                strict_reference_alignment=False,
            ),
        )
        progress_metrics = self._progress_metrics(previous_progress, current_progress)
        if self._target_distance(current_positions, target_instance) < self._target_distance(previous_positions, target_instance):
            progress_metrics = self._merge_progress_modes(progress_metrics, ["bridge_target_distance"])
        return progress_metrics

    def _goal_progress_candidate_metrics(
        self,
        *,
        current_positions: dict[str, tuple[int, int]],
        plan: dict[str, list[tuple[int, int]]] | None,
        agents: list[AgentSpec],
        arrived_agents: set[str],
        steps_to_execute: int,
    ) -> list[str]:
        if plan is None or steps_to_execute <= 0:
            return []
        predicted_positions = self._predicted_positions_after_prefix(plan, agents, steps_to_execute)
        if predicted_positions is None:
            return []
        return self._goal_progress_execution_metrics(
            previous_positions=current_positions,
            current_positions=predicted_positions,
            agents=agents,
            arrived_agents=arrived_agents,
        )

    def _goal_progress_execution_metrics(
        self,
        *,
        previous_positions: dict[str, tuple[int, int]],
        current_positions: dict[str, tuple[int, int]],
        agents: list[AgentSpec],
        arrived_agents: set[str],
    ) -> list[str]:
        current_arrivals = set(arrived_agents)
        self._update_arrived_agents(current_arrivals, current_positions, agents)
        previous_progress = self._progress_snapshot(
            previous_positions,
            agents,
            arrived_agents,
            reference_frontier=0,
        )
        current_progress = self._progress_snapshot(
            current_positions,
            agents,
            current_arrivals,
            reference_frontier=0,
        )
        return self._progress_metrics(previous_progress, current_progress)

    def _can_execute_connected_plan(self, instance: Instance, result: PlannerResult | None) -> bool:
        return result is not None and result.status == "solved" and result.plan is not None and validate_plan(instance, result.plan).valid

    def _can_execute_subset_bridge(
        self,
        instance: Instance,
        result: PlannerResult | None,
        steps_to_execute: int,
    ) -> bool:
        if steps_to_execute <= 0 or result is None or result.status != "solved" or result.plan is None:
            return False
        if not validate_plan(instance, result.plan).valid:
            return False
        return self._reference_prefix_length(instance, result.plan) > steps_to_execute

    def _execute_plan_prefix(
        self,
        instance: Instance,
        agents: list[AgentSpec],
        current_positions: dict[str, tuple[int, int]],
        complete_paths: dict[str, list[tuple[int, int]]],
        plan: dict[str, list[tuple[int, int]]],
        *,
        start_index: int,
        steps_to_execute: int,
        mode: str,
        radius: int,
    ) -> tuple[bool, int]:
        executed_steps = 0
        for step_offset in range(1, steps_to_execute + 1):
            next_positions = {
                agent.id: plan[agent.id][min(start_index + step_offset, len(plan[agent.id]) - 1)]
                for agent in agents
            }
            if self._has_collision(next_positions):
                return False, executed_steps
            if not is_team_connected(next_positions, mode=mode, radius=radius):
                return False, executed_steps
            for agent in agents:
                if not is_legal_move(current_positions[agent.id], next_positions[agent.id]):
                    return False, executed_steps
            current_positions.update(next_positions)
            for agent in agents:
                complete_paths[agent.id].append(current_positions[agent.id])
            executed_steps += 1
        return True, executed_steps

    def _reference_execution_policy(self, allow_reference_execution: bool) -> str:
        return "connected_fallback" if allow_reference_execution else "guide_only"

    def _reference_category(self, allow_reference_execution: bool) -> str:
        return "connected_executable_reference" if allow_reference_execution else "guide_only_reference"

    def _reference_frontier_index(
        self,
        positions: dict[str, tuple[int, int]],
        reference_plan: dict[str, list[tuple[int, int]]],
        *,
        strict_reference_alignment: bool,
    ) -> int:
        if not reference_plan:
            return 0
        max_frontier = max((len(path) for path in reference_plan.values()), default=1) - 1
        frontier = 0
        for step in range(max_frontier + 1):
            if all(
                manhattan(positions[agent_id], path[min(step, len(path) - 1)]) == 0
                if strict_reference_alignment
                else manhattan(positions[agent_id], path[min(step, len(path) - 1)]) <= self.max_reference_deviation
                for agent_id, path in reference_plan.items()
            ):
                frontier = step
        return frontier

    def _guide_target_deviation_limit(self, target_instance: Instance) -> int:
        family = str(target_instance.metadata.get("family", ""))
        scale = str(target_instance.metadata.get("scale", ""))
        deviation_limit = self.max_reference_deviation
        if scale == "24x24_8a":
            deviation_limit = max(deviation_limit, 3)
        if scale == "32x32_12a":
            deviation_limit = max(deviation_limit, 4)
        if family in {"open", "corridor"} and scale == "32x32_12a":
            deviation_limit = max(deviation_limit, 5)
        if family == "warehouse" and scale == "24x24_8a":
            deviation_limit = max(deviation_limit, 4)
        if family == "warehouse" and scale == "32x32_12a":
            deviation_limit = max(deviation_limit, 6)
        return deviation_limit

    def _guide_bridge_offsets(
        self,
        instance: Instance,
        reference_remaining: int,
        *,
        preferred_offset: int | None = None,
    ) -> list[int]:
        scale = str(instance.metadata.get("scale", ""))
        family = str(instance.metadata.get("family", ""))
        raw_offsets = [
            preferred_offset or 0,
            min(self.window_size, reference_remaining),
            max(2, min(self.window_size - 2, reference_remaining)) if self.window_size > 2 else 0,
            max(2, min(self.window_size // 2, reference_remaining)),
            max(1, min(self.replan_interval * 2, reference_remaining)),
            max(1, min(self.replan_interval, reference_remaining)),
            1,
        ]
        if scale == "32x32_12a":
            raw_offsets.insert(2, max(3, min(self.window_size - 1, reference_remaining)))
        if family == "warehouse" and scale == "32x32_12a":
            raw_offsets.insert(3, max(3, min(self.window_size // 2 + 1, reference_remaining)))
        if scale == "24x24_8a":
            raw_offsets = raw_offsets[:5]
        unique_offsets: list[int] = []
        for offset in raw_offsets:
            clipped = min(reference_remaining, max(0, offset))
            if clipped > 0 and clipped not in unique_offsets:
                unique_offsets.append(clipped)
        return unique_offsets

    def _guide_bridge_budget(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
        *,
        attempts: int,
    ) -> float:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        scale = str(instance.metadata.get("scale", ""))
        family = str(instance.metadata.get("family", ""))
        factor = 2.0
        cap = 6.0
        floor = 0.25
        if scale == "24x24_8a":
            factor = 2.4
            cap = 7.5
            floor = 0.35
        if scale == "32x32_12a":
            factor = 3.0
            cap = 10.0
            floor = 0.6
        if family == "warehouse" and scale == "32x32_12a":
            factor = 3.8
            cap = 14.0
            floor = 0.9
        elif family in {"open", "corridor"} and scale == "32x32_12a":
            factor = 3.3
            cap = 11.0
            floor = 0.7
        elif family == "warehouse" and scale == "24x24_8a":
            factor = 2.8
            cap = 8.5
            floor = 0.45
        base_budget = max(floor, self._local_budget(instance, time_limit_s, start_time) * factor)
        return min(base_budget, cap, time_remaining, max(floor, time_remaining / max(1, attempts)))

    def _goal_progress_budget(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
    ) -> float:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        scale = str(instance.metadata.get("scale", ""))
        family = str(instance.metadata.get("family", ""))
        factor = 2.6
        cap = 8.0
        floor = 0.35
        if scale == "24x24_8a":
            factor = 3.2
            cap = 12.0
            floor = 0.5
        if scale == "32x32_12a":
            factor = 4.4
            cap = 20.0
            floor = 1.0
        if family in {"open", "corridor"} and scale == "32x32_12a":
            factor = 4.8
            cap = 24.0
            floor = 1.2
        if family == "warehouse" and scale == "24x24_8a":
            factor = 4.0
            cap = 16.0
            floor = 0.8
        if family == "warehouse" and scale == "32x32_12a":
            factor = 6.0
            cap = 32.0
            floor = 1.8
        base_budget = max(floor, self._local_budget(instance, time_limit_s, start_time) * factor)
        return min(base_budget, cap, time_remaining)

    def _prefer_executable_recovery_after_bridge_miss(self, instance: Instance) -> bool:
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        return (family == "warehouse" and scale in {"24x24_8a", "32x32_12a"}) or (
            family in {"open", "corridor"} and scale == "32x32_12a"
        )

    def _executable_recovery_acceptance_horizon(self, instance: Instance, steps_to_execute: int) -> int:
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        horizon = steps_to_execute
        if family == "warehouse" and scale == "32x32_12a":
            horizon = max(horizon, 4)
        elif family in {"open", "corridor"} and scale == "32x32_12a":
            horizon = max(horizon, 3)
        elif family == "warehouse" and scale == "24x24_8a":
            horizon = max(horizon, 3)
        else:
            horizon = max(horizon, min(2, self.window_size))
        return horizon

    def _executable_recovery_attempts(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
    ) -> list[tuple[str, float]]:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        budgets: list[tuple[str, float]]
        if family == "warehouse" and scale == "32x32_12a":
            budgets = [
                ("connected_step", min(max(4.0, time_remaining * 0.28), 96.0, time_remaining)),
                ("enhanced_connected_step", min(max(2.5, time_remaining * 0.2), 72.0, time_remaining)),
                ("prioritized_cc", min(max(1.2, time_remaining * 0.1), 24.0, time_remaining)),
            ]
        elif family in {"open", "corridor"} and scale == "32x32_12a":
            budgets = [
                ("connected_step", min(max(1.5, time_remaining * 0.14), 28.0, time_remaining)),
                ("enhanced_connected_step", min(max(1.0, time_remaining * 0.09), 18.0, time_remaining)),
                ("prioritized_cc", min(max(0.6, time_remaining * 0.05), 8.0, time_remaining)),
            ]
        elif family == "warehouse" and scale == "24x24_8a":
            budgets = [
                ("connected_step", min(max(1.2, time_remaining * 0.12), 18.0, time_remaining)),
                ("enhanced_connected_step", min(max(0.8, time_remaining * 0.08), 12.0, time_remaining)),
                ("prioritized_cc", min(max(0.5, time_remaining * 0.04), 6.0, time_remaining)),
            ]
        elif scale == "32x32_12a":
            budgets = [
                ("connected_step", min(max(1.0, time_remaining * 0.1), 20.0, time_remaining)),
                ("enhanced_connected_step", min(max(0.7, time_remaining * 0.07), 12.0, time_remaining)),
                ("prioritized_cc", min(max(0.4, time_remaining * 0.03), 6.0, time_remaining)),
            ]
        else:
            budgets = [
                ("connected_step", min(max(0.6, time_remaining * 0.08), 10.0, time_remaining)),
                ("prioritized_cc", min(max(0.3, time_remaining * 0.03), 4.0, time_remaining)),
            ]
        return [(name, budget) for name, budget in budgets if budget > 0.0]

    def _subset_bridge_budget(
        self,
        instance: Instance,
        time_limit_s: float,
        start_time: float,
    ) -> float:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        factor = 5.0
        cap = 18.0
        floor = 1.0
        if family == "warehouse" and scale == "32x32_12a":
            factor = 8.0
            cap = 36.0
            floor = 2.4
        base_budget = max(floor, self._local_budget(instance, time_limit_s, start_time) * factor)
        return min(base_budget, cap, time_remaining)

    def _use_subset_bridge_mode(self, instance: Instance) -> bool:
        return str(instance.metadata.get("family", "")) == "warehouse" and str(instance.metadata.get("scale", "")) == "32x32_12a"

    def _reference_budget(self, instance: Instance, time_limit_s: float, start_time: float) -> float:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        family = str(instance.metadata.get("family", ""))
        scale = str(instance.metadata.get("scale", ""))
        ratio = 0.55
        cap = 45.0
        if scale == "24x24_8a":
            ratio = 0.72
            cap = 120.0
        if scale == "32x32_12a":
            ratio = 0.88
            cap = 360.0
        if family in {"warehouse", "open"} and scale == "24x24_8a":
            ratio = 0.76
            cap = 140.0
        if family in {"warehouse", "open"} and scale == "32x32_12a":
            ratio = 0.93
            cap = 420.0
        return min(max(5.0, time_remaining * ratio), cap, time_remaining)

    def _reference_only_limit(self, instance: Instance, reference_horizon: int) -> int:
        scale = str(instance.metadata.get("scale", ""))
        family = str(instance.metadata.get("family", ""))
        base = self.max_reference_only_windows
        if scale == "32x32_12a":
            base = max(base, reference_horizon + 12)
        elif scale == "24x24_8a":
            base = max(base, reference_horizon // 2 + 10)
        if family in {"warehouse", "open"}:
            base = max(base, reference_horizon + 16)
        return base

    def _local_budget(self, instance: Instance, time_limit_s: float, start_time: float) -> float:
        time_remaining = max(0.001, time_limit_s - (perf_counter() - start_time))
        scale = str(instance.metadata.get("scale", ""))
        if scale == "32x32_12a":
            return min(max(0.2, time_remaining * 0.08), 4.0)
        if scale == "24x24_8a":
            return min(max(0.15, time_remaining * 0.06), 3.0)
        return min(max(0.1, time_remaining * 0.05), 2.0)

    def _is_usable_reference(self, instance: Instance, result: PlannerResult) -> bool:
        return result.status == "solved" and result.plan is not None and validate_plan(instance, result.plan).valid

    def _reference_prefix_length(
        self,
        instance: Instance,
        plan: dict[str, list[tuple[int, int]]] | None,
    ) -> int:
        if plan is None:
            return 0
        agents = list(instance.agents)
        if any(agent.id not in plan or not plan[agent.id] for agent in agents):
            return 0
        positions = {agent.id: agent.start for agent in agents}
        if any(plan[agent.id][0] != agent.start for agent in agents):
            return 0
        max_steps = max(len(plan[agent.id]) for agent in agents)
        mode, radius = resolve_connectivity_rule(instance.connectivity, radius=self.connectivity_range)
        for step in range(1, max_steps):
            next_positions = {
                agent.id: plan[agent.id][min(step, len(plan[agent.id]) - 1)]
                for agent in agents
            }
            if self._has_collision(next_positions):
                return step
            if not is_team_connected(next_positions, mode=mode, radius=radius):
                return step
            for agent in agents:
                if not is_legal_move(positions[agent.id], next_positions[agent.id]):
                    return step
            positions = next_positions
        return max_steps

    def _progress_snapshot(
        self,
        positions: dict[str, tuple[int, int]],
        agents: list[AgentSpec],
        arrived_agents: set[str],
        *,
        reference_frontier: int,
    ) -> ProgressSnapshot:
        return ProgressSnapshot(
            agents_at_goal=sum(1 for agent in agents if positions[agent.id] == agent.goal),
            first_arrival_count=len(arrived_agents),
            remaining_distance=self._remaining_distance(positions, agents),
            reference_frontier=reference_frontier,
        )

    def _progress_snapshot_improved(self, current: ProgressSnapshot, best: ProgressSnapshot) -> bool:
        return (
            current.agents_at_goal,
            current.first_arrival_count,
            -current.remaining_distance,
            current.reference_frontier,
        ) > (
            best.agents_at_goal,
            best.first_arrival_count,
            -best.remaining_distance,
            best.reference_frontier,
        )

    def _progress_metrics(self, previous: ProgressSnapshot, current: ProgressSnapshot) -> list[str]:
        metrics: list[str] = []
        if current.agents_at_goal > previous.agents_at_goal:
            metrics.append("agents_at_goal")
        if current.first_arrival_count > previous.first_arrival_count:
            metrics.append("first_arrival_count")
        if current.reference_frontier > previous.reference_frontier:
            metrics.append("reference_frontier_advance")
        if current.remaining_distance < previous.remaining_distance:
            metrics.append("distance_reduction")
        return metrics

    def _merge_progress_modes(self, existing: list[str], current: list[str]) -> list[str]:
        merged = list(existing)
        for item in current:
            if item not in merged:
                merged.append(item)
        return merged

    def _format_progress_mode(self, progress_modes: list[str]) -> str:
        return "|".join(progress_modes) if progress_modes else "none"

    def _timeline_entry(
        self,
        *,
        step_index: int,
        mode: str,
        progress: ProgressSnapshot,
        progress_metrics: list[str],
        window_failed: bool,
        stall_recovery: bool,
    ) -> dict[str, Any]:
        return {
            "step_index": step_index,
            "mode": mode,
            "window_failed": window_failed,
            "stall_recovery": stall_recovery,
            "agents_at_goal": progress.agents_at_goal,
            "first_arrival_count": progress.first_arrival_count,
            "remaining_distance": progress.remaining_distance,
            "reference_frontier": progress.reference_frontier,
            "progress_metrics": list(progress_metrics),
        }

    def _update_arrived_agents(
        self,
        arrived_agents: set[str],
        positions: dict[str, tuple[int, int]],
        agents: list[AgentSpec],
    ) -> None:
        for agent in agents:
            if positions[agent.id] == agent.goal:
                arrived_agents.add(agent.id)

    def _overall_window_mode(self, local_success_windows: int, fallback_windows: int) -> str:
        if local_success_windows > 0 and fallback_windows > 0:
            return "hybrid_recovery"
        if fallback_windows > 0:
            return "reference_prefix_fallback"
        return "local_window"

    def _result(
        self,
        *,
        status: str,
        instance: Instance,
        plan: dict[str, list[tuple[int, int]]] | None,
        start_time: float,
        expanded_nodes: int,
        connectivity_rejections: int,
        reference_source: str,
        reference_portfolio_source: str,
        reference_attempts: int,
        reference_budget_s: float,
        reference_attempt_sequence: list[dict[str, Any]],
        source_portfolio_successes: int,
        window_failures: int,
        reference_prefix_steps: int,
        local_success_windows: int,
        fallback_windows: int,
        fallback_progress_resets: int,
        stall_recovery_uses: int,
        replans: int,
        window_mode: str,
        best_progress_step: int,
        steps_since_last_progress: int,
        stall_exit_reason: str,
        fallback_progress_mode: str,
        progress_timeline: list[dict[str, Any]],
        reference_rebuilds: int,
        reference_execution_policy: str,
        guide_bridge_attempts: int,
        guide_bridge_successes: int,
        guide_bridge_max_offset: int,
        guide_bridge_progress_resets: int,
        guide_frontier_shrinks: int,
        guide_abandonments: int,
        executable_recovery_attempts: int,
        executable_recovery_successes: int,
        executable_recovery_source: str,
        reason: str = "",
    ) -> PlannerResult:
        metadata = {
            "planner": self.name,
            "mode": "hybrid_window_reference",
            "window_size": self.window_size,
            "replan_interval": self.replan_interval,
            "priority_order": self.priority_order,
            "reference_source": reference_source,
            "reference_attempts": reference_attempts,
            "reference_portfolio_source": reference_portfolio_source,
            "reference_budget_s": round(reference_budget_s, 3),
            "reference_attempt_sequence": reference_attempt_sequence,
            "reference_rebuilds": reference_rebuilds,
            "reference_execution_policy": reference_execution_policy,
            "window_mode": window_mode,
            "window_failures": window_failures,
            "reference_prefix_steps": reference_prefix_steps,
            "local_success_windows": local_success_windows,
            "fallback_windows": fallback_windows,
            "fallback_progress_resets": fallback_progress_resets,
            "stall_recovery_uses": stall_recovery_uses,
            "stall_exit_reason": stall_exit_reason,
            "replans": replans,
            "source_portfolio_attempts": reference_attempts,
            "source_portfolio_successes": source_portfolio_successes,
            "guide_bridge_attempts": guide_bridge_attempts,
            "guide_bridge_successes": guide_bridge_successes,
            "guide_bridge_max_offset": guide_bridge_max_offset,
            "guide_bridge_progress_resets": guide_bridge_progress_resets,
            "guide_frontier_shrinks": guide_frontier_shrinks,
            "guide_abandonments": guide_abandonments,
            "executable_recovery_attempts": executable_recovery_attempts,
            "executable_recovery_successes": executable_recovery_successes,
            "executable_recovery_source": executable_recovery_source,
            "best_progress_step": best_progress_step,
            "steps_since_last_progress": steps_since_last_progress,
            "fallback_progress_mode": fallback_progress_mode,
            "progress_timeline": progress_timeline,
        }
        if reason:
            metadata["reason"] = reason
        return PlannerResult(
            status=status,
            plan=plan,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes,
            connectivity_rejections=connectivity_rejections,
            metadata=metadata,
        )

    def _all_at_goals(self, positions: dict[str, tuple[int, int]], agents: list[AgentSpec]) -> bool:
        return all(positions[agent.id] == agent.goal for agent in agents)

    def _remaining_distance(self, positions: dict[str, tuple[int, int]], agents: list[AgentSpec]) -> int:
        return sum(manhattan(positions[agent.id], agent.goal) for agent in agents)

    def _has_collision(self, positions: dict[str, tuple[int, int]]) -> bool:
        return len(set(positions.values())) != len(positions)
