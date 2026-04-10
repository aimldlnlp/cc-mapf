from __future__ import annotations

from pathlib import Path

import csv
import yaml
from rich.console import Console

from cc_mapf.cli import main
from cc_mapf.experiments import load_suite_config, run_batch, suite_time_limit_for_instance
from cc_mapf.generator import generate_instance


def test_generate_command_creates_instance_yaml_files(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.yaml"
    config = {
        "name": "mini_gen",
        "families": ["open"],
        "scales": [{"width": 8, "height": 8, "agents": 3}],
        "seeds": [1, 2],
        "planners": ["cbs", "connected_step"],
        "time_limit_s": 5.0,
        "render": {"enabled": False, "preset": "showcase"},
        "output_root": str(tmp_path / "runs"),
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    output_dir = tmp_path / "generated"
    exit_code = main(["generate", "--config", str(config_path), "--output", str(output_dir)])
    assert exit_code == 0
    yaml_files = sorted(output_dir.glob("*.yaml"))
    assert len(yaml_files) == 2


def test_batch_command_writes_metrics_and_showcase_bundle(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.yaml"
    config = {
        "name": "mini_batch",
        "families": ["open", "corridor", "warehouse", "formation_shift"],
        "scales": [{"width": 8, "height": 8, "agents": 3}],
        "seeds": [1],
        "planners": ["cbs", "connected_step"],
        "time_limit_s": 5.0,
        "render": {
            "enabled": True,
            "preset": "showcase",
            "font_family": "DejaVu Serif",
            "font_weight": "normal",
        },
        "output_root": str(tmp_path / "runs"),
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    exit_code = main(["batch", "--config", str(config_path)])
    assert exit_code == 0
    run_dirs = sorted((tmp_path / "runs").iterdir())
    assert len(run_dirs) == 1
    run_dir = run_dirs[0]
    assert (run_dir / "metrics.csv").exists()
    assert (run_dir / "summary.json").exists()
    assert (run_dir / "progress.log").exists()
    with (run_dir / "metrics.csv").open() as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames is not None
        for column in [
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
        ]:
            assert column in reader.fieldnames
    showcase_dir = run_dir / "showcase"
    assert len(list(showcase_dir.glob("*.png"))) == 7
    assert len(list(showcase_dir.glob("*.gif"))) == 5
    assert (showcase_dir / "showcase_manifest.json").exists()


def test_batch_command_skips_showcase_when_render_disabled(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.yaml"
    config = {
        "name": "mini_batch_no_render",
        "families": ["open"],
        "scales": [{"width": 8, "height": 8, "agents": 3}],
        "seeds": [1],
        "planners": ["cbs"],
        "time_limit_s": 5.0,
        "render": {"enabled": False, "preset": "showcase"},
        "output_root": str(tmp_path / "runs"),
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")

    console = Console(record=True, width=120)
    run_dir = run_batch(config_path, console=console)

    assert (run_dir / "metrics.csv").exists()
    assert (run_dir / "summary.json").exists()
    assert not (run_dir / "showcase").exists()
    assert "Rendered showcase bundle" not in (run_dir / "progress.log").read_text(encoding="utf-8")
    assert "render showcase" not in console.export_text()


def test_suite_time_limit_by_scale_overrides_default(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.yaml"
    config = {
        "name": "limit_override",
        "families": ["open"],
        "scales": [
            {"width": 16, "height": 16, "agents": 4},
            {"width": 24, "height": 24, "agents": 8},
        ],
        "seeds": [1],
        "planners": ["connected_step"],
        "time_limit_s": 30.0,
        "time_limit_s_by_scale": {
            "24x24_8a": 180.0,
        },
        "render": {"enabled": False, "preset": "showcase"},
        "output_root": str(tmp_path / "runs"),
    }
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    suite = load_suite_config(config_path)
    small = generate_instance("open", 16, 16, 4, 1)
    medium = generate_instance("open", 24, 24, 8, 1)
    assert suite_time_limit_for_instance(suite, small) == 30.0
    assert suite_time_limit_for_instance(suite, medium) == 180.0
