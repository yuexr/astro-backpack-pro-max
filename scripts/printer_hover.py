"""Give the output hologram a mouse hit target while its tooltip is hover-only."""

import copy

from asset_io import es, prop
from game_assets import extract
from kismet import kismet_size

SYNC_HOVER = "BPM_SetPrinterHologramHover"
HOVER_COLLIDER = "BPM_PrinterHoverCollider"
SAVED_RESPONSE = "BPM_PrinterHoverResponse"
# Verified against Astroneer 1.45.1.0's CollisionProfile channel configuration.
CLICKABLE_CHANNEL = 16


def add_hover_helper(editor):
    engine = editor.imp("/Script/Engine", kind="Package")
    primitive = editor.imp("PrimitiveComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    equal_object = editor.imp("EqualEqual_ObjectObject", maths, "Function")
    equal_byte = editor.imp("EqualEqual_ByteByte", maths, "Function")
    negate = editor.imp("Not_PreBool", maths, "Function")
    both = editor.imp("BooleanAND", maths, "Function")
    get_collision = editor.imp("GetCollisionEnabled", primitive, "Function")
    set_collision = editor.imp("SetCollisionEnabled", primitive, "Function")
    get_response = editor.imp("GetCollisionResponseToChannel", primitive, "Function")
    set_response = editor.imp("SetCollisionResponseToChannel", primitive, "Function")
    native_view = es(editor.d)["CLIENT Printer View"]
    object_field = copy.deepcopy(
        next(
            p
            for p in native_view["LoadedProperties"]
            if p["Name"] == "PrinterOutputSlotTooltipComponent"
        )
    )
    object_field.update(
        Name=editor.name(HOVER_COLLIDER),
        PropertyClass=primitive,
        PropertyFlags="CPF_None",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(object_field)
    cdo = es(editor.d)["Default__" + editor.cls["ObjectName"]]
    cdo["Data"].append(prop(editor.d, "Object", HOVER_COLLIDER, 0))
    editor.cls["CreateBeforeSerializationDependencies"].append(primitive)
    donor = extract("Astro/Content/Items/Catalog/BackpackCatalog")
    donor_class = next(e for e in donor["Exports"] if "ClassExport" in e["$type"])
    byte = copy.deepcopy(
        next(
            p for p in donor_class["LoadedProperties"] if "FByteProperty" in p["$type"]
        )
    )
    editor.copy_names(donor, byte)
    byte.update(
        Name=editor.name(SAVED_RESPONSE),
        Enum=0,
        PropertyFlags="CPF_None",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    editor.cls["LoadedProperties"].append(byte)

    fid = len(editor.d["Exports"]) + 1
    collider = editor.ex("EX_LocalVariable", Variable=editor.ptr("Collider", fid))
    allow = editor.ex("EX_LocalVariable", Variable=editor.ptr("AllowHover", fid))

    def remember(value):
        return editor.ex(
            "EX_LetObj",
            VariableExpression=editor.var(HOVER_COLLIDER),
            AssignmentExpression=value,
        )

    def collision(target, value):
        return editor.ctx(
            target, editor.call(set_collision, editor.ex("EX_ByteConst", Value=value))
        )

    def response(target, value):
        return editor.ctx(
            target,
            editor.call(
                set_response, editor.ex("EX_ByteConst", Value=CLICKABLE_CHANNEL), value
            ),
        )

    saved_response = editor.ex(
        "EX_Let",
        Value=editor.ptr(SAVED_RESPONSE),
        Variable=editor.var(SAVED_RESPONSE),
        Expression=editor.ctx(
            collider,
            editor.call(
                get_response, editor.ex("EX_ByteConst", Value=CLICKABLE_CHANNEL)
            ),
        ),
    )

    already_enabled = editor.call(
        both,
        allow,
        editor.call(equal_object, collider, editor.var(HOVER_COLLIDER), math=True),
        math=True,
    )
    body = [
        editor.guard(editor.call(negate, already_enabled, math=True)),  # 0 -> return
        editor.guard(editor.call(valid, editor.var(HOVER_COLLIDER))),  # 1 -> clear
        collision(editor.var(HOVER_COLLIDER), 0),  # 2: restore the collider we changed
        response(editor.var(HOVER_COLLIDER), editor.var(SAVED_RESPONSE)),
        remember(editor.ex("EX_NoObject")),
        editor.guard(allow),
        editor.guard(editor.call(valid, collider)),
        editor.guard(
            editor.call(
                equal_byte,
                editor.ctx(collider, editor.call(get_collision)),
                editor.ex("EX_ByteConst", Value=0),
                math=True,
            )
        ),  # preserve any existing native collision setting
        saved_response,
        # QueryOnly alone still ignores the game's separate clickable trace.
        # Change only that channel, preserving every physics/slot response.
        response(collider, editor.ex("EX_ByteConst", Value=2)),
        collision(collider, 1),  # QueryOnly, never physics collision
        remember(collider),  # no repeated reconfiguration for the same hologram
    ]
    assert editor.function(SYNC_HOVER, body) == fid
    fn = editor.d["Exports"][fid - 1]
    fn["ScriptBytecode"][1]["CodeOffset"] = sum(
        map(kismet_size, fn["ScriptBytecode"][:4])
    )
    parameter = copy.deepcopy(object_field)
    parameter.update(Name=editor.name("Collider"), PropertyFlags="CPF_Parm")
    enabled = copy.deepcopy(
        next(
            p
            for p in editor.cls["LoadedProperties"]
            if p["Name"] == "BPM_PrinterTooltipHidden"
        )
    )
    enabled.update(Name=editor.name("AllowHover"), PropertyFlags="CPF_Parm")
    fn["LoadedProperties"] = [parameter, enabled]
    fn["CreateBeforeSerializationDependencies"] = sorted(
        (set(fn["CreateBeforeSerializationDependencies"]) | {primitive}) - {fid}
    )
    return fid
