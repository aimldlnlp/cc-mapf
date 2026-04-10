from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .environment import DIRECTIONS4, in_bounds, is_free, manhattan
from .model import Cell, Instance, Plan, ValidationResult


def pad_plan(instance: Instance, plan: Plan | None) -> tuple[Plan, list[dict[str, Any]]]:
    normalized: Plan = {}
    missing_paths: list[dict[str, Any]] = []
    source = plan or {}
    for agent in instance.agents:
        raw_path = source.get(agent.id)
        if not raw_path:
            normalized[agent.id] = [agent.start]
            missing_paths.append({"agent": agent.id, "reason": "missing_path"})
            continue
        normalized_path = [tuple(cell) for cell in raw_path]
        if normalized_path[0] != agent.start:
            missing_paths.append(
                {
                    "agent": agent.id,
                    "reason": "bad_start",
                    "expected": list(agent.start),
                    "observed": list(normalized_path[0]),
                }
            )
        normalized[agent.id] = normalized_path
    max_len = max((len(path) for path in normalized.values()), default=1)
    for agent_id, path in normalized.items():
        if not path:
            normalized[agent_id] = [next(agent.start for agent in instance.agents if agent.id == agent_id)]
            path = normalized[agent_id]
        if len(path) < max_len:
            normalized[agent_id] = path + [path[-1]] * (max_len - len(path))
    return normalized, missing_paths


def states_from_plan(plan: Plan) -> list[dict[str, Cell]]:
    if not plan:
        return []
    horizon = max(len(path) for path in plan.values())
    states: list[dict[str, Cell]] = []
    for time_index in range(horizon):
        states.append({agent_id: path[time_index] for agent_id, path in plan.items()})
    return states


def connectivity_components(positions: dict[str, Cell]) -> list[list[str]]:
    if not positions:
        return []
    adjacency: dict[str, set[str]] = {agent_id: set() for agent_id in positions}
    agent_items = list(positions.items())
    for index, (agent_a, cell_a) in enumerate(agent_items):
        for agent_b, cell_b in agent_items[index + 1 :]:
            if manhattan(cell_a, cell_b) == 1:
                adjacency[agent_a].add(agent_b)
                adjacency[agent_b].add(agent_a)
    components: list[list[str]] = []
    unseen = set(positions)
    while unseen:
        seed = next(iter(unseen))
        queue = deque([seed])
        component: list[str] = []
        unseen.remove(seed)
        while queue:
            current = queue.popleft()
            component.append(current)
            for nxt in sorted(adjacency[current]):
                if nxt in unseen:
                    unseen.remove(nxt)
                    queue.append(nxt)
        components.append(sorted(component))
    return components


def validate_state(instance: Instance, positions: dict[str, Cell], time_index: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    move_failures: list[dict[str, Any]] = []
    vertex_conflicts: list[dict[str, Any]] = []
    occupancy: dict[Cell, list[str]] = defaultdict(list)
    for agent in instance.agents:
        cell = positions[agent.id]
        if not in_bounds(instance.grid, cell):
            move_failures.append({"time": time_index, "agent": agent.id, "reason": "out_of_bounds", "cell": list(cell)})
        elif not is_free(instance.grid, cell):
            move_failures.append({"time": time_index, "agent": agent.id, "reason": "obstacle", "cell": list(cell)})
        occupancy[cell].append(agent.id)
    for cell, agents_here in occupancy.items():
        if len(agents_here) > 1:
            vertex_conflicts.append({"time": time_index, "cell": list(cell), "agents": sorted(agents_here)})
    connectivity_failures: list[dict[str, Any]] = []
    components = connectivity_components(positions)
    if len(components) > 1:
        connectivity_failures.append({"time": time_index, "components": components})
    return move_failures, vertex_conflicts, connectivity_failures


def is_legal_move(prev_cell: Cell, next_cell: Cell) -> bool:
    if prev_cell == next_cell:
        return True
    return any((prev_cell[0] + dx, prev_cell[1] + dy) == next_cell for dx, dy in DIRECTIONS4)


def validate_transition(
    instance: Instance,
    previous: dict[str, Cell],
    current: dict[str, Cell],
    time_index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    move_failures: list[dict[str, Any]] = []
    swap_conflicts: list[dict[str, Any]] = []
    for agent in instance.agents:
        prev_cell = previous[agent.id]
        curr_cell = current[agent.id]
        if not is_legal_move(prev_cell, curr_cell):
            move_failures.append(
                {
                    "time": time_index,
                    "agent": agent.id,
                    "reason": "illegal_jump",
                    "from": list(prev_cell),
                    "to": list(curr_cell),
                }
            )
    for index, first in enumerate(instance.agents):
        for second in instance.agents[index + 1 :]:
            if (
                previous[first.id] == current[second.id]
                and previous[second.id] == current[first.id]
                and previous[first.id] != previous[second.id]
            ):
                swap_conflicts.append(
                    {
                        "time": time_index,
                        "agents": sorted([first.id, second.id]),
                        "edge": [list(previous[first.id]), list(current[first.id])],
                    }
                )
    return move_failures, swap_conflicts


def first_arrival_time(path: list[Cell], goal: Cell) -> int | None:
    for index, cell in enumerate(path):
        if cell == goal:
            return index
    return None


def validate_plan(instance: Instance, plan: Plan | None) -> ValidationResult:
    padded_plan, missing_paths = pad_plan(instance, plan)
    states = states_from_plan(padded_plan)
    vertex_conflicts: list[dict[str, Any]] = []
    swap_conflicts: list[dict[str, Any]] = []
    connectivity_failures: list[dict[str, Any]] = []
    move_failures: list[dict[str, Any]] = []
    for time_index, state in enumerate(states):
        state_move_failures, state_vertex_conflicts, state_connectivity_failures = validate_state(instance, state, time_index)
        move_failures.extend(state_move_failures)
        vertex_conflicts.extend(state_vertex_conflicts)
        connectivity_failures.extend(state_connectivity_failures)
        if time_index == 0:
            continue
        transition_move_failures, transition_swap_conflicts = validate_transition(instance, states[time_index - 1], state, time_index)
        move_failures.extend(transition_move_failures)
        swap_conflicts.extend(transition_swap_conflicts)
    arrival_times: list[int] = []
    for agent in instance.agents:
        arrival = first_arrival_time(padded_plan[agent.id], agent.goal)
        if arrival is None:
            move_failures.append({"agent": agent.id, "reason": "goal_not_reached"})
            arrival = len(padded_plan[agent.id]) - 1
        arrival_times.append(arrival)
    makespan = max(arrival_times, default=0)
    sum_of_costs = sum(arrival_times)
    valid = not any([missing_paths, vertex_conflicts, swap_conflicts, connectivity_failures, move_failures])
    return ValidationResult(
        valid=valid,
        makespan=makespan,
        sum_of_costs=sum_of_costs,
        vertex_conflicts=vertex_conflicts,
        swap_conflicts=swap_conflicts,
        connectivity_failures=connectivity_failures,
        move_failures=move_failures,
        missing_paths=missing_paths,
    )
