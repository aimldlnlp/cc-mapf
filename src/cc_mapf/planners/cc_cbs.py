from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from itertools import count
from time import perf_counter

from ..connectivity import connectivity_components, position_connected_to_reference, resolve_connectivity_rule
from ..environment import shortest_path_length
from ..model import Cell, Instance, Plan, Planner, PlannerResult
from ..validation import pad_plan, validate_plan
from .cbs import first_conflict, node_cost
from .search_common import space_time_a_star


@dataclass(frozen=True, order=True)
class VertexConstraint:
    agent_id: str = field(compare=False)
    pos: Cell = field(compare=False)
    timestep: int


@dataclass(frozen=True, order=True)
class EdgeConstraint:
    agent_id: str = field(compare=False)
    pos_from: Cell = field(compare=False)
    pos_to: Cell = field(compare=False)
    timestep: int


@dataclass
class ConstraintSet:
    vertex: set[VertexConstraint] = field(default_factory=set)
    edge: set[EdgeConstraint] = field(default_factory=set)

    def copy(self) -> ConstraintSet:
        return ConstraintSet(vertex=set(self.vertex), edge=set(self.edge))

    def add_vertex(self, agent_id: str, pos: Cell, timestep: int) -> None:
        self.vertex.add(VertexConstraint(agent_id, pos, timestep))

    def add_edge(self, agent_id: str, pos_from: Cell, pos_to: Cell, timestep: int) -> None:
        self.edge.add(EdgeConstraint(agent_id, pos_from, pos_to, timestep))

    def vertex_constraints_for(self, agent_id: str) -> set[tuple[Cell, int]]:
        return {
            (constraint.pos, constraint.timestep)
            for constraint in self.vertex
            if constraint.agent_id == agent_id
        }

    def edge_constraints_for(self, agent_id: str) -> set[tuple[Cell, Cell, int]]:
        return {
            (constraint.pos_from, constraint.pos_to, constraint.timestep)
            for constraint in self.edge
            if constraint.agent_id == agent_id
        }

    def signature(self) -> tuple[tuple[tuple[str, Cell, int], ...], tuple[tuple[str, Cell, Cell, int], ...]]:
        vertex = tuple(
            sorted((constraint.agent_id, constraint.pos, constraint.timestep) for constraint in self.vertex)
        )
        edge = tuple(
            sorted((constraint.agent_id, constraint.pos_from, constraint.pos_to, constraint.timestep) for constraint in self.edge)
        )
        return vertex, edge


@dataclass
class CTNode:
    constraints: ConstraintSet
    paths: Plan


class CCCBSPlanner(Planner):
    name: str = "cc_cbs"

    def __init__(self, connectivity_range: float | None = None, cost_type: str = "makespan"):
        self.connectivity_range = connectivity_range
        self.cost_type = cost_type

    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        start_time = perf_counter()
        optimistic = max((shortest_path_length(instance.grid, agent.start, agent.goal) or 0) for agent in instance.agents)
        horizon = max(16, optimistic + instance.grid.width * instance.grid.height // 2 + len(instance.agents) * 4)
        root_constraints = ConstraintSet()
        root_paths: Plan = {}
        expanded_nodes = 0
        connectivity_rejections = 0
        for agent in instance.agents:
            search_result = self._low_level_search(agent.id, instance, root_constraints, max_time=horizon)
            if search_result is None:
                return PlannerResult(
                    status="failed",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes,
                    connectivity_rejections=connectivity_rejections,
                    metadata={"planner": self.name, "failed_agent": agent.id},
                )
            path, expanded, rejected = search_result
            root_paths[agent.id] = path
            expanded_nodes += expanded
            connectivity_rejections += rejected
        queue: list[tuple[tuple[int, int, int, int], int, CTNode]] = []
        ticket = count()
        root = CTNode(constraints=root_constraints, paths=root_paths)
        heapq.heappush(queue, (self._priority(root), next(ticket), root))
        seen = {root_constraints.signature()}
        high_level_expansions = 0
        while queue:
            if perf_counter() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=perf_counter() - start_time,
                    expanded_nodes=expanded_nodes + high_level_expansions,
                    connectivity_rejections=connectivity_rejections,
                    metadata={"planner": self.name},
                )
            _, _, node = heapq.heappop(queue)
            high_level_expansions += 1
            conflict = first_conflict(instance, node.paths)
            if conflict is not None:
                children = self._split_conflict(node, conflict, instance, horizon)
            else:
                violation = self._find_connectivity_violation(instance, node.paths)
                if violation is None:
                    validation = validate_plan(instance, node.paths)
                    if validation.valid:
                        return PlannerResult(
                            status="solved",
                            plan=node.paths,
                            runtime_s=perf_counter() - start_time,
                            expanded_nodes=expanded_nodes + high_level_expansions,
                            connectivity_rejections=connectivity_rejections,
                            metadata={"planner": self.name, "cost_type": self.cost_type},
                        )
                    return PlannerResult(
                        status="failed",
                        plan=node.paths,
                        runtime_s=perf_counter() - start_time,
                        expanded_nodes=expanded_nodes + high_level_expansions,
                        connectivity_rejections=connectivity_rejections,
                        metadata={"planner": self.name, "reason": "validation_failed"},
                    )
                children = self._split_connectivity(node, violation, instance, horizon)
            for child, child_expanded, child_connectivity_rejections in children:
                expanded_nodes += child_expanded
                connectivity_rejections += child_connectivity_rejections
                signature = child.constraints.signature()
                if signature in seen:
                    continue
                seen.add(signature)
                heapq.heappush(queue, (self._priority(child), next(ticket), child))
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=perf_counter() - start_time,
            expanded_nodes=expanded_nodes + high_level_expansions,
            connectivity_rejections=connectivity_rejections,
            metadata={"planner": self.name},
        )

    def _low_level_search(
        self,
        agent_id: str,
        instance: Instance,
        constraints: ConstraintSet,
        *,
        reference_paths: Plan | None = None,
        max_time: int,
    ) -> tuple[list[Cell], int, int] | None:
        agent = next(agent for agent in instance.agents if agent.id == agent_id)
        mode, radius = resolve_connectivity_rule(instance.connectivity, radius=self.connectivity_range)
        rejected_here = 0

        def state_validator(cell: Cell, time_index: int) -> bool:
            nonlocal rejected_here
            if not position_connected_to_reference(
                cell,
                time_index,
                reference_paths or {},
                mode=mode,
                radius=radius,
            ):
                rejected_here += 1
                return False
            return True

        result = space_time_a_star(
            instance.grid,
            agent.start,
            agent.goal,
            vertex_constraints=constraints.vertex_constraints_for(agent_id),
            edge_constraints=constraints.edge_constraints_for(agent_id),
            state_validator=state_validator if reference_paths else None,
            max_time=max_time,
        )
        if result is None:
            return None
        path, expanded = result
        return path, expanded, rejected_here

    def _find_connectivity_violation(self, instance: Instance, paths: Plan) -> dict[str, object] | None:
        padded, _ = pad_plan(instance, paths)
        horizon = max((len(path) for path in padded.values()), default=0)
        mode, radius = resolve_connectivity_rule(instance.connectivity, radius=self.connectivity_range)
        for time_index in range(horizon):
            positions = {agent.id: padded[agent.id][time_index] for agent in instance.agents}
            components = connectivity_components(positions, mode=mode, radius=radius)
            if len(components) > 1:
                ordered = sorted(components, key=lambda component: (-len(component), component))
                return {"time": time_index, "components": ordered}
        return None

    def _split_conflict(
        self,
        node: CTNode,
        conflict: dict,
        instance: Instance,
        horizon: int,
    ) -> list[tuple[CTNode, int, int]]:
        children: list[tuple[CTNode, int, int]] = []
        if conflict["type"] == "vertex":
            for agent_id in conflict["agents"]:
                child = self._replan_agent(
                    node,
                    agent_id,
                    instance,
                    horizon,
                    vertex_constraint=(tuple(conflict["cell"]), int(conflict["time"])),
                )
                if child is not None:
                    children.append(child)
            return children
        if conflict["type"] == "swap":
            for agent_id in conflict["agents"]:
                edge = conflict["edge_by_agent"][agent_id]
                child = self._replan_agent(
                    node,
                    agent_id,
                    instance,
                    horizon,
                    edge_constraint=(tuple(edge[0]), tuple(edge[1]), int(conflict["time"]) - 1),
                )
                if child is not None:
                    children.append(child)
        return children

    def _split_connectivity(
        self,
        node: CTNode,
        violation: dict[str, object],
        instance: Instance,
        horizon: int,
    ) -> list[tuple[CTNode, int, int]]:
        components = violation["components"]
        assert isinstance(components, list)
        time_index = int(violation["time"])
        primary_component = set(components[0])
        children: list[tuple[CTNode, int, int]] = []
        for agent_id in sorted(agent.id for agent in instance.agents if agent.id not in primary_component):
            offending_cell = node.paths[agent_id][min(time_index, len(node.paths[agent_id]) - 1)]
            reference_paths = {other_id: node.paths[other_id] for other_id in primary_component}
            child = self._replan_agent(
                node,
                agent_id,
                instance,
                horizon,
                vertex_constraint=(offending_cell, time_index),
                reference_paths=reference_paths,
            )
            if child is not None:
                children.append(child)
        return children

    def _replan_agent(
        self,
        node: CTNode,
        agent_id: str,
        instance: Instance,
        horizon: int,
        *,
        vertex_constraint: tuple[Cell, int] | None = None,
        edge_constraint: tuple[Cell, Cell, int] | None = None,
        reference_paths: Plan | None = None,
    ) -> tuple[CTNode, int, int] | None:
        constraints = node.constraints.copy()
        if vertex_constraint is not None:
            cell, time_index = vertex_constraint
            constraints.add_vertex(agent_id, cell, time_index)
        if edge_constraint is not None:
            from_cell, to_cell, time_index = edge_constraint
            constraints.add_edge(agent_id, from_cell, to_cell, time_index)
        effective_references = reference_paths or {
            other_id: path for other_id, path in node.paths.items() if other_id != agent_id
        }
        search_result = self._low_level_search(
            agent_id,
            instance,
            constraints,
            reference_paths=effective_references,
            max_time=horizon,
        )
        if search_result is None:
            return None
        path, expanded, rejected = search_result
        new_paths = {key: list(value) for key, value in node.paths.items()}
        new_paths[agent_id] = path
        return CTNode(constraints=constraints, paths=new_paths), expanded, rejected

    def _priority(self, node: CTNode) -> tuple[int, int, int, int]:
        base = node_cost(node.paths)
        penalty = len(node.constraints.vertex) + len(node.constraints.edge)
        if self.cost_type == "sum_costs":
            return base[1], base[0], base[2], penalty
        return base[0], base[1], base[2], penalty
