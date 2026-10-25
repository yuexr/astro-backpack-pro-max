"""Keep auto arms out of the slots on carried equipment."""

import copy

from asset_io import es, prop
from blueprint import Blueprint
from game_assets import extract
from kismet import kismet_size, op_type

ITEMS = (
    "Astro/Content/Components_Small/Generator_Small",
    "Astro/Content/Components_Small/Smelter_Small",
    "Astro/Content/Components_Small/Printer_Breadboards_T1",
    # The hydrazine jetpack inherits its startup event from this Blueprint.
    "Astro/Content/Components_Small/Jetpacks/Jetpack_BASE",
)
PREFIX = "BPM_AutoArm"
RESTORE = PREFIX + "RestoreSlots"
BLOCK = PREFIX + "BlockSlots"
REFRESH = PREFIX + "RefreshSlots"
BIND = PREFIX + "BindSlots"
SAVED = PREFIX + "BlockedSlotNames"
EVENTS = {
    "OnPlacedInSlot": REFRESH,
    "OnSpawnedInSlot": REFRESH,
    # The release notification can arrive before CurrentSlot is cleared.
    "OnReleasedFromSlotClientSafe": RESTORE,
}


def patch_item(document):
    editor = Blueprint(document)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    physical = editor.imp("PhysicalItem", astro)
    slots = editor.imp("SlotsComponent", astro)
    slot = editor.imp("Slot", astro, "ScriptStruct")
    reference = editor.imp("SlotReference", astro, "ScriptStruct")
    component = editor.imp("ActorComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    arrays = editor.imp("KismetArrayLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    get_owner = editor.imp("GetOwner", component, "Function")
    length = editor.imp("Array_Length", arrays, "Function")
    contains = editor.imp("Array_Contains", arrays, "Function")
    add = editor.imp("Array_AddUnique", arrays, "Function")
    clear = editor.imp("Array_Clear", arrays, "Function")
    less = editor.imp("Less_IntInt", maths, "Function")
    plus = editor.imp("Add_IntInt", maths, "Function")
    either = editor.imp("BooleanOR", maths, "Function")
    carried_classes = []
    for asset, name in [
        ("/Game/Items/BackpackRail", "BackpackRail_C"),
        ("/Game/Components_Small/SmallDeform", "SmallDeform_C"),
    ]:
        package = editor.imp(asset, kind="Package")
        carried_classes.append(
            editor.imp(name, package, "BlueprintGeneratedClass", "/Script/Engine")
        )

    # Store only the slots we changed. Never enable a slot vanilla had disabled.
    schema = next(
        p
        for e in document["Exports"]
        for p in e.get("LoadedProperties", [])
        if "FArrayProperty" in p["$type"]
    )
    saved = copy.deepcopy(schema)
    inner = copy.deepcopy(schema["Inner"])
    inner.pop("Struct", None)
    inner.pop("PropertyClass", None)
    inner.update(
        {"$type": "UAssetAPI.FieldTypes.FGenericProperty, UAssetAPI"},
        Name=editor.name(SAVED),
        SerializedType="NameProperty",
        ElementSize=8,
        PropertyFlags="CPF_None",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    saved.update(
        Name=editor.name(SAVED),
        Inner=inner,
        PropertyFlags="CPF_Transient",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(saved)
    default = es(document)["Default__" + editor.cls["ObjectName"]]
    default["Data"].append(
        dict(
            prop(document, "Array", SAVED, []),
            ArrayType="NameProperty",
            DummyStruct=None,
        )
    )

    schemas = {
        kind: next(
            p
            for e in document["Exports"]
            for p in e.get("LoadedProperties", [])
            if p.get("SerializedType") == kind
        )
        for kind in ("IntProperty", "ObjectProperty")
    }

    def variable(owner, name, local=False):
        return editor.ex(
            "EX_LocalVariable" if local else "EX_InstanceVariable",
            Variable=editor.ptr(name, owner),
        )

    def member(owner, name, value):
        return editor.ex(
            "EX_StructMemberContext",
            StructMemberExpression=editor.ptr(name, owner),
            StructExpression=value,
        )

    def context(obj, value, owner, name):
        expression = editor.ctx(obj, value)
        expression["RValuePointer"] = editor.ptr(name, owner)
        return expression

    own = variable(physical, "SlotsComponent")
    inventory = context(own, variable(slots, "Slots"), slots, "Slots")

    def function(name, make, locals_=()):
        fid = len(document["Exports"]) + 1
        body, labels, jumps = make(fid)
        assert editor.function(name, body) == fid
        fn = document["Exports"][fid - 1]
        # Blueprint.function defaults guards to return. Resolve our loop branches.
        offsets = [0]
        for expression in fn["ScriptBytecode"]:
            offsets.append(offsets[-1] + kismet_size(expression))
        for index, label in jumps:
            fn["ScriptBytecode"][index]["CodeOffset"] = offsets[labels[label]]
        for label, kind, cls in locals_:
            field = copy.deepcopy(schemas[kind])
            field.update(
                Name=editor.name(label),
                PropertyFlags="CPF_None",
                RepIndex=0,
                RepNotifyFunc="None",
            )
            if cls:
                field["PropertyClass"] = cls
            fn["LoadedProperties"].append(field)
        fn["CreateBeforeSerializationDependencies"] = sorted(
            (set(fn["CreateBeforeSerializationDependencies"]) | {slots, physical})
            - {fid}
        )
        return fid

    def slot_loop(fid, restoring):
        index = variable(fid, "Index", True)
        row = editor.ex("EX_ArrayGetByRef", ArrayVariable=inventory, ArrayIndex=index)
        name = member(slot, "Name", row)
        accepts = member(slot, "bAcceptsInputItems", row)
        body = [
            editor.guard(editor.call(valid, own)),
            editor.ex(
                "EX_Let",
                Value=editor.ptr("Index", fid),
                Variable=index,
                Expression=editor.ex("EX_IntZero"),
            ),
        ]
        labels = {"loop": len(body)}
        body.append(
            editor.guard(editor.call(less, index, editor.call(length, inventory)))
        )
        jumps = [(len(body) - 1, "done")]
        body.append(
            editor.guard(
                editor.call(contains, editor.var(SAVED), name) if restoring else accepts
            )
        )
        jumps.append((len(body) - 1, "next"))
        if not restoring:
            body.append(editor.call(add, editor.var(SAVED), name))
        body.append(
            editor.ex(
                "EX_LetBool",
                VariableExpression=accepts,
                AssignmentExpression=editor.ex("EX_True" if restoring else "EX_False"),
            )
        )
        labels["next"] = len(body)
        body += [
            editor.ex(
                "EX_Let",
                Value=editor.ptr("Index", fid),
                Variable=index,
                Expression=editor.call(plus, index, editor.ex("EX_IntConst", Value=1)),
            ),
            editor.ex("EX_Jump", CodeOffset=0),
        ]
        jumps.append((len(body) - 1, "loop"))
        labels["done"] = len(body)
        if restoring:
            body.append(editor.call(clear, editor.var(SAVED)))
        return body, labels, jumps

    restore = function(
        RESTORE, lambda fid: slot_loop(fid, True), [("Index", "IntProperty", None)]
    )
    block = function(
        BLOCK, lambda fid: slot_loop(fid, False), [("Index", "IntProperty", None)]
    )

    def refresh(fid):
        carrying = variable(fid, "CarryingSlots", True)
        current = variable(physical, "CurrentSlot")
        owner = context(carrying, editor.call(get_owner), get_owner, "ReturnValue")
        checks = [
            editor.call(valid, editor.ex("EX_DynamicCast", ClassPtr=cls, Target=owner))
            for cls in carried_classes
        ]
        return (
            [
                editor.call(restore, local=True),
                editor.ex(
                    "EX_LetObj",
                    VariableExpression=carrying,
                    AssignmentExpression=member(reference, "Component", current),
                ),
                editor.guard(editor.call(valid, carrying)),
                editor.guard(editor.call(either, *checks)),
                editor.call(block, local=True),
            ],
            {},
            [],
        )

    refresh_id = function(
        REFRESH, refresh, [("CarryingSlots", "ObjectProperty", slots)]
    )

    def bind(_fid):
        body = []
        for event, handler in EVENTS.items():
            body.append(
                editor.ex(
                    "EX_AddMulticastDelegate",
                    Delegate=variable(physical, event),
                    DelegateToAdd=editor.ex(
                        "EX_InstanceDelegate", FunctionName=editor.name(handler)
                    ),
                )
            )
        body.append(editor.call(refresh_id, local=True))
        return body, {}, []

    bind_id = function(BIND, bind)
    begin = es(document)["ReceiveBeginPlay"]
    code = begin["ScriptBytecode"]
    index = next(
        i for i, expression in enumerate(code) if op_type(expression) == "EX_Return"
    )
    code.insert(index, editor.call(bind_id, local=True))
    begin["ScriptBytecodeSize"] = sum(map(kismet_size, code))
    begin["CreateBeforeSerializationDependencies"].append(bind_id)


def assets():
    result = []
    for path in ITEMS:
        document = extract(path)
        patch_item(document)
        result.append((path.rsplit("/", 1)[-1], document, path))
    return result
