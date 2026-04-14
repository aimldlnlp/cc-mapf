from __future__ import annotations

import csv
import json
from pathlib import Path
from time import perf_counter

import pytest
import yaml

from cc_mapf.generator import generate_instance
from cc_mapf.cli import main
from cc_mapf.model import AgentSpec, ConnectivitySpec, GridMap, Instance, PlannerResult
from cc_mapf.planners import build_planner
from cc_mapf.planners.prioritized_cc import PrioritizedCCPlanner
from cc_mapf.planners.windowed_cc import GuidedBridgeResult, ReferencePortfolioResult, WindowedCCPlanner
from cc_mapf.validation import validate_plan


def trio_lane_instance() -> Instance:
    return Instance(
        name="trio_lane",
        grid=GridMap(width=7, height=7, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (3, 1)),
            AgentSpec("r2", (1, 2), (3, 2)),
            AgentSpec("r3", (1, 3), (3, 3)),
        ],
        connectivity=ConnectivitySpec(radius=1),
    )


def disconnected_start_instance() -> Instance:
    return Instance(
        name="disconnected_start",
        grid=GridMap(width=8, height=8, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (2, 1)),
            AgentSpec("r2", (6, 6), (5, 6)),
        ],
        connectivity=ConnectivitySpec(radius=1),
    )


def long_lane_instance() -> Instance:
    return Instance(
        name="long_lane",
        grid=GridMap(width=9, height=7, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (5, 1)),
            AgentSpec("r2", (1, 2), (5, 2)),
            AgentSpec("r3", (1, 3), (5, 3)),
        ],
        connectivity=ConnectivitySpec(radius=1),
    )


def four_lane_instance() -> Instance:
    return Instance(
        name="four_lane",
        grid=GridMap(width=10, height=8, obstacles=set()),
        agents=[
            AgentSpec("r1", (1, 1), (6, 1)),
            AgentSpec("r2", (1, 2), (6, 2)),
            AgentSpec("r3", (1, 3), (6, 3)),
            AgentSpec("r4", (1, 4), (6, 4)),
        ],
        connectivity=ConnectivitySpec(radius=1),
        metadata={"family": "warehouse", "scale": "32x32_12a"},
    )


def test_planner_variants_solve_simple_connected_shift() -> None:
    instance = trio_lane_instance()
    for planner_name in ["prioritized_cc", "windowed_cc", "cc_cbs"]:
        result = build_planner(planner_name).solve(instance, 5.0)
        assert result.status == "solved"
        assert result.plan is not None
        assert validate_plan(instance, result.plan).valid


def test_windowed_cc_replans_small_windows_successfully() -> None:
    instance = trio_lane_instance()
    result = WindowedCCPlanner(window_size=1, replan_interval=1).solve(instance, 5.0)
    assert result.status == "solved"
    assert result.plan is not None
    assert validate_plan(instance, result.plan).valid
    assert result.metadata["reference_source"] in {"prioritized_cc", "connected_step"}
    assert result.metadata["window_mode"] in {"local_window", "reference_prefix_fallback", "hybrid_recovery"}


def test_windowed_cc_guide_only_local_success_does_not_raise_scope_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", lambda *args, **kwargs: PrioritizedCCPlanner().solve(instance, 2.0))
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.plan is not None
    assert validate_plan(instance, result.plan).valid
    assert result.metadata["reference_execution_policy"] == "guide_only"


def test_windowed_cc_uses_reference_prefix_fallback_and_reports_hybrid_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1)
    original = planner._solve_local_window
    call_count = {"value": 0}

    def flaky_local(window_instance: Instance, budget: float) -> PlannerResult:
        call_count["value"] += 1
        if call_count["value"] == 1:
            return PlannerResult(
                status="failed",
                plan=None,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
            )
        return original(window_instance, budget)

    monkeypatch.setattr(planner, "_solve_local_window", flaky_local)
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.plan is not None
    assert validate_plan(instance, result.plan).valid
    assert result.metadata["reference_source"] == "prioritized_cc"
    assert result.metadata["window_mode"] == "hybrid_recovery"
    assert result.metadata["window_failures"] >= 1
    assert result.metadata["fallback_windows"] >= 1
    assert result.metadata["reference_prefix_steps"] >= 1
    assert result.metadata["reference_attempts"] >= 1
    assert result.metadata["reference_portfolio_source"]
    assert "reference_budget_s" in result.metadata


def test_windowed_cc_reference_portfolio_falls_through_to_enhanced_source(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1)
    solved_reference = PrioritizedCCPlanner().solve(instance, 5.0)
    attempts: list[str] = []

    def fake_reference_attempt(spec, attempt_instance: Instance, budget_s: float) -> PlannerResult:
        attempts.append(spec.portfolio_source)
        if spec.portfolio_source == "enhanced_connected_step":
            return solved_reference
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": spec.portfolio_source, "reason": "forced_reference_failure"},
        )

    monkeypatch.setattr(planner, "_run_reference_attempt", fake_reference_attempt)
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.metadata["reference_source"] == "enhanced_connected_step"
    assert result.metadata["reference_portfolio_source"] == "enhanced_connected_step"
    assert result.metadata["reference_attempts"] == 3
    assert attempts[:3] == ["prioritized_cc", "connected_step", "enhanced_connected_step"]


def test_windowed_cc_adaptive_fallback_allows_continuing_reference_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_reference_only_windows=1)

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.metadata["window_mode"] == "reference_prefix_fallback"
    assert result.metadata["fallback_windows"] >= 1
    assert result.metadata["fallback_progress_resets"] >= 1
    assert result.metadata["reference_execution_policy"] == "connected_fallback"


def test_windowed_cc_guide_only_reference_never_executes_direct_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    execute_calls = {"count": 0}

    def forbidden_execute(*args, **kwargs):
        execute_calls["count"] += 1
        return False, 0

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1),
    )
    monkeypatch.setattr(
        planner,
        "_solve_goal_progress_window",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_goal_progress_failure"},
        ),
    )
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "windowed_cc", "reason": "forced_executable_recovery_failure"},
        ),
    )
    monkeypatch.setattr(planner, "_execute_plan_prefix", forbidden_execute)
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["reference_execution_policy"] == "guide_only"
    assert result.metadata["guide_bridge_attempts"] >= 2
    assert result.metadata["guide_abandonments"] >= 1
    assert execute_calls["count"] == 0


def test_windowed_cc_guide_local_window_requires_immediate_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=2, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)],
        "r2": [(1, 2), (2, 2), (3, 2), (4, 2), (5, 2)],
        "r3": [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)],
    }
    delayed_window_plan = {
        "r1": [(1, 1), (1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def solved_but_idle_prefix(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="solved",
            plan=delayed_window_plan,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc"},
        )

    bridge_calls = {"count": 0}
    execute_calls = {"count": 0}

    def fake_bridge(*args, **kwargs) -> GuidedBridgeResult:
        bridge_calls["count"] += 1
        return GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=2, shrinks=1)

    def forbidden_execute(*args, **kwargs):
        execute_calls["count"] += 1
        return False, 0

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", solved_but_idle_prefix)
    monkeypatch.setattr(planner, "_solve_guided_bridge", fake_bridge)
    monkeypatch.setattr(
        planner,
        "_solve_goal_progress_window",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_goal_progress_failure"},
        ),
    )
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "windowed_cc", "reason": "forced_executable_recovery_failure"},
        ),
    )
    monkeypatch.setattr(planner, "_execute_plan_prefix", forbidden_execute)
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["reference_execution_policy"] == "guide_only"
    assert bridge_calls["count"] >= 1
    assert execute_calls["count"] == 0


def test_windowed_cc_guided_bridge_ladder_tries_smaller_offsets_until_success(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=4, replan_interval=1)
    current_positions = {agent.id: agent.start for agent in instance.agents}
    reference_plan = {
        "r1": [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)],
        "r2": [(1, 2), (2, 2), (3, 2), (4, 2), (5, 2)],
        "r3": [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)],
    }
    attempted_offsets: list[int] = []

    def selective_local(window_instance: Instance, budget: float) -> PlannerResult:
        offset = window_instance.agents[0].goal[0] - current_positions["r1"][0]
        attempted_offsets.append(offset)
        if offset == 2:
            return PrioritizedCCPlanner().solve(window_instance, 2.0)
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_bridge_miss"},
        )

    monkeypatch.setattr(planner, "_solve_local_window", selective_local)
    bridge = planner._solve_guided_bridge(
        instance,
        current_positions,
        reference_plan,
        0,
        5.0,
        perf_counter(),
    )
    assert bridge.result is not None
    assert bridge.offset == 2
    assert bridge.max_offset >= bridge.offset
    assert bridge.shrinks >= 1
    assert attempted_offsets[0] > bridge.offset
    assert bridge.offset in attempted_offsets


def test_windowed_cc_guided_bridge_rejects_backward_shuffle(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=2, replan_interval=1)
    current_positions = {agent.id: agent.start for agent in instance.agents}
    reference_plan = {
        "r1": [(1, 1), (2, 1), (3, 1), (4, 1), (5, 1)],
        "r2": [(1, 2), (2, 2), (3, 2), (4, 2), (5, 2)],
        "r3": [(1, 3), (2, 3), (3, 3), (4, 3), (5, 3)],
    }
    backward_shuffle = {
        "r1": [(1, 1), (0, 1), (1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (0, 2), (1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (0, 3), (1, 3), (2, 3), (3, 3)],
    }

    monkeypatch.setattr(
        planner,
        "_solve_local_window",
        lambda window_instance, budget: PlannerResult(
            status="solved",
            plan=backward_shuffle,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc"},
        ),
    )
    bridge = planner._solve_guided_bridge(
        instance,
        current_positions,
        reference_plan,
        0,
        5.0,
        perf_counter(),
    )
    assert bridge.result is None
    assert bridge.attempts >= 1


def test_windowed_cc_hard_guide_only_cases_stop_retrying_bridge_after_first_ladder_miss(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = four_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
        "r4": [(1, 4), (2, 4), (3, 4)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    bridge_calls = {"count": 0}
    recovery_calls = {"count": 0}

    def guide_bridge_miss(*args, **kwargs) -> GuidedBridgeResult:
        bridge_calls["count"] += 1
        return GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1)

    def failed_recovery(*args, **kwargs) -> PlannerResult:
        recovery_calls["count"] += 1
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "connected_step", "reason": "forced_executable_recovery_failure"},
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(planner, "_solve_guided_bridge", guide_bridge_miss)
    monkeypatch.setattr(planner, "_solve_executable_recovery", failed_recovery)
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["guide_abandonments"] >= 2
    assert bridge_calls["count"] == 1
    assert recovery_calls["count"] == 2


def test_windowed_cc_executable_recovery_can_rescue_warehouse_style_guide_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1),
    )
    monkeypatch.setattr(
        planner,
        "_solve_goal_progress_window",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_goal_progress_failure"},
        ),
    )
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda recovery_instance, budget_s, start_time: PrioritizedCCPlanner().solve(recovery_instance, 2.0),
    )
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.plan is not None
    assert validate_plan(instance, result.plan).valid
    assert result.metadata["reference_execution_policy"] == "guide_only"
    assert result.metadata["reference_prefix_steps"] == 0
    assert result.metadata["executable_recovery_successes"] >= 1


def test_windowed_cc_executable_recovery_uses_longer_acceptance_horizon_for_warehouse_style_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = four_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
        "r4": [(1, 4), (2, 4), (3, 4)],
    }
    acceptance_steps: list[int] = []

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    monkeypatch.setattr(
        planner,
        "_build_reference_plan",
        fake_reference,
    )
    monkeypatch.setattr(
        planner,
        "_solve_local_window",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_local_failure"},
        ),
    )
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1),
    )
    monkeypatch.setattr(
        planner,
        "_goal_progress_candidate_metrics",
        lambda *, steps_to_execute, **kwargs: acceptance_steps.append(steps_to_execute) or [],
    )
    monkeypatch.setattr(planner, "_can_execute_connected_plan", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda *args, **kwargs: PlannerResult(
            status="solved",
            plan=guide_plan,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "connected_step", "executable_recovery_source": "connected_step"},
        ),
    )
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert acceptance_steps
    assert acceptance_steps[0] == 4


def test_windowed_cc_executable_recovery_not_accepted_counts_window_failure_without_reference_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }
    delayed_recovery_plan = {
        "r1": [(1, 1), (1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1),
    )
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda *args, **kwargs: PlannerResult(
            status="solved",
            plan=delayed_recovery_plan,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "connected_step"},
        ),
    )
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["reference_execution_policy"] == "guide_only"
    assert result.metadata["guide_abandonments"] >= 1
    assert result.metadata["executable_recovery_attempts"] >= 1
    assert result.metadata["reason"] != "reference_execution_invalid"


def test_windowed_cc_subset_bridge_instance_freezes_non_active_agents(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = four_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1)
    current_positions = {agent.id: agent.start for agent in instance.agents}
    reference_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
        "r4": [(1, 4), (2, 4), (3, 4)],
    }

    monkeypatch.setattr(planner, "_subset_bridge_active_limit", lambda _instance: 1)
    monkeypatch.setattr(planner, "_subset_bridge_support_limit", lambda _instance: 0)

    subset_instance = planner._subset_bridge_instance(
        instance,
        current_positions,
        reference_plan,
        reference_step=0,
        steps_to_execute=1,
    )
    moved = [agent.id for agent in subset_instance.agents if agent.goal != agent.start]
    frozen = [agent.id for agent in subset_instance.agents if agent.goal == agent.start]
    assert len(moved) == 1
    assert len(frozen) == 3


def test_windowed_cc_executable_recovery_failure_counts_window_failure_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(result=None, offset=0, attempts=2, max_offset=1, shrinks=1),
    )
    monkeypatch.setattr(
        planner,
        "_solve_executable_recovery",
        lambda *args, **kwargs: PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "connected_step", "reason": "forced_executable_recovery_failure"},
        ),
    )
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["executable_recovery_attempts"] >= 1
    assert result.metadata["reference_execution_policy"] == "guide_only"


def test_windowed_cc_reference_frontier_tracks_current_alignment_step() -> None:
    planner = WindowedCCPlanner(window_size=2, replan_interval=1)
    reference_plan = {
        "r1": [(1, 1), (2, 1), (3, 1), (4, 1)],
        "r2": [(1, 2), (2, 2), (3, 2), (4, 2)],
        "r3": [(1, 3), (2, 3), (3, 3), (4, 3)],
    }
    positions = {
        "r1": (3, 1),
        "r2": (3, 2),
        "r3": (3, 3),
    }
    assert planner._reference_frontier_index(
        positions,
        reference_plan,
        strict_reference_alignment=True,
    ) == 2


def test_windowed_cc_reports_guide_bridge_invalid_when_bridge_execution_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = trio_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)
    guide_plan = {
        "r1": [(1, 1), (2, 1), (3, 1)],
        "r2": [(1, 2), (2, 2), (3, 2)],
        "r3": [(1, 3), (2, 3), (3, 3)],
    }
    bridge_plan = {
        "r1": [(1, 1), (2, 1)],
        "r2": [(1, 2), (2, 2)],
        "r3": [(1, 3), (2, 3)],
    }

    def fake_reference(*args, **kwargs) -> ReferencePortfolioResult:
        return ReferencePortfolioResult(
            result=PlannerResult(
                status="solved",
                plan=guide_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "windowed_cc"},
            ),
            reference_source="individual_shortest_guide",
            portfolio_source="individual_shortest_guide",
            attempts=1,
            successes=1,
            budget_s=0.1,
            attempt_sequence=[],
            failure_reason="",
            usable_as_partial=False,
            allow_reference_execution=False,
        )

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_build_reference_plan", fake_reference)
    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(
        planner,
        "_solve_guided_bridge",
        lambda *args, **kwargs: GuidedBridgeResult(
            result=PlannerResult(
                status="solved",
                plan=bridge_plan,
                runtime_s=0.0,
                expanded_nodes=0,
                connectivity_rejections=0,
                metadata={"planner": "prioritized_cc"},
            ),
            offset=1,
            attempts=1,
            max_offset=1,
            shrinks=0,
        ),
    )
    monkeypatch.setattr(planner, "_execute_plan_prefix", lambda *args, **kwargs: (False, 0))
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "guide_bridge_invalid"


def test_windowed_cc_fails_only_after_window_failure_limit_is_exceeded(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, max_window_failures=1, stall_limit=10)

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(planner, "_progress_metrics", lambda previous, current: [])
    result = planner.solve(instance, 5.0)
    assert result.status == "failed"
    assert result.metadata["stall_exit_reason"] == "window_failure_limit"
    assert result.metadata["fallback_windows"] == 2
    assert result.metadata["window_failures"] == 2


def test_windowed_cc_stall_recovery_is_used_once_and_clears_zero_progress(monkeypatch: pytest.MonkeyPatch) -> None:
    instance = long_lane_instance()
    planner = WindowedCCPlanner(window_size=1, replan_interval=1, stall_limit=1)

    def always_fail_local(window_instance: Instance, budget: float) -> PlannerResult:
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": "prioritized_cc", "reason": "forced_test_failure"},
        )

    progress_responses = iter([[], [], ["reference_frontier_advance"], ["distance_reduction"], ["agents_at_goal"]])

    def scripted_progress(previous, current):
        return next(progress_responses, ["distance_reduction"])

    monkeypatch.setattr(planner, "_solve_local_window", always_fail_local)
    monkeypatch.setattr(planner, "_progress_metrics", scripted_progress)
    result = planner.solve(instance, 5.0)
    assert result.status == "solved"
    assert result.metadata["stall_recovery_uses"] == 1
    assert result.metadata["fallback_windows"] >= 1


def test_windowed_cc_solves_representative_small_benchmark_cases() -> None:
    for family in ["formation_shift", "open"]:
        instance = generate_instance(family, 16, 16, 4, 1)
        result = WindowedCCPlanner(window_size=2, replan_interval=1).solve(instance, 5.0)
        assert result.status == "solved"
        assert result.plan is not None
        assert validate_plan(instance, result.plan).valid


def test_planner_variants_use_failed_status_on_unsatisfied_connectivity() -> None:
    instance = disconnected_start_instance()
    for planner_name in ["prioritized_cc", "windowed_cc", "cc_cbs"]:
        result = build_planner(planner_name).solve(instance, 2.0)
        assert result.status in {"failed", "timeout"}
        assert result.status != "success"


def test_batch_integration_registers_variant_statuses(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.yaml"
    config = {
        "name": "variant_batch",
        "families": ["open"],
        "scales": [{"width": 6, "height": 6, "agents": 2}],
        "seeds": [1],
        "planners": ["prioritized_cc", "windowed_cc", "cc_cbs"],
        "time_limit_s": 5.0,
        "render": {"enabled": False, "preset": "showcase"},
        "output_root": str(tmp_path / "runs"),
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    exit_code = main(["batch", "--config", str(config_path)])
    assert exit_code == 0
    run_dirs = sorted((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    with (run_dirs[0] / "metrics.csv").open() as handle:
        rows = list(csv.DictReader(handle))
    assert {row["planner"] for row in rows} == {"prioritized_cc", "windowed_cc", "cc_cbs"}
    assert all(row["planner_status"] in {"solved", "failed", "timeout"} for row in rows)
    assert all(row["planner_status"] != "success" for row in rows)
    plan_files = sorted((run_dirs[0] / "plans").glob("windowed_cc__*.json"))
    assert plan_files
    payload = json.loads(plan_files[0].read_text(encoding="utf-8"))
    metadata = payload["planner_result"]["metadata"]
    results_payload = json.loads((run_dirs[0] / "results.json").read_text(encoding="utf-8"))
    windowed_record = next(record for record in results_payload["records"] if record["planner"] == "windowed_cc")
    for key in [
        "mode",
        "reference_source",
        "reference_attempts",
        "reference_portfolio_source",
        "reference_budget_s",
        "reference_attempt_sequence",
        "reference_rebuilds",
        "reference_execution_policy",
        "window_mode",
        "window_failures",
        "reference_prefix_steps",
        "local_success_windows",
        "fallback_windows",
        "fallback_progress_resets",
        "guide_bridge_attempts",
        "guide_bridge_successes",
        "guide_bridge_max_offset",
        "guide_bridge_progress_resets",
        "guide_frontier_shrinks",
        "guide_abandonments",
        "executable_recovery_attempts",
        "executable_recovery_successes",
        "executable_recovery_source",
        "stall_recovery_uses",
        "stall_exit_reason",
        "fallback_progress_mode",
    ]:
        assert key in metadata
    for key in [
        "guide_abandonments",
        "executable_recovery_attempts",
        "executable_recovery_successes",
        "executable_recovery_source",
    ]:
        assert key in rows[0]
        assert key in windowed_record
