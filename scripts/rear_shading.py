"""Apply declared native flank normals with isolated sharp-boundary vertices."""
import numpy as np
from surface_tangents import surface_tangents


def body_buffers(raw,indices,keep,uv,boundary,patch,offsets,count):
    positions=np.frombuffer(raw,'<f4',count=count*3,offset=offsets['position']).reshape(count,3).copy()
    skin=np.frombuffer(raw,'u1',count=count*8,offset=offsets['skin']).reshape(count,8).copy()
    packed=np.frombuffer(raw,'i1',count=count*8,offset=offsets['tangent']).reshape(count,8).copy()
    sources=np.arange(count);normal_changed=np.zeros(count,dtype=bool);faces=indices.copy();uv=uv.copy();boundary=boundary.copy()
    if patch:
        used=set(faces[keep].reshape(-1));targets=set()
        for copy in patch['vertex_copies']:
            source,target=copy['source'],copy['target']
            assert target not in used and target not in targets and 0<=source<count and 0<=target<count
            targets.add(target);sources[target]=source;positions[target]=positions[source];skin[target]=skin[source];packed[target]=packed[source];uv[target]=uv[source];boundary[target]=boundary[source]
        chosen=np.asarray(patch['native_triangle_ids'],dtype=int);replacement=np.asarray(patch['native_triangle_indices'],dtype=int)
        assert keep[chosen].all() and np.array_equal(sources[replacement],faces[chosen])
        faces[chosen]=replacement
        vertex=np.asarray(patch['normal_vertex_ids'],dtype=int);n=np.asarray(patch['normals'],dtype=float)
        assert np.allclose(np.linalg.norm(n,axis=1),1,atol=1e-6)
        native=np.column_stack([-n[:,2],n[:,0],n[:,1]])
        packed[vertex,4:7]=np.round(native*127).astype('i1');normal_changed[vertex]=True
    if boundary.any() or normal_changed.any():
        n=packed[:,4:7].astype(float);n/=np.linalg.norm(n,axis=1)[:,None]
        tangent,sign,mapped=surface_tangents(positions,faces[keep],uv,n)
        update=(boundary|normal_changed)&mapped
        packed[update,:3]=np.round(tangent[update]*127).astype('i1');packed[update,7]=(sign[update]*127).astype('i1')
    for field,array in [('position',positions),('skin',skin),('tangent',packed),('index',faces.astype('<u2'))]:
        start=offsets[field];raw[start:start+array.nbytes]=array.tobytes()
    return dict(positions=positions,indices=faces,uv=uv,rear_uv_boundary=boundary,tangent_buffer=packed,vertex_sources=sources,normal_changed=normal_changed)
