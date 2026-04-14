#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, "src")

import matplotlib

matplotlib.use("Agg")

from cc_mapf.model import RenderConfig
from cc_mapf.render import (
    load_trace,
    load_trace_payload,
    render_failure_reason_breakdown,
    render_planner_success_matrix,
    render_windowed_cc_progress_timeline,
    render_windowed_cc_reference_portfolio,
    select_windowed_cc_record,
)
from cc_mapf.utils import ensure_dir, load_json


def render_advanced_showcase(run_dir: Path, output_name: str = "analysis") -> None:
    run_dir = Path(run_dir)
    output_dir = ensure_dir(run_dir / output_name)
    results = load_json(run_dir / "results.json")
    records = results["records"]
    config = RenderConfig.from_dict(results.get("render_config"))

    render_planner_success_matrix(output_dir / "planner-success-matrix.png", records, config)
    render_failure_reason_breakdown(output_dir / "failure-reason-breakdown.png", records, config)
    render_windowed_cc_reference_portfolio(output_dir / "windowed-cc-reference-portfolio.png", records, config)

    diagnostic_record = select_windowed_cc_record(records)
    if diagnostic_record is not None:
        instance, states, _ = load_trace(run_dir, diagnostic_record)
        payload = load_trace_payload(run_dir, diagnostic_record)
        render_windowed_cc_progress_timeline(
            output_dir / "windowed-cc-progress-timeline.png",
            diagnostic_record,
            instance,
            states,
            payload,
            config,
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/render/render_advanced_visualizations.py <run_directory> [output_folder]")
        sys.exit(1)
    target = Path(sys.argv[1])
    if not target.exists():
        print(f"Error: Directory not found: {target}")
        sys.exit(1)
    render_advanced_showcase(target, sys.argv[2] if len(sys.argv) > 2 else "analysis")
