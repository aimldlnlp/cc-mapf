import pytest

from cc_mapf.execution import schedule_plan, timed_transition
from cc_mapf.model import AgentSpec, GridMap, Instance
from cc_mapf.planners.connected_step import connected_transition, separated_transition


def handoff():
    return ((1, 1), (3, 1), (2, 1), (2, 2)), ((1, 1), (4, 1), (3, 1), (2, 1))


def test_fixed_segment_timing_requires_a_collision_for_link_handoff():
    before, after = handoff()
    assert timed_transition(before, after, minimum_separation=.5) is None
    collision_route = timed_transition(before, after, minimum_separation=0.)
    assert collision_route is not None
    assert any(len(set(state)) < len(state) for state in collision_route)


def test_detour_keeps_checkpoints_and_continuous_safety():
    before, after = handoff()
    agents = [AgentSpec(str(i), p, q) for i, (p, q) in enumerate(zip(before, after))]
    instance = Instance('handoff', GridMap(6, 4), agents)
    plan = {a.id: [before[i], after[i]] for i, a in enumerate(agents)}
    assert schedule_plan(instance, plan)['status'] == 'infeasible'
    result = schedule_plan(instance, plan, detours=True)
    assert result['status'] == 'solved' and result['detour_transitions'] == [0]
    states = list(zip(*(result['plan'][a.id] for a in agents)))
    assert [states[k] for k in result['checkpoint_indices']] == [before, after]
    assert any(p != before[0] for p in result['plan']['0'])
    assert all(connected_transition(a, b) and separated_transition(a, b, .5) for a, b in zip(states, states[1:]))


def test_scheduler_rejects_non_integer_reference_checkpoints():
    instance = Instance('fractional', GridMap(3, 3), [AgentSpec('a', (0, 0), (1, 0))])
    with pytest.raises(ValueError, match='integer'):
        schedule_plan(instance, {'a': [(0, 0), (.5, 0), (1, 0)]})


def test_official_summary_counts_planner_failures_in_denominator(tmp_path, monkeypatch):
    import json
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts/dev'))
    from evaluate_official_mujoco import summarize
    rows = []
    for case, stage in [('failed', 'planner_failed'), ('solved', 'executed')]:
        directory = tmp_path/case
        directory.mkdir()
        pair = [dict(case=case, stage=stage, feedback=f, success=stage=='executed' and f,
                     disconnected_s=None, contact_steps=None, goal_error_m=None,
                     arrival_s=None, checkpoint_error_m=None) for f in [False, True]]
        (directory/'result.json').write_text(json.dumps(pair))
        rows.extend(pair)
    assert summarize(tmp_path, ['failed','solved']) == rows
    text = (tmp_path/'SUMMARY.md').read_text()
    assert '| True | 1/2 | 1/1 | 1 |' in text
    assert '| False | 0/2 | 0/1 | 1 |' in text
