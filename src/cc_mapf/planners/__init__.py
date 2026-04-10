from __future__ import annotations

from ..model import Planner
from .cbs import CBSPlanner
from .cc_cbs import CCCBSPlanner
from .connected_step import ConnectedStepPlanner
from .enhanced_connected_step import EnhancedConnectedStepPlanner
from .greedy import GreedyPlanner
from .prioritized import PrioritizedPlanner
from .prioritized_cc import PrioritizedCCPlanner
from .windowed_cc import WindowedCCPlanner

PLANNER_REGISTRY = {
    "greedy": GreedyPlanner,
    "prioritized": PrioritizedPlanner,
    "cbs": CBSPlanner,
    "connected_step": ConnectedStepPlanner,
    "enhanced_connected_step": EnhancedConnectedStepPlanner,
    "cc_cbs": CCCBSPlanner,
    "prioritized_cc": PrioritizedCCPlanner,
    "windowed_cc": WindowedCCPlanner,
}


def build_planner(name: str) -> Planner:
    try:
        planner_cls = PLANNER_REGISTRY[name]
    except KeyError as exc:
        raise ValueError(f"Unknown planner: {name}") from exc
    return planner_cls()


__all__ = [
    "CBSPlanner",
    "CCCBSPlanner",
    "ConnectedStepPlanner",
    "EnhancedConnectedStepPlanner",
    "GreedyPlanner",
    "PrioritizedPlanner",
    "PrioritizedCCPlanner",
    "WindowedCCPlanner",
    "PLANNER_REGISTRY",
    "build_planner",
]
