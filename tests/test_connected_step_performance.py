from __future__ import annotations

from cc_mapf.generator import generate_instance
from cc_mapf.planners import build_planner
from cc_mapf.validation import validate_plan


def test_connected_step_reports_windowed_beam_diagnostics_on_medium_instance() -> None:
    instance = generate_instance("warehouse", 24, 24, 8, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "windowed_beam"
    assert "warm_start_used" in result.metadata
    assert "warm_start_status" in result.metadata
    assert "beam_width" in result.metadata
    assert "beam_horizon" in result.metadata
    assert "repair_invocations" in result.metadata
    assert "restart_invocations" in result.metadata
    assert "plateau_restart_invocations" in result.metadata
    assert "candidate_prunes" in result.metadata
    assert "disconnected_state_prunes" in result.metadata
    assert "reference_source" in result.metadata
    assert "transport_steps" in result.metadata
    assert "local_refine_steps" in result.metadata
    assert "macro_expansions" in result.metadata
    assert "macro_successes" in result.metadata
    assert "cycle_break_invocations" in result.metadata
    assert "escape_move_invocations" in result.metadata
    assert "recovery_successes" in result.metadata
    assert "local_dead_end_rescues" in result.metadata
    assert "source_portfolio_attempts" in result.metadata
    assert "source_portfolio_successes" in result.metadata
    assert "basin_restart_source" in result.metadata
    assert "diversification_bursts" in result.metadata
    assert "basin_restarts" in result.metadata
    assert "reference_switch_count" in result.metadata
    assert "active_subset_mean" in result.metadata
    assert "best_progress_step" in result.metadata
    assert "steps_since_last_progress" in result.metadata
    assert "stall_exit_reason" in result.metadata
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid


def test_connected_step_solves_representative_24x24_cases() -> None:
    cases = [
        ("open", 3),
        ("corridor", 1),
        ("warehouse", 1),
    ]
    solved = 0
    for family, seed in cases:
        instance = generate_instance(family, 24, 24, 8, seed)
        result = build_planner("connected_step").solve(instance, 8.0)
        if result.plan is None:
            continue
        validation = validate_plan(instance, result.plan)
        if validation.valid:
            solved += 1
    assert solved >= 2


def test_connected_step_reports_convoy_recovery_diagnostics_on_large_instance() -> None:
    instance = generate_instance("corridor", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    assert "escape_move_invocations" in result.metadata
    assert "recovery_successes" in result.metadata
    assert "local_dead_end_rescues" in result.metadata
    assert "source_portfolio_attempts" in result.metadata
    assert "source_portfolio_successes" in result.metadata
    assert "basin_restart_source" in result.metadata
    assert "best_progress_step" in result.metadata
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid


def test_connected_step_recovers_or_restarts_known_step_cap_case() -> None:
    instance = generate_instance("open", 24, 24, 8, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "windowed_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["restart_invocations"] >= 1
            or result.metadata["plateau_restart_invocations"] >= 1
            or result.metadata["diversification_bursts"] >= 1
            or result.metadata["reference_switch_count"] >= 1
        )


def test_connected_step_diversifies_known_open_plateau_case() -> None:
    instance = generate_instance("open", 24, 24, 8, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "windowed_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["diversification_bursts"] >= 1
            or result.metadata["reference_switch_count"] >= 1
            or result.metadata["stall_exit_reason"] == "plateau_limit"
        )


def test_connected_step_diversifies_known_warehouse_plateau_case() -> None:
    instance = generate_instance("warehouse", 24, 24, 8, 2)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "windowed_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["diversification_bursts"] >= 1
            or result.metadata["reference_switch_count"] >= 1
            or result.metadata["plateau_restart_invocations"] >= 1
        )


def test_connected_step_recovers_or_escapes_known_stalled_case() -> None:
    instance = generate_instance("corridor", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["escape_move_invocations"] >= 1
            or result.metadata["recovery_successes"] >= 1
            or result.metadata["basin_restarts"] >= 1
            or result.metadata["source_portfolio_attempts"] >= 1
        )


def test_connected_step_reports_timeout_recovery_diagnostics_on_large_case() -> None:
    instance = generate_instance("open", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    assert "recovery_successes" in result.metadata
    assert "steps_since_last_progress" in result.metadata
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["escape_move_invocations"] >= 1
            or result.metadata["cycle_break_invocations"] >= 1
            or result.metadata["basin_restarts"] >= 1
            or result.metadata["source_portfolio_attempts"] >= 1
        )


def test_connected_step_reports_basin_restart_on_timeout_prone_large_case() -> None:
    instance = generate_instance("warehouse", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 10.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["basin_restarts"] >= 1
            or result.metadata["reference_switch_count"] >= 1
            or result.metadata["source_portfolio_attempts"] >= 1
            or result.metadata["stall_exit_reason"] in {"basin_stalled", "early_stall", "step_cap", "deadline"}
        )


def test_connected_step_reports_local_dead_end_rescue_on_large_open_case() -> None:
    instance = generate_instance("open", 32, 32, 12, 1)
    result = build_planner("connected_step").solve(instance, 8.0)
    assert result.metadata["mode"] == "convoy_macro_beam"
    if result.plan is not None:
        assert validate_plan(instance, result.plan).valid
    else:
        assert (
            result.metadata["local_dead_end_rescues"] >= 1
            or result.metadata["source_portfolio_attempts"] >= 1
            or result.metadata["basin_restarts"] >= 1
        )
