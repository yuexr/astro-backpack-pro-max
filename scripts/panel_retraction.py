"""Optional mission-log retraction fix and native panel source guards."""

import copy
import hashlib
import json
import subprocess

from asset_io import HERE, es
from blueprint import Blueprint
from game_assets import PAK, REPAK
from kismet import kismet_size, op_type

MISSION = "Astro/Content/ControlPanels/Missions/MissionsControlPanel_Backpack"
STATE_EVENT = "BndEvt__CrackableActorComponent_K2Node_ComponentBoundEvent_1_OnCrackedStateChanged__DelegateSignature"
FULL_EVENT = "BndEvt__CrackableActorComponent_K2Node_ComponentBoundEvent_0_OnCrackedStateChanged__DelegateSignature"
PREFIX = "BPM_Retraction"


def verify_native_sources():
    """Check the installed game files before applying the patch."""
    manifest = json.loads((HERE / "panel-retraction-native.json").read_text())
    exe = PAK.parents[2] / "Binaries/Win64/Astro-Win64-Shipping.exe"
    assert exe.is_file(), "Cannot verify native panel code: game executable missing"
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == manifest["exe_sha256"], (
        "Native game code changed. Review the panel workaround, or disable "
        "PANEL_RETRACTION_FIX before rebuilding."
    )
    for member, expected in manifest["assets"].items():
        actual = subprocess.check_output([str(REPAK), "get", str(PAK), member])
        assert hashlib.sha256(actual).hexdigest() == expected, (
            "Native panel asset changed: "
            + member
            + ". Review the optional workaround."
        )
        cached = HERE / "vanilla" / member
        if cached.exists():
            assert cached.read_bytes() == actual, "Stale native asset cache: " + member


def _editor(document):
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    control = editor.imp("ControlPanel", astro)
    crack = editor.imp("CrackableActorComponent", astro)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    imports = {
        "valid": editor.imp("IsValid", system, "Function"),
        "closed": editor.imp("GetFullyClosed", crack, "Function"),
        "not": editor.imp("Not_PreBool", maths, "Function"),
        "control": control,
    }
    return editor, imports


def _parameter_function(editor, name, make):
    fid = len(editor.d["Exports"]) + 1
    param = copy.deepcopy(
        next(
            p
            for p in es(editor.d)[STATE_EVENT]["LoadedProperties"]
            if p["Name"] == "bIsCracked"
        )
    )
    param["Name"] = editor.name("Opened")
    opened = editor.ex("EX_LocalVariable", Variable=editor.ptr("Opened", fid))
    assert editor.function(name, make(opened)) == fid
    fn = editor.d["Exports"][fid - 1]
    fn["LoadedProperties"] = [param]
    fn["CreateBeforeSerializationDependencies"] = [
        d for d in fn["CreateBeforeSerializationDependencies"] if d != fid
    ]
    return fid


def _hook(editor, event, fid):
    fn = es(editor.d)[event]
    owner = editor.d["Exports"].index(fn) + 1
    expr = editor.call(
        fid,
        editor.ex("EX_LocalVariable", Variable=editor.ptr("bIsCracked", owner)),
        local=True,
    )
    code = fn["ScriptBytecode"]
    index = next(i for i, x in enumerate(code) if op_type(x) == "EX_Return")
    code.insert(index, expr)
    fn["ScriptBytecodeSize"] += kismet_size(expr)
    fn["CreateBeforeSerializationDependencies"].append(fid)


def without_hooks(document):
    """Remove mission-log hooks for comparison with the native asset."""
    result = copy.deepcopy(document)
    for fn in result["Exports"]:
        if fn["ObjectName"] not in [STATE_EVENT, FULL_EVENT]:
            continue
        kept = []
        for expr in fn["ScriptBytecode"]:
            node = expr.get("StackNode", 0)
            if (
                op_type(expr) == "EX_LocalFinalFunction"
                and node > 0
                and result["Exports"][node - 1]["ObjectName"].startswith(PREFIX)
            ):
                fn["ScriptBytecodeSize"] -= kismet_size(expr)
            else:
                kept.append(expr)
        fn["ScriptBytecode"] = kept
    return result


def _mission_target(editor, catalog_source):
    # the catalog subtracts its hover offset before saving the closed position
    # the mission log skips that step; copy it without changing rotation or scale
    source = es(catalog_source)["ExecuteUbergraph_BackpackCatalog"]
    native = source["ScriptBytecode"][226:230]
    assert len(native) == 4 and op_type(native[-1]) == "EX_Context"
    fid = len(editor.d["Exports"]) + 1
    code = copy.deepcopy(native)
    old_owner = catalog_source["Exports"].index(source) + 1
    editor.copy_names(catalog_source, code)

    def remap(value):
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key in ["StackNode", "ResolvedOwner"] and isinstance(child, int):
                    if key == "ResolvedOwner" and child == old_owner:
                        value[key] = fid
                    elif child < 0:
                        value[key] = editor.copy_import(catalog_source, child)
                else:
                    remap(child)
        elif isinstance(value, list):
            for child in value:
                remap(child)

    remap(code)
    fn = editor.function(PREFIX + "MissionTarget", code)
    assert fn == fid
    names = {
        "CallFunc_GetClosedRelativeTransform_ReturnValue",
        "CallFunc_BreakTransform_Location",
        "CallFunc_BreakTransform_Rotation",
        "CallFunc_BreakTransform_Scale",
        "CallFunc_MakeTransform_ReturnValue",
    }
    fields = copy.deepcopy(
        [p for p in source["LoadedProperties"] if p["Name"] in names]
    )
    for field in fields:
        editor.copy_names(catalog_source, field)
        for key in ["Struct", "PropertyClass"]:
            if isinstance(field.get(key), int) and field[key] < 0:
                field[key] = editor.copy_import(catalog_source, field[key])
    assert len(fields) == 5
    for field in fields:
        for key in ["Struct", "PropertyClass"]:
            dependency = field.get(key)
            if isinstance(dependency, int) and dependency:
                editor.d["Exports"][fid - 1][
                    "CreateBeforeSerializationDependencies"
                ].append(dependency)
    editor.d["Exports"][fid - 1]["LoadedProperties"] = fields
    editor.d["Exports"][fid - 1]["CreateBeforeSerializationDependencies"] = [
        d
        for d in editor.d["Exports"][fid - 1]["CreateBeforeSerializationDependencies"]
        if d != fid
    ]
    return fid


def patch_mission(document, catalog_source):
    editor, imp = _editor(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    timeline = editor.imp("TimelineComponent", engine)
    stop = editor.imp("Stop", timeline, "Function")
    position = editor.imp("SetPlaybackPosition", timeline, "Function")
    component = editor.ex(
        "EX_InstanceVariable",
        Variable=editor.ptr("CrackableActorComponent", imp["control"]),
    )
    slide = editor.var("MissionLogSlide")
    target = _mission_target(editor, catalog_source)
    closing = _parameter_function(
        editor,
        PREFIX + "MissionClosing",
        lambda opened: [
            editor.guard(editor.call(imp["not"], opened, math=True)),
            editor.guard(editor.call(imp["valid"], component)),
            editor.call(target, local=True),
        ],
    )
    closed = _parameter_function(
        editor,
        PREFIX + "MissionClosed",
        lambda opened: [
            editor.guard(editor.call(imp["not"], opened, math=True)),
            editor.guard(editor.call(imp["valid"], component)),
            editor.guard(editor.ctx(component, editor.call(imp["closed"]))),
            editor.call(target, local=True),
            editor.guard(editor.call(imp["valid"], slide)),
            editor.assign_bool("SlideOut", editor.ex("EX_False")),
            editor.ctx(slide, editor.call(stop)),
            # reset the slide to its starting position without firing its events
            # doing this twice is fine; hover still works
            editor.ctx(
                slide,
                editor.call(
                    position,
                    editor.ex("EX_FloatConst", Value=0.0),
                    editor.ex("EX_False"),
                    editor.ex("EX_True"),
                ),
            ),
        ],
    )
    _hook(editor, STATE_EVENT, closing)
    _hook(editor, FULL_EVENT, closed)
