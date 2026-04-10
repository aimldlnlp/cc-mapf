from __future__ import annotations

from .model import Instance, Plan, SimulationTrace
from .validation import pad_plan, states_from_plan, validate_plan


def simulate_plan(instance: Instance, plan: Plan | None) -> SimulationTrace:
    padded_plan, _ = pad_plan(instance, plan)
    validation = validate_plan(instance, padded_plan)
    states = states_from_plan(padded_plan)
    return SimulationTrace(states=states, padded_plan=padded_plan, validation=validation)
