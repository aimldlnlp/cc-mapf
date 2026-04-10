from __future__ import annotations

from collections import deque
from typing import Iterable

from .model import Cell, GridMap

DIRECTIONS4: tuple[Cell, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


def add_cell(cell: Cell, delta: Cell) -> Cell:
    return cell[0] + delta[0], cell[1] + delta[1]


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def in_bounds(grid: GridMap, cell: Cell) -> bool:
    x, y = cell
    return 0 <= x < grid.width and 0 <= y < grid.height


def is_free(grid: GridMap, cell: Cell) -> bool:
    return in_bounds(grid, cell) and cell not in grid.obstacles


def neighbors(grid: GridMap, cell: Cell, include_wait: bool = False) -> list[Cell]:
    result = [add_cell(cell, delta) for delta in DIRECTIONS4]
    result = [candidate for candidate in result if is_free(grid, candidate)]
    if include_wait and is_free(grid, cell):
        result.append(cell)
    return result


def free_cells(grid: GridMap) -> list[Cell]:
    return [
        (x, y)
        for y in range(grid.height)
        for x in range(grid.width)
        if (x, y) not in grid.obstacles
    ]


def connected_free_components(grid: GridMap) -> list[set[Cell]]:
    components: list[set[Cell]] = []
    unvisited = set(free_cells(grid))
    while unvisited:
        seed = next(iter(unvisited))
        queue = deque([seed])
        component = {seed}
        unvisited.remove(seed)
        while queue:
            current = queue.popleft()
            for nxt in neighbors(grid, current):
                if nxt in unvisited:
                    unvisited.remove(nxt)
                    component.add(nxt)
                    queue.append(nxt)
        components.append(component)
    return components


def largest_free_component(grid: GridMap) -> set[Cell]:
    components = connected_free_components(grid)
    if not components:
        return set()
    return max(components, key=len)


def bfs_shortest_path(
    grid: GridMap,
    start: Cell,
    goal: Cell,
    blocked: Iterable[Cell] | None = None,
) -> list[Cell] | None:
    blocked_cells = set(blocked or [])
    if start == goal:
        return [start]
    if start in blocked_cells or goal in blocked_cells:
        return None
    if not is_free(grid, start) or not is_free(grid, goal):
        return None
    queue = deque([start])
    parents: dict[Cell, Cell | None] = {start: None}
    while queue:
        current = queue.popleft()
        for nxt in neighbors(grid, current):
            if nxt in blocked_cells or nxt in parents:
                continue
            parents[nxt] = current
            if nxt == goal:
                return reconstruct_path(parents, goal)
            queue.append(nxt)
    return None


def reconstruct_path(parents: dict[Cell, Cell | None], goal: Cell) -> list[Cell]:
    path = [goal]
    current = goal
    while parents[current] is not None:
        current = parents[current]  # type: ignore[assignment]
        path.append(current)
    path.reverse()
    return path


def shortest_path_length(grid: GridMap, start: Cell, goal: Cell) -> int | None:
    path = bfs_shortest_path(grid, start, goal)
    if path is None:
        return None
    return len(path) - 1
