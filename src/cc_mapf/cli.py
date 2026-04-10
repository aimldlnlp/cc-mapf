from __future__ import annotations

import argparse
from pathlib import Path

from rich.console import Console

from .experiments import generate_from_config, run_batch, solve_single_instance
from .render import render_showcase


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ccmapf", description="Connectivity-constrained MAPF CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Generate suite instances from a YAML config")
    generate_parser.add_argument("--config", required=True, help="Path to suite YAML config")
    generate_parser.add_argument("--output", help="Optional output directory for generated instance YAML files")

    solve_parser = subparsers.add_parser("solve", help="Solve a single instance with one planner")
    solve_parser.add_argument("--config", required=True, help="Path to instance YAML config")
    solve_parser.add_argument("--planner", required=True, help="Planner name")
    solve_parser.add_argument("--time-limit", type=float, default=60.0, help="Planner time limit in seconds")
    solve_parser.add_argument("--output-root", default="artifacts/runs", help="Output root for single-run artifacts")

    batch_parser = subparsers.add_parser("batch", help="Run a full benchmark suite")
    batch_parser.add_argument("--config", required=True, help="Path to suite YAML config")

    render_parser = subparsers.add_parser("render", help="Render showcase artifacts for a completed run")
    render_parser.add_argument("--run", required=True, help="Run directory path")
    render_parser.add_argument("--preset", default="showcase", choices=["showcase", "diagnostic"], help="Render preset")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console()
    if args.command == "generate":
        output_dir = generate_from_config(args.config, output_dir=args.output)
        console.print(f"Generated instances: {output_dir}")
        return 0
    if args.command == "solve":
        run_dir = solve_single_instance(
            args.config,
            args.planner,
            time_limit_s=args.time_limit,
            output_root=args.output_root,
        )
        console.print(f"Single-run artifacts: {run_dir}")
        return 0
    if args.command == "batch":
        run_dir = run_batch(args.config, console=console)
        console.print(f"Batch artifacts: {run_dir}")
        return 0
    if args.command == "render":
        run_dir = Path(args.run)
        showcase_dir = render_showcase(run_dir)
        console.print(f"Rendered {args.preset} artifacts: {showcase_dir}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
