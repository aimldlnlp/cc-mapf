"""Fixed-controller stress screening on four saved official execution plans."""
from argparse import ArgumentParser, Namespace
import csv
import hashlib
import inspect
import json
import math
import re
from pathlib import Path
import traceback

from cc_mapf import mujoco_sim
from cc_mapf.experiments import load_instance
from cc_mapf.utils import dump_yaml
from evaluate_official_mujoco import source_hash
from reproduce_mujoco import sha

CASES = ['open_16x16_4a_s03','corridor_16x16_4a_s01',
         'warehouse_16x16_4a_s03','formation_shift_16x16_4a_s01']
PROFILES = [('nominal',None), ('position-s07',dict(seed=7,position_jitter_m=.02)),
            ('position-s19',dict(seed=19,position_jitter_m=.02)),
            ('dynamics',dict(mass_scale=1.2,friction_scale=.7)),
            ('combined-s07',dict(seed=7,position_jitter_m=.02,mass_scale=1.2,friction_scale=.7)),
            ('combined-s19',dict(seed=19,position_jitter_m=.02,mass_scale=1.2,friction_scale=.7))]


def controller_hash():
    text = inspect.getsource(mujoco_sim.run)
    block = text[text.index('            if args.physics:\n                positions ='):text.index('                mujoco.mj_step(model, data)')]
    text = ''.join(inspect.getsource(f) for f in [mujoco_sim.radio_tree,mujoco_sim.connectivity_velocity,mujoco_sim.wheel_scene_xml])+block
    return hashlib.sha256(text.encode()).hexdigest()


def summarize(out,cases,profiles,step_seconds=.375):
    rows = [json.loads(p.read_text()) for c in cases for name,_ in PROFILES
            if name in profiles and (p:=out/c/(name+'-result.json')).exists()]
    (out/'results.json').write_text(json.dumps(rows,indent=2))
    if rows:
        with (out/'results.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
    lines=['# Fixed-controller robustness screening','',f'Completed {len(rows)}/{len(cases)*len(profiles)} runs.','',
           '| Profile | Success | Completed | Expected |','|---|---:|---:|---:|']
    for name,_ in PROFILES:
        if name not in profiles: continue
        r=[x for x in rows if x['profile']==name]
        lines.append(f"| {name} | {sum(x['success'] for x in r)} | {len(r)} | {len(cases)} |")
    lines+=['','| Case | Profile | Stage | Disconnected (s) | Contacts | Goal error (mm) | Success |',
            '|---|---|---|---:|---:|---:|---|']
    for r in rows:
        value=lambda k,s=1:'-' if r[k] is None else f'{r[k]*s:.3f}'
        lines.append(f"| {r['case']} | {r['profile']} | {r['stage']} | {value('disconnected_s')} | {value('contacts')} | {value('goal_error_m',1000)} | {r['success']} |")
    lines+=['',f'Protocol: saved official cases, original detours and configs. Feedback stays enabled with one frozen controller, 0.08-cell margin, 1 m radio radius, 1 m/s speed cap, {step_seconds} s steps, and 2 s settling. No replanning or per-case tuning.', '',
            'Position samples are uniform in a disk of radius 0.02 m per robot, conditioned on initially connected, contact-free states (up to 10000 rejection samples). Seeds 7 and 19 are recorded with exact offsets and attempt counts. These are admissible-start tests, not recovery from disconnected starts.', '',
            'Dynamics multiply every robot body mass/inertia by 1.2 and every geometry friction coefficient by 0.7, including both surfaces of contacts. This tests simulator parameter variation, not identified real-world uncertainty. Combined profiles apply both changes. Nominal leaves perturbations disabled.', '',
            'Success requires completed simulation, zero disconnected 2 ms samples, no robot/obstacle contacts, no numerical warnings, and final goal error below 20 mm. Setup/execution exceptions count as failures. Four cases and two position seeds are a screening experiment, not a robustness guarantee.']
    (out/'SUMMARY.md').write_text('\n'.join(lines)+'\n')


def main():
    p=ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--step-seconds',type=float,default=.375)
    p.add_argument('--cases',nargs='+',default=CASES)
    p.add_argument('--profiles',nargs='+',choices=[n for n,_ in PROFILES],default=[n for n,_ in PROFILES])
    args=p.parse_args(); root=Path(__file__).resolve().parents[2]
    if not math.isfinite(args.step_seconds) or args.step_seconds<=0: p.error('--step-seconds must be finite and positive')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+',case) for case in args.cases): p.error('--cases must be simple instance names')
    reference,out=Path(args.reference).resolve(),Path(args.output).resolve()
    if out==reference or out.is_relative_to(reference): raise ValueError('Keep stress outputs separate from reference.')
    out.mkdir(parents=True,exist_ok=True)
    protocol=dict(cases=args.cases,profiles=args.profiles,step_seconds=args.step_seconds,controller_sha256=controller_hash(),
                  source_sha256=source_hash(root),runner_sha256=sha(__file__))
    file=out/'manifest.json'
    if file.exists() and json.loads(file.read_text())!=protocol: raise ValueError('Frozen protocol changed; use fresh outputs.')
    file.write_text(json.dumps(protocol,indent=2))
    for case in args.cases:
        folder=out/case;folder.mkdir(exist_ok=True)
        m=json.loads((reference/case/'manifest.json').read_text())
        plan=reference/case/'detour.json'; config=reference/case/'feedback-on.yaml'
        assert sha(plan)==m['variant_plan_sha256'] and sha(config)==m['feedback-on_config_sha256']
        for name,settings in PROFILES:
            if name not in args.profiles: continue
            assert source_hash(root)==protocol['source_sha256']
            result=folder/(name+'-result.json')
            if result.exists(): continue
            row=dict(case=case,profile=name,stage='error',disconnected_s=None,contacts=None,
                     numerical_warnings=None,goal_error_m=None,arrival_s=None,checkpoint_error_m=None,
                     initial_radio_m=None,success=False)
            evidence=dict(reference_plan_sha256=sha(plan),reference_config_sha256=sha(config),protocol=protocol)
            try:
                i=load_instance(config)
                if settings is not None: i.metadata['simulation_perturbation']=settings
                target=folder/(name+'.yaml');dump_yaml(i.to_dict(),target)
                evidence['config_sha256']=sha(target)
                r=mujoco_sim.run(Namespace(config=str(target),plan=str(plan),physics=True,drive='wheels',
                                          robot_model='soccer',headless=True,cell_size=1.,step_seconds=args.step_seconds,
                                          max_speed=1.,video=None,report=str(folder/(name+'.json'))))
                perturb=r['simulation_perturbation'];arrivals=r['goal_arrival_times_s'];err=max(r['final_goal_errors_m'])
                indices=json.loads(plan.read_text())['checkpoint_indices']
                samples=[r['waypoint_samples'][k] for k in indices if k<len(r['waypoint_samples'])]
                row.update(stage='executed',disconnected_s=r['disconnected_seconds'],contacts=r['contact_steps'],
                           numerical_warnings=r['numerical_warnings'],goal_error_m=err,
                           arrival_s=max(arrivals) if all(a is not None for a in arrivals) else None,
                           checkpoint_error_m=max(s.get('max_position_error_m',0) for s in samples),
                           initial_radio_m=perturb['initial_radio_tree_distance_m'] if perturb else None,
                           success=r['completed'] and r['disconnected_seconds']==0 and r['contact_steps']==0
                                   and r['numerical_warnings']==0 and err<.02)
            except Exception: (folder/(name+'-error.txt')).write_text(traceback.format_exc())
            assert source_hash(root)==protocol['source_sha256']
            assert sha(plan)==evidence['reference_plan_sha256'] and sha(config)==evidence['reference_config_sha256']
            (folder/(name+'-manifest.json')).write_text(json.dumps(evidence,indent=2))
            result.write_text(json.dumps(row,indent=2));summarize(out,args.cases,args.profiles,args.step_seconds)
            print(row,flush=True)
    print('Screening complete:',out,flush=True)


if __name__=='__main__': main()
