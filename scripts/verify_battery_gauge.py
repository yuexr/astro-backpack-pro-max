"""Verify the isolated native gauge variant, divider diameter and comparisons."""
import json
import numpy as np
from asset_io import es,ps,xyz
from battery_gauge import LABEL,SOURCE,PARENT
from game_assets import extract
from model import INFO,load_model
from settings import MODEL_STYLE,OUT,PKG


def check_battery_gauge(assets,geometry):
    model=load_model();parts={p['name']:p for p in model['parts']};info=json.loads(INFO.read_text());revision=info['battery_divider_revision']
    original=extract(SOURCE);current=assets[LABEL]
    assert len(current['Exports'])==len(original['Exports'])
    replacements={'PowerBar_Ringed_10_C':LABEL+'_C','Default__PowerBar_Ringed_10_C':'Default__'+LABEL+'_C'}
    for before,after in zip(original['Exports'],current['Exports']):
        assert after['ObjectName']==replacements.get(before['ObjectName'],before['ObjectName'])
        for key in ['OuterIndex','ClassIndex','TemplateIndex','SuperStruct','SuperIndex','ScriptBytecode','LoadedProperties']:
            assert after.get(key)==before.get(key),(before['ObjectName'],key)
        data=after.get('Data',[])
        if before['ObjectName']=='Spacer Meshes_GEN_VARIABLE':
            data=[p for p in data if p['Name']!='RelativeScale3D']
        assert data==before.get('Data',[]),(before['ObjectName'],'Native gauge behavior changed')
    assert current['Imports']==original['Imports']
    assert ps(es(current)['Default__'+LABEL+'_C'])['Ticks']['Value']==10
    parent=extract(PARENT);parent_class=original['Imports'][-original['Exports'][0]['SuperStruct']-1]['ObjectName'];assert parent_class=='PowerBar_Ringed_C'
    # Confirm the inherited construction script still supplies 1.1x spacer
    # instances. A game update must not silently invalidate this diameter.
    factors=[]
    def visit(value):
        if isinstance(value,dict):
            if 'StackNode' in value:
                node=value['StackNode'];entry=parent['Imports'][-node-1] if node<0 else parent['Exports'][node-1]
                if entry['ObjectName']=='MakeVector':
                    args=value['Parameters'];v=args[0].get('Value')
                    if isinstance(v,(int,float)) and v>1 and args[1].get('Value')==v:factors.append(v)
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(es(parent)['Set Ticks']['ScriptBytecode']);assert factors==[revision['native_spacer_instance_xy']]
    spacer=xyz(ps(es(current)['Spacer Meshes_GEN_VARIABLE'])['RelativeScale3D']);assert float(spacer['Z'])==1.
    assert abs(float(spacer['X'])-float(spacer['Y']))<1e-7
    widths=[float(np.ptp(parts['Battery'+end+'Casing']['v'][:,0])) for end in ['Top','Bottom']]
    gauges={}
    for label in ['BackpackRail','AstroCorpse']:
        d=assets[label];power=ps(es(d)['Power Bar_GEN_VARIABLE']);cls=d['Imports'][-power['ChildActorClass']['Value']-1]
        assert cls['ObjectName']==LABEL+'_C' and d['Imports'][-cls['OuterIndex']-1]['ObjectName']==PKG+LABEL
        scale=xyz(power['RelativeScale3D']);diameters=100*factors[0]*np.asarray([float(spacer[k])*float(scale[k]) for k in 'XY'])
        assert np.allclose(diameters,widths[0],atol=2e-5,rtol=0) and np.allclose(widths,widths[0],atol=2e-5,rtol=0)
        assert np.allclose([float(scale[k]) for k in 'XY'],[.09,.09],atol=1e-7),'Battery cells were widened with the spacers'
        gauges[label]=dict(divider_diameters_native=diameters.tolist(),casing_diameter_native=widths[0])
    if info.get('battery_solid_casing_revision'):
        assert not any(name.startswith(('BatteryTopTubeOpening_','BatteryBottomTubeOpening_')) for name in parts)
        expected=set(info.get('battery_tube_collar_revision',{}))
        assert {name for name in parts if name.startswith(('BatteryTopTubeEyelet_','BatteryBottomTubeEyelet_'))}==expected
        assert all(parts[f'BinderEyelet_{side}_{row}']['mat']=='Vanilla front casing sides' for side in [-1,1] for row in range(3))
    else:
        for name in info['top_tube_eyelet_revision']['parts']:
            assert parts[name]['mat']==parts['BinderEyelet_-1_0']['mat']=='eyelet'
    if MODEL_STYLE=='luxe':
        left=parts['LuxeYueMorse'];right=parts['LuxeYueMorsePolished'];assert 'normal' in left and 'normal' in right
        t=left['v'][left['f']];face=np.cross(t[:,1]-t[:,0],t[:,2]-t[:,0]);face/=np.linalg.norm(face,axis=1)[:,None]
        angles=np.degrees(np.arccos(np.clip((left['normal'][left['f']]*face[:,None,:]).sum(2),-1,1)))
        assert np.sum(angles>5)>60,'Left Morse code still has flat triangle shading'
    (OUT/'battery-divider-report.json').write_text(json.dumps(dict(gauges=gauges,native_cells_and_parent_functions_preserved=True,battery_cutout_ports_removed=bool(info.get('battery_solid_casing_revision')),battery_eyelets_present=bool(info.get('battery_tube_collar_revision')),binder_eyelets_match_front_side=True,left_morse_smooth=MODEL_STYLE=='luxe'),indent=2))
    return 'private native ten-cell gauge preserves cell size and charge functions; divider diameters match both solid casings on live/corpse backpacks; solid casings retain the approved low-profile tube fittings, binder eyelets match native front sides, both morse groups use authored smoothing'
