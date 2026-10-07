"""Six-agent opt-in preserves checkpoints; audits detect a known violation."""
import sys
from pathlib import Path
import numpy as np
import pytest
from cc_mapf.execution import schedule_plan
from cc_mapf.model import AgentSpec,GridMap,Instance


def test_six_agent_opt_in_and_residual_audit():
    agents=[AgentSpec(str(i),(i+1,1),(i+1,2)) for i in range(6)]
    instance=Instance('six',GridMap(9,4),agents)
    plan={a.id:[a.start,a.goal] for a in agents}
    with pytest.raises(ValueError): schedule_plan(instance,plan)
    result=schedule_plan(instance,plan,experimental_six=True)
    assert result['status']=='solved'
    assert result['checkpoint_indices']==[0,4]
    assert all(result['plan'][a.id][0]==a.start and result['plan'][a.id][-1]==a.goal for a in agents)
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/dev'))
    from evaluate_six_robot import residuals
    positions=np.array([[0.,0.],[1.,0.]])
    velocity=np.array([[-.4,0.],[.4,0.]])
    radio,clearance=residuals(positions,velocity,np.zeros_like(positions),[(0,1,1.)],1.,0.,.48,.25)
    assert radio==pytest.approx(.1) and clearance==0
    assert residuals(positions,np.zeros_like(positions),np.zeros_like(positions),[(0,1,1.)],1.,0.,.48,.25)==(0.,0.)


def test_obstacle_projection_checks_all_constraints_after_speed_limit():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/dev'))
    from obstacle_feedback import project,box_distance
    positions=np.array([[-.8,0.],[-1.7,0.]])
    velocity,audit=project(positions,np.array([[1.,0.],[1.,0.]]),1.,1.,np.array([[.5,0.],[.5,0.]]),
        .04,.48,.25,[(np.zeros(2),np.array([.5,.5]))],.22)
    assert audit['converged'] and max(audit[k] for k in ['radio','pair','obstacle'])<=1e-6
    assert np.linalg.norm(velocity,axis=1).max()<=1+1e-12
    assert velocity[0,0]<0
    assert box_distance(np.zeros(2),np.zeros(2),np.array([.5,.5]))[0]==-.5
    # Mutually conflicting close robots cannot be certified feasible by clipping.
    _,audit=project(np.array([[0.,0.],[.01,0.]]),np.zeros((2,2)),1.,.01,
        np.zeros((2,2)),.04,.48,.25,[],.22,max_iterations=3)
    assert not audit['converged'] and audit['pair']>0
