"""save the printer tooltip setting on this computer"""

import copy
import hashlib
import json
import uuid

from asset_io import HERE, es, prop
from blueprint import Blueprint
from game_assets import PAK, extract
from kismet import kismet_size, op_type
from settings import PKG

ASSET = "PrinterPreferences"
FIELD = "TooltipHidden"
SLOT = "BackpackProMax_PrinterPreferences"
EXTENSION = 2  # Astroneer's generic .sav type; worlds use type 1 (.savegame).
LOADED = "BPM_PrinterPreferenceLoaded"
LOAD = "BPM_LoadPrinterPreference"
SAVE = "BPM_SavePrinterPreference"


def preferences_asset():
    manifest = json.loads((HERE / "printer-preferences-native.json").read_text())
    exe = PAK.parents[2] / "Binaries/Win64/Astro-Win64-Shipping.exe"
    assert hashlib.sha256(exe.read_bytes()).hexdigest() == manifest["exe_sha256"], (
        "Game changed: review the printer save API before rebuilding."
    )
    # reuse the game's SaveGame format; we only need one bool
    d = extract(
        "Astro/Content/ControlPanels/ModularControlPanel/PanelParts/ControlPanelButtonBase"
    )
    cls = copy.deepcopy(next(e for e in d["Exports"] if "ClassExport" in e["$type"]))
    cdo = copy.deepcopy(d["Exports"][cls["ClassDefaultObject"] - 1])
    backpack = extract("Astro/Content/Items/BackpackRail")
    backpack_class = next(e for e in backpack["Exports"] if "ClassExport" in e["$type"])
    field = copy.deepcopy(
        next(
            p
            for p in backpack_class["LoadedProperties"]
            if "FBoolProperty" in p["$type"]
        )
    )
    d["Imports"] = []
    d["Exports"] = [cls, cdo]
    d["DependsMap"] = [[], []]
    editor = Blueprint(d)
    core = editor.imp("/Script/CoreUObject", kind="Package")
    engine = editor.imp("/Script/Engine", kind="Package")
    obj = editor.imp("Object", core)
    generated = editor.imp("BlueprintGeneratedClass", engine)
    generated_default = editor.imp(
        "Default__BlueprintGeneratedClass",
        engine,
        "BlueprintGeneratedClass",
        "/Script/Engine",
    )
    parent = editor.imp("SaveGame", engine)
    parent_default = editor.imp(
        "Default__SaveGame", engine, "SaveGame", "/Script/Engine"
    )
    field.update(Name=editor.name(FIELD), PropertyFlags="CPF_SaveGame")
    cls.update(
        ObjectName=editor.name(ASSET + "_C"),
        OuterIndex=0,
        ClassIndex=generated,
        SuperIndex=parent,
        TemplateIndex=generated_default,
        SuperStruct=parent,
        ClassWithin=obj,
        ClassDefaultObject=2,
        ClassFlags="CLASS_Parsed, CLASS_ReplicationDataIsSetUp, CLASS_CompiledFromBlueprint",
        ClassGeneratedBy=0,
        FuncMap=[],
        Children=[],
        Interfaces=[],
        LoadedProperties=[field],
        ScriptBytecode=[],
        ScriptBytecodeSize=0,
        ScriptBytecodeRaw=None,
        Data=[],
        Extras="",
        SerialSize=0,
        SerialOffset=0,
        SerializationBeforeSerializationDependencies=[parent, parent_default],
        CreateBeforeSerializationDependencies=[],
        SerializationBeforeCreateDependencies=[generated, generated_default],
        CreateBeforeCreateDependencies=[parent],
    )
    cdo.update(
        ObjectName=editor.name("Default__" + ASSET + "_C"),
        OuterIndex=0,
        ClassIndex=1,
        SuperIndex=0,
        TemplateIndex=parent_default,
        Data=[prop(d, "Bool", FIELD, False)],
        Extras="",
        SerialSize=0,
        SerialOffset=0,
        SerializationBeforeSerializationDependencies=[],
        CreateBeforeSerializationDependencies=[],
        SerializationBeforeCreateDependencies=[1, parent_default],
        CreateBeforeCreateDependencies=[],
    )
    d["PackageGuid"] = (
        "{" + str(uuid.uuid5(uuid.NAMESPACE_DNS, PKG + ASSET)).upper() + "}"
    )
    return d


def _locals(editor, fid, fields):
    function = editor.d["Exports"][fid - 1]
    function["LoadedProperties"] = fields
    deps = function["CreateBeforeSerializationDependencies"]
    for field in fields:
        if field.get("PropertyClass"):
            deps.append(field["PropertyClass"])
    function["CreateBeforeSerializationDependencies"] = sorted(set(deps) - {fid})


def patch_preferences(document, hidden, getter_name, toggle_name):
    editor = Blueprint(document)
    editor.bool_field(LOADED, False)
    engine = editor.imp("/Script/Engine", kind="Package")
    gameplay = editor.imp("GameplayStatics", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    not_bool = editor.imp("Not_PreBool", maths, "Function")
    valid = editor.imp("IsValid", system, "Function")
    load = editor.imp("LoadGameFromSlot", gameplay, "Function")
    create = editor.imp("CreateSaveGameObject", gameplay, "Function")
    save = editor.imp("SaveGameToSlot", gameplay, "Function")
    package = editor.imp(PKG + ASSET, kind="Package")
    save_class = editor.imp(
        ASSET + "_C", package, "BlueprintGeneratedClass", "/Script/Engine"
    )
    local_control = next(
        -i - 1
        for i, entry in enumerate(document["Imports"])
        if entry["ObjectName"] == "IsLocallyControlled"
    )
    obj_field = copy.deepcopy(
        next(
            p for p in editor.cls["LoadedProperties"] if "FObjectProperty" in p["$type"]
        )
    )
    obj_field.update(
        Name=editor.name("Preference"),
        PropertyClass=save_class,
        PropertyFlags="CPF_None",
        RepNotifyFunc="None",
        RepIndex=0,
    )
    # Astroneer adds an int32 OutFileSize output to SaveGameToSlot
    int_field = copy.deepcopy(
        next(
            p
            for e in document["Exports"]
            for p in e.get("LoadedProperties", [])
            if p.get("SerializedType") == "IntProperty"
        )
    )
    int_field.update(Name=editor.name("FileSize"), PropertyFlags="CPF_None")
    slot = lambda: editor.ex("EX_StringConst", Value=SLOT)
    extension = lambda: editor.ex("EX_ByteConst", Value=EXTENSION)
    index = lambda: editor.ex("EX_IntZero")

    def local(name, fid):
        return editor.ex("EX_LocalVariable", Variable=editor.ptr(name, fid))

    def assign_obj(target, value):
        return editor.ex(
            "EX_LetObj", VariableExpression=target, AssignmentExpression=value
        )

    def pref_value(target):
        return editor.ctx(
            target,
            editor.ex("EX_InstanceVariable", Variable=editor.ptr(FIELD, save_class)),
        )

    fid = len(document["Exports"]) + 1
    preference = local("Preference", fid)
    load_id = editor.function(
        LOAD,
        [
            editor.guard(editor.call(local_control)),
            editor.guard(editor.call(not_bool, editor.var(LOADED), math=True)),
            editor.assign_bool(LOADED, editor.ex("EX_True")),
            editor.assign_bool(hidden, editor.ex("EX_False")),
            assign_obj(
                preference,
                editor.ex(
                    "EX_DynamicCast",
                    ClassPtr=save_class,
                    Target=editor.call(load, slot(), extension(), index(), math=True),
                ),
            ),
            editor.guard(editor.call(valid, preference)),
            editor.assign_bool(hidden, pref_value(preference)),
        ],
    )
    assert load_id == fid
    _locals(editor, fid, [copy.deepcopy(obj_field)])
    fid = len(document["Exports"]) + 1
    preference = local("Preference", fid)
    save_id = editor.function(
        SAVE,
        [
            editor.guard(editor.call(local_control)),
            assign_obj(
                preference,
                editor.call(
                    create, editor.ex("EX_ObjectConst", Value=save_class), math=True
                ),
            ),
            editor.guard(editor.call(valid, preference)),
            editor.ex(
                "EX_LetBool",
                VariableExpression=pref_value(preference),
                AssignmentExpression=editor.var(hidden),
            ),
            editor.call(
                save,
                preference,
                slot(),
                local("FileSize", fid),
                extension(),
                index(),
                math=True,
            ),
        ],
    )
    assert save_id == fid
    _locals(editor, fid, [copy.deepcopy(obj_field), int_field])
    getter = es(document)[getter_name]
    getter["ScriptBytecode"].insert(0, editor.call(load_id, local=True))
    getter["ScriptBytecodeSize"] = sum(map(kismet_size, getter["ScriptBytecode"]))
    getter["CreateBeforeSerializationDependencies"].append(load_id)
    getter["FunctionFlags"] = getter["FunctionFlags"].replace(", FUNC_Const", "")
    toggle = es(document)[toggle_name]
    body = toggle["ScriptBytecode"][:-2]
    assert op_type(body[0]) == "EX_JumpIfNot"
    body.insert(1, editor.call(load_id, local=True))
    body.append(editor.call(save_id, local=True))
    body[0]["CodeOffset"] = sum(map(kismet_size, body))
    toggle["ScriptBytecode"] = body + toggle["ScriptBytecode"][-2:]
    toggle["ScriptBytecodeSize"] = sum(map(kismet_size, toggle["ScriptBytecode"]))
    toggle["CreateBeforeSerializationDependencies"] += [load_id, save_id]
