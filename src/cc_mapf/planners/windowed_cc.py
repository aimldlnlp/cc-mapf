#!/usr/bin/env python3
"""
Windowed Connectivity-Constrained MAPF.

Online replanning dengan finite horizon.
Cocok untuk dynamic environments dan large-scale problems.
"""

import heapq
from typing import Optional

from ..environment import is_free, neighbors
from ..model import AgentSpec, GridMap, Instance, Planner, PlannerResult


class WindowedCCPlanner(Planner):
    """
    Windowed planning dengan connectivity constraints.
    
    Algorithm:
    1. Plan untuk window pertama (e.g., 10 timesteps)
    2. Execute 1 timestep
    3. Update positions, shift window
    4. Replan dari posisi baru
    5. Repeat sampai semua agents reach goals
    
    Usage:
        planner = WindowedCCPlanner(window_size=10, replan_interval=1)
        result = planner.solve(instance, time_limit_s=300.0)
    """
    
    name: str = "windowed_cc"
    
    def __init__(self, window_size: int = 10,
                 replan_interval: int = 1,
                 connectivity_range: float = 3.0):
        """
        Args:
            window_size: Planning horizon (timesteps)
            replan_interval: Replan setiap N timesteps dieksekusi
            connectivity_range: Maximum distance untuk connectivity
        """
        self.window_size = window_size
        self.replan_interval = replan_interval
        self.connectivity_range = connectivity_range
        
    def solve(self, instance: Instance, time_limit_s: float = 300.0) -> PlannerResult:
        """
        Run windowed planning.
        
        Returns:
            PlannerResult dengan status dan plan
        """
        import time
        start_time = time.time()
        
        agents = list(instance.agents)
        grid = instance.grid
        
        # Current positions (start)
        current_positions: dict[str, tuple[int, int]] = {a.id: a.start for a in agents}
        agent_map = {a.id: a for a in agents}
        
        # Complete paths (accumulated)
        complete_paths: dict[str, list[tuple[int, int]]] = {
            a.id: [a.start] for a in agents
        }
        
        timestep = 0
        max_iterations = 1000  # Safety limit
        
        while not self._all_at_goals(current_positions, agents) and timestep < max_iterations:
            # Check time limit
            if time.time() - start_time > time_limit_s:
                return PlannerResult(
                    status="timeout",
                    plan=None,
                    runtime_s=time.time() - start_time,
                    expanded_nodes=0,
                    connectivity_rejections=0
                )
            
            # Plan untuk window berikutnya
            window_paths = self._plan_window(
                instance, current_positions, agents, timestep
            )
            
            if window_paths is None:
                return PlannerResult(
                    status="failure",
                    plan=None,
                    runtime_s=time.time() - start_time,
                    expanded_nodes=0,
                    connectivity_rejections=0
                )
            
            # Execute replan_interval steps
            for step in range(self.replan_interval):
                if timestep >= len(window_paths[agents[0].id]) - 1:
                    break
                
                next_positions = {}
                for agent in agents:
                    path = window_paths[agent.id]
                    next_pos = path[min(timestep + 1, len(path) - 1)]
                    next_positions[agent.id] = next_pos
                    complete_paths[agent.id].append(next_pos)
                
                # Check collisions
                if self._has_collision(next_positions):
                    return PlannerResult(
                        status="failure",
                        plan=None,
                        runtime_s=time.time() - start_time,
                        expanded_nodes=0,
                        connectivity_rejections=0
                    )
                
                # Check connectivity
                if not self._is_connected(next_positions):
                    return PlannerResult(
                        status="failure",
                        plan=None,
                        runtime_s=time.time() - start_time,
                        expanded_nodes=0,
                        connectivity_rejections=0
                    )
                
                current_positions = next_positions
                timestep += 1
                
                if self._all_at_goals(current_positions, agents):
                    break
        
        return PlannerResult(
            status="success",
            plan=complete_paths,
            runtime_s=time.time() - start_time,
            expanded_nodes=0,
            connectivity_rejections=0
        )
    
    def _plan_window(self, instance: Instance,
                    current_positions: dict[str, tuple[int, int]],
                    agents: list[AgentSpec],
                    start_timestep: int
                    ) -> Optional[dict[str, list[tuple[int, int]]]]:
        """
        Plan untuk window berikutnya (window_size steps).
        
        Uses prioritized planning dengan connectivity constraints.
        """
        # Sort agents by distance to goal
        agents_sorted = sorted(
            agents,
            key=lambda a: self._distance(current_positions[a.id], a.goal)
        )
        
        window_paths: dict[str, list[tuple[int, int]]] = {}
        
        # Build goals: agents should reach goal OR make progress
        window_goals = {}
        for agent in agents:
            dist = self._distance(current_positions[agent.id], agent.goal)
            if dist <= self.window_size:
                # Can reach goal dalam window ini
                window_goals[agent.id] = agent.goal
            else:
                # Make progress toward goal
                window_goals[agent.id] = self._compute_progress_goal(
                    agent, current_positions[agent.id], self.window_size
                )
        
        # Plan each agent
        for agent in agents_sorted:
            path = self._plan_agent_window(
                agent, instance, current_positions, window_goals[agent.id],
                window_paths, start_timestep
            )
            
            if path is None:
                return None
            
            window_paths[agent.id] = path
        
        return window_paths
    
    def _plan_agent_window(self, agent: AgentSpec, instance: Instance,
                          current_positions: dict[str, tuple[int, int]],
                          goal: tuple[int, int],
                          existing_paths: dict[str, list[tuple[int, int]]],
                          start_timestep: int
                          ) -> Optional[list[tuple[int, int]]]:
        """Plan path untuk satu agent dalam window."""
        grid = instance.grid
        start = current_positions[agent.id]
        
        # A* dengan constraints
        open_set: list[tuple[float, int, tuple[int, int], int]] = []
        heapq.heappush(open_set, (0.0, 0, start, 0))
        
        g_score: dict[tuple[tuple[int, int], int], float] = {(start, 0): 0.0}
        came_from: dict[tuple[tuple[int, int], int], tuple[tuple[int, int], int]] = {}
        counter = 1
        
        while open_set:
            _, _, pos, t = heapq.heappop(open_set)
            
            if t > self.window_size:
                continue
            
            # Check goal
            if pos == goal and t > 0:
                # Reconstruct path
                path = [pos]
                current_key = (pos, t)
                while current_key in came_from:
                    current_key = came_from[current_key]
                    path.append(current_key[0])
                path.reverse()
                
                # Pad path sampai window_size jika goal tercapai lebih awal
                while len(path) <= self.window_size:
                    path.append(pos)
                
                return path
            
            # Expand neighbors
            current_g = g_score.get((pos, t), float('inf'))
            
            for neighbor in neighbors(grid, pos, include_wait=True):
                new_t = t + 1
                
                # Check collision dengan agents lain
                collision = False
                for other_id, other_path in existing_paths.items():
                    if new_t < len(other_path) and other_path[new_t] == neighbor:
                        collision = True
                        break
                    # Edge collision check
                    if new_t > 0 and new_t < len(other_path):
                        if other_path[new_t - 1] == neighbor and other_path[new_t] == pos:
                            collision = True
                            break
                
                if collision:
                    continue
                
                if not is_free(grid, neighbor):
                    continue
                
                tentative_g = current_g + 1
                
                # Connectivity penalty
                penalty = self._compute_connectivity_penalty(
                    neighbor, new_t, existing_paths, current_positions
                )
                tentative_g += penalty
                
                neighbor_key = (neighbor, new_t)
                
                if tentative_g < g_score.get(neighbor_key, float('inf')):
                    came_from[neighbor_key] = (pos, t)
                    g_score[neighbor_key] = tentative_g
                    
                    h = abs(neighbor[0] - goal[0]) + abs(neighbor[1] - goal[1])
                    f = tentative_g + h
                    
                    heapq.heappush(open_set, (f, counter, neighbor, new_t))
                    counter += 1
        
        return None
    
    def _compute_progress_goal(self, agent: AgentSpec, 
                              current_pos: tuple[int, int],
                              max_steps: int) -> tuple[int, int]:
        """Compute intermediate goal yang membuat progress."""
        goal = agent.goal
        dx = goal[0] - current_pos[0]
        dy = goal[1] - current_pos[1]
        dist = (dx ** 2 + dy ** 2) ** 0.5
        
        if dist <= max_steps:
            return goal
        
        # Move max_steps toward goal
        ratio = max_steps / dist
        new_x = int(current_pos[0] + dx * ratio)
        new_y = int(current_pos[1] + dy * ratio)
        
        return (new_x, new_y)
    
    def _compute_connectivity_penalty(self, pos: tuple[int, int], t: int,
                                     existing_paths: dict[str, list[tuple[int, int]]],
                                     current_positions: dict[str, tuple[int, int]]
                                     ) -> float:
        """Compute connectivity penalty."""
        if not existing_paths:
            return 0.0
        
        min_dist = float('inf')
        
        for aid, path in existing_paths.items():
            if t < len(path):
                other_pos = path[t]
            else:
                other_pos = path[-1]
            
            dist = self._distance(pos, other_pos)
            min_dist = min(min_dist, dist)
        
        if min_dist <= self.connectivity_range:
            return 0.0
        else:
            return (min_dist - self.connectivity_range) * 0.5
    
    def _all_at_goals(self, positions: dict[str, tuple[int, int]], 
                     agents: list[AgentSpec]) -> bool:
        """Check apakah semua agents sudah di goals."""
        return all(positions[a.id] == a.goal for a in agents)
    
    def _has_collision(self, positions: dict[str, tuple[int, int]]) -> bool:
        """Check vertex collisions."""
        seen = set()
        for pos in positions.values():
            if pos in seen:
                return True
            seen.add(pos)
        return False
    
    def _is_connected(self, positions: dict[str, tuple[int, int]]) -> bool:
        """Check connectivity graph."""
        agent_ids = list(positions.keys())
        if len(agent_ids) <= 1:
            return True
        
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
                dist = self._distance(current_pos, other_pos)
                
                if dist <= self.connectivity_range:
                    visited.add(other)
                    queue.append(other)
        
        return len(visited) == len(agent_ids)
    
    def _distance(self, pos1: tuple[int, int], pos2: tuple[int, int]) -> float:
        """Euclidean distance."""
        return ((pos1[0] - pos2[0]) ** 2 + (pos1[1] - pos2[1]) ** 2) ** 0.5
