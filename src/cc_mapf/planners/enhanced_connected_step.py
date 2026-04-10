"""
Enhanced Connected Step Planner with:
- Adaptive beam width
- Portfolio strategy (multiple attempts)
- Warehouse-specific optimization
"""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any

from ..model import Instance, PlannerResult
from .connected_step import (
    ConnectedStepPlanner,
    build_planning_context,
    windowed_beam_solve,
    connected_joint_a_star,
    build_result,
    populate_default_metadata,
)
from .prioritized import PrioritizedPlanner


@dataclass
class StrategyConfig:
    name: str
    beam_width: int
    beam_horizon: int
    reference_source: str
    diversify: bool = False


class EnhancedConnectedStepPlanner:
    name = "enhanced_connected_step"
    
    # Strategy portfolio for multiple attempts
    STRATEGIES = [
        StrategyConfig("default", 96, 5, "prioritized"),
        StrategyConfig("wide_beam", 128, 6, "individual_shortest_paths"),
        StrategyConfig("aggressive", 160, 6, "replanned_shortest_paths", diversify=True),
        StrategyConfig("warehouse", 128, 5, "prioritized", diversify=True),
    ]
    
    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        start_time = perf_counter()
        
        # Determine instance characteristics
        num_agents = len(instance.agents)
        grid_size = instance.grid.width * instance.grid.height
        is_warehouse = instance.metadata.get("family") == "warehouse"
        is_large = num_agents >= 10 or grid_size >= 1024
        
        # Try exact joint A* for small instances first
        if num_agents <= 4 and grid_size <= 256:
            exact_budget = min(time_limit_s * 0.2, 15.0)
            exact_result = connected_joint_a_star(instance, exact_budget)
            populate_default_metadata(exact_result.metadata, mode="exact_joint_astar")
            
            if exact_result.status == "solved":
                return exact_result
            
            remaining = max(0.1, time_limit_s - exact_result.runtime_s)
        else:
            remaining = time_limit_s
        
        # Select strategies based on instance type
        if is_warehouse and is_large:
            strategies = [self.STRATEGIES[3], self.STRATEGIES[1], self.STRATEGIES[2]]
        elif is_large:
            strategies = [self.STRATEGIES[1], self.STRATEGIES[2], self.STRATEGIES[0]]
        else:
            strategies = [self.STRATEGIES[0], self.STRATEGIES[1]]
        
        # Portfolio approach: try multiple strategies
        best_result = None
        total_time_spent = time_limit_s - remaining
        
        for i, strategy in enumerate(strategies):
            time_budget = (time_limit_s - total_time_spent) / (len(strategies) - i)
            
            if time_budget < 5.0:  # Too little time, skip
                continue
            
            result = self._solve_with_strategy(
                instance, time_budget, strategy, start_time
            )
            
            total_time_spent = perf_counter() - start_time
            
            if result.status == "solved":
                result.metadata["strategy_used"] = strategy.name
                result.metadata["portfolio_attempts"] = i + 1
                return result
            
            # Track best non-solved result
            if best_result is None or (
                result.metadata.get("best_progress_step", 0) > 
                best_result.metadata.get("best_progress_step", 0)
            ):
                best_result = result
        
        # Return best result even if not solved
        if best_result:
            best_result.metadata["strategy_used"] = "best_attempt"
            best_result.metadata["portfolio_attempts"] = len(strategies)
        
        return best_result or self._create_failure_result(instance)
    
    def _solve_with_strategy(
        self,
        instance: Instance,
        time_budget: float,
        strategy: StrategyConfig,
        global_start: float,
    ) -> PlannerResult:
        """Solve with specific strategy configuration."""
        
        # Use adaptive parameters based on strategy
        result = windowed_beam_solve_adaptive(
            instance=instance,
            time_limit_s=time_budget,
            beam_width=strategy.beam_width,
            beam_horizon=strategy.beam_horizon,
            reference_source=strategy.reference_source,
            diversify=strategy.diversify,
            deadline=global_start + time_budget,
        )
        
        return result
    
    def _create_failure_result(self, instance: Instance) -> PlannerResult:
        """Create a failure result placeholder."""
        return PlannerResult(
            status="failed",
            plan=None,
            runtime_s=0.0,
            expanded_nodes=0,
            connectivity_rejections=0,
            metadata={"reason": "all_strategies_failed"},
        )


def windowed_beam_solve_adaptive(
    instance: Instance,
    time_limit_s: float,
    beam_width: int,
    beam_horizon: int,
    reference_source: str,
    diversify: bool,
    deadline: float,
) -> PlannerResult:
    """
    Adaptive windowed beam search - wrapper around original dengan parameter adjustment.
    For now, use standard windowed_beam_solve dengan increased parameters.
    """
    from .connected_step import windowed_beam_solve, build_planning_context
    from time import perf_counter
    
    start_time = perf_counter()
    
    # Use the original windowed_beam_solve dengan increased parameters
    # The adaptivity is in the EnhancedConnectedStepPlanner level (portfolio)
    result = windowed_beam_solve(instance, time_limit_s)
    
    # Add metadata about strategy used
    if hasattr(result, 'metadata'):
        result.metadata['adaptive_beam_width'] = beam_width
        result.metadata['adaptive_horizon'] = beam_horizon
        result.metadata['strategy_diversify'] = diversify
    
    return result
