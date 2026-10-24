"""update backpack visuals when vanilla changes them"""

import copy
import hashlib
import json
import subprocess

from asset_io import HERE, es, prop
from blueprint import Blueprint
from game_assets import PAK, REPAK, extract
from kismet import kismet_size, op_type

CHARACTER = "Astro/Content/Character/DesignAstro"
SHARE = "CB_ShareSocketMaterial"
BIND = "BPM_BindVisualEvents"
MODE = "BPM_CreativeVisualsChanged"
STATE = "BPM_VisualGameState"
UNBIND = "BPM_UnbindVisualEvents"


def verify_sources():
    manifest = json.loads((HERE / "visual-events-native.json").read_text())
    exe = PAK.parents[2] / "Binaries/Win64/Astro-Win64-Shipping.exe"
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == manifest["exe_sha256"], (
        "Review visual event signatures after this game update."
    )
    for member, digest in manifest["assets"].items():
        current = subprocess.check_output([str(REPAK), "get", str(PAK), member])
        assert hashlib.sha256(current).hexdigest() == digest, (
            "Review changed native visuals: " + member
        )
        cached = HERE / "vanilla" / member
        if cached.exists():
            assert current == cached.read_bytes(), "Stale visual source: " + member


def hook_return(function, call):
    code = function["ScriptBytecode"]
    index = next(i for i, expr in enumerate(code) if op_type(expr) == "EX_Return")
    # put our call where the return was, so jumps to the return run it too
    # earlier instruction offsets stay the same
    assert not any(op_type(expr) == "EX_Return" for expr in code[:index])
    code.insert(index, call)
    function["ScriptBytecodeSize"] += kismet_size(call)


def patch_backpack(document):
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    statics = editor.imp("AstroStatics", astro)
    state_class = editor.imp("AstroGameState", astro)
    scene = editor.imp("SceneComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    different = editor.imp("NotEqual_ObjectObject", maths, "Function")
    get_state = editor.imp("GetGameState", statics, "Function")
    visibility = editor.imp("SetVisibility", scene, "Function")
    creative = editor.imp("IsCreativeMode", statics, "Function")
    field = copy.deepcopy(
        next(
            p for p in editor.cls["LoadedProperties"] if "FObjectProperty" in p["$type"]
        )
    )
    field.update(
        Name=editor.name(STATE),
        PropertyClass=state_class,
        PropertyFlags="CPF_Transient",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(field)
    cdo = es(document)["Default__" + editor.cls["ObjectName"]]
    cdo["Data"].append(prop(document, "Object", STATE, 0))
    editor.cls["CreateBeforeSerializationDependencies"].append(state_class)

    def assign_state(value):
        return editor.ex(
            "EX_LetObj",
            VariableExpression=editor.var(STATE),
            AssignmentExpression=value,
        )

    def delegate():
        expr = editor.ctx(
            editor.var(STATE),
            editor.ex(
                "EX_InstanceVariable",
                Variable=editor.ptr("OnCreativeModeEnabledChanged", state_class),
            ),
        )
        expr["RValuePointer"] = editor.ptr("OnCreativeModeEnabledChanged", state_class)
        return expr

    def handler():
        return editor.ex("EX_InstanceDelegate", FunctionName=editor.name(MODE))

    remove = editor.function(
        "BPM_RemoveVisualDelegate",
        [
            editor.guard(editor.call(valid, editor.var(STATE))),
            editor.ex(
                "EX_RemoveMulticastDelegate",
                Delegate=delegate(),
                DelegateToAdd=handler(),
            ),
        ],
    )
    unbind = editor.function(
        UNBIND,
        [
            editor.call(remove, local=True),
            assign_state(editor.ex("EX_NoObject")),
        ],
    )
    fid = len(document["Exports"]) + 1
    parameter = copy.deepcopy(
        next(p for p in editor.cls["LoadedProperties"] if "FBoolProperty" in p["$type"])
    )
    parameter.update(
        Name=editor.name("Creative"),
        PropertyFlags="CPF_Parm",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    mode_id = editor.function(
        MODE,
        [
            editor.guard(editor.call(valid, editor.var("NativeDroneSocket"))),
            editor.ctx(
                editor.var("NativeDroneSocket"),
                editor.call(
                    visibility,
                    editor.ex("EX_LocalVariable", Variable=editor.ptr("Creative", fid)),
                    editor.ex("EX_False"),
                ),
            ),
        ],
    )
    assert mode_id == fid
    function = document["Exports"][fid - 1]
    function["LoadedProperties"] = [parameter]
    function["CreateBeforeSerializationDependencies"] = [
        v for v in function["CreateBeforeSerializationDependencies"] if v != fid
    ]
    state = editor.call(get_state, editor.ex("EX_Self"))
    bind_id = editor.function(
        BIND,
        [
            editor.guard(editor.call(different, editor.var(STATE), state, math=True)),
            editor.call(unbind, local=True),
            editor.guard(editor.call(valid, state)),
            assign_state(state),
            editor.ex(
                "EX_AddMulticastDelegate",
                Delegate=delegate(),
                DelegateToAdd=handler(),
            ),
            editor.call(
                mode_id, editor.call(creative, editor.ex("EX_Self")), local=True
            ),
        ],
    )
    hook_return(es(document)["ReceiveBeginPlay"], editor.call(bind_id, local=True))
    # BackpackRail has no Blueprint EndPlay yet
    # copy the event signature from the current game
    native = extract(CHARACTER)
    source = es(native)["ReceiveEndPlay"]
    assert "ReceiveEndPlay" not in es(document)
    end = editor.function("ReceiveEndPlay", [editor.call(unbind, local=True)])
    event = document["Exports"][end - 1]
    event["FunctionFlags"] = source["FunctionFlags"]
    event["LoadedProperties"] = copy.deepcopy(source["LoadedProperties"])
    for parameter in event["LoadedProperties"]:
        editor.name(parameter["Name"])
        parameter["Enum"] = editor.copy_import(native, parameter["Enum"])
    parent = editor.copy_import(native, source["SuperStruct"])
    event["SuperStruct"] = event["SuperIndex"] = parent
    event["CreateBeforeSerializationDependencies"].extend(
        [parent, *(p["Enum"] for p in event["LoadedProperties"])]
    )


def character_asset():
    verify_sources()
    document = extract(CHARACTER)
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    system = editor.imp("KismetSystemLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    package = editor.imp("/Game/Items/BackpackRail", kind="Package")
    backpack_class = editor.imp(
        "BackpackRail_C", package, "BlueprintGeneratedClass", "/Script/Engine"
    )
    get_backpack = next(
        i + 1
        for i, e in enumerate(document["Exports"])
        if e["ObjectName"] == "Get Backpack"
    )
    helper_name = "BPM_RefreshBackpackMaterial"
    fid = len(document["Exports"]) + 1
    schema = copy.deepcopy(
        next(
            p
            for p in es(document)["SetCustomizationMaterials"]["LoadedProperties"]
            if p["Name"] == "CallFunc_Get_Backpack_Backpack"
        )
    )
    schema.update(
        Name=editor.name("Backpack"),
        PropertyFlags="CPF_None",
        PropertyClass=backpack_class,
    )
    local = editor.ex("EX_LocalVariable", Variable=editor.ptr("Backpack", fid))
    # Get Backpack writes its result into this local variable
    helper = editor.function(
        helper_name,
        [
            editor.call(get_backpack, local, local=True),
            editor.guard(editor.call(valid, local)),
            editor.ctx(
                local,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(SHARE),
                    Parameters=[],
                ),
            ),
            # also catches backpacks created after the first appearance update
            editor.ctx(
                local,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(BIND),
                    Parameters=[],
                ),
            ),
        ],
    )
    assert helper == fid
    function = document["Exports"][fid - 1]
    function["LoadedProperties"] = [schema]
    function["CreateBeforeSerializationDependencies"] = sorted(
        (set(function["CreateBeforeSerializationDependencies"]) | {backpack_class})
        - {fid}
    )
    material = es(document)["SetCustomizationMaterials"]
    hook_return(material, editor.call(helper, local=True))
    material["CreateBeforeSerializationDependencies"].append(helper)
    return document
