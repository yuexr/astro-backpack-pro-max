"""auto-arm blocker for player slots and carried snails"""

import copy

from asset_io import es, ps, setbool
from blueprint import Blueprint
from game_assets import extract
from kismet import kismet_size, op_type

TOOL = "Astro/Content/Components_Small/SmallDeform"
SNAIL = "Astro/Content/Items/Snails/TerrariumSnail_CrackableActor"
PREFIX = "BPM_AutoArm"
ALLOW = PREFIX + "AllowFood"
BLOCK = PREFIX + "BlockFood"
REFRESH = PREFIX + "RefreshFood"
BIND = PREFIX + "BindFood"
EVENTS = {
    "OnPlacedInSlot": REFRESH,
    "OnSpawnedInSlot": REFRESH,
    # CurrentSlot can still be set during release, so allow feeding directly
    "OnReleasedFromSlotClientSafe": ALLOW,
}


def patch_backpack_slots(document):
    exports = es(document)
    for i in range(1, 17):
        setbool(
            document, exports[f"Item Slot {i}_GEN_VARIABLE"], "AcceptInputItems", False
        )
    aux = ps(exports["Slots_GEN_VARIABLE"])["Slots"]["Value"]
    assert len(aux) == 2
    for slot in aux:
        fields = ps({"Data": slot["Value"]})
        assert fields["Name"]["Value"] in ("Aux Slot Right", "Aux Slot Left")
        fields["bAcceptsInputItems"]["Value"] = False


def patch_tool(document):
    exports = es(document)
    for i in range(1, 4):
        setbool(
            document, exports[f"AugmentSlot{i}_GEN_VARIABLE"], "AcceptInputItems", False
        )


def patch_snail(document):
    """Update feeding when the snail is placed or removed."""
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    actor = editor.imp("Actor", engine)
    component = editor.imp("ActorComponent", engine)
    physical = editor.imp("PhysicalItem", astro)
    slots = editor.imp("SlotsComponent", astro)
    slot = editor.imp("Slot", astro, "ScriptStruct")
    reference = editor.imp("SlotReference", astro, "ScriptStruct")
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    arrays = editor.imp("KismetArrayLibrary", engine)
    package = editor.imp("/Game/Items/BackpackRail", kind="Package")
    backpack = editor.imp(
        "BackpackRail_C", package, "BlueprintGeneratedClass", "/Script/Engine"
    )
    get_parent = editor.imp("GetParentActor", actor, "Function")
    get_owner = editor.imp("GetOwner", component, "Function")
    valid = editor.imp("IsValid", system, "Function")
    equal = editor.imp("EqualEqual_NameName", maths, "Function")
    greater = editor.imp("Greater_IntInt", maths, "Function")
    length = editor.imp("Array_Length", arrays, "Function")

    def var(owner, field, local=False):
        return editor.ex(
            "EX_LocalVariable" if local else "EX_InstanceVariable",
            Variable=editor.ptr(field, owner),
        )

    def context(obj, expression, field=None, owner=None):
        expr = editor.ctx(obj, expression)
        if field:
            expr["RValuePointer"] = editor.ptr(field, owner)
        return expr

    def member(owner, field, value):
        return editor.ex(
            "EX_StructMemberContext",
            StructMemberExpression=editor.ptr(field, owner),
            StructExpression=value,
        )

    food_array = context(editor.var("Slots"), var(slots, "Slots"), "Slots", slots)
    food = editor.ex(
        "EX_ArrayGetByRef", ArrayVariable=food_array, ArrayIndex=editor.ex("EX_IntZero")
    )

    def feeding(allow):
        return [
            editor.guard(editor.call(valid, editor.var("Slots"))),
            editor.guard(
                editor.call(
                    greater, editor.call(length, food_array), editor.ex("EX_IntZero")
                )
            ),
            editor.guard(
                editor.call(
                    equal,
                    member(slot, "Name", food),
                    editor.ex("EX_NameConst", Value=editor.name("FoodSlot")),
                )
            ),
            editor.ex(
                "EX_LetBool",
                VariableExpression=member(slot, "bAcceptsInputItems", food),
                AssignmentExpression=editor.ex("EX_True" if allow else "EX_False"),
            ),
        ]

    allow = editor.function(ALLOW, feeding(True))
    block = editor.function(BLOCK, feeding(False))
    schema = next(
        p
        for e in document["Exports"]
        for p in e.get("LoadedProperties", [])
        if "FObjectProperty" in p["$type"]
    )

    def with_locals(label, make, fields):
        fid = len(document["Exports"]) + 1
        assert editor.function(label, make(fid)) == fid
        function = document["Exports"][fid - 1]
        for field, cls in fields:
            prop = copy.deepcopy(schema)
            prop.update(
                Name=editor.name(field),
                PropertyClass=cls,
                PropertyFlags="CPF_None",
                RepIndex=0,
                RepNotifyFunc="None",
            )
            function["LoadedProperties"].append(prop)
        dependencies = function["CreateBeforeSerializationDependencies"]
        function["CreateBeforeSerializationDependencies"] = sorted(
            (set(dependencies) | {physical, backpack} | {c for _, c in fields}) - {fid}
        )
        return fid

    def parent_assignment(fid):
        return editor.ex(
            "EX_LetObj",
            VariableExpression=var(fid, "ParentItem", True),
            AssignmentExpression=editor.ex(
                "EX_DynamicCast", ClassPtr=physical, Target=editor.call(get_parent)
            ),
        )

    def refresh(fid):
        parent = var(fid, "ParentItem", True)
        carrying = var(fid, "CarryingSlots", True)
        current = context(parent, var(physical, "CurrentSlot"), "CurrentSlot", physical)
        owner = context(carrying, editor.call(get_owner), "ReturnValue", get_owner)
        return [
            editor.call(allow, local=True),
            parent_assignment(fid),
            editor.guard(editor.call(valid, parent)),
            editor.ex(
                "EX_LetObj",
                VariableExpression=carrying,
                AssignmentExpression=member(reference, "Component", current),
            ),
            editor.guard(editor.call(valid, carrying)),
            editor.guard(
                editor.call(
                    valid, editor.ex("EX_DynamicCast", ClassPtr=backpack, Target=owner)
                )
            ),
            editor.call(block, local=True),
        ]

    refresh_id = with_locals(
        REFRESH, refresh, [("ParentItem", physical), ("CarryingSlots", slots)]
    )

    def bind(fid):
        parent = var(fid, "ParentItem", True)
        body = [parent_assignment(fid), editor.guard(editor.call(valid, parent))]
        for event, handler in EVENTS.items():
            body.append(
                editor.ex(
                    "EX_AddMulticastDelegate",
                    Delegate=context(parent, var(physical, event), event, physical),
                    DelegateToAdd=editor.ex(
                        "EX_InstanceDelegate", FunctionName=editor.name(handler)
                    ),
                )
            )
        body.append(editor.call(refresh_id, local=True))
        return body

    bind_id = with_locals(BIND, bind, [("ParentItem", physical)])
    begin = es(document)["ReceiveBeginPlay"]
    code = begin["ScriptBytecode"]
    index = next(i for i, expr in enumerate(code) if op_type(expr) == "EX_Return")
    code.insert(index, editor.call(bind_id, local=True))
    begin["ScriptBytecodeSize"] = sum(map(kismet_size, code))
    begin["CreateBeforeSerializationDependencies"].append(bind_id)


def assets():
    tool = extract(TOOL)
    patch_tool(tool)
    snail = extract(SNAIL)
    patch_snail(snail)
    return [
        ("SmallDeform", tool, TOOL),
        ("TerrariumSnail_CrackableActor", snail, SNAIL),
    ]
