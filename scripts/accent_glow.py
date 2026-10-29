"""Isolated lower-accent glow; refresh only through existing appearance events."""

import copy
import json

from asset_io import es, prop
from blueprint import Blueprint
from game_assets import extract
from kismet import kismet_size
from settings import LUXE_GLOW, OUT, PKG
from visual_events import hook_return

REFRESH = "BPM_RefreshAccentGlow"
MATERIAL = "BPM_AccentGlowMaterial"


def patch(document, corpse=False):
    if not LUXE_GLOW:
        return
    geometry = json.loads((OUT / "geometry-report.json").read_text())
    label = next(
        n
        for n, v in geometry["assets"].items()
        if v.get("fixed_material") == PKG + "LowerBatteryGlow"
    )
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    core = editor.imp("/Script/CoreUObject", kind="Package")
    interface = editor.imp("MaterialInterface", engine)
    mid = editor.imp("MaterialInstanceDynamic", engine)
    mic = editor.imp("MaterialInstanceConstant", engine)
    primitive = editor.imp("PrimitiveComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    strings = editor.imp("KismetStringLibrary", engine)
    linear = editor.imp("LinearColor", core, "ScriptStruct")
    valid = editor.imp("IsValid", system, "Function")
    get = editor.imp("GetMaterial", primitive, "Function")
    set_material = editor.imp("SetMaterial", primitive, "Function")
    create = editor.imp("CreateDynamicMaterialInstance", primitive, "Function")
    get_dyn = editor.imp("K2_GetVectorParameterValue", mid, "Function")
    get_const = editor.imp("K2_GetVectorParameterValue", mic, "Function")
    set_colour = editor.imp("SetVectorParameterValue", mid, "Function")
    multiply = editor.imp("Multiply_LinearColorFloat", maths, "Function")
    either = editor.imp("BooleanOR", maths, "Function")
    negate = editor.imp("Not_PreBool", maths, "Function")
    base = editor.imp("GetBaseMaterial", interface, "Function")
    get_name = editor.imp("GetObjectName", system, "Function")
    unequal = editor.imp("NotEqual_StriStri", strings, "Function")
    package = editor.imp(PKG + "LowerBatteryGlow", kind="Package")
    source_asset = editor.imp(
        "LowerBatteryGlow", package, "MaterialInstanceConstant", "/Script/Engine"
    )
    schema = copy.deepcopy(
        next(
            p for p in editor.cls["LoadedProperties"] if "FObjectProperty" in p["$type"]
        )
    )
    field = copy.deepcopy(schema)
    field.update(
        Name=editor.name(MATERIAL), PropertyClass=mid, PropertyFlags="CPF_Transient"
    )
    editor.cls["LoadedProperties"].append(field)
    editor.cls["CreateBeforeSerializationDependencies"].append(mid)
    cdo = next(
        e
        for e in document["Exports"]
        if e["ObjectName"] == "Default__" + editor.cls["ObjectName"]
    )
    cdo["Data"].append(prop(document, "Object", MATERIAL, 0))
    fid = len(document["Exports"]) + 1
    local = lambda n: editor.ex("EX_LocalVariable", Variable=editor.ptr(n, fid))
    nm = lambda n: editor.ex("EX_NameConst", Value=editor.name(n))
    cast = lambda cls: editor.ex("EX_DynamicCast", ClassPtr=cls, Target=local("Source"))
    assign_obj = lambda dst, value: editor.ex(
        "EX_LetObj", VariableExpression=dst, AssignmentExpression=value
    )
    target = editor.var("Compact_" + label)
    mesh = editor.var("Backpack_mk2" if corpse else "backpack_mk2")
    body = []
    labels = {}
    jumps = []

    def mark(label):
        labels[label] = len(body)

    def jump_if_not(condition, destination):
        jumps.append((len(body), destination))
        body.append(editor.guard(condition))

    def jump(destination):
        jumps.append((len(body), destination))
        body.append(editor.ex("EX_Jump", CodeOffset=0))

    jump_if_not(editor.call(valid, target), "end")
    jump_if_not(editor.call(valid, mesh), "end")
    body.append(
        assign_obj(
            local("Source"), editor.ctx(mesh, editor.call(get, editor.ex("EX_IntZero")))
        )
    )
    jump_if_not(
        editor.call(
            either, editor.call(valid, cast(mid)), editor.call(valid, cast(mic))
        ),
        "end",
    )
    # The one shipped rainbow shader has no PrimaryColor. Keep its native
    # material rather than mistaking an absent colour parameter for black.
    base_name = editor.call(get_name, editor.ctx(local("Source"), editor.call(base)))
    jump_if_not(
        editor.call(
            unequal, base_name, editor.ex("EX_StringConst", Value="M_suits_rainbow")
        ),
        "native",
    )
    jump_if_not(editor.call(negate, editor.call(valid, editor.var(MATERIAL))), "ready")
    body.append(
        assign_obj(
            editor.var(MATERIAL),
            editor.ctx(
                target,
                editor.call(
                    create,
                    editor.ex("EX_IntZero"),
                    editor.ex("EX_ObjectConst", Value=source_asset),
                    nm("None"),
                ),
            ),
        )
    )
    mark("ready")
    jump_if_not(editor.call(valid, editor.var(MATERIAL)), "end")
    body.append(
        editor.ctx(
            target,
            editor.call(set_material, editor.ex("EX_IntZero"), editor.var(MATERIAL)),
        )
    )
    jump_if_not(editor.call(valid, cast(mid)), "constant")
    body.append(
        editor.ex(
            "EX_Let",
            Value=editor.ptr("Tint", fid),
            Variable=local("Tint"),
            Expression=editor.ctx(cast(mid), editor.call(get_dyn, nm("PrimaryColor"))),
        )
    )
    jump("apply")
    mark("constant")
    body.append(
        editor.ex(
            "EX_Let",
            Value=editor.ptr("Tint", fid),
            Variable=local("Tint"),
            Expression=editor.ctx(
                cast(mic), editor.call(get_const, nm("PrimaryColor"))
            ),
        )
    )
    mark("apply")
    body.append(
        editor.ctx(
            editor.var(MATERIAL),
            editor.call(set_colour, nm("Color Tint"), local("Tint")),
        )
    )
    body.append(
        editor.ctx(
            editor.var(MATERIAL),
            editor.call(
                set_colour,
                nm("Emissive Tint"),
                editor.call(
                    multiply, local("Tint"), editor.ex("EX_FloatConst", Value=1.1)
                ),
            ),
        )
    )
    jump("end")
    mark("native")
    body.append(
        editor.ctx(
            target, editor.call(set_material, editor.ex("EX_IntZero"), local("Source"))
        )
    )
    mark("end")
    function_id = editor.function(REFRESH, body)
    assert function_id == fid
    function = document["Exports"][fid - 1]
    starts = []
    offset = 0
    for instruction in function["ScriptBytecode"]:
        starts.append(offset)
        offset += kismet_size(instruction)
    for index, destination in jumps:
        function["ScriptBytecode"][index]["CodeOffset"] = starts[labels[destination]]
    source_field = copy.deepcopy(schema)
    source_field.update(
        Name=editor.name("Source"), PropertyClass=interface, PropertyFlags="CPF_None"
    )
    character = extract("Astro/Content/Character/DesignAstro")
    tint_field = copy.deepcopy(
        next(
            p
            for e in character["Exports"]
            for p in e.get("LoadedProperties", [])
            if p.get("Struct", 0) < 0
            and character["Imports"][-p["Struct"] - 1]["ObjectName"] == "LinearColor"
        )
    )
    tint_field.update(Name=editor.name("Tint"), Struct=linear, PropertyFlags="CPF_None")
    function["LoadedProperties"] = [source_field, tint_field]
    function["CreateBeforeSerializationDependencies"] = sorted(
        set(function["CreateBeforeSerializationDependencies"])
        | {interface, mid, mic, linear, source_asset}
    )
    share = es(document)["CB_ShareSocketMaterial"]
    hook_return(share, editor.call(fid, local=True))
    end = share["ScriptBytecodeSize"] - 3
    for instruction in share["ScriptBytecode"]:
        if "CodeOffset" in instruction:
            instruction["CodeOffset"] = end
    share["CreateBeforeSerializationDependencies"].append(fid)
