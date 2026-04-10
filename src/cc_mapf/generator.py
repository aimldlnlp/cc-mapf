from __future__ import annotations

import random
from pathlib import Path

from .environment import bfs_shortest_path, free_cells, largest_free_component, neighbors
from .model import AgentSpec, ConnectivitySpec, GridMap, Instance, SuiteConfig
from .utils import dump_yaml, ensure_dir, scale_label

FAMILIES = ("open", "corridor", "warehouse", "formation_shift")


def generate_suite_instances(config: SuiteConfig) -> list[Instance]:
    instances: list[Instance] = []
    for family in config.families:
        for scale in config.scales:
            for seed in config.seeds:
                instances.append(
                    generate_instance(
                        family=family,
                        width=scale.width,
                        height=scale.height,
                        agent_count=scale.agents,
                        seed=seed,
                    )
                )
    return instances


def save_instances(instances: list[Instance], output_dir: str | Path) -> None:
    outdir = ensure_dir(output_dir)
    for instance in instances:
        dump_yaml(instance.to_dict(), outdir / f"{instance.name}.yaml")


def generate_instance(family: str, width: int, height: int, agent_count: int, seed: int) -> Instance:
    if family not in FAMILIES:
        raise ValueError(f"Unknown family: {family}")
    rng = random.Random(seed)
    obstacles = generate_obstacles(family, width, height, rng)
    grid = GridMap(width=width, height=height, obstacles=obstacles)
    starts, goals = select_positions(family, grid, agent_count, rng)
    agents = [
        AgentSpec(id=f"r{index:02d}", start=start, goal=goal)
        for index, (start, goal) in enumerate(zip(starts, goals), start=1)
    ]
    name = f"{family}_{scale_label(width, height, agent_count)}_s{seed:02d}"
    return Instance(
        name=name,
        grid=grid,
        agents=agents,
        connectivity=ConnectivitySpec(mode="adjacency", radius=1),
        metadata={"family": family, "seed": seed, "scale": scale_label(width, height, agent_count)},
    )


def generate_obstacles(family: str, width: int, height: int, rng: random.Random) -> set[tuple[int, int]]:
    obstacles: set[tuple[int, int]] = set()
    if family == "open":
        density = 0.07 if width * height <= 400 else 0.09
        for x in range(1, width - 1):
            for y in range(1, height - 1):
                if rng.random() < density:
                    obstacles.add((x, y))
    elif family == "corridor":
        wall_x = width // 2
        opening_y = height // 2
        for y in range(height):
            if y not in {opening_y, opening_y - 1 if opening_y > 0 else opening_y}:
                obstacles.add((wall_x, y))
        side_x = max(1, wall_x - 2)
        for y in range(1, height - 1):
            if y not in {opening_y, opening_y - 1 if opening_y > 0 else opening_y}:
                obstacles.add((side_x, y))
    elif family == "warehouse":
        for x in range(2, width - 2, 4):
            for y in range(1, height - 1):
                if y % 4 != 2:
                    obstacles.add((x, y))
    elif family == "formation_shift":
        box_w = max(2, width // 6)
        box_h = max(2, height // 4)
        start_x = width // 2 - box_w // 2
        start_y = height // 2 - box_h // 2
        for x in range(start_x, start_x + box_w):
            for y in range(start_y, start_y + box_h):
                if x in {start_x, start_x + box_w - 1} or y in {start_y, start_y + box_h - 1}:
                    obstacles.add((x, y))
    return {cell for cell in obstacles if 0 <= cell[0] < width and 0 <= cell[1] < height}


def select_positions(
    family: str,
    grid: GridMap,
    agent_count: int,
    rng: random.Random,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    component = sorted(largest_free_component(grid))
    if len(component) < agent_count * 2:
        raise ValueError("Largest free component is too small for requested agent count.")
    if family == "formation_shift":
        starts = formation_line(grid, agent_count, left_side=True)
        goals = formation_block(grid, agent_count, left_side=False)
        if starts and goals and positions_are_valid(grid, starts, goals):
            return starts, goals
    starts = sample_connected_group(grid, component, agent_count, rng, region_cells(family, grid, "start"))
    excluded = set(starts)
    goals = sample_connected_group(grid, [cell for cell in component if cell not in excluded], agent_count, rng, region_cells(family, grid, "goal"))
    if not positions_are_valid(grid, starts, goals):
        starts = sample_connected_group(grid, component, agent_count, rng, component)
        excluded = set(starts)
        goals = sample_connected_group(grid, [cell for cell in component if cell not in excluded], agent_count, rng, component)
    if not positions_are_valid(grid, starts, goals):
        raise ValueError("Failed to generate valid connected start and goal sets.")
    return starts, goals


def region_cells(family: str, grid: GridMap, phase: str) -> list[tuple[int, int]]:
    all_free = set(free_cells(grid))
    if family in {"open", "corridor"}:
        if phase == "start":
            return [cell for cell in all_free if cell[0] <= grid.width // 3]
        return [cell for cell in all_free if cell[0] >= (2 * grid.width) // 3]
    if family == "warehouse":
        if phase == "start":
            return [cell for cell in all_free if cell[0] <= grid.width // 3 and cell[1] >= grid.height // 3]
        return [cell for cell in all_free if cell[0] >= (2 * grid.width) // 3 and cell[1] <= (2 * grid.height) // 3]
    if family == "formation_shift":
        if phase == "start":
            return [cell for cell in all_free if cell[0] <= grid.width // 4]
        return [cell for cell in all_free if cell[0] >= grid.width // 2]
    return list(all_free)


def sample_connected_group(
    grid: GridMap,
    candidate_cells: list[tuple[int, int]],
    agent_count: int,
    rng: random.Random,
    preferred_cells: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    candidate_set = set(candidate_cells)
    preferred = [cell for cell in preferred_cells if cell in candidate_set]
    seeds = preferred if len(preferred) >= agent_count else candidate_cells
    seeds = list(seeds)
    rng.shuffle(seeds)
    for seed in seeds:
        group = [seed]
        seen = {seed}
        frontier = [seed]
        while frontier and len(group) < agent_count:
            current = frontier.pop(0)
            nbrs = [nxt for nxt in neighbors(grid, current) if nxt in candidate_set and nxt not in seen]
            nbrs.sort(key=lambda cell: (cell not in preferred, cell[0], cell[1]))
            for nxt in nbrs:
                seen.add(nxt)
                group.append(nxt)
                frontier.append(nxt)
                if len(group) == agent_count:
                    return sorted(group)
        if len(group) == agent_count:
            return sorted(group)
    raise ValueError("Unable to sample a connected group of cells.")


def positions_are_valid(grid: GridMap, starts: list[tuple[int, int]], goals: list[tuple[int, int]]) -> bool:
    if len(starts) != len(goals) or len(set(starts)) != len(starts) or len(set(goals)) != len(goals):
        return False
    for start, goal in zip(starts, goals):
        if bfs_shortest_path(grid, start, goal) is None:
            return False
    return True


def formation_line(grid: GridMap, agent_count: int, left_side: bool) -> list[tuple[int, int]] | None:
    y = grid.height // 2
    x_start = 1 if left_side else max(1, grid.width - agent_count - 2)
    cells = [(x_start + offset, y) for offset in range(agent_count)]
    if all(cell not in grid.obstacles and 0 <= cell[0] < grid.width for cell in cells):
        return cells
    return None


def formation_block(grid: GridMap, agent_count: int, left_side: bool) -> list[tuple[int, int]] | None:
    side = 1
    while side * side < agent_count:
        side += 1
    x_anchor = 1 if left_side else max(1, grid.width - side - 2)
    y_anchor = max(1, grid.height // 2 - side // 2)
    cells: list[tuple[int, int]] = []
    for y in range(y_anchor, y_anchor + side):
        for x in range(x_anchor, x_anchor + side):
            if len(cells) == agent_count:
                break
            cells.append((x, y))
        if len(cells) == agent_count:
            break
    if all(0 <= cell[0] < grid.width and 0 <= cell[1] < grid.height and cell not in grid.obstacles for cell in cells):
        return cells
    return None
