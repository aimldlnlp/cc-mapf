"""Evaluate frozen wheel feedback on all twelve official four-robot cases."""
from argparse import ArgumentParser, Namespace
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback

from cc_mapf.execution import schedule_plan
from cc_mapf.experiments import load_instance
from cc_mapf.mujoco_sim import run
from cc_mapf.utils import dump_yaml
from cc_mapf.validation import pad_plan, validate_plan
from reproduce_mujoco import sha


CASES = [f'{family}_16x16_4a_s{seed:02d}' for family in
         ['open', 'corridor', 'warehouse', 'formation_shift'] for seed in [1, 2, 3]]


def source_hash(root):
    return hashlib.sha256(b''.join(p.relative_to(root).as_posix().encode()+p.read_bytes()
                                  for p in sorted((root/'src').rglob('*.py')))).hexdigest()


def summarize(out, cases):
    rows = []
    for case in cases:
        path = out/case/'result.json'
        if path.exists():
            rows.extend(json.loads(path.read_text()))
    (out/'results.json').write_text(json.dumps(rows, indent=2))
    if rows:
        with (out/'results.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    lines = ['# Official four-robot evaluation', '',
             f'Completed {len(rows)//2}/{len(cases)} cases. Each case has feedback off/on with the same plan and fixed 0.08-cell margin.', '',
             '| Feedback | End-to-end success | Executed success | Planner/scheduler/error failures |',
             '|---|---:|---:|---:|']
    for feedback in [False, True]:
        subset = [r for r in rows if r['feedback'] == feedback]
        executed = [r for r in subset if r['stage'] == 'executed']
        passed = sum(r['success'] for r in subset)
        lines.append(f'| {feedback} | {passed}/{len(cases)} | {passed}/{len(executed)} | {len(subset)-len(executed)} |')
    lines += ['', 'Missing cases are pending, not counted as successes. Planner/scheduler failures count against end-to-end success. An empty executed denominator is undefined.', '',
              '| Case | Stage | Feedback | Disconnected (s) | Contacts | Goal error (mm) | Settled arrival (s) | Checkpoint error (mm) | Success |',
              '|---|---|---|---:|---:|---:|---:|---:|---|']
    for r in rows:
        def value(key, scale=1):
            return '-' if r[key] is None else f'{r[key]*scale:.3f}'
        lines.append(f"| {r['case']} | {r['stage']} | {r['feedback']} | {value('disconnected_s')} | {value('contact_steps')} | {value('goal_error_m',1000)} | {value('arrival_s')} | {value('checkpoint_error_m',1000)} | {r['success']} |")
    lines += ['', 'Protocol: original planner/generator/validator from the pinned Git commit; official 45 s planner budget. Current strict validation gates execution. The checkpoint scheduler uses quarter steps, existing local half-cell detours, 0.5-cell separation, and its existing 5 s patch budget. No case-specific controller tuning.', '',
              'Physics: soccer wheel/roller model, 1 m/cell, 1 m radio radius, 1 m/s speed cap, 0.375 s per quarter step, 2 s settling. Success requires completion, zero disconnected 2 ms samples, no robot/obstacle contacts, no numerical warnings, and final goal error below 20 mm.', '',
              'The feedback controller and its fixed 0.125 s prediction, 2% motion reserve, and 0.5% settling reserve are frozen by source SHA256. Planned original checkpoints are preserved, but timings can increase and actual positions can differ. Reports include both effects. Zero sampled disconnection is not a continuous-time safety proof.', '',
              'Per-case reference/instance/plan hashes, configs, raw reports, and errors are retained. Optional videos rerun the same saved plan/config. Videos represent execution variants, not unchanged original trajectories.']
    (out/'SUMMARY.md').write_text('\n'.join(lines)+'\n')
    return rows


def prepare_reference(case, args, root, out):
    reference = out/case/'reference'
    reference.parent.mkdir(exist_ok=True)
    if not (reference/'manifest.json').exists():
        subprocess.run([sys.executable, str(root/'scripts/dev/reproduce_mujoco.py'),
                        '--output', str(reference), '--stage', 'plan', '--ref', args.ref,
                        '--case', case], check=True)
    return reference


def evaluate(case, args, root, out):
    folder = out/case
    folder.mkdir(exist_ok=True)
    rows = [dict(case=case, feedback=f, stage='error', planner_status=None, planner_runtime_s=None,
                 detour_count=None, original_motion_s=None, motion_s=None, arrival_s=None,
                 disconnected_s=None, contact_steps=None, numerical_warnings=None, goal_error_m=None,
                 checkpoint_error_m=None, radio_tree_max_m=None, success=False) for f in [False, True]]
    try:
        reference = prepare_reference(case, args, root, out)
        frozen = json.loads((reference/'manifest.json').read_text())
        for name, key in [('instance.yaml','instance_sha256'), ('plan.json','plan_sha256')]:
            assert sha(reference/name) == frozen[key]
        baseline = json.loads((reference/'baseline.json').read_text())
        payload = json.loads((reference/'plan.json').read_text())
        for row in rows:
            row.update(stage='planner_failed', planner_status=baseline['result_status'],
                       planner_runtime_s=baseline['runtime_s'])
        if payload.get('plan') is None or not baseline['validation']['valid']:
            return rows
        instance = load_instance(reference/'instance.yaml')
        plan = {a:[tuple(p) for p in path] for a,path in payload['plan'].items()}
        strict = validate_plan(instance, plan)
        (folder/'strict-validation.json').write_text(json.dumps(strict.to_dict(), indent=2))
        for row in rows:
            row['stage'] = 'strict_validation_failed'
        if not strict.valid:
            return rows
        scheduled = schedule_plan(instance, plan, detours=True)
        plan_file = folder/'detour.json'
        plan_file.write_text(json.dumps(scheduled, indent=2))
        for row in rows:
            row.update(stage='scheduler_failed', detour_count=len(scheduled['detour_transitions']))
        if scheduled['plan'] is None:
            return rows
        padded, _ = pad_plan(instance, plan)
        for agent in instance.agents:
            assert [tuple(scheduled['plan'][agent.id][k]) for k in scheduled['checkpoint_indices']] == padded[agent.id]
        manifest = dict(reference=frozen, variant_plan_sha256=sha(plan_file),
                        source_sha256=source_hash(root), runner_sha256=sha(__file__))
        for row in rows:
            name = 'feedback-on' if row['feedback'] else 'feedback-off'
            config, report_file = folder/(name+'.yaml'), folder/(name+'.json')
            instance.metadata.update(tracking_margin_cells=.08, connectivity_feedback=row['feedback'])
            dump_yaml(instance.to_dict(), config)
            manifest[name+'_config_sha256'] = sha(config)
            report = run(Namespace(config=str(config), plan=str(plan_file), physics=True, drive='wheels',
                                   robot_model='soccer', headless=True, cell_size=1., step_seconds=.375,
                                   max_speed=1., video=str(folder/(name+'.mp4')) if case in args.video_cases else None,
                                   report=str(report_file)))
            checkpoints = [report['waypoint_samples'][k] for k in scheduled['checkpoint_indices']
                           if k < len(report['waypoint_samples'])]
            arrivals = report['goal_arrival_times_s']
            error = max(report['final_goal_errors_m'])
            row.update(stage='executed', original_motion_s=(len(next(iter(padded.values())))-1)*1.5,
                       motion_s=(len(next(iter(scheduled['plan'].values())))-1)*.375,
                       arrival_s=max(arrivals) if all(a is not None for a in arrivals) else None,
                       disconnected_s=report['disconnected_seconds'], contact_steps=report['contact_steps'],
                       numerical_warnings=report['numerical_warnings'], goal_error_m=error,
                       checkpoint_error_m=max(s.get('max_position_error_m',0) for s in checkpoints),
                       radio_tree_max_m=report['max_radio_tree_distance_m'],
                       success=report['completed'] and report['disconnected_seconds']==0 and
                               report['contact_steps']==0 and report['numerical_warnings']==0 and error<.02)
            assert sha(plan_file) == manifest['variant_plan_sha256']
            (folder/'manifest.json').write_text(json.dumps(manifest, indent=2))
            print(case, name, row, flush=True)
        for name, key in [('instance.yaml','instance_sha256'), ('plan.json','plan_sha256')]:
            assert sha(reference/name) == frozen[key]
    except Exception:
        (folder/'error.txt').write_text(traceback.format_exc())
        print(case, 'error; see error.txt', flush=True)
    return rows


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--stage', choices=['plan','all'], default='all')
    parser.add_argument('--ref', default='4e7419e584f6f1633624ffd440296a14d8da769e')
    parser.add_argument('--cases', nargs='+', choices=CASES, default=CASES)
    parser.add_argument('--video-cases', nargs='*', choices=CASES, default=[])
    args = parser.parse_args()
    root, out = Path(__file__).resolve().parents[2], Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    protocol = dict(cases=args.cases, ref=args.ref, source_sha256=source_hash(root),
                    runner_sha256=sha(__file__), tracking_margin_cells=.08, step_seconds=.375,
                    cell_size_m=1., max_speed_m_s=1., planner_budget_s=45., patch_budget_s=5.)
    manifest_file = out/'manifest.json'
    if manifest_file.exists() and json.loads(manifest_file.read_text()) != protocol:
        raise ValueError('Frozen batch protocol/source changed; use another output directory.')
    manifest_file.write_text(json.dumps(protocol, indent=2))
    for case in args.cases:
        assert source_hash(root) == protocol['source_sha256'], 'Controller source changed during batch.'
        if args.stage == 'plan':
            prepare_reference(case, args, root, out)
            continue
        result = out/case/'result.json'
        if not result.exists():
            rows = evaluate(case, args, root, out)
            assert source_hash(root) == protocol['source_sha256'], 'Controller source changed during batch.'
            result.write_text(json.dumps(rows, indent=2))
        summarize(out, args.cases)
    print('Batch complete:', out, flush=True)


if __name__ == '__main__':
    main()
