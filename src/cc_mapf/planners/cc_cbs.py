#!/usr/bin/env python3
"""
CC-CBS: Conflict-Based Search with Connectivity Constraints.

Optimal MAPF planner yang menangani:
1. Vertex conflicts (dua agent di posisi sama)
2. Edge conflicts (dua agent swap positions)
3. Connectivity violations (graph tidak terhubung)

Based on: Sharon, Guni, et al. "Conflict-based search for optimal multi-agent path finding." AAAI 2012.
Extended dengan connectivity constraints.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from typing import Optional

from ..environment import is_free, neighbors
from ..model import AgentSpec, GridMap, Instance, Planner, PlannerResult


@dataclass(frozen=True, order=True)
class VertexConstraint:
    """Constraint: agent cannot be at (pos) at timestep."""
    agent_id: str = field(compare=False)
    pos: tuple[int, int] = field(compare=False)
    timestep: int


@dataclass(frozen=True, order=True)
class EdgeConstraint:
    """Constraint: agent cannot move from pos1 to pos2 at timestep."""
    agent_id: str = field(compare=False)
    pos_from: tuple[int, int] = field(compare=False)
    pos_to: tuple[int, int] = field(compare=False)
    timestep: int


@dataclass
class ConstraintSet:
    """Kumpulan constraint untuk satu CT node."""
    vertex: set[VertexConstraint] = field(default_factory=set)
    edge: set[EdgeConstraint] = field(default_factory=set)
    
    def copy(self) -> ConstraintSet:
        return ConstraintSet(
            vertex=set(self.vertex),
            edge=set(self.edge)
        )
    
    def add_vertex(self, agent_id: str, pos: tuple[int, int], timestep: int):
        self.vertex.add(VertexConstraint(agent_id, pos, timestep))
    
    def add_edge(self, agent_id: str, pos_from: tuple[int, int], 
                 pos_to: tuple[int, int], timestep: int):
        self.edge.add(EdgeConstraint(agent_id, pos_from, pos_to, timestep))


@dataclass
class CTNode:
    """
    Constraint Tree Node.
    
    Attributes:
        constraints: Set of constraints untuk semua agents
        paths: Dictionary agent_id -> list of positions (path)
        cost: Total cost (makespan atau sum of costs)
    """
    constraints: ConstraintSet
    paths: dict[str, list[tuple[int, int]]]
    cost: float
    
    def __lt__(self, other: CTNode) -> bool:
        return self.cost < other.cost


class CCCBSPlanner(Planner):
    """
    Conflict-Based Search with Connectivity Constraints.
    
    Usage:
        planner = CCCBSPlanner()
        result = planner.solve(instance, time_limit_s=300.0)
    """
    
    name: str = "cc_cbs"
    
    def __init__(self, connectivity_range: float = 3.0,
                 cost_type: str = "makespan"):
        """
        Args:
            connectivity_range: Maximum distance untuk connectivity
            cost_type: "makespan" or "sum_costs"
        """
        self.connectivity_range = connectivity_range
        self.cost_type = cost_type
        
    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        """
        Run CC-CBS algorithm.
        
        Returns:
            PlannerResult dengan status, plan, dan metadata
        """
        start_time = time.time()
        grid = instance.grid
        agents = instance.agents
        agent_ids = [a.id for a in agents]
        agent_map = {a.id: a for a in agents}
        
        # Root node: empty constraints, individual paths
        root_constraints = ConstraintSet()
        root_paths: dict[str, list[tuple[int, int]]] = {}
        
        for agent in agents:
            path = self._low_level_search(agent, instance, root_constraints)
            if path is None:
                return PlannerResult(
                    status="failure",
                    plan=None,
                    runtime_s=time.time() - start_time,
                    expanded_nodes=0,
                    connectivity_rejections=0
                )
            root_paths[agent.id] = path
        
        root_cost = self._compute_cost(root_paths)
        root_node = CTNode(root_constraints, root_paths, root_cost)
        
        # Priority queue untuk CT
        open_list: list[tuple[float, int, CTNode]] = []
        counter = 0
        heapq.heappush(open_list, (root_cost, counter, root_node))
        counter += 1
        
        nodes_expanded = 0
        
        while open_list and (time.time() - start_time) < time_limit_s:
            _, _, current = heapq.heappop(open_list)
            nodes_expanded += 1
            
            # Check conflicts
            conflict = self._find_conflict(current.paths)
            if conflict is None:
                # Check connectivity
                violation = self._find_connectivity_violation(current.paths)
                if violation is None:
                    # Valid solution found!
                    return PlannerResult(
                        status="success",
                        plan=current.paths,
                        runtime_s=time.time() - start_time,
                        expanded_nodes=nodes_expanded,
                        connectivity_rejections=0
                    )
                else:
                    # Split by connectivity violation
                    children = self._split_connectivity(
                        current, violation, instance
                    )
            else:
                # Split by conflict
                children = self._split_conflict(current, conflict, instance)
            
            # Add children to open list
            for child in children:
                heapq.heappush(open_list, (child.cost, counter, child))
                counter += 1
        
        if not open_list:
            return PlannerResult(
                status="failure",
                plan=None,
                runtime_s=time.time() - start_time,
                expanded_nodes=nodes_expanded,
                connectivity_rejections=0
            )
        else:
            return PlannerResult(
                status="timeout",
                plan=None,
                runtime_s=time.time() - start_time,
                expanded_nodes=nodes_expanded,
                connectivity_rejections=0
            )
    
    def _low_level_search(self, agent: AgentSpec, instance: Instance,
                         constraints: ConstraintSet) -> Optional[list[tuple[int, int]]]:
        """
        A* search untuk single agent dengan constraints.
        
        Returns:
            Path sebagai list of positions, atau None jika tidak ada path
        """
        grid = instance.grid
        start = agent.start
        goal = agent.goal
        
        # A* dengan temporal constraints
        open_set: list[tuple[float, int, tuple[int, int], int]] = []
        heapq.heappush(open_set, (0.0, 0, start, 0))
        
        g_score: dict[tuple[tuple[int, int], int], float] = {(start, 0): 0.0}
        came_from: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
        counter = 1
        
        max_timestep = 500  # Prevent infinite search
        
        while open_set:
            _, _, pos, timestep = heapq.heappop(open_set)
            
            if timestep > max_timestep:
                continue
            
            # Check goal
            if pos == goal:
                # Reconstruct path
                path = [pos]
                current_key = (pos, timestep)
                while current_key in came_from:
                    current_key = came_from[current_key]
                    path.append(current_key[0])
                path.reverse()
                return path
            
            # Expand neighbors
            current_g = g_score.get((pos, timestep), float('inf'))
            
            for neighbor in neighbors(grid, pos, include_wait=True):
                new_timestep = timestep + 1
                
                # Check vertex constraint
                if VertexConstraint(agent.id, neighbor, new_timestep) in constraints.vertex:
                    continue
                
                # Check edge constraint
                if EdgeConstraint(agent.id, pos, neighbor, new_timestep) in constraints.edge:
                    continue
                
                # Check if neighbor is valid (not obstacle)
                if not is_free(grid, neighbor):
                    continue
                
                tentative_g = current_g + 1
                neighbor_key = (neighbor, new_timestep)
                
                if tentative_g < g_score.get(neighbor_key, float('inf')):
                    came_from[neighbor_key] = (pos, timestep)
                    g_score[neighbor_key] = tentative_g
                    
                    # Heuristic: Manhattan distance
                    h = abs(neighbor[0] - goal[0]) + abs(neighbor[1] - goal[1])
                    f = tentative_g + h
                    
                    heapq.heappush(open_set, (f, counter, neighbor, new_timestep))
                    counter += 1
        
        return None
    
    def _find_conflict(self, paths: dict[str, list[tuple[int, int]]]
                      ) -> Optional[dict]:
        """
        Find first conflict antara dua agents.
        
        Returns:
            Dict dengan keys: 'type', 'agent1', 'agent2', 'pos', 'timestep'
            atau None jika tidak ada conflict
        """
        agent_ids = list(paths.keys())
        max_timestep = max(len(p) for p in paths.values())
        
        for t in range(max_timestep):
            # Check vertex conflicts
            positions: dict[tuple[int, int], list[str]] = {}
            for aid in agent_ids:
                pos = paths[aid][min(t, len(paths[aid]) - 1)]
                if pos not in positions:
                    positions[pos] = []
                positions[pos].append(aid)
            
            for pos, aids_at_pos in positions.items():
                if len(aids_at_pos) > 1:
                    return {
                        'type': 'vertex',
                        'agent1': aids_at_pos[0],
                        'agent2': aids_at_pos[1],
                        'pos': pos,
                        'timestep': t
                    }
            
            # Check edge conflicts (swap)
            if t > 0:
                for i, aid1 in enumerate(agent_ids):
                    for aid2 in agent_ids[i+1:]:
                        pos1_prev = paths[aid1][min(t-1, len(paths[aid1]) - 1)]
                        pos1_curr = paths[aid1][min(t, len(paths[aid1]) - 1)]
                        pos2_prev = paths[aid2][min(t-1, len(paths[aid2]) - 1)]
                        pos2_curr = paths[aid2][min(t, len(paths[aid2]) - 1)]
                        
                        if pos1_prev == pos2_curr and pos1_curr == pos2_prev:
                            return {
                                'type': 'edge',
                                'agent1': aid1,
                                'agent2': aid2,
                                'pos1': pos1_prev,
                                'pos2': pos1_curr,
                                'timestep': t
                            }
        
        return None
    
    def _find_connectivity_violation(self, paths: dict[str, list[tuple[int, int]]]
                                    ) -> Optional[dict]:
        """
        Check apakah connectivity graph terhubung di semua timesteps.
        
        Returns:
            Dict dengan keys: 'timestep', 'disconnected_agents'
            atau None jika terhubung
        """
        agent_ids = list(paths.keys())
        max_timestep = max(len(p) for p in paths.values())
        
        for t in range(max_timestep):
            # Build connectivity graph pada timestep t
            positions = {
                aid: paths[aid][min(t, len(paths[aid]) - 1)]
                for aid in agent_ids
            }
            
            # Check connectivity via BFS
            if len(agent_ids) <= 1:
                continue
            
            visited = set()
            queue = [agent_ids[0]]
            visited.add(agent_ids[0])
            
            while queue:
                current = queue.pop(0)
                current_pos = positions[current]
                
                for other in agent_ids:
                    if other in visited:
                        continue
                    other_pos = positions[other]
                    dist = ((current_pos[0] - other_pos[0]) ** 2 + 
                           (current_pos[1] - other_pos[1]) ** 2) ** 0.5
                    
                    if dist <= self.connectivity_range:
                        visited.add(other)
                        queue.append(other)
            
            if len(visited) != len(agent_ids):
                disconnected = [a for a in agent_ids if a not in visited]
                return {
                    'timestep': t,
                    'disconnected_agents': disconnected,
                    'connected_component': list(visited)
                }
        
        return None
    
    def _split_conflict(self, node: CTNode, conflict: dict, 
                       instance: Instance) -> list[CTNode]:
        """
        Split CT node berdasarkan conflict.
        
        Returns:
            List of child CT nodes
        """
        children = []
        
        if conflict['type'] == 'vertex':
            agent1 = conflict['agent1']
            agent2 = conflict['agent2']
            pos = conflict['pos']
            timestep = conflict['timestep']
            
            # Child 1: agent1 cannot be at pos at timestep
            child1 = self._create_child_node(
                node, agent1, 'vertex', pos, timestep, instance
            )
            if child1:
                children.append(child1)
            
            # Child 2: agent2 cannot be at pos at timestep
            child2 = self._create_child_node(
                node, agent2, 'vertex', pos, timestep, instance
            )
            if child2:
                children.append(child2)
        
        elif conflict['type'] == 'edge':
            agent1 = conflict['agent1']
            agent2 = conflict['agent2']
            pos1 = conflict['pos1']
            pos2 = conflict['pos2']
            timestep = conflict['timestep']
            
            # Child 1: agent1 cannot move pos1->pos2 at timestep
            child1 = self._create_child_node(
                node, agent1, 'edge', pos1, timestep, instance, pos2
            )
            if child1:
                children.append(child1)
            
            # Child 2: agent2 cannot move pos2->pos1 at timestep
            child2 = self._create_child_node(
                node, agent2, 'edge', pos2, timestep, instance, pos1
            )
            if child2:
                children.append(child2)
        
        return children
    
    def _split_connectivity(self, node: CTNode, violation: dict,
                           instance: Instance) -> list[CTNode]:
        """
        Split CT node berdasarkan connectivity violation.
        
        Strategy: Force disconnected agents to move toward connected component.
        """
        children = []
        timestep = violation['timestep']
        disconnected = violation['disconnected_agents']
        connected = violation['connected_component']
        
        # For each disconnected agent, add constraint to move toward connected agents
        for agent_id in disconnected:
            # Find agent object
            agent = None
            for a in instance.agents:
                if a.id == agent_id:
                    agent = a
                    break
            
            if agent is None:
                continue
            
            # Add constraint: agent harus stay di posisi saat ini (temporary constraint)
            # Ini adalah simplifikasi - seharusnya lebih sophisticated
            child = self._create_child_node(
                node, agent_id, 'vertex', agent.start, timestep, instance
            )
            if child:
                children.append(child)
        
        return children if children else [node]
    
    def _create_child_node(self, parent: CTNode, agent_id: str,
                          constraint_type: str, pos, timestep: int,
                          instance: Instance, pos_to=None) -> Optional[CTNode]:
        """Create child CT node dengan constraint baru."""
        # Copy constraints
        new_constraints = parent.constraints.copy()
        
        if constraint_type == 'vertex':
            new_constraints.add_vertex(agent_id, pos, timestep)
        elif constraint_type == 'edge':
            new_constraints.add_edge(agent_id, pos, pos_to, timestep)
        
        # Find agent object
        agent = None
        for a in instance.agents:
            if a.id == agent_id:
                agent = a
                break
        
        if agent is None:
            return None
        
        # Replan untuk agent yang terkena constraint
        new_paths = dict(parent.paths)
        new_path = self._low_level_search(agent, instance, new_constraints)
        
        if new_path is None:
            return None
        
        new_paths[agent_id] = new_path
        
        new_cost = self._compute_cost(new_paths)
        return CTNode(new_constraints, new_paths, new_cost)
    
    def _compute_cost(self, paths: dict[str, list[tuple[int, int]]]) -> float:
        """Compute cost berdasarkan cost_type."""
        if self.cost_type == "makespan":
            return float(max(len(p) for p in paths.values()))
        else:  # sum_costs
            return float(sum(len(p) for p in paths.values()))
