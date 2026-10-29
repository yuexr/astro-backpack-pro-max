"""Build tangent frames from UV directions, retaining stable fallback frames."""
import numpy as np


def surface_tangents(vertices, faces, uv, normals):
    vertices=np.asarray(vertices,dtype=float);uv=np.asarray(uv,dtype=float)
    basis=np.zeros_like(normals)
    basis[np.arange(len(normals)),np.argmin(abs(normals),axis=1)]=1
    fallback=np.cross(basis,normals)
    fallback/=np.linalg.norm(fallback,axis=1)[:,None]
    du=np.zeros_like(vertices);dv=np.zeros_like(vertices)
    p=vertices[faces];u=uv[faces]
    e1=p[:,1]-p[:,0];e2=p[:,2]-p[:,0]
    a=u[:,1]-u[:,0];b=u[:,2]-u[:,0]
    det=a[:,0]*b[:,1]-a[:,1]*b[:,0]
    area=np.linalg.norm(np.cross(e1,e2),axis=1)
    valid=(abs(det)>1e-18)&(area>1e-14)
    selected=faces[valid];weight=area[valid]/det[valid]
    first=(e1[valid]*b[valid,1,None]-e2[valid]*a[valid,1,None])*weight[:,None]
    second=(-e1[valid]*b[valid,0,None]+e2[valid]*a[valid,0,None])*weight[:,None]
    for k in range(3):
        np.add.at(du,selected[:,k],first)
        np.add.at(dv,selected[:,k],second)
    tangent=du-normals*(du*normals).sum(1)[:,None]
    lengths=np.linalg.norm(tangent,axis=1);mapped=lengths>1e-12
    tangent[mapped]/=lengths[mapped,None];tangent[~mapped]=fallback[~mapped]
    handedness=np.ones(len(vertices))
    handedness[mapped]=np.where((np.cross(normals[mapped],tangent[mapped])*dv[mapped]).sum(1)<0,-1,1)
    return tangent,handedness,mapped
