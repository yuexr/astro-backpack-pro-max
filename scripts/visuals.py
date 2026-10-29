"""Add the socket meshes and share the backpack material."""

import base64
import copy
import json
import uuid

from asset_io import HERE, location, ps, xyz
from asset_io import append as append_export
from asset_io import name as asset_name
from asset_io import prop as asset_prop
from kismet import kismet_size as size
from settings import OUT, PKG

DRONE_SOCKET_INSET = (
    2.0  # Outer rim seating; keep the recessed centre above the casing.
)


def add_visual_components(d, front_parts, corpse=False):
    def name(n):
        return asset_name(d, n)

    def imp(n, outer, kind="Class", pkg="/Script/CoreUObject"):
        for i, x in enumerate(d["Imports"]):
            if (x["ObjectName"], x["OuterIndex"], x["ClassName"]) == (n, outer, kind):
                return -i - 1
        d["Imports"].append(
            {
                "$type": "UAssetAPI.Import, UAssetAPI",
                "ObjectName": name(n),
                "OuterIndex": outer,
                "ClassPackage": name(pkg),
                "ClassName": name(kind),
                "PackageName": None,
                "bImportOptional": False,
            }
        )
        return -len(d["Imports"])

    def prop(t, n, v):
        return asset_prop(d, t, n, v)

    def append(e):
        return append_export(d, e)

    mesh_name = "Backpack_mk2" if corpse else "backpack_mk2"
    mesh = next(
        e for e in d["Exports"] if e["ObjectName"] == mesh_name + "_GEN_VARIABLE"
    )
    mesh_id = d["Exports"].index(mesh) + 1
    cls_id = mesh["OuterIndex"]
    cls = d["Exports"][cls_id - 1]
    mesh_node = next(
        e
        for e in d["Exports"]
        if ps(e).get("ComponentTemplate", {}).get("Value") == mesh_id
    )
    scs = d["Exports"][mesh_node["OuterIndex"] - 1]
    parent_name = "ItemSlots" if corpse else "Item Slots"
    parent = next(
        e
        for e in d["Exports"]
        if ps(e).get("InternalVariableName", {}).get("Value") == parent_name
    )
    origin = xyz(
        ps(
            next(
                e
                for e in d["Exports"]
                if e["ObjectName"] == parent_name + "_GEN_VARIABLE"
            )
        )["RelativeLocation"]
    )
    geometry = json.loads((OUT / "geometry-report.json").read_text())
    cx = geometry["socket_centre_native_x"]
    specifications = []
    for n in range(16):
        y = (-40 if n % 2 == 0 else 40) if n < 8 else (-18 if n % 2 == 0 else 18)
        z = [47.0, 14.3, -18.1, -51.0][n % 8 // 2]
        specifications.append(
            (f"NativeBackpackSocket{n + 1}", "backpack_socket", 0.88, [cx, y, z])
        )
    for mesh_part in front_parts:
        specifications.append(("Compact_" + mesh_part, mesh_part, 1.0, [0.0, 0.0, 0.0]))
    if not corpse:
        specifications.append(("NativeDroneSocket", "drone_socket", 0.25, None))
    components = []
    for variable, mesh_part, scale_value, centre in specifications:
        variable = name(variable)
        fixed_material = geometry["assets"].get(mesh_part, {}).get("fixed_material")
        if not fixed_material:
            components.append(variable)
        pkg = imp(PKG + mesh_part, 0, "Package")
        asset = imp(mesh_part, pkg, "SkeletalMesh", "/Script/Engine")
        e = copy.deepcopy(mesh)
        e.update(
            ObjectName=name(variable + "_GEN_VARIABLE"),
            SerialSize=0,
            SerialOffset=0,
            Extras="",
        )
        data = ps(mesh)
        e["Data"] = [
            prop("Object", "SkeletalMesh", asset),
            prop("Bool", "bUseAttachParentBound", True),
            prop("Bool", "bReceivesDecals", False),
        ]
        if fixed_material:
            material_pkg = imp(fixed_material, 0, "Package")
            material = imp(
                fixed_material.rsplit("/", 1)[-1],
                material_pkg,
                "MaterialInstanceConstant",
                "/Script/Engine",
            )
            override = prop(
                "Array", "OverrideMaterials", [prop("Object", "0", material)]
            )
            override["ArrayType"] = "ObjectProperty"
            e["Data"].append(override)
        body = copy.deepcopy(data["BodyInstance"]) if "BodyInstance" in data else None
        if body is None:
            donor = json.loads(
                (HERE / "vanilla/Astro/Content/Items/BackpackRail.json").read_text()
            )
            native_body = next(
                x
                for x in donor["Exports"]
                if x["ObjectName"] == "backpack_mk2_GEN_VARIABLE"
            )
            body = copy.deepcopy(ps(native_body)["BodyInstance"])
            body["Value"] = [
                x
                for x in body["Value"]
                if x["Name"] in ["CollisionEnabled", "CollisionProfileName"]
            ]
            for n in [
                "BodyInstance",
                "CollisionEnabled",
                "CollisionProfileName",
                "ECollisionEnabled",
            ]:
                name(n)
        if body:
            for field in body["Value"]:
                if field["Name"] == "CollisionEnabled":
                    field["EnumValue"] = "ECollisionEnabled::NoCollision"
                if field["Name"] == "CollisionProfileName":
                    field["Value"] = "NoCollision"
            name("NoCollision")
            name("ECollisionEnabled::NoCollision")
            e["Data"].append(body)
        scale = copy.deepcopy(
            next(
                q
                for x in d["Exports"]
                for q in x.get("Data", [])
                if q["Name"] == "RelativeScale3D"
            )
        )
        xyz(scale).update(X=scale_value, Y=scale_value, Z=scale_value)
        e["Data"].append(scale)
        component_parent = parent
        if variable == "NativeDroneSocket":
            # Keep the actual drone slot unchanged; inset only its visible socket.
            # The native visual's local Z=3 offset contributes -.75 on backpack Y.
            slot = next(
                x
                for x in d["Exports"]
                if x["ObjectName"] == "Creative Drone Slot_GEN_VARIABLE"
            )
            sp = ps(slot)
            body_origin = xyz(ps(mesh)["RelativeLocation"])
            loc = [
                float(xyz(sp["RelativeLocation"])[k]) - float(body_origin[k])
                for k in "XYZ"
            ]
            loc[1] += DRONE_SOCKET_INSET - 0.75
            location(d, e, loc)
            e["Data"].append(copy.deepcopy(sp["RelativeRotation"]))
            component_parent = mesh_node
            e["Data"].append(prop("Bool", "bVisible", False))
        else:
            if corpse:
                location(d, e, [centre[i] - origin[k] for i, k in enumerate("XYZ")])
            else:
                # vehicle mode hides the item branch; the shell isn't an item
                component_parent = mesh_node
                location(d, e, centre)
        e["CreateBeforeSerializationDependencies"] = [asset]
        if fixed_material:
            e["CreateBeforeSerializationDependencies"].append(material)
        comp = append(e)
        node = copy.deepcopy(mesh_node)
        node.update(
            ObjectName=name("SCS_Node_" + variable),
            SerialSize=0,
            SerialOffset=0,
            Extras="",
        )
        guid = copy.deepcopy(ps(mesh_node)["VariableGuid"])
        guid["Value"][0]["Value"] = (
            "{"
            + str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS, ("corpse." if corpse else "live.") + variable
                )
            ).upper()
            + "}"
        )
        node["Data"] = [
            prop("Object", "ComponentClass", mesh["ClassIndex"]),
            prop("Object", "ComponentTemplate", comp),
            guid,
            prop("Name", "InternalVariableName", variable),
        ]
        node["CreateBeforeSerializationDependencies"] = [comp, mesh["ClassIndex"]]
        node_id = append(node)
        for owner, key in [(component_parent, "ChildNodes"), (scs, "AllNodes")]:
            array = ps(owner)[key]["Value"]
            array.append(prop("Object", str(len(array)), node_id))
            owner["CreateBeforeSerializationDependencies"].append(node_id)
        field = copy.deepcopy(
            next(x for x in cls["LoadedProperties"] if x["Name"] == mesh_name)
        )
        field["Name"] = variable
        cls["LoadedProperties"].append(field)
        cls["CreateBeforeSerializationDependencies"].append(comp)
    # Share the live material so palettes and effects match.
    engine = imp("/Script/Engine", 0, "Package")
    primitive = imp("PrimitiveComponent", engine)
    get = imp("GetMaterial", primitive, "Function")
    set_ = imp("SetMaterial", primitive, "Function")
    system = imp("KismetSystemLibrary", engine)
    valid = imp("IsValid", system, "Function")
    scene = imp("SceneComponent", engine)
    visible = imp("SetVisibility", scene, "Function")
    skinned = imp("SkinnedMeshComponent", engine)
    master_pose = imp("SetMasterPoseComponent", skinned, "Function")
    astro = imp("/Script/Astro", 0, "Package")
    statics = imp("AstroStatics", astro)
    creative = imp("IsCreativeMode", statics, "Function")

    def ex(t, **kw):
        return {
            "$type": "UAssetAPI.Kismet.Bytecode.Expressions." + t + ", UAssetAPI",
            **kw,
        }

    def ptr(owner, n=None):
        return {
            "$type": "UAssetAPI.Kismet.Bytecode.KismetPropertyPointer, UAssetAPI",
            "New": {
                "$type": "UAssetAPI.UnrealTypes.FFieldPath, UAssetAPI",
                "Path": [name(n)] if n else [],
                "ResolvedOwner": owner,
            },
        }

    def var(n):
        return ex("EX_InstanceVariable", Variable=ptr(cls_id, n))

    def call(f, *params, local=False):
        return ex(
            "EX_LocalFinalFunction" if local else "EX_FinalFunction",
            StackNode=f,
            Parameters=list(params),
        )

    def ctx(obj, expr):
        return ex(
            "EX_Context",
            ObjectExpression=obj,
            Offset=size(expr),
            PropertyType=0,
            RValuePointer=ptr(0),
            ContextExpression=expr,
        )

    body = [
        ex("EX_JumpIfNot", CodeOffset=0, BooleanExpression=call(valid, var(mesh_name)))
    ]
    for mesh_part, specification in geometry["assets"].items():
        if specification.get("follows_shoulder_pose"):
            variable = "Compact_" + mesh_part
            body.append(
                ex(
                    "EX_JumpIfNot",
                    CodeOffset=0,
                    BooleanExpression=call(valid, var(variable)),
                )
            )
            body.append(
                ctx(var(variable), call(master_pose, var(mesh_name), ex("EX_False")))
            )
    for variable in components:
        body.append(
            ex(
                "EX_JumpIfNot",
                CodeOffset=0,
                BooleanExpression=call(valid, var(variable)),
            )
        )
        body.append(
            ctx(
                var(variable),
                call(
                    set_,
                    ex("EX_IntZero"),
                    ctx(var(mesh_name), call(get, ex("EX_IntZero"))),
                ),
            )
        )
    if not corpse:
        body.append(
            ctx(
                var("NativeDroneSocket"),
                call(visible, call(creative, ex("EX_Self")), ex("EX_False")),
            )
        )
    end = sum(map(size, body))
    for e in body:
        if "CodeOffset" in e:
            e["CodeOffset"] = end
    body.extend(
        [ex("EX_Return", ReturnExpression=ex("EX_Nothing")), ex("EX_EndOfScript")]
    )
    begin = next(e for e in d["Exports"] if e["ObjectName"] == "ReceiveBeginPlay")
    fn = copy.deepcopy(begin)
    fn.update(
        ObjectName=name("CB_ShareSocketMaterial"),
        SerialSize=0,
        SerialOffset=0,
        SuperStruct=0,
        SuperIndex=0,
        LoadedProperties=[],
        ScriptBytecode=body,
        ScriptBytecodeSize=sum(map(size, body)),
        FunctionFlags="FUNC_Public, FUNC_BlueprintCallable",
    )
    assert base64.b64decode(fn["Extras"]) == b"\0" * 8
    fn["CreateBeforeSerializationDependencies"] = [
        cls_id,
        get,
        set_,
        valid,
        visible,
        creative,
        master_pose,
    ]
    fn["SerializationBeforeSerializationDependencies"] = []
    fn["CreateBeforeCreateDependencies"] = [cls_id]
    fn_id = append(fn)
    cls["FuncMap"].append([name("CB_ShareSocketMaterial"), fn_id])
    cls["Children"].insert(0, fn_id)
    cls["CreateBeforeSerializationDependencies"].append(fn_id)
    for key in ["ReceiveBeginPlay"]:
        wrapper = next(e for e in d["Exports"] if e["ObjectName"] == key)
        index = next(
            i
            for i, expr in enumerate(wrapper["ScriptBytecode"])
            if expr["$type"].split(".")[-1].split(",")[0] == "EX_Return"
        )
        wrapper["ScriptBytecode"].insert(index, call(fn_id, local=True))
        wrapper["ScriptBytecodeSize"] += 10
        wrapper["CreateBeforeSerializationDependencies"].append(fn_id)
