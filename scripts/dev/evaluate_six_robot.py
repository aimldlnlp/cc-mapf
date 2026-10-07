"""Audit frozen current-tree or future-tree control on six-robot wheel runs.

Run one process per variant; the existing future-tree override is process-local.
Timing covers controller execution only, excluding residual instrumentation.
"""
from argparse import ArgumentParser
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np
from cc_mapf import mujoco_sim as sim
from cc_mapf.experiments import load_instance
import evaluate_future_tree
import evaluate_horizon250
import evaluate_robustness
from reproduce_mujoco import sha


def residuals(positions, velocity, measured, edges, radius, reserve, clearance, horizon):
    predicted = positions + measured * horizon
    normals = np.array([(1., 1.), (1., -1.), (-1., 1.), (-1., -1.)])
    radio = max((float(np.max(normals @ (velocity[i]-velocity[j]) / 8
                              + normals @ (predicted[i]-predicted[j])
                              - radius*(1-reserve))) for i,j,_ in edges), default=0.)
    separation = 0.
    for i in range(len(positions)):
        for j in range(i+1,len(positions)):
            delta = positions[i]-positions[j]
            distance = np.linalg.norm(delta)
            if distance > 1e-9:
                normal = delta/distance
                separation = max(separation, float(clearance-normal @ (predicted[i]-predicted[j])
                    - normal @ (velocity[i]-velocity[j])/8))
    return max(0., radio), max(0., separation)


def main():
    parser = ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument('--variant', choices=['current','future','obstacle'], required=True)
    parser.add_argument('--video')
    own, remaining = parser.parse_known_args()
    output = Path(remaining[remaining.index('--output')+1]).resolve()
    output.mkdir(parents=True,exist_ok=True)
    protocol = dict(variant=own.variant,runner_sha256=sha(__file__),motion_horizon_s=.25,settling_horizon_s=.125)
    if own.variant=='obstacle':
        protocol['obstacle_controller_sha256']=sha(Path(__file__).with_name('obstacle_feedback.py'))
        protocol.update(obstacle_margin_m=.02,max_projection_iterations=64)
    protocol_file = output/'six-robot-protocol.json'
    if protocol_file.exists() and json.loads(protocol_file.read_text())!=protocol:
        raise ValueError('Frozen six-robot protocol changed; choose a fresh output.')
    protocol_file.write_text(json.dumps(protocol,indent=2))
    sys.argv = [sys.argv[0], *remaining]
    original_run, original_velocity = sim.run, sim.connectivity_velocity
    original_hash = evaluate_robustness.controller_hash
    fingerprint = hashlib.sha256((original_hash()+json.dumps(protocol,sort_keys=True)).encode()).hexdigest()
    controller = evaluate_future_tree.candidate if own.variant=='future' else evaluate_horizon250.candidate
    original_summarize = evaluate_robustness.summarize

    def summarize(out,cases,profiles,step_seconds=.625):
        original_summarize(out,cases,profiles,step_seconds)
        text = (out/'SUMMARY.md').read_text().replace('four saved','six-robot saved').replace(
            'Four cases and two position seeds are a screening experiment, not a robustness guarantee.',
            'Six robots; experimental opt-in, not a safety or scaling guarantee.')
        (out/'SUMMARY.md').write_text(text)

    def audited_run(args):
        instance = load_instance(args.config)
        if len(instance.agents) not in (4,6) or (len(instance.agents)==6 and not instance.metadata.get('experimental_six_robot_feedback')):
            raise ValueError('This audit requires four robots or six with explicit experimental feedback.')
        times, radio, clearance, speed = [], [], [], []
        obstacle_audits=[]
        if own.variant=='obstacle':
            import mujoco
            from obstacle_feedback import project
            model=mujoco.MjModel.from_xml_string(sim.wheel_scene_xml(instance,args.cell_size))
            boxes=[(model.geom_pos[g,:2].copy(),model.geom_size[g,:2].copy()) for g in range(model.ngeom) if (model.geom(g).name or '').startswith('wall_')]
            body_radius=max(model.geom(f'robot_geom_{i}').size[0] for i in range(len(instance.agents)))
        worst = None

        def measured_controller(positions,desired,radius,max_speed,measured_velocity=None,
                                reserve=.02,clearance_distance=0.,prediction_seconds=.375):
            nonlocal worst
            horizon = .25 if prediction_seconds==.375 else prediction_seconds
            measured = np.zeros_like(positions) if measured_velocity is None else measured_velocity
            edges = evaluate_future_tree.original_tree(positions+measured*horizon if own.variant in ('future','obstacle') else positions)
            if any(np.abs(positions[i]-positions[j]).sum()>radius+1e-6 for i,j,_ in edges):
                edges = evaluate_future_tree.original_tree(positions)
            start = perf_counter()
            if own.variant=='obstacle':
                corrected,obstacle_audit=project(positions,desired,radius,max_speed,measured,
                    reserve,clearance_distance,horizon,boxes,body_radius)
            else:
                corrected = controller(positions,desired,radius,max_speed,measured_velocity,
                                       reserve,clearance_distance,prediction_seconds)
            times.append(perf_counter()-start)
            if own.variant=='obstacle': obstacle_audits.append(obstacle_audit)
            r,c = residuals(positions,corrected,measured,edges,radius,reserve,clearance_distance,horizon)
            radio.append(r); clearance.append(c)
            speed.append(max(0.,float(np.linalg.norm(corrected,axis=1).max()-max_speed)))
            if worst is None or max(r,c)>worst['residual_m']:
                worst = dict(call=len(times),residual_m=max(r,c),radio_residual_m=r,clearance_residual_m=c,
                             positions=positions.tolist(),measured=measured.tolist(),desired=desired.tolist(),
                             corrected=corrected.tolist(),edges=edges,horizon_s=horizon,reserve=reserve)
            if len(times)%5000==0: print('Controller calls:',len(times),flush=True)
            return corrected

        sim.connectivity_velocity = measured_controller
        if own.video:
            args.video=own.video
            args.preset='showcase'
        try:
            report = original_run(args)
        finally:
            sim.connectivity_velocity = original_velocity
        report['controller_audit'] = dict(variant=own.variant,calls=len(times),
            median_ms=float(np.median(times)*1000),p95_ms=float(np.percentile(times,95)*1000),
            max_ms=max(times)*1000,over_2ms_calls=sum(t>.002 for t in times),
            max_radio_residual_m=max(radio),max_clearance_residual_m=max(clearance),
            radio_violation_calls=sum(r>1e-6 for r in radio),clearance_violation_calls=sum(c>1e-6 for c in clearance),
            max_speed_excess_m_s=max(speed),worst=worst,
            note='Post-projection residuals in equivalent metres; controller timing excludes audit and physics.')
        report['audit_runner_sha256']=sha(__file__)
        if obstacle_audits:
            report['obstacle_audit']=dict(max_residual_m=max(a['obstacle'] for a in obstacle_audits),
                unconverged_calls=sum(not a['converged'] for a in obstacle_audits),
                max_iterations=max(a['iterations'] for a in obstacle_audits),
                max_joint_residual_m=max(max(a[k] for k in ['radio','pair','obstacle']) for a in obstacle_audits))
        if args.report:
            Path(args.report).write_text(json.dumps(report,indent=2))
        print('Controller audit:',json.dumps({k:v for k,v in report['controller_audit'].items() if k!='worst'}),flush=True)
        return report

    sim.run=audited_run
    evaluate_robustness.controller_hash=lambda: fingerprint
    evaluate_robustness.summarize=summarize
    try:
        evaluate_robustness.main()
    finally:
        sim.run=original_run
        sim.connectivity_velocity=original_velocity
        evaluate_robustness.controller_hash=original_hash
        evaluate_robustness.summarize=original_summarize


if __name__=='__main__': main()
