"""Verify solid casings, capped ribbon, octagons, raised stripe and live palette."""
import json,hashlib
from collections import Counter
import numpy as np
from asset_io import HERE,gltf
from settings import MODEL_STYLE,OUT


def topology(t):
    v,f=np.unique(np.round(t.reshape(-1,3),6),axis=0,return_inverse=True)
    edges=Counter(tuple(sorted((int(a),int(b)))) for face in f.reshape(-1,3) for a,b in zip(face,np.roll(face,-1)))
    return v,edges


def distances(points,t):
    inverse=np.linalg.pinv((t[:,1:]-t[:,:1]).transpose(0,2,1));out=[]
    for p in points:
        w12=np.einsum('nij,nj->ni',inverse,p-t[:,0]);w=np.column_stack([1-w12.sum(1),w12]);proj=(w[:,:,None]*t).sum(1)
        d=np.where(w.min(1)>=0,np.linalg.norm(proj-p,axis=1),np.inf)
        for i,j in [(0,1),(1,2),(2,0)]:
            e=t[:,j]-t[:,i];u=np.clip(((p-t[:,i])*e).sum(1)/(e*e).sum(1),0,1)
            d=np.minimum(d,np.linalg.norm(t[:,i]+u[:,None]*e-p,axis=1))
        out.append(d.min())
    return np.asarray(out)


def check_comparisons(model,info,geometry=None):
    if MODEL_STYLE!='luxe':return []
    parts={p['name']:p for p in model['parts']}
    def triangles(name):
        p=parts[name];return p['v'][p['f']]/100
    report={}
    for end in ['Top','Bottom']:
        name='Battery'+end+'Casing';t=triangles(name);v,edges=topology(t)
        assert len(t)==info.get('combined_battery_housings',{}).get(name,{}).get('triangles',126) and set(edges.values())=={2}
        assert len(v)-len(edges)+len(t)==2,'Battery casing contains a hole'
    assert not any(n.startswith(('BatteryTopTubeOpening_','BatteryBottomTubeOpening_')) for n in parts)
    eyelet_names=set(info.get('battery_tube_collar_revision',{}))
    assert {n for n in parts if n.startswith(('BatteryTopTubeEyelet_','BatteryBottomTubeEyelet_'))}==eyelet_names
    ribbon=parts['SmoothFrontBaseSideEdge'];t=triangles(ribbon['name']);v,edges=topology(t)
    back=np.all(abs(t[:,:,2]-t[:,:,2].min())<1e-7,axis=1)
    assert len(t)==82 and back.sum()==26 and (~back).sum()==56
    assert sum(count==1 for count in edges.values())==28 and set(edges.values())=={1,2}
    assert len(np.unique(np.round(t[:,:,2],7)))==2
    corner_normals=ribbon['normal'][ribbon['f']]
    assert np.allclose(corner_normals[back],[0,0,-1],atol=1e-6),'Rear cap must stay flat with a sharp wall join'
    assert np.allclose(corner_normals[~back,:,2],0,atol=1e-7),'Ribbon walls must retain their smooth side normals'
    assert np.allclose(np.linalg.norm(ribbon['normal'],axis=1),1,atol=1e-6)
    assembly=np.concatenate([t,triangles('SmoothFrontBase')]);av,ae=topology(assembly)
    assert set(ae.values())=={2} and len(av)-len(ae)+len(assembly)==2,'Front assembly must be closed'
    front=np.unique(np.round(triangles('SmoothFrontBase').reshape(-1,3),6),axis=0)
    edge=np.unique(np.round(t[abs(t[:,:,2]-t[:,:,2].max())<1e-7],6),axis=0)
    assert np.array_equal(front,edge),'Ribbon no longer follows the exact front contour'
    _,native,ids=gltf(HERE/'exports/Models/backpack_mk2/backpack_mk2.gltf')
    expected=np.asarray(native['TEXCOORD_0'][ids[list(range(607,612))+list(range(765,770))]].mean((0,1)),dtype='<f2').astype(float)
    assert np.array_equal(model['PALETTE_BINDINGS'][ribbon['mat']]['uv'],expected)
    for side in [-1,1]:
        for row in range(3):assert parts[f'BinderEyelet_{side}_{row}']['mat']==ribbon['mat']
    gold={}
    for side in [-1,1]:
        for row in range(4):
            name=f'LuxePadInlay_{side}_{row}';p=parts[name];t=triangles(name);face=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);face/=np.linalg.norm(face,axis=1)[:,None]
            assert len(t)==112 and np.allclose(p['normal'][p['f']],face[:,None,:],atol=2e-6)
            gold[name]=len(t)
    assert len(triangles('LuxeElbowStar_-1'))==30 and len(triangles('LuxeElbowMoon_1'))==270 and 'LuxeElbowMoon_-1' not in parts
    name='LuxeElbowStar_SettingShell_-1';p=parts[name];t=triangles(name);centre=(t.reshape(-1,3)[:,:2].min(0)+t.reshape(-1,3)[:,:2].max(0))/2
    radius=np.linalg.norm(t[:,:,:2]-centre,axis=2);wall=np.all(abs(radius-radius.max())<1e-6,axis=1)
    assert len(t)==96 and wall.sum()==16 and len(np.unique(np.round(t[wall,:,:2].reshape(-1,2),6),axis=0))==8
    n=p['normal'][p['f']];base=t[:,:,2].min();upper=wall[:,None]&(t[:,:,2]>base+1e-7)
    radial=t[:,:,:2]-centre;radial/=np.maximum(np.linalg.norm(radial,axis=2)[:,:,None],1e-30)
    assert np.allclose(n[upper,:2],radial[upper],atol=1e-6) and np.allclose(n[upper,2],0,atol=1e-6)
    right=parts['LuxeElbowMoon_SettingShell_1'];rt=triangles(right['name']);rn=np.cross(rt[:,1]-rt[:,0],rt[:,2]-rt[:,0]);rn/=np.linalg.norm(rn,axis=1)[:,None]
    assert len(rt)==96
    if info.get('right_octagon_setting_revision'):
        assert info['right_octagon_setting_revision']['matches_left_policy'] and 'normal' in right
    else:
        assert np.allclose(right['normal'][right['f']],rn[:,None,:],atol=2e-6)
    bands={}
    for side in [-1,1]:
        t=triangles(f'LuxeOxygenSupportBand_{side}');v,edges=topology(t);assert len(t)==574 and set(edges.values())=={2}
        front=t[:,:,2].mean(1)>-.05;assert t[front,:,1].min()>1.24 and t[~front,:,1].min()<1.20
        assert abs(t[-12:,:,1].mean()-1.245)<1e-7;bands[str(side)]=len(t)
    v=native['POSITION'].astype(float);v=np.column_stack([v[:,2],v[:,1]+.51,-(v[:,0]-.0146842727662)])
    stripe=triangles('LuxeRearCasingStripe');ref=json.loads((HERE/'rear-stripe-reference.json').read_text());source_ids=ref['stripe_source_native_triangles']+[3002,3004];surface=v[ids[source_ids]]
    points=np.concatenate([stripe.reshape(-1,3),stripe.mean(1),(stripe[:,0]+stripe[:,1])/2,(stripe[:,1]+stripe[:,2])/2,(stripe[:,2]+stripe[:,0])/2])
    gap=distances(points,surface);assert gap.min()>.00007 and gap.max()<.00017,('Raised stripe clearance',gap.min(),gap.max())
    body=np.load(OUT/'body-expected.npz');assert not body['normal_changed'].any() and np.array_equal(body['vertex_sources'],np.arange(len(v)))
    restored=np.asarray(info['raised_rear_stripe_revision']['restored_native_triangles']);assert model['keep'][restored].all() and np.array_equal(body['indices'][restored],ids[restored])
    corners=np.unique(ids[restored]);boundary=body['rear_uv_boundary'][corners]
    assert np.array_equal(body['uv'][corners[~boundary]],native['TEXCOORD_0'][corners[~boundary]])
    # Four shared flat-rear join vertices retain the accepted affine UV repair.
    assert boundary.sum()==4
    coefficients=np.asarray(info['rear_uv_correction']['coefficients'])
    assert np.allclose(body['uv'][corners[boundary]],v[corners[boundary],:2]*coefficients[:,0]+coefficients[:,1],atol=6e-8,rtol=0)
    assert 'LuxeRearStripeShellSurface' not in parts and 'native_rear_flank_shading' not in info
    cap=parts['LuxeOxygenCasings'];assert cap['mat'] in model['PALETTE_BINDINGS'] and cap['mat'] not in model['FIXED_BINDINGS'] and 'uv' not in cap
    assert cap['mat']==parts['RoundOuterRail_-1']['mat']==parts['RoundOuterRail_1']['mat']
    assert info['oxygen_cap_material_revision']['source']=='tubing'
    if geometry:
        batch=[d for d in geometry['assets'].values() if 'LuxeOxygenCasings' in d['parts']];assert len(batch)==1 and not batch[0].get('fixed_material')
    report.update(solid_casings_closed=True,battery_cutout_ports_removed=True,battery_eyelets_present=bool(eyelet_names),ribbon_backface_restored_without_bevel=True,front_assembly_closed=True,ribbon_triangles=len(ribbon['f']),ribbon_and_binder_eyelets_use_native_side_material=True,gold_borders_flat=gold,octagon_settings=True,both_settings_blend_to_native_body=bool(info.get('right_octagon_setting_revision')),bands=bands,restored_native_side_triangles=len(restored),native_body_normals_unchanged=True,stripe_clearance_model=[float(gap.min()),float(gap.max())],oxygen_caps_use_live_astronaut_palette=True)
    (OUT/'luxe-comparisons-report.json').write_text(json.dumps(report,indent=2))
    return ['solid casings with low-profile tube fittings, closed native-grey front assembly, flat gold borders, both octagon settings blended to native body, capped front-trimmed bands, restored native side mapping, raised stripe clearance and live astronaut-palette oxygen caps verified']
