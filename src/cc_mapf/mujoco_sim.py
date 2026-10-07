"""MuJoCo replay and planar robot tracking for existing CC-MAPF plans."""
from __future__ import annotations

import json
import copy
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .experiments import load_instance
from .validation import validate_plan

COLORS = [(0.2, 0.5, 0.9), (0.9, 0.35, 0.2), (0.2, 0.7, 0.4), (0.7, 0.3, 0.8)]
# Native collision rollers: 28.5 mm center radius plus 6 mm bearing radius.
WHEEL_RADIUS = .0345


def scene_xml(instance, cell_size: float, physics: bool, robot_model: str = "soccer") -> str:
    root = ET.Element("mujoco", model="cc_mapf")
    ET.SubElement(root, "option", timestep="0.005")
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "global", offwidth="1280", offheight="720")
    ET.SubElement(visual, "headlight", ambient="0.35 0.35 0.35", diffuse="0.55 0.55 0.55", specular="0.1 0.1 0.1")
    asset_root = Path(__file__).parent / "assets" / "robot_soccer_kit"
    source = ET.parse(asset_root / "robot_soccer_kit.xml").getroot() if robot_model == "soccer" else None
    scale = 2.5 * cell_size
    if source is not None:
        assets = copy.deepcopy(source.find("asset"))
        for mesh in assets.findall("mesh"):
            mesh.set("name", Path(mesh.get("file")).stem)
            mesh.set("file", str((asset_root / "assets" / mesh.get("file")).resolve()))
            mesh.set("scale", f"{scale} {scale} {scale}")
        root.append(assets)
    world = ET.SubElement(root, "worldbody")
    width, height = instance.grid.width * cell_size, instance.grid.height * cell_size
    ET.SubElement(world, "light", pos=f"{width / 2} {height / 2} 8", diffuse="0.7 0.7 0.7")
    ET.SubElement(world, "geom", name="floor", type="plane", size=f"{width} {height} 0.1", rgba="0.13 0.17 0.22 1")
    for x in range(instance.grid.width + 1):
        ET.SubElement(world, "geom", type="box", pos=f"{x * cell_size} {height / 2} 0.001",
                      size=f"{.002 * cell_size} {height / 2} .001", rgba="0.55 0.6 0.65 1", contype="0", conaffinity="0")
    for y in range(instance.grid.height + 1):
        ET.SubElement(world, "geom", type="box", pos=f"{width / 2} {y * cell_size} 0.001",
                      size=f"{width / 2} {.002 * cell_size} .001", rgba="0.55 0.6 0.65 1", contype="0", conaffinity="0")
    for index, (x, y) in enumerate(sorted(instance.grid.obstacles)):
        ET.SubElement(world, "geom", name=f"wall_{index}", type="box",
                      pos=f"{(x + .5) * cell_size} {(y + .5) * cell_size} {cell_size / 2}",
                      size=f"{cell_size / 2} {cell_size / 2} {cell_size / 2}", rgba="0.3 0.35 0.4 1")
    actuators = ET.SubElement(root, "actuator") if physics else None
    for index, agent in enumerate(instance.agents):
        color = " ".join(str(v) for v in COLORS[index % len(COLORS)])
        gx, gy = agent.goal
        ET.SubElement(world, "geom", name=f"goal_{index}", type="cylinder",
                      pos=f"{(gx + .5) * cell_size} {(gy + .5) * cell_size} 0.005",
                      size=f"{.3 * cell_size} 0.005", rgba=f"{color} 0.6", contype="0", conaffinity="0")
        x, y = agent.start
        body = ET.SubElement(world, "body", name=f"robot_{index}",
                             pos=f"{(x + .5) * cell_size} {(y + .5) * cell_size} {0.11 * cell_size}",
                             **({} if physics else {"mocap": "true"}))
        if physics:
            for axis, direction in [("x", "1 0 0"), ("y", "0 1 0")]:
                joint = f"robot_{index}_{axis}"
                ET.SubElement(body, "joint", name=joint, type="slide", axis=direction, damping="2")
                ET.SubElement(actuators, "motor", joint=joint, ctrllimited="true", ctrlrange="-20 20")
        ET.SubElement(body, "geom", name=f"robot_geom_{index}", type="cylinder",
                      size=f"{.15 * cell_size} {.1 * cell_size}", mass="1", rgba=f"{color} {0 if source is not None else 1}")
        if source is not None:
            robot = copy.deepcopy(source.find("worldbody/body"))
            for parent in robot.iter():
                for child in list(parent):
                    if child.tag in ("joint", "freejoint", "inertial") or (child.tag == "geom" and child.get("class") != "visual"):
                        parent.remove(child)
                parent.attrib.pop("class", None)
                parent.attrib.pop("childclass", None)
                parent.attrib.pop("name", None)
                if parent.get("pos"):
                    parent.set("pos", " ".join(str(float(v) * scale) for v in parent.get("pos").split()))
                if parent.tag == "geom":
                    parent.set("contype", "0")
                    parent.set("conaffinity", "0")
                    parent.set("mass", "0")
                    if parent.get("mesh") == "blue1_blue":
                        parent.attrib.pop("material", None)
                        parent.set("rgba", f"{color} 1")
            robot.set("pos", f"0 0 {-0.03 * cell_size}")
            body.append(robot)
        else:
            ET.SubElement(body, "geom", type="box", pos=f"{.1 * cell_size} 0 {.105 * cell_size}",
                      size=f"{.05 * cell_size} {.02 * cell_size} {.01 * cell_size}",
                      rgba="1 1 1 1", contype="0", conaffinity="0", mass="0")
    if source is not None:
        import mujoco
        import numpy as np
        probe = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
        state = mujoco.MjData(probe)
        mujoco.mj_forward(probe, state)
        for index in range(len(instance.agents)):
            body_id = probe.body(f"robot_{index}").id
            points = []
            for geom_id in range(probe.ngeom):
                ancestor = int(probe.geom_bodyid[geom_id])
                while ancestor and ancestor != body_id:
                    ancestor = int(probe.body_parentid[ancestor])
                mesh_id = int(probe.geom_dataid[geom_id])
                if ancestor != body_id or probe.geom_type[geom_id] != mujoco.mjtGeom.mjGEOM_MESH:
                    continue
                start, count = probe.mesh_vertadr[mesh_id], probe.mesh_vertnum[mesh_id]
                vertices = probe.mesh_vert[start:start + count]
                points.append(vertices @ state.geom_xmat[geom_id].reshape(3, 3).T + state.geom_xpos[geom_id] - state.xpos[body_id])
            points = np.concatenate(points)
            radius = float(np.linalg.norm(points[:, :2], axis=1).max()) + .005 * cell_size
            bottom, top = float(points[:, 2].min()), float(points[:, 2].max())
            collision = root.find(f".//geom[@name='robot_geom_{index}']")
            collision.set("size", f"{radius} {(top - bottom) / 2 + .005 * cell_size}")
            collision.set("pos", f"0 0 {(top + bottom) / 2}")
    return ET.tostring(root, encoding="unicode")


def annotate_scene(scene, positions, edges, connected, cell_size, showcase=False):
    import mujoco
    import numpy as np
    for first, second in edges:
        if scene.ngeom >= scene.maxgeom:
            break
        geom = scene.geoms[scene.ngeom]
        color = [0.15, .9, .65, .35 if showcase else 1] if connected else [1, .2, .15, .7 if showcase else 1]
        mujoco.mjv_initGeom(geom, mujoco.mjtGeom.mjGEOM_LINE, np.zeros(3), np.zeros(3), np.eye(3).ravel(), np.array(color, dtype=np.float32))
        a = np.array([*positions[first], .4 * cell_size])
        b = np.array([*positions[second], .4 * cell_size])
        mujoco.mjv_connector(geom, mujoco.mjtGeom.mjGEOM_LINE, 1.4 if showcase else 3, a, b)
        scene.ngeom += 1


def label_frame(frame, scene, positions, agents, elapsed, connected, cell_size, showcase=False):
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    image = Image.fromarray(frame)
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 22)
    except OSError:
        font = ImageFont.load_default(size=22)
    if showcase:
        draw.rounded_rectangle((32,32,365,110),radius=12,fill='#18232c')
        draw.text((50,45),'CC-MAPF',font=font,fill='white')
        draw.text((50,77),'Connected robot motion',font=font,fill='#b9cbd7')
        right = frame.shape[1]-32
        draw.rounded_rectangle((right-220,32,right,80),radius=12,fill='#18232c')
        color = '#4dd5a2' if connected else '#ff7965'
        draw.ellipse((right-202,48,right-188,62),fill=color)
        draw.text((right-176,43),'Connected' if connected else 'Disconnected',font=font,fill=color)
        draw.rounded_rectangle((32,frame.shape[0]-76,174,frame.shape[0]-32),radius=10,fill='#18232c')
        draw.text((50,frame.shape[0]-65),f'{elapsed:05.1f} s',font=font,fill='white')
        return np.asarray(image)
    camera = scene.camera[0]
    origin = (scene.camera[0].pos + scene.camera[1].pos) / 2
    forward, up = camera.forward, camera.up
    right = np.cross(forward, up)
    focal = frame.shape[0] * camera.frustum_near / (camera.frustum_top - camera.frustum_bottom)
    for index, agent in enumerate(agents):
        delta = np.array([*positions[index], .42 * cell_size]) - origin
        depth = float(delta @ forward)
        if depth <= 0:
            continue
        x = frame.shape[1] / 2 + focal * (delta @ right) / depth
        y = frame.shape[0] / 2 - focal * (delta @ up) / depth
        draw.text((x, y), agent.id, font=font, fill="white", stroke_width=2, stroke_fill="#111923", anchor="mm")
    draw.rounded_rectangle((20, 20, 530, 80), radius=10, fill="#111923")
    draw.text((35, 38), f"CC-MAPF  |  {elapsed:04.1f}s  |  {'CONNECTED' if connected else 'DISCONNECTED'}", font=font,
              fill="#65f0be" if connected else "#ff6655")
    return np.asarray(image)


def wheel_scene_xml(instance, cell_size):
    """Reuse the vendored three-omni-wheel mechanism, including passive rollers."""
    root = ET.fromstring(scene_xml(instance, cell_size, False, 'soccer'))
    source = ET.parse(Path(__file__).parent / 'assets/robot_soccer_kit/robot_soccer_kit.xml').getroot()
    root.append(copy.deepcopy(source.find('default')))
    root.find('option').set('timestep', '0.002')
    root.find('option').set('noslip_iterations', '1')
    root.find('option').set('integrator', 'implicitfast')
    world = root.find('worldbody')
    for geom in world.findall('geom'):
        if geom.get('name') == 'floor' or geom.get('name', '').startswith('wall_'):
            geom.set('contype', '3')
            geom.set('conaffinity', '3')
    actuators = ET.SubElement(root, 'actuator')
    scale = 2.5 * cell_size
    for index, agent in enumerate(instance.agents):
        old = world.find(f"body[@name='robot_{index}']")
        chassis = copy.deepcopy(old.find('geom'))
        chassis.set('pos', f'0 0 {.13 * cell_size}')
        chassis.set('size', f"{chassis.get('size').split()[0]} {.04 * cell_size}")
        chassis.set('mass', '0')
        # Separate proxy chassis from its own rollers; robot proxies still collide.
        chassis.set('contype', '2')
        chassis.set('conaffinity', '2')
        world.remove(old)
        robot = copy.deepcopy(source.find('worldbody/body'))
        for parent in robot.iter():
            for child in list(parent):
                if child.tag == 'joint' and child.get('name') == 'kicker':
                    parent.remove(child)
            if parent.get('name'):
                parent.set('name', f"r{index}_{parent.get('name')}")
            if parent.get('pos'):
                parent.set('pos', ' '.join(str(float(v) * scale) for v in parent.get('pos').split()))
            for attribute in ('size', 'range'):
                if parent.get(attribute):
                    parent.set(attribute, ' '.join(str(float(v) * scale) for v in parent.get(attribute).split()))
            if parent.tag == 'inertial':
                parent.set('fullinertia', ' '.join(str(float(v) * scale**2) for v in parent.get('fullinertia').split()))
            if parent.tag == 'joint':
                parent.set('frictionloss', '0.001' if '_speed' in parent.get('name', '') else '0')
                parent.set('armature', '0.0001' if '_speed' in parent.get('name', '') else '0.000001')
                parent.set('damping', '0.001' if '_speed' in parent.get('name', '') else '0.00001')
            if parent.tag == 'geom' and parent.get('mesh') == 'blue1_blue':
                parent.attrib.pop('material', None)
                parent.set('rgba', ' '.join(map(str, (*COLORS[index % len(COLORS)], 1))))
        robot.set('name', f'robot_{index}')
        robot.set('pos', f'{(agent.start[0]+.5)*cell_size} {(agent.start[1]+.5)*cell_size} {.0435 * cell_size}')
        robot.append(chassis)
        world.append(robot)
        for wheel in range(1, 4):
            ET.SubElement(actuators, 'velocity', name=f'r{index}_wheel{wheel}', joint=f'r{index}_wheel{wheel}_speed',
                          kv='0.1', ctrlrange='-16 16', forcerange='-1 1', ctrllimited='true', forcelimited='true')
    return ET.tostring(root, encoding='unicode')


def waypoint(path, elapsed: float, step_seconds: float, cell_size: float):
    phase = min(elapsed / step_seconds, len(path) - 1)
    index = int(phase)
    following = min(index + 1, len(path) - 1)
    fraction = phase - index
    return tuple((path[index][axis] * (1 - fraction) + path[following][axis] * fraction + .5) * cell_size for axis in (0, 1))


def radio_tree(positions):
    """Minimum spanning tree using the measured Manhattan radio distance."""
    import numpy as np
    groups = list(range(len(positions)))
    edges = []
    pairs = sorted((float(np.abs(positions[i]-positions[j]).sum()), i, j)
                   for i in range(len(positions)) for j in range(i+1, len(positions)))
    for distance, i, j in pairs:
        if groups[i] != groups[j]:
            old, new = groups[j], groups[i]
            groups = [new if g == old else g for g in groups]
            edges.append((i, j, distance))
    return edges


def connectivity_velocity(positions, desired, radius, max_speed, measured_velocity=None, reserve=.02, clearance=0., prediction_seconds=.375):
    """Project velocities onto predicted radio and robot-clearance constraints."""
    import numpy as np
    velocity = desired.copy()
    edges = radio_tree(positions)
    # Low-traction direction changes need more braking time than the position gain's 125 ms.
    predicted = positions if measured_velocity is None else positions + measured_velocity * prediction_seconds
    normals = np.array([(1., 1.), (1., -1.), (-1., 1.), (-1., -1.)])
    # Reserve physical tracking slack, without changing the measured radio radius.
    safe_radius = radius * (1-reserve)
    # ponytail: bounded cyclic projection for four robots; use a constrained
    # optimizer if a larger team needs convergence guarantees.
    for _ in range(12):
        for i, j, _ in edges:
            delta = predicted[i] - predicted[j]
            for normal in normals:
                limit = 8 * (safe_radius - normal @ delta)
                excess = normal @ (velocity[i]-velocity[j]) - limit
                if excess > 0:
                    correction = normal * excess / 4
                    velocity[i] -= correction
                    velocity[j] += correction
        if clearance:
            for i in range(len(positions)):
                for j in range(i+1,len(positions)):
                    delta = positions[i]-positions[j]
                    distance = np.linalg.norm(delta)
                    if distance < 1e-9: continue
                    normal = delta/distance
                    limit = 8*(clearance-normal @ (predicted[i]-predicted[j]))
                    deficit = limit-normal @ (velocity[i]-velocity[j])
                    if deficit > 0:
                        correction = normal*deficit/2
                        velocity[i] += correction
                        velocity[j] -= correction
    speeds = np.linalg.norm(velocity, axis=1, keepdims=True)
    velocity *= np.minimum(1., max_speed / np.maximum(speeds, 1e-9))
    return velocity


def perturb_wheels(model, data, body_ids, settings, cell_size):
    """Apply bounded, reproducible model/start perturbations before execution."""
    import mujoco
    import numpy as np
    amplitude = float(settings.get('position_jitter_m', 0.))
    mass_scale = float(settings.get('mass_scale', 1.))
    friction_scale = float(settings.get('friction_scale', 1.))
    if not all(math.isfinite(x) for x in [amplitude,mass_scale,friction_scale]) or not 0 <= amplitude <= .05 or not .5 <= mass_scale <= 2 or not .5 <= friction_scale <= 2:
        raise ValueError('Perturbations require jitter 0..0.05 m and mass/friction scales 0.5..2.')
    seed = settings.get('seed', 0)
    if not isinstance(seed, int) or seed < 0:
        raise ValueError('Perturbation seed must be a nonnegative integer.')
    robots = np.isin(model.body_rootid, body_ids)
    original_mass = float(model.body_mass[robots].sum())
    model.body_mass[robots] *= mass_scale
    model.body_inertia[robots] *= mass_scale
    # Scale both sides of each contact: MuJoCo mixes surface friction values.
    model.geom_friction[:] *= friction_scale
    mujoco.mj_setConst(model, data)
    initial = data.qpos.copy()
    rng = np.random.default_rng(seed)
    floor = model.geom('floor').id
    for attempt in range(1,10001):
        data.qpos[:] = initial
        angles = rng.uniform(0,2*np.pi,len(body_ids))
        radii = amplitude * np.sqrt(rng.random(len(body_ids)))
        offsets = np.column_stack((np.cos(angles),np.sin(angles))) * radii[:,None]
        for i, body in enumerate(body_ids):
            address = model.jnt_qposadr[model.body_jntadr[body]]
            data.qpos[address:address+2] += offsets[i]
        mujoco.mj_forward(model,data)
        bottleneck = max((d for _,_,d in radio_tree(data.xpos[body_ids,:2])),default=0.)
        contact = any(floor not in (c.geom1,c.geom2) and
                      model.body_rootid[model.geom_bodyid[c.geom1]] != model.body_rootid[model.geom_bodyid[c.geom2]]
                      for c in data.contact)
        if bottleneck <= cell_size + 1e-6 and not contact:
            return dict(seed=seed, position_jitter_m=amplitude, mass_scale=mass_scale,
                        friction_scale=friction_scale, offsets_m=offsets.tolist(), attempts=attempt,
                        initial_radio_tree_distance_m=bottleneck, initial_contact=False,
                        original_robot_mass_kg=original_mass,
                        perturbed_robot_mass_kg=float(model.body_mass[robots].sum()))
    raise ValueError('No initially connected, contact-free perturbation found in 10000 samples.')


def run(args) -> dict:
    try:
        import mujoco
        import numpy as np
    except ImportError as exc:
        raise RuntimeError('Install the optional simulator: python -m pip install -e ".[mujoco]"') from exc
    if any(not math.isfinite(v) or v <= 0 for v in (args.cell_size, args.step_seconds, args.max_speed)):
        raise ValueError("cell-size, step-seconds and max-speed must be finite and positive.")
    instance = load_instance(args.config)
    payload = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    plan = {key: [tuple(cell) for cell in path] for key, path in payload.get("plan", payload).items()}
    validation = validate_plan(instance, plan)
    if not validation.valid:
        raise ValueError(f"Invalid plan: {validation.to_dict()}")
    robot_model = getattr(args, "robot_model", "soccer")
    wheels = getattr(args, 'drive', 'planar') == 'wheels'
    if wheels and (not args.physics or robot_model != 'soccer'):
        raise ValueError('Wheel drive requires --physics and --robot-model soccer.')
    model = mujoco.MjModel.from_xml_string(wheel_scene_xml(instance, args.cell_size) if wheels else scene_xml(instance, args.cell_size, args.physics, robot_model))
    preset = getattr(args,'preset','analysis')
    if preset not in ['analysis','showcase']: raise ValueError('Preset must be analysis or showcase.')
    showcase = preset == 'showcase'
    if showcase:
        from .mujoco_showcase import style_model,follow_camera,decorate_scene
        style_model(model)
    frame_width,frame_height,fps = (1920,1080,30) if showcase else (1280,720,20)
    history = []
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    body_ids = [model.body(f"robot_{i}").id for i in range(len(instance.agents))]
    robot_geoms = {model.geom(f"robot_geom_{i}").id for i in range(len(instance.agents))}
    chassis_geoms = robot_geoms.copy()
    if wheels:
        for geom_id in range(model.ngeom):
            ancestor = int(model.geom_bodyid[geom_id])
            while ancestor and ancestor not in body_ids:
                ancestor = int(model.body_parentid[ancestor])
            if ancestor in body_ids:
                robot_geoms.add(geom_id)
        wheel_joints = [[model.joint(f'r{i}_wheel{j}_speed').id for j in range(1, 4)] for i in range(len(body_ids))]
        free_dofs = [model.jnt_dofadr[model.body_jntadr[b]] for b in body_ids]
    perturbation = instance.metadata.get('simulation_perturbation')
    if perturbation is not None and (not wheels or instance.connectivity.mode != 'adjacency' or instance.connectivity.radius != 1):
        raise ValueError('Simulation perturbations require radius-1 adjacency and wheel physics.')
    applied_perturbation = perturb_wheels(model, data, body_ids, perturbation, args.cell_size) if perturbation is not None else None
    wheel_contacts = 0
    max_slip = 0.
    camera = mujoco.MjvCamera()
    cells = [cell for path in plan.values() for cell in path]
    low = np.min(cells, axis=0)
    high = np.max(cells, axis=0)
    camera.lookat[:] = [*((low + high + 1) * args.cell_size / 2), .15 * args.cell_size]
    camera.distance = max(3, float((high - low).max()) + 2) * args.cell_size * 1.6
    camera.azimuth, camera.elevation = 125, -48
    duration = (max(len(path) for path in plan.values()) - 1) * args.step_seconds + 2
    motion_end = duration - 2
    tracking_margin = float(instance.metadata.get("tracking_margin_cells", 0.0)) * args.cell_size
    if not math.isfinite(tracking_margin) or not 0 <= tracking_margin <= .1 * args.cell_size:
        raise ValueError("tracking_margin_cells must be between 0 and 0.1.")
    # Wheel contacts have a finite positioning deadband. Keep terminal slack
    # inside the 2 cm goal tolerance rather than relying on exact boundary links.
    wheel_goal_slack = min(tracking_margin, .01 * args.cell_size) if wheels else 0.
    feedback = bool(instance.metadata.get('connectivity_feedback', False))
    feedback_limit = 6 if instance.metadata.get('experimental_six_robot_feedback', False) else 4
    if feedback and (not wheels or instance.connectivity.mode != 'adjacency' or instance.connectivity.radius != 1 or len(instance.agents) > feedback_limit):
        raise ValueError('Connectivity feedback requires wheel physics, radius-1 adjacency, and at most four robots.')
    feedback_steps = 0
    radio_samples = []
    max_radio_distance = 0.
    viewer = renderer = writer = None
    contacts = disconnected = samples = 0
    disconnect_intervals = []
    disconnect_start = None
    max_error = 0.0
    final_errors = []
    goal_positions = np.array([[(a.goal[0]+.5)*args.cell_size, (a.goal[1]+.5)*args.cell_size] for a in instance.agents])
    last_outside_goal = np.zeros(len(instance.agents))
    first_goal_arrival = [0. if np.linalg.norm(data.xpos[body_ids[i], :2] - goal_positions[i]) < .02 else None for i in range(len(body_ids))]
    waypoint_samples = [{'waypoint': 0, 'sample_time_s': 0., 'connected': True}]
    next_waypoint = 1
    started = time.perf_counter()
    try:
        if not args.headless:
            import mujoco.viewer
            viewer = mujoco.viewer.launch_passive(model, data)
            viewer.cam.lookat[:] = camera.lookat
            viewer.cam.distance, viewer.cam.azimuth, viewer.cam.elevation = camera.distance, camera.azimuth, camera.elevation
        if args.video:
            import imageio.v2 as imageio
            Path(args.video).parent.mkdir(parents=True, exist_ok=True)
            renderer = mujoco.Renderer(model, height=frame_height, width=frame_width)
            if Path(args.video).suffix.lower() == ".mp4":
                writer = imageio.get_writer(args.video, fps=fps, codec="libx264", quality=8, pixelformat="yuv420p", macro_block_size=1)
            elif Path(args.video).suffix.lower() == ".gif":
                writer = imageio.get_writer(args.video, mode="I", duration=1000/fps, loop=0)
            else:
                raise ValueError("Video output must be .gif or .mp4.")
        next_frame = 0.0
        while data.time < duration:
            if viewer is not None and not viewer.is_running():
                break
            target_time = data.time if args.physics else data.time + model.opt.timestep
            targets = np.array([waypoint(plan[a.id], target_time, args.step_seconds, args.cell_size) for a in instance.agents])
            nominal_targets = targets.copy()
            if args.physics and tracking_margin:
                # Contract uniformly for communication slack; release before final goals.
                center = targets.mean(axis=0)
                extent = float(np.linalg.norm(targets - center, axis=1).max())
                envelope = min(1., data.time / .5, max(0., 1 - (data.time - motion_end) / .75))
                if wheels:
                    envelope = min(1., data.time / .5, max(wheel_goal_slack / tracking_margin, 1 - (data.time - motion_end) / .75))
                targets -= (targets - center) * min(.1, tracking_margin / max(extent, 1e-9)) * envelope
            if args.physics:
                positions = data.xpos[body_ids, :2]
                desired = 8 * (targets - positions)
                speeds = np.linalg.norm(desired, axis=1, keepdims=True)
                desired *= np.minimum(1, args.max_speed / np.maximum(speeds, 1e-9))
                if feedback:
                    measured = np.array([data.qvel[d:d+2] for d in free_dofs])
                    corrected = connectivity_velocity(positions, desired, args.cell_size, args.max_speed,
                                                      measured, .04 if data.time < motion_end else .005,
                                                      2*max(model.geom_size[g,0] for g in chassis_geoms)+.04*args.cell_size,
                                                      prediction_seconds=.375 if data.time < motion_end else .125)
                    feedback_steps += bool(np.max(np.abs(corrected-desired)) > 1e-9)
                    desired = corrected
                if wheels:
                    for i, joints in enumerate(wheel_joints):
                        rotation = data.xmat[body_ids[i]].reshape(3, 3)
                        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
                        yaw_speed = np.clip(-4 * yaw, -2, 2)
                        for j, joint in enumerate(joints):
                            tangent = np.cross(data.xaxis[joint], [0., 0., 1.])[:2]
                            offset = data.xanchor[joint, :2] - positions[i]
                            contact_velocity = desired[i] + yaw_speed * np.array([-offset[1], offset[0]])
                            data.ctrl[i*3+j] = np.clip(tangent @ contact_velocity / (WHEEL_RADIUS * 2.5 * args.cell_size), -16, 16)
                else:
                    velocity = data.qvel.reshape(-1, 2)
                    # Unit mass: 32 velocity gain with 8 position gain is critically damped.
                    data.ctrl[:] = np.clip(32 * (desired - velocity) + 2 * velocity, -20, 20).ravel()
                mujoco.mj_step(model, data)
                mujoco.mj_forward(model, data)
                if any(data.warning[w].number for w in (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC)):
                    break
            else:
                for index in range(len(instance.agents)):
                    data.mocap_pos[index, :2] = targets[index]
                mujoco.mj_forward(model, data)
                data.time += model.opt.timestep
            positions = data.xpos[body_ids, :2]
            outside = np.linalg.norm(positions - goal_positions, axis=1) >= .02
            last_outside_goal[outside] = data.time
            for i in range(len(body_ids)):
                if not outside[i] and first_goal_arrival[i] is None:
                    first_goal_arrival[i] = float(data.time)
            max_error = max(max_error, float(np.linalg.norm(positions - nominal_targets, axis=1).max()))
            linked = {0}
            edges = []
            for i in range(len(positions)):
                for j in range(i + 1, len(positions)):
                    delta = positions[i] - positions[j]
                    distance = np.linalg.norm(delta) if instance.connectivity.mode == "euclidean" else np.abs(delta).sum()
                    if distance <= instance.connectivity.radius * args.cell_size + 1e-6:
                        edges.append((i, j))
            while True:
                expanded = set(linked)
                for i in linked:
                    for j in range(len(positions)):
                        delta = positions[i] - positions[j]
                        distance = np.linalg.norm(delta) if instance.connectivity.mode == "euclidean" else np.abs(delta).sum()
                        if distance <= instance.connectivity.radius * args.cell_size + 1e-6:
                            expanded.add(j)
                if expanded == linked:
                    break
                linked = expanded
            disconnected += len(linked) != len(positions)
            if instance.connectivity.mode == 'adjacency':
                bottleneck = max((d for _, _, d in radio_tree(positions)), default=0.)
                max_radio_distance = max(max_radio_distance, bottleneck)
                if data.time >= next_frame:
                    radio_samples.append({'time_s': float(data.time), 'tree_bottleneck_m': bottleneck})
            if next_waypoint * args.step_seconds <= motion_end and data.time + model.opt.timestep / 2 >= next_waypoint * args.step_seconds:
                expected = np.array([waypoint(plan[a.id], next_waypoint * args.step_seconds, args.step_seconds, args.cell_size) for a in instance.agents])
                waypoint_samples.append({'waypoint': next_waypoint, 'sample_time_s': float(data.time),
                                         'connected': len(linked) == len(positions),
                                         'max_position_error_m': float(np.linalg.norm(positions-expected, axis=1).max())})
                next_waypoint += 1
            if len(linked) != len(positions) and disconnect_start is None:
                disconnect_start = max(0., float(data.time - model.opt.timestep))
            elif len(linked) == len(positions) and disconnect_start is not None:
                disconnect_intervals.append([disconnect_start, float(data.time - model.opt.timestep)])
                disconnect_start = None
            floor_id = model.geom('floor').id
            contacts += any((c.geom1 in robot_geoms or c.geom2 in robot_geoms) and floor_id not in (c.geom1, c.geom2)
                            and model.body_rootid[model.geom_bodyid[c.geom1]] != model.body_rootid[model.geom_bodyid[c.geom2]] for c in data.contact)
            if wheels:
                wheel_contacts += any(floor_id in (c.geom1, c.geom2) and (c.geom1 in robot_geoms or c.geom2 in robot_geoms) for c in data.contact)
                for i, joints in enumerate(wheel_joints):
                    dof = model.jnt_dofadr[model.body_jntadr[body_ids[i]]]
                    velocity = data.qvel[dof:dof+3]
                    angular = data.xmat[body_ids[i]].reshape(3, 3) @ data.qvel[dof+3:dof+6]
                    for joint in joints:
                        tangent = np.cross(data.xaxis[joint], [0., 0., 1.])
                        offset = data.xanchor[joint] - data.xpos[body_ids[i]]
                        slip = WHEEL_RADIUS * 2.5 * args.cell_size * data.qvel[model.jnt_dofadr[joint]] - tangent @ (velocity + np.cross(angular, offset))
                        max_slip = max(max_slip, abs(float(slip)))
            samples += 1
            if data.time >= next_frame:
                if showcase:
                    follow_camera(camera,positions,data.time,args.cell_size)
                    history.append(positions.copy())
                    history = history[-25:]
                if viewer is not None:
                    with viewer.lock():
                        viewer.user_scn.ngeom = 0
                        if showcase:
                            viewer.cam.lookat[:] = camera.lookat
                            viewer.cam.distance,viewer.cam.elevation = camera.distance,camera.elevation
                            decorate_scene(viewer.user_scn,positions,goal_positions,history,COLORS,args.cell_size)
                        annotate_scene(viewer.user_scn, positions, edges, len(linked) == len(positions), args.cell_size,showcase)
                    viewer.sync()
                if renderer is not None:
                    renderer.update_scene(data, camera=camera)
                    if showcase: decorate_scene(renderer.scene,positions,goal_positions,history,COLORS,args.cell_size)
                    annotate_scene(renderer.scene, positions, edges, len(linked) == len(positions), args.cell_size,showcase)
                    writer.append_data(label_frame(renderer.render(), renderer.scene, positions, instance.agents,
                                                   data.time, len(linked) == len(positions), args.cell_size,showcase))
                next_frame += 1/fps
            if viewer is not None:
                time.sleep(max(0, started + data.time - time.perf_counter()))
        final_errors = [float(np.linalg.norm(data.xpos[body_ids[i], :2] - np.array(waypoint(plan[a.id], duration, args.step_seconds, args.cell_size)))) for i, a in enumerate(instance.agents)]
    finally:
        for resource in (writer, renderer, viewer):
            if resource is not None:
                resource.close()
    report = {"mode": "planar_physics" if args.physics else "kinematic_replay", "instance": instance.name,
              "completed": bool(data.time >= duration), "simulation_seconds": float(data.time),
              "cell_size_m": args.cell_size, "step_seconds": args.step_seconds, "max_speed_m_s": args.max_speed,
              "max_tracking_error_m": max_error, "final_goal_errors_m": final_errors,
              "contact_steps": int(contacts), "disconnected_seconds": disconnected * model.opt.timestep, "samples": samples,
              "mujoco_version": mujoco.__version__}
    report['numerical_warnings'] = int(sum(data.warning[w].number for w in (mujoco.mjtWarning.mjWARN_BADQPOS, mujoco.mjtWarning.mjWARN_BADQVEL, mujoco.mjtWarning.mjWARN_BADQACC)))
    report["robot_visual"] = robot_model
    report['render_preset'] = preset
    if disconnect_start is not None:
        disconnect_intervals.append([disconnect_start, float(data.time)])
    report['disconnected_intervals_s'] = disconnect_intervals
    arrivals = [float(last_outside_goal[i] + model.opt.timestep) if final_errors[i] < .02 and last_outside_goal[i] else (0. if final_errors[i] < .02 else None) for i in range(len(final_errors))]
    report.update(goal_tolerance_m=.02, goal_arrival_times_s=arrivals, waypoint_samples=waypoint_samples,
                  first_goal_arrival_times_s=first_goal_arrival,
                  waypoint_disconnected_count=sum(not s['connected'] for s in waypoint_samples))
    report["tracking_margin_m"] = tracking_margin
    report['simulation_perturbation'] = applied_perturbation
    report.update(connectivity_feedback=feedback, connectivity_feedback_steps=feedback_steps,
                  max_radio_tree_distance_m=max_radio_distance, radio_samples=radio_samples)
    report["collision_radii_m"] = [float(model.geom_size[g, 0]) for g in sorted(chassis_geoms)]
    if wheels:
        report.update(mode='wheel_physics', wheel_ground_contact_steps=wheel_contacts, max_wheel_slip_m_s=max_slip,
                      wheel_speed_limit_rad_s=16, wheel_torque_limit_nm=1, wheel_goal_slack_m=wheel_goal_slack)
    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
