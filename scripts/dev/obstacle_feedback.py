"""Experimental joint radio, robot, obstacle and speed projection."""
import numpy as np
from evaluate_future_tree import original_tree


def box_distance(position, center, half):
    closest=np.clip(position,center-half,center+half)
    delta=position-closest
    distance=float(np.linalg.norm(delta))
    if distance>1e-12: return distance,delta/distance,closest
    gaps=half-np.abs(position-center)
    axis=int(np.argmin(gaps))
    normal=np.zeros(2);normal[axis]=1. if position[axis]>=center[axis] else -1.
    closest=position.copy();closest[axis]=center[axis]+normal[axis]*half[axis]
    return -float(gaps[axis]),normal,closest


def project(positions,desired,radius,max_speed,measured,reserve,clearance,horizon,
            boxes,body_radius,obstacle_margin=.02,max_iterations=64):
    predicted=positions+measured*horizon
    edges=original_tree(predicted)
    if any(np.abs(positions[i]-positions[j]).sum()>radius+1e-6 for i,j,_ in edges):
        edges=original_tree(positions)
    rows=[];limits=[];kinds=[]
    def constraint(i,j,normal,limit,kind):
        row=np.zeros_like(positions);row[i]=normal
        if j is not None: row[j]=-normal
        rows.append(row.ravel());limits.append(limit);kinds.append(kind)
    for i,j,_ in edges:
        for normal in np.array([(1.,1.),(1.,-1.),(-1.,1.),(-1.,-1.)]):
            constraint(i,j,normal,8*(radius*(1-reserve)-normal@(predicted[i]-predicted[j])),'radio')
    for i in range(len(positions)):
        for j in range(i+1,len(positions)):
            delta=positions[i]-positions[j];distance=np.linalg.norm(delta)
            if distance>1e-12:
                normal=delta/distance
                constraint(i,j,-normal,8*(normal@(predicted[i]-predicted[j])-clearance),'pair')
        for center,half in boxes:
            distance,normal,closest=box_distance(positions[i],center,half)
            if distance>body_radius+obstacle_margin+max_speed*horizon+.1: continue
            constraint(i,None,-normal,8*(normal@(predicted[i]-closest)-body_radius-obstacle_margin),'obstacle')
    matrix=np.array(rows);bounds=np.array(limits);norms=np.sum(matrix*matrix,axis=1)
    velocity=desired.copy().ravel()
    # ponytail: bounded cyclic feasibility projection, not a nearest-command
    # optimizer or an infeasibility certificate; report unresolved residuals.
    for iteration in range(max_iterations):
        for row,bound,norm in zip(matrix,bounds,norms):
            excess=row@velocity-bound
            if excess>0: velocity-=row*(excess/norm)
        shaped=velocity.reshape(-1,2)
        speed=np.linalg.norm(shaped,axis=1,keepdims=True)
        shaped*=np.minimum(1.,max_speed/np.maximum(speed,1e-12))
        excess=np.maximum(0.,matrix@velocity-bounds)/8
        if np.max(excess,initial=0.)<=1e-6: break
    audit={kind:float(np.max(excess[np.array(kinds)==kind],initial=0.)) for kind in ['radio','pair','obstacle']}
    audit.update(iterations=iteration+1,converged=max(audit.values())<=1e-6)
    return velocity.reshape(-1,2),audit
