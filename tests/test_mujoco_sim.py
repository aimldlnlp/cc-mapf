from argparse import Namespace
import json

import pytest

from cc_mapf.model import AgentSpec, ConnectivitySpec, GridMap, Instance
from cc_mapf.planners.connected_step import ConnectedStepPlanner
from cc_mapf.validation import validate_plan


def test_showcase_changes_visuals_without_changing_physics():
    mujoco = pytest.importorskip('mujoco')
    import numpy as np
    from cc_mapf.mujoco_sim import wheel_scene_xml
    from cc_mapf.mujoco_showcase import style_model
    instance = Instance('visual', GridMap(3, 3), [AgentSpec('a', (1, 1), (2, 1))])
    model = mujoco.MjModel.from_xml_string(wheel_scene_xml(instance, 1.))
    fields = ('qpos0', 'body_mass', 'body_inertia', 'geom_friction', 'geom_size',
              'geom_pos', 'geom_contype', 'geom_conaffinity', 'jnt_axis',
              'actuator_gainprm', 'actuator_biasprm', 'actuator_ctrlrange')
    before = {name: getattr(model, name).copy() for name in fields}
    style_model(model)
    assert (model.vis.global_.offwidth, model.vis.global_.offheight) == (1920, 1080)
    for name, value in before.items():
        assert np.array_equal(getattr(model, name), value), name


def test_goal_must_be_final_and_cost_counts_last_arrival():
    instance = Instance("goal", GridMap(4, 2), [AgentSpec("r", (0, 0), (1, 0))])
    assert not validate_plan(instance, {"r": [(0, 0), (1, 0), (2, 0)]}).valid
    result = validate_plan(instance, {"r": [(0, 0), (1, 0), (2, 0), (1, 0), (1, 0)]})
    assert result.valid and result.makespan == 3 and result.sum_of_costs == 3


def test_connected_step_rejects_unsupported_connectivity():
    instance = Instance("radius", GridMap(4, 2), [AgentSpec("r", (0, 0), (1, 0))], ConnectivitySpec(radius=2))
    with pytest.raises(ValueError, match="radius=1"):
        ConnectedStepPlanner().solve(instance, 1)


@pytest.mark.parametrize("physics", [False, True])
def test_mujoco_tracks_four_robot_plan(tmp_path, physics):
    pytest.importorskip("mujoco")
    from cc_mapf.mujoco_sim import run
    from cc_mapf.experiments import load_instance
    config = "configs/instances/example.yaml"
    instance = load_instance(config)
    result = ConnectedStepPlanner().solve(instance, 5)
    assert result.status == "solved"
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    report = run(Namespace(config=config, plan=str(plan_path), physics=physics, headless=True,
                           cell_size=1.0, step_seconds=1.0, max_speed=1.0, video=None, report=None))
    assert report["completed"]
    assert report["contact_steps"] == 0
    assert max(report["final_goal_errors_m"]) < .02
    assert report["disconnected_seconds"] < .01
    assert all(.2 < radius < .3 for radius in report["collision_radii_m"])


def test_corridor_physics_with_mesh_collision(tmp_path):
    pytest.importorskip("mujoco")
    from cc_mapf.mujoco_sim import run
    from cc_mapf.experiments import load_instance
    config = "configs/instances/mujoco_corridor.yaml"
    instance = load_instance(config)
    result = ConnectedStepPlanner().solve(instance, 10)
    assert result.status == "solved"
    path = tmp_path / "corridor.json"
    path.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    report = run(Namespace(config=config, plan=str(path), physics=True, headless=True,
                           cell_size=1., step_seconds=1.5, max_speed=1., video=None, report=None))
    assert report["completed"] and report["contact_steps"] == 0
    assert report["disconnected_seconds"] == 0
    assert max(report["final_goal_errors_m"]) < .02


def test_video_annotations_and_disconnect_status():
    mujoco = pytest.importorskip("mujoco")
    import numpy as np
    from cc_mapf.mujoco_sim import annotate_scene, label_frame
    scene = mujoco.MjvScene(mujoco.MjModel.from_xml_string('<mujoco/>'), maxgeom=10)
    positions = np.array([[0., 0.], [1., 0.]])
    annotate_scene(scene, positions, [(0, 1)], False, 1.)
    assert scene.ngeom == 1
    assert scene.geoms[0].rgba[0] == 1
    scene.camera[0].forward[:] = [0, 0, -1]
    scene.camera[0].up[:] = [0, 1, 0]
    scene.camera[0].pos[:] = [0, 0, 5]
    scene.camera[1].pos[:] = [0, 0, 5]
    scene.camera[0].frustum_near = .1
    scene.camera[0].frustum_top = .1
    scene.camera[0].frustum_bottom = -.1
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
    labeled = label_frame(frame, scene, positions, [AgentSpec('a', (0,0), (0,0)), AgentSpec('b', (1,0), (1,0))], 1., False, 1.)
    assert labeled.shape == frame.shape and labeled.sum() > 0


def test_l_turn_and_formation_change_stay_connected(tmp_path):
    pytest.importorskip("mujoco")
    from cc_mapf.experiments import load_instance
    from cc_mapf.mujoco_sim import run
    from cc_mapf.planners.connected_step import connected_transition
    instance = load_instance("configs/instances/mujoco_l_corridor.yaml")
    result = ConnectedStepPlanner().solve(instance, 5)
    assert result.status == "solved" and validate_plan(instance, result.plan).valid
    states = list(zip(*(result.plan[a.id] for a in instance.agents)))
    assert all(connected_transition(a, b) for a, b in zip(states, states[1:]))
    path = tmp_path / "turn.json"
    path.write_text(json.dumps(result.to_dict()), encoding="utf-8")
    report = run(Namespace(config="configs/instances/mujoco_l_corridor.yaml", plan=str(path), physics=True,
                           headless=True, cell_size=1., step_seconds=1.5, max_speed=1., video=None, report=None))
    assert report["completed"] and report["contact_steps"] == 0
    assert report["disconnected_seconds"] == 0
    assert max(report["final_goal_errors_m"]) < .002


def test_warehouse_refinement_recovers_continuous_motion(tmp_path):
    pytest.importorskip("mujoco")
    from cc_mapf.experiments import load_instance
    from cc_mapf.mujoco_sim import run
    from cc_mapf.connectivity import is_team_connected
    instance = load_instance("configs/instances/mujoco_warehouse.yaml")
    result = ConnectedStepPlanner().solve(instance, 5)
    assert result.status == "solved"
    assert result.metadata["waypoint_resolution_cells"] == .5
    assert validate_plan(instance, result.plan).valid
    states = list(zip(*(result.plan[a.id] for a in instance.agents)))
    for previous, current in zip(states, states[1:]):
        for phase in [n / 20 for n in range(21)]:
            positions = {a.id: tuple(p + (q-p)*phase for p,q in zip(previous[i], current[i])) for i,a in enumerate(instance.agents)}
            assert is_team_connected(positions, spec=instance.connectivity)
    path = tmp_path / 'warehouse.json'
    path.write_text(json.dumps(result.to_dict()), encoding='utf-8')
    report = run(Namespace(config='configs/instances/mujoco_warehouse.yaml', plan=str(path), physics=True,
                           headless=True, cell_size=1., step_seconds=1.5, max_speed=1., video=None, report=None))
    assert report['completed'] and report['contact_steps'] == 0
    assert report['disconnected_seconds'] == 0
    assert max(report['final_goal_errors_m']) < .02


def test_fractional_connectivity_tolerance_is_only_roundoff():
    from cc_mapf.connectivity import is_team_connected
    assert is_team_connected({'a': (1.075, 6.), 'b': (2.075, 6.)})
    assert not is_team_connected({'a': (1., 6.), 'b': (2.0001, 6.)})


def test_warehouse_seed_three_refined_search():
    from cc_mapf.generator import generate_instance
    instance = generate_instance('warehouse', 8, 8, 4, 3)
    instance.metadata.update(continuous_execution=True, continuous_refinement=True)
    result = ConnectedStepPlanner().solve(instance, 10)
    assert result.status == 'solved'
    assert validate_plan(instance, result.plan).valid


@pytest.mark.parametrize('drive,step_scale', [('planar', 1), ('wheels', 2)])
def test_formation_shift_tracking(tmp_path, drive, step_scale):
    pytest.importorskip('mujoco')
    from cc_mapf.generator import generate_instance
    from cc_mapf.mujoco_sim import run
    from cc_mapf.utils import dump_yaml
    instance = generate_instance('formation_shift', 8, 8, 4, 2)
    instance.metadata.update(continuous_execution=True, continuous_refinement=True, tracking_margin_cells=.08)
    result = ConnectedStepPlanner().solve(instance, 10)
    assert result.status == 'solved' and validate_plan(instance, result.plan).valid
    config, plan = tmp_path / 'instance.yaml', tmp_path / 'plan.json'
    dump_yaml(instance.to_dict(), config)
    plan.write_text(json.dumps(result.to_dict()), encoding='utf-8')
    report = run(Namespace(config=str(config), plan=str(plan), physics=True, drive=drive, headless=True,
                           cell_size=1., step_seconds=step_scale * 1.5 * result.metadata.get('waypoint_resolution_cells', 1),
                           max_speed=1., video=None, report=None))
    assert report['completed'] and report['contact_steps'] == 0
    assert report['numerical_warnings'] == 0
    assert report['disconnected_seconds'] == 0
    assert max(report['final_goal_errors_m']) < .02


def test_wheel_motion_requires_ground_traction():
    mujoco = pytest.importorskip('mujoco')
    import numpy as np
    from cc_mapf.mujoco_sim import wheel_scene_xml
    instance = Instance('traction', GridMap(5, 5), [AgentSpec('r01', (1, 1), (1, 1))])
    distances = []
    for friction in [True, False]:
        model = mujoco.MjModel.from_xml_string(wheel_scene_xml(instance, 1.))
        assert model.nu == 3 and model.njnt == 64
        if not friction:
            model.geom_friction[:] = 0
            model.geom_condim[:] = 1
            model.opt.noslip_iterations = 0
        data = mujoco.MjData(model)
        for _ in range(250):
            mujoco.mj_step(model, data)
        start = data.qpos[:2].copy()
        data.ctrl[:] = [2, 2, -4]
        for _ in range(1000):
            mujoco.mj_step(model, data)
        assert not any(w.number for w in data.warning)
        distances.append(float(np.linalg.norm(data.qpos[:2] - start)))
    assert distances[0] > .3
    assert distances[1] < .03


def test_single_wheel_robot_tracks_a_turn(tmp_path):
    pytest.importorskip('mujoco')
    from cc_mapf.mujoco_sim import run
    from cc_mapf.utils import dump_yaml
    instance = Instance('wheel_turn', GridMap(5, 5), [AgentSpec('r01', (1, 1), (3, 3))])
    config, plan = tmp_path / 'instance.yaml', tmp_path / 'plan.json'
    dump_yaml(instance.to_dict(), config)
    plan.write_text(json.dumps({'r01': [(1, 1), (2, 1), (3, 1), (3, 2), (3, 3)]}))
    report = run(Namespace(config=str(config), plan=str(plan), physics=True, drive='wheels', headless=True,
                           cell_size=1., step_seconds=3., max_speed=.5, video=None, report=None))
    assert report['mode'] == 'wheel_physics' and report['completed']
    assert report['contact_steps'] == 0 and report['wheel_ground_contact_steps'] > 0
    assert report['max_tracking_error_m'] < .1
    assert max(report['final_goal_errors_m']) < .02


def test_replay_waypoint_times_and_goal_arrivals(tmp_path):
    pytest.importorskip('mujoco')
    from cc_mapf.mujoco_sim import run
    from cc_mapf.utils import dump_yaml
    instance = Instance('timing', GridMap(4, 4), [AgentSpec('a', (0, 0), (2, 0))])
    config, plan = tmp_path / 'instance.yaml', tmp_path / 'plan.json'
    dump_yaml(instance.to_dict(), config)
    plan.write_text(json.dumps({'a': [(0, 0), (1, 0), (2, 0)]}))
    report = run(Namespace(config=str(config), plan=str(plan), physics=False, headless=True,
                           cell_size=1., step_seconds=1., max_speed=1., video=None, report=None))
    assert len(report['waypoint_samples']) == 3
    assert report['waypoint_disconnected_count'] == 0
    assert max(s.get('max_position_error_m', 0) for s in report['waypoint_samples']) < 1e-8
    assert abs(report['goal_arrival_times_s'][0] - 1.98) <= .0051


def test_replay_distinguishes_first_and_settled_arrival(tmp_path):
    pytest.importorskip('mujoco')
    from cc_mapf.mujoco_sim import run
    from cc_mapf.utils import dump_yaml
    instance = Instance('goal_departure', GridMap(3, 3), [AgentSpec('a', (0, 0), (1, 0))])
    config, plan = tmp_path / 'instance.yaml', tmp_path / 'plan.json'
    dump_yaml(instance.to_dict(), config)
    plan.write_text(json.dumps({'a': [(0, 0), (1, 0), (0, 0), (1, 0)]}))
    report = run(Namespace(config=str(config), plan=str(plan), physics=False, headless=True,
                           cell_size=1., step_seconds=1., max_speed=1., video=None, report=None))
    assert abs(report['first_goal_arrival_times_s'][0] - .98) <= .0051
    assert abs(report['goal_arrival_times_s'][0] - 2.98) <= .0051


def test_radio_feedback_anticipates_outward_motion_and_preserves_center():
    import numpy as np
    from cc_mapf.mujoco_sim import connectivity_velocity
    positions = np.array([[0., 0.], [.94, 0.]])
    stopped = np.zeros((2, 2))
    measured = np.array([[-.4, 0.], [.4, 0.]])
    assert np.array_equal(connectivity_velocity(positions, stopped, 1., 1.), stopped)
    corrected = connectivity_velocity(positions, stopped, 1., 1., measured)
    assert corrected[1, 0] - corrected[0, 0] < 0
    assert np.allclose(corrected.mean(axis=0), 0)
    assert np.linalg.norm(corrected, axis=1).max() <= 1
    # Both axes contribute at an L1 corner; protecting only the x-axis fails.
    diagonal = np.array([[0., 0.], [.5, .5]])
    desired = np.array([[-.2, -.2], [.2, .2]])
    corrected = connectivity_velocity(diagonal, desired, 1., 1.)
    assert (corrected[1]-corrected[0]).sum() < 0


def test_radio_feedback_brakes_before_robot_clearance_is_lost():
    import numpy as np
    from cc_mapf.mujoco_sim import connectivity_velocity
    positions = np.array([[0.,0.],[.6,0.]])
    desired = np.array([[.4,0.],[-.4,0.]])
    corrected = connectivity_velocity(positions,desired,1.,1.,desired,clearance=.48)
    assert corrected[1,0]-corrected[0,0] > 0
    assert np.allclose(corrected.mean(axis=0),0)
    assert np.linalg.norm(corrected,axis=1).max() <= 1.


def test_wheel_perturbations_are_bounded_connected_and_reproducible():
    mujoco = pytest.importorskip('mujoco')
    import numpy as np
    from cc_mapf.mujoco_sim import perturb_wheels, wheel_scene_xml
    instance = Instance('perturbation', GridMap(5,5),
                        [AgentSpec(str(i),p,p) for i,p in enumerate([(1,1),(2,1),(1,2),(2,2)])])
    results = []
    for _ in range(2):
        model = mujoco.MjModel.from_xml_string(wheel_scene_xml(instance,1.))
        data = mujoco.MjData(model)
        bodies = [model.body(f'robot_{i}').id for i in range(4)]
        friction = model.geom_friction.copy()
        result = perturb_wheels(model,data,bodies,dict(seed=7,position_jitter_m=.02,mass_scale=1.2,friction_scale=.7),1.)
        assert np.linalg.norm(result['offsets_m'],axis=1).max() <= .02
        assert result['initial_radio_tree_distance_m'] <= 1+1e-6
        assert not result['initial_contact']
        assert result['perturbed_robot_mass_kg'] == pytest.approx(1.2*result['original_robot_mass_kg'])
        assert np.allclose(model.geom_friction,.7*friction)
        results.append(result)
    assert results[0] == results[1]
    with pytest.raises(ValueError,match='jitter'):
        perturb_wheels(model,data,bodies,dict(position_jitter_m=.06),1.)


def test_line_formation_perturbation_survives_rare_admissible_sampling():
    mujoco = pytest.importorskip('mujoco')
    from cc_mapf.mujoco_sim import perturb_wheels, wheel_scene_xml
    instance = Instance('line',GridMap(7,4),
                        [AgentSpec(str(i),(i+1,1),(i+1,1)) for i in range(4)])
    model = mujoco.MjModel.from_xml_string(wheel_scene_xml(instance,1.))
    data = mujoco.MjData(model)
    result = perturb_wheels(model,data,[model.body(f'robot_{i}').id for i in range(4)],
                            dict(seed=7,position_jitter_m=.02),1.)
    assert 200 < result['attempts'] <= 10000
    assert result['initial_radio_tree_distance_m'] <= 1+1e-6
