from __future__ import annotations

from ..model import Planner
from .cbs import CBSPlanner
from .connected_step import ConnectedStepPlanner
from .enhanced_connected_step import EnhancedConnectedStepPlanner
from .greedy import GreedyPlanner
from .prioritized import PrioritizedPlanner

PLANNER_REGISTRY = {
    "greedy": GreedyPlanner,
    "prioritized": PrioritizedPlanner,
    "cbs": CBSPlanner,
    "connected_step": ConnectedStepPlanner,
    "enhanced_connected_step": EnhancedConnectedStepPlanner,
}


def build_planner(name: str) -> Planner:
    try:
        planner_cls = PLANNER_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown planner: {name}") from exc
    return planner_cls()


__all__ = [
    "CBSPlanner",
    "ConnectedStepPlanner",
    "EnhancedConnectedStepPlanner",
    "GreedyPlanner",
    "PrioritizedPlanner",
    "PLANNER_REGISTRY",
    "build_planner",
]
