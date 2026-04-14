from __future__ import annotations

from time import perf_counter

from ..connectivity import position_connected_to_reference, resolve_connectivity_rule
from ..environment import manhattan, shortest_path_length
from ..model import Instance, Plan, Planner, PlannerResult
from ..validation import validate_plan
from .search_common import space_time_a_star


class PrioritizedCCPlanner(Planner):
    name: str = "prioritized_cc"

    def __init__(self, connectivity_range: float | None = None, priority_order: str = "goal_distance"):
        self.connectivity_range = connectivity_range
        self.priority_order = priority_order

    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        start_time = perf_counter()
        base_order = self._base_order(instance)
        rotations = min(3, len(base_order))
        best_failure: PlannerResult | None = None
        for rotation in range(rotations):
            if perf_counter() - start_time > time_limit_s:
                break
            order = base_order[rotation:] + base_order[:rotation]
            result = self._solve_with_order(instance, order, time_limit_s, start_time, rotation)
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
        rotation: int,
    ) -> PlannerResult:
        reserved_vertices: set[tuple[tuple[int, int], int]] = set()
        reserved_edges: set[tuple[tuple[int, int], tuple[int, int], int]] = set()
        plan: Plan = {}
        expanded_nodes = 0
        connectivity_rejections = 0
        optimistic = max((shortest_path_length(instance.grid, agent.start, agent.goal) or 0) for agent in instance.agents)
        horizon = max(16, optimistic + instance.grid.width * instance.grid.height // 2 + len(instance.agents) * 4)
        mode, radius = resolve_connectivity_rule(instance.connectivity, radius=self.connectivity_range)
        for agent in order:
            if perf_counter() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    metadata={"planner": self.name},
                )
            rejected_here = 0
            reference_paths = {agent_id: path for agent_id, path in plan.items()}

            def state_validator(cell: tuple[int, int], time_index: int) -> bool:
                nonlocal rejected_here
                if not position_connected_to_reference(
                    cell,
                    time_index,
                    reference_paths,
                    mode=mode,
                    radius=radius,
                ):
                    rejected_here += 1
                    return False
                return True

            search_result = space_time_a_star(
                instance.grid,
                agent.start,
                agent.goal,
                reserved_vertices=reserved_vertices,
                reserved_edges=reserved_edges,
                state_validator=state_validator if reference_paths else None,
                max_time=horizon,
            )
            connectivity_rejections += rejected_here
            if search_result is None:
                return PlannerResult(
                    status="failed",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    metadata={
                        "planner": self.name,
                        "failed_agent": agent.id,
                        "priority_order": self.priority_order,
                        "rotation": rotation,
                        "connectivity_mode": mode,
                        "connectivity_radius": radius,
                    },
                )
            path, expanded = search_result
            expanded_nodes += expanded
            plan[agent.id] = path
            for time_index, cell in enumerate(path):
                reserved_vertices.add((cell, time_index))
                if time_index < len(path) - 1:
                    reserved_edges.add((cell, path[time_index + 1], time_index))
            for time_index in range(len(path), horizon + 1):
                reserved_vertices.add((path[-1], time_index))
        validation = validate_plan(instance, plan)
        if not validation.valid:
            return PlannerResult(
                status="failed",
                plan=plan,
                runtime_s=perf_counter() - start_time,
                expanded_nodes=expanded_nodes,
                connectivity_rejections=connectivity_rejections,
                metadata={
                    "planner": self.name,
                    "reason": "validation_failed",
                    "priority_order": self.priority_order,
                    "rotation": rotation,
                    "connectivity_mode": mode,
                    "connectivity_radius": radius,
                },
            )
        return PlannerResult(
            status="solved",
            plan=plan,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes,
            connectivity_rejections=connectivity_rejections,
            metadata={
                "planner": self.name,
                "priority_order": self.priority_order,
                "rotation": rotation,
                "connectivity_mode": mode,
                "connectivity_radius": radius,
            },
        )

    def _base_order(self, instance: Instance):
        if self.priority_order == "start_distance":
            return sorted(instance.agents, key=lambda agent: (agent.start[0] + agent.start[1], agent.id))
        if self.priority_order == "agent_id":
            return sorted(instance.agents, key=lambda agent: agent.id)
        return sorted(instance.agents, key=lambda agent: (-manhattan(agent.start, agent.goal), agent.id))
