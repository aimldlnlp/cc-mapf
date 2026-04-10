from __future__ import annotations

from collections import deque
from time import perf_counter

from ..environment import bfs_shortest_path, manhattan, neighbors
from ..model import Cell, Instance, Plan, PlannerResult
from ..validation import connectivity_components


def stepwise_solve(
    instance: Instance,
    *,
    name: str,
    time_limit_s: float,
    enforce_connectivity: bool,
    repair_depth: int,
    max_detours: int,
) -> PlannerResult:
    start_time = perf_counter()
    positions = {agent.id: agent.start for agent in instance.agents}
    goals = {agent.id: agent.goal for agent in instance.agents}
    plan: Plan = {agent.id: [agent.start] for agent in instance.agents}
    agent_order = [agent.id for agent in sorted(instance.agents, key=lambda item: (-manhattan(item.start, item.goal), item.id))]
    connectivity_rejections = 0
    expanded_nodes = 0
    max_steps = max(16, instance.grid.width * instance.grid.height + 4 * len(instance.agents))
    for _ in range(max_steps):
        if perf_counter() - start_time > time_limit_s:
            return PlannerResult(
                status="timeout",
                plan=None,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                metadata={"planner": name},
            )
        if all(positions[agent.id] == goals[agent.id] for agent in instance.agents):
            return PlannerResult(
                status="solved",
                plan=plan,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                metadata={"planner": name},
            )
        candidates = build_candidate_moves(instance, positions, goals, max_detours=max_detours)
        next_state, explored, rejected = first_valid_joint_state(
            instance,
            positions,
            agent_order,
            candidates,
            enforce_connectivity=enforce_connectivity,
        )
        expanded_nodes += explored
        connectivity_rejections += rejected
        if next_state is None and repair_depth > 0:
            sequence, repair_expanded, repair_rejected = repair_sequence(
                instance,
                positions,
                goals,
                agent_order,
                depth_limit=repair_depth,
                max_detours=max_detours,
                enforce_connectivity=enforce_connectivity,
            )
            expanded_nodes += repair_expanded
            connectivity_rejections += repair_rejected
            if sequence:
                for state in sequence:
                    positions = state
                    append_state(plan, positions)
                continue
        elif next_state is not None:
            positions = next_state
            append_state(plan, positions)
            continue
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes,
            connectivity_rejections=connectivity_rejections,
            metadata={"planner": name},
        )
    return PlannerResult(
        status="failed",
        plan=None,
        runtime_s=perf_counter() - start_time,
        expanded_nodes=expanded_nodes,
        connectivity_rejections=connectivity_rejections,
        metadata={"planner": name, "reason": "step_cap"},
    )


def append_state(plan: Plan, state: dict[str, Cell]) -> None:
    for agent_id, cell in state.items():
        plan[agent_id].append(cell)


def build_candidate_moves(
    instance: Instance,
    positions: dict[str, Cell],
    goals: dict[str, Cell],
    *,
    max_detours: int,
) -> dict[str, list[Cell]]:
    candidates: dict[str, list[Cell]] = {}
    occupied = set(positions.values())
    for agent in instance.agents:
        current = positions[agent.id]
        blocked = occupied - {current}
        shortest = bfs_shortest_path(instance.grid, current, goals[agent.id], blocked=blocked)
        preferred = current if shortest is None or len(shortest) == 1 else shortest[1]
        ordered = [preferred, current]
        alternatives = sorted(
            neighbors(instance.grid, current),
            key=lambda cell: (manhattan(cell, goals[agent.id]), cell[0], cell[1]),
        )
        for cell in alternatives:
            if cell not in ordered:
                ordered.append(cell)
            if len(ordered) >= max_detours + 2:
                break
        candidates[agent.id] = ordered
    return candidates


def first_valid_joint_state(
    instance: Instance,
    positions: dict[str, Cell],
    agent_order: list[str],
    candidates: dict[str, list[Cell]],
    *,
    enforce_connectivity: bool,
) -> tuple[dict[str, Cell] | None, int, int]:
    explored = 0
    connectivity_rejections = 0
    assigned: dict[str, Cell] = {}
    used_cells: set[Cell] = set()

    def backtrack(index: int) -> dict[str, Cell] | None:
        nonlocal explored, connectivity_rejections
        if index == len(agent_order):
            explored += 1
            if enforce_connectivity and len(connectivity_components(assigned)) > 1:
                connectivity_rejections += 1
                return None
            return dict(assigned)
        agent_id = agent_order[index]
        current = positions[agent_id]
        for candidate in candidates[agent_id]:
            if candidate in used_cells:
                continue
            if any(
                positions[other] == candidate and assigned.get(other) == current
                for other in assigned
            ):
                continue
            assigned[agent_id] = candidate
            used_cells.add(candidate)
            result = backtrack(index + 1)
            if result is not None:
                return result
            used_cells.remove(candidate)
            assigned.pop(agent_id)
        return None

    return backtrack(0), explored, connectivity_rejections


def enumerate_joint_states(
    instance: Instance,
    positions: dict[str, Cell],
    agent_order: list[str],
    candidates: dict[str, list[Cell]],
    *,
    enforce_connectivity: bool,
    limit: int = 32,
) -> tuple[list[dict[str, Cell]], int, int]:
    results: list[dict[str, Cell]] = []
    explored = 0
    connectivity_rejections = 0
    assigned: dict[str, Cell] = {}
    used_cells: set[Cell] = set()

    def backtrack(index: int) -> None:
        nonlocal explored, connectivity_rejections
        if len(results) >= limit:
            return
        if index == len(agent_order):
            explored += 1
            if enforce_connectivity and len(connectivity_components(assigned)) > 1:
                connectivity_rejections += 1
                return
            results.append(dict(assigned))
            return
        agent_id = agent_order[index]
        current = positions[agent_id]
        for candidate in candidates[agent_id]:
            if candidate in used_cells:
                continue
            if any(
                positions[other] == candidate and assigned.get(other) == current
                for other in assigned
            ):
                continue
            assigned[agent_id] = candidate
            used_cells.add(candidate)
            backtrack(index + 1)
            used_cells.remove(candidate)
            assigned.pop(agent_id)
            if len(results) >= limit:
                return

    backtrack(0)
    return results, explored, connectivity_rejections


def repair_sequence(
    instance: Instance,
    start_positions: dict[str, Cell],
    goals: dict[str, Cell],
    agent_order: list[str],
    *,
    depth_limit: int,
    max_detours: int,
    enforce_connectivity: bool,
) -> tuple[list[dict[str, Cell]] | None, int, int]:
    start_cost = total_distance(start_positions, goals)
    queue = deque([(start_positions, [])])
    seen = {state_key(agent_order, start_positions)}
    explored_total = 0
    connectivity_rejections = 0
    while queue:
        positions, prefix = queue.popleft()
        if len(prefix) >= depth_limit:
            continue
        candidates = build_candidate_moves(instance, positions, goals, max_detours=max_detours)
        next_states, explored, rejected = enumerate_joint_states(
            instance,
            positions,
            agent_order,
            candidates,
            enforce_connectivity=enforce_connectivity,
            limit=24,
        )
        explored_total += explored
        connectivity_rejections += rejected
        for next_state in next_states:
            key = state_key(agent_order, next_state)
            if key in seen:
                continue
            seen.add(key)
            sequence = prefix + [next_state]
            if all(next_state[agent.id] == goals[agent.id] for agent in instance.agents):
                return sequence, explored_total, connectivity_rejections
            if total_distance(next_state, goals) < start_cost:
                return sequence, explored_total, connectivity_rejections
            queue.append((next_state, sequence))
    return None, explored_total, connectivity_rejections


def total_distance(positions: dict[str, Cell], goals: dict[str, Cell]) -> int:
    return sum(manhattan(cell, goals[agent_id]) for agent_id, cell in positions.items())


def state_key(agent_order: list[str], state: dict[str, Cell]) -> tuple[Cell, ...]:
    return tuple(state[agent_id] for agent_id in agent_order)
