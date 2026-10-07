"""Evaluate the frozen pre-fix controller with the same local runtime."""
import hashlib
import importlib.util
from pathlib import Path
import evaluate_robustness as evaluator

root=Path(__file__).resolve().parents[2]
snapshot=root/'artifacts/mujoco/traction-diagnosis/baseline-mujoco_sim.py'
spec=importlib.util.spec_from_file_location('cc_mapf._traction_baseline',snapshot)
baseline=importlib.util.module_from_spec(spec);spec.loader.exec_module(baseline)
baseline.__file__=str(root/'src/cc_mapf/mujoco_sim.py')
evaluator.mujoco_sim=baseline

def source_hash(folder):
    return hashlib.sha256(b''.join(p.relative_to(folder).as_posix().encode()+
                                  (snapshot.read_bytes() if p==folder/'src/cc_mapf/mujoco_sim.py' else p.read_bytes())
                                  for p in sorted((folder/'src').rglob('*.py')))).hexdigest()

evaluator.source_hash=source_hash
assert evaluator.controller_hash()=='4deb5292712d5bda7f6d30daefad1e1892b6ab2aea4e65bfe137acc0d579a4e6'
evaluator.main()
