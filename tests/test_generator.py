from __future__ import annotations

from cc_mapf.generator import generate_instance
from cc_mapf.validation import connectivity_components


def test_generator_is_deterministic_for_seed() -> None:
    first = generate_instance("open", 10, 10, 4, 7)
    second = generate_instance("open", 10, 10, 4, 7)
    assert first.to_dict() == second.to_dict()


def test_generated_starts_and_goals_are_connected() -> None:
    instance = generate_instance("warehouse", 12, 12, 4, 3)
    start_positions = {agent.id: agent.start for agent in instance.agents}
    goal_positions = {agent.id: agent.goal for agent in instance.agents}
    assert len(connectivity_components(start_positions)) == 1
    assert len(connectivity_components(goal_positions)) == 1
