from __future__ import annotations

import heapq
from itertools import count

from ..environment import manhattan, neighbors
from ..model import Cell, GridMap


def space_time_a_star(
    grid: GridMap,
    start: Cell,
    goal: Cell,
    *,
    vertex_constraints: set[tuple[Cell, int]] | None = None,
    edge_constraints: set[tuple[Cell, Cell, int]] | None = None,
    reserved_vertices: set[tuple[Cell, int]] | None = None,
    reserved_edges: set[tuple[Cell, Cell, int]] | None = None,
    max_time: int = 128,
) -> tuple[list[Cell], int] | None:
    vertex_constraints = vertex_constraints or set()
    edge_constraints = edge_constraints or set()
    reserved_vertices = reserved_vertices or set()
    reserved_edges = reserved_edges or set()
    if (start, 0) in vertex_constraints or (start, 0) in reserved_vertices:
        return None
    queue: list[tuple[int, int, int, Cell, int]] = []
    ticket = count()
    heapq.heappush(queue, (manhattan(start, goal), 0, next(ticket), start, 0))
    parents: dict[tuple[Cell, int], tuple[Cell, int] | None] = {(start, 0): None}
    best_cost: dict[tuple[Cell, int], int] = {(start, 0): 0}
    expanded = 0
    while queue:
        _, g_cost, _, cell, time_index = heapq.heappop(queue)
        expanded += 1
        state = (cell, time_index)
        if best_cost.get(state, g_cost) != g_cost:
            continue
        if cell == goal and goal_is_safe(goal, time_index, max_time, vertex_constraints, reserved_vertices):
            return reconstruct_state_path(parents, state), expanded
        if time_index >= max_time:
            continue
        for nxt in neighbors(grid, cell, include_wait=True):
            next_time = time_index + 1
            if (nxt, next_time) in vertex_constraints or (nxt, next_time) in reserved_vertices:
                continue
            if (cell, nxt, time_index) in edge_constraints:
                continue
            if (nxt, cell, time_index) in reserved_edges:
                continue
            next_state = (nxt, next_time)
            next_cost = g_cost + 1
            if next_cost >= best_cost.get(next_state, 1_000_000_000):
                continue
            best_cost[next_state] = next_cost
            parents[next_state] = state
            priority = next_cost + manhattan(nxt, goal)
            heapq.heappush(queue, (priority, next_cost, next(ticket), nxt, next_time))
    return None


def goal_is_safe(
    goal: Cell,
    arrival_time: int,
    max_time: int,
    vertex_constraints: set[tuple[Cell, int]],
    reserved_vertices: set[tuple[Cell, int]],
) -> bool:
    for time_index in range(arrival_time, max_time + 1):
        if (goal, time_index) in vertex_constraints or (goal, time_index) in reserved_vertices:
            return False
    return True


def reconstruct_state_path(
    parents: dict[tuple[Cell, int], tuple[Cell, int] | None],
    goal_state: tuple[Cell, int],
) -> list[Cell]:
    path = [goal_state[0]]
    current = goal_state
    while parents[current] is not None:
        current = parents[current]  # type: ignore[assignment]
        path.append(current[0])
    path.reverse()
    return path
