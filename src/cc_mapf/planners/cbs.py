from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from itertools import count
from time import perf_counter

from ..model import Cell, Instance, Plan, PlannerResult
from ..validation import pad_plan
from .search_common import space_time_a_star


@dataclass(order=True)
class CBSNode:
    priority: tuple[int, int, int]
    ticket: int
    constraints: dict[str, dict[str, set]]
    paths: Plan = field(compare=False)


class CBSPlanner:
    name = "cbs"

    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        start_time = perf_counter()
        horizon = max(16, instance.grid.width * instance.grid.height // 2 + len(instance.agents) * 4)
        root_paths: Plan = {}
        expanded_nodes = 0
        for agent in instance.agents:
            result = space_time_a_star(instance.grid, agent.start, agent.goal, max_time=horizon)
            if result is None:
                return PlannerResult(
                    status="failed",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=0,
                    metadata={"planner": self.name, "failed_agent": agent.id},
                )
            path, expanded = result
            root_paths[agent.id] = path
            expanded_nodes += expanded
        queue: list[CBSNode] = []
        ticket = count()
        root_constraints = {agent.id: {"vertex": set(), "edge": set()} for agent in instance.agents}
        root = CBSNode(priority=node_cost(root_paths), ticket=next(ticket), constraints=root_constraints, paths=root_paths)
        heapq.heappush(queue, root)
        high_level_expansions = 0
        while queue:
            if perf_counter() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes + high_level_expansions,
                    connectivity_rejections=0,
                    metadata={"planner": self.name},
                )
            node = heapq.heappop(queue)
            high_level_expansions += 1
            conflict = first_conflict(instance, node.paths)
            if conflict is None:
                return PlannerResult(
                    status="solved",
                    plan=node.paths,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes + high_level_expansions,
                    connectivity_rejections=0,
                    metadata={"planner": self.name},
                )
            for agent_id in conflict["agents"]:
                child_constraints = clone_constraints(node.constraints)
                if conflict["type"] == "vertex":
                    child_constraints[agent_id]["vertex"].add((tuple(conflict["cell"]), int(conflict["time"])))
                else:
                    edge = conflict["edge_by_agent"][agent_id]
                    child_constraints[agent_id]["edge"].add((tuple(edge[0]), tuple(edge[1]), int(conflict["time"]) - 1))
                child_paths = {key: list(path) for key, path in node.paths.items()}
                agent = next(item for item in instance.agents if item.id == agent_id)
                search_result = space_time_a_star(
                    instance.grid,
                    agent.start,
                    agent.goal,
                    vertex_constraints=child_constraints[agent_id]["vertex"],
                    edge_constraints=child_constraints[agent_id]["edge"],
                    max_time=horizon,
                )
                if search_result is None:
                    continue
                new_path, expanded = search_result
                expanded_nodes += expanded
                child_paths[agent_id] = new_path
                heapq.heappush(
                    queue,
                    CBSNode(
                        priority=node_cost(child_paths),
                        ticket=next(ticket),
                        constraints=child_constraints,
                        paths=child_paths,
                    ),
                )
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes + high_level_expansions,
            connectivity_rejections=0,
            metadata={"planner": self.name},
        )


def node_cost(paths: Plan) -> tuple[int, int, int]:
    makespan = max((len(path) - 1 for path in paths.values()), default=0)
    sum_cost = sum(len(path) - 1 for path in paths.values())
    path_volume = sum(len(path) for path in paths.values())
    return makespan, sum_cost, path_volume


def clone_constraints(constraints: dict[str, dict[str, set]]) -> dict[str, dict[str, set]]:
    return {
        agent_id: {
            "vertex": set(values["vertex"]),
            "edge": set(values["edge"]),
        }
        for agent_id, values in constraints.items()
    }


def first_conflict(instance: Instance, plan: Plan) -> dict | None:
    padded, _ = pad_plan(instance, plan)
    horizon = max((len(path) for path in padded.values()), default=0)
    agent_ids = [agent.id for agent in instance.agents]
    for time_index in range(horizon):
        positions = {agent_id: padded[agent_id][time_index] for agent_id in agent_ids}
        seen: dict[Cell, str] = {}
        for agent_id, cell in positions.items():
            if cell in seen:
                return {
                    "type": "vertex",
                    "time": time_index,
                    "cell": list(cell),
                    "agents": sorted([seen[cell], agent_id]),
                }
            seen[cell] = agent_id
        if time_index == 0:
            continue
        prev = {agent_id: padded[agent_id][time_index - 1] for agent_id in agent_ids}
        for index, first in enumerate(agent_ids):
            for second in agent_ids[index + 1 :]:
                if prev[first] == positions[second] and prev[second] == positions[first] and prev[first] != prev[second]:
                    return {
                        "type": "swap",
                        "time": time_index,
                        "agents": [first, second],
                        "edge_by_agent": {
                            first: [list(prev[first]), list(positions[first])],
                            second: [list(prev[second]), list(positions[second])],
                        },
                    }
    return None
