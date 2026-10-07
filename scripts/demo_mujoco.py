"""Run the bundled, validated four-robot warehouse demo."""
from argparse import ArgumentParser, Namespace
import json
from pathlib import Path
import sys

import numpy as np
from cc_mapf import mujoco_sim as sim

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/dev'))
from evaluate_future_tree import candidate


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--video', help='Render an MP4; omit for a headless physics check.')
    parser.add_argument('--output', default='artifacts/mujoco/portfolio-demo')
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'report.json'
    if report_path.exists() or (args.video and Path(args.video).exists()):
        parser.error('Choose fresh output paths to preserve existing evidence.')
    original = sim.connectivity_velocity
    sim.connectivity_velocity = candidate
    try:
        report = sim.run(Namespace(
            config=str(ROOT / 'configs/instances/portfolio_warehouse.yaml'),
            plan=str(ROOT / 'configs/plans/portfolio_warehouse.json'),
            physics=True, drive='wheels', robot_model='soccer', preset='showcase',
            headless=True, cell_size=1., step_seconds=.625, max_speed=1.,
            video=args.video, report=str(report_path)))
    finally:
        sim.connectivity_velocity = original
    baseline = json.loads((ROOT / 'docs/results/demo-reference.json').read_text())
    assert report['completed'] and report['contact_steps'] == report['numerical_warnings'] == 0
    assert report['disconnected_seconds'] == 0 and max(report['final_goal_errors_m']) < .02
    for field in ('max_tracking_error_m', 'final_goal_errors_m', 'simulation_seconds'):
        assert np.allclose(report[field], baseline[field], atol=1e-6, rtol=0), field
    print(json.dumps(dict(completed=report['completed'], contacts=report['contact_steps'],
        disconnected_s=report['disconnected_seconds'], goal_mm=1000*max(report['final_goal_errors_m']),
        tracking_mm=1000*report['max_tracking_error_m'], report=str(report_path))))


if __name__ == '__main__':
    main()
