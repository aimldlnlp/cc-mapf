#!/usr/bin/env python3
"""
Prioritized Connectivity-Constrained MAPF.

Plan agents secara berurutan dengan priority ordering.
Fast dan scalable, tapi suboptimal.
"""

import heapq
from typing import Optional

from ..environment import is_free, neighbors
from ..model import AgentSpec, GridMap, Instance, Planner, PlannerResult


class PrioritizedCCPlanner(Planner):
    """
    Prioritized planning dengan connectivity constraints.
    
    Algorithm:
    1. Sort agents by priority (default: distance to goal)
    2. For each agent in order:
       - Plan path dengan A*
       - Add constraints: must maintain connectivity to already-planned agents
       - Treat other agents sebagai dynamic obstacles
    
    Usage:
        planner = PrioritizedCCPlanner(connectivity_range=3.0)
        result = planner.solve(instance, time_limit_s=300.0)
    """
    
    name: str = "prioritized_cc"
    
    def __init__(self, connectivity_range: float = 3.0,
                 priority_order: str = "goal_distance"):
        """
        Args:
            connectivity_range: Maximum distance untuk connectivity
            priority_order: "goal_distance", "start_distance", atau "random"
        """
        self.connectivity_range = connectivity_range
        self.priority_order = priority_order
        
    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        """
        Run prioritized planning.
        
        Returns:
            PlannerResult dengan status dan plan
        """
        import time
        start_time = time.time()
        
        agents = list(instance.agents)
        
        # Sort agents by priority
        if self.priority_order == "goal_distance":
            agents.sort(key=lambda a: self._distance(a.start, a.goal))
        elif self.priority_order == "start_distance":
            agents.sort(key=lambda a: a.start[0] + a.start[1])
        # else: random order (as-is)
        
        paths: dict[str, list[tuple[int, int]]] = {}
        planned_positions: dict[int, list[tuple[int, int]]] = {}  # timestep -> positions
        
        for agent in agents:
            # Check time limit
            if time.time() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=time.time() - start_time,
                    expanded_nodes=0,
                    connectivity_rejections=0
                )
            
            path = self._plan_agent_with_connectivity(
                agent, instance, paths, planned_positions
            )
            if path is None:
                return PlannerResult(
                    status="failure",
                    plan=None,
                    runtime_s=time.time() - start_time,
                    expanded_nodes=0,
                    connectivity_rejections=0
                )
            
            paths[agent.id] = path
            
            # Update planned positions
            for t, pos in enumerate(path):
                if t not in planned_positions:
                    planned_positions[t] = []
                planned_positions[t].append(pos)
        
        return PlannerResult(
            status="success",
            plan=paths,
            runtime_s=time.time() - start_time,
            expanded_nodes=0,
            connectivity_rejections=0
        )
    
    def _plan_agent_with_connectivity(self, agent: AgentSpec, instance: Instance,
                                     existing_paths: dict[str, list[tuple[int, int]]],
                                     planned_positions: dict[int, list[tuple[int, int]]]
                                     ) -> Optional[list[tuple[int, int]]]:
        """
        Plan single agent dengan connectivity constraints ke agents yang sudah diplan.
        
        Strategy: A* dengan modified cost untuk encourage connectivity.
        """
        grid = instance.grid
        start = agent.start
        goal = agent.goal
        
        if not existing_paths:
            # First agent: no connectivity constraint
            return self._simple_a_star(grid, start, goal, planned_positions)
        
        # Get reference positions from already planned agents
        
        # A* dengan connectivity awareness
        open_set: list[tuple[float, int, tuple[int, int], int]] = []
        heapq.heappush(open_set, (0.0, 0, start, 0))
        
        g_score: dict[tuple[tuple[int, int], int], float] = {(start, 0): 0.0}
        came_from: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
        counter = 1
        max_timestep = 500
        
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
                
                # Check collision dengan agents lain
                if new_timestep in planned_positions and neighbor in planned_positions[new_timestep]:
                    continue
                
                if not is_free(grid, neighbor):
                    continue
                
                tentative_g = current_g + 1
                
                # Connectivity penalty
                connectivity_penalty = self._compute_connectivity_penalty(
                    neighbor, new_timestep, existing_paths
                )
                tentative_g += connectivity_penalty
                
                neighbor_key = (neighbor, new_timestep)
                
                if tentative_g < g_score.get(neighbor_key, float('inf')):
                    came_from[neighbor_key] = (pos, timestep)
                    g_score[neighbor_key] = tentative_g
                    
                    # Heuristic
                    h = abs(neighbor[0] - goal[0]) + abs(neighbor[1] - goal[1])
                    f = tentative_g + h
                    
                    heapq.heappush(open_set, (f, counter, neighbor, new_timestep))
                    counter += 1
        
        return None
    
    def _compute_connectivity_penalty(self, pos: tuple[int, int], timestep: int,
                                     existing_paths: dict[str, list[tuple[int, int]]]
                                     ) -> float:
        """
        Compute penalty untuk positions yang jauh dari connected agents.
        
        Returns:
            0 jika connected, positive value jika disconnected
        """
        min_dist = float('inf')
        
        for aid, path in existing_paths.items():
            other_pos = path[min(timestep, len(path) - 1)]
            dist = self._distance(pos, other_pos)
            min_dist = min(min_dist, dist)
        
        if min_dist <= self.connectivity_range:
            return 0.0  # Connected, no penalty
        else:
            # Penalty proportional to distance beyond range
            return (min_dist - self.connectivity_range) * 0.5
    
    def _simple_a_star(self, grid: GridMap, start: tuple[int, int], goal: tuple[int, int],
                      obstacles: dict) -> Optional[list[tuple[int, int]]]:
        """Standard A* tanpa connectivity constraints."""
        open_set: list[tuple[float, int, tuple[int, int]]] = []
        heapq.heappush(open_set, (0.0, 0, start))
        
        g_score: dict[tuple[int, int], float] = {start: 0.0}
        came_from: dict[tuple[int, int], tuple[int, int]] = {}
        counter = 1
        
        while open_set:
            _, _, pos = heapq.heappop(open_set)
            
            if pos == goal:
                # Reconstruct path
                path = [pos]
                while pos in came_from:
                    pos = came_from[pos]
                    path.append(pos)
                path.reverse()
                return path
            
            for neighbor in neighbors(grid, pos, include_wait=True):
                if not is_free(grid, neighbor):
                    continue
                
                tentative_g = g_score[pos] + 1
                
                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = pos
                    g_score[neighbor] = tentative_g
                    
                    h = abs(neighbor[0] - goal[0]) + abs(neighbor[1] - goal[1])
                    f = tentative_g + h
                    
                    heapq.heappush(open_set, (f, counter, neighbor))
                    counter += 1
        
        return None
    
    def _distance(self, pos1: tuple[int, int], pos2: tuple[int, int]) -> float:
        """Euclidean distance."""
        return ((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2) ** 0.5
