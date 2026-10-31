"""Check preview isolation, query shapes and generated mesh swap/restore behaviour."""
import json
import numpy as np
from asset_io import HERE, es, ps, xyz
from game_assets import extract
from printer_hover import CLICKABLE_CHANNEL, HOVER_COLLIDER, SYNC_HOVER
from printer_hover_preview import PREVIEWS, SAVED_MESH, SWAPPED_MESH, SWAP_PREVIEW
from printer_tooltip import HIDDEN
from settings import OUT
from verify_printer import PrinterVM


def normalize(value):
    if isinstance(value, float):return float(np.float32(value))
    if isinstance(value, list):return [normalize(v) for v in value]
    if isinstance(value, dict):return {k: normalize(v) for k, v in value.items()}
    return value


def check_hover_previews(assets):
    reference = json.loads((HERE / 'printer-native-api-reference.json').read_text())
    functions = set(reference['functions'])
    assert '/Script/Engine.StaticMeshComponent:GetStaticMesh' not in functions
    assert reference['properties']['/Script/Engine.StaticMeshComponent:StaticMesh'] == 'ObjectProperty'
    doc = assets['BackpackRail']
    def native_path(index):
        entry = doc['Imports'][-index-1]
        parent = native_path(entry['OuterIndex']) if entry['OuterIndex'] < 0 else ''
        return parent + ('.' if parent.startswith('/Script/') and '.' not in parent else ':') + entry['ObjectName'] if parent else entry['ObjectName']
    def check_calls(value):
        if isinstance(value, dict):
            if isinstance(value.get('StackNode'), int) and value['StackNode'] < 0:
                path = native_path(value['StackNode'])
                if path.startswith('/Script/Engine.'):
                    assert path in functions, ('No reflected native function', path)
            for child in value.values():check_calls(child)
        elif isinstance(value, list):
            for child in value:check_calls(child)
    for function in [SYNC_HOVER, SWAP_PREVIEW]:check_calls(es(doc)[function]['ScriptBytecode'])
    assert not any(i['ClassName']=='Function' and i['ObjectName']=='GetStaticMesh' for i in doc['Imports'])
    for original, label in PREVIEWS.items():
        native = extract('Astro/Content/Models/Indicators/' + original)
        private = assets[label]
        assert private['Imports'] == native['Imports']
        assert len(private['Exports']) == len(native['Exports'])
        for old, new in zip(native['Exports'], private['Exports']):
            assert old.get('Extras') == new.get('Extras'), 'Visible/cooked mesh bytes changed'
            data = [p for p in new['Data'] if p['Name'] != 'AggGeom'] if 'BodySetup' in old['ObjectName'] else new['Data']
            assert normalize(old['Data']) == normalize(data)
        body = next(e for e in private['Exports'] if 'BodySetup' in e['ObjectName'])
        agg = ps(body)['AggGeom']['Value']
        assert len(agg) == 1 and agg[0]['Name'] == 'BoxElems' and len(agg[0]['Value']) == 1
        fields = {p['Name']: p for p in agg[0]['Value'][0]['Value']}
        assert fields['bContributeToMass']['Value'] is False
        assert fields['CollisionEnabled']['EnumValue'] == 'ECollisionEnabled::QueryOnly'
        bounds = {p['Name']: p for p in ps(es(native)[original])['ExtendedBounds']['Value']}
        centre = np.array([float(xyz(fields['Center'])[a]) for a in 'XYZ'])
        extent = np.array([float(fields[a]['Value'])/2 for a in 'XYZ'])
        wanted = np.array([float(xyz(bounds['BoxExtent'])[a]) for a in 'XYZ'])
        assert np.max(abs(centre - [float(xyz(bounds['Origin'])[a]) for a in 'XYZ'])) < 1e-5
        assert np.all(extent >= wanted) and np.max(extent-wanted) < .002
        assert (OUT / ('staging/Astro/Content/Mods/CompactBackpack16/' + label + '.uasset')).is_file()
        assert not (OUT / ('staging/Astro/Content/Models/Indicators/' + original + '.uasset')).exists()
    for actor in ['Battery', 'Oxygen_Tank_Small']:
        assert not (OUT / ('staging/Astro/Content/Components_Small/' + actor + '.uasset')).exists()
    document = assets['BackpackRail'];cls = es(document)['BackpackRail_C']
    for name in [SAVED_MESH, SWAPPED_MESH]:
        assert 'CPF_Net' not in next(p for p in cls['LoadedProperties'] if p['Name']==name)['PropertyFlags']
    assert 'FUNC_Net' not in es(document)[SWAP_PREVIEW]['FunctionFlags']
    actor = {'local':True,HIDDEN:True,'output':{'state':2},'Printer Output Slot':object(),
        'PrinterVisible':True,'REP_ShowPrinterOutputSlotTooltip':True,'native_view_calls':0,'state_requests':[]}
    vm=PrinterVM(document,actor)
    for original,label in PREVIEWS.items():
        c={'collision':0,'mesh':vm.mesh_assets[original],'responses':{CLICKABLE_CHANNEL:1,3:0}}
        unrelated={'collision':0,'mesh':vm.mesh_assets[original]}
        vm.run(SYNC_HOVER,[c,True]);assert c['mesh'] is vm.mesh_assets[label] and c['collision']==1
        assert unrelated['mesh'] is vm.mesh_assets[original] and unrelated['collision']==0
        count=len(actor['mesh_requests'])
        for _ in range(100):vm.run(SYNC_HOVER,[c,True])
        assert len(actor['mesh_requests'])==count,'Repeated mesh replacement'
        c['collision']=0
        vm.run(SYNC_HOVER,[c,True]);assert c['mesh'] is vm.mesh_assets[label] and c['collision']==1
        vm.run(SYNC_HOVER,[c,False]);assert c['mesh'] is vm.mesh_assets[original] and c['collision']==0
        assert c['responses']=={CLICKABLE_CHANNEL:1,3:0}
        assert actor[SAVED_MESH] is None and actor[SWAPPED_MESH] is None
    c={'collision':0,'mesh':vm.mesh_assets['indicator_batterySmall']}
    vm.run(SYNC_HOVER,[c,True]);c['mesh']=vm.mesh_assets['indicator_canisterOxygenSmall']
    vm.run(SYNC_HOVER,[c,True]);assert c['mesh'] is vm.mesh_assets['PrinterHoverOxygenTank']
    c['mesh']=vm.mesh_assets['working_indicator'];vm.run(SYNC_HOVER,[c,False])
    assert c['mesh'] is vm.mesh_assets['working_indicator'],'Cleanup overwrote a new recipe'
    c['mesh']=vm.mesh_assets['indicator_batterySmall'];vm.run(SYNC_HOVER,[c,True])
    next_c={'collision':0,'mesh':vm.mesh_assets['indicator_canisterOxygenSmall']}
    vm.run(SYNC_HOVER,[next_c,True]);assert c['mesh'] is vm.mesh_assets['indicator_batterySmall'] and c['collision']==0
    assert next_c['mesh'] is vm.mesh_assets['PrinterHoverOxygenTank']
    vm.run(SYNC_HOVER,[next_c,False]);vm.run(SYNC_HOVER,[None,True]);assert actor[HOVER_COLLIDER] is None
    for mode in [1,2,3]:
        c={'collision':mode,'mesh':vm.mesh_assets['indicator_batterySmall']}
        vm.run(SYNC_HOVER,[c,True]);assert c['mesh'] is vm.mesh_assets['indicator_batterySmall'] and c['collision']==mode
    c={'collision':0,'mesh':vm.mesh_assets['indicator_batterySmall']};actor['output']['InputRespondingCollider']=c
    actor['local']=False;vm.native_view();assert c['mesh'] is vm.mesh_assets['indicator_batterySmall'] and c['collision']==0
    actor['local']=True;actor[HIDDEN]=True;vm.native_view();assert c['mesh'] is vm.mesh_assets['PrinterHoverBattery']
    actor['PrinterVisible']=False;vm.native_view();assert c['mesh'] is vm.mesh_assets['indicator_batterySmall'] and c['collision']==0
    return [
        'private Battery/Oxygen indicator boxes retain visible mesh bytes and bounds; query-only, no mass, no native item/indicator overrides',
        'preview native calls match reflected API; StaticMesh uses a property read; swap/restore simulations cover recipe/component reuse, resets, close and remote ownership',
    ]
