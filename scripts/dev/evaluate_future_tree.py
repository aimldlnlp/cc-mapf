"""Evaluate future-aware selection among currently connected radio trees."""
import numpy as np
from cc_mapf import mujoco_sim as sim
import evaluate_robustness


original,original_tree=sim.connectivity_velocity,sim.radio_tree
assert evaluate_robustness.controller_hash()=='08d599c7e7e7eb1a93494b58c1514896fa0837de7c6b45065f8e6371e0b9ccad'


def candidate(positions,desired,radius,max_speed,measured_velocity=None,
              reserve=.02,clearance=0.,prediction_seconds=.375):
    horizon=.25 if prediction_seconds==.375 else prediction_seconds
    predicted=positions if measured_velocity is None else positions+measured_velocity*horizon
    edges=original_tree(predicted)
    if any(np.abs(positions[i]-positions[j]).sum()>radius+1e-6 for i,j,_ in edges):
        edges=original_tree(positions)
    sim.radio_tree=lambda _:edges
    try:
        return original(positions,desired,radius,max_speed,measured_velocity,reserve,clearance,horizon)
    finally:
        sim.radio_tree=original_tree


if __name__=='__main__':
    sim.connectivity_velocity=candidate
    try: evaluate_robustness.main()
    finally: sim.connectivity_velocity=original

# ponytail: tree override is process-local; pass the tree explicitly if simulations become threaded.
