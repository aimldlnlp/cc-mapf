from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from .generator import generate_suite_instances, save_instances
from .model import Instance, PlannerResult, RenderConfig, SuiteConfig
from .planners import build_planner
from .render import planner_summary as render_planner_summary
from .render import render_showcase
from .simulation import simulate_plan
from .utils import dump_json, dump_yaml, ensure_dir, load_yaml, mean, median, plan_to_serializable, scale_label, timestamp_id


@dataclass
class RunLogger:
    path: Path

    def __post_init__(self) -> None:
        self.path.write_text("", encoding="utf-8")

    def log(self, message: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")


def load_suite_config(path: str | Path) -> SuiteConfig:
    return SuiteConfig.from_dict(load_yaml(path))


def load_instance(path: str | Path) -> Instance:
    return Instance.from_dict(load_yaml(path))


def generate_from_config(config_path: str | Path, output_dir: str | Path | None = None) -> Path:
    config = load_suite_config(config_path)
    target_dir = Path(output_dir) if output_dir is not None else ensure_dir(Path("artifacts") / "generated" / f"{timestamp_id()}_{config.name}")
    ensure_dir(target_dir)
    instances = generate_suite_instances(config)
    save_instances(instances, target_dir)
    return target_dir


def solve_single_instance(
    instance_path: str | Path,
    planner_name: str,
    *,
    time_limit_s: float | None = None,
    output_root: str | Path = "artifacts/runs",
) -> Path:
    instance = load_instance(instance_path)
    planner = build_planner(planner_name)
    run_dir = ensure_dir(Path(output_root) / f"{timestamp_id()}_single_{planner_name}_{instance.name}")
    logger = RunLogger(run_dir / "progress.log")
    logger.log(f"Loaded instance {instance.name}")
    dump_yaml(instance.to_dict(), run_dir / "instance.yaml")
    result = planner.solve(instance, time_limit_s or 60.0)
    logger.log(f"Planner {planner_name} finished with status={result.status}")
    record = persist_result(run_dir, instance, planner_name, result)
    summary = summarize_records([record])
    dump_json(summary, run_dir / "summary.json")
    dump_json({"run_id": run_dir.name, "records": [record], "render_config": RenderConfig().to_dict()}, run_dir / "results.json")
    write_metrics_csv([record], run_dir / "metrics.csv")
    return run_dir


def run_batch(config_path: str | Path, *, console: Console | None = None) -> Path:
    console = console or Console()
    suite = load_suite_config(config_path)
    run_dir = ensure_dir(Path(suite.output_root) / f"{timestamp_id()}_{suite.name}")
    logger = RunLogger(run_dir / "progress.log")
    plans_dir = ensure_dir(run_dir / "plans")
    validations_dir = ensure_dir(run_dir / "validation")
    instances_dir = ensure_dir(run_dir / "instances")
    dump_yaml(suite.to_dict(), run_dir / "config_copy.yaml")
    logger.log(f"Created run directory {run_dir}")

    records: list[dict[str, Any]] = []
    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        load_task = progress.add_task("load config", total=1)
        generate_task = progress.add_task("generate/load instances", total=1, start=False, visible=True)
        solve_task = progress.add_task("solve planners", total=1, start=False, visible=True)
        render_task = progress.add_task("render showcase", total=1, start=False, visible=suite.render_enabled)
        summary_task = progress.add_task("write summary", total=1, start=False, visible=True)

        progress.advance(load_task)
        logger.log(f"Loaded suite {suite.name}")

        instances = generate_suite_instances(suite)
        progress.update(generate_task, total=len(instances), completed=0)
        progress.start_task(generate_task)
        for instance in instances:
            dump_yaml(instance.to_dict(), instances_dir / f"{instance.name}.yaml")
            progress.advance(generate_task)
        logger.log(f"Generated {len(instances)} instances")

        total_solves = len(instances) * len(suite.planners)
        progress.update(solve_task, total=total_solves, completed=0)
        progress.start_task(solve_task)
        for planner_index, planner_name in enumerate(suite.planners, start=1):
            planner = build_planner(planner_name)
            logger.log(f"Running planner {planner_name}")
            for instance_index, instance in enumerate(instances, start=1):
                progress.update(
                    solve_task,
                    description=(
                        f"solve planners planner {planner_index}/{len(suite.planners)} "
                        f"{planner_name} instance {instance_index}/{len(instances)} {instance.name}"
                    ),
                )
                result = planner.solve(instance, suite_time_limit_for_instance(suite, instance))
                record = persist_result(
                    run_dir,
                    instance,
                    planner_name,
                    result,
                    plans_dir=plans_dir,
                    validations_dir=validations_dir,
                )
                records.append(record)
                logger.log(
                    f"{planner_name} on {instance.name}: status={record['planner_status']} valid={record['valid']} solved={record['solved']}"
                )
                progress.advance(solve_task)

        summary_data = summarize_records(records)
        results_payload = {
            "run_id": run_dir.name,
            "suite_config": suite.to_dict(),
            "render_config": suite.render.to_dict(),
            "records": records,
        }
        dump_json(results_payload, run_dir / "results.json")
        if suite.render_enabled:
            progress.start_task(render_task)
            render_showcase(run_dir, results_payload=results_payload, summary=summary_data, config=suite.render)
            logger.log("Rendered showcase bundle")
            progress.advance(render_task)
        else:
            logger.log("Skipped showcase rendering because render.enabled is false")

        progress.start_task(summary_task)
        write_metrics_csv(records, run_dir / "metrics.csv")
        dump_json(summary_data, run_dir / "summary.json")
        logger.log("Wrote metrics.csv and summary.json")
        progress.advance(summary_task)

    print_summary_table(console, summary_data, run_dir)
    return run_dir


def suite_time_limit_for_instance(suite: SuiteConfig, instance: Instance) -> float:
    scale = str(
        instance.metadata.get(
            "scale",
            scale_label(instance.grid.width, instance.grid.height, len(instance.agents)),
        )
    )
    return float(suite.time_limit_s_by_scale.get(scale, suite.time_limit_s))


def persist_result(
    run_dir: Path,
    instance: Instance,
    planner_name: str,
    result: PlannerResult,
    *,
    plans_dir: Path | None = None,
    validations_dir: Path | None = None,
) -> dict[str, Any]:
    plans_dir = plans_dir or ensure_dir(run_dir / "plans")
    validations_dir = validations_dir or ensure_dir(run_dir / "validation")
    trace = simulate_plan(instance, result.plan)
    plan_path: Path | None = None
    if result.plan is not None:
        plan_path = plans_dir / f"{planner_name}__{instance.name}.json"
        dump_json(
            {
                "planner": planner_name,
                "instance": instance.name,
                "status": result.status,
                "plan": plan_to_serializable(trace.padded_plan),
                "states": [
                    {agent_id: [cell[0], cell[1]] for agent_id, cell in state.items()}
                    for state in trace.states
                ],
                "validation": trace.validation.to_dict(),
                "planner_result": result.to_dict(),
            },
            plan_path,
        )
    validation_path = validations_dir / f"{planner_name}__{instance.name}.json"
    dump_json(trace.validation.to_dict(), validation_path)
    solved = result.status == "solved" and trace.validation.valid
    failure_reason = ""
    if not solved:
        failure_reason = str(result.metadata.get("reason") or result.metadata.get("failed_agent") or result.status)
    record = {
        "planner": planner_name,
        "instance": instance.name,
        "family": instance.metadata.get("family", "unknown"),
        "scale": instance.metadata.get(
            "scale",
            scale_label(instance.grid.width, instance.grid.height, len(instance.agents)),
        ),
        "seed": int(instance.metadata.get("seed", 0)),
        "planner_status": result.status,
        "valid": trace.validation.valid,
        "solved": solved,
        "has_plan": result.plan is not None,
        "makespan": trace.validation.makespan if result.plan is not None else None,
        "sum_of_costs": trace.validation.sum_of_costs if result.plan is not None else None,
        "runtime_s": round(result.runtime_s, 6),
        "expanded_nodes": result.expanded_nodes,
        "connectivity_rejections": result.connectivity_rejections,
        "planner_mode": result.metadata.get("mode", ""),
        "repair_invocations": int(result.metadata.get("repair_invocations", 0)),
        "restart_invocations": int(result.metadata.get("restart_invocations", 0)),
        "plateau_restart_invocations": int(result.metadata.get("plateau_restart_invocations", 0)),
        "candidate_prunes": int(result.metadata.get("candidate_prunes", 0)),
        "disconnected_state_prunes": int(result.metadata.get("disconnected_state_prunes", 0)),
        "reference_source": result.metadata.get("reference_source", ""),
        "transport_steps": int(result.metadata.get("transport_steps", 0)),
        "local_refine_steps": int(result.metadata.get("local_refine_steps", 0)),
        "macro_expansions": int(result.metadata.get("macro_expansions", 0)),
        "macro_successes": int(result.metadata.get("macro_successes", 0)),
        "cycle_break_invocations": int(result.metadata.get("cycle_break_invocations", 0)),
        "escape_move_invocations": int(result.metadata.get("escape_move_invocations", 0)),
        "recovery_successes": int(result.metadata.get("recovery_successes", 0)),
        "local_dead_end_rescues": int(result.metadata.get("local_dead_end_rescues", 0)),
        "source_portfolio_attempts": int(result.metadata.get("source_portfolio_attempts", 0)),
        "source_portfolio_successes": int(result.metadata.get("source_portfolio_successes", 0)),
        "basin_restart_source": str(result.metadata.get("basin_restart_source", "")),
        "diversification_bursts": int(result.metadata.get("diversification_bursts", 0)),
        "basin_restarts": int(result.metadata.get("basin_restarts", 0)),
        "reference_switch_count": int(result.metadata.get("reference_switch_count", 0)),
        "active_subset_mean": float(result.metadata.get("active_subset_mean", 0.0)),
        "best_progress_step": int(result.metadata.get("best_progress_step", 0)),
        "steps_since_last_progress": int(result.metadata.get("steps_since_last_progress", 0)),
        "stall_exit_reason": str(result.metadata.get("stall_exit_reason", "")),
        "connectivity_failure_count": len(trace.validation.connectivity_failures),
        "vertex_conflict_count": len(trace.validation.vertex_conflicts),
        "swap_conflict_count": len(trace.validation.swap_conflicts),
        "failure_reason": failure_reason,
        "plan_file": str(plan_path.relative_to(run_dir)) if plan_path is not None else None,
        "validation_file": str(validation_path.relative_to(run_dir)),
        "instance_file": f"instances/{instance.name}.yaml",
        "instance_data": instance.to_dict(),
    }
    return record


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "total_records": len(records),
        "planners": {},
        "by_family": {},
        "by_scale": {},
    }
    planners = sorted({record["planner"] for record in records})
    families = sorted({record["family"] for record in records})
    scales = sorted({record["scale"] for record in records})
    for planner in planners:
        summary["planners"][planner] = summarize_subset([record for record in records if record["planner"] == planner])
    for family in families:
        summary["by_family"][family] = {
            planner: summarize_subset(
                [record for record in records if record["family"] == family and record["planner"] == planner]
            )
            for planner in planners
        }
    for scale in scales:
        summary["by_scale"][scale] = {
            planner: summarize_subset(
                [record for record in records if record["scale"] == scale and record["planner"] == planner]
            )
            for planner in planners
        }
    summary["render_summary"] = render_planner_summary(records)
    return summary


def summarize_subset(records: list[dict[str, Any]]) -> dict[str, Any]:
    solved = [record for record in records if record["solved"]]
    makespans = [float(record["makespan"]) for record in solved if record["makespan"] is not None]
    sums = [float(record["sum_of_costs"]) for record in solved if record["sum_of_costs"] is not None]
    runtimes = [float(record["runtime_s"]) for record in records]
    return {
        "total": len(records),
        "solved": len(solved),
        "success_rate": len(solved) / len(records) if records else 0.0,
        "mean_makespan": mean(makespans),
        "median_makespan": median(makespans),
        "mean_sum_of_costs": mean(sums),
        "median_sum_of_costs": median(sums),
        "mean_runtime_s": mean(runtimes),
        "total_connectivity_rejections": sum(int(record["connectivity_rejections"]) for record in records),
        "total_restart_invocations": sum(int(record["restart_invocations"]) for record in records),
        "total_plateau_restart_invocations": sum(int(record["plateau_restart_invocations"]) for record in records),
        "total_escape_move_invocations": sum(int(record["escape_move_invocations"]) for record in records),
        "total_recovery_successes": sum(int(record["recovery_successes"]) for record in records),
        "total_local_dead_end_rescues": sum(int(record["local_dead_end_rescues"]) for record in records),
        "total_source_portfolio_attempts": sum(int(record["source_portfolio_attempts"]) for record in records),
        "total_source_portfolio_successes": sum(int(record["source_portfolio_successes"]) for record in records),
        "total_diversification_bursts": sum(int(record["diversification_bursts"]) for record in records),
        "total_basin_restarts": sum(int(record["basin_restarts"]) for record in records),
        "total_reference_switch_count": sum(int(record["reference_switch_count"]) for record in records),
        "mean_best_progress_step": mean([float(record["best_progress_step"]) for record in records]),
        "mean_steps_since_last_progress": mean([float(record["steps_since_last_progress"]) for record in records]),
    }


def write_metrics_csv(records: list[dict[str, Any]], path: str | Path) -> None:
    if not records:
        return
    fieldnames = [
        "planner",
        "instance",
        "family",
        "scale",
        "seed",
        "planner_status",
        "valid",
        "solved",
        "has_plan",
        "makespan",
        "sum_of_costs",
        "runtime_s",
        "expanded_nodes",
        "connectivity_rejections",
        "planner_mode",
        "repair_invocations",
        "restart_invocations",
        "plateau_restart_invocations",
        "candidate_prunes",
        "disconnected_state_prunes",
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
        "connectivity_failure_count",
        "vertex_conflict_count",
        "swap_conflict_count",
        "failure_reason",
        "plan_file",
        "validation_file",
        "instance_file",
    ]
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field) for field in fieldnames})


def print_summary_table(console: Console, summary: dict[str, Any], run_dir: Path) -> None:
    table = Table(title="Batch Summary", title_style="none")
    table.add_column("Planner")
    table.add_column("Success")
    table.add_column("Mean makespan")
    table.add_column("Mean runtime (s)")
    table.add_column("Conn. rejects")
    for planner, stats in summary["planners"].items():
        table.add_row(
            planner,
            f"{stats['solved']}/{stats['total']} ({stats['success_rate'] * 100:.1f}%)",
            f"{stats['mean_makespan']:.2f}",
            f"{stats['mean_runtime_s']:.3f}",
            str(stats["total_connectivity_rejections"]),
        )
    console.print(table)
    console.print(f"Artifacts: {run_dir}")
