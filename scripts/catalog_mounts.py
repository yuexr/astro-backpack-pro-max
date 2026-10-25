"""Copy the current backpack palette and request only the active child catalog."""

import copy

from asset_io import es
from blueprint import Blueprint
from catalog import QUEUE_READY, READY_REQUEST
from settings import PANEL_RETRACTION_FIX


def add_palette_copy(editor):
    document = editor.d
    engine = editor.imp("/Script/Engine", kind="Package")
    actor = editor.imp("Actor", engine)
    primitive = editor.imp("PrimitiveComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    valid = editor.imp("IsValid", system, "Function")
    root = editor.imp("K2_GetRootComponent", actor, "Function")
    get = editor.imp("GetMaterial", primitive, "Function")
    set_ = editor.imp("SetMaterialByName", primitive, "Function")
    fid = len(document["Exports"]) + 1
    child = editor.ex("EX_LocalVariable", Variable=editor.ptr("CatalogActor", fid))
    target = editor.ctx(child, editor.call(root))
    body = editor.var("backpack_mk2")
    material = editor.ctx(body, editor.call(get, editor.ex("EX_IntZero")))
    function = editor.function(
        "BPM_CopyCatalogPalette",
        [
            editor.guard(editor.call(valid, child)),
            editor.guard(editor.call(valid, body)),
            editor.guard(editor.call(valid, target)),
            editor.guard(editor.call(valid, material)),
            editor.ctx(
                target,
                editor.call(
                    set_,
                    editor.ex("EX_NameConst", Value=editor.name("Suit")),
                    material,
                ),
            ),
        ],
    )
    schema = copy.deepcopy(
        next(
            p
            for p in es(document)["CLIENT Printer View"]["LoadedProperties"]
            if p["Name"] == "PrinterOutputSlotTooltipComponent"
        )
    )
    schema.update(
        Name=editor.name("CatalogActor"),
        PropertyClass=actor,
        PropertyFlags="CPF_Parm",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    fn = document["Exports"][function - 1]
    fn["LoadedProperties"] = [schema]
    fn["CreateBeforeSerializationDependencies"] = sorted(
        (set(fn["CreateBeforeSerializationDependencies"]) | {actor}) - {function}
    )
    return function


def patch_catalog_mounts(document):
    """Native appearance and mode events can retry an unsettled active catalog."""
    editor = Blueprint(document)
    palette = add_palette_copy(editor)
    engine = editor.imp("/Script/Engine", kind="Package")
    astro = editor.imp("/Script/Astro", kind="Package")
    actor = editor.imp("Actor", engine)
    child_component = editor.imp("ChildActorComponent", engine)
    system = editor.imp("KismetSystemLibrary", engine)
    maths = editor.imp("KismetMathLibrary", engine)
    statics = editor.imp("AstroStatics", astro)
    valid = editor.imp("IsValid", system, "Function")
    negate = editor.imp("Not_PreBool", maths, "Function")
    creative = editor.imp("IsCreativeMode", statics, "Function")
    fid = len(document["Exports"]) + 1
    child = editor.ex("EX_LocalVariable", Variable=editor.ptr("CatalogActor", fid))
    apply_child = editor.function(
        "BPM_RequestCatalogChildStartup",
        [
            editor.call(palette, child, local=True),
            editor.guard(editor.call(valid, child)),
            editor.ctx(
                child,
                editor.ex(
                    "EX_VirtualFunction",
                    VirtualFunctionName=editor.name(READY_REQUEST),
                    Parameters=[],
                ),
            )
            if PANEL_RETRACTION_FIX
            else editor.ex("EX_Nothing"),
        ],
    )
    schema = copy.deepcopy(
        next(
            p
            for p in es(document)["CLIENT Printer View"]["LoadedProperties"]
            if p["Name"] == "PrinterOutputSlotTooltipComponent"
        )
    )
    schema.update(
        Name=editor.name("CatalogActor"),
        PropertyClass=actor,
        PropertyFlags="CPF_Parm",
        RepIndex=0,
        RepNotifyFunc="None",
    )
    fn = document["Exports"][apply_child - 1]
    fn["LoadedProperties"] = [schema]
    fn["CreateBeforeSerializationDependencies"] = sorted(
        (set(fn["CreateBeforeSerializationDependencies"]) | {actor}) - {apply_child}
    )
    requests = []
    for name, mode in [("Catalog", False), ("catalogCreative", True)]:
        active_mode = editor.call(creative, editor.ex("EX_Self"))
        child_actor = editor.ctx(
            editor.var(name),
            editor.ex(
                "EX_InstanceVariable",
                Variable=editor.ptr("ChildActor", child_component),
            ),
        )
        requests.append(
            editor.function(
                "BPM_Request" + ("Creative" if mode else "Regular") + "CatalogStartup",
                [
                    editor.guard(
                        active_mode
                        if mode
                        else editor.call(negate, active_mode, math=True)
                    ),
                    editor.guard(editor.call(valid, editor.var(name))),
                    editor.call(apply_child, child_actor, local=True),
                ],
            )
        )
    editor.function(
        QUEUE_READY, [editor.call(request, local=True) for request in requests]
    )
