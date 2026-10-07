"""Run one official-suite case with a pristine planner, then replay its fixed plan."""
from argparse import ArgumentParser, Namespace
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

from cc_mapf.experiments import load_instance
from cc_mapf.mujoco_sim import run
from cc_mapf.validation import validate_plan


WORKER = '''
import json, sys
from pathlib import Path
import cc_mapf
from cc_mapf.experiments import load_suite_config, suite_time_limit_for_instance
from cc_mapf.generator import generate_suite_instances
from cc_mapf.planners import build_planner
from cc_mapf.validation import validate_plan
from cc_mapf.utils import dump_yaml
out, suite_path, case_name = map(Path, sys.argv[1:])
assert Path(cc_mapf.__file__).resolve().is_relative_to(Path.cwd() / 'src')
suite = load_suite_config(suite_path)
instance = next(i for i in generate_suite_instances(suite) if i.name == str(case_name))
assert 'connected_step' in suite.planners
budget = suite_time_limit_for_instance(suite, instance)
result = build_planner('connected_step').solve(instance, budget)
dump_yaml(instance.to_dict(), out / 'instance.yaml')
(out / 'plan.json').write_text(json.dumps(result.to_dict(), indent=2))
validation = validate_plan(instance, result.plan)
(out / 'baseline.json').write_text(json.dumps({
    'case': instance.name, 'planner': 'connected_step', 'time_limit_s': budget,
    'result_status': result.status, 'runtime_s': result.runtime_s,
    'validation': validation.to_dict(), 'suite_case_count': len(generate_suite_instances(suite)),
    'planner_source': str(Path(cc_mapf.__file__).relative_to(Path.cwd()))
}, indent=2))
print(instance.name, result.status, validation.to_dict(), flush=True)
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--stage', choices=['all', 'plan', 'simulate'], default='all')
    parser.add_argument('--ref', default='HEAD')
    parser.add_argument('--suite', default='configs/suites/paper_best_4_6_8_10_official_rerun.yaml')
    parser.add_argument('--case', default='warehouse_16x16_4a_s01')
    parser.add_argument('--step-seconds', type=float, default=1.5)
    parser.add_argument('--video', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if args.stage in ['all', 'plan']:
        if (out / 'original').exists() and any((out / 'original').iterdir()):
            raise FileExistsError('Use a new output directory for planning; --stage simulate reuses frozen evidence.')
        git = ['git', '-c', f'safe.directory={root.as_posix()}']
        revision = subprocess.check_output([*git, 'rev-parse', f'{args.ref}^{{commit}}'], cwd=root, text=True).strip()
        suite_relative = Path(args.suite).as_posix()
        archive = out / 'original-source.tar'
        subprocess.run([*git, 'archive', '--format=tar', f'--output={archive}', revision, 'src', suite_relative], cwd=root, check=True)
        snapshot = out / 'original'
        snapshot.mkdir(exist_ok=True)
        with tarfile.open(archive) as bundle:
            bundle.extractall(snapshot, filter='data')
        worker = out / 'original_worker.py'
        worker.write_text(WORKER, encoding='utf-8')
        environment = {**os.environ, 'PYTHONPATH': str(snapshot / 'src'), 'OPENBLAS_NUM_THREADS': '1', 'OMP_NUM_THREADS': '1'}
        subprocess.run([sys.executable, str(worker), str(out), suite_relative, args.case], cwd=snapshot, env=environment, check=True)
        manifest = {'reference_commit': revision, 'suite': suite_relative, 'suite_sha256': sha(snapshot / suite_relative),
                    'case': args.case, 'instance_sha256': sha(out / 'instance.yaml'), 'plan_sha256': sha(out / 'plan.json'),
                    'original_archive_sha256': sha(archive), 'planner_modified': False}
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    if args.stage == 'plan':
        return
    manifest = json.loads((out / 'manifest.json').read_text())
    baseline = json.loads((out / 'baseline.json').read_text())
    instance = load_instance(out / 'instance.yaml')
    assert sha(out / 'instance.yaml') == manifest['instance_sha256']
    assert sha(out / 'plan.json') == manifest['plan_sha256']
    assert not instance.metadata.get('continuous_execution')
    assert not instance.metadata.get('continuous_refinement')
    assert not instance.metadata.get('tracking_margin_cells', 0)
    payload = json.loads((out / 'plan.json').read_text())
    if payload.get('plan') is None:
        raise RuntimeError(f"Original planner has no plan: {baseline['result_status']}")
    plan = {a: [tuple(p) for p in path] for a, path in payload['plan'].items()}
    validation = validate_plan(instance, plan)
    if not validation.valid:
        raise RuntimeError(f'Original plan fails current strict validation: {validation.to_dict()}')
    (out / 'strict-validation.json').write_text(json.dumps(validation.to_dict(), indent=2))
    grid = baseline['validation']
    if not grid['valid']:
        raise RuntimeError('Reference planner validation failed.')
    sources = sorted((root / 'src').rglob('*.py'))
    manifest.update(step_seconds=args.step_seconds, cell_size_m=1., max_speed_m_s=1., tracking_margin_cells=0,
                    refinement=False, adapter_sha256=sha(__file__),
                    simulation_source_sha256=hashlib.sha256(b''.join(p.relative_to(root).as_posix().encode()+p.read_bytes() for p in sources)).hexdigest())
    (out / 'simulation-manifest.json').write_text(json.dumps(manifest, indent=2))
    rows = []
    for mode in ['replay', 'wheels']:
        report = run(Namespace(config=str(out / 'instance.yaml'), plan=str(out / 'plan.json'), physics=mode=='wheels',
                               drive='wheels' if mode=='wheels' else 'planar', robot_model='soccer', headless=True,
                               cell_size=1., step_seconds=args.step_seconds, max_speed=1.,
                               video=str(out / f'{mode}.mp4') if args.video else None, report=str(out / f'{mode}.json')))
        arrivals = report['goal_arrival_times_s']
        first = report['first_goal_arrival_times_s']
        rows.append({'mode': mode, 'grid_makespan_steps': grid['makespan'], 'grid_sum_of_costs_steps': grid['sum_of_costs'],
                     'grid_settled_sum_of_costs_steps': validation.sum_of_costs,
                     'nominal_makespan_s': grid['makespan']*args.step_seconds,
                     'nominal_sum_of_costs_s': grid['sum_of_costs']*args.step_seconds,
                     'observed_first_arrival_makespan_s': max(first) if all(a is not None for a in first) else None,
                     'observed_first_arrival_sum_of_costs_s': sum(first) if all(a is not None for a in first) else None,
                     'observed_settled_makespan_s': max(arrivals) if all(a is not None for a in arrivals) else None,
                     'observed_settled_sum_of_costs_s': sum(arrivals) if all(a is not None for a in arrivals) else None,
                     'max_goal_error_m': max(report['final_goal_errors_m']), 'contact_steps': report['contact_steps'],
                     'disconnected_seconds': report['disconnected_seconds'], 'waypoint_disconnected_count': report['waypoint_disconnected_count'],
                     'numerical_warnings': report['numerical_warnings'],
                     'physical_success': report['completed'] and report['numerical_warnings']==0 and report['contact_steps']==0
                                         and report['disconnected_seconds']==0 and max(report['final_goal_errors_m'])<.02})
        (out / 'comparison.json').write_text(json.dumps(rows, indent=2))
        print(mode, rows[-1], flush=True)
    with (out / 'comparison.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    assert sha(out / 'instance.yaml') == manifest['instance_sha256']
    assert sha(out / 'plan.json') == manifest['plan_sha256']


if __name__ == '__main__':
    main()
