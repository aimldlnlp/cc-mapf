from __future__ import annotations

from collections import deque

from .environment import manhattan
from .model import Cell, ConnectivitySpec, Plan


def resolve_connectivity_rule(
    spec: ConnectivitySpec | None = None,
    *,
    mode: str | None = None,
    radius: int | float | None = None,
) -> tuple[str, int]:
    resolved_mode = str(mode if mode is not None else (spec.mode if spec is not None else "adjacency"))
    resolved_radius = int(radius if radius is not None else (spec.radius if spec is not None else 1))
    return resolved_mode, max(1, resolved_radius)


def cells_are_connected(
    left: Cell,
    right: Cell,
    *,
    spec: ConnectivitySpec | None = None,
    mode: str | None = None,
    radius: int | float | None = None,
) -> bool:
    resolved_mode, resolved_radius = resolve_connectivity_rule(spec, mode=mode, radius=radius)
    if resolved_mode == "euclidean":
        dx = left[0] - right[0]
        dy = left[1] - right[1]
        return dx * dx + dy * dy <= resolved_radius * resolved_radius
    return manhattan(left, right) <= resolved_radius


def connectivity_components(
    positions: dict[str, Cell],
    *,
    spec: ConnectivitySpec | None = None,
    mode: str | None = None,
    radius: int | float | None = None,
) -> list[list[str]]:
    if not positions:
        return []
    adjacency: dict[str, set[str]] = {agent_id: set() for agent_id in positions}
    agent_items = list(positions.items())
    for index, (agent_a, cell_a) in enumerate(agent_items):
        for agent_b, cell_b in agent_items[index + 1 :]:
            if cells_are_connected(cell_a, cell_b, spec=spec, mode=mode, radius=radius):
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


def is_team_connected(
    positions: dict[str, Cell],
    *,
    spec: ConnectivitySpec | None = None,
    mode: str | None = None,
    radius: int | float | None = None,
) -> bool:
    return len(connectivity_components(positions, spec=spec, mode=mode, radius=radius)) <= 1


def reference_positions(reference_paths: Plan, time_index: int) -> dict[str, Cell]:
    return {
        agent_id: path[min(time_index, len(path) - 1)]
        for agent_id, path in reference_paths.items()
        if path
    }


def position_connected_to_reference(
    cell: Cell,
    time_index: int,
    reference_paths: Plan,
    *,
    spec: ConnectivitySpec | None = None,
    mode: str | None = None,
    radius: int | float | None = None,
) -> bool:
    if not reference_paths:
        return True
    for reference_cell in reference_positions(reference_paths, time_index).values():
        if cells_are_connected(cell, reference_cell, spec=spec, mode=mode, radius=radius):
            return True
    return False
