"""Seat the hidden outer back edge on the curved casing, clear of the insert."""
import json
import numpy as np
from asset_io import HERE, ps, xyz
from visuals import DRONE_SOCKET_INSET

def fit_socket(vertices, casing_triangles):
    rail=json.loads((HERE/'vanilla/Astro/Content/Items/BackpackRail.json').read_text())
    exports={e['ObjectName']:e for e in rail['Exports']}
    slot=ps(exports['Creative Drone Slot_GEN_VARIABLE'])
    body=ps(exports['backpack_mk2_GEN_VARIABLE'])
    location=np.array([float(xyz(slot['RelativeLocation'])[k])-float(xyz(body['RelativeLocation'])[k]) for k in 'XYZ'])
    location[1]+=DRONE_SOCKET_INSET-.75
    angles=slot['RelativeRotation']['Value'][0]['Value']
    pitch,yaw,roll=np.radians([angles[k] for k in ['Pitch','Yaw','Roll']])
    sp,sy,sr=np.sin([pitch,yaw,roll]);cp,cy,cr=np.cos([pitch,yaw,roll])
    rotation=np.array([[cp*cy,sr*sp*cy-cr*sy,-(cr*sp*cy+sr*sy)],
                       [cp*sy,sr*sp*sy+cr*cy,cy*sr-cr*sp*sy],
                       [sp,-sr*cp,cr*cp]])
    triangles=casing_triangles.astype(float)
    matrices=np.stack([triangles[:,:,0],triangles[:,:,2],np.ones(triangles.shape[:2])],axis=1)
    valid=abs(np.linalg.det(matrices))>1e-7
    matrices=matrices[valid];triangles=triangles[valid]
    def clearance(point):
        weights=np.linalg.solve(matrices,np.broadcast_to([point[0],point[2],1.],(len(matrices),3))[:,:,None])[:,:,0]
        ys=(weights*triangles[:,:,1]).sum(1)
        hits=ys[(weights.min(1)>-1e-5)&(ys<0)]
        assert len(hits),point
        return float(hits.min()-point[1])
    result=vertices.astype(float).copy()
    rear=abs(vertices[:,2]-vertices[:,2].min())<.0001
    # This is the outer back edge only. All front rim and inner insert vertices
    # retain their exact source positions; the drone's attachment stays native.
    before=result@rotation.T*.25+location
    for index in np.flatnonzero(rear):
        delta=clearance(before[index])-.02
        result[index,2]+=delta/(.25*rotation[1,2])
    after=result@rotation.T*.25+location
    distances=[clearance(p) for p in after[rear]]
    inner=np.linalg.norm(vertices[:,:2],axis=1)<15
    inside=[clearance(p) for p in after[inner]]
    assert min(inside)>.2, 'The casing clips the socket insert'
    assert np.array_equal(result[~rear],vertices[~rear])
    assert max(abs(np.asarray(distances)-.02))<1e-5
    report=dict(inset=DRONE_SOCKET_INSET,rear_rim_vertices=int(rear.sum()),
                rear_rim_clearance_range=[min(distances),max(distances)],
                inner_clearance_range=[min(inside),max(inside)],
                maximum_hidden_edge_adjustment=float(abs(result[rear,2]-vertices[rear,2]).max()),
                front_rim_and_inner_geometry_unchanged=True,actual_drone_slot_unchanged=True)
    return result,report
