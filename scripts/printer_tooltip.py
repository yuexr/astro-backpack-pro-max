"""printer info button and tooltip toggle"""

import base64
import copy
import json
import uuid

import numpy as np
from asset_io import HERE, append, es, gltf, prop, ps, xyz
from blueprint import Blueprint, replace_instruction
from game_assets import extract
from kismet import kismet_size
from settings import OUT, PKG, PRINTER_ICON_SCALE

BUTTON = "BPM_EyeButton"
HIDDEN = "BPM_PrinterTooltipHidden"
TOGGLE = "BPM_TogglePrinterTooltip"
GET_HIDDEN = "BPM_IsPrinterTooltipHidden"


def renamed(document, replacements):
    def walk(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [walk(item) for item in value]
        if isinstance(value, dict):
            return {key: walk(item) for key, item in value.items()}
        return value

    return walk(document)


def info_mesh():
    source = "Astro/Content/Models/ControlPanels/control_panel_button_round_arrow"
    document = extract(source)
    mesh = next(
        e
        for e in document["Exports"]
        if e["ObjectName"] == "control_panel_button_round_arrow"
    )
    raw = bytearray(base64.b64decode(mesh["Extras"]))
    _, attributes, indices = gltf(
        HERE / "exports/Models/ControlPanels/control_panel_button_round_arrow.gltf"
    )
    vertices = attributes["POSITION"][:, [0, 2, 1]] * 100
    assert vertices.shape == (181, 3) and indices.shape == (246, 3)
    position_offset, tangent_offset, uv_offset, index_offset = 110, 2308, 3764, 5234
    original_positions = (
        np.frombuffer(raw, "<f4", count=181 * 3, offset=position_offset)
        .reshape(-1, 3)
        .copy()
    )
    assert np.allclose(original_positions, vertices, atol=1e-4, rtol=0)
    assert np.array_equal(
        np.frombuffer(raw, "<u2", count=indices.size, offset=index_offset).reshape(
            -1, 3
        ),
        indices,
    )
    texcoords = (
        np.frombuffer(raw, "<f2", count=181 * 4, offset=uv_offset).reshape(-1, 4).copy()
    )
    tangents = (
        np.frombuffer(raw, "i1", count=181 * 8, offset=tangent_offset)
        .reshape(-1, 8)
        .copy()
    )
    assert np.array_equal(texcoords[:, :2], attributes["TEXCOORD_0"])
    arrow = np.flatnonzero(attributes["TEXCOORD_0"][:, 0] > 0.65)
    arrow_faces = np.flatnonzero(np.isin(indices[:, 0], arrow))
    assert len(arrow) == 57 and len(arrow_faces) == 62
    assert np.isin(indices[arrow_faces], arrow).all()

    # The approved info disc fits inside the native arrow buffer.
    approved = json.loads((HERE.parent / "models/printer-info.json").read_text())
    glyph = approved["parts"]["info"]
    points = np.array(glyph["positions"], dtype="<f4")
    # Resize only the flat glyph; keep button size, depth and click target.
    centre = (points[:, 1:].min(axis=0) + points[:, 1:].max(axis=0)) / 2
    points[:, 1:] = centre + (points[:, 1:] - centre) * PRINTER_ICON_SCALE
    faces = np.array(glyph["triangles"])
    assert len(points) <= len(arrow) and len(faces) <= len(arrow_faces)
    # The exporter uses clockwise front faces in native coordinates.
    crosses = np.cross(
        points[faces[:, 1]] - points[faces[:, 0]],
        points[faces[:, 2]] - points[faces[:, 0]],
    )
    faces[crosses[:, 0] > 0] = faces[crosses[:, 0] > 0][:, [0, 2, 1]]
    allocated = arrow[: len(points)]
    positions = original_positions.copy()
    positions[arrow] = points[0]
    positions[allocated] = points
    new_indices = indices.copy()
    new_indices[arrow_faces] = 0
    new_indices[arrow_faces[: len(faces)]] = allocated[faces]
    texcoords[allocated, :2] = np.array([0.689453125, 0.92919921875], dtype="<f2")
    tangents[allocated, :3] = [0, 127, 0]
    tangents[allocated, 3] = 127
    tangents[allocated, 4:7] = [127, 0, 0]
    tangents[allocated, 7] = -127
    for offset, data in [
        (position_offset, positions.astype("<f4")),
        (tangent_offset, tangents),
        (uv_offset, texcoords),
        (index_offset, new_indices.astype("<u2")),
    ]:
        raw[offset : offset + data.nbytes] = data.tobytes()
    mesh["Extras"] = base64.b64encode(raw).decode()
    np.savez(
        OUT / "printer-info-expected.npz",
        positions=positions,
        indices=new_indices,
        uv=texcoords[:, :2].astype("f4"),
        original_positions=original_positions,
        casing=np.flatnonzero(~np.isin(np.arange(181), arrow)),
    )
    # Keep the existing private asset path for saved backpacks.
    asset_name = "PrinterEyeMesh"
    return renamed(
        document,
        {
            "control_panel_button_round_arrow": asset_name,
            "/Game/Models/ControlPanels/control_panel_button_round_arrow": PKG
            + asset_name,
        },
    )


def info_button():
    document = extract(
        "Astro/Content/ControlPanels/ModularControlPanel/PanelParts/ControlPanelButton_Round"
    )
    document = renamed(
        document,
        {
            "/Game/ControlPanels/ModularControlPanel/PanelParts/ControlPanelButton_Round": PKG
            + "PrinterEyeButton",
            "ControlPanelButton_Round": "PrinterEyeButton",
            "ControlPanelButton_Round_C": "PrinterEyeButton_C",
            "Default__ControlPanelButton_Round_C": "Default__PrinterEyeButton_C",
            "/Game/Models/ControlPanels/control_panel_button_round_arrow": PKG
            + "PrinterEyeMesh",
            "control_panel_button_round_arrow": "PrinterEyeMesh",
        },
    )
    # This button stays usable while printing; navigation button state is separate.
    es(document)["Default__PrinterEyeButton_C"]["Data"].append(
        prop(document, "Bool", "bButtonEnabled", True)
    )
    return document


def printer_head():
    document = extract("Astro/Content/Components/Printhead_Backpack")
    source = extract("Astro/Content/Components/PrintheadSelector")
    editor = Blueprint(
        document, next(e for e in source["Exports"] if "FunctionExport" in e["$type"])
    )
    src = es(source)
    old_component = src["ControlPanelButtonChildActor_LeftButton_GEN_VARIABLE"]
    component = copy.deepcopy(old_component)
    editor.copy_names(source, component["Data"])
    component.update(
        ObjectName=editor.name(BUTTON + "_GEN_VARIABLE"),
        OuterIndex=editor.cid,
        ClassIndex=editor.copy_import(source, old_component["ClassIndex"]),
        TemplateIndex=editor.copy_import(source, old_component["TemplateIndex"]),
        SerialSize=0,
        SerialOffset=0,
    )
    pkg = editor.imp(PKG + "PrinterEyeButton", kind="Package")
    button_class = editor.imp(
        "PrinterEyeButton_C", pkg, "BlueprintGeneratedClass", "/Script/Engine"
    )
    ps(component)["ChildButtonClass"]["Value"] = button_class
    xyz(ps(component)["RelativeLocation"])["Y"] = 0.0
    component["CreateBeforeSerializationDependencies"] = [button_class]
    component["SerializationBeforeSerializationDependencies"] = []
    component["SerializationBeforeCreateDependencies"] = [
        component["ClassIndex"],
        component["TemplateIndex"],
    ]
    component["CreateBeforeCreateDependencies"] = [editor.cid]
    component_id = append(document, component)
    source_class = next(e for e in source["Exports"] if "ClassExport" in e["$type"])
    field = copy.deepcopy(
        next(
            p
            for p in source_class["LoadedProperties"]
            if p["Name"] == "ControlPanelButtonChildActor_LeftButton"
        )
    )
    field.update(
        Name=editor.name(BUTTON),
        PropertyClass=editor.copy_import(source, field["PropertyClass"]),
    )
    editor.cls["LoadedProperties"].append(field)
    editor.cls["CreateBeforeSerializationDependencies"].append(component_id)

    scs = next(
        e
        for e in document["Exports"]
        if e["ObjectName"].startswith("SimpleConstructionScript_")
    )
    scs_id = document["Exports"].index(scs) + 1
    old_id = source["Exports"].index(old_component) + 1
    old_node = next(
        e
        for e in source["Exports"]
        if ps(e).get("ComponentTemplate", {}).get("Value") == old_id
    )
    node = copy.deepcopy(old_node)
    editor.copy_names(source, node["Data"])
    node.update(
        ObjectName=editor.name("SCS_" + BUTTON),
        OuterIndex=scs_id,
        ClassIndex=editor.copy_import(source, old_node["ClassIndex"]),
        TemplateIndex=editor.copy_import(source, old_node["TemplateIndex"]),
        SerialSize=0,
        SerialOffset=0,
    )
    ps(node)["ComponentClass"]["Value"] = component["ClassIndex"]
    ps(node)["ComponentTemplate"]["Value"] = component_id
    ps(node)["InternalVariableName"]["Value"] = editor.name(BUTTON)
    ps(node)["VariableGuid"]["Value"][0]["Value"] = (
        "{"
        + str(uuid.uuid5(uuid.NAMESPACE_DNS, "backpack-pro-max.printer-eye")).upper()
        + "}"
    )
    node["Data"] = [
        p
        for p in node["Data"]
        if p["Name"]
        not in [
            "ChildNodes",
            "ParentComponentOrVariableName",
            "ParentComponentOwnerClassName",
            "bIsParentComponentNative",
        ]
    ]
    node["Data"] += [
        prop(document, "Name", "ParentComponentOrVariableName", "Scene"),
        prop(document, "Name", "ParentComponentOwnerClassName", "PrintheadSelector_C"),
        prop(document, "Bool", "bIsParentComponentNative", False),
    ]
    editor.name("Scene")
    editor.name("PrintheadSelector_C")
    node["CreateBeforeSerializationDependencies"] = [
        component_id,
        component["ClassIndex"],
    ]
    node["SerializationBeforeSerializationDependencies"] = []
    node["SerializationBeforeCreateDependencies"] = [
        node["ClassIndex"],
        node["TemplateIndex"],
    ]
    node["CreateBeforeCreateDependencies"] = [scs_id]
    node_id = append(document, node)
    source_scs = source["Exports"][old_node["OuterIndex"] - 1]
    for label in ["RootNodes", "AllNodes"]:
        array = copy.deepcopy(ps(source_scs)[label])
        editor.copy_names(source, array)
        array["Value"] = [prop(document, "Object", "0", node_id)]
        scs["Data"] = [p for p in scs["Data"] if p["Name"] != label] + [array]
    scs["CreateBeforeSerializationDependencies"].append(node_id)

    # Button presses are local; call the owning backpack without a circular asset import.
    engine = editor.imp("/Script/Engine", kind="Package")
    actor = editor.imp("Actor", engine)
    parent = editor.imp("GetAttachParentActor", actor, "Function")
    system = editor.imp("KismetSystemLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    parent_actor = editor.call(parent)
    native_sound = src["NavigateRight"]["ScriptBytecode"][0]["Expression"]
    native_post = native_sound["ContextExpression"]
    event = copy.deepcopy(native_post["Parameters"][0])
    assert event["Value"] == "play_sym_right"
    left_event = copy.deepcopy(
        src["NavigateLeft"]["ScriptBytecode"][0]["Expression"]["ContextExpression"][
            "Parameters"
        ][0]
    )
    assert left_event["Value"] == "play_sym_left"
    math_library = editor.imp("KismetMathLibrary", engine)
    select_string = editor.imp("SelectString", math_library, "Function")
    # Read the current setting before toggling: hidden -> show/right, visible -> hide/left.
    current_hidden = editor.ctx(
        copy.deepcopy(parent_actor),
        editor.ex(
            "EX_VirtualFunction",
            VirtualFunctionName=editor.name(GET_HIDDEN),
            Parameters=[],
        ),
    )
    event = editor.call(select_string, event, left_event, current_hidden, math=True)
    child_actor_owner = native_post["Parameters"][1]["ContextExpression"]["Variable"][
        "New"
    ]["ResolvedOwner"]
    info_button_actor = editor.ctx(
        editor.var(BUTTON),
        editor.ex(
            "EX_InstanceVariable",
            Variable=editor.ptr(
                "ChildActor", editor.copy_import(source, child_actor_owner)
            ),
        ),
    )
    sound = editor.ctx(
        editor.ex(
            "EX_ObjectConst",
            Value=editor.copy_import(source, native_sound["ObjectExpression"]["Value"]),
        ),
        editor.call(
            editor.copy_import(source, native_post["StackNode"]),
            event,
            info_button_actor,
            copy.deepcopy(native_post["Parameters"][2]),
        ),
    )
    callback_id = len(document["Exports"]) + 1
    sound_handle = editor.ptr("CallFunc_PostEvent_ReturnValue", callback_id)
    sound = editor.ex(
        "EX_Let",
        Value=copy.deepcopy(sound_handle),
        Variable=editor.ex("EX_LocalVariable", Variable=copy.deepcopy(sound_handle)),
        Expression=sound,
    )
    callback = editor.function(
        "BPM_EyePressed",
        [
            editor.guard(editor.call(valid, copy.deepcopy(parent_actor))),
            sound,
            editor.ctx(
                parent_actor,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(TOGGLE),
                    Parameters=[],
                ),
            ),
        ],
    )
    assert callback == callback_id
    callback_export = document["Exports"][callback - 1]
    callback_export["LoadedProperties"] = copy.deepcopy(
        src["NavigateRight"]["LoadedProperties"]
    )
    editor.copy_names(source, callback_export["LoadedProperties"])
    editor.name("IntProperty")
    callback_export["CreateBeforeSerializationDependencies"] = [
        i
        for i in callback_export["CreateBeforeSerializationDependencies"]
        if i != callback
    ] + [sound["Expression"]["ObjectExpression"]["Value"]]

    binding_source = next(
        e
        for e in source["Exports"]
        if e["ObjectName"].startswith("ComponentDelegateBinding_")
    )
    binding = copy.deepcopy(binding_source)
    editor.copy_names(source, binding["Data"])
    binding.update(
        ObjectName=editor.name("BPM_PrinterEyeBinding"),
        OuterIndex=editor.cid,
        ClassIndex=editor.copy_import(source, binding_source["ClassIndex"]),
        TemplateIndex=editor.copy_import(source, binding_source["TemplateIndex"]),
        SerialSize=0,
        SerialOffset=0,
    )
    row = copy.deepcopy(ps(binding)["ComponentDelegateBindings"]["Value"][0])
    fields = {p["Name"]: p for p in row["Value"]}
    fields["ComponentPropertyName"]["Value"] = editor.name(BUTTON)
    fields["FunctionNameToBind"]["Value"] = editor.name("BPM_EyePressed")
    ps(binding)["ComponentDelegateBindings"]["Value"] = [row]
    binding["CreateBeforeSerializationDependencies"] = [component_id, callback]
    binding["SerializationBeforeSerializationDependencies"] = []
    binding["SerializationBeforeCreateDependencies"] = [
        binding["ClassIndex"],
        binding["TemplateIndex"],
    ]
    binding["CreateBeforeCreateDependencies"] = [editor.cid]
    binding_id = append(document, binding)
    dynamic = copy.deepcopy(ps(source_class)["DynamicBindingObjects"])
    editor.copy_names(source, dynamic)
    dynamic["Value"] = [prop(document, "Object", "0", binding_id)]
    editor.cls["Data"].append(dynamic)
    editor.cls["CreateBeforeSerializationDependencies"].append(binding_id)
    return document


def patch_backpack(document):
    editor = Blueprint(document)
    editor.bool_field(HIDDEN, False)
    getter_id = editor.function(GET_HIDDEN, [])
    getter = document["Exports"][getter_id - 1]
    getter["ScriptBytecode"][0]["ReturnExpression"] = editor.var(HIDDEN)
    getter["ScriptBytecodeSize"] = sum(map(kismet_size, getter["ScriptBytecode"]))
    result = copy.deepcopy(
        next(p for p in editor.cls["LoadedProperties"] if p["Name"] == HIDDEN)
    )
    result.update(
        Name=editor.name("ReturnValue"),
        PropertyFlags="CPF_Parm, CPF_OutParm, CPF_ReturnParm",
    )
    getter["LoadedProperties"] = [result]
    getter["FunctionFlags"] += ", FUNC_BlueprintPure, FUNC_Const"
    imports = {e["ObjectName"]: -i - 1 for i, e in enumerate(document["Imports"])}
    printer_view = es(document)["CLIENT Printer View"]
    # Decide once, before native code asks the tooltip to animate. Collapsing it
    # after the native show request restarts its badge animation every update.
    code = printer_view["ScriptBytecode"]
    gate = copy.deepcopy(code[47])
    assert gate["VariableExpression"]["Variable"]["New"]["Path"] == [
        "CallFunc_BooleanAND_ReturnValue"
    ]
    original = gate["AssignmentExpression"]
    assert original["StackNode"] == imports["BooleanAND"]
    assert [p["Variable"]["New"]["Path"] for p in original["Parameters"]] == [
        ["PrinterVisible"],
        ["REP_ShowPrinterOutputSlotTooltip"],
    ]
    gate["AssignmentExpression"] = editor.call(
        imports["BooleanAND"],
        original,
        editor.call(
            imports["Not_PreBool"], editor.call(getter_id, local=True), math=True
        ),
        math=True,
    )
    replace_instruction(printer_view, 47, gate)
    printer_view_id = document["Exports"].index(printer_view) + 1
    editor.function(
        TOGGLE,
        [
            editor.guard(editor.call(imports["IsLocallyControlled"])),
            editor.assign_bool(
                HIDDEN,
                editor.call(imports["Not_PreBool"], editor.var(HIDDEN), math=True),
            ),
            editor.call(printer_view_id, local=True),
        ],
    )
    from printer_preferences import patch_preferences

    patch_preferences(document, HIDDEN, GET_HIDDEN, TOGGLE)


def build_printer_assets():
    from printer_preferences import ASSET, preferences_asset

    return {
        ASSET: (
            preferences_asset(),
            "Astro/Content/Mods/CompactBackpack16/" + ASSET + ".uasset",
        ),
        "PrinterEyeMesh": (
            info_mesh(),
            "Astro/Content/Mods/CompactBackpack16/PrinterEyeMesh.uasset",
        ),
        "PrinterEyeButton": (
            info_button(),
            "Astro/Content/Mods/CompactBackpack16/PrinterEyeButton.uasset",
        ),
        "Printhead_Backpack": (
            printer_head(),
            "Astro/Content/Components/Printhead_Backpack.uasset",
        ),
    }
