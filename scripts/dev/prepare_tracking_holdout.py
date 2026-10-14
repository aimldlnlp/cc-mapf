"""Freeze plans using the pinned original planner; larger teams are opt-in."""
from concurrent.futures import ThreadPoolExecutor
from argparse import ArgumentParser
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from cc_mapf.experiments import load_instance
from cc_mapf.execution import schedule_plan
from cc_mapf.utils import dump_yaml
from cc_mapf.validation import validate_plan
from reproduce_mujoco import WORKER,sha

root=Path(__file__).resolve().parents[2]
parser=ArgumentParser(description=__doc__)
parser.add_argument('--output',default=str(root/'artifacts/mujoco/tracking-holdout-reference'))
parser.add_argument('--size',type=int,choices=[16,20,24,28],default=20)
parser.add_argument('--seed',type=int,default=41)
parser.add_argument('--agents',type=int,choices=[4,6],default=4)
parser.add_argument('--families',nargs='+',choices=['open','corridor','warehouse','formation_shift'],default=['open','corridor','warehouse','formation_shift'])
args=parser.parse_args()
if args.seed<0: parser.error('--seed must be nonnegative')
out=Path(args.output).resolve()
if (out/'original-source.tar').exists(): raise FileExistsError('Heldout plans are already frozen; reuse them or choose a fresh --output directory.')
out.mkdir(parents=True,exist_ok=True)
ref='4e7419e584f6f1633624ffd440296a14d8da769e'
families=args.families
suite=dict(name='tracking_holdout',families=families,scales=[dict(width=args.size,height=args.size,agents=args.agents)],
           seeds=[args.seed],planners=['connected_step'],time_limit_s=45.,render=dict(enabled=False),output_root='artifacts/runs')
dump_yaml(suite,out/'suite.yaml')
archive=out/'original-source.tar'
subprocess.run(['git','-c',f'safe.directory={root.as_posix()}','archive','--format=tar',
                f'--output={archive}',ref,'src'],cwd=root,check=True)
original=out/'original';original.mkdir(exist_ok=True)
with tarfile.open(archive) as bundle: bundle.extractall(original,filter='data')
worker=out/'original_worker.py';worker.write_text(WORKER)
environment={**os.environ,'PYTHONPATH':str(original/'src'),'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}

def prepare(family):
    case=f'{family}_{args.size}x{args.size}_{args.agents}a_s{args.seed:02d}'
    folder=out/case;folder.mkdir(exist_ok=True)
    with (folder/'planner.log').open('w') as log:
        subprocess.run([sys.executable,str(worker),str(folder),str(out/'suite.yaml'),case],
                        cwd=original,env=environment,stdout=log,stderr=subprocess.STDOUT,check=True)
    instance=load_instance(folder/'instance.yaml')
    payload=json.loads((folder/'plan.json').read_text())
    if not payload.get('plan'): raise RuntimeError(f'{case}: original planner has no solution')
    plan={a:[tuple(p) for p in path] for a,path in payload['plan'].items()}
    assert validate_plan(instance,plan).valid
    scheduled=schedule_plan(instance,plan,detours=True,experimental_six=args.agents==6)
    (folder/'detour.json').write_text(json.dumps(scheduled,indent=2))
    if scheduled['status']!='solved': raise RuntimeError(f'{case}: scheduling failed')
    instance.metadata.update(tracking_margin_cells=.08,connectivity_feedback=True)
    if args.agents==6: instance.metadata['experimental_six_robot_feedback']=True
    dump_yaml(instance.to_dict(),folder/'feedback-on.yaml')
    manifest=dict(reference_commit=ref,planner_modified=False,seed=args.seed,grid=[args.size,args.size],agents=args.agents,
                  original_archive_sha256=sha(archive),suite_sha256=sha(out/'suite.yaml'),
                  original_plan_sha256=sha(folder/'plan.json'),instance_sha256=sha(folder/'instance.yaml'),
                  variant_plan_sha256=sha(folder/'detour.json'))
    manifest['feedback-on_config_sha256']=sha(folder/'feedback-on.yaml')
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2))
    print(case,'prepared',flush=True)
    return case
def prepare_recorded(family):
    case=f'{family}_{args.size}x{args.size}_{args.agents}a_s{args.seed:02d}'
    folder=out/case
    try:
        prepare(family)
        result=dict(case=case,stage='prepared',success=True)
    except Exception as exc:
        if args.agents==4: raise
        result=dict(case=case,stage='preparation_failed',success=False,error=f'{type(exc).__name__}: {exc}')
        print(result,flush=True)
    folder.mkdir(exist_ok=True)
    (folder/'preparation-result.json').write_text(json.dumps(result,indent=2))
    return case

# ponytail: serialize six-agent searches so the fixed five-second detour budget
# is not consumed by competing planner jobs; four-agent behavior stays parallel.
with ThreadPoolExecutor(max_workers=1 if args.agents==6 else 4) as pool:
    cases=list(pool.map(prepare_recorded,families))
(out/'cases.json').write_text(json.dumps(cases))
