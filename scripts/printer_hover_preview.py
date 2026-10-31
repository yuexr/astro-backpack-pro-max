"""Private mouse-hit shapes for the two printer indicators without simple collision."""

import copy

from asset_io import es, name, ps, xyz
from game_assets import extract
from settings import PKG

PREVIEWS = {
    "indicator_batterySmall": "PrinterHoverBattery",
    "indicator_canisterOxygenSmall": "PrinterHoverOxygenTank",
}
SWAP_PREVIEW = "BPM_SetPrinterHoverPreview"
SAVED_MESH = "BPM_PrinterHoverOriginalMesh"
SWAPPED_MESH = "BPM_PrinterHoverPrivateMesh"


def preview_assets():
    cube = extract("Engine/Content/BasicShapes/Cube")
    donor = next(e for e in cube["Exports"] if "BodySetup" in e["ObjectName"])
    result = {}
    for original, label in PREVIEWS.items():
        source = extract("Astro/Content/Models/Indicators/" + original)
        document = copy.deepcopy(source)
        body = next(e for e in document["Exports"] if "BodySetup" in e["ObjectName"])
        assert not any(p.get("Value") for p in ps(body).get("AggGeom", {}).get("Value", []))
        bounds = {p["Name"]: p for p in ps(es(document)[original])["ExtendedBounds"]["Value"]}
        aggregate = copy.deepcopy(ps(donor)["AggGeom"])
        boxes = next(p for p in aggregate["Value"] if p["Name"] == "BoxElems")
        aggregate["Value"] = [boxes]
        boxes["Value"] = boxes["Value"][:1]
        fields = {p["Name"]: p for p in boxes["Value"][0]["Value"]}
        xyz(fields["Center"]).update({axis: float(xyz(bounds["Origin"])[axis]) for axis in "XYZ"})
        for axis in "XYZ":
            fields[axis]["Value"] = 2 * float(xyz(bounds["BoxExtent"])[axis]) + 0.002
        fields["bContributeToMass"]["Value"] = False
        fields["CollisionEnabled"]["EnumValue"] = "ECollisionEnabled::QueryOnly"
        body["Data"].append(aggregate)

        def copy_names(value):
            if isinstance(value, str) and value in cube["NameMap"]:
                name(document, value)
            elif isinstance(value, dict):
                for child in value.values():
                    copy_names(child)
            elif isinstance(value, list):
                for child in value:
                    copy_names(child)

        copy_names(aggregate)
        name(document, "ECollisionEnabled::QueryOnly")
        replacements = {original: label, "/Game/Models/Indicators/" + original: PKG + label}

        def rename(value):
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [rename(child) for child in value]
            if isinstance(value, dict):
                return {key: rename(child) for key, child in value.items()}
            return value

        document = rename(document)
        for generation in document["Generations"]:
            generation["NameCount"] = len(document["NameMap"])
            generation["ExportCount"] = len(document["Exports"])
        result[label] = document, "Astro/Content/Mods/CompactBackpack16/" + label + ".uasset"
    return result


def add_preview_helper(editor, object_field):
    engine = editor.imp("/Script/Engine", kind="Package")
    component_class = editor.imp("StaticMeshComponent", engine)
    mesh_class = editor.imp("StaticMesh", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    equal = editor.imp("EqualEqual_ObjectObject", maths, "Function")
    set_mesh = editor.imp("SetStaticMesh", component_class, "Function")
    saved = copy.deepcopy(object_field)
    saved.update(Name=editor.name(SAVED_MESH), PropertyClass=mesh_class)
    editor.cls["LoadedProperties"].append(saved)
    swapped = copy.deepcopy(saved)
    swapped["Name"] = editor.name(SWAPPED_MESH)
    editor.cls["LoadedProperties"].append(swapped)
    editor.cls["CreateBeforeSerializationDependencies"].append(mesh_class)
    from asset_io import prop

    es(editor.d)["Default__" + editor.cls["ObjectName"]]["Data"].append(prop(editor.d, "Object", SAVED_MESH, 0))
    es(editor.d)["Default__" + editor.cls["ObjectName"]]["Data"].append(prop(editor.d, "Object", SWAPPED_MESH, 0))
    fid = len(editor.d["Exports"]) + 1
    collider = editor.ex("EX_LocalVariable", Variable=editor.ptr("Collider", fid))
    restore = editor.ex("EX_LocalVariable", Variable=editor.ptr("Restore", fid))
    component = editor.ex("EX_LocalVariable", Variable=editor.ptr("Preview", fid))
    current = editor.ex("EX_LocalVariable", Variable=editor.ptr("CurrentMesh", fid))
    mesh_property = editor.ptr("StaticMesh", component_class)
    read_mesh = editor.ctx(component, editor.ex("EX_InstanceVariable", Variable=mesh_property))
    read_mesh["RValuePointer"] = copy.deepcopy(mesh_property)

    def assign(variable, value):
        return editor.ex("EX_LetObj", VariableExpression=variable, AssignmentExpression=value)

    body = [
        assign(component, editor.ex("EX_DynamicCast", ClassPtr=component_class, Target=collider)),
        editor.guard(editor.call(valid, component)),
        assign(current, read_mesh),
        editor.guard(restore),
        editor.guard(editor.call(valid, editor.var(SAVED_MESH))),
        editor.guard(editor.call(equal, current, editor.var(SWAPPED_MESH), math=True)),
        editor.ctx(component, editor.call(set_mesh, editor.var(SAVED_MESH))),
        editor.ex("EX_Jump", CodeOffset=0),
    ]
    jumps = {1: "end", 3: 8, 4: "end", 5: "end", 7: "end"}
    dependencies = {component_class, mesh_class}
    for original, label in PREVIEWS.items():
        package = editor.imp("/Game/Models/Indicators/" + original, kind="Package")
        native = editor.imp(original, package, "StaticMesh", "/Script/Engine")
        package = editor.imp(PKG + label, kind="Package")
        private = editor.imp(label, package, "StaticMesh", "/Script/Engine")
        dependencies.update([native, private])
        index = len(body)
        body += [
            editor.guard(editor.call(equal, current, editor.ex("EX_ObjectConst", Value=native), math=True)),
            assign(editor.var(SAVED_MESH), current),
            assign(editor.var(SWAPPED_MESH), editor.ex("EX_ObjectConst", Value=private)),
            editor.ctx(component, editor.call(set_mesh, editor.ex("EX_ObjectConst", Value=private))),
            editor.ex("EX_Jump", CodeOffset=0),
        ]
        jumps[index] = len(body)
        jumps[index + 4] = "end"
    assert editor.function(SWAP_PREVIEW, body) == fid
    function = editor.d["Exports"][fid - 1]
    offsets = [0]
    from kismet import kismet_size

    for instruction in function["ScriptBytecode"]:
        offsets.append(offsets[-1] + kismet_size(instruction))
    end = len(body) - 2
    for index, destination in jumps.items():
        function["ScriptBytecode"][index]["CodeOffset"] = offsets[end if destination == "end" else destination]
    parameter = copy.deepcopy(object_field)
    parameter.update(Name=editor.name("Collider"), PropertyFlags="CPF_Parm")
    enabled = copy.deepcopy(next(p for p in editor.cls["LoadedProperties"] if p["Name"] == "BPM_PrinterTooltipHidden"))
    enabled.update(Name=editor.name("Restore"), PropertyFlags="CPF_Parm")
    local_component = copy.deepcopy(parameter)
    local_component.update(Name=editor.name("Preview"), PropertyClass=component_class, PropertyFlags="CPF_None")
    local_mesh = copy.deepcopy(saved)
    local_mesh.update(Name=editor.name("CurrentMesh"), PropertyFlags="CPF_None")
    function["LoadedProperties"] = [parameter, enabled, local_component, local_mesh]
    function["CreateBeforeSerializationDependencies"] = sorted(set(function["CreateBeforeSerializationDependencies"]) | dependencies)
    return fid
