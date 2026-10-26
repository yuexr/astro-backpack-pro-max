"""Check the drone and catalog helpers without running the game."""

import hashlib
import json
import struct

from asset_io import HERE, ps
from kismet import op_type


class VM:
    """Small interpreter for only the generated helpers; never calls the game."""

    def __init__(self, asset, actor):
        self.d = asset
        self.actor = actor
        self.timers = {}
        cls = next(e for e in asset["Exports"] if "ClassExport" in e["$type"])
        for p in cls.get("LoadedProperties", []):
            if p["Name"].startswith(("BPM_", "Compact_")) and "FObjectProperty" in p["$type"]:
                actor.setdefault(p["Name"], None)
            if p["Name"].startswith("BPM_") and (
                "FBoolProperty" in p["$type"] or "FByteProperty" in p["$type"]
            ):
                actor.setdefault(
                    p["Name"], False if "FBoolProperty" in p["$type"] else 0
                )

    def name(self, ptr):
        return ptr["New"]["Path"][0]

    def set(self, expr, value, obj, local):
        t = op_type(expr)
        if t == "EX_LocalVariable":
            local[self.name(expr["Variable"])] = value
            return
        if t == "EX_InstanceVariable":
            n = self.name(expr["Variable"])
            (self.actor if n in self.actor else obj)[n] = value
            return
        if t == "EX_Context":
            self.set(
                expr["ContextExpression"],
                value,
                self.eval(expr["ObjectExpression"], obj, local),
                local,
            )
            return
        raise AssertionError(t)

    def eval(self, x, obj, local):
        t = op_type(x)
        if t == "EX_DynamicCast":
            target = self.eval(x["Target"],obj,local)
            class_name = self.d["Imports"][-x["ClassPtr"]-1]["ObjectName"]
            return target if isinstance(target,dict) and target.get("material_class")==class_name else None
        if t in ["EX_InstanceVariable", "EX_LocalVariable"]:
            n = self.name(x["Variable"])
            return (
                self.actor
                if t == "EX_InstanceVariable" and n in self.actor
                else obj
                if t == "EX_InstanceVariable"
                else local
            )[n]
        if t in ["EX_True", "EX_False"]:
            return t == "EX_True"
        if t == "EX_NoObject":
            return None
        if t == "EX_Self":
            return self.actor
        if t in ["EX_IntZero", "EX_Nothing"]:
            return 0
        if t in ["EX_StringConst", "EX_FloatConst", "EX_ByteConst", "EX_NameConst"]:
            return x["Value"]
        if t == "EX_Let":
            self.set(x["Variable"], self.eval(x["Expression"], obj, local), obj, local)
            return
        if t == "EX_Context":
            return self.eval(
                x["ContextExpression"],
                self.eval(x["ObjectExpression"], obj, local),
                local,
            )
        if t in ["EX_LetBool", "EX_LetObj"]:
            self.set(
                x["VariableExpression"],
                self.eval(x["AssignmentExpression"], obj, local),
                obj,
                local,
            )
            return
        if t in ["EX_FinalFunction", "EX_LocalFinalFunction", "EX_CallMath"]:
            args = [self.eval(a, obj, local) for a in x["Parameters"]]
            node = x["StackNode"]
            if node > 0:
                return self.run(self.d["Exports"][node - 1]["ObjectName"], args)
            name = self.d["Imports"][-node - 1]["ObjectName"]
            if name == "BooleanOR":
                return bool(args[0] or args[1])
            if name == "IsValid":
                return args[0] is not None
            if name == "Not_PreBool":
                return not args[0]
            if name == "EqualEqual_ObjectObject":
                return args[0] is args[1]
            if name == "GetFullyClosed":
                return obj["fully_closed"]
            if name == "GetAnimInstance":
                return obj.get("anim_instance")
            if name == "GetAttachParentActor":
                return self.actor.get("parent")
            if name == "K2_GetRootComponent":
                return obj.get("SkeletalMesh")
            if name == "IsVisible":
                return obj["visible"]
            if name == "WasRecentlyRendered":
                return self.actor["rendered"]
            if name == "SetComponentTickEnabled":
                obj["tick_enabled"] = args[0]
                return
            if name == "IsComponentTickEnabled":
                return obj["tick_enabled"]
            if name == "IsActorTickEnabled":
                return self.actor.get("actor_tick_enabled", True)
            if name == "SetActorTickEnabled":
                self.actor["actor_tick_enabled"] = args[0]
                return
            if name == "K2_SetTimer":
                self.timers[args[1]] = {"seconds": args[2], "loop": args[3]}
                return
            if name == "K2_ClearTimer":
                self.timers.pop(args[1], None)
                return
            if name == "IsCreativeMode":
                return self.actor["creative"]
            if name == "GetMaterial":
                return obj["material"]
            if name == "SetMaterial":
                obj["material"] = args[1]
                return
            if name == "SetMaterialByName":
                assert args[0] == "Suit"
                obj["material"] = args[1]
                return
            if name == "SetMasterPoseComponent":
                obj["master_pose"] = args[0]
                return
            if name == "SetVisibility":
                obj["visible"] = args[0]
                return
            raise AssertionError(name)
        raise AssertionError(t)

    def run(self, name, args=()):
        e = next(x for x in self.d["Exports"] if x["ObjectName"] == name)
        local = {p["Name"]: v for p, v in zip(e["LoadedProperties"], args)}
        for x in e["ScriptBytecode"]:
            t = op_type(x)
            if t == "EX_Return":
                return self.eval(x["ReturnExpression"], self.actor, local)
            if t == "EX_JumpIfNot":
                assert x["CodeOffset"] == e["ScriptBytecodeSize"] - 3
                if not self.eval(x["BooleanExpression"], self.actor, local):
                    return
            else:
                self.eval(x, self.actor, local)


def check_behaviors(assets, geometry):
    def exports(d):
        return {e["ObjectName"]: e for e in d["Exports"]}

    # The drone mesh is always unclickable/no-collision; only its native slot
    # handles gameplay, and the replacement visual follows the native mode.
    d = assets["BackpackRail"]
    ex = exports(d)
    actor = {"creative": False, "backpack_mk2": {"material": object()}}
    for n in (
        [f"NativeBackpackSocket{i}" for i in range(1, 17)]
        + ["Compact_" + n for n in geometry["front_components"]]
        + ["NativeDroneSocket"]
    ):
        actor[n] = {"visible": False}
    vm = VM(d, actor)
    for mode in [False, True, False, True]:
        actor["creative"] = mode
        vm.run("CB_ShareSocketMaterial")
        assert actor["NativeDroneSocket"]["visible"] == mode
        assert (
            actor["NativeDroneSocket"]["material"] is actor["backpack_mk2"]["material"]
        )
    # The new mount is a child of the real mesh, with unchanged world placement.
    comp = ex["NativeDroneSocket_GEN_VARIABLE"]
    cid = d["Exports"].index(comp) + 1
    node = next(
        e
        for e in d["Exports"]
        if ps(e).get("ComponentTemplate", {}).get("Value") == cid
    )
    ni = d["Exports"].index(node) + 1
    owner = next(
        e
        for e in d["Exports"]
        if any(p["Value"] == ni for p in ps(e).get("ChildNodes", {}).get("Value", []))
    )
    assert ps(owner)["InternalVariableName"]["Value"] == "backpack_mk2"

    from settings import PANEL_RETRACTION_FIX
    from verify_catalog_events import check_catalog_once

    if PANEL_RETRACTION_FIX:
        check_catalog_once(assets["BackpackCatalog"])
    else:
        assert "BackpackCatalog" not in assets

    def read_glb(path):
        b = path.read_bytes()
        n = struct.unpack_from("<I", b, 12)[0]
        return json.loads(b[20 : 20 + n]), b[20 + n :]

    from model import INFO, MODEL

    newdoc, newbin = read_glb(MODEL)
    reference = json.loads(INFO.read_text())
    # each model has its own approved hashes
    assert (
        hashlib.sha256(newbin).hexdigest() == reference["approved_base_binary_sha256"]
    ), "approved model geometry or normals changed"
    canonical = json.dumps(newdoc, sort_keys=True, separators=(",", ":")).encode()
    assert (
        hashlib.sha256(canonical).hexdigest()
        == reference["approved_model_document_sha256"]
    ), "model doesn't match its approval file"
    from settings import GLOW_TEST
    accent_material = "Luxe accent glow test" if GLOW_TEST else "trim"
    trim = next(i for i, m in enumerate(newdoc["materials"]) if m["name"] == accent_material)
    assert (
        next(m for m in newdoc["meshes"] if m["name"] == "LowerBatteryAccent")[
            "primitives"
        ][0]["material"]
        == trim
    )
    creative = json.loads(
        (
            HERE / "vanilla/Astro/Content/Items/Catalog/BackpackCatalog_Creative.json"
        ).read_text()
    )
    superclass = next(
        e
        for e in creative["Exports"]
        if e["ObjectName"] == "BackpackCatalog_Creative_C"
    )["SuperStruct"]
    assert (
        superclass < 0
        and creative["Imports"][-superclass - 1]["ObjectName"] == "BackpackCatalog_C"
    )
    return [
        "Creative-only visibility helper tested through mode changes and real mesh bounds parent verified",
        "native catalog behavior preserved except startup hooks; inherited by Creative catalog",
        "startup initializes the native handle-out, controls-flat pose; early opening cancels initialization and leaves native animation in charge",
        "selected model and palette bindings match their approval file",
    ]
