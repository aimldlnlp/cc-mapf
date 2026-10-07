"""Evaluate the experimental 250 ms motion horizon without editing production."""
from cc_mapf import mujoco_sim
import evaluate_robustness


assert evaluate_robustness.controller_hash() == '08d599c7e7e7eb1a93494b58c1514896fa0837de7c6b45065f8e6371e0b9ccad'
original = mujoco_sim.connectivity_velocity


def candidate(positions, desired, radius, max_speed, measured_velocity=None,
              reserve=.02, clearance=0., prediction_seconds=.375):
    return original(positions, desired, radius, max_speed, measured_velocity,
                    reserve, clearance, .25 if prediction_seconds == .375 else prediction_seconds)


if __name__ == '__main__':
    mujoco_sim.connectivity_velocity = candidate
    try:
        evaluate_robustness.main()
    finally:
        mujoco_sim.connectivity_velocity = original
