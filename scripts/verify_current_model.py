"""Check the approved model revision's fit, straightness and shared shading."""
import hashlib,json
from collections import Counter
import numpy as np
from asset_io import HERE,gltf
from model import MODEL
from settings import MODEL_STYLE

def topology(t):
    v,f=np.unique(np.round(t.reshape(-1,3),7),axis=0,return_inverse=True)
    e=Counter(tuple(sorted([int(a),int(b)])) for face in f.reshape(-1,3) for a,b in zip(face,np.roll(face,-1)))
    return v,e

def check_current_model(model,info):
    reference=json.loads((HERE/'model-revision-reference.json').read_text());ref=reference['models'][MODEL_STYLE]
    assert info['packaged_model_revision']==reference['version']
    assert hashlib.sha256(MODEL.read_bytes()).hexdigest()==ref['glb_sha256'],'Model changed since the reviewed snapshot'
    parts={p['name']:p for p in model['parts']};report={}
    def triangles(name):
        p=parts[name];return p['v'][p['f']]/100
    for name,expected in ref['parts'].items():
        p=parts[name];v=p['v']/100
        assert len(p['f'])==expected['triangles'] and np.allclose([v.min(0),v.max(0)],expected['bounds'],atol=2e-7,rtol=0),(name,'Approved dimensions changed')
    if info.get('combined_battery_housings'):
        from verify_joined_housings import check_joined_housings
        support_report=check_joined_housings(parts,info)
        target=np.asarray(info['battery_support_edge_revision']['Bottom']['casing_vertex_right'])
    else:
        support_report={}
        for end in ['Top','Bottom']:
            case=parts['Battery'+end+'Casing'];cv=case['v']/100;cz=(cv[:,2].min()+cv[:,2].max())/2;cy=cv[:,1].min() if end=='Top' else cv[:,1].max();ring=np.unique(cv[abs(cv[:,1]-cy)<1e-7][:,[0,2]],axis=0);ring=ring[np.linalg.norm(ring-[0,cz],axis=1)>.045];rear=ring[(ring[:,0]>0)&(ring[:,1]<cz-1e-6)];target=rear[rear[:,0].argmax()];support=parts['Battery'+end+'Support'];sv=support['v']/100
            assert np.allclose([sv[:,0].min(),sv[:,0].max()],[-target[0],target[0]],atol=1e-8,rtol=0)
            assert abs(sv[:,2].max()-target[1])<1e-8
            assert abs(np.ptp(sv[:,0])-2*np.ptp(cv[:,0])/2*np.cos(np.pi/8))<2e-7
            ct=triangles(case['name']);cn=case['normal'][case['f']];st=triangles(support['name']);sn=support['normal'][support['f']];walls=np.ptp(ct[:,:,1],axis=1)>1e-7
            for side in [-1,1]:
                x=side*target[0];shared=np.r_[side*target[0],0.,target[1]-cz];shared/=np.linalg.norm(shared);shared+=np.array([side,0,0]);shared/=np.linalg.norm(shared)
                seam=walls[:,None]&(abs(ct[:,:,0]-x)<1e-7)&(abs(ct[:,:,2]-target[1])<1e-7);assert seam.sum()>=4
                assert np.allclose(cn[seam],shared,atol=2e-7)
                sw=np.all(abs(st[:,:,0]-x)<1e-7,axis=1);seam=sw[:,None]&(abs(st[:,:,2]-target[1])<1e-7);assert np.allclose(sn[seam],shared,atol=2e-7)
            support_report[end]=dict(width=float(np.ptp(sv[:,0])),front_depth=float(sv[:,2].max()),matched_casing_vertex=target.tolist())
        assert support_report['Top']==support_report['Bottom']
    backing=parts['BatteryBacking']['v']/100
    assert np.allclose([backing[:,0].min(),backing[:,0].max()],[-target[0],target[0]],atol=1e-8,rtol=0)
    report['supports']=support_report
    f=parts['SmoothFrontBase'];v=f['v']/100;t=triangles(f['name']);bounds=np.array([v.min(0),v.max(0)]);top=info['combined_battery_housings']['BatteryTopCasing']['support_end_y'] if info.get('combined_battery_housings') else parts['BatteryTopSupport']['v'][:,1].max()/100;bottom=info['combined_battery_housings']['BatteryBottomCasing']['support_end_y'] if info.get('combined_battery_housings') else parts['BatteryBottomSupport']['v'][:,1].min()/100;gaps=np.array([bounds[0,1]-bottom,top-bounds[1,1]])
    assert np.allclose(gaps,.0002,atol=8e-8,rtol=0)
    assert np.ptp(v[:,2])<1e-12 and np.allclose(f['normal'],[0,0,1],atol=1e-7)
    vertices,e=topology(t);long=0
    for (i,j),count in e.items():
        q=abs(vertices[j]-vertices[i])
        if count!=1 or np.linalg.norm(q)<.5:continue
        axis=q.argmax();assert np.linalg.norm(np.delete(q,axis))<2e-7;long+=1
    assert long==4
    r=info['front_alignment_revision']['radius_x'];centre=(bounds[1,:2]+bounds[0,:2])/2;corner=(bounds[1,:2]-bounds[0,:2])/2-r;rho=np.linalg.norm(vertices[:,:2]-centre-np.sign(vertices[:,:2]-centre)*corner,axis=1);assert abs(rho-r).max()<8e-8
    a,e=topology(np.concatenate([t,triangles('SmoothFrontBaseSideEdge')]))
    assert set(e.values())=={2} and len(a)-len(e)+len(t)+len(triangles('SmoothFrontBaseSideEdge'))==2
    report['panel']=dict(end_gaps=gaps.tolist(),equal_circular_corners=True,straight_edges=True,closed=True)
    collars={}
    for name,detail in info['battery_tube_collar_revision'].items():
        p=parts[name];recess=parts[name.replace('Eyelet','Recess')];end='Top' if 'Top' in name else 'Bottom';side=-1 if name.endswith('_-1') else 1
        assert p['mat']==parts['BinderEyelet_1_0']['mat'] and recess['mat']==parts['BinderRecess_1_0']['mat']
        assert len(p['f'])==96 and len(recess['f'])<=16 and detail['visible_rim_width']==.0022 and detail['maximum_surface_protrusion']==.0048
        axis=np.asarray(detail['tube_axis']);origin=np.asarray(detail['tube_axis_origin']);tri=triangles(name);samples=np.concatenate([tri[-24:].reshape(-1,3),tri[-24:].mean(1)]);clearance=np.linalg.norm((samples-origin)-((samples-origin)@axis)[:,None]*axis,axis=1)-detail['tube_radius'];assert clearance.min()>.0001
        cv=parts['Battery'+end+'Casing']['v']/100;sv=np.asarray(info['combined_battery_housings']['Battery'+end+'Casing']['support_region_bounds']) if info.get('combined_battery_housings') else parts['Battery'+end+'Support']['v']/100;cy=cv[:,1].min() if end=='Top' else cv[:,1].max();cz=info['combined_battery_housings']['Battery'+end+'Casing']['cylinder_centre_z'] if info.get('combined_battery_housings') else (cv[:,2].min()+cv[:,2].max())/2;ring=np.unique(cv[abs(cv[:,1]-cy)<1e-7][:,[0,2]],axis=0);ring=ring[np.linalg.norm(ring-[0,cz],axis=1)>.045];ring=ring[np.argsort(np.arctan2(ring[:,1]-cz,ring[:,0]))];floor=triangles(recess['name']);points=np.concatenate([floor.reshape(-1,3),floor.mean(1),(floor[:,0]+floor[:,1])/2,(floor[:,1]+floor[:,2])/2,(floor[:,2]+floor[:,0])/2]);offsets=[]
        for q in points:
            hits=[]
            for a,b in zip(ring,np.roll(ring,-1,axis=0)):
                if abs(b[1]-a[1])<1e-12:continue
                w=(q[2]-a[1])/(b[1]-a[1])
                if -1e-6<=w<=1+1e-6:hits.append(float(a[0]+w*(b[0]-a[0])))
            assert hits
            x=max(hits) if side==1 else min(hits)
            if sv[:,2].min()-1e-7<=q[2]<=sv[:,2].max()+1e-7:x=max(x,sv[:,0].max()) if side==1 else min(x,sv[:,0].min())
            offsets.append(side*(q[0]-x))
        assert np.allclose(offsets,.0004,atol=7e-8,rtol=0),(name,min(offsets),max(offsets))
        collars[name]=dict(eyelet_triangles=len(p['f']),recess_triangles=len(recess['f']),minimum_clearance=float(clearance.min()),floor_offset_range=[min(offsets),max(offsets)])
    report['collars']=collars
    if MODEL_STYLE=='luxe':
        _,a,ids=gltf(HERE/'exports/Models/backpack_mk2/backpack_mk2.gltf');v=a['POSITION'].astype(float);v=np.column_stack([v[:,2],v[:,1]+.51,-(v[:,0]-.0146842727662)]);n=a['NORMAL'].astype(float);n=np.column_stack([n[:,2],n[:,1],-n[:,0]]);t=v[ids[model['keep']]];norm=n[ids[model['keep']]];mat=np.stack([t[:,:,0],t[:,:,1],np.ones(t.shape[:2])],axis=1);valid=abs(np.linalg.det(mat))>1e-12;t=t[valid];norm=norm[valid];inverse=np.linalg.inv(mat[valid]);settings={}
        for name in ['LuxeElbowStar_SettingShell_-1','LuxeElbowMoon_SettingShell_1']:
            p=parts[name];tri=triangles(name);ns=p['normal'][p['f']];centre=(tri.reshape(-1,3)[:,:2].min(0)+tri.reshape(-1,3)[:,:2].max(0))/2;radius=np.linalg.norm(tri[:,:,:2]-centre,axis=2);wall=np.all(abs(radius-radius.max())<1e-6,axis=1);assert wall.sum()==16;base=tri[:,:,2].min();count=0
            for i in np.flatnonzero(wall):
                for j,q in enumerate(tri[i]):
                    if abs(q[2]-base)<1e-7:
                        w=np.einsum('nij,j->ni',inverse,np.r_[q[:2],1]);hit=w.min(1)>-2e-6;assert hit.any();k=np.where(hit,(w*t[:,:,2]).sum(1),-np.inf).argmax();expected=w[k]@norm[k];expected/=np.linalg.norm(expected);count+=1
                    else:
                        radial=q[:2]-centre;radial/=np.linalg.norm(radial);expected=np.r_[radial,0.]
                    assert np.allclose(ns[i,j],expected,atol=2e-6),(name,'Setting body join lost native shading')
            settings[name]=dict(native_base_corners=count,smooth_outer_wall_triangles=int(wall.sum()))
        report['settings']=settings
    return report
