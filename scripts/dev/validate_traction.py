"""Run the unchanged 24-case stress protocol in four independent processes."""
from concurrent.futures import ThreadPoolExecutor
from argparse import ArgumentParser
import json
from pathlib import Path
import subprocess
import sys
from evaluate_robustness import CASES

root=Path(__file__).resolve().parents[2]
parser=ArgumentParser(description=__doc__)
parser.add_argument('--output',default='artifacts/mujoco/traction-validation-local')
variant=parser.add_mutually_exclusive_group()
variant.add_argument('--baseline',action='store_true')
variant.add_argument('--horizon250',action='store_true')
variant.add_argument('--future-tree',action='store_true')
parser.add_argument('--step-seconds',type=float,default=.375)
parser.add_argument('--reference',default=str(root/'artifacts/mujoco/official12-feedback'))
parser.add_argument('--cases',nargs='+',default=CASES)
parser.add_argument('--profiles',nargs='+')
args=parser.parse_args()
out=Path(args.output).resolve()
out.mkdir(parents=True,exist_ok=True)

def evaluate(case):
    folder=out/'shards'/case
    folder.mkdir(parents=True,exist_ok=True)
    with (folder/'run.log').open('w') as log:
        runner='evaluate_robustness.py'
        if args.baseline: runner='evaluate_traction_baseline.py'
        elif args.horizon250: runner='evaluate_horizon250.py'
        elif args.future_tree: runner='evaluate_future_tree.py'
        command=[sys.executable,str(root/'scripts/dev'/runner),'--reference',args.reference,
                 '--output',str(folder),'--cases',case,'--step-seconds',str(args.step_seconds)]
        if args.profiles: command+=['--profiles',*args.profiles]
        subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
    rows=json.loads((folder/'results.json').read_text())
    print(case,sum(r['success'] for r in rows),'/',len(rows),flush=True)
    return rows

with ThreadPoolExecutor(max_workers=4) as pool:
    rows=[row for group in pool.map(evaluate,args.cases) for row in group]
(out/'results.json').write_text(json.dumps(rows,indent=2))
print('Complete:',sum(r['success'] for r in rows),'/',len(rows),flush=True)
