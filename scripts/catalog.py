"""One bounded catalog close flow, built directly from the native asset.

Start after native setup, request the native closed pose, and wait for its
animation-end notification. Opening or the deadline releases temporary tick
settings. There is no timer between closes or after successful initialization.
"""

import copy

from asset_io import es, prop
from blueprint import Blueprint
from game_assets import extract
from kismet import kismet_size, op_type
from panel_retraction import FULL_EVENT, STATE_EVENT

OPEN_EVENTS = (
    "SpindleTransition__CloseTop__EventFunc",
    "SpindleTransition__PopOutBottom__EventFunc",
)


CATALOG = "Astro/Content/Items/Catalog/BackpackCatalog"
PENDING = "BPM_CatalogPosePending"
OVERRIDE = "BPM_CatalogTickOverride"
SAVED = "BPM_CatalogSavedTickOption"
SAVED_TICK = "BPM_CatalogSavedTickEnabled"
SAVED_ACTOR_TICK = "BPM_CatalogSavedActorTickEnabled"
INITIALIZED = "BPM_CatalogStartupSettled"
EVALUATED = "BPM_CatalogClosedAnimationInstance"
START = "BPM_StartCatalogClosedPose"
DEFER = "BPM_BeginCatalogAfterNativeSetup"
TRY = "BPM_TrySetCatalogClosedPose"
STOP = "BPM_StopCatalogPoseCorrection"
FINISH = "BPM_FinalizeCatalogAnimation"
QUEUE_FINISH = "BPM_QueueCatalogAnimationFinish"
COMPLETE = "BPM_CatalogClosedAnimationFinished"
OPENED = "BPM_ReleaseCatalogClosedPoseIfOpened"
CLOSED = "BPM_CatalogClosed"
KEEP = "BPM_KeepCatalogClosedPoseUpdating"
READY_REQUEST = "BPM_RequestCatalogStartupPose"
QUEUE_READY = "BPM_RequestCatalogStartupPoses"
RETRY_SECONDS = 0.1
WAIT_SECONDS = 10.0


def build_catalog():
    document = extract(CATALOG)
    editor = Blueprint(document)
    for field in [PENDING, OVERRIDE, SAVED_TICK, SAVED_ACTOR_TICK, INITIALIZED]:
        editor.bool_field(field)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    control = editor.imp("ControlPanel", astro)
    crack = editor.imp("CrackableActorComponent", astro)
    skel = editor.imp("SkeletalMeshComponent", engine)
    skinned = editor.imp("SkinnedMeshComponent", engine)
    scene = editor.imp("SceneComponent", engine)
    actor = editor.imp("Actor", engine)
    actor_component = editor.imp("ActorComponent", engine)
    anim_class = editor.imp("AnimInstance", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    negate = editor.imp("Not_PreBool", maths, "Function")
    equal = editor.imp("EqualEqual_ObjectObject", maths, "Function")
    closed = editor.imp("GetFullyClosed", crack, "Function")
    tick = editor.imp("SetComponentTickEnabled", actor_component, "Function")
    tick_enabled = editor.imp("IsComponentTickEnabled", actor_component, "Function")
    actor_tick = editor.imp("SetActorTickEnabled", actor, "Function")
    actor_tick_enabled = editor.imp("IsActorTickEnabled", actor, "Function")
    visible = editor.imp("IsVisible", scene, "Function")
    get_anim = editor.imp("GetAnimInstance", skel, "Function")
    set_timer = editor.imp("K2_SetTimer", system, "Function")
    clear_timer = editor.imp("K2_ClearTimer", system, "Function")
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
    evaluated = copy.deepcopy(
        next(
            p for p in editor.cls["LoadedProperties"] if "FObjectProperty" in p["$type"]
        )
    )
    evaluated.update(
        Name=editor.name(EVALUATED),
        PropertyClass=anim_class,
        PropertyFlags="CPF_Transient",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(evaluated)
    es(document)["Default__" + editor.cls["ObjectName"]]["Data"].append(
        prop(document, "Object", EVALUATED, 0)
    )
    editor.cls["CreateBeforeSerializationDependencies"].append(anim_class)
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
    current_anim = editor.ctx(mesh, editor.call(get_anim))

    def let(variable, value, field, owner):
        return editor.ex(
            "EX_Let",
            Value=editor.ptr(field, owner),
            Variable=variable,
            Expression=value,
        )

    def mark(value):
        return editor.ex(
            "EX_LetObj",
            VariableExpression=editor.var(EVALUATED),
            AssignmentExpression=value,
        )

    def timer(callback, seconds):
        return editor.call(
            set_timer,
            editor.ex("EX_Self"),
            editor.ex("EX_StringConst", Value=editor.name(callback)),
            editor.ex("EX_FloatConst", Value=seconds),
            editor.ex("EX_False"),
            editor.ex("EX_FloatConst", Value=0.0),
            editor.ex("EX_FloatConst", Value=0.0),
        )

    def clear(callback):
        return editor.call(
            clear_timer,
            editor.ex("EX_Self"),
            editor.ex("EX_StringConst", Value=editor.name(callback)),
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

    def completion_guards():
        return [
            editor.guard(editor.var(PENDING)),
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.guard(editor.call(valid, mesh)),
            editor.guard(editor.call(valid, editor.var(EVALUATED))),
            editor.guard(
                editor.call(equal, editor.var(EVALUATED), current_anim, math=True)
            ),
        ]

    restore = editor.function(
        "BPM_RestoreCatalogTickOption",
        [
            editor.guard(editor.var(OVERRIDE)),
            editor.call(actor_tick, editor.var(SAVED_ACTOR_TICK)),
            editor.assign_bool(OVERRIDE, editor.ex("EX_False")),
            editor.guard(editor.call(valid, mesh)),
            let(option, editor.var(SAVED), "VisibilityBasedAnimTickOption", skinned),
            editor.ctx(mesh, editor.call(tick, editor.var(SAVED_TICK))),
        ],
    )
    capture = editor.function(
        "BPM_CaptureCatalogTickOption",
        [
            editor.guard(editor.call(negate, editor.var(OVERRIDE), math=True)),
            let(editor.var(SAVED), option, SAVED, editor.cid),
            editor.assign_bool(SAVED_TICK, editor.ctx(mesh, editor.call(tick_enabled))),
            editor.assign_bool(SAVED_ACTOR_TICK, editor.call(actor_tick_enabled)),
            editor.assign_bool(OVERRIDE, editor.ex("EX_True")),
        ],
    )
    keep = editor.function(
        KEEP,
        [
            editor.guard(editor.var(PENDING)),
            editor.guard(editor.var(OVERRIDE)),
            editor.guard(editor.call(valid, mesh)),
            editor.assign_bool("ExtendTop", editor.ex("EX_True")),
            editor.assign_bool("ExtendPanel", editor.ex("EX_False")),
            let(
                option,
                editor.ex("EX_ByteConst", Value=0),
                "VisibilityBasedAnimTickOption",
                skinned,
            ),
            freeze(False),
            editor.call(actor_tick, editor.ex("EX_False")),
            editor.ctx(mesh, editor.call(tick, editor.ex("EX_True"))),
        ],
    )
    stop = editor.function(
        STOP,
        [
            *[clear(callback) for callback in [DEFER, TRY, FINISH, STOP]],
            editor.assign_bool(PENDING, editor.ex("EX_False")),
            editor.call(restore, local=True),
        ],
    )
    editor.function(
        FINISH,
        [
            *completion_guards(),
            freeze(True),
            editor.assign_bool(INITIALIZED, editor.ex("EX_True")),
            editor.call(stop, local=True),
        ],
    )
    queue_finish = editor.function(
        QUEUE_FINISH,
        [
            *completion_guards(),
            # The notify fires during animation update; freeze after bone evaluation.
            timer(FINISH, 0.01),
        ],
    )
    attempt = editor.function(
        TRY,
        [
            editor.guard(editor.var(PENDING)),
            # One finite readiness/retry path, regardless of recent rendering.
            timer(TRY, RETRY_SECONDS),
            editor.guard(editor.call(valid, mesh)),
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.guard(editor.ctx(mesh, editor.call(visible))),
            editor.guard(editor.call(valid, current_anim)),
            editor.call(capture, local=True),
            editor.call(keep, local=True),
            editor.call(queue_finish, local=True),
        ],
    )
    parent = editor.call(editor.imp("GetAttachParentActor", actor, "Function"))
    editor.function(
        DEFER,
        [
            editor.guard(editor.var(PENDING)),
            editor.call(attempt, local=True),
            editor.guard(editor.call(valid, parent)),
            editor.ctx(
                parent,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(QUEUE_READY),
                    Parameters=[],
                ),
            ),
        ],
    )
    start = editor.function(
        START,
        [
            editor.guard(editor.call(negate, editor.var(PENDING), math=True)),
            editor.assign_bool(PENDING, editor.ex("EX_True")),
            # Duplicate native events cannot extend this catalog's deadline.
            timer(STOP, WAIT_SECONDS),
            # Native BeginPlay disables the closed mesh after ReceiveBeginPlay.
            timer(DEFER, 0.01),
        ],
    )
    editor.function(
        READY_REQUEST,
        [
            editor.guard(editor.call(negate, editor.var(INITIALIZED), math=True)),
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.call(start, local=True),
        ],
    )
    editor.function(
        COMPLETE,
        [
            editor.guard(editor.call(valid, component)),
            editor.guard(editor.ctx(component, editor.call(closed))),
            editor.guard(editor.call(valid, mesh)),
            editor.guard(editor.call(valid, current_anim)),
            # Remember a native completion even if it precedes the close callback.
            mark(current_anim),
            editor.call(queue_finish, local=True),
        ],
    )

    def with_opened_parameter(label, make):
        fid = len(document["Exports"]) + 1
        field = copy.deepcopy(
            next(
                p
                for p in es(document)[STATE_EVENT]["LoadedProperties"]
                if p["Name"] == "bIsCracked"
            )
        )
        field["Name"] = editor.name("Opened")
        opened = editor.ex("EX_LocalVariable", Variable=editor.ptr("Opened", fid))
        assert editor.function(label, make(opened)) == fid
        fn = document["Exports"][fid - 1]
        fn["LoadedProperties"] = [field]
        fn["CreateBeforeSerializationDependencies"] = [
            dep for dep in fn["CreateBeforeSerializationDependencies"] if dep != fid
        ]
        return fid

    opening = with_opened_parameter(
        OPENED,
        lambda opened: [
            editor.guard(opened),
            mark(editor.ex("EX_NoObject")),
            editor.call(stop, local=True),
        ],
    )
    timeline = editor.imp("TimelineComponent", engine)
    stop_timeline = editor.imp("Stop", timeline, "Function")
    transition = editor.var("SpindleTransition")
    stop_opening = editor.function(
        "BPM_StopCatalogOpeningTimeline",
        [
            editor.guard(editor.call(valid, transition)),
            editor.ctx(transition, editor.call(stop_timeline)),
        ],
    )
    closing = with_opened_parameter(
        CLOSED,
        lambda opened: [
            editor.guard(editor.call(negate, opened, math=True)),
            editor.guard(editor.call(valid, component)),
            editor.call(stop_opening, local=True),
            # Native closed callbacks may freeze the mesh while correction is pending.
            editor.call(keep, local=True),
            editor.call(start, local=True),
        ],
    )

    def hook(event, fid, before=False, parameter=False):
        fn = es(document)[event]
        args = (
            [
                editor.ex(
                    "EX_LocalVariable",
                    Variable=editor.ptr(
                        "bIsCracked", document["Exports"].index(fn) + 1
                    ),
                )
            ]
            if parameter
            else []
        )
        call = editor.call(fid, *args, local=True)
        code = fn["ScriptBytecode"]
        at = (
            0
            if before
            else next(i for i, x in enumerate(code) if op_type(x) == "EX_Return")
        )
        code.insert(at, call)
        fn["ScriptBytecodeSize"] += kismet_size(call)
        fn["CreateBeforeSerializationDependencies"].append(fid)

    hook("ReceiveBeginPlay", start)
    hook(STATE_EVENT, opening, before=True, parameter=True)
    hook(STATE_EVENT, closing, parameter=True)
    hook(FULL_EVENT, closing, parameter=True)
    cracked = editor.imp("GetCracked", crack, "Function")
    for event in OPEN_EVENTS:
        wrapper = es(document)[event]
        native = copy.deepcopy(wrapper["ScriptBytecode"][0])
        helper = editor.function(
            "BPM_Catalog" + event.split("__")[1],
            [
                editor.guard(editor.call(valid, component)),
                editor.guard(editor.ctx(component, editor.call(cracked))),
                native,
            ],
        )
        call = editor.call(helper, local=True)
        wrapper["ScriptBytecode"][0] = call
        wrapper["ScriptBytecodeSize"] += kismet_size(call) - kismet_size(native)
        wrapper["CreateBeforeSerializationDependencies"].append(helper)
    return document
