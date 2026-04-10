from __future__ import annotations

from ..model import Instance, PlannerResult
from .stepwise_common import stepwise_solve


class GreedyPlanner:
    name = "greedy"

    def solve(self, instance: Instance, time_limit_s: float) -> PlannerResult:
        return stepwise_solve(
            instance,
            name=self.name,
            time_limit_s=time_limit_s,
            enforce_connectivity=False,
            repair_depth=0,
            max_detours=1,
        )
