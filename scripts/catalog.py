"""let the catalog finish closing, then freeze its pose"""

import copy

from asset_io import es
from blueprint import Blueprint
from game_assets import extract
from kismet import kismet_size, op_type

PENDING = "BPM_CatalogPosePending"
STARTED = "BPM_CatalogPoseStarted"
OVERRIDE = "BPM_CatalogTickOverride"
SAVED = "BPM_CatalogSavedTickOption"
SAVED_TICK = "BPM_CatalogSavedTickEnabled"
TRY = "BPM_TrySetCatalogClosedPose"
FREEZE = "BPM_FreezeCatalogClosedPose"


def patch_catalog_startup():
    document = extract("Astro/Content/Items/Catalog/BackpackCatalog")
    editor = Blueprint(document)
    for field in [PENDING, STARTED, OVERRIDE, SAVED_TICK]:
        editor.bool_field(field)
    byte = copy.deepcopy(
        next(p for p in editor.cls["LoadedProperties"] if "FByteProperty" in p["$type"])
    )
    byte.update(
        Name=editor.name(SAVED),
        Enum=0,
        PropertyFlags="CPF_None",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(byte)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    control = editor.imp("ControlPanel", astro)
    crack = editor.imp("CrackableActorComponent", astro)
    skel = editor.imp("SkeletalMeshComponent", engine)
    skinned = editor.imp("SkinnedMeshComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    actor_component = editor.imp("ActorComponent", engine)
    valid = editor.imp("IsValid", system, "Function")
    negate = editor.imp("Not_PreBool", maths, "Function")
    closed = editor.imp("GetFullyClosed", crack, "Function")
    set_timer = editor.imp("K2_SetTimer", system, "Function")
    clear_timer = editor.imp("K2_ClearTimer", system, "Function")
    tick = editor.imp("SetComponentTickEnabled", actor_component, "Function")
    tick_enabled = editor.imp("IsComponentTickEnabled", actor_component, "Function")
    mesh = editor.ex(
        "EX_InstanceVariable", Variable=editor.ptr("SkeletalMesh", control)
    )
    component = editor.ex(
        "EX_InstanceVariable", Variable=editor.ptr("CrackableActorComponent", control)
    )
    option = editor.ctx(
        mesh,
        editor.ex(
            "EX_InstanceVariable",
            Variable=editor.ptr("VisibilityBasedAnimTickOption", skinned),
        ),
    )

    def let(variable, value, field, owner):
        return editor.ex(
            "EX_Let",
            Value=editor.ptr(field, owner),
            Variable=variable,
            Expression=value,
        )

    def timer_clear(callback):
        return editor.call(
            clear_timer,
            editor.ex("EX_Self"),
            editor.ex("EX_StringConst", Value=editor.name(callback)),
        )

    def timer(callback, seconds):
        # one-shot only; these callbacks never restart themselves
        return editor.call(
            set_timer,
            editor.ex("EX_Self"),
            editor.ex("EX_StringConst", Value=editor.name(callback)),
            editor.ex("EX_FloatConst", Value=seconds),
            editor.ex("EX_False"),
            editor.ex("EX_FloatConst", Value=0.0),
            editor.ex("EX_FloatConst", Value=0.0),
        )

    def freeze(enabled):
        return editor.ex(
            "EX_LetBool",
            VariableExpression=editor.ctx(
                mesh,
                editor.ex(
                    "EX_InstanceVariable",
                    Variable=editor.ptr("bNoSkeletonUpdate", skel),
                ),
            ),
            AssignmentExpression=editor.ex("EX_True" if enabled else "EX_False"),
        )

    restore = editor.function(
        "BPM_RestoreCatalogTickOption",
        [
            editor.guard(editor.var(OVERRIDE)),
            editor.guard(editor.call(valid, mesh)),
            let(option, editor.var(SAVED), "VisibilityBasedAnimTickOption", skinned),
            editor.ctx(mesh, editor.call(tick, editor.var(SAVED_TICK))),
            editor.assign_bool(OVERRIDE, editor.ex("EX_False")),
        ],
    )
    capture = editor.function(
        "BPM_CaptureCatalogTickOption",
        [
            editor.guard(editor.call(negate, editor.var(OVERRIDE), math=True)),
            editor.guard(editor.call(valid, mesh)),
            let(editor.var(SAVED), option, SAVED, editor.cid),
            editor.assign_bool(SAVED_TICK, editor.ctx(mesh, editor.call(tick_enabled))),
            editor.assign_bool(OVERRIDE, editor.ex("EX_True")),
        ],
    )
    keep = editor.function(
        "BPM_KeepCatalogClosedPoseUpdating",
        [
            editor.guard(editor.var(PENDING)),
            editor.guard(editor.var(STARTED)),
            editor.guard(editor.call(valid, mesh)),
            editor.assign_bool("ExtendTop", editor.ex("EX_True")),
            editor.assign_bool("ExtendPanel", editor.ex("EX_False")),
            # the pose still needs to update when the catalog is off-screen
            let(
                option,
                editor.ex("EX_ByteConst", Value=0),
                "VisibilityBasedAnimTickOption",
                skinned,
            ),
            freeze(False),
            editor.ctx(mesh, editor.call(tick, editor.ex("EX_True"))),
        ],
    )
    editor.function(
        FREEZE,
        [
            timer_clear(TRY),
            timer_clear(FREEZE),
            editor.assign_bool(PENDING, editor.ex("EX_False")),
            editor.assign_bool(STARTED, editor.ex("EX_False")),
            editor.call(restore, local=True),
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.guard(editor.call(valid, mesh)),
            freeze(True),
        ],
    )
    attempt = editor.function(
        TRY,
        [
            editor.guard(editor.var(PENDING)),
            editor.guard(editor.call(valid, mesh)),
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.assign_bool(STARTED, editor.ex("EX_True")),
            editor.call(capture, local=True),
            editor.call(keep, local=True),
            timer_clear(TRY),
            timer(FREEZE, 1.0),
        ],
    )
    start = editor.function(
        "BPM_StartCatalogClosedPose",
        [
            editor.assign_bool(PENDING, editor.ex("EX_True")),
            editor.assign_bool(STARTED, editor.ex("EX_False")),
            # this event can arrive before vanilla finishes changing state
            # try once next frame; the fully-closed event can try again later
            timer(TRY, 0.01),
            editor.call(attempt, local=True),
        ],
    )
    fid = len(document["Exports"]) + 1
    param = copy.deepcopy(
        next(
            p
            for p in es(document)[
                "BndEvt__CrackableActorComponent_K2Node_ComponentBoundEvent_1_OnCrackedStateChanged__DelegateSignature"
            ]["LoadedProperties"]
            if p["Name"] == "bIsCracked"
        )
    )
    param["Name"] = editor.name("Opened")
    cancel = editor.function(
        "BPM_ReleaseCatalogClosedPoseIfOpened",
        [
            editor.guard(
                editor.ex("EX_LocalVariable", Variable=editor.ptr("Opened", fid))
            ),
            editor.assign_bool(PENDING, editor.ex("EX_False")),
            editor.assign_bool(STARTED, editor.ex("EX_False")),
            timer_clear(TRY),
            timer_clear(FREEZE),
            editor.call(restore, local=True),
        ],
    )
    fn = document["Exports"][cancel - 1]
    fn["LoadedProperties"] = [param]
    fn["CreateBeforeSerializationDependencies"] = [
        v for v in fn["CreateBeforeSerializationDependencies"] if v != cancel
    ]

    def hook(name, call, before=False):
        fn = es(document)[name]
        code = fn["ScriptBytecode"]
        index = next(i for i, expr in enumerate(code) if op_type(expr) == "EX_Return")
        code.insert(0 if before else index, call)
        fn["ScriptBytecodeSize"] += kismet_size(call)
        fn["CreateBeforeSerializationDependencies"].append(call["StackNode"])

    hook("ReceiveBeginPlay", editor.call(start, local=True))
    hook(
        "BndEvt__CrackableActorComponent_K2Node_ComponentBoundEvent_0_OnCrackedStateChanged__DelegateSignature",
        editor.call(keep, local=True),
    )
    opened = "BndEvt__CrackableActorComponent_K2Node_ComponentBoundEvent_1_OnCrackedStateChanged__DelegateSignature"
    owner = document["Exports"].index(es(document)[opened]) + 1
    hook(
        opened,
        editor.call(
            cancel,
            editor.ex("EX_LocalVariable", Variable=editor.ptr("bIsCracked", owner)),
            local=True,
        ),
        before=True,
    )
    return document
