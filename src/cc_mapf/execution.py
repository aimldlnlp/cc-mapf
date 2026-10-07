"""Small execution variants that keep every original grid checkpoint."""
from collections import deque
from itertools import product

from .model import AgentSpec, GridMap, Instance
from .planners.connected_step import connected_transition, refined_continuous_solve, separated_transition
from .validation import pad_plan, validate_plan


def timed_transition(previous, current, subdivisions=4, minimum_separation=.5):
    """Search monotone progress along fixed segments; robots may wait."""
    active = [i for i, (p, q) in enumerate(zip(previous, current)) if p != q]

    def positions(progress):
        state = list(previous)
        for i, fraction in zip(active, progress):
            state[i] = tuple(p + (q-p)*fraction/subdivisions for p, q in zip(previous[i], current[i]))
        return tuple(state)

    if connected_transition(previous, current) and separated_transition(previous, current, minimum_separation):
        return [positions((k,) * len(active)) for k in range(subdivisions+1)]
    start, goal = (0,) * len(active), (subdivisions,) * len(active)
    parents = {start: None}
    pending = deque([start])
    moves = [m for m in product((0, 1), repeat=len(active)) if any(m)]
    while pending:
        state = pending.popleft()
        if state == goal:
            route = []
            while state is not None:
                route.append(positions(state))
                state = parents[state]
            return route[::-1]
        before = positions(state)
        for move in moves:
            following = tuple(s+m for s, m in zip(state, move))
            if max(following, default=0) > subdivisions or following in parents:
                continue
            after = positions(following)
            if connected_transition(before, after) and separated_transition(before, after, minimum_separation):
                parents[following] = state
                pending.append(following)
    return None


def local_detour(instance, previous, current, subdivisions):
    """Reuse the existing half-cell planner inside a small cropped arena."""
    cells = previous + current
    low = [max(0, min(p[k] for p in cells)-1) for k in (0, 1)]
    high = [min(size-1, max(p[k] for p in cells)+1) for k, size in enumerate((instance.grid.width, instance.grid.height))]
    agents = [AgentSpec(a.id, tuple(previous[i][k]-low[k] for k in (0, 1)),
                        tuple(current[i][k]-low[k] for k in (0, 1))) for i, a in enumerate(instance.agents)]
    obstacles = {(x-low[0], y-low[1]) for x, y in instance.grid.obstacles if low[0] <= x <= high[0] and low[1] <= y <= high[1]}
    local = Instance('execution_patch', GridMap(high[0]-low[0]+1, high[1]-low[1]+1, obstacles), agents)
    result = refined_continuous_solve(local, 5.)
    if result.plan is None:
        return None
    states = [tuple(tuple(p[k]+low[k] for k in (0, 1)) for p in state)
              for state in zip(*(result.plan[a.id] for a in agents))]
    route = [states[0]]
    for before, after in zip(states, states[1:]):
        for tick in range(1, subdivisions//2+1):
            route.append(tuple(tuple(p+(q-p)*tick/(subdivisions//2) for p, q in zip(a, b)) for a, b in zip(before, after)))
    return route


def schedule_plan(instance, plan, *, detours=False, subdivisions=4, experimental_six=False):
    limit = 6 if experimental_six else 4
    if instance.connectivity.mode != 'adjacency' or instance.connectivity.radius != 1 or len(instance.agents) > limit:
        raise ValueError('Execution scheduling supports at most four agents with radius-1 adjacency.')
    if subdivisions not in (2, 4, 8) or not validate_plan(instance, plan).valid:
        raise ValueError('Use a valid grid plan and subdivisions 2, 4, or 8.')
    padded, _ = pad_plan(instance, plan)
    states = [tuple(state) for state in zip(*(padded[a.id] for a in instance.agents))]
    if any(any(v != int(v) for v in p) for state in states for p in state):
        raise ValueError('Reference checkpoints must use integer grid cells.')
    route, checkpoints, failures, patches = [states[0]], [0], [], []
    for tick, (before, after) in enumerate(zip(states, states[1:])):
        segment = timed_transition(before, after, subdivisions)
        if segment is None and detours:
            segment = local_detour(instance, before, after, subdivisions)
            if segment is not None:
                patches.append(tick)
        if segment is None:
            failures.append(tick)
            continue
        if not all(connected_transition(a, b) and separated_transition(a, b, .5) for a, b in zip(segment, segment[1:])):
            raise RuntimeError('Execution patch violates connectivity or separation.')
        route.extend(segment[1:])
        checkpoints.append(len(route)-1)
    output = {a.id: [s[i] for s in route] for i, a in enumerate(instance.agents)} if not failures else None
    if output is not None:
        assert validate_plan(instance, output).valid
        assert [route[index] for index in checkpoints] == states
    return {'status': 'solved' if output is not None else 'infeasible',
            'mode': 'checkpoint_detours' if detours else 'timing_only', 'subdivisions': subdivisions,
            'minimum_separation_cells': .5, 'infeasible_transitions': failures, 'detour_transitions': patches,
            'checkpoint_indices': checkpoints if output is not None else None, 'plan': output}
