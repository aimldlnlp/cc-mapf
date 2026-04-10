from __future__ import annotations

from time import perf_counter

from ..environment import manhattan, shortest_path_length
from ..model import Instance, Plan, PlannerResult
from .search_common import space_time_a_star


class PrioritizedPlanner:
    name = "prioritized"

    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        start_time = perf_counter()
        base_order = sorted(instance.agents, key=lambda agent: (-manhattan(agent.start, agent.goal), agent.id))
        rotations = min(3, len(base_order))
        best_failure: PlannerResult | None = None
        for rotation in range(rotations):
            if perf_counter() - start_time > time_limit_s:
                break
            order = base_order[rotation:] + base_order[:rotation]
            result = self._solve_with_order(instance, order, time_limit_s, start_time)
            if result.status == "solved":
                return result
            best_failure = result
        return best_failure or PlannerResult(
            status="timeout",
            plan=None,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"planner": self.name},
        )

    def _solve_with_order(
        self,
        instance: Instance,
        order,
        time_limit_s: float,
        start_time: float,
    ) -> PlannerResult:
        reserved_vertices: set[tuple[tuple[int, int], int]] = set()
        reserved_edges: set[tuple[tuple[int, int], tuple[int, int], int]] = set()
        plan: Plan = {}
        expanded_nodes = 0
        optimistic = max(shortest_path_length(instance.grid, agent.start, agent.goal) or 0 for agent in instance.agents)
        horizon = max(16, optimistic + instance.grid.width * instance.grid.height // 2 + len(instance.agents) * 4)
        for agent in order:
            if perf_counter() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=0,
                    metadata={"planner": self.name},
                )
            result = space_time_a_star(
                instance.grid,
                agent.start,
                agent.goal,
                reserved_vertices=reserved_vertices,
                reserved_edges=reserved_edges,
                max_time=horizon,
            )
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
            expanded_nodes += expanded
            plan[agent.id] = path
            for time_index, cell in enumerate(path):
                reserved_vertices.add((cell, time_index))
                if time_index < len(path) - 1:
                    reserved_edges.add((cell, path[time_index + 1], time_index))
            for time_index in range(len(path), horizon + 1):
                reserved_vertices.add((path[-1], time_index))
        return PlannerResult(
            status="solved",
            plan=plan,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes,
            connectivity_rejections=0,
            metadata={"planner": self.name},
        )
