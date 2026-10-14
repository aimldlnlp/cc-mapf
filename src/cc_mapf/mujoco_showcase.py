"""Presentation-only styling and smooth camera motion for MuJoCo videos."""
import math


def style_model(model):
    import mujoco
    model.vis.global_.offwidth, model.vis.global_.offheight = 1920,1080
    model.vis.quality.offsamples = 4
    model.vis.quality.shadowsize = 4096
    model.vis.headlight.ambient[:] = .45
    model.vis.headlight.diffuse[:] = .7
    model.vis.headlight.specular[:] = .15
    model.light_ambient[:] = .2
    model.light_diffuse[:] = .85
    model.light_specular[:] = .25
    for i in range(model.ngeom):
        name = mujoco.mj_id2name(model,mujoco.mjtObj.mjOBJ_GEOM,i) or ''
        if name == 'floor': model.geom_rgba[i] = [.48,.53,.57,1.]
        elif name.startswith('wall_'): model.geom_rgba[i] = [.28,.34,.39,1.]
        elif name.startswith('goal_'): model.geom_rgba[i,3] = 0.
        elif model.geom_contype[i] == 0 and model.geom_type[i] == mujoco.mjtGeom.mjGEOM_BOX:
            model.geom_rgba[i] = [.58,.62,.65,.25]


def follow_camera(camera,positions,elapsed,cell_size):
    import numpy as np
    # A brief wide view eases into a close group view, then follows smoothly.
    blend = min(1.,max(0.,(elapsed-.75)/2.25))
    blend = blend*blend*(3-2*blend)
    center = positions.mean(axis=0)
    target = np.array([*center,.18*cell_size])
    camera.lookat[:] += (target-camera.lookat)*(.10*blend)
    span = float(np.ptp(positions,axis=0).max())
    distance = max(4.8*cell_size,(span+1.2*cell_size)*1.65)
    camera.distance += (distance-camera.distance)*(.10*blend)
    camera.elevation += (-62-camera.elevation)*.08


def decorate_scene(scene,positions,goals,history,colors,cell_size):
    import mujoco
    import numpy as np
    def segment(a,b,color,radius):
        if scene.ngeom >= scene.maxgeom: return
        geom = scene.geoms[scene.ngeom]
        mujoco.mjv_initGeom(geom,mujoco.mjtGeom.mjGEOM_CAPSULE,np.zeros(3),np.zeros(3),
                           np.eye(3).ravel(),np.array(color,dtype=np.float32))
        mujoco.mjv_connector(geom,mujoco.mjtGeom.mjGEOM_CAPSULE,radius,a,b)
        scene.ngeom += 1
    for i,goal in enumerate(goals):
        color = [*colors[i%len(colors)],.85]
        for k in range(32):
            points = [[goal[0]+.29*cell_size*math.cos(t),goal[1]+.29*cell_size*math.sin(t),.017*cell_size]
                      for t in [k*math.tau/32,(k+1)*math.tau/32]]
            segment(*points,color,.012*cell_size)
    for k,(before,after) in enumerate(zip(history,history[1:])):
        alpha = .08+.28*(k+1)/len(history)
        for i,(a,b) in enumerate(zip(before,after)):
            if np.linalg.norm(a-b)<1e-5: continue
            segment([*a,.018*cell_size],[*b,.018*cell_size],
                    [*colors[i%len(colors)],alpha],.008*cell_size)
