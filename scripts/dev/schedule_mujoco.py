"""Compare fixed-segment timing and local detours against frozen official checkpoints."""
from argparse import ArgumentParser, Namespace
import hashlib
import json
from pathlib import Path

from cc_mapf.execution import schedule_plan
from cc_mapf.experiments import load_instance
from cc_mapf.mujoco_sim import run
from cc_mapf.utils import dump_yaml


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--stage', choices=['all', 'schedule', 'simulate'], default='all')
    parser.add_argument('--video', action='store_true')
    parser.add_argument('--tracking-margin', type=float, default=0., help='Explicit execution variant; never changes the frozen reference')
    parser.add_argument('--connectivity-feedback', action='store_true', help='Apply measured-position radio feedback to wheel velocities')
    args = parser.parse_args()
    reference, out = Path(args.reference).resolve(), Path(args.output).resolve()
    if reference == out or out.is_relative_to(reference):
        raise ValueError('Keep variant outputs outside the frozen reference directory.')
    out.mkdir(parents=True, exist_ok=True)
    frozen = json.loads((reference / 'manifest.json').read_text())
    for filename, key in [('instance.yaml', 'instance_sha256'), ('plan.json', 'plan_sha256')]:
        if sha(reference / filename) != frozen[key]:
            raise ValueError('Reference input hashes have changed.')
    instance = load_instance(reference / 'instance.yaml')
    if not 0 <= args.tracking_margin <= .1:
        raise ValueError('Tracking margin must be between 0 and 0.1 cells.')
    plan = {a: [tuple(c) for c in p] for a, p in json.loads((reference / 'plan.json').read_text())['plan'].items()}
    if args.stage in ['all', 'schedule']:
        for detours, name in [(False, 'timing-only'), (True, 'detour')]:
            result = schedule_plan(instance, plan, detours=detours)
            (out / f'{name}.json').write_text(json.dumps(result, indent=2))
            print(name, {k: v for k, v in result.items() if k != 'plan'}, flush=True)
    if args.stage == 'schedule':
        return
    result = json.loads((out / 'detour.json').read_text())
    if result['status'] != 'solved':
        raise RuntimeError('No valid detour trajectory to execute.')
    for i, agent in enumerate(instance.agents):
        assert [tuple(result['plan'][agent.id][k]) for k in result['checkpoint_indices']] == plan[agent.id]
    reference_simulation = json.loads((reference / 'simulation-manifest.json').read_text())
    step_seconds = reference_simulation['step_seconds'] / result['subdivisions']
    root = Path(__file__).resolve().parents[2]
    sources = sorted((root / 'src').rglob('*.py'))
    instance.metadata['tracking_margin_cells'] = args.tracking_margin
    manifest = {'reference_commit': frozen['reference_commit'], 'reference_instance_sha256': frozen['instance_sha256'],
                'reference_plan_sha256': frozen['plan_sha256'], 'variant_plan_sha256': sha(out / 'detour.json'),
                'script_sha256': sha(__file__), 'step_seconds': step_seconds,
                'cell_size_m': reference_simulation['cell_size_m'], 'max_speed_m_s': reference_simulation['max_speed_m_s'],
                'tracking_margin_cells': args.tracking_margin,
                'connectivity_feedback': args.connectivity_feedback,
                'checkpoint_indices': result['checkpoint_indices'],
                'source_sha256': hashlib.sha256(b''.join(p.relative_to(root).as_posix().encode()+p.read_bytes() for p in sources)).hexdigest()}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    rows = []
    for mode in ['replay', 'wheels']:
        config = out / f'{mode}-instance.yaml'
        instance.metadata['connectivity_feedback'] = args.connectivity_feedback and mode == 'wheels'
        dump_yaml(instance.to_dict(), config)
        manifest[mode+'_execution_instance_sha256'] = sha(config)
        (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
        report = run(Namespace(config=str(config), plan=str(out / 'detour.json'), physics=mode=='wheels',
                               drive='wheels' if mode=='wheels' else 'planar', robot_model='soccer', headless=True,
                               cell_size=manifest['cell_size_m'], max_speed=manifest['max_speed_m_s'], step_seconds=step_seconds,
                               video=str(out / f'{mode}.mp4') if args.video else None, report=str(out / f'{mode}.json')))
        checkpoints = [report['waypoint_samples'][k] for k in result['checkpoint_indices']]
        rows.append({'mode': mode, 'completed': report['completed'], 'disconnected_seconds': report['disconnected_seconds'],
                     'contact_steps': report['contact_steps'], 'numerical_warnings': report['numerical_warnings'],
                     'reference_checkpoint_disconnections': sum(not s['connected'] for s in checkpoints),
                     'max_reference_checkpoint_error_m': max(s.get('max_position_error_m', 0) for s in checkpoints),
                     'max_goal_error_m': max(report['final_goal_errors_m']), 'motion_duration_s': (len(result['plan'][instance.agents[0].id])-1)*step_seconds,
                     'continuous_execution_success': report['completed'] and report['numerical_warnings']==0 and report['contact_steps']==0
                                                     and report['disconnected_seconds']==0 and max(report['final_goal_errors_m'])<.02})
        (out / 'comparison.json').write_text(json.dumps(rows, indent=2))
        print(mode, rows[-1], flush=True)
    for filename, key in [('instance.yaml', 'instance_sha256'), ('plan.json', 'plan_sha256')]:
        assert sha(reference / filename) == frozen[key]
    assert sha(out / 'detour.json') == manifest['variant_plan_sha256']


if __name__ == '__main__':
    main()
